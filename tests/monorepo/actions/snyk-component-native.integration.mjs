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
const action = path.join(root,'ci/scan/snyk/action.yml');
function native(t, overrides={}, setup=()=>{}) {
  const directory=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'snyk-native-')));
  t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
  const bin=path.join(directory,'bin');fs.mkdirSync(bin);
  const log=path.join(directory,'recording.jsonl');
  // Local executable doubles receive the actual production native argv/environment.
  const body=`#!${process.execPath}
const fs=require('fs'),path=require('path');
const tool=path.basename(process.argv[1]),args=process.argv.slice(2),cp=require('child_process');
const state=JSON.parse(fs.readFileSync(path.join(process.env.DIRECTORY,'head-fixture.json')));
function drift(phase){if(state.phase===phase){const r=cp.spawnSync(state.git,['-C',process.env.SOURCE_PATH,'checkout','--detach',state.old]);if(r.status!==0)process.exit(77);}}
fs.appendFileSync(path.join(process.env.DIRECTORY,'recording.jsonl'),JSON.stringify({tool,args,env:process.env})+'\\n');
if(tool==='timeout'){if(args[2]==='snyk'&&args[3]==='test'&&process.env.MANIFEST==='timeout')process.exit(124);const r=require('child_process').spawnSync(args[2],args.slice(3),{stdio:'inherit',env:process.env,timeout:8000,killSignal:'SIGKILL'});process.exit(r.status===null?153:r.status);}
if(tool==='tronador'){drift('prepare');if(process.env.SNYK_TOKEN)process.exit(19);if(process.env.MANIFEST==='build-fail')process.exit(8);if(process.env.MANIFEST==='large-build')fs.writeFileSync(path.join(process.env.COMPONENT_PATH,'legitimate-build.bin'),Buffer.alloc(20*1024*1024));console.log(JSON.stringify({calls:[{tool:'dotnet',arguments:['restore','selected.csproj'],workingDirectory:process.env.COMPONENT_PATH}]}));process.exit(0);}
if(args[0]==='--version'){console.log(process.env.MANIFEST==='wrong-version'?'0.0.0':'1.1308.4');process.exit(0);}
drift('scan');console.error('raw-secret-canary');
if(process.env.MANIFEST==='large-scan-artifact')fs.writeFileSync(path.join(process.env.COMPONENT_PATH,'legitimate-scan.bin'),Buffer.alloc(20*1024*1024));
function emit(fd,data){
  let offset=0;
  while(offset<data.length){
    try{offset+=fs.writeSync(fd,data,offset,Math.min(4096,data.length-offset));}
    catch(error){if(error.code==='EAGAIN'){Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,1);continue;}if(error.code==='EPIPE')return;throw error;}
  }
}
const row={ok:true,vulnerabilities:[],packageManager:process.env.MANAGER,targetFile:process.env.MANIFEST};
if(['huge','huge-stdout','huge-json'].includes(process.env.MANIFEST))emit(1,process.env.MANIFEST==='huge-json'?Buffer.from(JSON.stringify({...row,pad:' '.repeat(40*1024*1024)})):Buffer.alloc(40*1024*1024));
else {if(process.env.MANIFEST==='huge-stderr')emit(2,Buffer.alloc(40*1024*1024));console.log(JSON.stringify(row));}
process.exit(process.env.MANIFEST==='findings'?1:0);

`;
  for(const tool of ['snyk','tronador','timeout']) fs.writeFileSync(path.join(bin,tool),body,{mode:0o700});
  const manifest=overrides.MANIFEST||'package.json';
  if (!manifest.includes('..') && !path.isAbsolute(manifest)) fs.writeFileSync(path.join(directory,manifest),'{}');
  const git=gitFixture(directory);
  fs.writeFileSync(path.join(directory,'head-fixture.json'),JSON.stringify({...git,git:realGit,phase:overrides.HEAD_DRIFT,failure:overrides.HEAD_FAILURE}));
  if(overrides.HEAD_FAILURE)fs.writeFileSync(path.join(bin,'git'),`#!${process.execPath}
const fs=require('fs'),cp=require('child_process');const s=JSON.parse(fs.readFileSync(${JSON.stringify(path.join(directory,'head-fixture.json'))}));if(s.failure==='stderr'){console.log(s.head);console.error('e'.repeat(200));process.exit(0);}if(s.failure==='oversized'){console.log('a'.repeat(200));process.exit(0);}process.exit({missing:127,failed:2,timeout:124}[s.failure]);`,{mode:0o700});
  setup(directory);
  const parsed=spawnSync('yq',['-o=json','-I=0','.',action],{encoding:'utf8'});
  assert.equal(parsed.status,0,parsed.stderr);
  const step=JSON.parse(parsed.stdout).runs.steps.find(s=>s.id==='scan');
  assert.equal(step.shell,'bash');
  const env={PATH:bin+path.delimiter+process.env.PATH,DIRECTORY:directory,DECISION:'ready',SOURCE_SHA:git.head,SOURCE_PATH:directory,COMPONENT_PATH:directory,PLAN_PATH:path.join(directory,'plan.json'),COMPONENT:'api',MANIFEST:'package.json',MANAGER:'npm',BUILD_PROFILE:'npm',PYTHON_COMMAND:path.join(directory,'.venv/bin/python3'),SNYK_TOKEN:'scan-token-canary',GITHUB_OUTPUT:path.join(directory,'github-output'),...overrides};
  const r=spawnSync('/bin/bash',['--noprofile','--norc','-c',step.run],{env,encoding:'utf8',timeout:10000,maxBuffer:65536});
  return {r,directory,step,log,git,records:fs.existsSync(log)?fs.readFileSync(log,'utf8').trim().split('\n').map(JSON.parse):[],outputs:fs.existsSync(env.GITHUB_OUTPUT)?fs.readFileSync(env.GITHUB_OUTPUT,'utf8'):''};
}
test('actual native body executes fixed installed CLI preparation and pinned Snyk with environment token only',t=>{
  const f=native(t);assert.equal(f.r.status,0,JSON.stringify(f.r));
  const build=f.records.find(r=>r.tool==='tronador');assert.ok(build);
  assert.deepEqual(build.args,['components','build','api','--workdir',f.directory,'--plan',path.join(f.directory,'plan.json'),'--allow-network','--no-install-tools','--json']);
  assert.equal(build.env.SNYK_TOKEN,undefined);
  const scan=f.records.find(r=>r.tool==='snyk'&&r.args[0]==='test');assert.ok(scan);
  assert.deepEqual(scan.args,['test','--file=package.json','--package-manager=npm','--json']);
  assert.equal(scan.env.SNYK_TOKEN,'scan-token-canary');assert.equal(scan.args.join(' ').includes('scan-token-canary'),false);
  assert.equal(scan.env.AWS_ACCESS_KEY_ID,undefined);assert.equal(scan.env.AZURE_CLIENT_SECRET,undefined);
  assert.ok(scan.env.HOME.startsWith(f.directory));assert.equal(fs.statSync(path.join(f.directory,'snyk.json')).mode&0o777,0o600);
  assert.equal(f.r.stdout+f.r.stderr,'');assert.match(f.outputs,/exit=0/);
});
for(const decision of ['snyk-untrusted-source','snyk-missing-credential','snyk-cargo-test-unsupported']) test(`native never invokes tools for ${decision}`,t=>{
  const f=native(t,{DECISION:decision});assert.equal(f.records.length,0);assert.equal(f.r.status,0);
});
for(const key of ['AWS_ACCESS_KEY_ID','AZURE_CLIENT_SECRET','GOOGLE_APPLICATION_CREDENTIALS','ARM_CLIENT_SECRET','ACTIONS_ID_TOKEN_REQUEST_TOKEN','CLOUDOPSWORKS_AUTH','TF_TOKEN_app_terraform_io']) test(`ambient ${key} blocks source execution`,t=>{
  const f=native(t,{[key]:'deploy-secret-canary'});assert.equal(f.records.length,0);assert.match(f.outputs,/snyk-credential-boundary/);
  assert.equal((f.r.stdout+f.r.stderr).includes('deploy-secret-canary'),false);
});
for(const [manifest,expected] of [['wrong-version','snyk-version-mismatch'],['timeout','exit=124'],['huge','exit='],['findings','exit=1']]) test(`actual native classification ${manifest}`,t=>{
  const f=native(t,{MANIFEST:manifest});assert.equal(f.r.status,0,JSON.stringify(f.r));assert.ok(f.outputs.includes(expected),f.outputs);
  assert.equal((f.r.stdout+f.r.stderr).includes('raw-secret-canary'),false);
  if(manifest==='wrong-version')assert.equal(f.records.some(r=>r.tool==='tronador'),false);
  if(manifest==='huge'){assert.match(f.outputs,/error=snyk-capture-limit/);assert.ok(fs.statSync(path.join(f.directory,'snyk.json')).size<=16*1024*1024);}
});
test('fresh exclusive capture rejects preexisting report without execution',t=>{
  // A second native invocation against the same directory must not reuse an earlier report.
  const f=native(t);const env={PATH:process.env.PATH,DIRECTORY:f.directory,DECISION:'ready',SOURCE_PATH:f.directory,COMPONENT_PATH:f.directory,PLAN_PATH:'/plan',COMPONENT:'api',MANIFEST:'package.json',MANAGER:'npm',BUILD_PROFILE:'npm',SNYK_TOKEN:'token',GITHUB_OUTPUT:path.join(f.directory,'retry-output')};
  const r=spawnSync('/bin/bash',['-c',f.step.run],{env,encoding:'utf8'});assert.equal(r.status,0);assert.match(fs.readFileSync(env.GITHUB_OUTPUT,'utf8'),/snyk-capture-exists/);
});
for(const [profile,manifest,manager] of [
  ['pnpm','package.json','pnpm'],['yarn','package.json','yarn'],['go','go.mod','gomodules'],
  ['maven','pom.xml','maven'],['gradle','build.gradle.kts','gradle'],['python','requirements.txt','pip'],
  ['python','pyproject.toml','poetry'],['python','Pipfile','pip'],['bundler','Gemfile','rubygems'],['rails','Gemfile','rubygems'],
])test(`actual native ${profile}/${manifest} fixed argv, no generic dispatch`,t=>{
  const f=native(t,{BUILD_PROFILE:profile,MANIFEST:manifest,MANAGER:manager});
  const scan=f.records.find(r=>r.tool==='snyk'&&r.args[0]==='test');assert.ok(scan,JSON.stringify(f));
  assert.deepEqual(scan.args.slice(0,4),['test','--file='+manifest,'--package-manager='+manager,'--json']);
  assert.equal(scan.args.includes('--command='+path.join(f.directory,'.venv/bin/python3')),profile==='python'&&manager==='pip');
  assert.equal(scan.args.some(a=>a.includes('all-projects')||a.includes('skip-unresolved')),false);
  if (['bundler','rails'].includes(profile)) {assert.equal(scan.env.BUNDLE_PATH,path.join(f.directory,'.bundle/vendor'));assert.equal(scan.env.BUNDLE_FROZEN,'true');}
});
test('.NET uses exact project restored by CLI, not ambiguous repository project guessing',t=>{
  const f=native(t,{BUILD_PROFILE:'dotnet',MANIFEST:'',MANAGER:'nuget'},directory=>{
    for(const project of ['selected.csproj','unselected.csproj'])fs.writeFileSync(path.join(directory,project),'');
  });
  const scan=f.records.find(r=>r.tool==='snyk'&&r.args[0]==='test');assert.ok(scan,JSON.stringify(f));
  assert.equal(scan.args[1],'--file=selected.csproj');
});
test('build failure never reaches scanner or leaks private diagnostics',t=>{
  const f=native(t,{MANIFEST:'build-fail'});assert.match(f.outputs,/error=snyk-build-preparation/);
  assert.equal(f.records.some(r=>r.tool==='snyk'&&r.args[0]==='test'),false);assert.equal(f.r.stdout+f.r.stderr,'');
});
for(const key of ['GITHUB_TOKEN','KUBECONFIG','DOCKER_CONFIG','SNYK_API','NODE_OPTIONS','BASH_ENV'])test(`native source child strips ambient ${key}`,t=>{
  const f=native(t,{[key]:'nonallowed-canary'});
  const scan=f.records.find(r=>r.tool==='snyk'&&r.args[0]==='test');assert.ok(scan,JSON.stringify(f));assert.equal(scan.env[key],undefined);
  const build=f.records.find(r=>r.tool==='tronador');assert.equal(build.env[key],undefined);
});

