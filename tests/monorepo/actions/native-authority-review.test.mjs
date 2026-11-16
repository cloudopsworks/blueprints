// LOCAL independent review: matching authority comes only from actual producer bodies.
// Altered records below are adversarial log noise, never positive ownership fixtures.
import test from 'node:test';
import assert from 'node:assert/strict';
import {product,reserve,historical} from './native_recovery_fixture.mjs';
import {runStep} from './action_test_support.mjs';

const prefix='CLOUDOPSWORKS_STATE_V1 ';
function produced(t){
 const f=product(t),writer=reserve(f);
 assert.equal(writer.r.error,undefined,JSON.stringify(writer.r));
 const log=writer.r.logs.find(item=>item.message?.startsWith(prefix)).message;
 return {f,writer,log};
}
function changed(log,edit){
 const value=JSON.parse(log.slice(prefix.length));edit(value);
 return prefix+JSON.stringify(value);
}
function denied(result,error){
 assert.equal(result.r.error?.message,error,JSON.stringify(result.r));
 assert.deepEqual(result.r.outputs,{});
 assert.equal(result.r.calls.some(call=>call.kind==='exec'||call.method?.includes('createDeployment')),false);
}

test('history ignores an unrelated receipt marker while retaining the actual producer binding',t=>{
 const {f,writer,log}=produced(t);
 const noise=changed(log,value=>{value.receiptId='901';value.stateHandleDigest='sha256:'+'f'.repeat(64);});
 const result=historical(f,writer,{stateLog:noise+'\n'+log});
 assert.equal(result.r.error,undefined,JSON.stringify(result.r));
 assert.ok(result.r.outputs['state-handle']);
 assert.equal(JSON.parse(result.r.outputs.marker).receiptId,'900');
});

for(const [name,mutate,error] of [
 ['duplicate matching receipt',log=>log+'\n'+log,'history-marker-count'],
 ['conflicting matching receipt',log=>log+'\n'+changed(log,value=>value.stateHandleDigest='sha256:'+'f'.repeat(64)),'history-marker-count'],
 ['extra matching authority field',log=>changed(log,value=>value.authorized=true),'history-state-binding'],
 ['wrong source-stage ID',log=>changed(log,value=>value.sourceStage.artifactId='701'),'history-marker-count'],
 ['foreign receipt marker only',log=>changed(log,value=>value.receiptId='901'),'history-marker-count'],
])test(`history denies ${name} without publishing a retained handle`,t=>{
 const {f,writer,log}=produced(t);
 denied(historical(f,writer,{stateLog:mutate(log)}),error);
});

test('history rejects duplicate successful writer jobs rather than choosing one',t=>{
 const {f,writer}=produced(t);
 denied(historical(f,writer,{jobs:jobs=>jobs.push({...jobs[1],id:804})}),'history-writer-identity');
});

test('history ignores an unrelated stage ID after matching the actual reservation source stage',t=>{
 const {f,writer}=produced(t),stagePrefix='CLOUDOPSWORKS_STAGE_V1 ';
 const unrelated=JSON.parse(f.stageLog.slice(stagePrefix.length));unrelated.artifactId='701';
 const result=historical(f,writer,{stageLog:stagePrefix+JSON.stringify(unrelated)+'\n'+f.stageLog});
 assert.equal(result.r.error,undefined,JSON.stringify(result.r));
 assert.ok(result.r.outputs['state-handle']);
 assert.equal(JSON.parse(result.r.outputs.marker).sourceStage.artifactId,'700');
});

test('history rejects duplicate matching stage markers instead of accepting the last log line',t=>{
 const {f,writer}=produced(t);
 denied(historical(f,writer,{stageLog:f.stageLog+'\n'+f.stageLog}),'history-marker-count');
});

for(const closure of [false,true])test(`current protected policy uses ${closure?'original PR base, not closure host default':'default branch for manual delivery'}`,t=>{
 const f=product(t,{closure}),expected=closure?'support/1.0':'main';
 const sha=branch=>branch==='main'?'e'.repeat(40):'d'.repeat(40);
 const result=runStep('cd/monorepo/native/preflight/action.yml','policy-ref',{
  context:{repo:f.repo},env:{...f.env,CLOSURE:String(closure),BASE_REF:closure?'support/1.0':'',HOST_REF:'refs/heads/main'},
  api:[{method:'rest.repos.get',result:{data:{id:12345,default_branch:'main'}}},{method:'rest.repos.getBranch',result:{data:{protected:true,commit:{sha:sha(expected)}}}}],
 });
 assert.equal(result.error,undefined,JSON.stringify(result));
 assert.equal(result.calls.find(call=>call.method==='rest.repos.getBranch').args.branch,expected);
 assert.equal(result.outputs.sha,sha(expected));
});
