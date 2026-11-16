import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {runStep} from './action_test_support.mjs';
const action = 'ci/monorepo/plan/baseline/action.yml';
function setup(t, extra = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'normal-baseline-'));
  t.after(() => fs.rmSync(directory, {recursive:true,force:true}));
  const file = path.join(directory, 'configuration.json');
  fs.writeFileSync(file, JSON.stringify({previewPolicy:{enabled:true,targets:[{targetId:'eks'}]}}));
  return {RUNNER_TEMP:directory, CONFIGURATION:file, HEAD_SHA:'a'.repeat(40), PR_NUMBER:'7', AUTOMATION_ID:'99',
    GITHUB_REPOSITORY_ID:'123', GITHUB_REPOSITORY:'example/mixed', GITHUB_RUN_ID:'5', GITHUB_RUN_ATTEMPT:'2', ...extra};
}
function run(env, options = {}) {
  const result = runStep(action, 'normal', {env, ...options});
  if (result.error) return result;
  result.record = JSON.parse(fs.readFileSync(result.outputs.baseline));
  return result;
}
function state(targetId='eks', headSha='b'.repeat(40)) {
  return {repository:{id:'123',fullName:'example/mixed'},prNumber:7,targetId,headSha,phase:'ready',
    namespace:`pr-7-${targetId}-${createHash('sha256').update(`123:7:${targetId}`).digest('hex').slice(0,12)}`};
}
function receipt(record=state()) {
  return {method:'rest.repos.listDeployments',args:{environment:`cloudopsworks/preview/${record.targetId}/pr-7`}, result:{data:[
    {id:100,creator:{id:42},payload:{kind:'PreviewMetadata'}},
    {id:10,creator:{id:99},payload:{kind:'PreviewMetadata',state:record}},
  ]}};
}
const typed = record => ({prefix:['components','contracts','validate','--kind','PreviewState'],result:{stdout:JSON.stringify({record})}});
const status = target => ({method:'rest.repos.listDeploymentStatuses',args:{deployment_id:10},result:{data:[{id:12,creator:{id:42},state:'success'}, {id:11,creator:{id:99},state:target || 'success'}]}});

test('normal reader queries actual actor-filtered receipts but cannot endorse the unmigrated stage', t => {
  const env=setup(t), record=state();
  const result=run(env,{api:[receipt(record),status()],tools:[typed(record)]});
  assert.equal(result.error,undefined);
  assert.equal(result.record.reason,'normal-stage-unavailable');
  assert.equal(result.record.found,false);
  assert.equal(result.record.baseSha,'');
  assert.equal(result.record.headSha,env.HEAD_SHA);
  assert.deepEqual(result.unused,{api:0,tools:0,fetches:0});
  assert.equal(fs.statSync(result.outputs.baseline).mode & 0o077,0);
});

test('absent receipt means explicit safe materialization, not an arbitrary earlier CI', t => {
  const result=run(setup(t),{api:[{method:'rest.repos.listDeployments',result:{data:[]}}]});
  assert.equal(result.record.reason,'preview-receipt-absent');
  assert.equal(result.record.baseSha,'');
  assert.equal(result.calls.filter(call=>call.kind==='api').length,1);
});

test('deployments permission denied is propagated as unavailable evidence without secrets or cloud calls', t => {
  const result=run(setup(t),{api:[{method:'rest.repos.listDeployments',error:{status:403}}]});
  assert.equal(result.error,undefined);
  assert.equal(result.record.reason,'preview-receipt-inaccessible');
  assert.equal(result.record.found,false);
  assert.equal(result.calls.length,1);
});

test('missing automation identity cannot accept unfiltered preview materialization', t => {
  const result=run(setup(t,{AUTOMATION_ID:''}));
  assert.equal(result.record.reason,'preview-automation-unavailable');
  assert.deepEqual(result.calls,[]);
});

test('only latest trusted status, not latest untrusted success, determines receipt usability', t => {
  const record=state();
  const result=run(setup(t),{api:[receipt(record),status('failure')],tools:[typed(record)]});
  assert.equal(result.record.reason,'preview-receipt-unusable');
  assert.equal(result.record.found,false);
});

test('all configured target receipts must agree before even considering stage proof', t => {
  const env=setup(t);
  fs.writeFileSync(env.CONFIGURATION,JSON.stringify({previewPolicy:{enabled:true,targets:[{targetId:'eks'},{targetId:'aks'}]}}));
  const a=state(),b=state('aks','c'.repeat(40));
  const result=run(env,{api:[receipt(a),status(),receipt(b),status()],tools:[typed(a),typed(b)]});
  assert.equal(result.record.reason,'preview-targets-disagree');
  assert.equal(result.record.baseSha,'');
});

test('bad typed receipt is never promoted to a Go selector base', t => {
  const result=run(setup(t),{api:[receipt()],tools:[{prefix:['components','contracts','validate'],result:{exitCode:1}}]});
  assert.equal(result.record.reason,'preview-receipt-unusable');
  assert.equal(result.record.baseSha,'');
});
