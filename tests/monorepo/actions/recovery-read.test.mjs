import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {runStep} from './action_test_support.mjs';
const action='cd/monorepo/recovery/backend/read/action.yml';
const account='123456789012',digest='sha256:'+'a'.repeat(64),region='us-east-1';
function fixture(t,change={}){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'recovery-native-read-')));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const handle={ownership:'managed',scope:'component',resourceIdentity:{kind:'aws.lambda',provider:'aws',packageMode:'zip',region,functionName:'retained-api'},providerIdentity:account,backendIdentity:{provider:'aws',accountId:account},backend:{kind:'s3',bucket:'retained-state',key:'retained/api.tfstate',workspace:'default',region,useLockfile:true,dynamodbTable:null}};
 const selection={handle,digest,operation:change.operation||'destroy',lockId:change.operation==='unlock'?'exact-native-lock':null};
 const env={RUNNER_TEMP:root};
 for(const label of ['backend','workload']){
  const home=path.join(root,label);fs.mkdirSync(home,{mode:0o700});const empty=path.join(home,'empty');fs.writeFileSync(empty,'',{mode:0o600});
  const binding={provider:'aws',roleArn:`arn:aws:iam::${account}:role/${label}`,region};selection[label+'Binding']=binding;
  const credential={binding,env:{PATH:process.env.PATH,HOME:home,AWS_CONFIG_FILE:empty,AWS_SHARED_CREDENTIALS_FILE:empty,AWS_EC2_METADATA_DISABLED:'true',AWS_REGION:region,AWS_DEFAULT_REGION:region,AWS_ACCESS_KEY_ID:label+'-access',AWS_SECRET_ACCESS_KEY:label+'-secret',AWS_SESSION_TOKEN:label+'-session',AWS_PAGER:''}};
  if(change.credential)change.credential(credential,label);
  env[label.toUpperCase()+'_CONTEXT']=path.join(home,'context.json');fs.writeFileSync(env[label.toUpperCase()+'_CONTEXT'],JSON.stringify(credential),{mode:0o600});
 }
 env.SELECTION=path.join(root,'selection.json');fs.writeFileSync(env.SELECTION,JSON.stringify(selection),{mode:0o600});
 const arn=`arn:aws:lambda:${region}:${account}:function:retained-api`;
 const state={version:4,serial:1,lineage:'frozen-lineage',resources:[{mode:'managed',type:'aws_lambda_function',name:'component',instances:[{attributes:{arn,function_name:'retained-api',tags:{'cloudopsworks-owner':digest}}}]}]};
 if(change.state)change.state(state);
 const bytes=JSON.stringify(state),head={ContentLength:Buffer.byteLength(bytes),ETag:'"state-etag"',...change.head};
 const tools=[{command:'aws',args:['--version'],result:{stdout:'aws-cli/2.40.1 Python/3 local-test'}},
 {prefix:['components','contracts','validate','--kind','StateHandle'],result:{stdout:JSON.stringify({digest})}},
 ...['backend','workload'].map(label=>({command:'aws',prefix:['sts','get-caller-identity'],result:{stdout:JSON.stringify({Account:account,Arn:`arn:aws:sts::${account}:assumed-role/${label}/session`,...change.identity})}})),
 {command:'aws',prefix:['s3api','head-object'],result:{stdout:JSON.stringify(head),...change.headResult}},
 {command:'aws',prefix:['s3api','get-object','--bucket','retained-state','--key','retained/api.tfstate','--if-match','"state-etag"'],nativeFile:bytes,result:{stdout:JSON.stringify({ETag:change.downloadETag||head.ETag})}},
 {command:'aws',prefix:['s3api','list-objects-v2'],result:{stdout:JSON.stringify({IsTruncated:false,Contents:selection.operation==='unlock'?[{Key:handle.backend.key+'.tflock'}]:[],...change.listing})}},
 ];
 if(selection.operation==='unlock'){
  const lock={ID:selection.lockId,Path:handle.backend.bucket+'/'+handle.backend.key,...change.lock},body=JSON.stringify(lock);
  tools.push({command:'aws',prefix:['s3api','head-object'],result:{stdout:JSON.stringify({ContentLength:Buffer.byteLength(body),ETag:'"lock-etag"'})}},
   {command:'aws',prefix:['s3api','get-object'],nativeFile:body,result:{stdout:'{"ETag":"\\\"lock-etag\\\""}'}});
 }
 return {root,env,tools,state,arn,selection};
}
function read(t,change={}){const f=fixture(t,change);return {f,r:runStep(action,'state',f)};}
function ownership(f,stateProof,change={}){
 return runStep(action,'ownership',{env:{STATE_PROOF:stateProof,RUNNER_TEMP:f.root},tools:[{command:'aws',prefix:['lambda','get-function'],result:{stdout:JSON.stringify({Configuration:{FunctionArn:f.arn,FunctionName:'retained-api'},Tags:{'cloudopsworks-owner':digest},...change})}}]});
}
for(const operation of ['destroy','unlock'])test(`conditional ${operation} read proves native state/lock and exact owner without app artifacts or INIT`,t=>{
 const {f,r}=read(t,{operation});assert.equal(r.error,undefined,JSON.stringify(r));
 const p=JSON.parse(fs.readFileSync(r.outputs['state-proof']));assert.equal(p.operation,operation);assert.equal(p.handleDigest,digest);
 assert.equal(fs.statSync(p.statePath).mode&0o777,0o600);
 const owner=ownership(f,r.outputs['state-proof']);assert.equal(owner.error,undefined,JSON.stringify(owner));
 const final=runStep(action,'inspect',{env:{OWNERSHIP_PROOF:owner.outputs['ownership-proof'],RUNNER_TEMP:f.root}});
 assert.equal(final.error,undefined,JSON.stringify(final));assert.ok(final.outputs.proof);
 const proof=JSON.parse(fs.readFileSync(final.outputs.proof));assert.deepEqual(proof.resourceAddresses,['aws_lambda_function.component']);
 const all=[...r.calls,...owner.calls,...final.calls];assert.equal(all.some(c=>c.command==='tofu'||c.command==='terragrunt'),false);
 assert.equal(all.some(c=>c.args?.includes('render')||c.args?.includes('artifacts')),false);
});
for(const [name,change]of [
 ['state service error',{headResult:{exitCode:1,stdout:''}}],
 ['oversized state',{head:{ContentLength:4194305}}],
 ['state length lie',{head:{ContentLength:1}}],
 ['conditional object changed',{downloadETag:'"different-etag"'}],
 ['ambiguous/truncated lock listing',{listing:{IsTruncated:true}}],
 ['destroy with native lock',{listing:{Contents:[{Key:'retained/api.tfstate.tflock'}]}}],
 ['unlock absent lock',{operation:'unlock',listing:{Contents:[]}}],
 ['unlock wrong native lock ID',{operation:'unlock',lock:{ID:'foreign-lock'}}],
 ['unlock wrong native lock address',{operation:'unlock',lock:{Path:'foreign-bucket/key'}}],
 ['wrong STS principal',{identity:{Account:'999999999999'}}],
 ['ambient credential field',{credential:(c,label)=>{if(label==='backend')c.env.AWS_PROFILE='ambient';}}],
])test(`native precondition denies ${name} before INIT and exposes no proof`,t=>{
 const {r}=read(t,change);assert.ok(r.error,JSON.stringify(r));assert.deepEqual(r.outputs,{});
 assert.equal(r.calls.some(c=>c.command==='tofu'||c.command==='terragrunt'),false);
});
for(const [name,change]of [
 ['foreign state ownership tag',{state:s=>s.resources[0].instances[0].attributes.tags['cloudopsworks-owner']='foreign'}],
 ['foreign managed address',{state:s=>s.resources.push({mode:'managed',type:'aws_iam_role',name:'unrelated',instances:[{attributes:{}}]})}],
 ['empty state inventory',{state:s=>s.resources=[]}],
 ['foreign Lambda ARN',{state:s=>s.resources[0].instances[0].attributes.arn='arn:aws:lambda:us-east-1:999999999999:function:retained-api'}],
])test(`ownership proof denies ${name} before INIT`,t=>{
 const {f,r}=read(t,change);assert.equal(r.error,undefined,JSON.stringify(r));
 const rejected=ownership(f,r.outputs['state-proof']);assert.ok(rejected.error,JSON.stringify(rejected));assert.deepEqual(rejected.outputs,{});
 assert.equal(rejected.calls.some(c=>c.command==='tofu'||c.command==='terragrunt'),false);
});
test('native owner mismatch denies even when retained Terraform state claims the correct tag',t=>{
 const {f,r}=read(t);assert.equal(r.error,undefined,JSON.stringify(r));
 const rejected=ownership(f,r.outputs['state-proof'],{Tags:{'cloudopsworks-owner':'foreign'}});
 assert.ok(rejected.error);assert.deepEqual(rejected.outputs,{});
});
test('recheck denies changed native ETag rather than accepting stale retained proof',t=>{
 const {f,r}=read(t);assert.equal(r.error,undefined,JSON.stringify(r));const owner=ownership(f,r.outputs['state-proof']);assert.equal(owner.error,undefined,JSON.stringify(owner));
 const prior=JSON.parse(fs.readFileSync(owner.outputs['ownership-proof']));prior.stateETag='"prior-etag"';
 const previous=path.join(f.root,'prior-proof.json');fs.writeFileSync(previous,JSON.stringify(prior),{mode:0o600});
 const result=runStep(action,'inspect',{env:{OWNERSHIP_PROOF:owner.outputs['ownership-proof'],PREVIOUS_PROOF:previous,RUNNER_TEMP:f.root}});
 assert.equal(result.error?.message,'recovery-precondition-changed');assert.deepEqual(result.outputs,{});
});
