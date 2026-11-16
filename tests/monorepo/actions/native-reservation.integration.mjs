// LOCAL actual-body chain; all hosted bodies and immutable workflow bytes come from product YAML.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {binary,product,prove,reserve,historical,unlock} from './native_recovery_fixture.mjs';
import {runStep} from './action_test_support.mjs';
const preflight='cd/monorepo/native/preflight/action.yml';
const canonical=v=>JSON.stringify(v===null||typeof v!=='object'?v:Array.isArray(v)?v.map(x=>JSON.parse(canonical(x))):Object.fromEntries(Object.keys(v).sort().map(k=>[k,JSON.parse(canonical(v[k]))])));
const digest=v=>'sha256:'+createHash('sha256').update(canonical(v)).digest('hex');

test('actual preflight data body uses real fresh-origin CLI without caller origin digests',t=>{
 const f=product(t),r=f.prepare();assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs.eligible,'true');
 const p=JSON.parse(fs.readFileSync(r.outputs.prepared));assert.equal(p.operation.stateHandle.moduleId,'aws-lambda');assert.equal(p.operation.stateHandleDigest,digest(p.operation.stateHandle));
 const call=r.calls.find(c=>Array.isArray(c.args)&&c.args.includes('--module-root')&&c.args.includes('plan'));const input=JSON.parse(call.input);assert.equal(Object.hasOwn(input.origin,'moduleRevision'),false);assert.equal(Object.hasOwn(input.origin,'providerLockDigest'),false);
});


test('actual preflight→writer captures durable create/readback and emits existing exact receipt marker',t=>{
 const f=product(t),{r,receipt}=reserve(f);assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs['receipt-id'],'900');
 const created=r.calls.find(c=>c.method==='rest.repos.createDeployment');assert.deepEqual(created.args.payload,receipt.payload);assert.equal(created.args.auto_merge,false);assert.deepEqual(created.args.required_contexts,[]);
 const read=r.calls.find(c=>c.method==='rest.repos.getDeployment');assert.equal(read.args.deployment_id,'900');
 const marker=JSON.parse(r.logs.find(l=>l.message?.startsWith('CLOUDOPSWORKS_STATE_V1 ')).message.slice('CLOUDOPSWORKS_STATE_V1 '.length));assert.equal(marker.receiptId,'900');assert.equal(marker.stateHandleDigest,receipt.payload.stateHandleDigest);
});
for(const [name,change] of [['existing native state',{state:{IsTruncated:false,KeyCount:1,Contents:[{Key:'some-state'}]}}],['incomplete Lambda inventory',{functions:{Functions:[],NextMarker:'more'}}],['existing Lambda',{functions:{Functions:[{FunctionName:'example'}]}}],['existing owned package object',{object:{IsTruncated:false,KeyCount:1,Contents:[{Key:'existing'}]}}]])test(`native preflight denies ${name} without mutation`,t=>{
 const f=product(t),{r}=prove(f,change);assert.ok(r.error,JSON.stringify(r));assert.equal(r.logs.some(l=>l.message?.startsWith('CLOUDOPSWORKS_PREFLIGHT_V1 ')),false);assert.equal(r.calls.some(c=>c.kind==='api'||c.args?.includes?.('apply')),false);
});
for(const [name,change] of [['wrong current attempt',{job:{run_attempt:2}}],['unsuccessful preflight',{job:{conclusion:'failure'}}],['missing native proof',{log:''}],['wrong exact readback',{readback:{id:901}}]])test(`reservation denies ${name} and never emits ownership marker`,t=>{
 const f=product(t),{r}=reserve(f,change);assert.ok(r.error,JSON.stringify(r));assert.equal(r.logs.some(l=>l.message?.startsWith('CLOUDOPSWORKS_STATE_V1 ')),false);
});

