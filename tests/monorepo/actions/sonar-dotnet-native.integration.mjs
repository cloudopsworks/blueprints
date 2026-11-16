import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {root,runStep} from './action_test_support.mjs';
const realGit=spawnSync('which',['git'],{encoding:'utf8'}).stdout.trim();
function gitAt(source,...args){const r=spawnSync(realGit,['-C',source,...args],{encoding:'utf8'});assert.equal(r.status,0,r.stderr);return r.stdout.trim();}
function gitFixture(source){gitAt(source,'init','-q');gitAt(source,'config','user.name','Local test');gitAt(source,'config','user.email','test@example.invalid');fs.writeFileSync(path.join(source,'head-marker'),'old');gitAt(source,'add','.');gitAt(source,'commit','-qm','old');const old=gitAt(source,'rev-parse','HEAD');fs.writeFileSync(path.join(source,'head-marker'),'current');gitAt(source,'commit','-qam','current');return {old,head:gitAt(source,'rev-parse','HEAD')};}
const action='ci/dotnet/scan/sonarqube/component/action.yml';
const cli=process.env.TRONADOR_CLI||'/tmp/tronador-v511-python-prep';
function native(t,scenario={},overrides={},setup=()=>{}){
 const directory=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'sonar-dotnet-native-')));t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
 const source=path.join(directory,'source'),bin=path.join(directory,'bin'),scannerDirectory=path.join(directory,'cloudopsworks-scanner-tools/dotnet'),metadata=fs.mkdtempSync(path.join(directory,'sonar-analysis-'));
 for(const d of [source,bin,scannerDirectory])fs.mkdirSync(d,{recursive:true});fs.chmodSync(metadata,0o700);
 const git=gitFixture(source);
 const project=scenario.project||'selected.csproj';if(!project.includes('..')&&!path.isAbsolute(project)&&!project.includes('\n'))fs.writeFileSync(path.join(source,project),'');
 fs.writeFileSync(path.join(directory,'scenario.json'),JSON.stringify({...scenario,old:git.old,git:realGit}));
 const body=`#!${process.execPath}
const fs=require('fs'),path=require('path'),cp=require('child_process');
const tool=path.basename(process.argv[1]),args=process.argv.slice(2),d=process.env.DIRECTORY;
const s=JSON.parse(fs.readFileSync(path.join(d,'scenario.json')));
function drift(phase){if(s.drift===phase){const r=cp.spawnSync(s.git,['-C',process.env.SOURCE_PATH,'checkout','--detach',s.old]);if(r.status!==0)process.exit(77);}}
fs.appendFileSync(path.join(d,'recording.jsonl'),JSON.stringify({tool,args,cwd:process.cwd(),env:process.env})+'\\n');
if(tool==='timeout'){
 const phase=args[2].endsWith('dotnet-sonarscanner')?args[3]:args[2]==='dotnet'&&args[3]==='build'?'build':args[2];
 if(s.timeout===phase)process.exit(124);
 const r=cp.spawnSync(args[2],args.slice(3),{stdio:'inherit',env:process.env});process.exit(r.status===null?153:r.status);
}
function emit(fd,data){let offset=0;while(offset<data.length)offset+=fs.writeSync(fd,data,offset,data.length-offset);}
function noisy(phase){if(s.huge===phase){try{emit(1,Buffer.alloc(40*1024*1024));}catch{}}else console.error('private-diagnostic-token-canary');}
if(tool==='tronador'){drift('prepare');
 if(process.env.SONAR_TOKEN||process.env.SONARQUBE_SCANNER_PARAMS)process.exit(19);
 if(s.prepareFailure)process.exit(8);if(s.largeArtifact==='prepare')fs.writeFileSync(path.join(process.env.COMPONENT_PATH,'large-prepare.bin'),Buffer.alloc(20*1024*1024));
 const p=s.project||'selected.csproj',cwd=s.foreignCwd?'/elsewhere':process.env.COMPONENT_PATH;
 const calls=[{tool:'dotnet',arguments:['restore',p],workingDirectory:cwd},{tool:'dotnet',arguments:['build',p,'--no-restore','--configuration',s.configuration||'Release'],workingDirectory:cwd}];
 if(s.ambiguous)calls.unshift(calls[0]);
 if(s.huge==='prepare-stderr'){try{emit(2,Buffer.alloc(40*1024*1024));}catch{}}
 console.log(s.badBuildJson?'{':JSON.stringify({calls}));process.exit(0);
}
if(tool==='dotnet'&&args[0]==='tool'){console.log('Package Id Version Commands');console.log('dotnet-sonarscanner '+(s.wrongVersion?'0.0.0':'12.1.0')+' dotnet-sonarscanner');process.exit(0);}
if(tool==='dotnet'){
 drift('build');noisy('build');if(s.largeArtifact==='build')fs.writeFileSync(path.join(process.cwd(),'large-instrumented.bin'),Buffer.alloc(20*1024*1024));process.exit(s.buildFailure?9:0);
}
if(args[0]==='begin'){
 noisy('begin');if(s.beginFailure)process.exit(7);
 const marker='/d:sonar.scanner.metadataFilePath=';fs.writeFileSync(path.join(d,'metadata-path'),args.find(a=>a.startsWith(marker)).slice(marker.length));fs.mkdirSync(path.join(process.cwd(),'.sonarqube'));process.exit(0);
}
if(args[0]==='end'){
 drift('end');noisy('end');if(s.endFailure)process.exit(6);
 const filename=fs.readFileSync(path.join(d,'metadata-path'),'utf8');
 fs.writeFileSync(filename,s.badMetadata?'projectKey=other\\nceTaskId=wrong\\n':'projectKey='+process.env.PROJECT_KEY+'\\nceTaskId=AY_Exact-Task\\n',{mode:0o600});process.exit(0);
}
process.exit(99);
`;
 for(const name of ['dotnet','tronador','timeout'])fs.writeFileSync(path.join(bin,name),body,{mode:0o700});
 fs.writeFileSync(path.join(scannerDirectory,'dotnet-sonarscanner'),body,{mode:0o700});
 if(scenario.gitFailure)fs.writeFileSync(path.join(bin,'git'),`#!${process.execPath}
if(${JSON.stringify(scenario.gitFailure)}==='stderr'){console.log(${JSON.stringify(git.head)});console.error('e'.repeat(200));process.exit(0);}if(${JSON.stringify(scenario.gitFailure)}==='oversized'){console.log('a'.repeat(200));process.exit(0);}process.exit(${{missing:127,failed:2,timeout:124}[scenario.gitFailure]});`,{mode:0o700});
 setup({directory,source,metadata,scannerDirectory});
 const parsed=spawnSync('yq',['-o=json','-I=0','.',path.join(root,action)],{encoding:'utf8'});assert.equal(parsed.status,0,parsed.stderr);
 const step=JSON.parse(parsed.stdout).runs.steps.find(s=>s.id==='scan');
 const env={PATH:bin+path.delimiter+process.env.PATH,DIRECTORY:directory,DECISION:'ready',SOURCE_SHA:git.head,SOURCE_PATH:source,COMPONENT_PATH:source,PLAN_PATH:path.join(directory,'plan.json'),COMPONENT:'api',SCANNER_DIRECTORY:scannerDirectory,METADATA_DIRECTORY:metadata,SERVER:'https://sonar.example/context',PROJECT_KEY:'repository:api',VERSION:'1.2.3',SONAR_TOKEN:'sonar-token-canary',GITHUB_OUTPUT:path.join(directory,'github-output'),...overrides};
 const r=spawnSync('/bin/bash',['--noprofile','--norc','-c',step.run],{env,encoding:'utf8',timeout:20000,maxBuffer:65536});
 const records=fs.existsSync(path.join(directory,'recording.jsonl'))?fs.readFileSync(path.join(directory,'recording.jsonl'),'utf8').trim().split('\n').map(JSON.parse):[];
 const outputs=fs.existsSync(env.GITHUB_OUTPUT)?fs.readFileSync(env.GITHUB_OUTPUT,'utf8'):'';
 return{directory,source,metadata,r,records,outputs,step,env,git};
}
const commands=f=>f.records.filter(r=>r.tool!=='timeout');
function result(f,gate='passed'){
 fs.writeFileSync(path.join(f.directory,'context.json'),JSON.stringify({componentId:'api',sourceSha:f.git.head,profile:'dotnet',scanner:'sonar',artifactDigest:'sha256:'+'c'.repeat(64),correlationId:'scan-'+'d'.repeat(32),decision:f.env.DECISION,qualityGate:true,required:true}),{mode:0o600});
 const native=Object.fromEntries(f.outputs.trim().split('\n').filter(Boolean).map(s=>s.split('=')));
 return runStep(action,'report',{env:{DIRECTORY:f.directory,NATIVE_STATUS:native.status||'',NATIVE_ERROR:native.error||'',GATE_STATUS:gate,GATE_QUALITY:'OK',TASK_ID:'AY_Exact-Task',ANALYSIS_ID:'AY_Exact-Analysis'},realCli:cli});
}
test('actual native body runs tokenless CLI preparation then exact pinned begin/build/end in same component cwd',t=>{
 const f=native(t);assert.equal(f.r.status,0,JSON.stringify(f.r));assert.equal(f.outputs,'status=uploaded\n');
 const calls=commands(f);assert.deepEqual(calls.map(c=>[c.tool,c.args[0]]),[['dotnet','tool'],['tronador','components'],['dotnet-sonarscanner','begin'],['dotnet','build'],['dotnet-sonarscanner','end']]);
 const prepare=calls[1];assert.deepEqual(prepare.args,['components','build','api','--workdir',f.source,'--plan',path.join(f.directory,'plan.json'),'--allow-network','--no-install-tools','--json']);
 for(const c of calls.slice(0,2)){assert.equal(c.env.SONAR_TOKEN,undefined);assert.equal(c.env.SONARQUBE_SCANNER_PARAMS,undefined);}
 for(const c of calls)assert.equal(c.env.GITHUB_OUTPUT,undefined,'output path is not exported to source children');
 for(const c of calls.slice(2)){
  assert.equal(c.cwd,f.source);assert.deepEqual(JSON.parse(c.env.SONARQUBE_SCANNER_PARAMS),{'sonar.token':'sonar-token-canary'});assert.equal(c.env.SONAR_TOKEN,undefined);
  assert.ok(!c.args.join(' ').includes('sonar-token-canary'));assert.equal(c.env.AWS_ACCESS_KEY_ID,undefined);
 }
 assert.deepEqual(calls[2].args,['begin','/k:repository:api','/v:1.2.3','/d:sonar.host.url=https://sonar.example/context','/d:sonar.scanner.metadataFilePath='+path.join(f.metadata,'report-task.txt')]);
 assert.deepEqual(calls[3].args,['build','selected.csproj','--no-restore','--configuration','Release','--no-incremental','--disable-build-servers']);assert.deepEqual(calls[4].args,['end']);
 assert.equal(f.r.stdout+f.r.stderr,'');assert.equal(result(f).outputs.status,'passed');
});
for(const decision of ['sonar-untrusted-source','sonar-missing-credential'])test(`native executes nothing for ${decision}`,t=>{const f=native(t,{}, {DECISION:decision});assert.equal(f.r.status,0);assert.equal(f.records.length,0);assert.notEqual(result(f).outputs.status,'passed');});
for(const name of ['AWS_ACCESS_KEY_ID','AZURE_CLIENT_SECRET','GOOGLE_APPLICATION_CREDENTIALS','ARM_CLIENT_SECRET','ACTIONS_ID_TOKEN_REQUEST_TOKEN','TF_TOKEN_app_terraform_io','CLOUDOPSWORKS_AUTH'])test(`ambient ${name} blocks before source execution`,t=>{const f=native(t,{}, {[name]:'cloud-token-canary'});assert.equal(f.records.length,0);assert.match(f.outputs,/sonar-credential-boundary/);assert.notEqual(result(f).outputs.status,'passed');});
for(const name of ['GITHUB_TOKEN','SNYK_TOKEN','SEMGREP_APP_TOKEN','KUBECONFIG','DOCKER_CONFIG','NODE_OPTIONS','SONARQUBE_SCANNER_PARAMS'])test(`native strips unrelated ${name}`,t=>{const f=native(t,{}, {[name]:'unrelated-secret-canary'});assert.equal(f.outputs,'status=uploaded\n');for(const c of commands(f)){if(name!=='SONARQUBE_SCANNER_PARAMS')assert.equal(c.env[name],undefined);else assert.notEqual(c.env[name],'unrelated-secret-canary');}});
for(const [scenario,error,last]of [
 [{wrongVersion:true},'sonar-tool-version','tool'],[{prepareFailure:true},'sonar-build-preparation','components'],[{ambiguous:true},'sonar-project-selection','components'],[{foreignCwd:true},'sonar-project-selection','components'],[{configuration:'Debug'},'sonar-project-selection','components'],[{badBuildJson:true},'sonar-project-selection','components'],
 [{beginFailure:true},'sonar-begin-failed','begin'],[{buildFailure:true},'sonar-instrumented-build-failed','build'],[{endFailure:true},'sonar-end-failed','end'],[{timeout:'begin'},'sonar-begin-failed','components'],[{timeout:'build'},'sonar-instrumented-build-failed','begin'],[{timeout:'end'},'sonar-end-failed','build'],
])test(`native failure ${JSON.stringify(scenario)} is nonclean with no downstream phase`,t=>{const f=native(t,scenario);assert.equal(f.r.status,0,JSON.stringify(f.r));assert.match(f.outputs,new RegExp('error='+error));assert.equal(commands(f).at(-1).args[0],last);assert.equal(f.r.stdout+f.r.stderr,'');assert.equal(result(f).outputs.status,'infrastructure-error');});
for(const project of ['../outside.csproj','-option.csproj','/absolute.csproj','x\\file.csproj','file\nname.csproj'])test(`native project boundary rejects ${JSON.stringify(project)}`,t=>{const f=native(t,{project});assert.match(f.outputs,/sonar-project-path/);assert.equal(commands(f).some(c=>c.args[0]==='begin'),false);});
test('typed project filename with spaces remains one argv, not shell code',t=>{const f=native(t,{project:'Library Name.csproj'});assert.equal(f.outputs,'status=uploaded\n');assert.equal(commands(f).find(c=>c.args[0]==='build').args[1],'Library Name.csproj');});
for(const [name,setup]of [
 ['metadata',f=>fs.writeFileSync(path.join(f.metadata,'report-task.txt'),'stale')],['scanner workspace',f=>fs.mkdirSync(path.join(f.source,'.sonarqube'))],['metadata symlink',f=>fs.symlinkSync('/etc/passwd',path.join(f.metadata,'report-task.txt'))],
])test(`native rejects stale ${name} before token-bearing phases`,t=>{const f=native(t,{}, {},setup);assert.match(f.outputs,/sonar-stale-analysis/);assert.equal(commands(f).some(c=>c.args[0]==='begin'),false);});
for(const phase of ['begin','build','end','prepare-stderr'])test(`native stream bound ${phase} cannot become clean even with ignored EPIPE`,t=>{const f=native(t,{huge:phase});assert.equal(f.r.status,0,JSON.stringify(f.r));assert.match(f.outputs,/error=sonar-/);assert.equal(f.r.stdout+f.r.stderr,'');assert.equal(result(f).outputs.status,'infrastructure-error');for(const file of ['begin.log','instrumented-build.log','end.log','prepare.stderr'])if(fs.existsSync(path.join(f.directory,file)))assert.ok(fs.statSync(path.join(f.directory,file)).size<=16777216);});
for(const phase of ['prepare','build'])test(`capture limits do not truncate legitimate ${phase} artifact`,t=>{const f=native(t,{largeArtifact:phase});assert.equal(f.outputs,'status=uploaded\n');assert.equal(fs.statSync(path.join(f.source,phase==='prepare'?'large-prepare.bin':'large-instrumented.bin')).size,20*1024*1024);});
test('second invocation cannot overwrite earlier private captures or start scanner',t=>{const f=native(t),count=f.records.length;const r=spawnSync('/bin/bash',['-c',f.step.run],{env:{...f.env,GITHUB_OUTPUT:path.join(f.directory,'retry-output')},encoding:'utf8'});assert.equal(r.status,0);assert.match(fs.readFileSync(path.join(f.directory,'retry-output'),'utf8'),/sonar-capture-exists/);assert.equal(fs.readFileSync(path.join(f.directory,'recording.jsonl'),'utf8').trim().split('\n').length,count);});
test('actual emitted native metadata is accepted by frozen gate metadata body and wrong metadata is denied',t=>{
 for(const badMetadata of [false,true]){const f=native(t,{badMetadata});assert.equal(f.outputs,'status=uploaded\n');const p=runStep('ci/scan/sonarqube/quality-gate/action.yml','component-metadata',{env:{RUNNER_TEMP:f.directory,METADATA_DIRECTORY:f.metadata,ANALYSIS_STARTED_AT:'1',PROJECT_KEY:'repository:api',SONAR_URL:'https://sonar.example/context'}});if(badMetadata)assert.ok(p.error);else {assert.equal(p.error,undefined,JSON.stringify(p));assert.equal(p.outputs['task-id'],'AY_Exact-Task');}}
});
test('actual native producer metadata flows through exact correlated gate and typed ScannerResult',t=>{
 const f=native(t),g='ci/scan/sonarqube/quality-gate/action.yml';assert.equal(f.outputs,'status=uploaded\n');
 const p=runStep(g,'component-metadata',{env:{RUNNER_TEMP:f.directory,METADATA_DIRECTORY:f.metadata,ANALYSIS_STARTED_AT:'1',PROJECT_KEY:'repository:api',SONAR_URL:'https://sonar.example/context'}});
 assert.equal(p.error,undefined,JSON.stringify(p));
 const r=runStep(g,'component-gate',{env:{SERVER:p.outputs.server,TASK_ID:p.outputs['task-id'],PROJECT_KEY:'repository:api',SONAR_TOKEN:'sonar-token-canary'},fetches:[
  {url:'https://sonar.example/context/api/ce/task?id=AY_Exact-Task',headers:{'content-type':'application/json'},body:JSON.stringify({task:{id:'AY_Exact-Task',type:'REPORT',componentKey:'repository:api',status:'SUCCESS',analysisId:'AY_Exact-Analysis'}})},
  {url:'https://sonar.example/context/api/qualitygates/project_status?analysisId=AY_Exact-Analysis',headers:{'content-type':'application/json'},body:JSON.stringify({projectStatus:{status:'OK'}})},
 ]});assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs['component-status'],'passed');assert.equal(result(f,r.outputs['component-status']).outputs.status,'passed');
});

