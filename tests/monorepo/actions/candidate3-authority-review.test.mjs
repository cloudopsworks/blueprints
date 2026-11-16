// LOCAL independent candidate3 checks; positive caller bytes are production bytes.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {root,runStep} from './action_test_support.mjs';
import {binary,product,reserve,historical,ownership,unlock,destroyPreparation} from './native_recovery_fixture.mjs';

const contextAction='cd/tasks/repo/context/action.yml';
const host='a'.repeat(40),blueprint='b'.repeat(40),policy='c'.repeat(40),merge='d'.repeat(40),tip='e'.repeat(40),head='f'.repeat(40);
const api=(method,data,args)=>({method,args,result:{data}});
function contextFixture(historical,edit=()=>{}){
 const caller='.github/workflows/composite-first-closure.yml',bytes=fs.readFileSync(path.join(root,'../monorepo-app-template',caller));
 const pull={number:17,state:'closed',merged:true,merge_commit_sha:merge,base:{ref:'support/1.2',sha:tip,repo:{id:123}},head:{ref:'topic',sha:head,repo:{id:123}}};
 const association={number:17,base:{ref:pull.base.ref,sha:policy,repo:{id:123}},head:structuredClone(pull.head)};edit(association);
 const run={id:456,run_attempt:2,repository:{id:123},event:'pull_request_target',path:caller,head_sha:host,head_branch:'master',pull_requests:[association],referenced_workflows:[{path:'cloudopsworks/blueprints/.github/workflows/monorepo-delivery-slice.yml@v5.11.0',sha:blueprint}]};
 const options={env:{GITHUB_REPOSITORY_ID:'123',GITHUB_RUN_ID:'456',GITHUB_RUN_ATTEMPT:'2',...(historical?{CONTEXT_RUN_ID:'456',CONTEXT_RUN_ATTEMPT:'2'}:{})},context:{repo:{owner:'example',repo:'mixed'},payload:historical?{action:'closed',pull_request:{number:999}}:{action:'closed',pull_request:{...pull,base:{...pull.base,sha:policy}}}},api:[
  api('rest.repos.get',{id:123,default_branch:'master'}),api('rest.actions.getWorkflowRunAttempt',run),
  api('rest.repos.getBranch',{protected:true,commit:{sha:host}},{branch:'master'}),
  api('rest.repos.getContent',{type:'file',encoding:'base64',content:bytes.toString('base64'),sha:createHash('sha1').update(`blob ${bytes.length}\0`).update(bytes).digest('hex')},{ref:host,path:caller}),
  api('rest.git.getRef',{object:{type:'commit',sha:blueprint}}),api('rest.pulls.get',pull,{pull_number:17}),
 ]};
 if(!historical){options.api.push(api('rest.repos.getBranch',{protected:true,commit:{sha:tip}},{branch:pull.base.ref}));for(const [base,end] of [[policy,tip],[policy,merge],[merge,tip]])options.api.push(api('rest.repos.compareCommitsWithBasehead',{status:'ahead',base_commit:{sha:base},merge_base_commit:{sha:base}},{basehead:base+'...'+end}));}
 return options;
}
for(const historical of [false,true]){
 test(`${historical?'historical':'current'} association scalar control preserves independently verified source boundaries`,()=>{
  const result=runStep(contextAction,'verify',contextFixture(historical));
  assert.equal(result.error,undefined,JSON.stringify(result));assert.equal(result.unused.api,0);
  assert.equal(result.outputs['pr-number'],'17');
  assert.equal(result.outputs['source-sha'],historical?undefined:merge);
  assert.equal(result.outputs['policy-sha'],historical?undefined:policy);
 });
 test(`${historical?'historical':'current'} association rejects array-coerced base SHA before authority output`,()=>{
  const result=runStep(contextAction,'verify',contextFixture(historical,a=>{a.base.sha=[policy];}));
  assert.equal(result.error?.message,'context-run-pull-association',JSON.stringify(result));
  assert.deepEqual(result.outputs,{});
  assert.equal(result.calls.length,2,'malformed shape must fail before branch/caller/PR reads');
 });
}

