import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {runStep} from './action_test_support.mjs';
const action='ci/monorepo/plan/endorsement/action.yml';
const digest='sha256:'+'a'.repeat(64),sha='b'.repeat(40);
function origin(extra={}) {return {repositoryId:'123',runId:'456',runAttempt:'2',event:'push',ref:'refs/heads/develop',hostSha:sha,callerPath:'.github/workflows/main-build.yml',callerSha:sha,blueprintSha:'c'.repeat(40),sourceSha:sha,sourceRef:'refs/heads/develop',sourceRepositoryId:'123',trustedSource:true,plannerJobId:'999',artifactId:'789',artifactName:'monorepo-plan-456-2',archiveDigest:digest,planDigest:digest,checkId:'91',checkName:'monorepo-delivery/456/2',checkAppId:'15368',checkExternalId:'cloudopsworks:123:456:2',prNumber:'0',headRepositoryId:'',headSha:'',headRef:'',baseRef:'',policySha:'',closed:false,merged:false,...extra};}
const planner={repositoryId:'123',runId:'456',runAttempt:'2',artifactId:'789',artifactName:'monorepo-plan-456-2',archiveDigest:digest};
const job=(name,id)=>({id,name,run_id:456,run_attempt:2,status:'completed',conclusion:'success'});
function fixture(change={}) {
 const record=origin(change.record),jobs=[job('lifecycle / ci / monorepo-ci-origin',998),job('lifecycle / ci / monorepo-ci-plan',999),job('lifecycle / ci / monorepo-ci-required',996),job('lifecycle / monorepo-ci-origin-init',997)];
 return {env:{MODE:'origin-verify',CALLER_MODE:'normal-main',ARTIFACT_ID:'',ARCHIVE_DIGEST:'',RUN_ID:'456',RUN_ATTEMPT:'2',GITHUB_REPOSITORY_ID:'123'},api:[
 {method:'rest.actions.getWorkflowRunAttempt',result:{data:{id:456,run_attempt:2,repository:{id:123},event:'push',path:'.github/workflows/main-build.yml',referenced_workflows:['monorepo-main-build.yml','monorepo-ci.yml'].map(name=>({path:'cloudopsworks/blueprints/.github/workflows/'+name+'@v5.11.0',sha:'c'.repeat(40)}))}}},
 {method:'rest.actions.listJobsForWorkflowRunAttempt',result:{data:{jobs:change.jobs ? [...change.jobs,...jobs.filter(j=>[996,997].includes(j.id))] : jobs}}},
 {method:'rest.git.getRef',result:{data:{object:{type:'commit',sha:'c'.repeat(40)}}}},
 ...[998,999].map(id=>({method:'request:GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs',args:{job_id:id},result:{status:302,headers:{location:`https://logs.invalid/${id}`}}}))],
 fetches:[{url:'https://logs.invalid/998',body:change.logs??'CLOUDOPSWORKS_ORIGIN_V1 '+JSON.stringify(record)},
 {url:'https://logs.invalid/999',body:'CLOUDOPSWORKS_STAGE_V1 '+JSON.stringify({...planner,...change.planner})}]};
}
test('independent second origin-writer edge and original planner edge expose exact locators, never an authorization boolean',()=>{
 const r=runStep(action,'verify',fixture()); assert.equal(r.error,undefined,JSON.stringify(r));
 assert.equal(r.outputs['artifact-id'],'789');assert.equal(r.outputs['planner-job-id'],'999');
 assert.deepEqual(JSON.parse(r.outputs.origin),origin());assert.deepEqual(r.unused,{api:0,tools:0,fetches:0});
});
for(const [label,change] of [
 ['duplicate origin',{logs:('CLOUDOPSWORKS_ORIGIN_V1 '+JSON.stringify(origin())+'\n').repeat(2)}],
 ['unknown origin field',{record:{arbitrary:true}}],['wrong origin attempt',{record:{runAttempt:'1'}}],

 ['wrong planner job ID',{record:{plannerJobId:'997'}}],['planner archive changed',{planner:{archiveDigest:'sha256:'+'d'.repeat(64)}}],
 ['old writer attempt',{jobs:[job('lifecycle / ci / monorepo-ci-plan',999),{...job('lifecycle / ci / monorepo-ci-origin',998),run_attempt:1}]}],
 ['unknown writer prefix',{jobs:[job('lifecycle / ci / monorepo-ci-plan',999),job('monorepo-ci-origin',998)]}],
 ['malformed canonical line',{logs:'CLOUDOPSWORKS_ORIGIN_V1 '+JSON.stringify(origin(),null,1)}],
 ['oversized proof',{logs:'CLOUDOPSWORKS_ORIGIN_V1 '+' '.repeat(65537)}],
])test(`second edge denies ${label}`,()=>{const r=runStep(action,'verify',fixture(change)),expected={'duplicate origin':'origin-marker-count','unknown origin field':'origin-marker-binding','wrong origin attempt':'origin-marker-binding','wrong planner job ID':'origin-marker-binding','planner archive changed':'planner-marker-binding','old writer attempt':'planner-job-status','unknown writer prefix':'planner-job-identity','oversized proof':'origin-marker-bound'}[label];assert.equal(label==='malformed canonical line'?r.error?.name:r.error?.message,label==='malformed canonical line'?'SyntaxError':expected,JSON.stringify(r));assert.equal(r.outputs.origin,undefined);assert.equal(r.outputs['artifact-id'],undefined);});
test('origin emission binds typed plan digest and native original host before producing canonical proof',()=>{
 const record=origin();const facts={...record};for(const key of ['repositoryId','runId','runAttempt','plannerJobId','artifactId','artifactName','archiveDigest','planDigest','checkId','checkName','checkAppId','checkExternalId'])delete facts[key];
 const r=runStep(action,'origin',{env:{ORIGIN_FACTS:JSON.stringify(facts),RUN_ID:'456',RUN_ATTEMPT:'2',GITHUB_RUN_ID:'456',GITHUB_RUN_ATTEMPT:'2',GITHUB_REPOSITORY_ID:'123',GITHUB_WORKFLOW_SHA:sha,BLUEPRINT_SHA:'c'.repeat(40),SOURCE_TRUSTED:'true',GITHUB_SHA:sha,GITHUB_REF:'refs/heads/develop',
  PLAN_SOURCE:sha,PLAN_DIGEST:digest,PLAN_JOB_ID:'999',ARTIFACT_ID:'789',ARCHIVE_DIGEST:digest,
  CHECK:JSON.stringify({checkId:'91',checkName:'monorepo-delivery/456/2',checkAppId:'15368',checkExternalId:'cloudopsworks:123:456:2',sourceSha:sha})},context:{eventName:'push',repo:{owner:'example',repo:'mixed'},payload:{}},api:[{method:'rest.actions.getWorkflowRunAttempt',result:{data:{id:456,run_attempt:2,repository:{id:123},head_sha:sha,path:'.github/workflows/main-build.yml',event:'push',head_branch:'develop',referenced_workflows:[{path:'cloudopsworks/blueprints/.github/workflows/monorepo-ci.yml@v5.11.0',sha:'c'.repeat(40)}]}}}]});
 assert.equal(r.error,undefined,JSON.stringify(r));const log=r.logs.find(x=>x.kind==='info')?.message;assert.ok(log?.startsWith('CLOUDOPSWORKS_ORIGIN_V1 '));
 assert.deepEqual(JSON.parse(log.slice('CLOUDOPSWORKS_ORIGIN_V1 '.length)),record);
});
test('origin writer rejects retained earlier-attempt planner/initializer routing',()=>{
 const r=runStep(action,'origin',{env:{RUN_ID:'456',RUN_ATTEMPT:'1',GITHUB_RUN_ID:'456',GITHUB_RUN_ATTEMPT:'2'}});
 assert.ok(r.error);assert.deepEqual(r.logs,[]);
});
function initializerFixture(change={}) {
 const f=fixture();f.env.MODE='origin-emit';f.env.ARTIFACT_ID='789';f.env.ARCHIVE_DIGEST=digest;f.env.CHECK_ID='91';
 const ack={repositoryId:'123',runId:'456',runAttempt:'2',checkId:'91',checkName:'monorepo-delivery/456/2',checkAppId:'15368',checkExternalId:'cloudopsworks:123:456:2',...change.ack};
 Object.assign(f.api[1].result.data.jobs.find(j=>j.id===997),change.job||{});
 f.api=f.api.slice(0,3).concat([
 {method:'request:GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs',args:{job_id:999},result:{status:302,headers:{location:'https://logs.invalid/999'}}},
 {method:'request:GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs',args:{job_id:997},result:{status:302,headers:{location:'https://logs.invalid/997'}}},
 {method:'rest.checks.get',args:{check_run_id:91},result:{data:{id:91,name:ack.checkName,external_id:ack.checkExternalId,head_sha:sha,status:'queued',conclusion:null,app:{id:15368,slug:'github-actions'},...change.check}}}]);
 f.fetches=[{url:'https://logs.invalid/999',body:'CLOUDOPSWORKS_STAGE_V1 '+JSON.stringify(planner)},
 {url:'https://logs.invalid/997',body:change.logs??'CLOUDOPSWORKS_DELIVERY_CHECK_V1 '+JSON.stringify(ack)}];return f;
}
test('source-free writer independently reads actual successful initializer acknowledgement then GETs exact check ID',()=>{
 const r=runStep(action,'verify',initializerFixture());assert.equal(r.error,undefined,JSON.stringify(r));
 assert.equal(JSON.parse(r.outputs.check).checkId,'91');assert.equal(JSON.parse(r.outputs.check).sourceSha,sha);assert.deepEqual(r.unused,{api:0,tools:0,fetches:0});
});
for(const [label,change] of [
 ['retained initializer',{job:{run_attempt:1}}],['failed initializer',{job:{conclusion:'failure'}}],
 ['counterfeit acknowledgement',{ack:{checkId:'92'}}],['wrong App',{check:{app:{id:1,slug:'github-actions'}}}],
 ['already completed check',{check:{status:'completed',conclusion:'success'}}],
 ['unknown acknowledgement field',{ack:{grant:true}}],
])test(`writer denies ${label}`,()=>{const r=runStep(action,'verify',initializerFixture(change));assert.equal(r.error?.message,{'retained initializer':'planner-job-status','failed initializer':'planner-job-status','counterfeit acknowledgement':'origin-initializer-binding','wrong App':'origin-check-binding','already completed check':'origin-check-binding','unknown acknowledgement field':'origin-initializer-binding'}[label],JSON.stringify(r));assert.equal(r.outputs.origin,undefined);});
function closureWriter(change={}) {
 const host='d'.repeat(40),merge='e'.repeat(40),policy='f'.repeat(40),head='a'.repeat(40);
 const pull={number:17,state:'closed',merged:true,merge_commit_sha:merge,head:{sha:head,ref:'feature/fix',repo:{id:456}},base:{sha:policy,ref:'support/v1',repo:{id:123}}};
 const facts={event:'pull_request_target',ref:'refs/heads/master',hostSha:host,callerPath:'.github/workflows/pr-close.yaml',callerSha:host,blueprintSha:'c'.repeat(40),sourceSha:merge,sourceRef:'refs/heads/support/v1',sourceRepositoryId:'123',trustedSource:true,prNumber:'17',headRepositoryId:'456',headSha:head,headRef:'feature/fix',baseRef:'support/v1',policySha:policy,closed:true,merged:true,...change.facts};
 const api=(method,data,args={})=>({method:'rest.'+method,args,result:{data}});
 return {env:{ORIGIN_FACTS:JSON.stringify(facts),RUN_ID:'456',RUN_ATTEMPT:'2',GITHUB_RUN_ID:'456',GITHUB_RUN_ATTEMPT:'2',GITHUB_REPOSITORY_ID:'123',GITHUB_WORKFLOW_SHA:host,BLUEPRINT_SHA:'c'.repeat(40),SOURCE_TRUSTED:'true',GITHUB_SHA:host,GITHUB_REF:'refs/heads/master',PLAN_SOURCE:merge,PLAN_DIGEST:digest,PLAN_JOB_ID:'999',ARTIFACT_ID:'789',ARCHIVE_DIGEST:digest,
  CHECK:JSON.stringify({checkId:'91',checkName:'monorepo-delivery/456/2',checkAppId:'15368',checkExternalId:'cloudopsworks:123:456:2',sourceSha:merge}),...change.env},
 context:{eventName:'pull_request_target',repo:{owner:'example',repo:'mixed'},payload:{action:'closed',pull_request:{...pull,...change.event}}},api:[
 api('actions.getWorkflowRunAttempt',{id:456,run_attempt:2,repository:{id:123},head_sha:host,path:'.github/workflows/pr-close.yaml',event:'pull_request_target',head_branch:'master',referenced_workflows:[{path:'cloudopsworks/blueprints/.github/workflows/monorepo-ci.yml@v5.11.0',sha:'c'.repeat(40)}]}),
 api('pulls.get',{...pull,...change.pull},{pull_number:17}),
 api('repos.get',{id:123,default_branch:'master'})]};
}
test('closure origin writer preserves actual event protected-base snapshot, not a current default/base tip',()=>{
 const r=runStep(action,'origin',closureWriter());assert.equal(r.error,undefined,JSON.stringify(r));
 const record=JSON.parse(r.logs.find(x=>x.kind==='info').message.slice('CLOUDOPSWORKS_ORIGIN_V1 '.length));
 assert.equal(record.policySha,'f'.repeat(40));assert.equal(record.hostSha,'d'.repeat(40));assert.equal(record.sourceSha,'e'.repeat(40));assert.equal(record.headRepositoryId,'456');
});
for(const [label,change] of [
 ['source',{facts:{sourceSha:'a'.repeat(40)}}],['ref',{facts:{ref:'refs/heads/develop'}}],['PR head',{facts:{headSha:'b'.repeat(40)}}],
 ['protected-base snapshot',{facts:{policySha:'e'.repeat(40)}}],['attempt',{env:{RUN_ATTEMPT:'1'}}],['source trust',{facts:{trustedSource:false}}],
 ['PR disposition',{facts:{closed:false}}],['API merge race',{pull:{merge_commit_sha:'a'.repeat(40)}}],
])test(`closed writer rejects mutated ${label} facts before emission`,()=>{
 const r=runStep(action,'origin',closureWriter(change));assert.equal(r.error?.message,{'source':'origin-writer-source','ref':'origin-writer-source','PR head':'origin-writer-pull','protected-base snapshot':'origin-writer-closure','attempt':'origin-writer-context','source trust':'origin-writer-run','PR disposition':'origin-writer-pull','API merge race':'origin-writer-closure'}[label],JSON.stringify(r));assert.deepEqual(r.logs,[]);
});
function prWriter(){
 const f=closureWriter(),facts=JSON.parse(f.env.ORIGIN_FACTS),head='a'.repeat(40),mergeHost='d'.repeat(40),caller='9'.repeat(40);
 Object.assign(facts,{event:'pull_request',ref:'refs/pull/17/merge',hostSha:mergeHost,callerPath:'.github/workflows/pr-build.yml',callerSha:caller,sourceSha:head,sourceRef:'refs/heads/feature/fix',sourceRepositoryId:'456',trustedSource:false,closed:false,merged:false});
 Object.assign(f.env,{ORIGIN_FACTS:JSON.stringify(facts),GITHUB_SHA:mergeHost,GITHUB_WORKFLOW_SHA:caller,GITHUB_REF:'refs/pull/17/merge',PLAN_SOURCE:head,SOURCE_TRUSTED:'false'});
 Object.assign(f.context,{eventName:'pull_request'});Object.assign(f.context.payload,{action:'opened'});Object.assign(f.context.payload.pull_request,{state:'open',merged:false});
 Object.assign(f.api[0].result.data,{event:'pull_request',path:'.github/workflows/pr-build.yml',head_sha:head,head_branch:'feature/fix'});Object.assign(f.api[1].result.data,{state:'open',merged:false});f.api.pop();return f;
}
test('native PR writer preserves distinct API source, merge host, and caller workflow SHA',()=>{
 const r=runStep(action,'origin',prWriter());assert.equal(r.error,undefined,JSON.stringify(r));assert.deepEqual(r.unused,{api:0,tools:0,fetches:0});
 const record=JSON.parse(r.logs[0].message.slice('CLOUDOPSWORKS_ORIGIN_V1 '.length));assert.equal(record.sourceSha,'a'.repeat(40));assert.equal(record.hostSha,'d'.repeat(40));assert.equal(record.callerSha,'9'.repeat(40));assert.equal(record.ref,'refs/pull/17/merge');assert.equal(record.trustedSource,false);
});
for(const [label,patch,error]of [['API source as native host',{hostSha:'a'.repeat(40)},'origin-writer-source'],['API source as caller',{callerSha:'a'.repeat(40)},'origin-writer-source'],['wrong pull merge ref',{ref:'refs/pull/18/merge'},'origin-writer-source'],['uncaptured base',{policySha:'8'.repeat(40)},'origin-writer-pr-source'],['forged source trust',{trustedSource:true},'origin-writer-run']])test('native PR writer denies '+label,()=>{
 const f=prWriter();f.env.ORIGIN_FACTS=JSON.stringify({...JSON.parse(f.env.ORIGIN_FACTS),...patch});const r=runStep(action,'origin',f);assert.equal(r.error?.message,error);assert.deepEqual(r.logs,[]);
});
for(const [label,patch] of [['wrong API producer path',{path:'.github/workflows/unrelated.yml',event:'push'}],['wrong API producer event',{path:'.github/workflows/main-build.yml',event:'workflow_run'}]])test(`independent origin bootstrap denies ${label} before captured fields/content`,()=>{
 const f=fixture();Object.assign(f.api[0].result.data,patch);
 const r=runStep(action,'verify',f);assert.equal(r.error?.message,'origin-producer-api');assert.equal(r.calls.some(c=>c.method?.includes('/logs')||c.method==='rest.repos.getContent'),false);assert.deepEqual(r.outputs,{});
});

