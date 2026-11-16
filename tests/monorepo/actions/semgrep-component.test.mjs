import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {runStep,loadStep} from './action_test_support.mjs';
const action='ci/scan/semgrep/action.yml',cli=process.env.TRONADOR_CLI||'/tmp/tronador-v511-python-prep';
const sha='a'.repeat(40),digest='sha256:'+'c'.repeat(64);
const clean={version:'1.185.0',results:[],errors:[],paths:{scanned:['components/api/app.js']},skipped_rules:[]};
const finding={check_id:'rule.id',path:'components/api/app.js',start:{line:1,col:1,offset:0},end:{line:1,col:2,offset:1},extra:{message:'finding',metadata:{},severity:'WARNING',fingerprint:'id',lines:'x'}};
function fixture(t,profile='npm'){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'semgrep-component-')));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const source=path.join(root,'components/api');fs.mkdirSync(source,{recursive:true});fs.writeFileSync(path.join(source,'app.js'),'x');
 const relative='.cloudopsworks/out/api/main.zip';fs.mkdirSync(path.dirname(path.join(root,relative)),{recursive:true});fs.writeFileSync(path.join(root,relative),'payload');
 const plan={repository:{id:'12345',fullName:'example/app'},headSha:sha,prNumber:null,components:[{id:'api',path:'components/api',buildProfile:profile}],buildSelection:[{componentId:'api'}]};
 const record={componentId:'api',headSha:sha,status:'succeeded',mainArtifact:{digest,location:{kind:'local',path:relative}}};
 const event={repository:{id:12345,full_name:'example/app'}};for(const [name,data]of Object.entries({plan:{},result:{},event}))fs.writeFileSync(path.join(root,name+'.json'),JSON.stringify(data));
 const env={SOURCE_PATH:root,PLAN_PATH:path.join(root,'plan.json'),COMPONENT_RESULT:path.join(root,'result.json'),COMPONENT:'api',SOURCE_SHA:sha,SOURCE_REF:'refs/heads/develop',TRUSTED:'true',SEMGREP_APP_TOKEN:'scan-token',RUNNER_TEMP:root,GITHUB_ACTIONS:'true',GITHUB_EVENT_NAME:'push',GITHUB_EVENT_PATH:path.join(root,'event.json'),GITHUB_REPOSITORY:'example/app',GITHUB_REPOSITORY_ID:'12345',GITHUB_RUN_ID:'42',GITHUB_RUN_ATTEMPT:'2',GITHUB_REF:'refs/heads/develop',GITHUB_SHA:sha,GITHUB_SERVER_URL:'https://github.com',GITHUB_API_URL:'https://api.github.com'};
 const tools=[{prefix:['components','contracts','validate','--kind','BuildPlan'],result:{stdout:JSON.stringify({record:plan})}},{prefix:['components','contracts','validate','--kind','ComponentResult'],result:{stdout:JSON.stringify({record})}},{prefix:['components','artifacts','verify'],result:{stdout:JSON.stringify({payloadVerified:true,digest})}},{command:'git',result:{stdout:sha+'\n'}}];
 return{root,source,plan,record,event,env,tools};
}
function prepare(f){return runStep(action,'prepare',f);}
function report(f,p,content,exit='0',error=''){
 if(arguments.length<3)content=clean;
 if(content!==undefined)fs.writeFileSync(path.join(p.outputs.directory,'semgrep.json'),typeof content==='string'?content:JSON.stringify(content),{mode:0o600});
 const r=runStep(action,'report',{env:{DIRECTORY:p.outputs.directory,NATIVE_EXIT:exit,NATIVE_ERROR:error},realCli:cli});
 return{...r,record:r.calls.find(c=>c.command==='tronador')?.input&&JSON.parse(r.calls.find(c=>c.command==='tronador').input)};
}
for(const profile of ['npm','pnpm','yarn','go','maven','gradle','dotnet','python','bundler','rails','cargo'])test(`finite ${profile} preserves typed source identity and reported scope`,t=>{
 const f=fixture(t,profile),p=prepare(f);assert.equal(p.error,undefined,JSON.stringify(p));assert.equal(p.outputs.decision,'ready');
 const r=report(f,p);assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs.status,'passed');assert.equal(r.record.profile,profile);assert.equal(r.record.required,false);assert.equal(r.record.sourceSha,sha);assert.equal(r.record.artifactDigest,digest);assert.match(r.record.correlationId,/^scan-[a-f0-9]{32}$/);
 assert.equal(fs.statSync(p.outputs.directory).mode&0o777,0o700);assert.equal(fs.statSync(r.outputs.result).mode&0o777,0o600);assert.ok(report(f,p).error,'exclusive output');
});
for(const [name,content,exit]of [['nonblocking',{...clean,results:[finding]},'0'],['blocking',{...clean,results:[finding]},'1'],['platform block empty findings',clean,'1']])test(`valid ${name} is advisory`,t=>{const f=fixture(t),p=prepare(f);assert.equal(report(f,p,content,exit).outputs.status,'findings-advisory');});
for(const [name,content]of [
 ['empty',''],['malformed','{'],['substring','notice\n'+JSON.stringify(clean)],['null',null],['array',[clean]],['wrong version',{...clean,version:'1.184.0'}],['missing version',{...clean,version:undefined}],
 ['errors',{...clean,errors:[{code:3,level:'warn',type:'Syntax error',message:'raw-canary'}]}],['bad errors',{...clean,errors:{}}],['bad results',{...clean,results:{}}],['empty targets',{...clean,paths:{scanned:[]}}],['invalid target',{...clean,paths:{scanned:['../outside']}}],['absolute target',{...clean,paths:{scanned:['/etc/passwd']}}],['missing target',{...clean,paths:{scanned:['missing.js']}}],['malformed finding',{...clean,results:[{...finding,start:{line:0,col:1}}]}],['foreign finding',{...clean,results:[{...finding,path:'missing.js'}]}],['bad severity',{...clean,results:[{...finding,extra:{...finding.extra,severity:'UNKNOWN'}}]}],['skipped rules',{...clean,skipped_rules:[{rule_id:'r',details:'bad'}]}],['skipped target',{...clean,paths:{...clean.paths,skipped:[{path:'app.js',reason:'analysis_failed'}]}}],['unresolved subproject',{...clean,subprojects:[{resolved:false}]}],['resolution reason',{...clean,subprojects:[{resolved:true,unresolved_reason:'Failed'}]}],['huge',' '.repeat(16*1024*1024+1)],
])test(`report never green for ${name}`,t=>{const f=fixture(t),p=prepare(f),r=report(f,p,content);assert.equal(r.error,undefined,JSON.stringify(r));assert.notEqual(r.outputs.status,'passed');assert.equal(JSON.stringify(r).includes('raw-canary'),false);});
for(const [exit,code]of [['2','semgrep-tool-error'],['3','semgrep-target-parse'],['4','semgrep-rule-parse'],['5','semgrep-config-yaml'],['7','semgrep-missing-config'],['8','semgrep-language'],['13','semgrep-authentication'],['124','semgrep-timeout'],['137','semgrep-tool-signal'],['9','semgrep-tool-exit']])test(`native exit ${exit} classified`,t=>{const f=fixture(t),p=prepare(f),r=report(f,p,clean,exit);assert.equal(r.outputs.status,'infrastructure-error');assert.equal(r.record.errorCode,code);});
for(const[name,change,decision]of [['untrusted',f=>f.env.TRUSTED='false','semgrep-untrusted-source'],['missing token',f=>delete f.env.SEMGREP_APP_TOKEN,'semgrep-missing-credential']])test(`no source execution authorization: ${name}`,t=>{const f=fixture(t);change(f);const p=prepare(f);assert.equal(p.error,undefined,JSON.stringify(p));assert.equal(p.outputs.decision,decision);assert.notEqual(report(f,p).outputs.status,'passed');});
for(const[name,change]of [['source traversal',f=>f.plan.components[0].path='../outside'],['result SHA',f=>f.record.headSha='b'.repeat(40)],['not selected',f=>f.plan.buildSelection=[]],['payload digest',f=>f.tools[2].result.stdout=JSON.stringify({payloadVerified:true,digest:'sha256:'+'d'.repeat(64)})],['source symlink',f=>{fs.renameSync(f.source,f.source+'-real');fs.symlinkSync(f.source+'-real',f.source);}],['push native SHA',f=>f.env.GITHUB_SHA='b'.repeat(40)],['repository mismatch',f=>f.env.GITHUB_REPOSITORY='other/repo'],['bad run',f=>f.env.GITHUB_RUN_ID='0'],['bad ref',f=>f.env.GITHUB_REF='refs/heads/develop\nother']])test(`prepare rejects ${name}`,t=>{const f=fixture(t);change(f);f.tools[0].result.stdout=JSON.stringify({record:f.plan});f.tools[1].result.stdout=JSON.stringify({record:f.record});const p=prepare(f);assert.ok(p.error,JSON.stringify(p));assert.equal(p.outputs.directory,undefined);});
test('real workflow_run host metadata remains unchanged while original source differs',t=>{
 const f=fixture(t);f.env.GITHUB_EVENT_NAME='workflow_run';f.env.GITHUB_SHA='b'.repeat(40);f.event.workflow_run={head_sha:'c'.repeat(40)};
 fs.writeFileSync(f.env.GITHUB_EVENT_PATH,JSON.stringify(f.event));const before=fs.readFileSync(f.env.GITHUB_EVENT_PATH);
 const p=prepare(f);assert.equal(p.error,undefined,JSON.stringify(p));assert.deepEqual(fs.readFileSync(p.outputs.event),before);assert.deepEqual(fs.readFileSync(f.env.GITHUB_EVENT_PATH),before);
});
test('report rejects symlink, failed contract and unknown diagnostic without raw exposure',t=>{
 const f=fixture(t),p=prepare(f);fs.symlinkSync('/etc/passwd',path.join(p.outputs.directory,'semgrep.json'));assert.equal(report(f,p,undefined).outputs.status,'infrastructure-error');
 const f2=fixture(t),p2=prepare(f2),r=report(f2,p2,clean,'0','raw-canary');assert.equal(r.record.errorCode,'semgrep-tool-error');assert.equal(JSON.stringify(r).includes('raw-canary'),false);
});
test('inline bodies remain bounded and actual YAML scripts',()=>{for(const id of ['prepare','report'])assert.ok(loadStep(action,id).script.split('\n').filter(x=>x.trim()).length<=120);});
for(const mode of ['world-readable','directory','hardlink','missing'])test(`private report boundary ${mode}`,t=>{
 const f=fixture(t),p=prepare(f),file=path.join(p.outputs.directory,'semgrep.json');
 if(mode==='directory')fs.mkdirSync(file);else if(mode!=='missing'){fs.writeFileSync(file,JSON.stringify(clean),{mode:mode==='world-readable'?0o644:0o600});if(mode==='hardlink')fs.linkSync(file,path.join(f.root,'linked'));}
 assert.equal(report(f,p,undefined).outputs.status,'infrastructure-error');
});
test('installed ScannerResult contract failure never emits output or raw diagnostics',t=>{
 const f=fixture(t),p=prepare(f);fs.writeFileSync(path.join(p.outputs.directory,'semgrep.json'),JSON.stringify(clean),{mode:0o600});
 const r=runStep(action,'report',{env:{DIRECTORY:p.outputs.directory,NATIVE_EXIT:'0'},tools:[{result:{exitCode:1,stderr:'raw-secret-canary'}}]});
 assert.ok(r.error);assert.equal(r.outputs.result,undefined);assert.equal(JSON.stringify(r).includes('raw-secret-canary'),false);
});
for(const mutation of ['none','result-source','artifact-bytes'])test(`real offline CLI linked contracts and main payload: ${mutation}`,t=>{
 const f=fixture(t,'go'),base=new URL('../../../../tronador-cli-v511/internal/components/testdata/contracts/',import.meta.url);
 const plan=JSON.parse(fs.readFileSync(new URL('valid/build-plan.json',base))),record=JSON.parse(fs.readFileSync(new URL('valid/oci-image-valid.json',base)));
 const payload=path.join(f.root,record.mainArtifact.location.path);fs.mkdirSync(path.dirname(payload),{recursive:true});fs.copyFileSync(new URL('artifacts/image.oci.tar',base),payload);
 if(mutation==='result-source')record.headSha='b'.repeat(40);if(mutation==='artifact-bytes')fs.appendFileSync(payload,'corruption');
 fs.writeFileSync(f.env.PLAN_PATH,JSON.stringify(plan));fs.writeFileSync(f.env.COMPONENT_RESULT,JSON.stringify(record));
 f.env.GITHUB_REPOSITORY=plan.repository.fullName;f.env.GITHUB_REPOSITORY_ID=String(plan.repository.id);f.env.SOURCE_SHA=plan.headSha;f.env.GITHUB_SHA=plan.headSha;
 fs.writeFileSync(f.env.GITHUB_EVENT_PATH,JSON.stringify({repository:{id:plan.repository.id,full_name:plan.repository.fullName}}));
 const r=runStep(action,'prepare',{env:f.env,realCli:cli,tools:[{command:'git',result:{stdout:plan.headSha+'\n'}}]});
 if(mutation==='none'){assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs.decision,'ready');}else assert.ok(r.error,JSON.stringify(r));
});
test('identical bound source produces deterministic ScannerResult',t=>{const f=fixture(t),a=report(f,prepare(f)),b=report(f,prepare(f));assert.deepEqual(fs.readFileSync(a.outputs.result),fs.readFileSync(b.outputs.result));});
test('resolved dependency-source paths stay inside component',t=>{const f=fixture(t),p=prepare(f);assert.equal(report(f,p,{...clean,subprojects:[{resolved:true,dependency_sources:['../outside']}]}).outputs.status,'infrastructure-error');});
test('scanned target symlinks cannot bless outside content',t=>{const f=fixture(t),p=prepare(f);fs.unlinkSync(path.join(f.source,'app.js'));fs.symlinkSync('/etc/passwd',path.join(f.source,'app.js'));assert.equal(report(f,p).outputs.status,'infrastructure-error');});
test('CLI normalization cannot substitute a different ScannerResult identity',t=>{const f=fixture(t),p=prepare(f);fs.writeFileSync(path.join(p.outputs.directory,'semgrep.json'),JSON.stringify(clean),{mode:0o600});const r=runStep(action,'report',{env:{DIRECTORY:p.outputs.directory,NATIVE_EXIT:'0'},tools:[{result:{stdout:JSON.stringify({record:{componentId:'other'}})}}]});assert.ok(r.error);assert.equal(r.outputs.result,undefined);});
test('unknown build profile is not an executable scanner routing input',t=>{const f=fixture(t,'arbitrary-command');assert.ok(prepare(f).error);});