test('actual writer request/readback/marker→immutable product caller/workflows→history→backend select works after original payload expiry',t=>{
 const f=product(t),produced=reserve(f),retained=historical(f,produced);assert.equal(retained.r.error,undefined,JSON.stringify(retained.r));
 const select=runStep('cd/monorepo/recovery/backend/action.yml','select',{realCli:binary,context:{repo:f.repo},env:{...f.env,STATE_HANDLE:retained.r.outputs['state-handle'],RESERVATION_MARKER:retained.r.outputs['reservation-marker'],DEPLOYMENT_STATE_CONF:'s3:\n  bucket: state-example\n  region: us-east-1\n  use_lockfile: true\n  auth_ref: aws-state\n',AUTH_BINDINGS:JSON.stringify(f.bindings),OPERATION:'unlock',LOCK_ID:'native-lock'}});assert.equal(select.error,undefined,JSON.stringify(select));
 assert.ok(select.outputs.selection);assert.equal(JSON.parse(fs.readFileSync(select.outputs.selection)).digest,retained.receipt.payload.stateHandleDigest);
 const recoveryCalls=[...retained.r.calls,...retained.host.calls,...retained.located.calls,...select.calls];assert.equal(recoveryCalls.some(c=>/Artifact|Blob|Tree/.test(c.method||'')||c.args?.includes?.('render')||c.args?.includes?.('artifacts')),false,'history/unlock does not retrieve original payload or app source');
});
for(const [name,change] of [['wrong writer attempt',{jobs:j=>j[1].run_attempt=2}],['arbitrary writer name',{jobs:j=>j[1].name='untrusted'}],['missing retained writer marker',{stateLog:''}],['missing source-stage proof',{stageLog:''}],['foreign reusable SHA',{host:{referenced_workflows:[]}}]])test(`history denies ${name} even with captured schema-valid handle`,t=>{
 const f=product(t),retained=historical(f,reserve(f),change);assert.ok(retained.r.error,JSON.stringify(retained.r));assert.deepEqual(retained.r.outputs,{});
});
test('failed producer job with durable completed reservation step is recovery-only, not forward success',t=>{
 const f=product(t),retained=historical(f,reserve(f),{writerConclusion:'failure'});assert.equal(retained.r.error,undefined,JSON.stringify(retained.r));assert.ok(retained.r.outputs['state-handle']);assert.equal(retained.r.outputs.success,undefined);
});
test('captured actual producer→history→conditional backend ownership→pre-INIT→pre-unlock→exact native force-unlock after payload/config expiry',t=>{
 const f=product(t),produced=reserve(f);
 for(const name of ['policy','stage-plan.json','stage-manifest.json','plan.json','manifest.json','configuration.json'])fs.rmSync(path.join(f.work,name),{recursive:true,force:true});
 const retained=historical(f,produced);assert.equal(retained.r.error,undefined,JSON.stringify(retained.r));
 const recovered=unlock(f,retained);assert.equal(recovered.error,undefined,JSON.stringify(recovered));
 const calls=[...retained.r.calls,...retained.host.calls,...retained.located.calls,...recovered.calls];
 assert.equal(calls.some(c=>/Artifact|Blob|Tree/.test(c.method||'')||c.args?.includes?.('render')||c.args?.includes?.('artifacts')),false);
 const release=calls.filter(c=>c.args?.includes?.('force-unlock'));assert.equal(release.length,1);assert.equal(release[0].args.at(-1),'native-lock');
});
for(const before of ['beforeInit','beforeUnlock'])test(`captured reservation recovery denies changed state ${before} and retains reservation/native resources`,t=>{
 const f=product(t),retained=historical(f,reserve(f)),recovered=unlock(f,retained,{[before]:true});assert.equal(recovered.error?.message,'recovery-precondition-changed');assert.equal(recovered.calls.some(c=>c.args?.includes?.('force-unlock')),false);
 if(before==='beforeInit')assert.equal(recovered.calls.some(c=>c.command==='terragrunt'),false);
});
test('closure history accepts actual post-tag SourceContext while keeping distinct default HOST and merge source',t=>{
 const f=product(t,{closure:true}),produced=reserve(f),retained=historical(f,produced);assert.notEqual(f.host.head_sha,f.plan.headSha);
 assert.equal(produced.p.sourceContext.event,'push');assert.equal(produced.p.sourceContext.ref,'refs/tags/v1.2.3');assert.equal(produced.p.sourceContext.baseRef,'');
 assert.equal(retained.r.error,undefined,JSON.stringify(retained.r));
});
for(const [name,change,error]of [['moved source tag',{tagSha:'f'.repeat(40)},'history-source-tag'],['unmerged retained PR',{pull:{merged:false}},'history-source-merge'],['different actual merge',{pull:{merge_commit_sha:'f'.repeat(40)}},'history-source-merge']])test(`closure historical ownership denies ${name} without rewriting HOST/source`,t=>{
 const f=product(t,{closure:true}),retained=historical(f,reserve(f),change);assert.equal(retained.r.error?.message,error,JSON.stringify(retained.r));assert.deepEqual(retained.r.outputs,{});
});
for(const [name,change,error]of [
 ['same native state already reserved',{entries:receipt=>[receipt]},'reservation-existing-owner-or-collision'],
 ['changed independently recomputed policy proof',{log:log=>{const prefix='CLOUDOPSWORKS_PREFLIGHT_V1 ',proof=JSON.parse(log.slice(prefix.length));proof.policyDigest='sha256:'+'f'.repeat(64);return prefix+JSON.stringify(proof);}},'reservation-preflight-proof'],
 ['duplicated actual preflight marker',{log:log=>log+'\n'+log},'reservation-preflight-proof'],
])test(`actual writer denies ${name} before create, retaining existing history`,t=>{
 const f=product(t),{r}=reserve(f,change);assert.equal(r.error?.message,error,JSON.stringify(r));assert.equal(r.calls.some(c=>c.method==='rest.repos.createDeployment'),false);assert.equal(r.logs.some(l=>l.message?.startsWith('CLOUDOPSWORKS_STATE_V1 ')),false);
});
// Explicit byte construction prevents confusing real GitHub log separators with literal backslash escapes.
for(const [name,bytes]of [['LF',[10]],['CRLF',[13,10]]]){
 const eol=String.fromCharCode(...bytes),timestamp='2026-11-13T12:00:00.000Z ';
 const log=records=>['Preparing exact native proof',...records,'Completed exact native proof'].map(line=>timestamp+line).join(eol)+eol;
 test(`timestamped actual preflight ${name} multiline logs authorize the real writer`,t=>{
  const f=product(t),produced=reserve(f,{log:marker=>log([marker])});
  assert.equal(log(['record']).includes(String.fromCharCode(10)),true);
  assert.equal(log(['record']).includes(String.fromCharCode(92)+'n'),false);
  assert.equal(produced.r.error,undefined,JSON.stringify(produced.r));assert.equal(produced.r.outputs['receipt-id'],'900');
 });
 test(`timestamped actual stage/state ${name} multiline logs retain exact-ID historical authority`,t=>{
  const f=product(t),produced=reserve(f),prefix='CLOUDOPSWORKS_STATE_V1 ';
  const actual=produced.r.logs.find(line=>line.message?.startsWith(prefix)).message;
  const stagePrefix='CLOUDOPSWORKS_STAGE_V1 ',noise=JSON.parse(f.stageLog.slice(stagePrefix.length));noise.artifactId='701';
  const retained=historical(f,produced,{stageLog:log([stagePrefix+JSON.stringify(noise),f.stageLog]),stateLog:log([actual])});
  assert.equal(retained.r.error,undefined,JSON.stringify(retained.r));assert.equal(JSON.parse(retained.r.outputs.marker).sourceStage.artifactId,'700');
 });
 test(`timestamped duplicate preflight ${name} multiline markers deny the real writer`,t=>{
  const f=product(t),produced=reserve(f,{log:marker=>log([marker,marker])});
  assert.equal(produced.r.error?.message,'reservation-preflight-proof');assert.equal(produced.r.calls.some(call=>call.method==='rest.repos.createDeployment'),false);
 });
 test(`timestamped duplicate matching state ${name} multiline markers deny historical authority`,t=>{
  const f=product(t),produced=reserve(f),prefix='CLOUDOPSWORKS_STATE_V1 ';
  const actual=produced.r.logs.find(line=>line.message?.startsWith(prefix)).message;
  const retained=historical(f,produced,{stageLog:log([f.stageLog]),stateLog:log([actual,actual])});
  assert.equal(retained.r.error?.message,'history-marker-count');assert.deepEqual(retained.r.outputs,{});
 });
}
