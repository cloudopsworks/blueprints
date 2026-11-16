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
test('main and tags do not request an empty captured-base snapshot; PR and closure require it',()=>{
 const workflow=yaml('.github/workflows/monorepo-scan.yml');
 for(const [job,producer] of [['component','inputs'],['required','context']]){
  const snapshot=workflow.jobs[job].steps.find(step=>step.id==='policy-snapshot');
  assert.equal(snapshot.if,`steps.${producer}.outputs.caller-mode == 'normal-pr' || steps.${producer}.outputs.caller-mode == 'normal-closure'`);
  assert.equal(snapshot.with['source-sha'],`\${{ steps.${producer}.outputs.policy-sha }}`);
 }
});
import os from 'node:os';
import {runStep} from './action_test_support.mjs';
for(const mode of ['normal-main','normal-pr','normal-closure'])test(`actual policy ${mode} with absent captured base has no fallback`,t=>{
 const directory=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'policy18-')));
 t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
 const configuration=path.join(directory,'source.json');
 fs.writeFileSync(configuration,JSON.stringify({scanners:{sonarqubeEnabled:false,sonarqubeQualityGateEnabled:false,sonarqubeFailOnQualityGate:false,snykEnabled:false,semgrepEnabled:false,trivyEnabled:false,dependencyTrackEnabled:false}}));
 const result=runStep('ci/monorepo/stage/scans/action.yml','policy',{env:{RUNNER_TEMP:directory,CALLER_MODE:mode,CONFIGURATION:configuration,POLICY_CONFIGURATION:''}});
 if(mode==='normal-main'){
  assert.equal(result.error,undefined,JSON.stringify(result));
  assert.equal(JSON.parse(result.outputs['policy-digests']).length,1);
  assert.ok(Object.values(JSON.parse(fs.readFileSync(result.outputs.configuration)).scanners).every(flag=>flag===false));
 }else{assert.equal(result.error?.message,'scan-policy-bound');assert.deepEqual(result.outputs,{});}
 assert.deepEqual(result.calls,[],'absent captured base cannot request a CLI/API/source fallback');
});
