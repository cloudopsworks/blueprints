import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {root,runStep,loadStep} from './action_test_support.mjs';
const wrapper='ci/dotnet/scan/sonarqube/action.yml', action='ci/dotnet/scan/sonarqube/component/action.yml';
const cli=process.env.TRONADOR_CLI||'/tmp/tronador-v511-python-prep';
const digest='sha256:'+'c'.repeat(64);
const doc=p=>JSON.parse(spawnSync('yq',['-o=json','-I=0','.',path.join(root,p)],{encoding:'utf8'}).stdout);
function fixture(t,changes={}){
 const directory=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'sonar-dotnet-test-')));t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
 const source=path.join(directory,'components/api');fs.mkdirSync(source,{recursive:true});fs.writeFileSync(path.join(source,'selected.csproj'),'');
 const relative='.cloudopsworks/out/api/main.zip';fs.mkdirSync(path.dirname(path.join(directory,relative)),{recursive:true});fs.writeFileSync(path.join(directory,relative),'payload');
 const plan={headSha:'a'.repeat(40),version:'1.2.3',components:[{id:'api',path:'components/api',language:'dotnet',buildProfile:'dotnet'}],buildSelection:[{componentId:'api'}]};
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
test('legacy .NET action inputs/defaults/every existing body remain compatible',()=>{
 const before=JSON.parse(spawnSync('yq',['-o=json','-I=0','.',path.resolve(root,'../.omx/evidence/monorepo-v511-sonar-dotnet-before-action.yml')],{encoding:'utf8'}).stdout),current=doc(wrapper);
 assert.deepEqual(Object.fromEntries(Object.keys(before.inputs).map(k=>[k,current.inputs[k]])),before.inputs);
 for(const original of before.runs.steps){const step=current.runs.steps.find(s=>s.name===original.name);assert.deepEqual(Object.fromEntries(Object.entries(step).filter(([k])=>k!=='if')),original);assert.equal(step.if,original.id==='repo_owner'?undefined:"inputs.component-mode != 'true'");}
 assert.equal(current.inputs['component-mode'].default,'false');
 assert.equal(current.runs.steps.find(s=>s.id==='component').uses,'./bp/ci/dotnet/scan/sonarqube/component');
});
test('new named component action uses frozen correlated gate and no source helper',()=>{
 const d=doc(action),g=d.runs.steps.find(s=>s.id==='gate');assert.equal(g.uses,'./bp/ci/scan/sonarqube/quality-gate');assert.equal(g.with['component-mode'],'true');
 assert.equal(g.with['metadata-directory'],'${{ steps.prepare.outputs.metadata-directory }}');assert.equal(g.if,"steps.scan.outputs.status == 'uploaded'");
 for(const id of ['prepare','report']){assert.ok(loadStep(action,id).script.split('\n').filter(l=>l.trim()&&!l.trim().startsWith('//')).length<=120);}
 const s=d.runs.steps.find(s=>s.id==='scan');assert.equal(s.shell,'bash');assert.ok(!s.run.includes('ulimit'));
});
test('prepare binds typed source/result/main artifact and private identity',t=>{
 const f=fixture(t),p=prepare(f);assert.equal(p.error,undefined,JSON.stringify(p));assert.equal(p.outputs.decision,'ready');assert.equal(p.outputs.source,f.source);
 assert.equal(p.outputs.version,f.plan.version);assert.equal(fs.statSync(p.outputs['metadata-directory']).mode&0o777,0o700);
 assert.equal(fs.existsSync(path.join(p.outputs['metadata-directory'],'report-task.txt')),false);
 assert.equal(path.dirname(p.outputs['metadata-directory']),f.directory);assert.match(path.basename(p.outputs['metadata-directory']),/^sonar-analysis-/);
 assert.ok(p.calls.every(c=>!c.env?.SONAR_TOKEN&&!c.env?.AWS_ACCESS_KEY_ID));
 const r=report(p);assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs.status,'passed');assert.equal(r.record.scanner,'sonar');assert.equal(r.record.profile,'dotnet');assert.equal(r.record.artifactDigest,digest);assert.equal(r.record.required,true);
});
for(const [name,change]of [
 ['component traversal',f=>f.plan.components[0].path='../outside'],['wrong profile',f=>f.plan.components[0].buildProfile='npm'],['not selected',f=>f.plan.buildSelection=[]],
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
for(const mutation of ['none','result-source','artifact-bytes'])test(`real offline CLI validates .NET plan/result/artifact ${mutation}`,t=>{
 const f=fixture(t),base=path.resolve(root,'../tronador-cli-v511/internal/components/testdata/contracts');
 const plan=JSON.parse(fs.readFileSync(path.join(base,'valid/build-plan.json'))),result=JSON.parse(fs.readFileSync(path.join(base,'valid/oci-image-valid.json')));
 plan.components[0].language='dotnet';plan.components[0].buildProfile='dotnet';for(const c of [plan.components[0],plan.matrix.include[0]])c.toolchains=[{tool:'dotnet',version:'10.0.100',distribution:'default',components:['api']}];
 const payload=path.join(f.directory,result.mainArtifact.location.path);fs.mkdirSync(path.dirname(payload),{recursive:true});fs.copyFileSync(path.join(base,'artifacts/image.oci.tar'),payload);
 if(mutation==='result-source')result.headSha='b'.repeat(40);if(mutation==='artifact-bytes')fs.appendFileSync(payload,'corruption');
 fs.writeFileSync(f.env.PLAN_PATH,JSON.stringify(plan));fs.writeFileSync(f.env.COMPONENT_RESULT,JSON.stringify(result));
 const p=runStep(action,'prepare',{env:f.env,realCli:cli,tools:[{command:'git',result:{stdout:plan.headSha+'\n'}}]});if(mutation==='none')assert.equal(p.error,undefined,JSON.stringify(p));else assert.ok(p.error,JSON.stringify(p));
});

test('existing owner resolver executes before component and forwards override/fallback without new config',t=>{
 const d=doc(wrapper),owner=d.runs.steps.find(s=>s.id==='repo_owner'),component=d.runs.steps.find(s=>s.id==='component');
 assert.ok(d.runs.steps.indexOf(owner)<d.runs.steps.indexOf(component));assert.equal(owner.if,undefined);
 assert.equal(component.with.organization,'${{ steps.repo_owner.outputs.result }}');
 for(const [yaml,expected]of [['repository_owner: cloud-org\n','cloud-org'],['other: value\n','github-owner']]){
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'sonar-owner-'));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));fs.mkdirSync(path.join(dir,'source/.cloudopsworks/vars'),{recursive:true});fs.writeFileSync(path.join(dir,'source/.cloudopsworks/vars/inputs-global.yaml'),yaml);
  const out=path.join(dir,'out'),r=spawnSync('/bin/bash',['-e','-c',owner.run],{cwd:dir,env:{PATH:process.env.PATH,GITHUB_REPOSITORY_OWNER:'github-owner',INPUTS_SOURCE_PATH:'source',GITHUB_OUTPUT:out},encoding:'utf8'});
  assert.equal(r.status,0,r.stderr);assert.equal(fs.readFileSync(out,'utf8'),'result<<EOF\n'+expected+'\nEOF\n');
 }
});
for(const organization of ['', 'bad\norg', 'x'.repeat(256)])test(`Cloud organization rejects bounded invalid value ${organization.length}`,t=>{const f=fixture(t,{SONAR_URL:'https://sonarcloud.io',ORGANIZATION:organization});assert.ok(prepare(f).error);});
test('Cloud organization is resolved bounded action data; self-host ignores it',t=>{
 for(const server of ['https://sonarcloud.io','https://sonarcloud.us']){const p=prepare(fixture(t,{SONAR_URL:server,ORGANIZATION:'cloud-org'}));assert.equal(p.error,undefined,JSON.stringify(p));assert.equal(p.outputs.organization,'cloud-org');}
 const p=prepare(fixture(t,{ORGANIZATION:'not used\n'}));assert.equal(p.error,undefined,JSON.stringify(p));assert.equal(p.outputs.organization,'');
});

test('native original HEAD is bound from validated prepare output and bounded at lifecycle seams',()=>{
 const parsed=JSON.parse(spawnSync('yq',['-o=json','-I=0','.',path.join(root,'ci/dotnet/scan/sonarqube/component/action.yml')],{encoding:'utf8'}).stdout),scan=parsed.runs.steps.find(s=>s.id==='scan');
 assert.equal(scan.env.SOURCE_SHA,'${{ steps.prepare.outputs.source-sha }}');
 assert.match(scan.run,/timeout --kill-after=10s 30s git -C/);assert.match(scan.run,/head -c 42/);assert.match(scan.run,/head_codes=\("\$\{PIPESTATUS\[@\]\}"\)/);
 assert.ok(scan.run.indexOf('check_head prepared')<scan.run.indexOf('SONARQUBE_SCANNER_PARAMS=$('));
 assert.ok(scan.run.indexOf('check_head instrumented')<scan.run.indexOf('600s "$scanner" end'));
 assert.ok(scan.run.lastIndexOf('check_head completed')<scan.run.indexOf("printf 'status=uploaded"));
});
