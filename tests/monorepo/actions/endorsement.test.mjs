import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {runStep} from './action_test_support.mjs';
const action='ci/monorepo/plan/endorsement/action.yml';
const digest='sha256:'+'a'.repeat(64);
function receipt(change={}){return {repositoryId:'123',runId:'456',runAttempt:'2',artifactId:'789',artifactName:'monorepo-plan-456-2',archiveDigest:digest,...change};}
const marker=r=>'CLOUDOPSWORKS_STAGE_V1 '+JSON.stringify(r);
function fixture(change={}){
 const job={id:999,name:'plan',run_id:456,run_attempt:2,status:'completed',conclusion:'success',...change.job};
 return {env:{MODE:'verify',CALLER_MODE:'direct',ARTIFACT_ID:'789',ARCHIVE_DIGEST:digest,RUN_ID:'456',RUN_ATTEMPT:'2',GITHUB_REPOSITORY_ID:'123',...change.env},api:[
  {method:'rest.actions.getWorkflowRunAttempt',args:{run_id:'456',attempt_number:'2'},result:{data:{id:456,run_attempt:2,repository:{id:123},...change.run}}},
  {method:'rest.actions.listJobsForWorkflowRunAttempt',args:{run_id:'456',attempt_number:'2',page:1},result:{data:{jobs:change.jobs||[job]}}},
  {method:'request:GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs',args:{job_id:999},result:{status:302,headers:{location:'https://logs.invalid/signed'}}},
 ],fetches:[{url:'https://logs.invalid/signed',body:change.logs??marker(receipt())}]};
}
test('exact expected plan ID binds to the unique successful current-attempt writer job log',()=>{
 const r=runStep(action,'verify',fixture());assert.equal(r.error,undefined);assert.deepEqual(r.unused,{api:0,tools:0,fetches:0});
 const call=r.calls.find(c=>c.kind==='fetch');assert.deepEqual(call.headers,{});assert.equal(call.credentials,'omit');assert.equal(call.redirect,'error');
});
test('distinct valid other-ID receipt does not reject the selected exact ID',()=>{
 const r=runStep(action,'verify',fixture({logs:[marker(receipt({artifactId:'788'})),marker(receipt())].join('\n')}));assert.equal(r.error,undefined);
});
for(const [name,change] of [
 ['old attempt',{run:{run_attempt:1}}],['wrong repository',{run:{repository:{id:124}}}],
 ['old job attempt',{job:{run_attempt:1}}],['wrong job run',{job:{run_id:455}}],
 ['failed recovery evidence',{job:{conclusion:'failure'}}],['unfinished writer',{job:{status:'in_progress'}}],
 ['wrong fixed writer name',{job:{name:'build'}}],['duplicate writer jobs',{jobs:[{name:'plan'},{name:'plan'}]}],
 ['wrong expected ID',{logs:marker(receipt({artifactId:'788'}))}],
 ['wrong receipt attempt',{logs:marker(receipt({runAttempt:'1'}))}],
 ['wrong digest',{logs:marker(receipt({archiveDigest:'sha256:'+'b'.repeat(64)}))}],
 ['unknown closed receipt field',{logs:marker(receipt({producerJob:'plan'}))}],
 ['duplicate same ID',{logs:marker(receipt())+'\n'+marker(receipt())}],
 ['counterfeit echoed marker',{logs:'echo '+marker(receipt())}],
 ['noncanonical JSON',{logs:'CLOUDOPSWORKS_STAGE_V1 '+JSON.stringify(receipt(),null,1)}],
])test(`planner authority denies ${name}`,()=>{
 const r=runStep(action,'verify',fixture(change));assert.ok(r.error);assert.deepEqual(r.outputs,{});
});
test('reusable writer job name is exact, not an inferred direct job',()=>{
 const f=fixture({env:{CALLER_MODE:'reusable'},job:{name:'Monorepo delivery slice / plan'}});
 const r=runStep(action,'verify',f);assert.equal(r.error,undefined);
});
function emitter(t,digests=[digest,digest]){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'plan-endorse-')));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const computed=path.join(root,'computed.json'),retrieved=path.join(root,'retrieved.json');fs.writeFileSync(computed,'{"kind":"BuildPlan"}');fs.writeFileSync(retrieved,'{"kind":"BuildPlan"}');
 return {env:{COMPUTED_PLAN:computed,RETRIEVED_PLAN:retrieved,ARTIFACT_ID:'789',ARCHIVE_DIGEST:digest,RUN_ID:'456',RUN_ATTEMPT:'2',GITHUB_RUN_ID:'456',GITHUB_RUN_ATTEMPT:'2',GITHUB_REPOSITORY_ID:'123'},tools:digests.map(d=>({args:['components','contracts','validate','--kind','BuildPlan'],result:{stdout:JSON.stringify({digest:d,record:{kind:'BuildPlan'}})}})),api:[{method:'rest.actions.getArtifact',result:{data:{id:789,name:'monorepo-plan-456-2',digest,expired:false,workflow_run:{id:456}}}}]};
}
test('writer emits closed receipt only after computed and retrieved canonical plan digests agree',t=>{
 const r=runStep(action,'emit',emitter(t));assert.equal(r.error,undefined);
 assert.deepEqual(r.logs.filter(l=>l.kind==='info').map(l=>l.message),[marker(receipt())]);
});
test('stale needs/retrieved planner digest never receives a success endorsement',t=>{
 const r=runStep(action,'emit',emitter(t,[digest,'sha256:'+'b'.repeat(64)]));assert.equal(r.error?.message,'planner-writer-bytes');
 assert.equal(r.calls.some(c=>c.kind==='api'),false);assert.deepEqual(r.logs,[]);
});
test('old writer attempt cannot emit in the current ambient attempt',t=>{
 const f=emitter(t);f.env.GITHUB_RUN_ATTEMPT='3';const r=runStep(action,'emit',f);assert.equal(r.error?.message,'planner-writer-context');assert.deepEqual(r.calls,[]);
});
test('endorsed plan exposes only typed identity fields for native downstream argv',t=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'endorsed-plan-identity-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));const file=path.join(root,'plan.json');fs.writeFileSync(file,JSON.stringify({headSha:'a'.repeat(40),baseSha:'b'.repeat(40),version:'1.2.3'}));const r=runStep('ci/monorepo/plan/endorsement/action.yml','identity',{env:{PLAN_PATH:file}});assert.equal(r.error,undefined);assert.equal(r.outputs.version,'1.2.3');assert.equal(r.outputs['base-sha'],'b'.repeat(40));
});

