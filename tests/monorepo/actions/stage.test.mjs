import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {runStep} from './action_test_support.mjs';
const action='ci/monorepo/stage/action.yml',head='a'.repeat(40),base='b'.repeat(40),digest='sha256:'+'c'.repeat(64);
function fixture(t,change={}){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'actual-stage-')));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const plan={repository:{id:'123',fullName:'example/mixed'},headSha:head,baseSha:base,version:'1.2.3',components:[{id:'go'},{id:'node'}],targets:[],previewPolicy:{},buildSelection:[{componentId:'go'},{componentId:'node'}],...change.plan};
 const planPath=path.join(root,'plan.json'),configPath=path.join(root,'config.json');fs.writeFileSync(planPath,JSON.stringify(plan));fs.writeFileSync(configPath,JSON.stringify({components:plan.components,targets:plan.targets,previewPolicy:plan.previewPolicy}));
 const jobs=['build','scan'].flatMap((role,roleIndex)=>['go','node'].map((id,index)=>({id:999+roleIndex*2+index,name:`Monorepo delivery slice / ${role} (${id})`,run_id:456,run_attempt:2,status:'completed',conclusion:'success'})));
 const artifacts=['go','node'].map((id,i)=>({id:789+i,name:`components-456-2-${id}`,digest}));
 if(change.jobs)change.jobs(jobs);if(change.artifacts)change.artifacts(artifacts);
 const tools=[{result:{stdout:JSON.stringify({digest,record:plan})}},{result:{stdout:JSON.stringify({digest:change.candidateDigest||digest,record:plan})}}];
 return {env:{PLAN_PATH:planPath,CONFIGURATION:configPath,SOURCE_SHA:head,BASE_SHA:base,VERSION:'1.2.3',RUN_ID:'456',RUN_ATTEMPT:'2',GITHUB_REPOSITORY_ID:'123',...change.env},tools,api:[
 {method:'rest.actions.getWorkflowRunAttempt',args:{run_id:'456',attempt_number:'2'},result:{data:{id:456,run_attempt:2,repository:{id:123},...change.run}}},
 {method:'rest.actions.listJobsForWorkflowRunAttempt',args:{attempt_number:'2',page:1},result:{data:{jobs}}},
 {method:'rest.actions.listWorkflowRunArtifacts',args:{run_id:'456',page:1},result:{data:{artifacts}}},
 ]};
}
test('stage corroborates normalized exact plan then requires same-host current build AND scan matrix success',t=>{
 const r=runStep(action,'locate',fixture(t));assert.equal(r.error,undefined);
 assert.deepEqual(JSON.parse(r.outputs.artifacts),[{artifactId:'789',archiveDigest:digest},{artifactId:'790',archiveDigest:digest}]);
 assert.deepEqual(r.calls.filter(c=>c.kind==='exec').map(c=>c.args),Array(2).fill(['components','contracts','validate','--kind','BuildPlan']));
 assert.deepEqual(r.unused,{api:0,tools:0,fetches:0});
});
for(const [name,change] of [
 ['normalized configuration mismatch',{candidateDigest:'sha256:'+'d'.repeat(64)}],
 ['source mismatch',{env:{SOURCE_SHA:'e'.repeat(40)}}],['base mismatch',{env:{BASE_SHA:'e'.repeat(40)}}],['version mismatch',{env:{VERSION:'9.9.9'}}],
 ['wrong current host attempt',{run:{run_attempt:1}}],['wrong host repository',{run:{repository:{id:124}}}],
 ['missing native job ID',{jobs:j=>{delete j[0].id;}}],['invalid native job ID',{jobs:j=>{j[0].id=0;}}],
 ['failed build',{jobs:j=>{j[0].conclusion='failure';}}],['failed scanner',{jobs:j=>{j[2].conclusion='failure';}}],
 ['unfinished scanner',{jobs:j=>{j[2].status='in_progress';}}],['old job attempt',{jobs:j=>{j[0].run_attempt=1;}}],
 ['wrong job host',{jobs:j=>{j[0].run_id=455;}}],['missing matrix member',{jobs:j=>j.pop()}],
 ['duplicate matrix member',{jobs:j=>j.push(j[0])}],['extra matrix member',{jobs:j=>j.push({...j[0],name:'Monorepo delivery slice / build (extra)'})}],
 ['missing artifact',{artifacts:a=>a.pop()}],['duplicate artifact name',{artifacts:a=>a.push(a[0])}],
])test(`stage denies ${name} without stage outputs`,t=>{
 const r=runStep(action,'locate',fixture(t,change));assert.ok(r.error);assert.deepEqual(r.outputs,{});
});
test('subset selection with no approved historical carry proof fails closed before API or second selector',t=>{
 const r=runStep(action,'locate',fixture(t,{plan:{buildSelection:[{componentId:'go'}]}}));
 assert.equal(r.error?.message,'stage-historical-carry-proof-required');assert.equal(r.calls.some(c=>c.kind==='api'),false);
 assert.equal(r.calls.some(c=>c.kind==='exec'&&['plan','build','package'].includes(c.args[1])),false);assert.deepEqual(r.outputs,{});
});
function manifestFixture(t,records=[{componentId:'go',status:'succeeded'},{componentId:'node',status:'succeeded'}]){
 const f=fixture(t),root=path.dirname(f.env.PLAN_PATH);
 const verified=records.map((record,i)=>{const recordPath=path.join(root,`result-${i}.json`);fs.writeFileSync(recordPath,JSON.stringify(record));return {recordPath,artifactId:String(789+i),artifactName:`components-456-2-${record.componentId}`};});
 return {env:{PLAN_PATH:f.env.PLAN_PATH,VERIFIED_RECORDS:JSON.stringify(verified),RUN_ID:'456',RUN_ATTEMPT:'2',RUNNER_TEMP:root},tools:records.map(record=>({result:{stdout:JSON.stringify({record})}}))};
}
test('manifest missing selected result denies before any CLI or output',t=>{
 const r=runStep(action,'manifest',manifestFixture(t,[{componentId:'go',status:'succeeded'}]));assert.equal(r.error?.message,'stage-result-count');assert.deepEqual(r.calls,[]);assert.deepEqual(r.outputs,{});
});
for(const [name,records] of [
 ['duplicate selected component',[{componentId:'go',status:'succeeded'},{componentId:'go',status:'succeeded'}]],
 ['failed result',[{componentId:'go',status:'failed'},{componentId:'node',status:'succeeded'}]],
 ['unselected component',[{componentId:'unexpected',status:'succeeded'},{componentId:'node',status:'succeeded'}]],
])test(`manifest denies ${name} instead of complete stage`,t=>{
 const r=runStep(action,'manifest',manifestFixture(t,records));assert.equal(r.error?.message,'stage-result-owner');assert.deepEqual(r.outputs,{});
});
test('manifest rejects stale REST artifact naming even with typed selected result',t=>{
 const f=manifestFixture(t),rows=JSON.parse(f.env.VERIFIED_RECORDS);rows[0].artifactName='components-456-1-go';f.env.VERIFIED_RECORDS=JSON.stringify(rows);
 const r=runStep(action,'manifest',f);assert.equal(r.error?.message,'stage-result-owner');assert.deepEqual(r.outputs,{});
});
test('normal final stage refuses admission without exact fresh barrier source host',t=>{
 const f=fixture(t);f.env.MODE='normal';f.env.SCAN_RUN_ID='900';f.env.SCAN_RUN_ATTEMPT='2';f.env.GITHUB_RUN_ID='901';f.env.GITHUB_RUN_ATTEMPT='2';
 const r=runStep(action,'normal-barrier',f);assert.equal(r.error?.message,'stage-scan-host');assert.deepEqual(r.outputs,{});
});
function normalBarrier(change={}){const job={id:991,name:'delivery / scan / monorepo-scan-required',run_id:900,run_attempt:2,status:'completed',conclusion:'success',...change.job};return{env:{SOURCE_SHA:head,HOST_SOURCE_SHA:head,CALLER_MODE:'normal-main',HOST_CALLER_MODE:'normal-main',ORIGIN_RUN_ID:'450',ORIGIN_RUN_ATTEMPT:'1',HOST_ORIGIN_RUN_ID:'450',HOST_ORIGIN_RUN_ATTEMPT:'1',SCAN_RUN_ID:'900',SCAN_RUN_ATTEMPT:'2',GITHUB_RUN_ID:'900',GITHUB_RUN_ATTEMPT:'2',GITHUB_REPOSITORY_ID:'123'},api:[{method:'rest.actions.getWorkflowRunAttempt',result:{data:{id:900,run_attempt:2,repository:{id:123},event:'workflow_run',...change.run}}},{method:'rest.actions.listJobsForWorkflowRunAttempt',result:{data:{jobs:change.jobs||[job]}}}]};}
test('normal stage requires exact completed successful current-attempt barrier independently of needs',()=>{const r=runStep(action,'normal-barrier',normalBarrier());assert.equal(r.error,undefined,JSON.stringify(r));assert.deepEqual(r.unused,{api:0,tools:0,fetches:0});});
for(const [name,change]of [['wrong host',{run:{event:'pull_request_target'}}],['failed barrier',{job:{conclusion:'failure'}}],['cancelled barrier',{job:{conclusion:'cancelled'}}],['stale barrier',{job:{run_attempt:1}}],['suffix spoof',{job:{name:'wrong / delivery / scan / monorepo-scan-required'}}],['missing barrier',{jobs:[]}]])test(`normal stage denies ${name}`,()=>{const r=runStep(action,'normal-barrier',normalBarrier(change));assert.ok(r.error,JSON.stringify(r));assert.deepEqual(r.outputs,{});});
test('normal stage original CI builds are separate from actual scanner host',t=>{const f=fixture(t);f.env.MODE='normal';f.env.CALLER_MODE='normal-main';f.api[1].result.data.jobs=f.api[1].result.data.jobs.filter(job=>job.name.includes('/ build')).map(job=>({...job,name:job.name.replace('Monorepo delivery slice / build','lifecycle / ci / monorepo-ci-build')}));const r=runStep(action,'locate',f);assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(JSON.parse(r.outputs.artifacts).length,2);});
