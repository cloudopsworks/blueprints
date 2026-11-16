import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {runStep} from './action_test_support.mjs';
const action='cd/monorepo/recovery/backend/action.yml',account='123456789012';
function directory(t){const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'recovery-backend-test-')));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));return root;}
function select(t,change={}){
 const root=directory(t),file=path.join(root,'handle.json');
 // Validator doubles exercise selection, not historical-writer authentication.
 const backend={kind:'s3',bucket:'retained-state',key:'retained/api.tfstate',region:'us-east-1',workspace:'default',useLockfile:true,dynamodbTable:null,authRef:'backend'};
 const handle={resourceIdentity:{kind:'aws.lambda',provider:'aws',packageMode:'zip',region:'us-east-1',functionName:'example',iac:{sourceBucket:'external-packages'}},origin:{repository:{id:'12345'},runId:'100',runAttempt:'1',sourceSha:'b'.repeat(40)},scope:'component',ownership:'managed',backend,backendIdentity:{provider:'aws',accountId:account},providerIdentity:account,authRefs:['backend','workload']};
 if(change.handle)change.handle(handle);
 fs.writeFileSync(file,JSON.stringify(handle),{mode:0o600});
 const configured={...handle.backend};delete configured.key;delete configured.prefix;
 if(change.configured)change.configured(configured);
 const bindings=Object.fromEntries(['backend','workload'].map(label=>[label,{provider:'aws',roleArn:`arn:aws:iam::${account}:role/${label}`,region:'us-east-1'}]));
 if(change.bindings)change.bindings(bindings);
 const checked={valid:true,digest:'sha256:'+'a'.repeat(64),record:handle};
 const markerFile=path.join(root,'marker.json');
 // Fixture-only closed-marker data for leaf guard tests; not historical authority evidence.
 fs.writeFileSync(markerFile,JSON.stringify({receiptId:'900',repositoryId:handle.origin.repository.id,runId:handle.origin.runId,runAttempt:handle.origin.runAttempt,sourceContext:{sourceSha:handle.origin.sourceSha},sourceStage:{},stateHandleDigest:checked.digest,workflowRef:'retained',workflowSha:'b'.repeat(40),resourceClaims:['arn:aws:lambda:us-east-1:'+account+':function:example','object:arn:aws:s3:::external-packages/components/'+'1'.repeat(64)+'/main.zip']}),{mode:0o600});
 const metadata={...checked,module:{metadata:{moduleId:'aws-lambda'},activationBlocked:false}};
 if(change.metadata)change.metadata(metadata);
 return {env:{STATE_HANDLE:file,RESERVATION_MARKER:markerFile,DEPLOYMENT_STATE_CONF:'operator YAML, not an app path',AUTH_BINDINGS:'protected YAML',OPERATION:'destroy',LOCK_ID:'',RUNNER_TEMP:root,GITHUB_WORKSPACE:root,...change.env},tools:[
 {args:['components','contracts','validate','--kind','StateHandle'],result:{stdout:JSON.stringify(checked)}},
 {args:['components','contracts','validate','--kind','StateHandle','--module-root',path.join(root,'bp/terraform/monorepo/modules/aws-lambda')],result:{stdout:JSON.stringify(metadata)}},
 {prefix:['components','settings','--kind','backend','--json'],result:{stdout:JSON.stringify(configured)}},
 {prefix:['components','settings','--kind','auth','--json'],result:{stdout:JSON.stringify(bindings)}},
 ]};
}
test('recovery backend selection matches frozen org settings before any cloud command',t=>{
 const r=runStep(action,'select',select(t));assert.equal(r.error,undefined,JSON.stringify(r));
 const selection=JSON.parse(fs.readFileSync(r.outputs.selection));assert.equal(selection.operation,'destroy');
 assert.equal(fs.statSync(r.outputs.selection).mode&0o777,0o600);
 assert.equal(r.calls.some(c=>c.command!=='tronador'),false);assert.equal(r.calls.some(c=>c.kind==='api'),false);
 assert.ok(r.calls.some(c=>c.args.includes('--module-root')),'selection must independently check the actual catalog');
});
for(const [name,metadata]of [
 ['blocked real metadata',v=>v.module.activationBlocked=true],
 ['missing module',v=>delete v.module],
 ['nonboolean block',v=>v.module.activationBlocked='false'],
 ['missing block',v=>delete v.module.activationBlocked],
 ['invalid envelope',v=>v.valid=false],
 ['changed handle',v=>v.record={...v.record,ownership:'external'}],
 ['changed digest',v=>v.digest='sha256:'+'f'.repeat(64)],
])test(`recovery selection denies ${name} before any settings/auth/native call`,t=>{
 const r=runStep(action,'select',select(t,{metadata}));assert.ok(r.error,JSON.stringify(r));assert.deepEqual(r.outputs,{});
 assert.equal(r.calls.length,2);assert.equal(r.calls.every(c=>c.command==='tronador'&&c.args[1]==='contracts'),true);
});
for(const [name,change]of [
 ['non-Lambda family',{handle:h=>h.resourceIdentity.kind='aws.eks'}],
 ['external owner',{handle:h=>h.ownership='external'}],
 ['non-S3 backend',{handle:h=>h.backend.kind='gcs'}],
 ['nondefault workspace',{handle:h=>h.backend.workspace='other'}],
 ['legacy missing backend identity',{handle:h=>delete h.backendIdentity}],
 ['DynamoDB lock',{handle:h=>h.backend.dynamodbTable='legacy-locks'}],
 ['unlocked S3 backend',{handle:h=>h.backend.useLockfile=false}],
 ['changed org backend bucket',{configured:b=>b.bucket='new-bucket'}],
 ['wrong backend principal',{bindings:b=>b.backend.roleArn='arn:aws:iam::999999999999:role/backend'}],
 ['wrong workload principal',{bindings:b=>b.workload.region='us-west-2'}],
 ['invalid native lock',{env:{OPERATION:'unlock',LOCK_ID:'lock with spaces'}}],
])test(`recovery selection denies ${name} before auth or INIT`,t=>{
 const r=runStep(action,'select',select(t,change));assert.ok(r.error);assert.deepEqual(r.outputs,{});
 assert.equal(r.calls.some(c=>c.command!=='tronador'),false);assert.equal(r.calls.some(c=>c.kind==='api'),false);
});
function capture(t,change={}){
 const root=directory(t),selection=path.join(root,'selection.json');
 fs.writeFileSync(selection,JSON.stringify(Object.fromEntries(['backend','workload'].map(label=>[label+'Binding',{provider:'aws',roleArn:`arn:aws:iam::${account}:role/${label}`,region:'us-east-1'}]))),{mode:0o600});
 const credentials=Object.fromEntries(['BACKEND','WORKLOAD'].flatMap(label=>[['ACCESS_KEY',`${label}-access`],['SECRET_KEY',`${label}-secret`],['SESSION_TOKEN',`${label}-session`]].map(([field,value])=>[label+'_'+field,value])));
 return {env:{SELECTION:selection,RUNNER_TEMP:root,AWS_PROFILE:'ambient-profile',AWS_WEB_IDENTITY_TOKEN_FILE:'/ambient-token',...credentials,...change.env},tools:[{command:'aws',args:['--version'],result:{stdout:'aws-cli/2.40.1 Python/3 local-test'}},...['backend','workload'].map(label=>({command:'aws',args:['sts','get-caller-identity','--region','us-east-1','--no-cli-pager','--output','json'],result:{stdout:JSON.stringify({Account:account,Arn:`arn:aws:sts::${account}:assumed-role/${label}/session`,...change.identity})}}))]};
}
test('recovery captures disjoint explicit temporary AWS contexts without ambient profiles',t=>{
 const r=runStep(action,'capture',capture(t));assert.equal(r.error,undefined,JSON.stringify(r));
 assert.equal(r.calls.length,3);
 const identities=r.calls.filter(call=>call.args[0]==='sts');
 for(const [index,label]of ['backend','workload'].entries()){
  const call=identities[index],file=r.outputs[label+'-context'];
  assert.equal(call.env.AWS_ACCESS_KEY_ID,label.toUpperCase()+'-access');
  assert.equal(call.env.AWS_PROFILE,undefined);assert.equal(call.env.AWS_WEB_IDENTITY_TOKEN_FILE,undefined);
  assert.equal(call.env.AWS_EC2_METADATA_DISABLED,'true');
  assert.equal(fs.statSync(file).mode&0o777,0o600);
  assert.equal(fs.statSync(path.dirname(file)).mode&0o777,0o700);
 }
 assert.notEqual(identities[0].env.HOME,identities[1].env.HOME);
 assert.notEqual(identities[0].env.AWS_CONFIG_FILE,identities[1].env.AWS_CONFIG_FILE);
});
for(const [name,change]of [
 ['missing selected temporary token',{env:{BACKEND_SESSION_TOKEN:''}}],
 ['wrong selected STS account',{identity:{Account:'999999999999'}}],
 ['wrong selected STS role',{identity:{Arn:`arn:aws:sts::${account}:assumed-role/foreign/session`}}],
])test(`recovery credential capture denies ${name}`,t=>{
 const r=runStep(action,'capture',capture(t,change));assert.ok(r.error);assert.deepEqual(r.outputs,{});
 assert.equal(r.calls.some(c=>c.args?.includes('init')),false);
});
