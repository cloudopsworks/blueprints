import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {root as blueprintRoot,runStep} from './action_test_support.mjs';
const action='ci/monorepo/plan/binding/action.yml';
const digest=bytes=>'sha256:'+createHash('sha256').update(bytes).digest('hex');
const unavailable=['normal-stage-unavailable','preview-automation-unavailable','preview-receipt-absent','preview-receipt-unusable','preview-targets-disagree','preview-receipt-inaccessible','stage-artifact-unavailable','original-artifact-unavailable'];
const cli=process.env.TRONADOR_CLI;
assert.equal(createHash('sha256').update(fs.readFileSync(cli)).digest('hex'),'2dd1cc04bcda2d26f851cfe61355bae79e57bd48267934df1ed521a9e87538c5');
let seed;
function nativePlans(){
 if(seed)return seed;
 const temp=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'normal23-unit-native-')));
 process.on('exit',()=>fs.rmSync(temp,{recursive:true,force:true}));
 const source=path.join(temp,'source');fs.cpSync(path.join(blueprintRoot,'tests/monorepo/fixtures/composite_first/mixed'),source,{recursive:true});
 const git=(...args)=>{const r=spawnSync('git',['-c','core.hooksPath=/dev/null','-c','user.name=Local','-c','user.email=local@example.invalid',...args],{cwd:source,encoding:'utf8'});assert.equal(r.status,0,r.stderr);return r.stdout.trim();};
 git('init','-q','-b','develop');git('add','.');git('commit','-qm','base');const base=git('rev-parse','HEAD');
 fs.appendFileSync(path.join(source,'components/node/index.js'),'\n// changed\n');git('add','.');git('commit','-qm','next');const head=git('rev-parse','HEAD');
 const make=baseSha=>{const r=runStep('ci/monorepo/plan/action.yml','plan',{realCli:cli,env:{RUNNER_TEMP:temp,SOURCE_PATH:source,HEAD_SHA:head,BASE_SHA:baseSha,VERSION:'1.2.3',PLAN_EVENT:'push',PR_NUMBER:'0',GITHUB_REPOSITORY_ID:'123',GITHUB_REPOSITORY:'example/mixed'}});assert.equal(r.error,undefined,JSON.stringify(r));return JSON.parse(fs.readFileSync(r.outputs.plan));};
 seed={head,base,initial:make(''),history:make(base)};return seed;
}
function fixture(t,found=false,reason=found?'normal-stage-available':unavailable[0]){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'normal23-binding-')));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const dir=fs.mkdtempSync(path.join(root,'input-'));fs.chmodSync(dir,0o700);
 const receipt={repositoryId:'123',runId:'456',runAttempt:'2',headSha:nativePlans().head,found,baseSha:found?nativePlans().base:'',reason,stage:found?{runId:'100',runAttempt:'1',artifactId:'200',archiveDigest:'sha256:'+'c'.repeat(64)}:null};
 const plan=structuredClone(found?nativePlans().history:nativePlans().initial);
 fs.writeFileSync(path.join(dir,'baseline.json'),JSON.stringify(receipt),{mode:0o600});fs.writeFileSync(path.join(dir,'plan.json'),JSON.stringify(plan),{mode:0o600});
 return {root,dir,receipt,plan,env:{RUNNER_TEMP:root,MODE:'prepare',VERIFICATION_ROLE:'',PLAN:path.join(dir,'plan.json'),CONSUMED_RECEIPT:path.join(dir,'baseline.json'),CONSUMED_DIGEST:digest(JSON.stringify(receipt)),EXPECTED_REPOSITORY_ID:'123',EXPECTED_REPOSITORY:'example/mixed',EXPECTED_RUN_ID:'456',EXPECTED_RUN_ATTEMPT:'2',EXPECTED_HEAD_SHA:receipt.headSha,GITHUB_REPOSITORY_ID:'123',GITHUB_REPOSITORY:'example/mixed',GITHUB_RUN_ID:'456',GITHUB_RUN_ATTEMPT:'2'}};
}
function run(f,env={}){
 fs.writeFileSync(f.env.PLAN,JSON.stringify(f.plan));
 return runStep(action,'bind',{realCli:cli,env:{...f.env,...env}});
}
for(const [found,reasons] of [[false,unavailable],[true,['normal-stage-available']]])for(const reason of reasons)for(const shape of ['prepare','writer','reader'])test(`closed reason ${reason} survives ${shape}`,t=>{
 const f=fixture(t,found,reason),r=run(f,shape==='prepare'?{}:{MODE:'verify',VERIFICATION_ROLE:shape,...(shape==='reader'?{CONSUMED_RECEIPT:'',CONSUMED_DIGEST:''}:{})});
 assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(JSON.parse(fs.readFileSync(r.outputs.receipt)).reason,reason);
 assert.equal(r.outputs.stage,found?JSON.stringify(f.receipt.stage):'');
 assert.equal(r.calls.some(c=>c.kind==='api'),false);
 if(shape==='prepare'){assert.deepEqual(fs.readdirSync(r.outputs.directory).sort(),['baseline.json','plan.json']);assert.equal(fs.statSync(r.outputs.directory).mode&0o777,0o700);assert.equal(fs.statSync(r.outputs.receipt).mode&0o777,0o600);}
});
for(const [found,reasons] of [[false,['normal-stage-available','unknown','',null]],[true,[...unavailable,'unknown','',null]]])for(const reason of reasons)for(const shape of ['prepare','writer','reader'])test(`reason relation rejects ${found}/${JSON.stringify(reason)}/${shape}`,t=>{
 const f=fixture(t,found,reason),r=run(f,shape==='prepare'?{}:{MODE:'verify',VERIFICATION_ROLE:shape,...(shape==='reader'?{CONSUMED_RECEIPT:'',CONSUMED_DIGEST:''}:{})});assert.equal(r.error?.message,'binding-reason');assert.deepEqual(r.outputs,{});
});
for(const [label,mutate,error] of [
 ['wrong digest',f=>{f.env.CONSUMED_DIGEST='sha256:'+'f'.repeat(64);},'binding-consumed-bytes'],
 ['wrong native base',f=>{f.plan.baseSha='b'.repeat(40);},'binding-native-base'],
 ['last selected duplicate',f=>{f.plan.buildSelection[1]={componentId:'go'};},'binding-native-plan'],
 ['unknown key',f=>{f.receipt.extra=true;},'binding-receipt'],
 ['null route mismatch',f=>{f.receipt.stage={};},'binding-stage'],
 ['wrong run',f=>{f.receipt.runId='457';},'binding-receipt'],
])test(`binding rejects ${label} before outputs`,t=>{
 const f=fixture(t);mutate(f);fs.writeFileSync(f.env.CONSUMED_RECEIPT,JSON.stringify(f.receipt));f.env.CONSUMED_DIGEST=label==='wrong digest'?f.env.CONSUMED_DIGEST:digest(JSON.stringify(f.receipt));
 const r=run(f);assert.equal(r.error?.message,error,JSON.stringify(r));assert.deepEqual(r.outputs,{});
});
for(const [label,raw,error] of [['duplicate','{"repositoryId":"wrong",','binding-receipt'],['invalid utf8',Buffer.from([0xff]),'TypeError'],['oversize',Buffer.alloc(65537),'binding-file-bound']])test(`raw receipt rejects ${label}`,t=>{
 const f=fixture(t);const bytes=label==='duplicate'?raw+JSON.stringify(f.receipt).slice(1):raw;fs.writeFileSync(f.env.CONSUMED_RECEIPT,bytes);f.env.CONSUMED_DIGEST=digest(bytes);
 const r=run(f);assert.equal(error==='TypeError'?r.error?.name:r.error?.message,error);assert.deepEqual(r.outputs,{});
});
for(const [label,change] of [['file mode',f=>fs.chmodSync(f.env.CONSUMED_RECEIPT,0o644)],['ancestor mode',f=>fs.chmodSync(f.dir,0o755)],['symlink',f=>{const p=f.env.CONSUMED_RECEIPT;fs.renameSync(p,p+'.old');fs.symlinkSync(p+'.old',p);} ]])test(`private receipt rejects ${label}`,t=>{const f=fixture(t);change(f);const r=run(f);assert.ok(r.error);assert.deepEqual(r.outputs,{});});
test('verify never silently becomes a reader when writer inputs omitted',t=>{const f=fixture(t);const r=run(f,{MODE:'verify',VERIFICATION_ROLE:'writer',CONSUMED_RECEIPT:'',CONSUMED_DIGEST:''});assert.equal(r.error?.message,'binding-inputs');assert.deepEqual(r.outputs,{});});
test('reader requires sibling companion and cannot take writer inputs',t=>{const f=fixture(t);const r=run(f,{MODE:'verify',VERIFICATION_ROLE:'reader'});assert.equal(r.error?.message,'binding-inputs');fs.unlinkSync(f.env.CONSUMED_RECEIPT);const missing=run(f,{MODE:'verify',VERIFICATION_ROLE:'reader',CONSUMED_RECEIPT:'',CONSUMED_DIGEST:''});assert.ok(missing.error);assert.deepEqual(missing.outputs,{});});

