import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {root} from './action_test_support.mjs';
const filename=path.join(root,'ci/monorepo/stage/endorsement/action.yml');
test('stage endorsement is a fixed named composite using the same verified control-artifact path',()=>{
 assert.ok(fs.existsSync(filename),'required fixed stage endorsement composite missing');
 const parsed=spawnSync('yq',['-o=json','-I=0','.',filename],{encoding:'utf8',env:{PATH:process.env.PATH},timeout:10000,maxBuffer:4194304});
 assert.equal(parsed.status,0,parsed.stderr);const action=JSON.parse(parsed.stdout);
 assert.equal(action.runs.using,'composite');
 for(const id of ['emit','verify'])assert.ok(action.runs.steps.some(step=>step.id===id&&step.uses==='actions/github-script@v9'));
 const data=action.runs.steps.find(step=>step.uses==='./bp/ci/monorepo/artifact');
 assert.ok(data);assert.equal(data.with['record-kind'],'ReleaseManifest');
 assert.equal(action.runs.steps.some(step=>step.run),false);
});

import os from 'node:os';
import {runStep} from './action_test_support.mjs';
const action='ci/monorepo/stage/endorsement/action.yml',archiveDigest='sha256:'+'a'.repeat(64);
function emitter(t,change={}){
 const rootDir=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'actual-stage-writer-')));t.after(()=>fs.rmSync(rootDir,{recursive:true,force:true}));
 const env={ARTIFACT_ID:'789',ARCHIVE_DIGEST:archiveDigest,RUN_ID:'456',RUN_ATTEMPT:'2',GITHUB_RUN_ID:'456',GITHUB_RUN_ATTEMPT:'2',GITHUB_REPOSITORY_ID:'123',...change.env};
 for(const label of ['COMPUTED','RETRIEVED']){
  const directory=path.join(rootDir,label);fs.mkdirSync(directory);
  for(const kind of ['PLAN','MANIFEST']){env[label+'_'+kind]=path.join(directory,kind+'.json');fs.writeFileSync(env[label+'_'+kind],JSON.stringify({kind:kind==='PLAN'?'BuildPlan':'ReleaseManifest'}));}
 }
 const planDigest='sha256:'+'b'.repeat(64),manifestDigest='sha256:'+'c'.repeat(64);
 const digests=[planDigest,manifestDigest,change.planDigest||planDigest,change.manifestDigest||manifestDigest];
 return {env,tools:digests.map((digest,index)=>({prefix:['components','contracts','validate','--kind',index%2?'ReleaseManifest':'BuildPlan'],result:{stdout:JSON.stringify({digest,record:{kind:index%2?'ReleaseManifest':'BuildPlan'}})}})),
 api:[{method:'rest.actions.getArtifact',args:{artifact_id:'789'},result:{data:{id:789,name:'monorepo-stage-456-2',digest:archiveDigest,expired:false,workflow_run:{id:456},...change.artifact}}}]};
}
function emit(t,change={}){
 const r=runStep(action,'emit',emitter(t,change));return r;
}
function verification(logs,change={}){
 const job={id:999,name:'Monorepo delivery slice / stage',run_id:456,run_attempt:2,status:'completed',conclusion:'success',...change.job};
 return {env:{MODE:'verify',CALLER_MODE:'reusable',ARTIFACT_ID:'789',ARCHIVE_DIGEST:archiveDigest,RUN_ID:'456',RUN_ATTEMPT:'2',GITHUB_REPOSITORY_ID:'123',...change.env},api:[
 {method:'rest.actions.getWorkflowRunAttempt',args:{run_id:'456',attempt_number:'2'},result:{data:{id:456,run_attempt:2,repository:{id:123},...change.run}}},
 {method:'rest.actions.listJobsForWorkflowRunAttempt',args:{run_id:'456',attempt_number:'2',page:1},result:{data:{jobs:change.jobs||[job]}}},
 {method:'request:GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs',args:{job_id:999},result:{status:302,headers:{location:'https://stage-logs.invalid/signed'}}},
 ],fetches:[{url:'https://stage-logs.invalid/signed',body:change.logs??logs}]};
}
function actualMarker(t){
 const produced=emit(t);assert.equal(produced.error,undefined,JSON.stringify(produced));
 const messages=produced.logs.filter(l=>l.kind==='info').map(l=>l.message);
 assert.equal(messages.length,1);return messages[0];
}
test('actual stage writer compares both computed/uploaded control records before emitting a closed binding',t=>{
 const r=emit(t);assert.equal(r.error,undefined,JSON.stringify(r));
 assert.deepEqual(r.calls.filter(c=>c.kind==='exec').map(c=>c.args[4]),['BuildPlan','ReleaseManifest','BuildPlan','ReleaseManifest']);
 for(const call of r.calls.filter(c=>c.args?.[4]==='ReleaseManifest'))assert.ok(call.args.includes('--linked-context'));
 const marker=r.logs.find(l=>l.kind==='info').message;
 assert.deepEqual(JSON.parse(marker.slice('CLOUDOPSWORKS_STAGE_V1 '.length)),{repositoryId:'123',runId:'456',runAttempt:'2',artifactId:'789',artifactName:'monorepo-stage-456-2',archiveDigest});
});
for(const [name,change]of [
 ['changed plan bytes',{planDigest:'sha256:'+'d'.repeat(64)}],
 ['changed manifest bytes',{manifestDigest:'sha256:'+'d'.repeat(64)}],
 ['stale ambient attempt',{env:{GITHUB_RUN_ATTEMPT:'3'}}],
 ['wrong uploaded stage name',{artifact:{name:'monorepo-plan-456-2'}}],
 ['expired uploaded control',{artifact:{expired:true}}],
])test(`stage writer denies ${name} before emitting authority`,t=>{
 const r=emit(t,change);assert.ok(r.error);assert.equal(r.logs.some(l=>l.kind==='info'),false);
});
test('actual stage consumer accepts the exact marker emitted by the actual fixed writer body',t=>{
 const marker=actualMarker(t),r=runStep(action,'verify',verification(marker));
 assert.equal(r.error,undefined,JSON.stringify(r));assert.deepEqual(r.unused,{api:0,tools:0,fetches:0});
 const request=r.calls.find(c=>c.kind==='fetch');assert.deepEqual(request.headers,{});assert.equal(request.credentials,'omit');assert.equal(request.redirect,'error');
});
for(const [name,change]of [
 ['old run attempt',{run:{run_attempt:1}}],['old writer attempt',{job:{run_attempt:1}}],
 ['wrong writer job',{job:{name:'Monorepo delivery slice / build (api)'}}],
 ['failed forward writer',{job:{conclusion:'failure'}}],['unfinished writer',{job:{status:'in_progress'}}],
 ['wrong writer host',{job:{run_id:455}}],['missing fixed writer',{jobs:[]}],
 ['duplicate fixed writer',{jobs:[{name:'Monorepo delivery slice / stage'},{name:'Monorepo delivery slice / stage'}]}],
])test(`stage consumer denies ${name} despite valid emitted bytes`,t=>{
 const r=runStep(action,'verify',verification(actualMarker(t),change));assert.ok(r.error);assert.deepEqual(r.outputs,{});
});
for(const mutation of ['duplicate','wrong-digest','wrong-repository','extra-field','wrong-id','echoed'])test(`stage consumer denies ${mutation} log binding`,t=>{
 const marker=actualMarker(t),binding=JSON.parse(marker.slice('CLOUDOPSWORKS_STAGE_V1 '.length));
 let logs=marker;
 if(mutation==='duplicate')logs+='\n'+marker;
 if(mutation==='wrong-digest')binding.archiveDigest='sha256:'+'d'.repeat(64);
 if(mutation==='wrong-repository')binding.repositoryId='124';
 if(mutation==='extra-field')binding.producerJob='stage';
 if(mutation==='wrong-id')binding.artifactId='788';
 if(!['duplicate','echoed'].includes(mutation))logs='CLOUDOPSWORKS_STAGE_V1 '+JSON.stringify(binding);
 if(mutation==='echoed')logs='echo '+marker;
 const r=runStep(action,'verify',verification(logs));assert.ok(r.error);assert.deepEqual(r.outputs,{});
});
