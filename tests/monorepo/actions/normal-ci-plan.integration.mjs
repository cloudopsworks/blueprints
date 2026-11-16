import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {runStep} from './action_test_support.mjs';

const cli = process.env.TRONADOR_CLI;
assert.ok(cli && fs.existsSync(cli), 'actual reviewed CLI binary required');
const action = 'ci/monorepo/plan/action.yml';

test('actual plan body uses real Git selection, explicit all and sole CLI concurrency projection', t => {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'normal-ci-git-')));
  t.after(() => fs.rmSync(root, {recursive: true, force: true}));
  const source = path.join(root, 'source');
  fs.cpSync(fileURLToPath(new URL('../fixtures/composite_first/mixed/', import.meta.url)), source, {recursive: true});
  const env = {HOME: root, SOURCE_PATH: source, RUNNER_TEMP: root, GITHUB_REPOSITORY_ID: '123',
    GITHUB_REPOSITORY: 'example/mixed', VERSION: '1.2.3', PLAN_EVENT: 'push', PR_NUMBER: '0',
    PLAN_ALL: 'false', MAX_PARALLEL: '32'};
  const git = (...args) => {
    const result = spawnSync('git', ['-c', 'core.hooksPath=/dev/null', '-c', 'user.name=Local', '-c',
      'user.email=test@example.invalid', ...args], {cwd: source, env: {PATH: process.env.PATH, HOME: root}, encoding: 'utf8'});
    assert.equal(result.status, 0, result.stderr);
    return result.stdout.trim();
  };
  const run = (step, extra = {}) => runStep(action, step, {realCli: cli, env: {...env, ...extra}});
  const planned = extra => {
    const result = run('plan', extra);
    assert.equal(result.error, undefined, JSON.stringify(result));
    return JSON.parse(fs.readFileSync(result.outputs.plan));
  };
  git('init', '-q', '-b', 'develop'); git('add', '.'); git('commit', '-qm', 'initial');
  const base = git('rev-parse', 'HEAD');
  const cap = run('limits', {MAX_PARALLEL: '1'});
  assert.equal(cap.error, undefined, JSON.stringify(cap));
  assert.equal(cap.outputs['max-parallel'], '1');
  const configured = run('limits');
  assert.equal(configured.error, undefined, JSON.stringify(configured));
  assert.equal(configured.outputs['max-parallel'], '2');
  const initial = planned({HEAD_SHA: base, BASE_SHA: ''});
  assert.deepEqual(initial.buildSelection.map(item => item.componentId), ['go', 'node']);
  fs.appendFileSync(path.join(source, 'components/node/index.js'), '\n// changed\n');
  git('add', '.'); git('commit', '-qm', 'node changed'); const head = git('rev-parse', 'HEAD');
  const partial = planned({HEAD_SHA: head, BASE_SHA: base});
  assert.deepEqual(partial.buildSelection.map(item => item.componentId), ['node']);
  assert.equal(partial.baseSha, base);
  const all = planned({HEAD_SHA: head, BASE_SHA: base, PLAN_ALL: 'true'});
  assert.deepEqual(all.buildSelection.map(item => item.componentId), ['go', 'node']);
  const noop = planned({HEAD_SHA: head, BASE_SHA: head});
  assert.equal(noop.buildNoop, true); assert.deepEqual(noop.buildSelection, []);
  git('mv', 'components/node/index.js', 'components/node/renamed.js');
  git('commit', '-qm', 'rename node source'); const renamed = git('rev-parse', 'HEAD');
  assert.deepEqual(planned({HEAD_SHA: renamed, BASE_SHA: head}).buildSelection.map(item => item.componentId), ['node']);
  fs.mkdirSync(path.join(source, 'shared'));
  fs.writeFileSync(path.join(source, 'shared/change.txt'), 'shared input');
  git('add', '.'); git('commit', '-qm', 'shared changed'); const shared = git('rev-parse', 'HEAD');
  assert.deepEqual(planned({HEAD_SHA: shared, BASE_SHA: renamed}).buildSelection.map(item => item.componentId), ['go', 'node']);
  const config = path.join(source, '.cloudopsworks/cloudopsworks-ci.yaml');
  fs.writeFileSync(config,fs.readFileSync(config,'utf8').replace('dependsOn: []','dependsOn: [go]'));
  git('add','.'); git('commit','-qm','node depends on go'); const dependencyBase=git('rev-parse','HEAD');
  fs.appendFileSync(path.join(source,'components/go/main.go'),'\n// dependency changed\n');
  git('add','.'); git('commit','-qm','go changed'); const dependencyHead=git('rev-parse','HEAD');
  assert.deepEqual(planned({HEAD_SHA:dependencyHead,BASE_SHA:dependencyBase}).buildSelection.map(item=>item.componentId),['go','node']);
  fs.writeFileSync(config, fs.readFileSync(config, 'utf8').replace('maxParallel: 2', 'maxParallel: 33'));
  const invalid = run('limits');
  assert.equal(invalid.error?.message, 'plan-configuration');
  assert.deepEqual(invalid.outputs, {});
  // This is actual CLI/Git projection; no hosted workflow or package build claim.
});

test('actual normal receipt reader uses installed Go PreviewState validation, not JS schema acceptance', t => {
  const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'normal-ci-receipt-')));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  const configuration=path.join(root,'configuration.json');
  fs.writeFileSync(configuration,JSON.stringify({previewPolicy:{enabled:true,targets:[{targetId:'eks'}]}}));
  const state={apiVersion:'cloudopsworks.io/v1',kind:'PreviewState',repository:{id:'123',fullName:'example/mixed'},prNumber:7,targetId:'eks',namespace:'pr-7-eks-123456789012',headSha:'b'.repeat(40),runId:'5',phase:'ready',isolation:null,components:[]};
  const result=runStep('ci/monorepo/plan/baseline/action.yml','normal',{realCli:cli,
    env:{RUNNER_TEMP:root,CONFIGURATION:configuration,HEAD_SHA:'a'.repeat(40),PR_NUMBER:'7',AUTOMATION_ID:'99',GITHUB_REPOSITORY_ID:'123',GITHUB_REPOSITORY:'example/mixed',GITHUB_RUN_ID:'5',GITHUB_RUN_ATTEMPT:'2'},
    api:[{method:'rest.repos.listDeployments',result:{data:[{id:10,creator:{id:99},payload:{kind:'PreviewMetadata',state}}]}}]});
  assert.equal(result.error,undefined,JSON.stringify(result));
  const record=JSON.parse(fs.readFileSync(result.outputs.baseline));
  assert.equal(record.found,false);
  assert.equal(record.baseSha,'');
  assert.equal(record.reason,'preview-receipt-unusable');
  const call=result.calls.find(call=>call.command==='tronador');
  assert.notEqual(call.result.exitCode,0);
  assert.match(call.result.stderr,/preview-isolation-required/);
});
