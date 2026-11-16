// LOCAL adversarial glue tests. Validator doubles are data, not historical writer authority.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {runStep} from './action_test_support.mjs';

const backendAction='cd/monorepo/recovery/backend/action.yml';
function temp(t,label){
 const directory=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),label)));
 t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
 return directory;
}
function selection(t){
 const root=temp(t,'catalog-guard-private-'),account='123456789012';
 const backend={kind:'s3',bucket:'retained-state',key:'retained/api.tfstate',region:'us-east-1',workspace:'default',useLockfile:true,dynamodbTable:null,authRef:'backend'};
 const handle={resourceIdentity:{kind:'aws.lambda',provider:'aws',packageMode:'zip',region:'us-east-1',functionName:'example',iac:{sourceBucket:'external-packages'}},origin:{repository:{id:'12345'},runId:'100',runAttempt:'1',sourceSha:'b'.repeat(40)},scope:'component',ownership:'managed',backend,backendIdentity:{provider:'aws',accountId:account},providerIdentity:account,authRefs:['backend','workload']};
 const content=JSON.stringify(handle),file=path.join(root,'handle.json');fs.writeFileSync(file,content,{mode:0o600});
 const configured={...backend};delete configured.key;
 const bindings=Object.fromEntries(['backend','workload'].map(label=>[label,{provider:'aws',roleArn:`arn:aws:iam::${account}:role/${label}`,region:'us-east-1'}]));
 const checked={valid:true,record:handle,digest:'sha256:'+'a'.repeat(64)};
 const markerFile=path.join(root,'marker.json');
 // Fixture-only closed-marker data for leaf guard tests; not historical authority evidence.
 fs.writeFileSync(markerFile,JSON.stringify({receiptId:'900',repositoryId:handle.origin.repository.id,runId:handle.origin.runId,runAttempt:handle.origin.runAttempt,sourceContext:{sourceSha:handle.origin.sourceSha},sourceStage:{},stateHandleDigest:checked.digest,workflowRef:'retained',workflowSha:'b'.repeat(40),resourceClaims:['arn:aws:lambda:us-east-1:'+account+':function:example','object:arn:aws:s3:::external-packages/components/'+'1'.repeat(64)+'/main.zip']}),{mode:0o600});
 return {root,content,file,env:{STATE_HANDLE:file,RESERVATION_MARKER:markerFile,DEPLOYMENT_STATE_CONF:'protected org YAML',AUTH_BINDINGS:'protected bindings YAML',OPERATION:'destroy',LOCK_ID:'',RUNNER_TEMP:root,GITHUB_WORKSPACE:root},tools:[
  {args:['components','contracts','validate','--kind','StateHandle'],result:{stdout:JSON.stringify(checked)}},
  {args:['components','contracts','validate','--kind','StateHandle','--module-root',path.join(root,'bp/terraform/monorepo/modules/aws-lambda')],result:{stdout:JSON.stringify({...checked,module:{metadata:{moduleId:'aws-lambda'},activationBlocked:false}})}},
  {args:['components','settings','--kind','backend','--json'],result:{stdout:JSON.stringify(configured)}},
  {args:['components','settings','--kind','auth','--json'],result:{stdout:JSON.stringify(bindings)}},
 ]};
}

test('backend accepts an ordinary private handle in the actual runner temp directory',t=>{
 const f=selection(t),r=runStep(backendAction,'select',f);
 assert.equal(r.error,undefined,JSON.stringify(r));
 assert.ok(r.outputs.selection);assert.equal(r.unused.tools,0);
 assert.equal(r.calls.length,4);assert.equal(r.calls[0].input,f.content);
 assert.equal(r.calls.every(call=>call.kind==='exec'&&call.command==='tronador'),true);
});

test('backend rejects a handle reached through a parent symlink before reading it or invoking validators',t=>{
 const f=selection(t),outside=temp(t,'catalog-guard-outside-');
 fs.writeFileSync(path.join(outside,'handle.json'),f.content,{mode:0o600});
 const link=path.join(f.root,'linked');fs.symlinkSync(outside,link,'dir');
 f.env.STATE_HANDLE=path.join(link,'handle.json');
 assert.notEqual(fs.realpathSync(f.env.STATE_HANDLE),f.env.STATE_HANDLE);
 const r=runStep(backendAction,'select',f);
 assert.equal(r.error?.message,'recovery-private-handle',JSON.stringify(r));
 assert.deepEqual(r.outputs,{});assert.deepEqual(r.calls,[]);
});

test('backend rejects a directly symlinked handle before reading it or invoking validators',t=>{
 const f=selection(t),link=path.join(f.root,'handle-link.json');
 fs.symlinkSync(f.file,link);f.env.STATE_HANDLE=link;
 const r=runStep(backendAction,'select',f);
 assert.equal(r.error?.message,'recovery-private-handle',JSON.stringify(r));
 assert.deepEqual(r.outputs,{});assert.deepEqual(r.calls,[]);
});

test('direct executor rejects a parent-symlink handle before API or native calls',t=>{
 const root=temp(t,'catalog-execute-private-'),outside=temp(t,'catalog-execute-outside-');
 fs.writeFileSync(path.join(outside,'handle.json'),'{}',{mode:0o600});
 const link=path.join(root,'linked');fs.symlinkSync(outside,link,'dir');
 const r=runStep('cd/monorepo/recovery/execute/action.yml','plan',{env:{RUNNER_TEMP:root,STATE_HANDLE:path.join(link,'handle.json'),OPERATION:'unlock',LOCK_ID:'exact-native-lock',HISTORICAL_CONTEXT:''}});
 assert.equal(r.error?.message,'recovery-private-input',JSON.stringify(r));
 assert.deepEqual(r.outputs,{});assert.deepEqual(r.calls,[]);
});