for(const [manifest,artifact] of [['large-build','legitimate-build.bin'],['large-scan-artifact','legitimate-scan.bin']])test(`capture limits do not truncate legitimate source artifact: ${manifest}`,t=>{
  const f=native(t,{MANIFEST:manifest});
  assert.equal(fs.statSync(path.join(f.directory,artifact)).size,20*1024*1024);
  assert.match(f.outputs,/exit=0\n/);
  assert.equal(normalized(f).outputs.status,'passed');
});

function normalized(f) {
  const context={componentId:'api',sourceSha:f.git.head,artifactDigest:'sha256:'+'c'.repeat(64),profile:'npm',buildProfile:'npm',correlationId:'scan-'+'d'.repeat(32),source:f.directory,manifest:'package.json',manager:'npm',decision:'ready'};
  fs.writeFileSync(path.join(f.directory,'context.json'),JSON.stringify(context),{mode:0o600});
  const outputs=Object.fromEntries(f.outputs.trim().split('\n').filter(Boolean).map(line=>{const at=line.indexOf('=');return [line.slice(0,at),line.slice(at+1)];}));
  return runStep('ci/scan/snyk/action.yml','report',{env:{DIRECTORY:f.directory,NATIVE_EXIT:outputs.exit||'',NATIVE_ERROR:outputs.error||''},realCli:process.env.TRONADOR_CLI||'/tmp/tronador-v511-python-prep'});
}
for(const manifest of ['huge-json','huge-stdout','huge-stderr'])test(`actual bounded ${manifest} cannot normalize clean even when native ignores EPIPE`,t=>{
  const f=native(t,{MANIFEST:manifest});assert.equal(f.r.status,0,JSON.stringify(f.r));
  assert.match(f.outputs,/error=snyk-capture-limit/);
  for(const file of ['snyk.json','scan.stderr'])assert.ok(fs.statSync(path.join(f.directory,file)).size<=16*1024*1024);
  assert.equal(f.r.stdout+f.r.stderr,'');assert.equal(normalized(f).outputs.status,'infrastructure-error');
});
test('benign bounded stderr stays separate from valid JSON stdout and preserves clean status',t=>{
  const f=native(t);assert.match(fs.readFileSync(path.join(f.directory,'scan.stderr'),'utf8'),/raw-secret-canary/);
  assert.equal(normalized(f).outputs.status,'passed');assert.equal(f.r.stdout+f.r.stderr,'');
});
test('fixed parent outputs survive while every native child omits step-output destination',t=>{
  const f=native(t);
  assert.equal(f.r.status,0,JSON.stringify(f.r));
  assert.match(f.outputs,/exit=0\nmanifest=package.json\n/);
  assert.ok(f.records.some(record=>record.tool==='tronador'));
  assert.ok(f.records.some(record=>record.tool==='snyk'&&record.args[0]==='test'));
  for(const record of f.records)assert.equal(record.env.GITHUB_OUTPUT,undefined,record.tool+' '+record.args.join(' '));
});

