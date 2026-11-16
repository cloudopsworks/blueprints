import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {root,runStep,loadStep} from './action_test_support.mjs';
const action='ci/scan/sonarqube/component/action.yml';
const cli=process.env.TRONADOR_CLI||'/tmp/tronador-v511-python-prep';
const digest='sha256:'+'c'.repeat(64);
const doc=p=>JSON.parse(spawnSync('yq',['-o=json','-I=0','.',path.join(root,p)],{encoding:'utf8'}).stdout);
function fixture(t,changes={}){
 const directory=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'sonar-dotnet-test-')));t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
 const source=path.join(directory,'components/api');fs.mkdirSync(source,{recursive:true});fs.writeFileSync(path.join(source,'selected.csproj'),'');
 const relative='.cloudopsworks/out/api/main.zip';fs.mkdirSync(path.dirname(path.join(directory,relative)),{recursive:true});fs.writeFileSync(path.join(directory,relative),'payload');
 const plan={headSha:'a'.repeat(40),version:'1.2.3',components:[{id:'api',path:'components/api',language:'go',buildProfile:'go'}],buildSelection:[{componentId:'api'}]};
 const record={componentId:'api',headSha:plan.headSha,status:'succeeded',mainArtifact:{digest,location:{kind:'local',path:relative}}};
 for(const name of ['plan','result'])fs.writeFileSync(path.join(directory,name+'.json'),'{}');
 const env={SOURCE_PATH:directory,PLAN_PATH:path.join(directory,'plan.json'),COMPONENT_RESULT:path.join(directory,'result.json'),COMPONENT:'api',SOURCE_SHA:plan.headSha,TRUSTED:'true',CREDENTIAL_PRESENT:'true',RUNNER_TEMP:directory,SONAR_URL:'https://sonar.example/context',PROJECT_KEY:'repository:api',VERSION:'1.2.3',QUALITY_GATE_ENABLED:'true',FAIL_ON_QUALITY_GATE:'true',...changes};
 const tools=[{prefix:['components','contracts','validate','--kind','BuildPlan'],result:{stdout:JSON.stringify({record:plan})}},{prefix:['components','contracts','validate','--kind','ComponentResult'],result:{stdout:JSON.stringify({record})}},{prefix:['components','artifacts','verify'],result:{stdout:JSON.stringify({payloadVerified:true,digest})}},{command:'git',result:{stdout:plan.headSha+'\n'}}];
 return{directory,source,plan,record,env,tools};
}
function prepare(f){return runStep(action,'prepare',f);}
function report(p,gate='passed',changes={}){
 const env={DIRECTORY:p.outputs.directory,NATIVE_STATUS:'uploaded',NATIVE_ERROR:'',GATE_STATUS:gate,GATE_QUALITY:({passed:'OK','gate-failed':'ERROR','gate-warning':'WARN','no-gate':'NONE'})[gate]||'',TASK_ID:'AY_Exact-Task',ANALYSIS_ID:'AY_Exact-Analysis',...changes};
 const r=runStep(action,'report',{env,realCli:cli});return{...r,record:r.calls[0]?.input&&JSON.parse(r.calls[0].input)};
}
test('new named component action uses frozen correlated gate and no source helper',()=>{
 const d=doc(action),g=d.runs.steps.find(s=>s.id==='gate');assert.equal(g.uses,'./bp/ci/scan/sonarqube/quality-gate');assert.equal(g.with['component-mode'],'true');
 assert.equal(g.with['metadata-directory'],'${{ steps.prepare.outputs.metadata-directory }}');assert.equal(g.if,"steps.scan.outputs.status == 'uploaded'");
 for(const id of ['prepare','report']){assert.ok(loadStep(action,id).script.split('\n').filter(l=>l.trim()&&!l.trim().startsWith('//')).length<=120);}
 for(const s of d.runs.steps.filter(s=>s.run))assert.ok(!s.run.includes('ulimit'));
});
test('prepare binds typed source/result/main artifact and private identity',t=>{
 const f=fixture(t),p=prepare(f);assert.equal(p.error,undefined,JSON.stringify(p));assert.equal(p.outputs.decision,'ready');assert.equal(p.outputs.source,f.source);
 assert.equal(p.outputs.version,f.plan.version);assert.equal(fs.statSync(p.outputs['metadata-directory']).mode&0o777,0o700);
 assert.equal(fs.existsSync(path.join(p.outputs['metadata-directory'],'report-task.txt')),false);
 assert.equal(path.dirname(p.outputs['metadata-directory']),f.directory);assert.match(path.basename(p.outputs['metadata-directory']),/^sonar-analysis-/);
 assert.ok(p.calls.every(c=>!c.env?.SONAR_TOKEN&&!c.env?.AWS_ACCESS_KEY_ID));
 const r=report(p);assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs.status,'passed');assert.equal(r.record.scanner,'sonar');assert.equal(r.record.profile,'go');assert.equal(r.record.artifactDigest,digest);assert.equal(r.record.required,true);
});
for(const [name,change]of [
 ['component traversal',f=>f.plan.components[0].path='../outside'],['wrong profile',f=>f.plan.components[0].buildProfile='dotnet'],['not selected',f=>f.plan.buildSelection=[]],
 ['wrong source',f=>f.plan.headSha='b'.repeat(40)],['wrong result',f=>f.record.componentId='other'],['wrong result source',f=>f.record.headSha='b'.repeat(40)],['failed result',f=>f.record.status='failed'],
 ['artifact traversal',f=>f.record.mainArtifact.location.path='.cloudopsworks/out/../bad'],['payload symlink',f=>{const p=path.join(f.directory,f.record.mainArtifact.location.path);fs.unlinkSync(p);fs.symlinkSync('/etc/passwd',p);}],[ 'source symlink',f=>{fs.renameSync(f.source,f.source+'-actual');fs.symlinkSync(f.source+'-actual',f.source);}],
 ['invalid URL',f=>f.env.SONAR_URL='https://attacker@sonar.example'],['invalid context',f=>f.env.SONAR_URL='https://sonar.example/a/../b'],['version mismatch',f=>f.env.VERSION='2.0.0'],['invalid project key',f=>f.env.PROJECT_KEY='project\nkey'],['invalid boolean',f=>f.env.QUALITY_GATE_ENABLED='1'],
])test(`prepare denies ${name}`,t=>{const f=fixture(t);change(f);f.tools[0].result.stdout=JSON.stringify({record:f.plan});f.tools[1].result.stdout=JSON.stringify({record:f.record});const p=prepare(f);assert.ok(p.error,JSON.stringify(p));assert.equal(p.outputs.directory,undefined);});
for(const [name,change]of [['wrong git',f=>f.tools[3].result.stdout='b'.repeat(40)],['unverified payload',f=>f.tools[2].result.stdout=JSON.stringify({payloadVerified:false,digest})],['different payload',f=>f.tools[2].result.stdout=JSON.stringify({payloadVerified:true,digest:'sha256:'+'d'.repeat(64)})]])test(`prepare rejects ${name}`,t=>{const f=fixture(t);change(f);assert.ok(prepare(f).error);});
for(const [changes,decision,status]of [[{TRUSTED:'false'},'sonar-untrusted-source','unavailable-untrusted-context'],[{CREDENTIAL_PRESENT:'false'},'sonar-missing-credential','infrastructure-error']])test(`no secret execution for ${decision}`,t=>{const p=prepare(fixture(t,changes));assert.equal(p.error,undefined,JSON.stringify(p));assert.equal(p.outputs.decision,decision);assert.equal(report(p).outputs.status,status);});
for(const gate of ['passed','gate-failed','gate-warning','no-gate','infrastructure-error',''])for(const required of [false,true])test(`gate ${gate||'missing'} required=${required} follows current policy`,t=>{
 const p=prepare(fixture(t,{FAIL_ON_QUALITY_GATE:String(required)}));const r=report(p,gate);assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.record.required,required);
 const expected=gate==='passed'?'passed':['gate-failed','gate-warning'].includes(gate)?required?'required-gate-failure':'findings-advisory':gate==='no-gate'?'unsupported-profile':'infrastructure-error';assert.equal(r.outputs.status,expected);
});
test('disabled quality gate still requires completed analysis; no-gate completed analysis can pass',t=>{
 for(const [gate,status]of [['no-gate','passed'],['infrastructure-error','infrastructure-error'],['','infrastructure-error']]){const p=prepare(fixture(t,{QUALITY_GATE_ENABLED:'false',FAIL_ON_QUALITY_GATE:'true'}));const r=report(p,gate);assert.equal(r.record.required,false);assert.equal(r.outputs.status,status);}
});
for(const change of [{NATIVE_STATUS:'',NATIVE_ERROR:''},{NATIVE_STATUS:'',NATIVE_ERROR:'sonar-begin-failed'},{TASK_ID:''},{ANALYSIS_ID:''},{GATE_QUALITY:'ERROR'}])test(`incomplete native/gate evidence cannot pass ${JSON.stringify(change)}`,t=>{const p=prepare(fixture(t));assert.equal(report(p,'passed',change).outputs.status,'infrastructure-error');});
test('raw native error is never reflected into result',t=>{const p=prepare(fixture(t));const r=report(p,'',{NATIVE_ERROR:'secret-canary'});assert.equal(r.outputs.status,'infrastructure-error');assert.equal(JSON.stringify(r).includes('secret-canary'),false);});
test('same deterministic component/source/artifact gives stable correlation; typed result exclusive',t=>{
 const f=fixture(t),p1=prepare(f),p2=prepare(f),r1=report(p1),r2=report(p2);assert.equal(r1.record.correlationId,r2.record.correlationId);assert.match(r1.record.correlationId,/^scan-[a-f0-9]{32}$/);assert.equal(fs.statSync(r1.outputs.result).mode&0o777,0o600);assert.ok(report(p1).error);
});
for(const mutation of ['none','result-source','artifact-bytes'])test(`real offline CLI validates CLI plan/result/artifact ${mutation}`,t=>{
 const f=fixture(t),base=path.resolve(root,'../tronador-cli-v511/internal/components/testdata/contracts');
 const plan=JSON.parse(fs.readFileSync(path.join(base,'valid/build-plan.json'))),result=JSON.parse(fs.readFileSync(path.join(base,'valid/oci-image-valid.json')));
 plan.components[0].language='go';plan.components[0].buildProfile='go';for(const c of [plan.components[0],plan.matrix.include[0]])c.toolchains=[{tool:'go',version:'1.25.0',distribution:'default',components:['api']}];
 const payload=path.join(f.directory,result.mainArtifact.location.path);fs.mkdirSync(path.dirname(payload),{recursive:true});fs.copyFileSync(path.join(base,'artifacts/image.oci.tar'),payload);
 if(mutation==='result-source')result.headSha='b'.repeat(40);if(mutation==='artifact-bytes')fs.appendFileSync(payload,'corruption');
 fs.writeFileSync(f.env.PLAN_PATH,JSON.stringify(plan));fs.writeFileSync(f.env.COMPONENT_RESULT,JSON.stringify(result));
 const p=runStep(action,'prepare',{env:f.env,realCli:cli,tools:[{command:'git',result:{stdout:plan.headSha+'\n'}}]});if(mutation==='none')assert.equal(p.error,undefined,JSON.stringify(p));else assert.ok(p.error,JSON.stringify(p));
});


