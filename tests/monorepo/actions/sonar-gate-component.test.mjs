import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';
import {loadStep, root} from './action_test_support.mjs';

const action = 'ci/scan/sonarqube/quality-gate/action.yml';
const source = path.join(root, action);
const nativeRequire = createRequire(import.meta.url);
const document = () => JSON.parse(spawnSync('yq', ['-o=json', '-I=0', '.', source], {encoding:'utf8'}).stdout);
const project = 'cloudopsworks_repository_api', taskId = 'AY_Exact-Task', analysisId = 'AY_Exact-Analysis';
const token = 'secret-sentinel-never-log';
const metadata = `projectKey=${project}\nserverUrl=https://attacker.example\nceTaskId=${taskId}\nceTaskUrl=https://attacker.example/private\ndashboardUrl=https://attacker.example/dashboard\n`;
const ce = (status='SUCCESS', changes={}) => ({task:{id:taskId, type:'REPORT', componentKey:project, status, ...(status==='SUCCESS'?{analysisId}:{}), ...changes}});
const gate = (status='OK') => ({projectStatus:{status, conditions:[]}});
function fixture(t, changes={}) {
  const temp = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'v511-sonar-gate-')));
  t.after(()=>fs.rmSync(temp,{recursive:true,force:true}));
  const directory = fs.mkdtempSync(path.join(temp,'sonar-analysis-')); fs.chmodSync(directory,0o700);
  const started = Date.now()-1000;
  fs.writeFileSync(path.join(directory,'report-task.txt'),metadata,{mode:0o600});
  return {temp,directory,env:{COMPONENT_MODE:'true',RUNNER_TEMP:temp,METADATA_DIRECTORY:directory,
    ANALYSIS_STARTED_AT:String(started),PROJECT_KEY:project,SONAR_URL:'https://sonar.example/context',
    SONAR_TOKEN:token,...changes}};
}
// LOCAL test-only execution of the exact extracted current production body.
// HTTPS responses and clock deadlines are protocol doubles, not real analysis.
async function invoke(f, id, replies=[]) {
  const outputs={}, calls=[], logs=[], secrets=[], timers=[], cleared=[], cancellations=[];
  let now = Date.now(), requestTimer;
  const core = {setOutput:(k,v)=>outputs[k]=v,setSecret:v=>secrets.push(v),warning:v=>logs.push(v),info:v=>logs.push(v)};
  const setTimeout=(callback,delay)=>{
    const timer={callback,delay};timers.push(timer);
    if(delay===5000){now+=delay;queueMicrotask(callback);} else requestTimer=timer;
    return timer;
  };
  const clearTimeout=timer=>cleared.push(timer);
  class Clock extends Date {static now(){return now;}}
  const fetch=async(url,options)=>{
    calls.push({url:String(url),options});
    const reply=replies.shift();assert.notEqual(reply,undefined,'Unexpected HTTP request');
    if(reply.abortFetch){queueMicrotask(requestTimer.callback);return await new Promise(()=>{});}
    if(reply.error)throw new Error(reply.error);
    if(reply.abortBody){
      return {status:200,headers:new Headers({'content-type':'application/json'}),body:{getReader(){return {
        read(){queueMicrotask(requestTimer.callback);return new Promise(()=>{});},
        cancel(){cancellations.push(true);return Promise.resolve();},releaseLock(){},
      };}}};
    }
    if(reply.stream)return {status:reply.httpStatus||200,headers:new Headers(reply.headers||{'content-type':'application/json'}),body:reply.stream};
    return new Response(reply.bytes || (typeof reply.body==='string'?reply.body:JSON.stringify(reply)),
      {status:reply.httpStatus||200,headers:reply.headers||{'content-type':'application/json'}});
  };
  let error;
  try {
    const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
    await new AsyncFunction('process','core','fetch','require','setTimeout','clearTimeout','Date','performance',loadStep(action,id).script)(
      {env:f.env,getuid:()=>process.getuid()},core,fetch,name=>{
        assert.ok(['fs','path'].includes(name.replace(/^node:/,'')));return nativeRequire(name);
      },setTimeout,clearTimeout,Clock,{now:()=>now});
  } catch(caught){error=caught.message;}
  return {outputs,calls,logs,secrets,timers,cleared,cancellations,error,remaining:replies.length};
}
async function prepare(f){return await invoke(f,'component-metadata');}
async function poll(f,replies){
  const p=await prepare(f);assert.equal(p.error,undefined);
  return await invoke({...f,env:{...f.env,SERVER:p.outputs.server,TASK_ID:p.outputs['task-id']}},'component-gate',replies);
}