for(const [label,patch]of [['missing producer reference',run=>run.referenced_workflows.pop()],['different producer pin',run=>run.referenced_workflows[0].sha='d'.repeat(40)],['duplicate producer reference',run=>run.referenced_workflows.push(run.referenced_workflows[0])]])test('released producer bootstrap rejects '+label+' before accepting log fields',()=>{
 const f=fixture();patch(f.api[0].result.data);const r=runStep(action,'verify',f);assert.equal(r.error?.message,'origin-producer-code');assert.equal(r.calls.some(c=>c.method?.includes('/logs')),false);assert.equal(r.outputs.origin,undefined);
});
for(const [label,extra,error]of [['wrong source repository',{sourceRepositoryId:'999'},'origin-main-binding'],['wrong exact check name',{checkName:'monorepo-delivery/latest'},'origin-check-binding'],['wrong native PR ref',{event:'pull_request',ref:'refs/pull/18/merge',prNumber:'17'},'origin-source-binding']])test('typed origin identity rejects '+label+' after independent reader bootstrap',t=>{
 const temp=fs.mkdtempSync(path.join(os.tmpdir(),'origin-typed-'));t.after(()=>fs.rmSync(temp,{recursive:true,force:true}));const file=path.join(temp,'plan.json');fs.writeFileSync(file,JSON.stringify({version:'1.2.3',baseSha:'',headSha:sha,buildSelection:[]}));
 const r=runStep(action,'identity',{env:{MODE:'origin-verify',PLAN_PATH:file,ORIGIN:JSON.stringify(origin(extra)),JOBS:'[]'},tools:[{result:{exitCode:0,stdout:JSON.stringify({digest})}}]});assert.equal(r.error?.message,error);assert.deepEqual(r.outputs,{});assert.equal(r.calls.length,1);
});
