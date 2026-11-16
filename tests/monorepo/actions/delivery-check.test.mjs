import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import {root, runStep} from './action_test_support.mjs';

const action = 'ci/monorepo/delivery-check/action.yml';
const source = 'a'.repeat(40);
const originUrl = 'https://github.com/example/mixed/actions/runs/41/attempts/2';
const deliveryUrl = 'https://github.com/example/mixed/actions/runs/70/attempts/1';
const name = 'monorepo-delivery/41/2';
const external = 'cloudopsworks:123:41:2';
const base = {GITHUB_REPOSITORY_ID:'123',GITHUB_RUN_ID:'41',GITHUB_RUN_ATTEMPT:'2',
  GITHUB_SERVER_URL:'https://github.com',GITHUB_REPOSITORY:'example/mixed',PHASE:'initialize',
  SOURCE_SHA:source,CALLER_MODE:'normal-main',ORIGIN_RUN_ID:'41',ORIGIN_RUN_ATTEMPT:'2',
  CHECK_ID:'',ENDORSED_CHECK_NAME:''};
const check = (extra = {}) => ({id:91,name,head_sha:source,external_id:external,
  app:{id:15368,slug:'github-actions'},status:'queued',conclusion:null,details_url:originUrl,...extra});
const response = (method,data,args={}) => ({method:'rest.'+method,args,result:{data}});
const get = data => response('checks.get',data,{check_run_id:91});
const context = {eventName:'push',repo:{owner:'example',repo:'mixed'},payload:{}};
function run(env={},api=[],ctx=context) { return runStep(action,'check',{env:{...base,...env},api,context:ctx}); }
const continuation = {GITHUB_RUN_ID:'70',GITHUB_RUN_ATTEMPT:'1',CHECK_ID:'91',ENDORSED_CHECK_NAME:name};
const continuationContext = {eventName:'workflow_run',repo:context.repo,payload:{workflow_run:{id:41,run_attempt:2}}};
const job = (conclusion='success',extra={}) => ({id:88,run_id:70,run_attempt:1,
  name:'delivery / monorepo-delivery-required',status:'completed',conclusion,...extra});
const jobs = records => response('actions.listJobsForWorkflowRunAttempt',{jobs:records},{run_id:'70',attempt_number:'1',page:1,per_page:100});

// First execution is deliberately RED while the production action does not exist.
test('source-free action resolves independent closed context and exposes no success flag', () => {
  const parsed = spawnSync('yq',['-o=json','-I=0','.',path.join(root,action)],{encoding:'utf8'});
  assert.equal(parsed.status,0,parsed.stderr);
  const yaml = JSON.parse(parsed.stdout);
  assert.deepEqual(Object.keys(yaml.inputs).sort(),['check-id','phase']);
  assert.equal(yaml.runs.steps[0].uses,'./bp/cd/tasks/repo/context');
  assert.match(yaml.runs.steps[0].with.mode,/workflow_run.*delivery.*normal/);
  assert.equal(yaml.runs.steps[1].with.retries,0);
  assert.ok(!readFileSync(path.join(root,action),'utf8').includes('checks.listForRef'));
});
test('initializer creates one queued source-bound check and independently GETs returned exact ID', () => {
  const result=run({},[response('checks.create',check(),{name,head_sha:source,external_id:external,status:'queued',details_url:originUrl}),get(check())]);
  assert.equal(result.error,undefined,JSON.stringify(result));
  assert.deepEqual(result.outputs,{'check-id':'91','check-name':name});
  assert.equal(result.calls.length,2);
});
test('a lost create response is not retried or adopted by name', () => {
  const result=run({},[{method:'rest.checks.create',error:{message:'response lost',status:502}}]);
  assert.ok(result.error);
  assert.equal(result.calls.length,1);
  assert.deepEqual(result.outputs,{});
});
for (const [label,env,ctx] of [
  ['PR', {CALLER_MODE:'normal-pr'},context],
  ['historical origin',{GITHUB_RUN_ID:'90'},context],
  ['unsupported phase',{PHASE:'success'},context],
  ['rerun delivery host',{...continuation,PHASE:'start',GITHUB_RUN_ATTEMPT:'2'},continuationContext],
  ['spoofed workflow event',{...continuation,PHASE:'start'},context],
  ['wrong event origin',{...continuation,PHASE:'start'},{...continuationContext,payload:{workflow_run:{id:42,run_attempt:2}}}],
  ['unendorsed check',{...continuation,PHASE:'start',ENDORSED_CHECK_NAME:''},continuationContext],
]) test(`reject ${label} before API mutation`,()=>{
  const result=run(env,[],ctx); assert.ok(result.error); assert.equal(result.calls.length,0);
});
for (const [field,value] of Object.entries({id:92,name:'other',head_sha:'b'.repeat(40),external_id:'other',
  app:{id:0,slug:'github-actions'},details_url:deliveryUrl,status:'completed',conclusion:'success'}))
  test(`initializer rejects acknowledged ${field} mismatch`,()=>{
    const result=run({},[response('checks.create',check()),get(check({[field]:value}))]);
    assert.ok(result.error,JSON.stringify(result)); assert.deepEqual(result.outputs,{});
  });
