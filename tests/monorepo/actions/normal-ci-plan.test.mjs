import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {runStep} from './action_test_support.mjs';

const action = 'ci/monorepo/plan/action.yml';
function directory(t) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'normal-ci-plan-')));
  t.after(() => fs.rmSync(root, {recursive: true, force: true}));
  return root;
}
function environment(t, extra = {}) {
  return {SOURCE_PATH: directory(t), PLAN_ALL: 'false', MAX_PARALLEL: '32', ...extra};
}
function validation(maxParallel = 2, extra = {}) {
  return {prefix: ['components', 'validate'], result: {exitCode: 0, stdout: JSON.stringify({valid: true, schemaVersion: 2, maxParallel, ...extra})}};
}

for (const [configured, cap, expected] of [[2, 32, 2], [16, 4, 4], [1, 1, 1], [32, 32, 32]]) {
  test(`actual plan limits obey Go-normalized config ${configured} and caller cap ${cap}`, t => {
    const env = environment(t, {MAX_PARALLEL: String(cap)});
    const result = runStep(action, 'limits', {env, tools: [validation(configured)]});
    assert.equal(result.error, undefined);
    assert.deepEqual(result.outputs, {all: 'false', 'max-parallel': String(expected)});
    assert.deepEqual(result.calls[0].args, ['components', 'validate', '--workdir', env.SOURCE_PATH, '--json']);
    assert.equal(result.calls[0].command, 'tronador');
  });
}

for (const [name, extra] of [['boolean', {PLAN_ALL: 'false; true'}], ['quoted-number', {MAX_PARALLEL: '2.0'}],
  ['zero', {MAX_PARALLEL: '0'}], ['over-limit', {MAX_PARALLEL: '33'}], ['negative', {MAX_PARALLEL: '-1'}]]) {
  test(`plan limits reject ${name} before a config process`, t => {
    const result = runStep(action, 'limits', {env: environment(t, extra)});
    assert.equal(result.error?.message, 'plan-limits');
    assert.deepEqual(result.calls, []);
    assert.deepEqual(result.outputs, {});
  });
}

for (const invalid of [0, 33, '2', null, 2.5]) {
  test(`plan limits reject invalid CLI configuration projection ${JSON.stringify(invalid)}`, t => {
    const result = runStep(action, 'limits', {env: environment(t), tools: [validation(invalid)]});
    assert.equal(result.error?.message, 'plan-configuration');
    assert.deepEqual(result.outputs, {});
  });
}

test('failed config validation is not an empty plan or caller-only concurrency', t => {
  const result = runStep(action, 'limits', {env: environment(t), tools: [
    {prefix: ['components', 'validate'], result: {exitCode: 1, stdout: '{}'}},
  ]});
  assert.equal(result.error?.message, 'plan-configuration');
  assert.deepEqual(result.outputs, {});
});

test('explicit all remains a fixed existing CLI flag, not an ad-hoc selector', t => {
  const root = directory(t), record = {headSha: 'a'.repeat(40), version: '1.2.3', matrix: {include: []}, buildNoop: true};
  const result = runStep(action, 'plan', {env: {SOURCE_PATH: root, RUNNER_TEMP: root, HEAD_SHA: record.headSha,
    BASE_SHA: 'b'.repeat(40), VERSION: record.version, PLAN_EVENT: 'push', PR_NUMBER: '0', PLAN_ALL: 'true',
    GITHUB_REPOSITORY_ID: '123', GITHUB_REPOSITORY: 'example/mixed'}, tools: [
      {prefix: ['components', 'plan'], result: {exitCode: 0, stdout: JSON.stringify(record)}},
      {prefix: ['components', 'contracts', 'validate'], result: {exitCode: 0, stdout: JSON.stringify({record})}},
    ]});
  assert.equal(result.error, undefined);
  assert.equal(result.calls[0].args.filter(value => value === '--all').length, 1);
  assert.equal(result.calls[0].args[result.calls[0].args.indexOf('--base') + 1], 'b'.repeat(40));
});
