import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
const yaml = file => {
 const parsed=spawnSync('yq',['-o=json','.',file],{encoding:'utf8'});
 assert.equal(parsed.status,0,parsed.stderr); return JSON.parse(parsed.stdout);
};
test('actual isolated planner seals consumed bytes and mandates post-endorsement readback',()=>{
 const workflow=yaml('.github/workflows/monorepo-ci.yml'),steps=workflow.jobs.plan.steps;
 const get=id=>{const s=steps.find(s=>s.id===id);assert.ok(s,`missing mandatory ${id}`);return s;};
 const ingress=get('baseline'),plan=get('plan'),prepare=get('plan-binding'),upload=get('plan-upload'),emit=get('plan-endorsement'),verify=get('plan-binding-readback');
 assert.equal(plan.with['base-sha'],'${{ steps.baseline.outputs.base-sha }}');
 assert.equal(prepare.uses,'./bp/ci/monorepo/plan/binding');
 assert.equal(prepare.with.mode,'prepare');
 assert.equal(prepare.with['consumed-receipt'],'${{ steps.baseline.outputs.receipt }}');
 assert.equal(prepare.with['consumed-digest'],'${{ steps.baseline.outputs.receipt-digest }}');
 assert.equal(prepare.with.plan,'${{ steps.plan.outputs.plan }}');
 assert.equal(upload.with.path,'${{ steps.plan-binding.outputs.directory }}');
 assert.equal(emit.with['computed-plan'],'${{ steps.plan.outputs.plan }}');
 assert.equal(verify.uses,'./bp/ci/monorepo/plan/binding');assert.equal(verify.with.mode,'verify');
 assert.equal(verify.with['verification-role'],'writer');
 assert.equal(verify.with.plan,'${{ steps.plan-endorsement.outputs.plan }}');
 assert.equal(verify.with['consumed-receipt'],prepare.with['consumed-receipt']);
 assert.equal(verify.with['consumed-digest'],prepare.with['consumed-digest']);
 for(const s of [prepare,upload,emit,verify]){assert.equal(s.if,undefined);assert.equal(s['continue-on-error'],undefined);}
 assert.deepEqual([ingress,plan,prepare,upload,emit,verify].map(s=>steps.indexOf(s)),[3,4,5,6,7,8]);
 assert.deepEqual(workflow.permissions,{});assert.deepEqual(workflow.jobs.plan.permissions,{contents:'read',actions:'read'});
 assert.deepEqual(Object.keys(workflow.jobs),['baseline','plan','build','required']);
});
test('unchanged independent planner proof body and no new retention log protocol',()=>{
 const data=fs.readFileSync('ci/monorepo/plan/endorsement/action.yml');
 assert.equal(createHash('sha256').update(data).digest('hex'),'d4025cbff828ee28b94ac82e6bd7ae150e51ddc7a26f6e101dca926ccaeff7aa');
 const binding=fs.readFileSync('ci/monorepo/plan/binding/action.yml','utf8');
 assert.doesNotMatch(binding,/CLOUDOPSWORKS_BASELINE_V1|github\.rest|fetch\(|retain-frozen|retain-prepared/);
 const output=yaml('ci/monorepo/plan/binding/action.yml').outputs;
 for(const key of Object.keys(output))assert.doesNotMatch(key,/verified|origin|source/);
});
