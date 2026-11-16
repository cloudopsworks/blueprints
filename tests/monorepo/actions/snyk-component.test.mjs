import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {root, runStep, loadStep} from './action_test_support.mjs';
const action = 'ci/scan/snyk/action.yml';
const cli = process.env.TRONADOR_CLI || '/tmp/tronador-v511-python-prep';
const digest = 'sha256:' + 'c'.repeat(64);
function fixture(t, profile = 'npm') {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'snyk-component-')));
  t.after(() => fs.rmSync(root, {recursive: true, force: true}));
  const source = path.join(root, 'components/api');
  fs.mkdirSync(source, {recursive: true});
  const manifests = {npm:'package.json', pnpm:'package.json', yarn:'package.json', go:'go.mod', maven:'pom.xml', gradle:'build.gradle', dotnet:'app.csproj', python:'requirements.txt', bundler:'Gemfile', rails:'Gemfile', cargo:'Cargo.toml'};
  fs.writeFileSync(path.join(source, manifests[profile]), '{}');
  const relative = '.cloudopsworks/out/api/main.zip';
  fs.mkdirSync(path.dirname(path.join(root, relative)), {recursive: true});
  fs.writeFileSync(path.join(root, relative), 'payload');
  const plan = {headSha:'a'.repeat(40), components:[{id:'api', path:'components/api', buildProfile:profile}], buildSelection:[{componentId:'api'}]};
  const record = {componentId:'api', headSha:plan.headSha, status:'succeeded', mainArtifact:{digest, location:{kind:'local', path:relative}}};
  for (const name of ['plan', 'result']) fs.writeFileSync(path.join(root, name+'.json'), '{}');
  const env = {SOURCE_PATH:root, PLAN_PATH:path.join(root,'plan.json'), COMPONENT_RESULT:path.join(root,'result.json'), COMPONENT:'api', SOURCE_SHA:plan.headSha, TRUSTED:'true', SNYK_TOKEN:'scan-canary', RUNNER_TEMP:root};
  const tools = [
    {prefix:['components','contracts','validate','--kind','BuildPlan'], result:{stdout:JSON.stringify({record:plan})}},
    {prefix:['components','contracts','validate','--kind','ComponentResult'], result:{stdout:JSON.stringify({record})}},
    {prefix:['components','artifacts','verify'], result:{stdout:JSON.stringify({payloadVerified:true,digest})}},
    {command:'git', result:{stdout:plan.headSha+'\n'}},
  ];
  return {root, source, plan, record, env, tools, manifest:manifests[profile]};
}
function prepare(f) { return runStep(action, 'prepare', f); }
function report(f, prepared, content, exit = '0', code = '') {
  if (content !== undefined) fs.writeFileSync(path.join(prepared.outputs.directory, 'snyk.json'), typeof content === 'string' ? content : JSON.stringify(content), {mode:0o600});
  const env = {DIRECTORY:prepared.outputs.directory, NATIVE_EXIT:exit, NATIVE_ERROR:code,NATIVE_MANIFEST:f.manifest};
  const r = runStep(action, 'report', {env, realCli:cli});
  return {...r, record:r.calls[0]?.input && JSON.parse(r.calls[0].input)};
}
const clean = {ok:true, vulnerabilities:[]};
for (const profile of ['npm','pnpm','yarn','go','maven','gradle','dotnet','python','bundler','rails']) {
  for (const findings of [false,true]) test(`${profile}: real YAML prepares exact manifest and normalizes ${findings?'findings':'clean'}`, t => {
    const f = fixture(t, profile), p = prepare(f);
    assert.equal(p.error, undefined, JSON.stringify(p));
    assert.equal(p.outputs.manifest, profile==='dotnet'?'':f.manifest);
    assert.equal(p.outputs.decision, 'ready');
    const r = report(f,p,{ok:!findings,vulnerabilities:findings?[{id:'SNYK-example',severity:'high'}]:[],packageManager:p.outputs.manager,targetFile:f.manifest},findings?'1':'0');
    assert.equal(r.error, undefined, JSON.stringify(r));
    assert.equal(r.outputs.status, findings?'findings-advisory':'passed');
    assert.equal(r.record.required,false); assert.equal(r.record.artifactDigest,digest);
    assert.equal(r.record.componentId,'api'); assert.equal(r.record.sourceSha,f.plan.headSha);
    assert.equal(r.record.profile,profile); assert.match(r.record.correlationId,/^scan-[a-f0-9]{32}$/);
    assert.equal(fs.statSync(p.outputs.directory).mode&0o777,0o700);
    assert.equal(fs.statSync(r.outputs.result).mode&0o777,0o600);
    const again = report(f,p,undefined,findings?'1':'0'); assert.ok(again.error,'exclusive result file');
  });
}
for (const [name,content,exit] of [
  ['missing',undefined,'0'],['empty','','0'],['malformed','{','0'],['null',null,'0'],['empty array',[],'0'],
  ['error',{error:'raw-secret-canary'},'0'],['mixed partial',[clean,{error:'raw-secret-canary'}],'0'],
  ['inconsistent ok',{ok:true,vulnerabilities:[{id:'x'}]},'0'],['inconsistent exit',clean,'1'],
  ['invalid vulnerability',{ok:false,vulnerabilities:[{}]},'1'],['huge',' '.repeat(16*1024*1024+1),'0'],
]) test(`never clean: ${name}`, t => {
  const f=fixture(t),p=prepare(f),r=report(f,p,content,exit);
  assert.equal(r.error,undefined,JSON.stringify(r)); assert.equal(r.outputs.status,'infrastructure-error');
  assert.equal(JSON.stringify(r).includes('raw-secret-canary'),false);
});
for (const [exit,status,code] of [['2','infrastructure-error','snyk-tool-error'],['3','unsupported-profile','snyk-no-supported-project'],['124','infrastructure-error','snyk-timeout'],['137','infrastructure-error','snyk-tool-signal'],['9','infrastructure-error','snyk-tool-exit']]) test(`native exit ${exit} is classified`, t=>{
  const f=fixture(t),p=prepare(f),r=report(f,p,clean,exit);
  assert.equal(r.outputs.status,status); assert.equal(r.record.errorCode,code);
});
for (const [name,change,decision] of [
  ['untrusted',f=>f.env.TRUSTED='false','snyk-untrusted-source'],
  ['missing token',f=>delete f.env.SNYK_TOKEN,'snyk-missing-credential'],
  ['Cargo',()=>{},'snyk-cargo-test-unsupported'],
]) test(`no execution authorization: ${name}`,t=>{
  const f=fixture(t,name==='Cargo'?'cargo':'npm');change(f);const p=prepare(f);
  assert.equal(p.error,undefined,JSON.stringify(p));assert.equal(p.outputs.decision,decision);
  const r=report(f,p,undefined);assert.notEqual(r.outputs.status,'passed');
});
for (const [name,change] of [
  ['source traversal',f=>f.plan.components[0].path='../outside'],
  ['artifact traversal',f=>f.record.mainArtifact.location.path='.cloudopsworks/out/../other'],
  ['wrong source SHA',f=>f.record.headSha='b'.repeat(40)],
  ['wrong component',f=>f.record.componentId='other'],
  ['not selected',f=>f.plan.buildSelection=[]],
  ['manifest symlink',f=>{fs.unlinkSync(path.join(f.source,'package.json'));fs.symlinkSync('/etc/passwd',path.join(f.source,'package.json'));}],
  ['source symlink',f=>{fs.renameSync(f.source,f.source+'-actual');fs.symlinkSync(f.source+'-actual',f.source);}],
  ['payload symlink',f=>{const p=path.join(f.root,f.record.mainArtifact.location.path);fs.unlinkSync(p);fs.symlinkSync('/etc/passwd',p);}],
]) test(`prepare fails closed: ${name}`,t=>{
  const f=fixture(t);change(f);f.tools[0].result.stdout=JSON.stringify({record:f.plan});f.tools[1].result.stdout=JSON.stringify({record:f.record});
  const r=prepare(f);assert.ok(r.error,JSON.stringify(r));assert.equal(r.outputs.directory,undefined);
});
test('report rejects symlink and nonregular files without reading target',t=>{
  const f=fixture(t),p=prepare(f);fs.symlinkSync('/etc/passwd',path.join(p.outputs.directory,'snyk.json'));
  assert.equal(report(f,p,undefined).outputs.status,'infrastructure-error');
});
test('report fails closed when installed CLI rejects ScannerResult',t=>{
  const f=fixture(t),p=prepare(f);fs.writeFileSync(path.join(p.outputs.directory,'snyk.json'),JSON.stringify(clean));
  const r=runStep(action,'report',{env:{DIRECTORY:p.outputs.directory,NATIVE_EXIT:'0'},tools:[{result:{exitCode:1,stderr:'raw-secret-canary'}}]});
  assert.ok(r.error);assert.equal(r.outputs.result,undefined);assert.equal(JSON.stringify(r).includes('raw-secret-canary'),false);
});
test('only bounded production inline bodies, with no generic dispatcher',()=>{
  for(const id of ['prepare','report']) assert.ok(loadStep(action,id).script.split('\n').length<=121);
});
for (const [lock,manifest,manager] of [['poetry.lock','pyproject.toml','poetry'],['Pipfile.lock','Pipfile','pip']]) test(`Python ${lock} retains finite native selection`,t=>{
  const f=fixture(t,'python');fs.writeFileSync(path.join(f.source,lock),'');fs.writeFileSync(path.join(f.source,manifest),'{}');
  const p=prepare(f);assert.equal(p.error,undefined,JSON.stringify(p));assert.equal(p.outputs.manifest,manifest);assert.equal(p.outputs.manager,manager);
});
test('Gradle Kotlin manifest is selected when Groovy manifest absent',t=>{
  const f=fixture(t,'gradle');fs.renameSync(path.join(f.source,'build.gradle'),path.join(f.source,'build.gradle.kts'));
  const p=prepare(f);assert.equal(p.error,undefined,JSON.stringify(p));assert.equal(p.outputs.manifest,'build.gradle.kts');
});
for (const [name,row] of [
  ['foreign manager',{...clean,packageManager:'maven'}],
  ['foreign path',{...clean,packageManager:'npm',path:'/elsewhere'}],
  ['target traversal',{...clean,packageManager:'npm',targetFile:'../outside'}],
  ['absolute target',{...clean,packageManager:'npm',targetFile:'/etc/passwd'}],
  ['absent target',{...clean,packageManager:'npm',targetFile:'missing.json'}],
  ['explicit error code',{...clean,packageManager:'npm',errorCode:'SNYK-FAIL'}],
]) test(`report identity/coverage rejects ${name}`,t=>{
  const f=fixture(t),p=prepare(f);assert.equal(report(f,p,row).outputs.status,'infrastructure-error');
});
test('.NET plugin-reported restored child assets are not confused with selected solution identity',t=>{
  const f=fixture(t,'dotnet'),p=prepare(f);fs.mkdirSync(path.join(f.source,'obj'));fs.writeFileSync(path.join(f.source,'obj/project.assets.json'),'{}');
  const r=report(f,p,{...clean,packageManager:'nuget',targetFile:'obj/project.assets.json'});
  assert.equal(r.outputs.status,'passed',JSON.stringify(r));
});
test('valid multi-row report requires every row complete and all findings consistent with exit',t=>{
  const f=fixture(t),p=prepare(f),row={...clean,packageManager:'npm',targetFile:'package.json'};
  assert.equal(report(f,p,[row,{...row,ok:false,vulnerabilities:[{id:'SNYK-real-shape',severity:'medium'}]}],'1').outputs.status,'findings-advisory');
});
for(const mode of ['world-readable','directory','hardlink']) test(`report file boundary rejects ${mode}`,t=>{
  const f=fixture(t),p=prepare(f),file=path.join(p.outputs.directory,'snyk.json');
  if(mode==='directory')fs.mkdirSync(file);
  else {fs.writeFileSync(file,JSON.stringify({...clean,packageManager:'npm'}),{mode:mode==='world-readable'?0o644:0o600});if(mode==='hardlink')fs.linkSync(file,path.join(f.root,'linked-report'));}
  assert.equal(report(f,p,undefined).outputs.status,'infrastructure-error');
});
for (const mutation of ['none','result-source','artifact-bytes']) test(`actual offline CLI validates linked BuildPlan/ComponentResult and payload: ${mutation}`,t=>{
  const f=fixture(t,'go');
  const base=new URL('../../../../tronador-cli-v511/internal/components/testdata/contracts/',import.meta.url);
  const plan=JSON.parse(fs.readFileSync(new URL('valid/build-plan.json',base)));
  const result=JSON.parse(fs.readFileSync(new URL('valid/oci-image-valid.json',base)));
  const payload=path.join(f.root,result.mainArtifact.location.path);fs.mkdirSync(path.dirname(payload),{recursive:true});
  fs.copyFileSync(new URL('artifacts/image.oci.tar',base),payload);
  if(mutation==='result-source')result.headSha='b'.repeat(40);
  if(mutation==='artifact-bytes')fs.appendFileSync(payload,'corruption');
  fs.writeFileSync(f.env.PLAN_PATH,JSON.stringify(plan));fs.writeFileSync(f.env.COMPONENT_RESULT,JSON.stringify(result));
  const r=runStep(action,'prepare',{env:f.env,realCli:cli,tools:[{command:'git',result:{stdout:plan.headSha+'\n'}}]});
  if(mutation==='none'){assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs.decision,'ready');assert.equal(r.calls.filter(c=>c.command==='tronador').length,3);}
  else {assert.ok(r.error,JSON.stringify(r));assert.equal(r.outputs.directory,undefined);}
});
for(const [name,change] of [
  ['wrong plan source',f=>f.plan.headSha='b'.repeat(40)],
  ['wrong git source',f=>f.tools[3].result.stdout='b'.repeat(40)],
  ['payload not verified',f=>f.tools[2].result.stdout=JSON.stringify({payloadVerified:false,digest})],
  ['payload wrong digest',f=>f.tools[2].result.stdout=JSON.stringify({payloadVerified:true,digest:'sha256:'+'d'.repeat(64)})],
  ['plan validator failure',f=>f.tools[0].result={exitCode:1,stderr:'raw-secret-canary'}],
  ['result validator failure',f=>f.tools[1].result={exitCode:1,stderr:'raw-secret-canary'}],
])test(`prepare rejects ${name} before exposing an executable scan`,t=>{
  const f=fixture(t);change(f);
  if(name==='wrong plan source')f.tools[0].result.stdout=JSON.stringify({record:f.plan});
  const p=prepare(f);assert.ok(p.error,JSON.stringify(p));assert.equal(p.outputs.directory,undefined);
  assert.equal(JSON.stringify(p).includes('raw-secret-canary'),false);
});
test('unknown native diagnostic is normalized rather than reflected into result/logs',t=>{
  const f=fixture(t),p=prepare(f),r=report(f,p,undefined,'0','raw-secret-canary');
  assert.equal(r.record.errorCode,'snyk-tool-error');assert.equal(JSON.stringify(r).includes('raw-secret-canary'),false);
});
test('same source/identity/report produces deterministic typed ScannerResult bytes',t=>{
  const f=fixture(t),p1=prepare(f),p2=prepare(f),row={...clean,packageManager:'npm',targetFile:'package.json'};
  const r1=report(f,p1,row),r2=report(f,p2,row);
  assert.deepEqual(fs.readFileSync(r1.outputs.result),fs.readFileSync(r2.outputs.result));
});

test('native original HEAD is bound from validated prepare output and bounded at lifecycle seams',()=>{
 const parsed=JSON.parse(spawnSync('yq',['-o=json','-I=0','.',path.join(root,'ci/scan/snyk/action.yml')],{encoding:'utf8'}).stdout),scan=parsed.runs.steps.find(s=>s.id==='scan');
 assert.equal(scan.env.SOURCE_SHA,'${{ steps.prepare.outputs.source-sha }}');
 assert.match(scan.run,/timeout --kill-after=10s 30s git -C/);assert.match(scan.run,/head -c 42/);assert.match(scan.run,/head_codes=\("\$\{PIPESTATUS\[@\]\}"\)/);
 assert.ok(scan.run.indexOf('check_head prepared')<scan.run.indexOf('export SNYK_TOKEN=$token'));

 assert.ok(scan.run.lastIndexOf('check_head completed')<scan.run.indexOf("printf 'exit=%s"));
});
