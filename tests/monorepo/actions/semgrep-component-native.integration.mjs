import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {root,runStep} from './action_test_support.mjs';
const action=path.join(root,'ci/scan/semgrep/action.yml');
// Validation only: import the actual locally installed pinned scanner, never a hosted helper.
const nativePython=process.env.SEMGREP_NATIVE_PYTHON||'/opt/homebrew/Cellar/semgrep/1.185.0/libexec/bin/python';
const metadataProbe=String.raw`import json, importlib.metadata, sys
from semgrep.commands.ci import ci
from semgrep.meta import GithubMeta
assert importlib.metadata.version('semgrep') == '1.185.0'
m=GithubMeta()
parsed=ci.make_context('ci',sys.argv[2:])
print(json.dumps(dict(version=importlib.metadata.version('semgrep'),commit=m.commit_sha,branch=m.branch,repository=m.repo_name,display=m.repo_display_name,event=m.event_name,subdir=str(parsed.params['subdir']))))`;
function native(t,mode='clean',extra={}){
 const directory=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'semgrep-native-')));t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
 const repository=path.join(directory,'repo'),source=path.join(repository,extra.COMPONENT_SUBDIR||'components/api'),bin=path.join(directory,'bin');fs.mkdirSync(source,{recursive:true});fs.mkdirSync(bin);
 const git=args=>{const r=spawnSync('git',['-C',repository,...args],{encoding:'utf8'});assert.equal(r.status,0,r.stderr);return r.stdout.trim();};
 git(['init','-q']);git(['config','user.email','test@example.invalid']);git(['config','user.name','Local test']);fs.writeFileSync(path.join(source,'app.js'),'x');git(['add','.']);git(['commit','-qm','first']);const other=git(['rev-parse','HEAD']);fs.writeFileSync(path.join(source,'app.js'),'y');git(['commit','-qam','selected']);const sha=git(['rev-parse','HEAD']);fs.writeFileSync(path.join(source,'.mode'),mode);fs.writeFileSync(path.join(source,'.other'),other);
 const event={repository:{id:12345,full_name:'example/app'},pull_request:{number:17,head:{sha,ref:'feature/test'},base:{sha:other,ref:'develop'}},workflow_run:{head_sha:sha}};
 const eventPath=path.join(directory,'event.json');fs.writeFileSync(eventPath,JSON.stringify(event),{mode:0o600});
 const body=`#!${process.execPath}
const fs=require('fs'),path=require('path'),cp=require('child_process');
const tool=path.basename(process.argv[1]),args=process.argv.slice(2);
fs.appendFileSync(path.join(process.env.DIRECTORY,'calls.jsonl'),JSON.stringify({tool,args,env:process.env})+'\\n');
if(tool==='timeout'){if(args[1]==='620s'&&fs.readFileSync(path.join(process.env.COMPONENT_PATH,'.mode'),'utf8')==='reader-failure')process.exit(7);const r=cp.spawnSync(args[2],args.slice(3),{stdio:'inherit',env:process.env,timeout:8000,killSignal:'SIGKILL'});process.exit(r.status===null?137:r.status);}
const mode=fs.readFileSync(path.join(process.env.COMPONENT_PATH,'.mode'),'utf8');
if(args[0]==='--version'){console.log(mode==='wrong-version'?'1.184.0':'1.185.0');process.exit(0);}
if(mode==='timeout')process.exit(124);if(mode==='signal')process.kill(process.pid,'SIGTERM');
if(mode==='artifact')fs.writeFileSync(path.join(process.env.COMPONENT_PATH,'legitimate-artifact.bin'),Buffer.alloc(20*1024*1024));
if(mode==='drift')cp.spawnSync('git',['checkout',fs.readFileSync(path.join(process.env.COMPONENT_PATH,'.other'),'utf8')],{stdio:'ignore'});
if(mode==='metadata'){const probe=cp.spawnSync(${JSON.stringify(nativePython)},['-c',${JSON.stringify(metadataProbe)},...args],{env:process.env,encoding:'utf8'});if(probe.status!==0){console.error(probe.stderr);process.exit(99);}fs.writeFileSync(path.join(process.env.DIRECTORY,'native-metadata.json'),probe.stdout);}
const row={version:'1.185.0',results:[],errors:[],paths:{scanned:['components/api/app.js']},skipped_rules:[]};
if(mode==='reported-error')row.errors=[{code:3,level:'warn',type:'Syntax error',message:'raw-secret-canary'}];
console.error('raw-secret-canary');
function emit(fd,data){let n=0;while(n<data.length){try{n+=fs.writeSync(fd,data,n,Math.min(4096,data.length-n));}catch(e){if(e.code==='EAGAIN'){Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,1);continue;}if(e.code==='EPIPE')return;throw e;}}}
if(mode==='huge-json')emit(1,Buffer.from(JSON.stringify({...row,pad:' '.repeat(40*1024*1024)})));
else {if(mode==='huge-stderr')emit(2,Buffer.alloc(40*1024*1024));console.log(mode==='malformed'?'bad-json':JSON.stringify(row));}
process.exit(mode==='blocking'?1:mode==='auth-error'?13:0);
`;
 for(const name of ['semgrep','timeout'])fs.writeFileSync(path.join(bin,name),body,{mode:0o700});
 const y=spawnSync('yq',['-o=json','-I=0','.',action],{encoding:'utf8'});assert.equal(y.status,0,y.stderr);const step=JSON.parse(y.stdout).runs.steps.find(s=>s.id==='scan');
 const env={PATH:bin+path.delimiter+process.env.PATH,DIRECTORY:directory,SOURCE_PATH:repository,COMPONENT_PATH:source,COMPONENT_SUBDIR:'components/api',ORIGINAL_BRANCH:'support/original',REPOSITORY_NAME:'example/app',REPOSITORY_DISPLAY:'example/app/api',SOURCE_SHA:sha,DECISION:'ready',VALIDATED_EVENT_PATH:eventPath,SEMGREP_APP_TOKEN:'scan-token',GITHUB_OUTPUT:path.join(directory,'outputs'),GITHUB_ACTIONS:'true',GITHUB_EVENT_NAME:'workflow_run',GITHUB_EVENT_PATH:eventPath,GITHUB_REPOSITORY:'example/app',GITHUB_REPOSITORY_ID:'12345',GITHUB_RUN_ID:'42',GITHUB_RUN_ATTEMPT:'2',GITHUB_SHA:other,GITHUB_REF:'refs/heads/develop',GITHUB_SERVER_URL:'https://github.com',GITHUB_API_URL:'https://api.github.com',...extra};
 if(mode==='capture-exists')fs.writeFileSync(path.join(directory,'capture.lock'),'old');
 const r=spawnSync('/bin/bash',['--noprofile','--norc','-c',step.run],{env,encoding:'utf8',timeout:12000,maxBuffer:65536});
 const outputs=fs.existsSync(env.GITHUB_OUTPUT)?fs.readFileSync(env.GITHUB_OUTPUT,'utf8'):'';const calls=fs.existsSync(path.join(directory,'calls.jsonl'))?fs.readFileSync(path.join(directory,'calls.jsonl'),'utf8').trim().split('\n').map(JSON.parse):[];
 return{directory,repository,source,sha,other,event,env,r,outputs,calls,git};
}
function normalized(f){fs.writeFileSync(path.join(f.directory,'context.json'),JSON.stringify({componentId:'api',profile:'npm',scanner:'semgrep',sourceSha:f.sha,artifactDigest:'sha256:'+'c'.repeat(64),correlationId:'scan-'+'d'.repeat(32),source:f.source,root:f.repository,decision:'ready'}),{mode:0o600});const outputs=Object.fromEntries(f.outputs.trim().split('\n').filter(Boolean).map(l=>{const n=l.indexOf('=');return[l.slice(0,n),l.slice(n+1)];}));return runStep('ci/scan/semgrep/action.yml','report',{env:{DIRECTORY:f.directory,NATIVE_EXIT:outputs.exit||'',NATIVE_ERROR:outputs.error||''},realCli:process.env.TRONADOR_CLI||'/tmp/tronador-v511-python-prep'});}
test('actual native pinned configured CI preserves real workflow_run metadata and clean reported scope',t=>{
 const f=native(t);assert.equal(f.r.status,0,JSON.stringify(f.r));assert.match(f.outputs,/exit=0/);const scan=f.calls.find(c=>c.tool==='semgrep'&&c.args[0]==='ci');assert.ok(scan);
 assert.deepEqual(scan.args,['ci','--subdir','components/api','--json','--no-suppress-errors','--disable-version-check']);assert.equal(scan.env.SEMGREP_APP_TOKEN,'scan-token');assert.equal(scan.args.includes('scan-token'),false);assert.equal(scan.env.GITHUB_EVENT_NAME,'workflow_run');assert.equal(scan.env.GITHUB_SHA,f.other);assert.equal(scan.env.SEMGREP_BRANCH,'support/original');assert.equal(scan.env.SEMGREP_REPO_NAME,'example/app');assert.equal(scan.env.SEMGREP_REPO_DISPLAY_NAME,'example/app/api');assert.equal(scan.env.GITHUB_EVENT_PATH,f.env.GITHUB_EVENT_PATH);assert.equal(scan.env.GITHUB_RUN_ID,'42');assert.deepEqual(JSON.parse(fs.readFileSync(scan.env.GITHUB_EVENT_PATH)),f.event);
 for(const c of f.calls)assert.equal(c.env.GITHUB_OUTPUT,undefined);assert.ok(scan.env.HOME.startsWith(f.directory));assert.ok(scan.env.SEMGREP_SETTINGS_FILE.startsWith(f.directory));assert.equal(f.r.stdout+f.r.stderr,'');assert.equal(normalized(f).outputs.status,'passed');
});
for(const decision of ['semgrep-untrusted-source','semgrep-missing-credential'])test(`native ${decision} never invokes tools`,t=>{const f=native(t,'clean',{DECISION:decision});assert.equal(f.calls.length,0);});
for(const key of ['AWS_ACCESS_KEY_ID','AZURE_CLIENT_SECRET','GOOGLE_APPLICATION_CREDENTIALS','ARM_CLIENT_SECRET','ACTIONS_ID_TOKEN_REQUEST_TOKEN','CLOUDOPSWORKS_AUTH','TF_TOKEN_app_terraform_io'])test(`native rejects ambient ${key}`,t=>{const f=native(t,'clean',{[key]:'cloud-canary'});assert.equal(f.calls.length,0);assert.match(f.outputs,/semgrep-credential-boundary/);assert.equal((f.r.stdout+f.r.stderr).includes('cloud-canary'),false);});
for(const key of ['GITHUB_TOKEN','GH_TOKEN','SEMGREP_AUDIT_ON','SEMGREP_COMMIT','SEMGREP_REPO_NAME','SEMGREP_APP_URL','SEMGREP_SUPPRESS_ERRORS','NODE_OPTIONS','BASH_ENV'])test(`native strips unauthorized ${key}`,t=>{const f=native(t,'clean',{[key]:'override-canary'});const scan=f.calls.find(c=>c.tool==='semgrep'&&c.args[0]==='ci');assert.ok(scan,JSON.stringify(f.r));assert.equal(scan.env[key],key==='SEMGREP_REPO_NAME'?'example/app':undefined);});
for(const[name,status]of [['blocking','findings-advisory'],['reported-error','infrastructure-error'],['auth-error','infrastructure-error'],['timeout','infrastructure-error'],['signal','infrastructure-error'],['malformed','infrastructure-error'],['wrong-version','infrastructure-error']])test(`actual native ${name} never false green`,t=>{const f=native(t,name);assert.equal(f.r.status,0,JSON.stringify(f.r));assert.equal(normalized(f).outputs.status,status);assert.equal((f.r.stdout+f.r.stderr).includes('raw-secret-canary'),false);if(name==='wrong-version')assert.equal(f.calls.some(c=>c.tool==='semgrep'&&c.args[0]==='ci'),false);});
for(const mode of ['huge-json','huge-stderr'])test(`actual ${mode} bounded during run and not clean`,t=>{const f=native(t,mode);assert.equal(f.r.status,0,JSON.stringify(f.r));assert.match(f.outputs,/semgrep-capture-limit/);for(const file of ['semgrep.json','scan.stderr'])assert.ok(fs.statSync(path.join(f.directory,file)).size<=16*1024*1024);assert.equal(normalized(f).outputs.status,'infrastructure-error');});
for(const eventName of ['pull_request','pull_request_target'])test(`native ${eventName} host is denied before tool execution`,t=>{const f=native(t,'clean',{GITHUB_EVENT_NAME:eventName,GITHUB_HEAD_REF:'feature/test',GITHUB_BASE_REF:'develop'});assert.equal(f.calls.length,0);assert.match(f.outputs,/semgrep-host-source/);assert.equal(f.git(['rev-parse','HEAD']),f.sha);assert.equal(normalized(f).outputs.status,'infrastructure-error');});
test('native source HEAD drift becomes infrastructure error before typed success',t=>{const f=native(t,'drift');assert.match(f.outputs,/semgrep-source-drift/);assert.equal(f.git(['rev-parse','HEAD']),f.other);assert.equal(normalized(f).outputs.status,'infrastructure-error');});