test('amendment17 carried source uses original branch rather than workflow_run origin SHA',t=>{
 const f=fixture(t);f.env.GITHUB_EVENT_NAME='workflow_run';f.env.GITHUB_SHA='b'.repeat(40);f.env.GITHUB_REF='refs/heads/main';
 f.env.SOURCE_REF='refs/heads/support/old';f.event.workflow_run={head_sha:'c'.repeat(40)};fs.writeFileSync(f.env.GITHUB_EVENT_PATH,JSON.stringify(f.event));
 const p=prepare(f);assert.equal(p.error,undefined,JSON.stringify(p));assert.equal(p.outputs.branch,'support/old');assert.equal(p.outputs.subdir,'components/api');assert.equal(p.outputs.repository,'example/app');assert.equal(p.outputs.display,'example/app/api');
 assert.deepEqual(JSON.parse(fs.readFileSync(p.outputs.event)),f.event);
});
for(const [sourceRef,branch]of [['refs/heads/develop','develop'],['refs/tags/v1.2.3','refs/tags/v1.2.3'],['refs/heads/release/1.2','release/1.2']])test(`amendment17 supported original ref ${sourceRef}`,t=>{
 const f=fixture(t);f.env.GITHUB_EVENT_NAME='workflow_dispatch';f.env.GITHUB_SHA='b'.repeat(40);f.env.SOURCE_REF=sourceRef;const p=prepare(f);assert.equal(p.error,undefined,JSON.stringify(p));assert.equal(p.outputs.branch,branch);
});
for(const sourceRef of ['', 'develop', 'refs/pull/17/merge', 'refs/heads/feature\nother'])test(`amendment17 unknown original ref denies ${JSON.stringify(sourceRef)}`,t=>{
 const f=fixture(t);f.env.SOURCE_REF=sourceRef;assert.ok(prepare(f).error);
});
for(const eventName of ['pull_request','pull_request_target'])test(`amendment17 native ${eventName} host cannot checkout and restore another scan source`,t=>{
 const f=fixture(t);f.env.SOURCE_REF='refs/heads/feature/example';f.env.GITHUB_EVENT_NAME=eventName;f.plan.prNumber=17;f.event.pull_request={number:17,head:{sha,ref:'feature/example'},base:{sha:'b'.repeat(40),ref:'develop'}};fs.writeFileSync(f.env.GITHUB_EVENT_PATH,JSON.stringify(f.event));f.tools[0].result.stdout=JSON.stringify({record:f.plan});assert.ok(prepare(f).error);
});
test('amendment17 root-relative report paths normalize but cannot cross component boundary',t=>{
 const f=fixture(t);f.env.SOURCE_REF='refs/heads/develop';const p=prepare(f);assert.equal(p.error,undefined,JSON.stringify(p));
 assert.equal(report(f,p,{...clean,paths:{scanned:['./components/api/app.js']}}).outputs.status,'passed');
 const other=fixture(t);other.env.SOURCE_REF='refs/heads/develop';const q=prepare(other);fs.mkdirSync(path.join(other.root,'components/worker'));fs.writeFileSync(path.join(other.root,'components/worker/app.js'),'other');
 assert.equal(report(other,q,{...clean,paths:{scanned:['components/worker/app.js']}}).outputs.status,'infrastructure-error');
});
