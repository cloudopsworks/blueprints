import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {runStep} from './action_test_support.mjs';
const action='cd/tasks/repo/context/action.yml';
const host='a'.repeat(40),blueprint='b'.repeat(40),policy='c'.repeat(40),merge='d'.repeat(40),baseTip='e'.repeat(40),head='f'.repeat(40);
function fixture(change={}){
 const caller='.github/workflows/composite-first-closure.yml',bytes=fs.readFileSync(fileURLToPath(new URL('../../../../monorepo-app-template/'+caller,import.meta.url)));
 const blob=createHash('sha1').update(`blob ${bytes.length}\0`).update(bytes).digest('hex');
 const pr={number:17,state:'closed',merged:true,merge_commit_sha:merge,base:{ref:'support/1.2',sha:baseTip,repo:{id:123}},head:{ref:'arbitrary-topic',sha:head,repo:{id:123}},...change.pull};
 const event={...pr,base:{...pr.base,sha:policy},...change.event};
 return {env:{GITHUB_REPOSITORY_ID:'123',GITHUB_RUN_ID:'456',GITHUB_RUN_ATTEMPT:'2'},context:{repo:{owner:'example',repo:'mixed'},payload:{action:'closed',number:17,pull_request:event}},api:[
 {method:'rest.repos.get',result:{data:{id:123,default_branch:'master'}}},
 {method:'rest.actions.getWorkflowRunAttempt',result:{data:{id:456,run_attempt:2,repository:{id:123},event:'pull_request_target',path:caller,head_sha:host,head_branch:'master',pull_requests:[],referenced_workflows:[{path:'cloudopsworks/blueprints/.github/workflows/monorepo-delivery-slice.yml@v5.11.0',sha:blueprint}]}}},
 {method:'rest.repos.getBranch',args:{branch:'master'},result:{data:{protected:true,commit:{sha:host}}}},
 {method:'rest.repos.getContent',args:{ref:host,path:caller},result:{data:{type:'file',encoding:'base64',content:bytes.toString('base64'),sha:blob}}},
 {method:'rest.git.getRef',result:{data:{object:{type:'commit',sha:blueprint}}}},
 {method:'rest.pulls.get',args:{pull_number:17},result:{data:pr}},
 {method:'rest.repos.getBranch',args:{branch:'support/1.2'},result:{data:{protected:true,commit:{sha:baseTip}}}},
 {method:'rest.repos.compareCommitsWithBasehead',args:{basehead:policy+'...'+baseTip},result:{data:{status:'ahead',base_commit:{sha:policy},merge_base_commit:{sha:policy}}}},
 {method:'rest.repos.compareCommitsWithBasehead',args:{basehead:policy+'...'+merge},result:{data:{status:'ahead',base_commit:{sha:policy},merge_base_commit:{sha:policy}}}},
 {method:'rest.repos.compareCommitsWithBasehead',args:{basehead:merge+'...'+baseTip},result:{data:change.mergeRelation||{status:'ahead',base_commit:{sha:merge},merge_base_commit:{sha:merge}}}},
 ]};
}
test('closure preserves distinct captured default host, original protected-base policy and merged app source',()=>{
 const r=runStep(action,'verify',fixture());assert.equal(r.error,undefined,JSON.stringify(r));
 assert.equal(r.unused.api,0);assert.equal(r.outputs['source-sha'],merge);assert.equal(r.outputs['policy-sha'],policy);
 assert.equal(r.outputs['host-ref'],'refs/heads/master');assert.equal(r.outputs['base-ref'],'support/1.2');
 assert.equal(r.outputs['pr-number'],'17');assert.equal(r.outputs.closure,'true');
 assert.notEqual(r.outputs['source-sha'],host);assert.notEqual(r.outputs['policy-sha'],baseTip);
 assert.ok(r.calls.some(call=>call.method==='rest.repos.getContent'&&call.args.ref===host));
});
for(const [name,change]of [
 ['unmerged close',{pull:{merged:false},event:{merged:false}}],
 ['contradictory event base',{event:{base:{ref:'support/other',sha:policy,repo:{id:123}}}}],
 ['contradictory merge SHA',{event:{merge_commit_sha:'9'.repeat(40)}}],
 ['foreign base repository',{pull:{base:{ref:'support/1.2',sha:baseTip,repo:{id:124}}}}],
 ['missing original event base SHA',{event:{base:{ref:'support/1.2',repo:{id:123}}}}],
])test(`closure denies ${name} without tag/source authority`,()=>{
 const r=runStep(action,'verify',fixture(change));assert.ok(r.error);assert.deepEqual(r.outputs,{});
 assert.equal(r.calls.some(call=>call.method?.includes('create')),false);
});

