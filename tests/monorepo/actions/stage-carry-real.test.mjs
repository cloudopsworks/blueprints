import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {runStep} from './action_test_support.mjs';
const binary=process.env.TRONADOR_CLI;
assert.ok(binary&&fs.existsSync(binary),'TRONADOR_CLI must name actual compiled CLI');
const fixtures=fileURLToPath(new URL('../../../../tronador-cli-v511/internal/components/testdata/contracts/valid/',import.meta.url));
const read=name=>JSON.parse(fs.readFileSync(path.join(fixtures,name+'.json')));
function setup(t,mutation){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'stage-real-carry-')));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const plan=read('build-plan'),original=read('component-result');plan.targets=[];plan.components[0].targetIds=[];
 const worker=structuredClone(plan.components[0]);worker.id='worker';worker.path='components/worker';worker.toolchains[0].components=['worker'];plan.components.push(worker);
 const prior=read('release-manifest');prior.targets=[];prior.components[0].targetIds=[];
 const old=structuredClone(original);old.componentId='worker';for(const key of ['mainArtifact','previewArtifact'])old[key].location.path=old[key].location.path.replace('/api/','/worker/');
 const entry={componentId:'worker',package:worker.package,workload:worker.workload,targetIds:[],mainArtifact:null,previewArtifact:null};
 for(const key of ['mainArtifact','previewArtifact'])entry[key]={...old[key],location:{kind:'actions-artifact',repositoryId:plan.repository.id,runId:'450',runAttempt:'1',artifactId:'790',artifactName:'components-450-1-worker',path:old[key].location.path}};
 prior.components.push(entry);plan.baseSha=plan.headSha;plan.headSha='c'.repeat(40);plan.version='1.2.4';
 const selected=structuredClone(original);selected.headSha=plan.headSha;selected.version=plan.version;for(const key of ['mainArtifact','previewArtifact']){selected[key].sourceSha=plan.headSha;selected[key].builtVersion=plan.version;selected[key].location.path=selected[key].location.path.replace('/1.2.3/','/1.2.4/');}
 if(mutation==='foreign-package')entry.package={kind:'function',format:'zip',entryPoint:'bootstrap'};
 const save=(name,value)=>{const p=path.join(root,name+'.json');fs.writeFileSync(p,JSON.stringify(value));return p;};
 const carried={recordPath:save('old-result',old),artifactId:'790',artifactName:'components-450-1-worker'};
 const env={RUNNER_TEMP:root,PLAN_PATH:save('current-plan',plan),VERIFIED_RECORDS:JSON.stringify([{recordPath:save('new-result',selected),artifactId:'789',artifactName:'components-456-2-api'}]),CARRIED_RECORDS:JSON.stringify(mutation==='missing'?[]:mutation==='duplicate'?[carried,carried]:[carried]),CARRY_MANIFEST:save('prior-manifest',prior),RUN_ID:'456',RUN_ATTEMPT:'2'};
 return {env,plan,prior,root};
}
for(const mutation of ['none','missing','duplicate','foreign-package'])test(`real typed selected+original carry stage ${mutation}`,t=>{
 const f=setup(t,mutation),r=runStep('ci/monorepo/stage/action.yml','manifest',{realCli:binary,env:f.env});
 if(mutation!=='none'){assert.ok(r.error,JSON.stringify(r));assert.deepEqual(r.outputs,{});return;}
 assert.equal(r.error,undefined,JSON.stringify(r));const manifest=JSON.parse(fs.readFileSync(r.outputs.manifest));
 assert.equal(manifest.headSha,f.plan.headSha);assert.equal(manifest.version,'1.2.4');assert.equal(manifest.components.length,2);
 assert.deepEqual(manifest.components[1],f.prior.components[1]);assert.equal(manifest.components[0].mainArtifact.location.runId,'456');assert.equal(manifest.components[1].mainArtifact.location.runId,'450');
 // Descriptor/control fixture proof only: no claim these unit descriptors are packaged apps.
 const archiveDigest='sha256:'+'d'.repeat(64),common={ARTIFACT_ID:'800',ARCHIVE_DIGEST:archiveDigest,RUN_ID:'456',RUN_ATTEMPT:'2',GITHUB_RUN_ID:'456',GITHUB_RUN_ATTEMPT:'2',GITHUB_REPOSITORY_ID:'12345'};
 const emitted=runStep('ci/monorepo/stage/endorsement/action.yml','emit',{realCli:binary,env:{...common,COMPUTED_PLAN:f.env.PLAN_PATH,COMPUTED_MANIFEST:r.outputs.manifest,RETRIEVED_PLAN:path.join(r.outputs.directory,'plan.json'),RETRIEVED_MANIFEST:r.outputs.manifest},api:[{method:'rest.actions.getArtifact',result:{data:{id:800,name:'monorepo-stage-456-2',digest:archiveDigest,expired:false,workflow_run:{id:456}}}}]});
 assert.equal(emitted.error,undefined,JSON.stringify(emitted));const marker=emitted.logs.find(l=>l.kind==='info').message;
 const consumed=runStep('ci/monorepo/stage/endorsement/action.yml','verify',{env:{...common,MODE:'verify',CALLER_MODE:'reusable'},api:[
 {method:'rest.actions.getWorkflowRunAttempt',result:{data:{id:456,run_attempt:2,repository:{id:12345}}}},
 {method:'rest.actions.listJobsForWorkflowRunAttempt',result:{data:{jobs:[{id:900,name:'Monorepo delivery slice / stage',run_id:456,run_attempt:2,status:'completed',conclusion:'success'}]}}},
 {method:'request:GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs',result:{status:302,headers:{location:'https://stage.invalid/log'}}}],fetches:[{url:'https://stage.invalid/log',body:marker}]});
 assert.equal(consumed.error,undefined,JSON.stringify(consumed));assert.deepEqual(consumed.unused,{api:0,tools:0,fetches:0});
});
