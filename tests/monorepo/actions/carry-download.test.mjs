import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {runStep} from './action_test_support.mjs';
const action='ci/monorepo/artifact/transport/action.yml';
const cli=process.env.TRONADOR_CLI;assert.ok(cli&&fs.existsSync(cli),'actual native CLI required');
function fixture(t,change={}){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'crossrun-carry-download-')));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const plan={repository:{id:'100',fullName:'example/mixed'},components:[{id:'api'},{id:'worker'},{id:'changed'}],buildSelection:[{componentId:'changed'}]};
 const rows=[['api','456','789'],['worker','567','790'],['changed','678','791']].map(([componentId,runId,artifactId])=>{
  const directory=path.join(root,componentId);fs.mkdirSync(directory);fs.writeFileSync(path.join(directory,'plan.json'),'{}');const zipped=spawnSync('zip',['-q','-X',path.join(directory,'archive.zip'),'plan.json'],{cwd:directory});assert.equal(zipped.status,0);
  const bytes=fs.readFileSync(path.join(directory,'archive.zip')),digest='sha256:'+createHash('sha256').update(bytes).digest('hex');
  const descriptor={kind:'container',format:'oci',digest:'sha256:'+'a'.repeat(64),sizeBytes:123,sourceSha:'b'.repeat(40),builtVersion:'1.2.3',location:{kind:'actions-artifact',repositoryId:'100',runId,runAttempt:'2',artifactId,artifactName:`components-${runId}-2-${componentId}`,path:`.cloudopsworks/out/${componentId}/1.2.3/main.oci.tar`}};
  return {componentId,runId,artifactId,bytes,digest,descriptor,artifact:{id:Number(artifactId),name:descriptor.location.artifactName,workflow_run:{id:Number(runId),head_sha:'c'.repeat(40)},expired:false,digest,size_in_bytes:bytes.length}};
 });
 if(change.rows)change.rows(rows);
 const manifest={repository:plan.repository,state:'complete',components:rows.map(row=>({componentId:row.componentId,mainArtifact:row.descriptor,previewArtifact:structuredClone(row.descriptor)}))};
 const planPath=path.join(root,'plan.json'),carryPath=path.join(root,'authenticated-manifest.json');fs.writeFileSync(planPath,JSON.stringify(plan));fs.writeFileSync(carryPath,JSON.stringify(manifest));
 const needed=rows.slice(0,2),api=needed.map(row=>({method:'rest.actions.getArtifact',args:{artifact_id:row.artifactId},result:{data:row.artifact}})),fetches=[];
 for(const row of needed){
  api.push({method:'rest.repos.get',result:{data:{id:100}}},
   {method:'rest.actions.getWorkflowRun',args:{run_id:row.runId},result:{data:{id:Number(row.runId),repository:{id:100},head_sha:'c'.repeat(40)}}},
   {method:'rest.actions.getArtifact',args:{artifact_id:row.artifactId},result:{data:row.artifact}},
   {method:'request:GET /repos/{owner}/{repo}/actions/artifacts/{artifact_id}/zip',args:{artifact_id:row.artifactId},result:{status:302,headers:{location:`https://carry-storage.invalid/${row.artifactId}`}}});
  fetches.push({url:`https://carry-storage.invalid/${row.artifactId}`,base64:row.bytes.toString('base64')});
 }
 return {env:{CARRY_MANIFEST:carryPath,PLAN_PATH:planPath,RUN_ID:'999',RUN_ATTEMPT:'4',GITHUB_REPOSITORY_ID:'100',RUNNER_TEMP:root},tools:[plan,manifest].map(record=>({prefix:['components','contracts','validate'],result:{stdout:JSON.stringify({record})}})),api,fetches};
}
function retrieve(f){
 const resolved=runStep(action,'resolve',{env:f.env,api:f.api.slice(0,2),tools:f.tools});
 if(resolved.error)return resolved;
 const result=runStep(action,'retrieve',{realCli:cli,env:{...f.env,RESOLVED_FILE:resolved.outputs['resolved-file']},api:f.api.slice(2),fetches:f.fetches});
 return {...result,calls:[...resolved.calls,...result.calls]};
}
test('carry download derives two original runs and excludes currently selected components without relabeling',t=>{
 const r=retrieve(fixture(t));assert.equal(r.error,undefined,JSON.stringify(r));
 const downloads=JSON.parse(fs.readFileSync(r.outputs['bundles-file']));assert.deepEqual(downloads.map(row=>[row.artifactId,row.runId]),[['789','456'],['790','567']]);
 const transports=downloads.map(row=>JSON.parse(fs.readFileSync(row.transport)));
 assert.deepEqual(transports.map(row=>row.runId),['456','567']);
 assert.equal(r.calls.some(call=>String(call.args?.artifact_id)==='791'),false);
 assert.equal(r.calls.some(call=>String(call.args?.run_id)==='999'),false);
 assert.deepEqual(r.unused,{api:0,tools:0,fetches:0});
});
for(const [name,mutate]of [
 ['expired historical payload',rows=>rows[0].artifact.expired=true],
 ['contradictory original run',rows=>rows[0].artifact.workflow_run.id=455],
 ['contradictory original artifact ID',rows=>rows[0].artifact.id=788],
])test(`carry transfer denies ${name} without final outputs`,t=>{
 const r=retrieve(fixture(t,{rows:mutate}));assert.ok(r.error);assert.deepEqual(r.outputs,{});
});

for(const mutation of ['runId','artifactName','missing-owner'])test(`carry reread denies substituted ${mutation} before transfer calls`,t=>{
 const f=fixture(t),resolved=runStep(action,'resolve',{env:f.env,api:f.api.slice(0,2),tools:f.tools});assert.equal(resolved.error,undefined,JSON.stringify(resolved));
 const rows=JSON.parse(fs.readFileSync(resolved.outputs['resolved-file']));if(mutation==='missing-owner')rows.pop();else rows[0][mutation]='unexpected';fs.writeFileSync(resolved.outputs['resolved-file'],JSON.stringify(rows));
 const result=runStep(action,'retrieve',{realCli:cli,env:{...f.env,RESOLVED_FILE:resolved.outputs['resolved-file']}});assert.equal(result.error?.message,'artifact-route-binding',JSON.stringify(result));assert.deepEqual(result.calls,[]);assert.deepEqual(result.outputs,{});
});
