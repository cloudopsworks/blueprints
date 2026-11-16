import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {root} from './action_test_support.mjs';
function yaml(file){
 assert.ok(fs.existsSync(file),`Required actual closure caller missing: ${file}`);
 const r=spawnSync('yq',['-o=json','-I=0','.',file],{env:{PATH:process.env.PATH},encoding:'utf8',timeout:10000,maxBuffer:4194304});
 assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout);
}
const workflowFile=path.join(root,'.github/workflows/monorepo-delivery-slice.yml');
test('actual local closure caller uses familiar closed PR event and the same delivery reusable',()=>{
 const caller=yaml(path.join(root,'../monorepo-app-template/.github/workflows/composite-first-closure.yml'));
 assert.deepEqual(caller.on.pull_request_target.types,['closed']);assert.deepEqual(caller.permissions,{});
 assert.equal(caller.jobs.delivery.name,'Monorepo delivery slice');
 assert.equal(caller.jobs.delivery.uses,'cloudopsworks/blueprints/.github/workflows/monorepo-delivery-slice.yml@v5.11.0');
 assert.deepEqual(caller.jobs.delivery.permissions,{contents:'write',actions:'read','pull-requests':'read',deployments:'write','id-token':'write'});
 assert.equal(Object.values(caller.jobs).some(job=>job.steps?.some(step=>step.run)),false);
});
test('native closure tag job follows successful component CI and calls only frozen source-free publisher',()=>{
 const workflow=yaml(workflowFile),tag=workflow.jobs['frozen-tag'];assert.ok(tag,'missing native frozen-tag job');
 assert.ok([tag.needs].flat().includes('build'));assert.doesNotMatch(tag.if||'',/always\(|failure\(/);
 assert.ok(tag.steps.some(step=>step.uses==='./bp/cd/tasks/repo/push-tag'&&step.with?.expected_version&&step.with?.expected_sha));
 for(const step of tag.steps.filter(s=>s.uses?.startsWith('actions/checkout@')))assert.equal(step.with.repository,'cloudopsworks/blueprints');
 assert.equal(tag.steps.some(step=>step.run),false);
});
test('same host explicitly joins successful-or-ineligible tag path before scan and stage',()=>{
 const workflow=yaml(workflowFile),scan=workflow.jobs.scan;
 assert.ok([scan.needs].flat().includes('frozen-tag'),'scan must depend on same-host tag, not a later tag-trigger run');
 assert.match(scan.if||'',/needs\[['"]frozen-tag['"]\]\.result|needs\.frozen-tag\.result/);
 assert.doesNotMatch(scan.if||'',/always\(/);
 assert.ok([workflow.jobs.stage.needs].flat().includes('scan'));
 assert.equal(workflow.on.workflow_run,undefined);
});