for(const server of ['https://sonarcloud.io','https://sonarcloud.us'])test(`actual ${server} begin gets one organization argv only`,t=>{
 const f=native(t,{}, {SERVER:server,ORGANIZATION:'cloud-org'});assert.equal(f.outputs,'status=uploaded\n');const calls=commands(f),begin=calls.find(c=>c.args[0]==='begin');assert.deepEqual(begin.args.filter(a=>a.startsWith('/o:')),['/o:cloud-org']);assert.equal(begin.args.some(a=>a.startsWith('/d:sonar.organization')),false);
 assert.equal(begin.args.includes('/d:sonar.region=us'),server.endsWith('.us'));for(const c of calls.filter(c=>c!==begin))assert.equal(c.args.some(a=>a.startsWith('/o:')),false);
});
test('self-hosted native begin omits organization even when owner supplied',t=>{const f=native(t,{}, {ORGANIZATION:'github-owner'});assert.equal(f.outputs,'status=uploaded\n');assert.equal(commands(f).some(c=>c.args.some(a=>a.startsWith('/o:')||a.startsWith('/d:sonar.organization')||a.startsWith('/d:sonar.region'))),false);});
for(const organization of ['', 'bad\norg','x'.repeat(256)])test(`native Cloud organization invalid length ${organization.length} stops before tools`,t=>{const f=native(t,{}, {SERVER:'https://sonarcloud.io',ORGANIZATION:organization});assert.match(f.outputs,/sonar-organization/);assert.equal(f.records.length,0);});

