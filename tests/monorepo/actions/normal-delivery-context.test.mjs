import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {root,runStep} from './action_test_support.mjs';
const action='cd/tasks/repo/context/action.yml';
const sha='a'.repeat(40),bp='b'.repeat(40),host='c'.repeat(40);
const content=(file,ref)=>{const bytes=fs.readFileSync(path.join(root,'..','monorepo-app-template',file));return {method:'rest.repos.getContent',args:{path:file,ref},result:{data:{type:'file',encoding:'base64',content:bytes.toString('base64'),sha:createHash('sha1').update(`blob ${bytes.length}\0`).update(bytes).digest('hex')}}};};
const ref=()=>({method:'rest.git.getRef',args:{owner:'cloudopsworks',repo:'blueprints',ref:'tags/v5.11.0'},result:{data:{object:{type:'commit',sha:bp}}}});
function fixture(change={}){
 const origin={event:'push',ref:'refs/heads/develop',hostSha:sha,callerPath:'.github/workflows/main-build.yml',callerSha:sha,blueprintSha:bp,sourceSha:sha,sourceRef:'refs/heads/develop',sourceRepositoryId:'123',trustedSource:true,prNumber:'0',headRepositoryId:'',headSha:'',headRef:'',baseRef:'',policySha:'',closed:false,merged:false,checkId:'91',checkName:'monorepo-delivery/456/2',...change.origin};
 const run={id:456,run_attempt:2,repository:{id:123},event:'push',path:'.github/workflows/main-build.yml',head_sha:sha,head_branch:'develop',status:'completed',conclusion:'success',pull_requests:[],referenced_workflows:['monorepo-main-build.yml','monorepo-ci.yml'].map(name=>({path:'cloudopsworks/blueprints/.github/workflows/'+name+'@v5.11.0',sha:bp})),...change.run};
 const actual={id:700,run_attempt:1,repository:{id:123},event:'workflow_run',path:'.github/workflows/delivery.yml',head_sha:host,head_branch:'master',referenced_workflows:[{path:'cloudopsworks/blueprints/.github/workflows/monorepo-delivery.yml@v5.11.0',sha:bp}],...change.host};
 return {env:{CONTEXT_MODE:'delivery',CONTEXT_RUN_ID:'456',CONTEXT_RUN_ATTEMPT:'2',GITHUB_REPOSITORY_ID:'123',GITHUB_RUN_ID:'700',GITHUB_RUN_ATTEMPT:'1',GITHUB_SHA:host,GITHUB_WORKFLOW_SHA:host,GITHUB_REF:'refs/heads/master',ORIGIN:JSON.stringify(origin)},
 context:{eventName:'workflow_run',repo:{owner:'example',repo:'mixed'},payload:{workflow_run:{id:456,run_attempt:2}}},api:[
 {method:'rest.repos.get',result:{data:{id:123,default_branch:'master'}}},
 {method:'rest.actions.getWorkflowRunAttempt',args:{run_id:'456',attempt_number:'2'},result:{data:run}},
 ref(),content('.github/workflows/main-build.yml',sha),
 {method:'rest.actions.getWorkflowRunAttempt',args:{run_id:'700',attempt_number:'1'},result:{data:actual}},
 ref(),content('.github/workflows/delivery.yml',host),
 ]};
}
const empty=()=>({totalCount:0,nodes:[],pageInfo:{hasNextPage:false}});
const policy=()=>({requiresApprovingReviews:true,requiredApprovingReviewCount:1,requiredStatusCheckContexts:['checkpr / Check Pull Request'],isAdminEnforced:true,dismissesStaleReviews:true,requiresStatusChecks:true,requiresStrictStatusChecks:true,allowsForcePushes:false,bypassPullRequestAllowances:empty(),bypassForcePushAllowances:empty()});
const branch=(name,commit)=>[{method:'rest.repos.getBranch',args:{branch:name},result:{data:{protected:true,commit:{sha:commit}}}},{method:'graphql',args:{ref:'refs/heads/'+name},result:{repository:{ref:{branchProtectionRule:policy()}}}}];
function execute(f){
 const raw=runStep(action,'normal',f);if(raw.error)return raw;
 assert.deepEqual(raw.unused,{api:0,tools:0,fetches:0});
 const proof='cd/tasks/repo/context/protected-source/action.yml',facts=JSON.parse(raw.outputs['origin-facts']);
 const env={...f.env,FACTS:JSON.stringify(facts),HOST_REF:raw.outputs['protection-host-ref'],HOST_SHA:raw.outputs['protection-host-sha'],TAG:'false'};
 const identity=runStep(proof,'identity',{env,context:f.context,api:[{method:'rest.repos.get',result:{data:{id:123}}}]});assert.equal(identity.error,undefined,JSON.stringify(identity));
 const calls=[];
 if(['pull_request','pull_request_target'].includes(facts.event))calls.push(...branch(facts.baseRef,facts.policySha));
 if(facts.event==='pull_request_target')calls.push(...branch(facts.ref.slice(11),facts.hostSha),{method:'rest.repos.compareCommitsWithBasehead',args:{basehead:facts.policySha+'...'+facts.sourceSha},result:{data:{status:'ahead',base_commit:{sha:facts.policySha},merge_base_commit:{sha:facts.policySha}}}});
 calls.push(...branch(env.HOST_REF.slice(11),env.HOST_SHA),...branch(facts.sourceRef.slice(11),facts.sourceSha));
 const verified=runStep(proof,'verify',{env,context:f.context,api:calls});if(verified.error)return verified;
 assert.deepEqual(verified.unused,{api:0,tools:0,fetches:0});
 return runStep(action,'projection',{env:{IDENTITY:JSON.stringify(raw.outputs),ORIGIN:f.env.ORIGIN,TRUSTED:verified.outputs['trusted-source']}});
}
test('actual default-branch workflow_run authenticates separate original caller/source and exact delivery caller',()=>{
 const r=execute(fixture());assert.equal(r.error,undefined,JSON.stringify(r));
 assert.equal(r.outputs['source-sha'],sha);assert.equal(r.outputs['run-id'],'456');assert.equal(r.outputs['delivery-check-id'],'91');assert.deepEqual(r.unused,{api:0,tools:0,fetches:0});
});
for(const [label,change]of [['nondefault continuation',{host:{head_branch:'develop'}}],['wrong real event',{host:{event:'workflow_dispatch'}}],['incomplete origin',{run:{status:'in_progress'}}],['failed main CI',{run:{conclusion:'failure'}}],['rewritten source',{origin:{sourceSha:'d'.repeat(40)}}],['wrong captured ref',{origin:{sourceRef:'refs/heads/master'}}]])test(`delivery context denies ${label}`,()=>{
 const r=execute(fixture(change));assert.ok(r.error,JSON.stringify(r));assert.deepEqual(r.outputs,{});
});

