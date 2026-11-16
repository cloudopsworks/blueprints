import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {runStep} from './action_test_support.mjs';
const action='ci/monorepo/artifact/action.yml';
function bundle(t,kind,extra=[]){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'control-artifact-')));
 t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const parent=fs.mkdtempSync(path.join(root,'artifact-data-')),directory=path.join(parent,'extracted');fs.mkdirSync(directory,{mode:0o700});
 const filename=kind==='ScannerResult'?'scanner-result.json':'manifest.json';
 const record={kind},files=[filename,...extra];fs.writeFileSync(path.join(directory,filename),JSON.stringify(record),{mode:0o600});
 const tools=[];
 if(kind==='ReleaseManifest'){
  const plan={kind:'BuildPlan'};files.push('plan.json');fs.writeFileSync(path.join(directory,'plan.json'),JSON.stringify(plan));
  tools.push({prefix:['components','contracts','validate','--kind','BuildPlan'],result:{stdout:JSON.stringify({record:plan})}});
 }
 tools.push({prefix:['components','contracts','validate','--kind',kind],result:{stdout:JSON.stringify({record})}});
 const metadata=path.join(parent,'bundles.json');fs.writeFileSync(metadata,JSON.stringify([{runId:'200',artifactId:'300',archiveDigest:'sha256:'+'a'.repeat(64),artifactName:'',archive:path.join(parent,'archive.zip'),transport:path.join(parent,'transport.json'),extract:directory,directory,files}]),{mode:0o600});
 return {env:{RUNNER_TEMP:root,BUNDLES_FILE:metadata,DIRECTORY:directory,FILES:JSON.stringify(files),RECORD_KIND:kind},tools};
}
for(const kind of ['ScannerResult','ReleaseManifest']){
 test(`${kind} control bundle validates typed records without an application descriptor`,t=>{
  const r=runStep(action,'records',bundle(t,kind));assert.equal(r.error,undefined,JSON.stringify(r));
  assert.ok(r.outputs.record);assert.equal(r.outputs.payloadVerified,undefined);
  assert.equal(r.calls.some(c=>c.args.includes('--descriptor')),false);
  if(kind==='ReleaseManifest')assert.equal(r.calls[1].args.includes('--linked-context'),true);
 });
 test(`${kind} control record rejects an unexpected extracted file`,t=>{
  const r=runStep(action,'records',bundle(t,kind,['untrusted-policy.json']));
  assert.ok(r.error);assert.deepEqual(r.outputs,{});
 });
}
test('ReleaseManifest control bundle requires its exact linked BuildPlan',t=>{
 const f=bundle(t,'ReleaseManifest');const bundles=JSON.parse(fs.readFileSync(f.env.BUNDLES_FILE));bundles[0].files=['manifest.json'];fs.writeFileSync(f.env.BUNDLES_FILE,JSON.stringify(bundles));
 fs.unlinkSync(path.join(f.env.DIRECTORY,'plan.json'));
 const r=runStep(action,'records',f);assert.ok(r.error);assert.deepEqual(r.outputs,{});
});
