import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import {root} from './action_test_support.mjs';
const file=path.join(root,'.github/workflows/monorepo-delivery-slice.yml');
const parsed=spawnSync('yq',['-o=json','-I=0','.',file],{env:{PATH:process.env.PATH},encoding:'utf8',timeout:10000,maxBuffer:1048576});
assert.equal(parsed.status,0,parsed.stderr);const workflow=JSON.parse(parsed.stdout);
test('actual same-host reusable DAG orders plan→build→scan→stage with ordinary successful-needs gating',()=>{
 assert.ok(workflow.on.workflow_call!==undefined);assert.equal(workflow.on.workflow_run,undefined);
 assert.equal(workflow.jobs.build.needs,'plan');assert.deepEqual(workflow.jobs.scan.needs,['plan','build','frozen-tag']);assert.deepEqual(workflow.jobs.stage.needs,['plan','build','frozen-tag','scan']);
 for(const id of ['build','scan','stage'])assert.doesNotMatch(workflow.jobs[id].if||'',/always\(|failure\(/);

});
test('scan and stage check out only Blueprint code and consume exact endorsed plan rather than application source or matrix outputs',()=>{
 for(const id of ['scan','stage']){
  const steps=workflow.jobs[id].steps;
  for(const step of steps.filter(s=>s.uses?.startsWith('actions/checkout@')))assert.equal(step.with.repository,'cloudopsworks/blueprints');
  assert.ok(steps.some(s=>s.uses==='./bp/cd/tasks/repo/context'));
  const endorsement=steps.find(s=>s.uses==='./bp/ci/monorepo/plan/endorsement');assert.equal(endorsement.with.mode,'verify');
  assert.equal(endorsement.with['run-attempt'],'${{ steps.context.outputs.run-attempt }}');
  assert.doesNotMatch(JSON.stringify(steps),/needs\.(?:build|scan)\.outputs/);
 }
 const scanner=workflow.jobs.scan.steps.find(s=>s.uses==='./bp/ci/scan/trivy');
 assert.equal(scanner.with['component-result'],'${{ steps.data.outputs.record }}');
 const stage=workflow.jobs.stage.steps.find(s=>s.uses==='./bp/ci/monorepo/stage');
 assert.equal(stage.with.plan,'${{ steps.plan.outputs.plan }}');assert.equal(stage.with.configuration,'${{ steps.source.outputs.configuration }}');
});

test('reusable permission defaults grant no token capabilities',()=>{
 assert.deepEqual(workflow.permissions,{},'reusable defaults must grant no permissions');
});
test('application build/test/package job has only contents read permission',()=>{
 assert.deepEqual(workflow.jobs.build.permissions,{contents:'read'},'application execution gets contents read only');
});
test('source-free plan, scan and stage control roles retain only required read permissions',()=>{
 for(const id of ['plan','scan','stage'])assert.deepEqual(workflow.jobs[id].permissions,{contents:'read',actions:'read','pull-requests':'read'});
});
