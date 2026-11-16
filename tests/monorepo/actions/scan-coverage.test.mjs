import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {root} from './action_test_support.mjs';
const filename=path.join(root,'ci/scan/trivy/endorsement/action.yml');
test('stage image coverage uses a fixed composite and the existing typed artifact verifier',()=>{
 assert.ok(fs.existsSync(filename),'required purpose/digest scan coverage composite missing');
 const parsed=spawnSync('yq',['-o=json','-I=0','.',filename],{env:{PATH:process.env.PATH},encoding:'utf8',timeout:10000,maxBuffer:4194304});
 assert.equal(parsed.status,0,parsed.stderr);const action=JSON.parse(parsed.stdout);assert.equal(action.runs.using,'composite');
 for(const id of ['locate','coverage'])assert.ok(action.runs.steps.some(step=>step.id===id&&step.uses==='actions/github-script@v9'));
 const data=action.runs.steps.find(step=>step.id==='diagnostic-main'&&step.uses==='./bp/ci/monorepo/artifact');assert.ok(data);
 assert.equal(data.with['record-kind'],'ScannerResult');
 assert.equal(action.runs.steps.some(step=>step.run),false);
});