for(const shape of ['prepare','writer','reader'])test(`BOM bytes rejected by ${shape}`,t=>{
 const f=fixture(t),bytes=Buffer.concat([Buffer.from([0xef,0xbb,0xbf]),fs.readFileSync(f.env.CONSUMED_RECEIPT)]);fs.writeFileSync(f.env.CONSUMED_RECEIPT,bytes);f.env.CONSUMED_DIGEST=digest(bytes);
 const r=run(f,shape==='prepare'?{}:{MODE:'verify',VERIFICATION_ROLE:shape,...(shape==='reader'?{CONSUMED_RECEIPT:'',CONSUMED_DIGEST:''}:{})});assert.equal(r.error?.message,'binding-receipt');assert.deepEqual(r.outputs,{});
});
for(const key of ['runId','runAttempt','artifactId','archiveDigest'])for(const kind of ['array','number','null','object'])for(const shape of ['prepare','writer','reader'])test(`stage ${key}/${kind} rejects ${shape}`,t=>{
 const f=fixture(t,true),original=f.receipt.stage[key];f.receipt.stage[key]=kind==='array'?[original]:kind==='number'?100:kind==='null'?null:{};fs.writeFileSync(f.env.CONSUMED_RECEIPT,JSON.stringify(f.receipt));f.env.CONSUMED_DIGEST=digest(JSON.stringify(f.receipt));
 const r=run(f,shape==='prepare'?{}:{MODE:'verify',VERIFICATION_ROLE:shape,...(shape==='reader'?{CONSUMED_RECEIPT:'',CONSUMED_DIGEST:''}:{})});assert.equal(r.error?.message,'binding-stage');assert.deepEqual(r.outputs,{});
});
for(const shape of ['prepare','writer','reader'])for(const reason of [0,{},['normal-stage-unavailable']])test(`non-string reason ${JSON.stringify(reason)}/${shape} rejects`,t=>{
 const f=fixture(t,false,reason),r=run(f,shape==='prepare'?{}:{MODE:'verify',VERIFICATION_ROLE:shape,...(shape==='reader'?{CONSUMED_RECEIPT:'',CONSUMED_DIGEST:''}:{})});assert.equal(r.error?.message,'binding-reason');assert.deepEqual(r.outputs,{});
});
for(const shape of ['prepare','writer','reader'])test(`malformed raw receipt rejected by ${shape}`,t=>{
 const f=fixture(t),raw=Buffer.from('{bad');fs.writeFileSync(f.env.CONSUMED_RECEIPT,raw);f.env.CONSUMED_DIGEST=digest(raw);
 const r=run(f,shape==='prepare'?{}:{MODE:'verify',VERIFICATION_ROLE:shape,...(shape==='reader'?{CONSUMED_RECEIPT:'',CONSUMED_DIGEST:''}:{})});assert.equal(r.error?.name,'SyntaxError');assert.deepEqual(r.outputs,{});
});
for(const [label,env,error]of [['long plan path',{PLAN:'/'+ 'x'.repeat(4097)},'binding-file-path'],['relative plan path',{PLAN:'relative/plan.json'},'binding-file-path'],['unknown mode',{MODE:'other'},'binding-inputs'],['reader missing role',{MODE:'verify',VERIFICATION_ROLE:''},'binding-inputs'],['wrong authenticated run',{EXPECTED_RUN_ID:'457'},'binding-writer-attempt'],['wrong expected head',{EXPECTED_HEAD_SHA:'b'.repeat(40)},'binding-receipt']])test(`binding closed shape rejects ${label}`,t=>{const r=run(fixture(t),env);assert.equal(r.error?.message,error);assert.deepEqual(r.outputs,{});});
for(const label of ['private plan mode','private plan ancestor','private plan symlink'])test(`binding rejects ${label} with no output`,t=>{
 const f=fixture(t);if(label==='private plan mode')fs.chmodSync(f.env.PLAN,0o644);else if(label==='private plan ancestor')fs.chmodSync(f.dir,0o755);else{fs.renameSync(f.env.PLAN,f.env.PLAN+'.real');fs.symlinkSync(f.env.PLAN+'.real',f.env.PLAN);}
 const r=run(f);assert.equal(r.error?.message,'binding-file-mode');assert.deepEqual(r.outputs,{});
});
test('receipt changed after captured consumed hash cannot be sealed',t=>{const f=fixture(t);f.receipt.reason='original-artifact-unavailable';fs.writeFileSync(f.env.CONSUMED_RECEIPT,JSON.stringify(f.receipt));const r=run(f);assert.equal(r.error?.message,'binding-consumed-bytes');assert.deepEqual(r.outputs,{});});