test('historical closure retains original native host and captured base while actual delivery host differs',()=>{
 const originalHost='d'.repeat(40),caller='e'.repeat(40),merge='f'.repeat(40),base='9'.repeat(40);
 const f=fixture({origin:{event:'pull_request_target',ref:'refs/heads/old-default',hostSha:originalHost,callerPath:'.github/workflows/pr-close.yaml',callerSha:caller,sourceSha:merge,sourceRef:'refs/heads/support/v1',prNumber:'17',headRepositoryId:'456',headSha:sha,headRef:'feature/topic',baseRef:'support/v1',policySha:base,closed:true,merged:true},run:{event:'pull_request_target',path:'.github/workflows/pr-close.yaml',head_sha:originalHost,head_branch:'old-default',conclusion:'failure',referenced_workflows:['monorepo-pr-close.yml','monorepo-closure.yml','monorepo-ci.yml'].map(name=>({path:'cloudopsworks/blueprints/.github/workflows/'+name+'@v5.11.0',sha:bp}))}});
 f.api[3]=content('.github/workflows/pr-close.yaml',caller);
 f.api.push({method:'rest.pulls.get',args:{pull_number:17},result:{data:{number:17,state:'closed',merged:true,merge_commit_sha:merge,head:{sha,ref:'feature/topic',repo:{id:456}},base:{sha:'8'.repeat(40),ref:'support/v1',repo:{id:123}}}}});
 const r=execute(f);assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs['source-sha'],merge);assert.equal(r.outputs['policy-sha'],base);assert.equal(r.outputs['host-ref'],'refs/heads/old-default');
});
