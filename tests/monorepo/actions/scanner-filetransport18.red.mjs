// UNIMPLEMENTED acceptance REDs retained separately from the green policy regression suite.
// Actual production YAML interfaces. File data is private routing, never authority.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {root} from './action_test_support.mjs';
function yaml(file) {
 const result=spawnSync('yq',['-o=json','.',path.join(root,file)],{encoding:'utf8'});
 assert.equal(result.status,0,result.stderr);return JSON.parse(result.stdout);
}
test('ScannerResult file opt-in replaces inline collections at every actual step mapping',()=>{
 const action=yaml('ci/monorepo/artifact/action.yml'),steps=Object.fromEntries(action.runs.steps.map(step=>[step.id,step]));
 assert.ok(action.inputs['artifact-set-file'],'private ScannerResult file ingress is required');
 assert.equal(steps.transport.uses,'./bp/ci/monorepo/artifact/transport');
 assert.equal(steps.transport.with['artifact-set-file'],'${{ inputs.artifact-set-file }}');
 const transport=yaml('ci/monorepo/artifact/transport/action.yml'),phases=Object.fromEntries(transport.runs.steps.map(step=>[step.id,step]));
 assert.equal(phases.retrieve.env.RESOLVED_FILE,'${{ steps.resolve.outputs.resolved-file }}');
 assert.equal(steps.records.env.BUNDLES_FILE,'${{ steps.transport.outputs.bundles-file }}');
 assert.equal(steps.payloads.env.VERIFIED_RECORDS_FILE,'${{ steps.records.outputs.verified-records-file }}');
 assert.equal(action.outputs['records-file'].value,'${{ steps.payloads.outputs.records-file }}');
});
test('normal all-seven-purpose coverage genuinely reuses one file-backed transport',()=>{
 const action=yaml('ci/monorepo/stage/scans/action.yml');
 const calls=action.runs.steps.filter(step=>step.uses==='./bp/ci/monorepo/artifact'&&step.if?.startsWith("inputs.mode == 'normal'"));
 assert.equal(calls.length,1);assert.equal(calls[0].with['artifact-set-file'],'${{ steps.normal-locate.outputs.artifacts-file }}');
 const coverage=action.runs.steps.find(step=>step.id==='normal-coverage');
 assert.equal(coverage.env.RECORDS_FILE,`\${{ steps.${calls[0].id}.outputs.records-file }}`);
 assert.ok(!Object.keys(coverage.env).some(key=>key.endsWith('_RECORDS')),'no re-expanded collection environment');
});