test('closure denies merge commit outside the current protected base lineage',()=>{const r=runStep(action,'verify',fixture({mergeRelation:{status:'diverged',base_commit:{sha:merge},merge_base_commit:{sha:policy}}}));assert.ok(r.error);assert.deepEqual(r.outputs,{});});

test('closure lifecycle uses native config-only classifier with captured host and actual base',()=>{const result={eligible:false,reason:'closure-base-excluded',refClass:'',environment:'',deploymentEnabled:true,isRelease:false,isPreRelease:false,hasQualifier:false,targetName:'',deploymentName:'',protectedEnvironment:''};const r=runStep(action,'lifecycle',{env:{DIRECTORY:'/private/policy',HOST_REF:'refs/heads/master',BASE_REF:'develop'},tools:[{args:['components','lifecycle','--config-only','--workdir','/private/policy','--event','pull_request_closed','--ref','refs/heads/master','--base-ref','develop','--json'],result:{stdout:JSON.stringify(result)}}]});assert.equal(r.error,undefined);assert.equal(r.outputs.eligible,'false');});
test('historical closed-PR context verifies host code without reusing current event or conflating host and source',()=>{
 const f=fixture();f.env.CONTEXT_RUN_ID='456';f.env.CONTEXT_RUN_ATTEMPT='2';f.api=f.api.slice(0,5);f.context.payload={};
 const r=runStep(action,'verify',f);assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs['source-sha'],undefined);assert.equal(r.outputs.closure,undefined);assert.equal(r.outputs['run-id'],'456');
});

function association(){return{number:17,base:{ref:'support/1.2',sha:policy,repo:{id:123}},head:{ref:'arbitrary-topic',sha:head,repo:{id:123}}};}
for(const [name,mutate] of [
 ['array base repo ID',a=>[{...a,base:{...a.base,repo:{id:[123]}}}]],['array head repo ID',a=>[{...a,head:{...a.head,repo:{id:[123]}}}]],
 ['object container',()=>({malformed:true})],['null container',()=>null],['null entry',()=>[null]],
 ['wrong PR',a=>[{...a,number:999}]],['foreign base repo',a=>[{...a,base:{...a.base,repo:{id:999}}}]],
 ['wrong protected base',a=>[{...a,base:{...a.base,ref:'develop'}}]],['foreign head repo',a=>[{...a,head:{...a.head,repo:{id:999}}}]],
 ['unrelated head',a=>[{...a,head:{...a.head,sha:'0'.repeat(40)}}]],['wrong topic ref',a=>[{...a,head:{...a.head,ref:'other'}}]],
 ['missing base SHA',a=>{delete a.base.sha;return[a];}],['duplicate association',a=>[a,a]],
])test(`closure denies workflow-run ${name} before any authority output`,()=>{const f=fixture();f.api[1].result.data.pull_requests=mutate(association());const r=runStep(action,'verify',f);assert.equal(r.error?.message,'context-run-pull-association',JSON.stringify(r));assert.deepEqual(r.outputs,{});assert.equal(r.calls.some(c=>c.method?.includes('create')),false);});
test('closure corroborates a nonempty association without replacing original policy or captured host',()=>{const f=fixture();f.api[1].result.data.pull_requests=[association()];const r=runStep(action,'verify',f);assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs['policy-sha'],policy);assert.equal(r.outputs['source-sha'],merge);assert.equal(r.outputs['host-ref'],'refs/heads/master');});
test('canonical closure permits missing association only with existing full event/PR corroboration',()=>{const f=fixture();delete f.api[1].result.data.pull_requests;const r=runStep(action,'verify',f);assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs['pr-number'],'17');});
for(const mismatch of [false,true])test(`historical context ${mismatch?'rejects contradictory':'corroborates'} nonempty association without borrowing current event`,()=>{const f=fixture(),pull=f.api[5];f.env.CONTEXT_RUN_ID='456';f.env.CONTEXT_RUN_ATTEMPT='2';f.api=f.api.slice(0,5);f.api[1].result.data.pull_requests=[association()];f.context.payload={action:'closed',pull_request:{number:999}};if(mismatch)pull.result.data.head={...pull.result.data.head,sha:'9'.repeat(40)};f.api.push(pull);const r=runStep(action,'verify',f);if(mismatch){assert.equal(r.error?.message,'context-run-pull-association',JSON.stringify(r));assert.deepEqual(r.outputs,{});}else{assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs['pr-number'],'17');assert.equal(r.outputs['source-sha'],undefined);assert.equal(r.outputs['policy-sha'],undefined);assert.equal(r.outputs.closure,undefined);assert.equal(r.unused.api,0);}});
