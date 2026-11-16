import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {root,runStep} from './action_test_support.mjs';
const endorsement='ci/scan/trivy/endorsement/action.yml',scans='ci/monorepo/stage/scans/action.yml';
function parsed(action){const r=spawnSync('yq',['-o=json','.',path.join(root,action)],{encoding:'utf8'});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout);}
test('existing scanner writer remains default emit and diagnostic verification has a closed mode',()=>{
 const action=parsed(endorsement);assert.equal(action.inputs.mode.default,'emit');
 assert.equal(action.runs.steps.find(s=>s.id==='emit').if,"inputs.mode == 'emit'");
 assert.equal(action.runs.steps.find(s=>s.id==='data').if,"inputs.mode == 'emit'");
 const denied=runStep(endorsement,'mode',{env:{MODE:'arbitrary'}});assert.equal(denied.error?.message,'scanner-endorsement-mode');assert.deepEqual(denied.outputs,{});assert.deepEqual(denied.calls,[]);
});
test('explicit diagnostic verification cannot execute emitter or emit an endorsement',()=>{
 const r=runStep(endorsement,'emit',{env:{MODE:'verify-diagnostic'}});assert.equal(r.error,undefined,JSON.stringify(r));assert.deepEqual(r.outputs,{});assert.deepEqual(r.logs,[]);assert.deepEqual(r.calls,[]);
});
test('stage diagnostic delegates only to existing protocol owner; normal path stays in stage scans',()=>{
 const action=parsed(scans),delegate=action.runs.steps.find(s=>s.id==='diagnostic');assert.ok(delegate);
 assert.equal(delegate.uses,'./bp/ci/scan/trivy/endorsement');assert.equal(delegate.with.mode,'verify-diagnostic');
 assert.equal(delegate.if,"inputs.mode == 'diagnostic'");assert.equal(action.runs.steps.some(s=>['locate','coverage'].includes(s.id)),false);
 assert.match(action.outputs.coverage.value,/steps.diagnostic.outputs.coverage/);
 assert.ok(action.runs.steps.some(s=>s.id==='normal-locate'));assert.ok(action.runs.steps.some(s=>s.id==='normal-coverage'));
 const reader=parsed(endorsement);for(const step of reader.runs.steps.filter(s=>s.id==='diagnostic-main'||s.id==='diagnostic-preview')){assert.equal(step.with['record-kind'],'ScannerResult');assert.ok(step.with['artifact-set-file']);assert.equal(step.with['artifact-set'],undefined);}
});
test('diagnostic linked context uses exclusive0600 creation in its private directory',()=>{
 const locate=parsed(endorsement).runs.steps.find(s=>s.id==='locate');assert.match(locate.with.script,/fs\.writeFile\(linked, JSON\.stringify\(\{plan\}\), \{mode: 0o600, flag: 'wx'\}\)/);assert.match(locate.with.script,/fs\.chmod\(directory, 0o700\)/);
});