for(const [language,profile]of [['node','npm'],['node','pnpm'],['node','yarn'],['go','go'],['python','python'],['rust','cargo'],['ruby','bundler'],['ruby','rails'],['java','maven'],['java','gradle']])test(`typed supported ${language}/${profile}`,t=>{const f=fixture(t);Object.assign(f.plan.components[0],{language,buildProfile:profile});f.tools[0].result.stdout=JSON.stringify({record:f.plan});const p=prepare(f);assert.equal(p.error,undefined,JSON.stringify(p));assert.equal(report(p).record.profile,profile);});
test('dotnet is rejected for separate native producer',t=>{const f=fixture(t);Object.assign(f.plan.components[0],{language:'dotnet',buildProfile:'dotnet'});f.tools[0].result.stdout=JSON.stringify({record:f.plan});assert.ok(prepare(f).error);});

test('known post-analysis source drift remains an explicit nonclean typed result',t=>{const p=prepare(fixture(t));const r=report(p,'passed',{NATIVE_STATUS:'',NATIVE_ERROR:'sonar-source-drift'});assert.equal(r.error,undefined);assert.equal(r.record.status,'infrastructure-error');assert.equal(r.record.errorCode,'sonar-source-drift');assert.equal(r.record.sourceSha,'a'.repeat(40));});