for(const phase of ['prepare','build','end'])test(`real Git ${phase} drift prevents .NET gate eligibility and preserves original identity`,t=>{
 const f=native(t,{drift:phase});assert.equal(gitAt(f.source,'rev-parse','HEAD'),f.git.old);assert.equal(f.r.status,0,JSON.stringify(f.r));assert.match(f.outputs,/error=sonar-source-drift/);assert.doesNotMatch(f.outputs,/status=uploaded/);
 const scanner=commands(f).filter(c=>c.tool==='dotnet-sonarscanner');assert.deepEqual(scanner.map(c=>c.args[0]),phase==='prepare'?[]:phase==='build'?['begin']:['begin','end']);
 const r=result(f);assert.equal(r.outputs.status,'infrastructure-error');const record=JSON.parse(fs.readFileSync(r.outputs.result));assert.equal(record.sourceSha,f.git.head);assert.equal(record.required,true);assert.equal(record.errorCode,'sonar-source-drift');
});

for(const mode of ['missing','failed','timeout','oversized','stderr'])test(`bounded Git ${mode} fails closed before .NET scanner authentication`,t=>{
 const f=native(t,{gitFailure:mode});assert.equal(f.r.status,0,JSON.stringify(f.r));assert.match(f.outputs,/error=sonar-source-drift/);assert.equal(commands(f).some(c=>c.tool==='dotnet-sonarscanner'),false);assert.equal(result(f).outputs.status,'infrastructure-error');
});
