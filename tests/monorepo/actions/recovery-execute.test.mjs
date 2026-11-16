import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {runStep} from './action_test_support.mjs';
const action='cd/monorepo/recovery/execute/action.yml',digest='sha256:'+'a'.repeat(64),source='b'.repeat(40),bp='c'.repeat(40);
function setup(t,change={}){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'recovery-execute-test-')));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const handle={protectedEnvironment:'release/prod',targetId:'prod-run',componentId:'api',backend:{kind:'s3',bucket:'retained-state',key:'retained/api.tfstate',region:'us-east-1',useLockfile:true}};
 const selection={handle,digest,operation:'unlock',lockId:'exact-native-lock'};
 const privateFile=(name,value)=>{const file=path.join(root,name);fs.writeFileSync(file,JSON.stringify(value),{mode:0o600});return file;};
 const selectionFile=privateFile('selection.json',selection);
 const proof={selection:selectionFile,workloadContext:privateFile('workload.json',{env:{PATH:process.env.PATH,HOME:root,AWS_ACCESS_KEY_ID:'workload-access'}}),backendContext:privateFile('backend.json',{env:{AWS_ACCESS_KEY_ID:'backend-access',AWS_SECRET_ACCESS_KEY:'backend-secret',AWS_SESSION_TOKEN:'backend-token'}}),handleDigest:digest,operation:'unlock',lockId:'exact-native-lock',lockETag:'"native-etag"',lockDigest:'sha256:'+'d'.repeat(64)};
 const checked={valid:true,record:handle,digest},metadata={...checked,module:{metadata:{moduleId:'aws-lambda'},activationBlocked:false}};
 if(change.metadata)change.metadata(metadata);
 const env={STATE_HANDLE:privateFile('handle.json',handle),PROOF:privateFile('proof.json',proof),RUNNER_TEMP:root,GITHUB_WORKSPACE:root,GITHUB_RUN_ID:'456',GITHUB_RUN_ATTEMPT:'2',GITHUB_REPOSITORY_ID:'123',SOURCE_SHA:source,BLUEPRINT_SHA:bp,OPERATION:'unlock',LOCK_ID:'exact-native-lock',HISTORICAL_CONTEXT:'',CONFIRMATION:'unlock release/prod/prod-run/api exact-native-lock',...change.env};
 const api=[{method:'rest.actions.getWorkflowRunAttempt',result:{data:{id:456,run_attempt:2,repository:{id:123},head_sha:source,triggering_actor:{login:'operator'}}}}];
 const tools=[{args:['components','contracts','validate','--kind','StateHandle'],result:{stdout:JSON.stringify(checked)}},{args:['components','contracts','validate','--kind','StateHandle','--module-root',path.join(root,'bp/terraform/monorepo/modules/aws-lambda')],result:{stdout:JSON.stringify(metadata),...change.metadataResult}},{prefix:['components','contracts','validate','--kind','OperationPlan'],result:{stdout:'{"valid":true}'}}];
 return {root,env,api,tools,handle,proof,privateFile};
}
test('executor independently validates catalog metadata before native pre-init',t=>{
 const f=setup(t),r=runStep(action,'plan',f);assert.equal(r.error,undefined,JSON.stringify(r));assert.ok(r.outputs['operation-plan']);
 assert.equal(r.calls.filter(c=>c.command==='tronador').length,3);assert.equal(r.calls.some(c=>c.args?.includes?.('render')||c.args?.includes?.('artifacts')),false);
 const operation=JSON.parse(fs.readFileSync(r.outputs['operation-plan']));assert.equal(operation.inputs,null);assert.equal(operation.lockId,'exact-native-lock');
});
for(const [name,change]of [
 ['blocked metadata',{metadata:v=>v.module.activationBlocked=true}],
 ['missing module',{metadata:v=>delete v.module}],
 ['string false',{metadata:v=>v.module.activationBlocked='false'}],
 ['changed handle',{metadata:v=>v.record={...v.record,targetId:'foreign'}}],
 ['changed digest',{metadata:v=>v.digest='sha256:'+'e'.repeat(64)}],
 ['invalid data envelope',{metadata:v=>v.valid=false}],
 ['validator failure',{metadataResult:{exitCode:1,stdout:''}}],
 ['oversized metadata',{metadataResult:{stdout:' '.repeat(4194305)}}],
])test(`direct executor denies ${name} even if a caller bypasses backend selection`,t=>{
 const f=setup(t,change),r=runStep(action,'plan',f);assert.ok(r.error,JSON.stringify(r));assert.deepEqual(r.outputs,{});
 assert.equal(r.calls.filter(c=>c.command==='tronador').length,2);assert.equal(r.calls.some(c=>c.command==='aws'||c.command==='terragrunt'||c.args?.includes?.('render')||c.args?.includes?.('artifacts')),false);
});
function nativeUnlock(t,change={}){
 const f=setup(t),r=runStep(action,'plan',f);assert.equal(r.error,undefined,JSON.stringify(r));
 const nativeEnv={OPERATION_PLAN:r.outputs['operation-plan'],DIRECTORY:r.outputs.directory,BACKEND_CONTEXT:f.proof.backendContext,WORKLOAD_CONTEXT:f.proof.workloadContext};
 const init=runStep(action,'unlock-init',{env:nativeEnv,tools:[{command:'tofu',args:['version','-json'],result:{stdout:'{"terraform_version":"1.11.4"}'}},{command:'terragrunt',args:['--version'],result:{stdout:'terragrunt version v0.99.4\n'}},{command:'terragrunt',args:['--non-interactive','--working-dir',path.join(r.outputs.directory,'unlock'),'run','--','init','-input=false','-get=false'],result:{exitCode:change.initFailure?1:0}}]});
 return {f,planned:r,nativeEnv,init};
}
test('unlock uses a backend-only native root then releases only the exact inspected native lock',t=>{
 const {f,planned,init}=nativeUnlock(t);assert.equal(init.error,undefined,JSON.stringify(init));
 const backendFile=path.join(init.outputs.root,'backend.tf.json'),backend=JSON.parse(fs.readFileSync(backendFile));
 assert.equal(backend.terraform.backend.s3.key,f.handle.backend.key);assert.equal(backend.terraform.backend.s3.access_key,'backend-access');assert.equal(fs.statSync(backendFile).mode&0o777,0o600);
 assert.deepEqual(fs.readdirSync(init.outputs.root).sort(),['backend.tf.json','terragrunt.hcl']);
 const unlock=runStep(action,'unlock',{env:{OPERATION_PLAN:planned.outputs['operation-plan'],ROOT:init.outputs.root,WORKLOAD_CONTEXT:f.proof.workloadContext,PROOF:f.env.PROOF},tools:[{command:'terragrunt',args:['--non-interactive','--working-dir',init.outputs.root,'run','--','force-unlock','-force','exact-native-lock']}]});
 assert.equal(unlock.error,undefined,JSON.stringify(unlock));
 const calls=[...planned.calls,...init.calls,...unlock.calls];assert.equal(calls.some(c=>c.args?.includes?.('render')||c.args?.includes?.('artifacts')||c.command==='aws'),false);
 assert.equal(unlock.calls[0].env.AWS_ACCESS_KEY_ID,'workload-access');assert.match(unlock.logs[0].message,/reservation retained/);
});
test('failed native unlock init never yields a usable root',t=>{const {init}=nativeUnlock(t,{initFailure:true});assert.ok(init.error);assert.deepEqual(init.outputs,{});});
for(const [name,mutate]of [['changed native lock',p=>p.lockId='foreign'],['missing lock ETag',p=>p.lockETag=null],['changed handle',p=>p.handleDigest='sha256:'+'f'.repeat(64)]])test(`unlock retains resources and reservation for ${name}`,t=>{
 const {f,planned,init}=nativeUnlock(t);assert.equal(init.error,undefined,JSON.stringify(init));const proof={...f.proof};mutate(proof);
 const r=runStep(action,'unlock',{env:{OPERATION_PLAN:planned.outputs['operation-plan'],ROOT:init.outputs.root,WORKLOAD_CONTEXT:f.proof.workloadContext,PROOF:f.privateFile('changed-proof.json',proof)}});
 assert.ok(r.error);assert.deepEqual(r.outputs,{});assert.deepEqual(r.calls,[]);
});
test('failed exact native force-unlock is reported without deleting reservation or state',t=>{
 const {f,planned,init}=nativeUnlock(t);const r=runStep(action,'unlock',{env:{OPERATION_PLAN:planned.outputs['operation-plan'],ROOT:init.outputs.root,WORKLOAD_CONTEXT:f.proof.workloadContext,PROOF:f.env.PROOF},tools:[{command:'terragrunt',prefix:['--non-interactive','--working-dir',init.outputs.root,'run','--','force-unlock','-force'],result:{exitCode:1}}]});
 assert.equal(r.error?.message,'recovery-unlock-failed-retained');assert.equal(r.calls.length,1);assert.deepEqual(r.outputs,{});
});
for(const changed of [false,true])test(`saved native destroy ${changed?'denies changed plan bytes':'applies only the retained verified plan path'}`,t=>{
 const f=setup(t),directory=path.join(f.root,'saved');fs.mkdirSync(directory,{mode:0o700});const plan=path.join(directory,'operation.tfplan');fs.writeFileSync(plan,'native saved plan unit data',{mode:0o600});
 const p={operation:'destroy',stateHandleDigest:digest,lockId:null},proof={operation:'destroy',lockETag:null,handleDigest:digest,resourceAddresses:['aws_lambda_function.component']};
 const saved={root:directory,digest:createHash('sha256').update(fs.readFileSync(plan)).digest('hex'),handleDigest:digest,resourceAddresses:proof.resourceAddresses};if(changed)fs.appendFileSync(plan,'changed');
 const r=runStep(action,'destroy',{env:{OPERATION_PLAN:f.privateFile('destroy.json',p),SAVED_PLAN:f.privateFile('saved.json',saved),PROOF:f.privateFile('destroy-proof.json',proof),WORKLOAD_CONTEXT:f.proof.workloadContext},tools:changed?[]:[{command:'terragrunt',args:['--non-interactive','--working-dir',directory,'run','--','apply','-input=false','operation.tfplan']}]});
 if(changed){assert.ok(r.error);assert.deepEqual(r.calls,[]);}else{assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.calls.length,1);}
 assert.deepEqual(r.outputs,{});
});
