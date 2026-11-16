import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import fs from 'node:fs';
import {createHash} from 'node:crypto';
import os from 'node:os';
import {root} from './action_test_support.mjs';

const yaml = file => {
  const parsed = spawnSync('yq', ['-o=json', '-I=0', '.', path.join(root, file)], {encoding: 'utf8'});
  assert.equal(parsed.status, 0, parsed.stderr);
  return JSON.parse(parsed.stdout);
};
const workflow = '.github/workflows/monorepo-ci.yml';
function execute(job, id, options = {}, file = workflow) {
  const step = yaml(file).jobs[job].steps.find(step => step.id === id);
  assert.equal(step?.uses, 'actions/github-script@v9');
  const result = spawnSync(process.execPath, [path.join(root, 'tests/monorepo/actions/script_worker.mjs')], {
    input: JSON.stringify({script: step.with.script, ...options}), encoding: 'utf8',
    env: {PATH: process.env.PATH, ...options.env}, cwd: options.cwd,
  });
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout);
}

test('normal CI separates metadata deployment reads from all application source execution', () => {
  const {jobs} = yaml(workflow);
  assert.deepEqual(jobs.baseline.permissions, {contents: 'read', actions: 'read', deployments: 'read', 'pull-requests': 'read'});
  const checkout = jobs.baseline.steps.find(step => step.uses?.includes('/cd/checkout@'));
  assert.equal(checkout.with.checkout_source, 'false');
  assert.ok(jobs.baseline.steps.some(step => step.uses === './bp/ci/monorepo/source'));
  assert.ok(jobs.baseline.steps.some(step => step.uses === './bp/ci/monorepo/plan/baseline' && step.with.mode === 'normal'));
  assert.equal(jobs.plan.needs, 'baseline');
  assert.deepEqual(jobs.plan.permissions, {contents: 'read', actions: 'read'});
  assert.deepEqual(jobs.build.permissions, {contents: 'read'});
  assert.deepEqual(jobs.required.permissions, {});
  for (const job of [jobs.baseline, jobs.plan, jobs.build]) {
    assert.ok(!JSON.stringify(job).includes('secrets.'));
    assert.ok(!JSON.stringify(job).includes('id-token'));
  }
  assert.ok(jobs.plan.steps.some(step => step.uses === 'actions/download-artifact@v7' && step.with['artifact-ids']));
  assert.ok(jobs.plan.steps.some(step => step.uses === './bp/ci/monorepo/plan'));
  assert.ok(jobs.build.steps.some(step => step.uses === './bp/ci/monorepo/build'));
  assert.ok(!JSON.stringify(jobs).includes('python3'));
  assert.deepEqual(jobs.required.needs, ['baseline', 'plan', 'build']);
});

for (const [baseline, plan, build, noop, succeeds] of [
  ['success','success','success','false',true], ['success','success','skipped','true',true],
  ['failure','success','success','false',false], ['cancelled','success','success','false',false],
  ['success','skipped','skipped','true',false], ['success','failure','skipped','false',false],
  ['success','success','skipped','false',false], ['success','success','cancelled','false',false],
  ['success','success','failure','false',false], ['success','success','success','true',false],
  ['success','success','success','unknown',false],
]) test(`actual aggregate ${baseline}/${plan}/${build}/${noop}`, () => {
  const result = execute('required', 'required', {env: {PHASES: JSON.stringify({baseline:{result:baseline}, plan:{result:plan,outputs:{noop}}, build:{result:build}})}});
  assert.equal(!result.error, succeeds, JSON.stringify(result));
});

test('shared reusable PR read ceiling propagates but builds retain contents-only', () => {
  for (const name of ['monorepo-pr-build.yml', 'monorepo-main-build.yml'])
    assert.equal(yaml(`.github/workflows/${name}`).jobs.ci.permissions['pull-requests'], 'read');
  assert.deepEqual(yaml(workflow).jobs.build.permissions, {contents:'read'});
});

const prWorkflow = '.github/workflows/monorepo-pr-build.yml';
const head = 'a'.repeat(40);
const captured = {number:7,head:{sha:head,repo:{id:456}},base:{repo:{id:123}}};
const prContext = {eventName:'pull_request',repo:{owner:'example',repo:'mixed'},payload:{pull_request:captured}};
const pull = record => ({method:'rest.pulls.get',args:{pull_number:7},result:{data:record}});

