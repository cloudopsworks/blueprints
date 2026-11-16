import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {root, loadStep} from './action_test_support.mjs';
const action='ci/monorepo/stage/inputs/action.yml';
function definition(){const r=spawnSync('yq',['-o=json','.',path.join(root,action)],{encoding:'utf8'});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout);}
test('pre-stage inputs independently authenticate current, baseline and original owners',()=>{
 const a=definition(),steps=Object.fromEntries(a.runs.steps.map(s=>[s.id,s]));
 assert.equal(steps.current.uses,'./bp/cd/tasks/repo/context');assert.equal(steps.current.with.mode,'normal');
 assert.equal(steps.plan.uses,'./bp/ci/monorepo/plan/endorsement');assert.equal(steps.plan.with.mode,'verify');
 assert.equal(steps.baseline.uses,'./bp/ci/monorepo/stage/endorsement');assert.equal(steps.baseline.with.mode,'verify');
 assert.equal(steps['baseline-context'].uses,'./bp/cd/tasks/repo/context');assert.equal(steps['baseline-context'].with.mode,undefined);
 assert.equal(steps.original.uses,'./bp/cd/tasks/repo/context');assert.equal(steps.original.with.mode,'normal');
 assert.equal(steps['original-plan'].uses,'./bp/ci/monorepo/plan/endorsement');
 assert.equal(steps.data.uses,'./bp/ci/monorepo/artifact');assert.equal(steps.data.with['record-kind'],'ComponentResult');
 assert.match(steps.data.with.plan,/original-plan.outputs.plan/);assert.doesNotMatch(steps.data.with.plan,/baseline/);
 assert.equal(steps.configuration.uses,'./bp/ci/monorepo/source');
 const text=fs.readFileSync(path.join(root,action),'utf8');assert.doesNotMatch(text,/actions\/checkout|secrets\.|id-token|scanner|success:|carry-manifest:|authenticated:/);
 for(const step of a.runs.steps){assert.equal(step.run,undefined);assert.ok(step.uses==='actions/github-script@v9'||step.uses.startsWith('./bp/'));}
 for(const id of ['route','origin','locate','result'])assert.ok(loadStep(action,id).script);
 assert.deepEqual(Object.keys(a.inputs).sort(),['baseline-artifact-id','baseline-archive-digest','baseline-run-attempt','baseline-run-id','component','plan-artifact-id','plan-archive-digest','run-attempt','run-id'].sort());
});
test('original execution identity is projected only from authenticated owner context outputs',()=>{
 const a=definition();
 for(const field of ['source-ref','source-repository-id','trusted-source']){
  assert.equal(a.inputs[field],undefined);
  assert.equal(a.outputs[field].value,`\${{ steps.original.outputs.${field} || steps.current.outputs.${field} }}`);
 }
});