for(const phase of ['prepare','scan'])test(`real Git ${phase} drift cannot start/complete attributed Snyk success`,t=>{
 const f=native(t,{HEAD_DRIFT:phase});assert.equal(gitAt(f.directory,'rev-parse','HEAD'),f.git.old);assert.equal(f.r.status,0,JSON.stringify(f.r));assert.match(f.outputs,/error=snyk-source-drift/);assert.doesNotMatch(f.outputs,/^exit=/m);
 const scans=f.records.filter(r=>r.tool==='snyk'&&r.args[0]==='test');assert.equal(scans.length,phase==='prepare'?0:1);
 const r=normalized(f);assert.equal(r.outputs.status,'infrastructure-error');const record=JSON.parse(fs.readFileSync(r.outputs.result));assert.equal(record.sourceSha,f.git.head);assert.equal(record.errorCode,'snyk-source-drift');
});

for(const mode of ['missing','failed','timeout','oversized','stderr'])test(`bounded Git ${mode} fails closed before Snyk authentication`,t=>{
 const f=native(t,{HEAD_FAILURE:mode});assert.equal(f.r.status,0,JSON.stringify(f.r));assert.match(f.outputs,/error=snyk-source-drift/);assert.equal(f.records.some(c=>c.tool==='snyk'&&c.args[0]==='test'),false);const r=normalized(f);assert.equal(r.outputs.status,'infrastructure-error');assert.equal(JSON.parse(fs.readFileSync(r.outputs.result)).sourceSha,f.git.head);
});