test('actual normal CI fixed writer has its own exact name, not the diagnostic job',()=>{
 const r=runStep(action,'verify',fixture({env:{CALLER_MODE:'normal-main'},job:{name:'lifecycle / ci / monorepo-ci-plan'}}));
 assert.equal(r.error,undefined,JSON.stringify(r));
});
test('normal plan cannot inherit the diagnostic writer identity',()=>{
 const r=runStep(action,'verify',fixture({env:{CALLER_MODE:'normal-main'}}));
 assert.equal(r.error?.message,'planner-job-identity');
});
for(const [mode,name]of [['normal-pr','ci / ci / monorepo-ci-plan'],['normal-closure','close / lifecycle / ci / monorepo-ci-plan']]){
 test(`${mode} accepts only its exact source-derived nested writer`,()=>{const r=runStep(action,'verify',fixture({env:{CALLER_MODE:mode},job:{name}}));assert.equal(r.error,undefined,JSON.stringify(r));});
 for(const wrong of ['monorepo-ci-plan','prefix / '+name,name+' / suffix'])test(`${mode} denies non-exact writer ${wrong}`,()=>{const r=runStep(action,'verify',fixture({env:{CALLER_MODE:mode},job:{name:wrong}}));assert.equal(r.error?.message,'planner-job-identity');assert.deepEqual(r.outputs,{});});
}