test('PR preparation freezes actual API/event/Git identity and defers sole version to plan composite', () => {
  const result=execute('prepare','prepare',{env:{GITHUB_REPOSITORY_ID:'123'},context:prContext,
    api:[pull(captured)],tools:[{command:'git',args:['rev-parse','HEAD'],result:{stdout:head+'\n'}}]},prWorkflow);
  assert.equal(result.error,undefined);
  assert.deepEqual(result.outputs,{head,base:'',version:'',event:'pull-request','materialize-all':'false'});
  assert.equal(result.calls.filter(call=>call.command==='tronador').length,0);
  assert.ok(!JSON.stringify(yaml(prWorkflow).jobs.prepare).includes('secrets.'));
  assert.ok(!JSON.stringify(yaml(prWorkflow).jobs.prepare).includes('lifecycle_entry.py'));
});

for (const [name,record,git] of [
  ['API raced head',{...captured,head:{...captured.head,sha:'b'.repeat(40)}},head],
  ['API wrong base',{...captured,base:{repo:{id:999}}},head],
  ['checkout wrong head',captured,'b'.repeat(40)],
]) test(`PR preparation rejects ${name}`, () => {
  const result=execute('prepare','prepare',{env:{GITHUB_REPOSITORY_ID:'123'},context:prContext,
    api:[pull(record)],tools:git===head ? [] : [{command:'git',result:{stdout:git+'\n'}}]},prWorkflow);
  assert.ok(result.error,JSON.stringify(result));
  assert.deepEqual(result.outputs,{});
});

test('actual normal identity uses source PR head, never GITHUB_SHA merge host', () => {
  const result=execute('baseline','identity',{env:{HEAD_SHA:head,PLAN_EVENT:'pull-request',GITHUB_REPOSITORY_ID:'123',GITHUB_SHA:'d'.repeat(40)},context:prContext,api:[pull(captured)]});
  assert.equal(result.error,undefined);
  assert.deepEqual(result.outputs,{head,'pr-number':'7'});
});

test('normal identity refuses user head authorization on actual push', () => {
  const result=execute('baseline','identity',{env:{HEAD_SHA:head,PLAN_EVENT:'push',GITHUB_SHA:'b'.repeat(40)},context:{eventName:'push',repo:{owner:'example',repo:'mixed'},payload:{}}});
  assert.equal(result.error?.message,'ci-source-identity');
  assert.deepEqual(result.outputs,{});
});

for (const [name,change,gitHead,success] of [
  ['exact absent baseline',{},head,true], ['wrong attempt',{runAttempt:'1'},head,false],
  ['wrong repository',{repositoryId:'999'},head,false], ['wrong source',{headSha:'b'.repeat(40)},head,false],
  ['unendorsed candidate',{found:true,baseSha:'b'.repeat(40)},head,false],
  ['wrong real Git checkout',{},'b'.repeat(40),false],
]) test(`actual planner transfer checks ${name}`, t => {
  const directory=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'normal-transfer-')));
  t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
  fs.mkdirSync(path.join(directory,'baseline-input'));
  fs.writeFileSync(path.join(directory,'baseline-input/baseline.json'),JSON.stringify({repositoryId:'123',runId:'5',runAttempt:'2',headSha:head,found:false,baseSha:'',reason:'normal-stage-unavailable',stage:null,...change}));
  const result=execute('plan','baseline',{cwd:directory,
    env:{RUNNER_TEMP:directory,HEAD_SHA:head,GITHUB_REPOSITORY_ID:'123',GITHUB_RUN_ID:'5',GITHUB_RUN_ATTEMPT:'2',BASELINE_PATH:path.join(directory,'baseline-input/baseline.json')},
    tools:[{command:'git',args:['rev-parse','HEAD'],result:{stdout:gitHead+'\n'}}]});
  assert.equal(!result.error,success,JSON.stringify(result));
  assert.equal(result.calls.length,1);assert.equal(result.calls[0].command,'git');
  if(success){
    assert.deepEqual(Object.keys(result.outputs).sort(),['base-sha','receipt','receipt-digest']);assert.equal(result.outputs['base-sha'],'');
    const original=fs.readFileSync(path.join(directory,'baseline-input/baseline.json')),receipt=result.outputs.receipt;
    assert.ok(receipt.startsWith(directory+path.sep));assert.notEqual(receipt,path.join(directory,'baseline-input/baseline.json'));
    assert.deepEqual(fs.readFileSync(receipt),original);
    assert.equal(result.outputs['receipt-digest'],'sha256:'+createHash('sha256').update(original).digest('hex'));
    assert.equal(fs.statSync(path.dirname(receipt)).mode&0o777,0o700);assert.equal(fs.statSync(receipt).mode&0o777,0o600);
  }else{assert.equal(result.error.message,name==='wrong real Git checkout'?'ci-plan-checkout':'ci-baseline-binding');assert.deepEqual(result.outputs,{});}
});

