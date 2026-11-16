import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {root} from './action_test_support.mjs';

function yaml(relative) {
 const parsed=spawnSync('yq',['-o=json','-I=0','.',path.join(root,relative)],{
  env:{PATH:process.env.PATH},encoding:'utf8',timeout:10000,maxBuffer:4194304});
 assert.equal(parsed.status,0,parsed.stderr);return JSON.parse(parsed.stdout);
}
const typed=yaml('ci/scan/trivy/action.yml'),legacy=yaml('ci/docker/scan/trivy/action.yml');
function local(step){return typeof step.uses==='string'&&step.uses.startsWith('./bp/');}
function sharedInvocation(){
 const existing=new Set(legacy.runs.steps.filter(local).map(s=>s.uses));
 const shared=typed.runs.steps.filter(s=>local(s)&&existing.has(s.uses));
 assert.equal(shared.length,1,'both real adapters must call one shared native invocation composite');
 return {typed:shared[0],legacy:legacy.runs.steps.find(s=>s.uses===shared[0].uses),
  action:yaml(shared[0].uses.slice('./bp/'.length)+'/action.yml')};
}
test('legacy and typed adapters reuse one actual pinned native Trivy implementation',()=>{
 const shared=sharedInvocation();assert.equal(shared.action.runs.using,'composite');
 assert.equal(shared.action.runs.steps.filter(s=>s.uses==='aquasecurity/setup-trivy@v0.3.1').length,1);
 const json=shared.action.runs.steps.filter(s=>s.uses==='aquasecurity/trivy-action@v0.36.0'&&s.with?.format==='json'&&s.with?.['scan-type']==='image');
 assert.equal(json.length,1);assert.equal(json[0].with['scan-type'],'image');
 assert.equal(json[0].with.scanners,'vuln');assert.equal(json[0].with['ignore-unfixed'],true);
 assert.equal(json[0].with.severity,'CRITICAL,HIGH,MEDIUM');
 for(const adapter of [typed,legacy]){
  assert.equal(adapter.runs.steps.some(s=>s.uses?.startsWith('aquasecurity/setup-trivy@')),false,'setup belongs to shared primitive');
  assert.equal(adapter.runs.steps.some(s=>s.uses?.startsWith('aquasecurity/trivy-action@')&&s.with?.format==='json'),false,'JSON invocation belongs to shared primitive');
 }
});
test('legacy wrapper preserves token, JSON filenames and native SARIF failure behavior',()=>{
 const shared=sharedInvocation();const values=Object.values(shared.legacy.with||{});
 assert.ok(values.includes('${{ inputs.source_path }}/docker-image.tar'));
 assert.ok(values.includes('${{ inputs.source_path }}/trivy-results.json'));
 assert.ok(values.includes('${{ inputs.token }}'));
 assert.notEqual(shared.legacy['continue-on-error'],true,'legacy JSON tool errors must still fail the wrapper');
 const download=legacy.runs.steps.find(s=>s.uses==='actions/download-artifact@v7');
 assert.equal(download.with.name,'docker-image');assert.equal(download.with.path,'${{ inputs.source_path }}');
 const sarif=legacy.runs.steps.find(s=>s.uses==='aquasecurity/trivy-action@v0.36.0'&&s.with?.format==='sarif');
 assert.ok(sarif);assert.equal(sarif.with.input,'${{ inputs.source_path }}/docker-image.tar');
 assert.equal(sarif.with.output,'${{ inputs.source_path }}/trivi-results.sarif');
 assert.equal(sarif.with.severity,'CRITICAL,HIGH');assert.equal(sarif.with['github-pat'],'${{ inputs.token }}');
 assert.equal(sarif.with['limit-severities-for-sarif'],true);assert.equal(sarif.with.scanners,'vuln');
 const upload=legacy.runs.steps.find(s=>s.uses==='github/codeql-action/upload-sarif@v4');
 assert.equal(upload.if,'success() || failure()');assert.equal(upload['continue-on-error'],true);
 assert.equal(upload.with.sarif_file,'${{ inputs.source_path }}/trivi-results.sarif');
 assert.equal(upload.with['wait-for-processing'],false);
});