test('native source artifacts over 16MiB are not globally truncated',t=>{const f=native(t,'artifact');assert.equal(f.r.status,0);assert.equal(fs.statSync(path.join(f.source,'legitimate-artifact.bin')).size,20*1024*1024);assert.equal(normalized(f).outputs.status,'passed');});
test('native supported log destination cannot create unbounded private debug logs',t=>{const f=native(t);const scan=f.calls.find(c=>c.tool==='semgrep'&&c.args[0]==='ci');assert.equal(scan.env.SEMGREP_LOG_FILE,'/dev/null');});

test('empty scoped token never invokes native tools even with ready decision',t=>{const f=native(t,'clean',{SEMGREP_APP_TOKEN:''});assert.equal(f.calls.length,0);assert.match(f.outputs,/semgrep-missing-credential/);});
for(const mode of ['capture-exists','reader-failure'])test(`native ${mode} fails closed without raw diagnostics`,t=>{const f=native(t,mode);assert.equal(f.r.status,0,JSON.stringify(f.r));assert.equal(normalized(f).outputs.status,'infrastructure-error');assert.equal((f.r.stdout+f.r.stderr).includes('raw-secret-canary'),false);});

for(const branch of ['support/original','release/5.11','refs/tags/v5.11.0'])test(`installed Semgrep 1.185.0 consumes original source on workflow_run: ${branch}`,t=>{
 assert.ok(fs.existsSync(nativePython),'SEMGREP_NATIVE_PYTHON must identify installed Semgrep 1.185.0');
 const f=native(t,'metadata',{ORIGINAL_BRANCH:branch});assert.equal(f.r.status,0,JSON.stringify(f.r));assert.match(f.outputs,/exit=0/);
 const metadata=JSON.parse(fs.readFileSync(path.join(f.directory,'native-metadata.json'),'utf8'));
 assert.deepEqual(metadata,{version:'1.185.0',commit:f.sha,branch,repository:'example/app',display:'example/app/api',event:'workflow_run',subdir:'components/api'});
 assert.notEqual(metadata.commit,f.env.GITHUB_SHA);assert.equal(f.git(['rev-parse','HEAD']),f.sha);assert.deepEqual(JSON.parse(fs.readFileSync(f.env.GITHUB_EVENT_PATH)),f.event);
});
for(const component of ['api','worker'])test(`installed native metadata preserves separate component display: ${component}`,t=>{
 assert.ok(fs.existsSync(nativePython),'SEMGREP_NATIVE_PYTHON must identify installed Semgrep 1.185.0');
 const f=native(t,'metadata',{REPOSITORY_DISPLAY:'example/app/'+component});assert.match(f.outputs,/exit=0/);
 const metadata=JSON.parse(fs.readFileSync(path.join(f.directory,'native-metadata.json'),'utf8'));assert.equal(metadata.repository,'example/app');assert.equal(metadata.display,'example/app/'+component);
});
test('installed native PR repair checks out PR HEAD then restores original HEAD at exit',t=>{
 assert.ok(fs.existsSync(nativePython),'SEMGREP_NATIVE_PYTHON must identify installed Semgrep 1.185.0');
 const f=native(t,'clean',{GITHUB_EVENT_NAME:'pull_request'});
 // All fetches remain local. Both base and original PR commits exist in this real repository.
 f.git(['branch','-f','develop',f.other]);f.git(['remote','add','origin',f.repository]);
 const event={...f.event,pull_request:{...f.event.pull_request,head:{sha:f.other,ref:'develop'},base:{sha:f.other,ref:'develop'}}};fs.writeFileSync(f.env.GITHUB_EVENT_PATH,JSON.stringify(event));
 const probe=String.raw`import json, subprocess
from semgrep.meta import GithubMeta
from semgrep.commands.ci import fix_head_if_github_action
m=GithubMeta()
before=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
fix_head_if_github_action(m)
after=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
print(json.dumps(dict(before=before,during=after,metadata=m.commit_sha)))`;
 const r=spawnSync(nativePython,['-c',probe],{cwd:f.repository,env:{...process.env,...f.env,PATH:process.env.PATH,SEMGREP_SEND_METRICS:'off',SEMGREP_ENABLE_VERSION_CHECK:'0'},encoding:'utf8',timeout:20000});assert.equal(r.status,0,r.stderr);
 assert.deepEqual(JSON.parse(r.stdout),{before:f.sha,during:f.other,metadata:f.other});assert.equal(f.git(['rev-parse','HEAD']),f.sha);
});

test('installed native CLI parses spaced component subdir as one argument from repository root',t=>{
 const f=native(t,'metadata',{COMPONENT_SUBDIR:'components/api with spaces'});assert.match(f.outputs,/exit=0/);
 const metadata=JSON.parse(fs.readFileSync(path.join(f.directory,'native-metadata.json'),'utf8'));assert.equal(metadata.subdir,'components/api with spaces');assert.equal(metadata.commit,f.sha);
 const call=f.calls.find(c=>c.tool==='semgrep'&&c.args[0]==='ci');assert.equal(call.args[2],'components/api with spaces');
});