test('advanced association base SHA never replaces the original event policy snapshot',()=>{
 const result=runStep(contextAction,'verify',contextFixture(false,a=>{a.base.sha=tip;}));
 assert.equal(result.error,undefined,JSON.stringify(result));assert.equal(result.unused.api,0);
 assert.equal(result.outputs['policy-sha'],policy);assert.equal(result.outputs['source-sha'],merge);
 assert.notEqual(result.outputs['policy-sha'],tip);
});

test('historical association rejects array-coerced repository ID before authority output',()=>{
 const result=runStep(contextAction,'verify',contextFixture(true,a=>{a.base.repo.id=[123];}));
 assert.equal(result.error?.message,'context-run-pull-association',JSON.stringify(result));assert.deepEqual(result.outputs,{});
 assert.equal(result.calls.length,2);
});

function retained(t){
 const f=product(t),writer=reserve(f),history=historical(f,writer);
 assert.equal(history.r.error,undefined,JSON.stringify(history.r));
 return {f,history};
}
function select(f,history,marker=history.r.outputs['reservation-marker']){
 return runStep('cd/monorepo/recovery/backend/action.yml','select',{realCli:binary,context:{repo:f.repo},env:{...f.env,STATE_HANDLE:history.r.outputs['state-handle'],RESERVATION_MARKER:marker,OPERATION:'unlock',LOCK_ID:'native-lock',DEPLOYMENT_STATE_CONF:'s3:\n  bucket: state-example\n  region: us-east-1\n  use_lockfile: true\n  auth_ref: aws-state\n',AUTH_BINDINGS:JSON.stringify(f.bindings)}});
}
test('actual writer/history private marker carries exact claims into backend selection',t=>{
 const {f,history}=retained(t),result=select(f,history);
 assert.equal(result.error,undefined,JSON.stringify(result));
 const selected=JSON.parse(fs.readFileSync(result.outputs.selection));
 assert.deepEqual(selected.resourceClaims,history.receipt.payload.resourceClaims);
 assert.deepEqual(selected.reservationMarker,JSON.parse(history.r.outputs.marker));
 assert.equal(result.calls.some(c=>c.command==='aws'),false);
});
test('backend selection cannot omit actual history marker and fall back to a schema-valid handle',t=>{
 const {f,history}=retained(t),result=select(f,history,'');
 assert.equal(result.error?.message,'recovery-private-marker',JSON.stringify(result));assert.deepEqual(result.outputs,{});
 assert.equal(result.calls.some(c=>c.command==='aws'),false);
});
for(const [name,edit,error] of [
 ['digest substitution',m=>{m.stateHandleDigest='sha256:'+'0'.repeat(64);},'recovery-reservation-binding'],
 ['foreign bucket claim',m=>{m.resourceClaims[1]=m.resourceClaims[1].replace('external-packages','foreign-packages');},'recovery-reservation-claims'],
])test(`backend selection rejects forged ${name} without credential authority`,t=>{
 const {f,history}=retained(t),marker=JSON.parse(fs.readFileSync(history.r.outputs['reservation-marker']));edit(marker);
 const result=select(f,history,f.privateFile('hostile-marker.json',marker));
 assert.equal(result.error?.message,error,JSON.stringify(result));assert.deepEqual(result.outputs,{});
 assert.equal(result.calls.some(c=>c.command==='aws'),false);
});