test('legacy defaults, output expression and official native gate body remain compatible',()=>{
  const d=document(), step=d.runs.steps.find(s=>s.name==='Sonar Scan Quality Gate Status');
  assert.deepEqual(Object.fromEntries(Object.entries(d.inputs).filter(([k])=>!['component-mode','metadata-directory','analysis-started-at','project-key'].includes(k))),{
    source_path:{description:'The path to the source code',required:false,default:'source'},
    blueprint_path:{description:'The path to the blueprint',required:false,default:'bp'},
    sonarqube_url:{description:'The Sonarqube URL',required:true},sonarqube_token:{description:'The Sonarqube token',required:true},
  });
  assert.equal(d.outputs.quality_gate_status.value,'${{ steps.sonarqube_quality_gate_status.outputs.quality_gate_status }}');
  assert.deepEqual({...step,if:undefined},{name:'Sonar Scan Quality Gate Status',uses:'sonarsource/sonarqube-quality-gate-action@master',
    env:{SONAR_TOKEN:'${{ inputs.sonarqube_token }}',SONAR_HOST_URL:'${{ inputs.sonarqube_url }}'},
    with:{scanMetadataReportFile:'${{ inputs.source_path }}/.scannerwork/report-task.txt'},if:undefined});
  assert.equal(step.if,"inputs.component-mode != 'true'");
  assert.equal(d.inputs['component-mode'].default,'false');
});
test('new steps use v9 and component branches only, without executable custom helpers',()=>{
  const d=document();assert.equal(d.runs.steps[0].id,'mode');
  for(const id of ['mode','component-metadata','component-gate']){
    const step=d.runs.steps.find(s=>s.id===id);assert.equal(step.uses,'actions/github-script@v9');
    assert.ok(!step.with.script.includes('${{'));
    if(id!=='mode')assert.equal(step.if,"inputs.component-mode == 'true'");
    assert.ok(step.with.script.split('\n').filter(l=>l.trim()&&!l.trim().startsWith('//')).length<=120);
  }
  assert.equal(d.runs.steps.find(s=>s.id==='component-metadata').env.SONAR_TOKEN,undefined);
});
for(const value of ['true','false'])test(`global mode validation accepts ${value}`,async t=>{
  const r=await invoke(fixture(t,{COMPONENT_MODE:value}),'mode');assert.equal(r.error,undefined);assert.equal(r.calls.length,0);
});
for(const value of ['', 'TRUE','1','false; echo injected'])test(`global mode rejects ${JSON.stringify(value)}`,async t=>{
  const r=await invoke(fixture(t,{COMPONENT_MODE:value}),'mode');assert.equal(r.error,'sonar-component-mode');
});
test('fresh private exact metadata binds task and configured host/context, ignoring metadata URLs',async t=>{
  const r=await prepare(fixture(t));assert.equal(r.error,undefined);
  assert.deepEqual(r.outputs,{'task-id':taskId,server:'https://sonar.example/context'});assert.equal(r.calls.length,0);
});
for(const host of ['https://sonar.example','https://sonar.example/','https://sonar.example/sonar/','https://sonar.example:8443/sonar'])test(`trusted host ${host}`,async t=>{
  const r=await prepare(fixture(t,{SONAR_URL:host}));assert.equal(r.error,undefined);
  assert.equal(r.outputs.server,host.replace(/\/$/,''));
});
for(const host of ['http://sonar.example','https://user:password@sonar.example','https://sonar.example/?x=1','https://sonar.example/#hash',
  'https://sonar.example/a/../b','https://sonar.example/%2felse','https://sonar.example\\else',' https://sonar.example','https://sonar.example//bad'])test(`reject unsafe host ${host}`,async t=>{
  const r=await prepare(fixture(t,{SONAR_URL:host}));assert.equal(r.error,'sonar-component-metadata');assert.equal(r.calls.length,0);
});
const badMetadata={missingTask:`projectKey=${project}\n`,wrongProject:`projectKey=other\nceTaskId=${taskId}\n`,
 duplicateTask:`${metadata}ceTaskId=other\n`,duplicateProject:`${metadata}projectKey=${project}\n`,
 emptyTask:`projectKey=${project}\nceTaskId=\n`,unsafeTask:`projectKey=${project}\nceTaskId=task&project=other\n`,
 control:`${metadata}\0`,malformed:`${metadata}not-a-property\n`,empty:'',oversize:'x'.repeat(16385)};