test('continuation starts only exact endorsed ID and reads update back',()=>{
  const running=check({status:'in_progress',details_url:deliveryUrl});
  const result=run({...continuation,PHASE:'start'},[get(check()),response('checks.update',running,
    {check_run_id:91,status:'in_progress',details_url:deliveryUrl}),get(running)],continuationContext);
  assert.equal(result.error,undefined,JSON.stringify(result));
  assert.equal(result.calls.length,3);
});
for (const conclusion of ['success','failure','cancelled','skipped']) test(`finish derives ${conclusion} from actual exact required job`,()=>{
  const expected=conclusion==='success'?'success':conclusion==='cancelled'?'cancelled':'failure';
  const running=check({status:'in_progress',details_url:deliveryUrl});
  const done=check({status:'completed',conclusion:expected,details_url:deliveryUrl});
  const result=run({...continuation,PHASE:'finish'},[get(running),jobs([job(conclusion)]),
    response('checks.update',done,{check_run_id:91,status:'completed',conclusion:expected}),get(done)],continuationContext);
  assert.equal(result.error,undefined,JSON.stringify(result));
});
for (const [label,records] of [
  ['missing',[]],['duplicate',[job(),job()]],['retained old attempt',[job('success',{run_attempt:0})]],
  ['wrong run',[job('success',{run_id:69})]],['incomplete',[job(null,{status:'in_progress'})]],
  ['wrong nested name',[job('success',{name:'monorepo-delivery-required'})]],
]) test(`finish rejects ${label} required job without mutation`,()=>{
  const result=run({...continuation,PHASE:'finish'},[get(check({status:'in_progress',details_url:deliveryUrl})),jobs(records)],continuationContext);
  assert.ok(result.error,JSON.stringify(result));
  assert.equal(result.calls.filter(c=>c.method==='rest.checks.update').length,0);
});
test('origin failure cannot publish delivery success when original CI succeeded',()=>{
  const result=run({PHASE:'origin-failure',CHECK_ID:'91'},[get(check()),
    response('actions.listJobsForWorkflowRunAttempt',{jobs:[job('success',{run_id:41,run_attempt:2,name:'lifecycle / ci / monorepo-ci-required'})]},
      {run_id:'41',attempt_number:'2'})]);
  assert.ok(result.error); assert.equal(result.calls.filter(c=>c.method==='rest.checks.update').length,0);
});
test('initializer rejects App identity changing between create and acknowledged readback',()=>{
  const r=run({},[response('checks.create',check()),get(check({app:{id:999,slug:'github-actions'}}))]);
  assert.ok(r.error,JSON.stringify(r)); assert.deepEqual(r.outputs,{});
});
test('continuation cannot replace another attempt record even at identical source SHA',()=>{
  const r=run({...continuation,PHASE:'start'},[get(check({name:'monorepo-delivery/41/3',external_id:'cloudopsworks:123:41:3'}))],continuationContext);
  assert.ok(r.error);assert.equal(r.calls.length,1);
});
test('already claimed in-progress record cannot be claimed again',()=>{
  const r=run({...continuation,PHASE:'start'},[get(check({status:'in_progress',details_url:deliveryUrl}))],continuationContext);
  assert.ok(r.error); assert.equal(r.calls.length,1);
});
test('deleted exact ID is not replaced',()=>{
  const r=run({...continuation,PHASE:'start'},[{method:'rest.checks.get',error:{status:404}}],continuationContext);
  assert.ok(r.error); assert.equal(r.calls.length,1);
});