test('native package ownership retains exact authenticated claims and expected S3 account owner',t=>{
 const {r,retained,f}=ownership(t);
 assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.unused.tools,0);
 const proof=JSON.parse(fs.readFileSync(r.outputs['ownership-proof']));
 assert.deepEqual(proof.resourceClaims,retained.receipt.payload.resourceClaims);
 const read=r.calls.find(c=>c.args?.includes('get-object-tagging'));
 assert.ok(read);assert.equal(read.args[read.args.indexOf('--expected-bucket-owner')+1],f.handle.providerIdentity);
});
for(const [name,mutate] of [
 ['bucket',(bucket,key)=>({bucket:'foreign-packages',key})],
 ['prefix',(bucket,key)=>({bucket,key:'components-lookalike/'+key.split('/').slice(-2).join('/')})],
 ['digest-key',(bucket,key)=>({bucket,key:key.replace(/[0-9a-f]{64}(?=\/main\.zip$)/,'0'.repeat(64))})],
])test(`native ownership denies authenticated-tag/linkage package ${name} substitution before object read`,t=>{
 const baseline=ownership(t);assert.equal(baseline.r.error,undefined,JSON.stringify(baseline.r));
 const original=baseline.state.resources[1].instances[0].attributes;
 const {r,state}=ownership(t,mutate(original.bucket,original.key));
 const fn=state.resources[0].instances[0].attributes,object=state.resources[1].instances[0].attributes;
 assert.equal(fn.s3_bucket,object.bucket);assert.equal(fn.s3_key,object.key);
 assert.equal(fn.tags['cloudopsworks-owner'],object.tags['cloudopsworks-owner']);
 assert.equal(r.error?.message,'recovery-authenticated-package-scope',JSON.stringify(r));assert.deepEqual(r.outputs,{});
 assert.equal(r.calls.length,1);assert.ok(r.calls[0].args.includes('get-function'));
 assert.equal(r.unused.tools,1,'object read must remain unconsumed after scope denial');
});

test('actual recovery S3 reads bind frozen backend owner and unlock has no application helpers',t=>{
 const {f,history}=retained(t),result=unlock(f,history);
 assert.equal(result.error,undefined,JSON.stringify(result));
 const reads=result.calls.filter(c=>c.command==='aws'&&c.args[0]==='s3api');assert.ok(reads.length>0);
 for(const read of reads){assert.ok(read.args.includes('--expected-bucket-owner'),JSON.stringify(read));assert.equal(read.args[read.args.indexOf('--expected-bucket-owner')+1],f.handle.backendIdentity.accountId);}
 assert.equal(result.calls.some(c=>/Artifact|Blob|Tree/.test(c.method||'')||c.args?.includes?.('render')||c.args?.includes?.('artifacts')),false);
 assert.equal(result.calls.filter(c=>c.args?.includes?.('force-unlock')).length,1);
});

test('actual historical destroy preparation retains proved identities and exact claims in saved-plan authority',t=>{
 const frame=destroyPreparation(t),{prepared,inspected}=frame;
 assert.equal(prepared.error,undefined,JSON.stringify(prepared));assert.equal(prepared.unused.tools,0);
 const saved=JSON.parse(fs.readFileSync(prepared.outputs['saved-plan'])),proof=JSON.parse(fs.readFileSync(inspected.outputs.proof));
 assert.deepEqual(saved.resourceIdentities,proof.resourceIdentities);assert.deepEqual(saved.resourceClaims,frame.retained.receipt.payload.resourceClaims);
 assert.equal(saved.digest,createHash('sha256').update(fs.readFileSync(path.join(saved.root,'operation.tfplan'))).digest('hex'));
 assert.equal(frame.calls.some(c=>/Artifact|Blob|Tree/.test(c.method||'')),false);
});
test('delete-only saved plan with exact addresses and bytes cannot substitute Lambda before identity',t=>{
 const frame=destroyPreparation(t,{before:changes=>{changes.find(c=>c.type==='aws_lambda_function').change.before.s3_key='components/'+'0'.repeat(64)+'/main.zip';}}),{prepared,changes}=frame;
 assert.equal(prepared.error?.message,'recovery-saved-before-identity',JSON.stringify(prepared));assert.deepEqual(prepared.outputs,{});assert.equal(prepared.unused.tools,0);
 assert.deepEqual(changes.map(c=>c.address).sort(),JSON.parse(fs.readFileSync(frame.inspected.outputs.proof)).resourceAddresses);
 for(const change of changes){assert.deepEqual(change.change.actions,['delete']);assert.equal(change.change.after,null);}
 const saved=path.join(frame.planned.outputs.directory,'destroy/operation.tfplan');
 assert.equal(fs.readFileSync(saved,'utf8'),'local native saved delete-only plan bytes');
 assert.equal(frame.calls.some(c=>c.args?.includes?.('apply')),false);
});