for(const [name,body]of Object.entries(badMetadata))test(`metadata rejects ${name}`,async t=>{
  const f=fixture(t);fs.writeFileSync(path.join(f.directory,'report-task.txt'),body);
  const r=await prepare(f);assert.equal(r.error,'sonar-component-metadata');assert.deepEqual(r.outputs,{});assert.equal(r.calls.length,0);
});
for(const kind of ['file-symlink','directory-symlink','outside-private-tree','insecure-directory','hardlink','fifo','missing','stale','future-start','bad-start','relative-directory'])test(`metadata rejects ${kind}`,async t=>{
  const f=fixture(t), file=path.join(f.directory,'report-task.txt');
  if(kind==='file-symlink'){fs.renameSync(file,file+'.original');fs.symlinkSync(file+'.original',file);}
  if(kind==='directory-symlink'){const linked=path.join(f.temp,'sonar-analysis-linked');fs.symlinkSync(f.directory,linked);f.env.METADATA_DIRECTORY=linked;}
  if(kind==='outside-private-tree'){f.env.RUNNER_TEMP=fs.mkdtempSync(path.join(f.temp,'other-'));}
  if(kind==='insecure-directory')fs.chmodSync(f.directory,0o755);
  if(kind==='hardlink')fs.linkSync(file,file+'.link');
  if(kind==='fifo'){fs.rmSync(file);assert.equal(spawnSync('mkfifo',[file]).status,0);}
  if(kind==='missing')fs.rmSync(file);
  if(kind==='stale')fs.utimesSync(file,new Date(1),new Date(1));
  if(kind==='future-start')f.env.ANALYSIS_STARTED_AT=String(Date.now()+60000);
  if(kind==='bad-start')f.env.ANALYSIS_STARTED_AT='1e3';
  if(kind==='relative-directory')f.env.METADATA_DIRECTORY=path.relative(process.cwd(),f.directory);
  const r=await prepare(f);assert.equal(r.error,'sonar-component-metadata');assert.deepEqual(r.outputs,{});assert.equal(r.calls.length,0);
});
test('completed exact task uses only its exact analysis quality query and token header',async t=>{
  const r=await poll(fixture(t),[ce(),gate()]);assert.equal(r.error,undefined);
  assert.deepEqual(r.outputs,{'component-status':'passed','component-quality-gate-status':'OK','task-id':taskId,'analysis-id':analysisId,'error-code':''});
  assert.deepEqual(r.calls.map(c=>c.url),[`https://sonar.example/context/api/ce/task?id=${taskId}`,`https://sonar.example/context/api/qualitygates/project_status?analysisId=${analysisId}`]);
  for(const c of r.calls){assert.equal(c.options.headers.Authorization,`Bearer ${token}`);assert.equal(c.options.redirect,'error');assert.equal(c.options.credentials,'omit');assert.equal(c.options.method,'GET');}
  assert.deepEqual(r.secrets,[token]);assert.ok(!JSON.stringify([r.outputs,r.logs,r.error]).includes(token));assert.equal(r.timers.length,2);assert.equal(r.cleared.length,2);
});
test('pending/in-progress are polled to exact completed analysis, never treated as success',async t=>{
  const r=await poll(fixture(t),[ce('PENDING'),ce('IN_PROGRESS'),ce(),gate()]);
  assert.equal(r.outputs['component-status'],'passed');assert.equal(r.calls.length,4);assert.equal(r.timers.filter(x=>x.delay===5000).length,2);
});
for(const [quality,status] of [['ERROR','gate-failed'],['WARN','gate-warning'],['NONE','no-gate']])test(`completed ${quality} is ${status}, not passed`,async t=>{
  const r=await poll(fixture(t),[ce(),gate(quality)]);assert.equal(r.error,undefined);assert.equal(r.outputs['component-status'],status);assert.equal(r.outputs['component-quality-gate-status'],quality);
});
const invalidTasks={failed:ce('FAILED'),canceled:ce('CANCELED'),unknown:ce('READY'),wrongTask:ce('SUCCESS',{id:'other'}),
 wrongComponent:ce('SUCCESS',{componentKey:'other'}),wrongType:ce('SUCCESS',{type:'ISSUE_SYNC'}),missingAnalysis:ce('SUCCESS',{analysisId:undefined}),
 invalidAnalysis:ce('SUCCESS',{analysisId:'analysis&project=other'}),nullTask:{task:null},array:[],errors:{errors:[{msg:'secret-error'}]},
 missingComponent:ce('SUCCESS',{componentKey:undefined})};