test('normal planner reads back and endorses its actual upload before publishing routing outputs', () => {
  const document=yaml(workflow),job=document.jobs.plan;
  assert.equal(job.permissions.actions,'read');
  const upload=job.steps.findIndex(step=>step.id==='plan-upload');
  const emit=job.steps.findIndex(step=>step.id==='plan-endorsement');
  assert.ok(upload>=0&&emit>upload);
  assert.equal(job.steps[emit].uses,'./bp/ci/monorepo/plan/endorsement');
  assert.equal(job.steps[emit].with.mode,'emit');
  assert.match(job.steps[emit].with['caller-mode'],/normal-pr.*normal-closure.*normal-main/);
  assert.equal(job.steps[emit].with['computed-plan'],'${{ steps.plan.outputs.plan }}');
  assert.equal(job.steps[emit].with['archive-digest'],'${{ steps.plan-upload.outputs.artifact-digest }}');
  assert.equal(document.on.workflow_call.outputs['plan-artifact-digest'].value,'${{ jobs.plan.outputs.plan-artifact-digest }}');
});
test('merged-closure CI ceiling propagates read-only PR lookup',()=>{
  assert.equal(yaml('.github/workflows/monorepo-closure.yml').jobs.ci.permissions['pull-requests'],'read');
});
test('actual merged closure identity builds the independently corroborated merge, not default host SHA',()=>{
  const merge='e'.repeat(40),base='c'.repeat(40),tip='f'.repeat(40);
  const record={number:7,state:'closed',merged:true,merge_commit_sha:merge,head:{sha:head,repo:{id:123}},base:{sha:base,ref:'support/1.2',repo:{id:123}}};
  const result=execute('baseline','identity',{env:{HEAD_SHA:merge,PLAN_EVENT:'push',GITHUB_REPOSITORY_ID:'123',GITHUB_SHA:'d'.repeat(40)},context:{eventName:'pull_request_target',repo:{owner:'example',repo:'mixed'},payload:{action:'closed',pull_request:record}},api:[pull(record),{method:'rest.repos.getBranch',args:{branch:'support/1.2'},result:{data:{protected:true,commit:{sha:tip}}}},...[[base,merge],[merge,tip]].map(([from,to])=>({method:'rest.repos.compareCommitsWithBasehead',args:{basehead:from+'...'+to},result:{data:{status:'ahead',base_commit:{sha:from},merge_base_commit:{sha:from}}}}))]});
  assert.equal(result.error,undefined,JSON.stringify(result));
  assert.deepEqual(result.outputs,{head:merge,'pr-number':'7'});
});

test('closed normal writer mappings follow actual caller/reusable names at each nesting level',()=>{
 const parse=filename=>{const r=spawnSync('yq',['-o=json','.',filename],{encoding:'utf8'});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout);};
 const caller=file=>parse(path.join(root,'../monorepo-app-template/.github/workflows',file));
 const ci=yaml(workflow),endorsement=fs.readFileSync(path.join(root,'ci/monorepo/plan/endorsement/action.yml'),'utf8');
 const routes=[
  [caller('main-build.yml').jobs.lifecycle,yaml('.github/workflows/monorepo-main-build.yml').jobs.ci],
  [caller('pr-build.yml').jobs.ci,yaml('.github/workflows/monorepo-pr-build.yml').jobs.ci],
  [caller('pr-close.yaml').jobs.close,yaml('.github/workflows/monorepo-pr-close.yml').jobs.lifecycle,yaml('.github/workflows/monorepo-closure.yml').jobs.ci],
 ];
 const ids=[['lifecycle','ci'],['ci','ci'],['close','lifecycle','ci']];
 for(const [index,route]of routes.entries()){
  assert.ok(route.every(job=>job.uses?.includes('/.github/workflows/monorepo-')));
  const name=route.map((job,i)=>job.name||ids[index][i]).concat(ci.jobs.plan.name).join(' / ');
  assert.ok(endorsement.includes("'"+name+"'"),name);
 }
});

test('actual ingress rejects BOM canonical bytes before any output',t=>{
 const directory=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'normal-transfer-bom-')));t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
 const file=path.join(directory,'baseline.json'),record={repositoryId:'123',runId:'5',runAttempt:'2',headSha:head,found:false,baseSha:'',reason:'normal-stage-unavailable',stage:null};fs.writeFileSync(file,Buffer.concat([Buffer.from([0xef,0xbb,0xbf]),Buffer.from(JSON.stringify(record))]));
 const r=execute('plan','baseline',{env:{RUNNER_TEMP:directory,BASELINE_PATH:file,HEAD_SHA:head,GITHUB_REPOSITORY_ID:'123',GITHUB_RUN_ID:'5',GITHUB_RUN_ATTEMPT:'2'},tools:[{command:'git',args:['rev-parse','HEAD'],result:{stdout:head+'\n'}}]});
 assert.equal(r.error?.message,'ci-baseline-binding');assert.deepEqual(r.outputs,{});assert.equal(r.calls.length,1);
});
