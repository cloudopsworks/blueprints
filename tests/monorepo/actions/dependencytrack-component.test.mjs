import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';
import {loadStep, root} from './action_test_support.mjs';

const action = 'ci/nodejs/scan/dtrack/action.yml';
const source = path.join(root, action);
const document = () => JSON.parse(spawnSync('yq', ['-o=json', '-I=0', '.', source], {encoding:'utf8'}).stdout);
const uuid = '12345678-1234-4234-8234-123456789abc';
const server = 'https://dependencytrack.example';
const nativeRequire = createRequire(import.meta.url);
const bom = JSON.stringify({bomFormat:'CycloneDX', specVersion:'1.5', version:1, components:[]});
function response(value, options={}) {
  return {body:JSON.stringify(value), status:200, headers:{'content-type':'application/json'}, ...options};
}
function fixture(t, changes={}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'v511-dtrack-'));
  t.after(() => fs.rmSync(directory, {recursive:true, force:true}));
  fs.writeFileSync(path.join(directory, 'bom.json'), bom);
  return {directory, env:{COMPONENT_MODE:'true', SOURCE_PATH:directory, BOM_PATH:'bom.json',
    DTRACK_URL:server, DTRACK_TOKEN:'secret-sentinel', PROJECT_NAME:'example/repository:api',
    PROJECT_VERSION:'1.2.3', ...changes}};
}
// Test-only invocation of the current extracted body. Timers and HTTP are finite
// doubles; no product code or separate scanner implementation is imported.
async function invoke(f, replies=[response({version:'4.14.6'}), response({token:uuid}), response({processing:false})], id='component') {
  const script = loadStep(action, id).script;
  const outputs={}, calls=[], logs=[], timers=[], cleared=[], callbacks=[];
  const core={setOutput:(key,value)=>outputs[key]=value, setSecret:()=>{},
    summary:{addRaw(value){logs.push(value);return this;},async write(){}},
    info:value=>logs.push(value), warning:value=>logs.push(value)};
  const fetch=async (url, options)=>{
    calls.push({url:String(url), ...options});
    const reply=replies.shift();assert.ok(reply, 'Unexpected HTTP request');
    if(reply.abortFetch) {
      queueMicrotask(callbacks.at(-1));
      return await new Promise((_,reject)=>options.signal.addEventListener('abort',()=>reject(new Error('private request deadline')), {once:true}));
    }
    if(reply.abortBody)queueMicrotask(callbacks.at(-1));
    if(reply.error)throw new Error(reply.error);
    if(reply.stream)return {status:reply.status||200, headers:new Headers(reply.headers||{}), body:reply.stream};
    return new Response(reply.body||'', {status:reply.status||200, headers:reply.headers||{}});
  };
  const setTimeout=(callback, delay)=>{
    const id=timers.length+1;timers.push(delay);callbacks.push(callback);if(delay===5000)callback();return id;
  };
  const clearTimeout=id=>cleared.push(id);
  const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
  let error;
  try {
    await new AsyncFunction('process','core','fetch','require','setTimeout','clearTimeout',script)(
      {env:f.env},core,fetch,name=>{
        assert.ok(['fs','path','crypto'].includes(name.replace(/^node:/,'')));
        return nativeRequire(name);
      },setTimeout,clearTimeout);
  } catch(caught) {error=caught.message;}
  return {outputs,calls,logs,timers,cleared,error,remaining:replies.length};
}
test('legacy upload body and default inputs remain unchanged',()=>{
  const d=document(), s=d.runs.steps.find(step=>step.name==='SBOM Dtrack Upload');
  assert.equal(d.inputs.source_path.default,'source');assert.equal(d.inputs.blueprint_path.default,'bp');
  for(const key of ['dtrack_url','dtrack_token','dtrack_project_key','semver','token'])assert.equal(d.inputs[key].required,true);
  assert.equal(createHash('sha256').update(s.run+'\n').digest('hex'),'282b17a8d4342b61c23057a33d1dbf5303b78d149aba5cf46eb5feceeb710157');
  assert.equal(s['working-directory'],'${{ inputs.source_path }}');
});
test('actual legacy body preserves curl argv, BOM filename and source cwd',t=>{
  const f=fixture(t), bin=path.join(f.directory,'bin');fs.mkdirSync(bin);
  fs.writeFileSync(path.join(bin,'curl'),'#!/bin/sh\nprintf "%s\\0" "$@" > "$CAPTURE"\npwd > "$CWD_FILE"\n',{mode:0o755});
  const s=document().runs.steps.find(step=>step.name==='SBOM Dtrack Upload');
  const r=spawnSync('/bin/bash',['-e','-c',s.run],{cwd:f.directory,encoding:'utf8',env:{PATH:bin+':/bin',
    CAPTURE:path.join(f.directory,'args'),CWD_FILE:path.join(f.directory,'cwd'),
    INPUTS_DTRACK_URL:'server.example',INPUTS_DTRACK_TOKEN:'token',INPUTS_DTRACK_PROJECT_KEY:'project $(touch injected)',INPUTS_SEMVER:'1.2.3'}});
  assert.equal(r.status,0,r.stderr);
  const args=fs.readFileSync(path.join(f.directory,'args'),'utf8').split('\0').slice(0,-1);
  assert.deepEqual(args,['-X','POST','https://server.example/api/v1/bom','-H','Content-Type: multipart/form-data','-H','X-API-Key: token',
    '-F','autoCreate=true','-F','projectName=project $(touch injected)','-F','projectVersion=1.2.3','-F','bom=@bom.xml']);
  assert.equal(fs.readFileSync(path.join(f.directory,'cwd'),'utf8').trim(),fs.realpathSync(f.directory));
  assert.equal(fs.existsSync(path.join(f.directory,'injected')),false);
});
test('component mode is opt-in and never reports a clean vulnerability verdict',()=>{
  const d=document();assert.equal(d.inputs['component-mode'].default,'false');
  assert.equal(d.inputs['bom-path'].default,'bom.json');
  assert.equal(d.runs.steps.find(s=>s.id==='component').if,"inputs.component-mode == 'true'");
  assert.equal(d.runs.steps.find(s=>s.name==='SBOM Dtrack Upload').if,"inputs.component-mode != 'true'");
  assert.deepEqual(Object.keys(d.outputs).sort(),['bom-digest','status','uploaded']);
  assert.ok(!loadStep(action,'component').script.includes('${{'));
  assert.equal(d.runs.steps[0].id,'mode');
});
for(const value of ['true','false'])test(`global mode check admits ${value}`,async t=>{
  const r=await invoke(fixture(t,{COMPONENT_MODE:value}),[],'mode');assert.equal(r.error,undefined);assert.equal(r.calls.length,0);
});
test('global mode check rejects invalid values before either upload branch',async t=>{
  const r=await invoke(fixture(t,{COMPONENT_MODE:'invalid'}),[],'mode');assert.ok(r.error);assert.equal(r.calls.length,0);
});
test('actual component body uploads bounded bytes and polls only its returned token',async t=>{
  const f=fixture(t), r=await invoke(f,[response({version:'4.11.0'}),response({token:uuid}),response({processing:true}),response({processing:false})]);
  assert.equal(r.error,undefined);assert.equal(r.remaining,0);
  assert.deepEqual(r.calls.map(c=>[c.url,c.method]),[[server+'/api/version','GET'],[server+'/api/v1/bom','PUT'],
    [server+'/api/v1/event/token/'+uuid,'GET'],[server+'/api/v1/event/token/'+uuid,'GET']]);
  const upload=JSON.parse(r.calls[1].body);
  assert.deepEqual(upload,{autoCreate:true,projectName:f.env.PROJECT_NAME,projectVersion:'1.2.3',bom:Buffer.from(bom).toString('base64')});
  for(const c of r.calls){assert.equal(c.redirect,'error');assert.equal(c.credentials,'omit');assert.ok(c.signal instanceof AbortSignal);assert.equal(c.headers['X-Api-Key'],'secret-sentinel');}
  assert.deepEqual(r.outputs,{uploaded:'true',status:'processed','bom-digest':'sha256:'+createHash('sha256').update(bom).digest('hex')});
  assert.equal(r.timers.filter(n=>n===5000).length,1);assert.equal(r.timers.filter(n=>n===10000).length,4);
  assert.match(r.logs.join(' '),/not a vulnerability verdict/);assert.ok(!JSON.stringify(r.outputs).includes(uuid));
});
for(const [name,changes] of [
  ['HTTP server',{DTRACK_URL:'http://dependencytrack.example'}],['URL credentials',{DTRACK_URL:'https://user:password@dependencytrack.example'}],
  ['query',{DTRACK_URL:server+'?token=secret'}],['fragment',{DTRACK_URL:server+'#x'}],['path',{DTRACK_URL:server+'/unreviewed'}],
  ['blank token',{DTRACK_TOKEN:''}],['header injection',{DTRACK_TOKEN:'token\r\nX-Evil: value'}],
  ['project injection',{PROJECT_NAME:'example\nforged'}],['blank project',{PROJECT_NAME:''}],['blank version',{PROJECT_VERSION:''}],
  ['path traversal',{BOM_PATH:'../outside.json'}],['absolute BOM',{BOM_PATH:'/etc/passwd'}],['unknown mode',{COMPONENT_MODE:'invalid'}],
])test(`component denies ${name} before HTTP`,async t=>{
  const r=await invoke(fixture(t,changes),[]);assert.ok(r.error);assert.deepEqual(r.outputs,{});assert.equal(r.calls.length,0);
});
for(const [name,make] of [
  ['missing BOM',f=>fs.unlinkSync(path.join(f.directory,'bom.json'))],
  ['empty BOM',f=>fs.writeFileSync(path.join(f.directory,'bom.json'),'')],
  ['invalid JSON',f=>fs.writeFileSync(path.join(f.directory,'bom.json'),'{')],
  ['non-CycloneDX JSON',f=>fs.writeFileSync(path.join(f.directory,'bom.json'),'{}')],
  ['oversized BOM',f=>fs.writeFileSync(path.join(f.directory,'bom.json'),Buffer.alloc(8*1024*1024+1))],
  ['symlink BOM',f=>{fs.renameSync(path.join(f.directory,'bom.json'),path.join(f.directory,'other.json'));fs.symlinkSync('other.json',path.join(f.directory,'bom.json'));}],
  ['symlink directory',f=>{fs.mkdirSync(path.join(f.directory,'sub'));fs.writeFileSync(path.join(f.directory,'sub','bom.json'),bom);fs.symlinkSync('sub',path.join(f.directory,'alias'));f.env.BOM_PATH='alias/bom.json';}],
  ['directory BOM',f=>{fs.unlinkSync(path.join(f.directory,'bom.json'));fs.mkdirSync(path.join(f.directory,'bom.json'));}],
])test(`component denies ${name} before HTTP`,async t=>{
  const f=fixture(t);make(f);const r=await invoke(f,[]);assert.ok(r.error);assert.deepEqual(r.outputs,{});assert.equal(r.calls.length,0);
});
for(const version of ['4.10.9','5.0.0','not-a-version',[],null])test(`unsupported API ${JSON.stringify(version)} denies before upload`,async t=>{
  const r=await invoke(fixture(t),[response({version})]);assert.ok(r.error);assert.equal(r.calls.length,1);assert.deepEqual(r.outputs,{});
});
for(const token of [undefined,'other-token',uuid.toUpperCase(),[],null,'00000000-0000-0000-0000-000000000000'])test(`invalid returned token ${JSON.stringify(token)} never polls`,async t=>{
  const r=await invoke(fixture(t),[response({version:'4.14.6'}),response({token})]);assert.ok(r.error);assert.equal(r.calls.length,2);assert.deepEqual(r.outputs,{});
});
for(const value of [{processing:'false'},{processing:null},{processing:false,token:'other-token'},{processing:false,status:'FAILED'},null,[]])test(`malformed or contradictory processing ${JSON.stringify(value)} cannot succeed`,async t=>{
  const r=await invoke(fixture(t),[response({version:'4.14.6'}),response({token:uuid}),response(value)]);assert.ok(r.error);assert.notEqual(r.outputs.status,'processed');
});
test('polling times out after twelve exact-token requests without success',async t=>{
  const r=await invoke(fixture(t),[response({version:'4.14.6'}),response({token:uuid}),...Array.from({length:12},()=>response({processing:true}))]);
  assert.match(r.error,/dtrack-processing-timeout/);assert.equal(r.calls.length,14);assert.equal(r.remaining,0);
  assert.equal(r.timers.filter(n=>n===5000).length,11);assert.notEqual(r.outputs.status,'processed');
});
for(const [name,reply] of [
  ['HTTP denial',response({secret:'do-not-log'},{status:403})],['redirect',response({}, {status:302,headers:{location:'https://attacker.invalid'}})],
  ['invalid JSON',{body:'not JSON',headers:{'content-type':'application/json'}}],
  ['advertised oversized response',{body:'{}',headers:{'content-type':'application/json','content-length':'65537'}}],
  ['chunked oversized response',{body:'x'.repeat(65537),headers:{'content-type':'application/json'}}],
  ['request timeout',{error:'private-token secret-sentinel timeout'}],
])test(`${name} fails closed with generic redacted error`,async t=>{
  const r=await invoke(fixture(t),[reply]);assert.ok(r.error);assert.deepEqual(r.outputs,{});assert.equal(r.calls.length,1);
  assert.ok(!r.error.includes('secret-sentinel'));assert.ok(!r.error.includes('do-not-log'));
  assert.equal(r.cleared.length,1);
});
test('XML envelope is accepted only without DTD/entity declarations',async t=>{
  const f=fixture(t,{BOM_PATH:'bom.xml'});fs.writeFileSync(path.join(f.directory,'bom.xml'),'<bom xmlns="http://cyclonedx.org/schema/bom/1.5" version="1"><components/></bom>');
  assert.equal((await invoke(f)).error,undefined);
  fs.writeFileSync(path.join(f.directory,'bom.xml'),'<!DOCTYPE bom [<!ENTITY secret SYSTEM "file:///etc/passwd">]><bom xmlns="http://cyclonedx.org/schema/bom/1.5">&secret;</bom>');
  const r=await invoke(f,[]);assert.ok(r.error);assert.equal(r.calls.length,0);
});
test('fixed request deadline aborts a hanging fetch without raw error leakage',async t=>{
  const r=await invoke(fixture(t),[{abortFetch:true}]);
  assert.equal(r.error,'dtrack-request-or-input');assert.equal(r.calls.length,1);assert.equal(r.cleared.length,1);assert.deepEqual(r.outputs,{});
});
test('fixed deadline also interrupts a hanging response body and cancels it',async t=>{
  let cancelled=false;
  const stream={getReader:()=>({read:()=>new Promise(()=>{}),cancel:async()=>{cancelled=true;},releaseLock(){}})};
  const r=await invoke(fixture(t),[{stream,abortBody:true,headers:{'content-type':'application/json'}}]);
  assert.equal(r.error,'dtrack-request-or-input');assert.equal(cancelled,true);assert.equal(r.cleared.length,1);assert.deepEqual(r.outputs,{});
});
for(const version of ['4.12.0','4.13.0'])test(`released API ${version} uses the same finite processing route`,async t=>{
  const r=await invoke(fixture(t),[response({version}),response({token:uuid}),response({processing:false})]);assert.equal(r.error,undefined);assert.equal(r.outputs.status,'processed');
});