for(const [name,reply]of Object.entries(invalidTasks))test(`CE rejects ${name}`,async t=>{
  const r=await poll(fixture(t),[reply]);assert.equal(r.error,undefined);assert.equal(r.outputs['component-status'],'infrastructure-error');assert.equal(r.calls.length,1);
  assert.ok(!r.outputs['component-quality-gate-status']);assert.ok(!r.outputs['analysis-id']);assert.ok(!JSON.stringify(r.logs).includes('secret-error'));
});
for(const reply of [{},gate('UNKNOWN'),{projectStatus:null},{projectStatus:[]},{errors:[{msg:token}],...gate()}])test(`invalid gate ${JSON.stringify(reply)} is not passed`,async t=>{
  const r=await poll(fixture(t),[ce(),reply]);assert.equal(r.outputs['component-status'],'infrastructure-error');assert.ok(!r.outputs['component-quality-gate-status']);assert.ok(!JSON.stringify(r.outputs).includes(token));
});
for(const reply of [{httpStatus:401,body:token},{httpStatus:403,body:token},{httpStatus:302,body:token},
 {body:'not-json'},{body:'null'},{body:'{}',headers:{'content-type':'text/html'}},{body:'{}',headers:{'content-type':'application/json','content-length':'1048577'}},
 {error:token},{abortFetch:true},{abortBody:true}])test(`HTTP/transport denial ${JSON.stringify(reply)}`,async t=>{
  const r=await poll(fixture(t),[reply]);assert.equal(r.error,undefined);assert.equal(r.outputs['component-status'],'infrastructure-error');assert.equal(r.calls.length,1);
  assert.ok(!JSON.stringify([r.outputs,r.logs]).includes(token));assert.equal(r.cleared.length,1);
  if(reply.abortBody)assert.equal(r.cancellations.length,1);
});
test('actual streamed overrun without Content-Length cancels and never passes',async t=>{
  let cancelled=false;
  const stream=new ReadableStream({pull(controller){controller.enqueue(new Uint8Array(65536));},cancel(){cancelled=true;}});
  const r=await poll(fixture(t),[{stream}]);assert.equal(r.outputs['component-status'],'infrastructure-error');assert.equal(cancelled,true);assert.equal(r.calls.length,1);
});
test('rejected HTTP headers cancel the unread response body',async t=>{
  let cancelled=false;
  const stream=new ReadableStream({pull(controller){controller.enqueue(new Uint8Array(16));},cancel(){cancelled=true;}});
  const r=await poll(fixture(t),[{stream,httpStatus:401}]);
  assert.equal(r.outputs['component-status'],'infrastructure-error');assert.equal(cancelled,true);
});
test('invalid UTF-8 response fails without exposing bytes',async t=>{
  const r=await poll(fixture(t),[{bytes:new Uint8Array([0xc0,0x80])}]);
  assert.equal(r.outputs['component-status'],'infrastructure-error');assert.equal(r.outputs['error-code'],'sonar-analysis-unavailable');
});
test('invalid UTF-8 metadata fails before any request',async t=>{
  const f=fixture(t);fs.writeFileSync(path.join(f.directory,'report-task.txt'),new Uint8Array([0xc0,0x80]));
  const r=await prepare(f);assert.equal(r.error,'sonar-component-metadata');assert.equal(r.calls.length,0);
});
test('quality response timeout cannot retain a completed analysis as a passing gate',async t=>{
  const r=await poll(fixture(t),[ce(),{abortBody:true}]);
  assert.equal(r.outputs['component-status'],'infrastructure-error');assert.equal(r.outputs['component-quality-gate-status'],'');
  assert.ok(!r.outputs['analysis-id']);assert.equal(r.calls.length,2);assert.equal(r.cancellations.length,1);
});
test('perpetually pending analysis hits fixed total deadline without a quality request',async t=>{
  const r=await poll(fixture(t),Array.from({length:70},()=>ce('PENDING')));
  assert.equal(r.outputs['component-status'],'infrastructure-error');assert.ok(r.calls.length<=60);assert.ok(r.calls.every(c=>c.url.includes('/ce/task?')));
  assert.ok(r.timers.every(x=>x.delay<=10000));
});
for(const badToken of ['', 'bad\nvalue',' bad', 'x'.repeat(8193)])test(`invalid token length ${badToken.length} never sent`,async t=>{
  const r=await poll(fixture(t,{SONAR_TOKEN:badToken}),[]);assert.equal(r.outputs['component-status'],'infrastructure-error');assert.equal(r.calls.length,0);
});
