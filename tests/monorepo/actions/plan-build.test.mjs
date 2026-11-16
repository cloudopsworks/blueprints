import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {runStep, loadStep} from './action_test_support.mjs';

const planAction = 'ci/monorepo/plan/action.yml';
const buildAction = 'ci/monorepo/build/action.yml';
const head = 'a'.repeat(40), base = 'b'.repeat(40);

function temporary(t) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'composite-action-test-')));
  t.after(() => fs.rmSync(root, {recursive: true, force: true}));
  return root;
}
function environment(root) {
  return {SOURCE_PATH: root, RUNNER_TEMP: root, HEAD_SHA: head, BASE_SHA: base,
    VERSION: '1.2.3', PLAN_EVENT: 'push', PR_NUMBER: '0',
    GITHUB_REPOSITORY_ID: '123', GITHUB_REPOSITORY: 'example/mixed'};
}
function tool(prefix, value, exitCode = 0) {
  return {prefix, result: {exitCode, stdout: typeof value === 'string' ? value : JSON.stringify(value)}};
}
function planned() {
  return {headSha: head, version: '1.2.3', matrix: {include: [{componentId: 'api'}]}, buildNoop: false};
}

test('test loader reads the actual v9 production body, not a copied fixture', () => {
  const actual = loadStep(planAction, 'plan');
  assert.match(actual.script, /components.*plan/);
  assert.equal(actual.env.HEAD_SHA, '${{ inputs.head-sha }}');
  assert.throws(() => loadStep(planAction, 'not-a-real-step'), /Actual v9 step missing/);
});

test('plan action invokes the real command boundary and writes only validated output', t => {
  const root = temporary(t), record = planned();
  const result = runStep(planAction, 'plan', {env: environment(root), tools: [
    tool(['components', 'plan'], record),
    tool(['components', 'contracts', 'validate', '--kind', 'BuildPlan'], {record}),
  ]});
  assert.equal(result.error, undefined);
  assert.equal(result.outputs.version, '1.2.3');
  assert.equal(result.outputs.noop, 'false');
  assert.deepEqual(JSON.parse(result.outputs.matrix), record.matrix);
  assert.deepEqual(JSON.parse(fs.readFileSync(result.outputs.plan)), record);
  assert.equal(fs.statSync(result.outputs.plan).mode & 0o777, 0o600);
  assert.equal(fs.statSync(path.dirname(result.outputs.plan)).mode & 0o777, 0o700);
  const args = result.calls[0].args;
  assert.equal(args[args.indexOf('--head') + 1], head);
  assert.equal(args[args.indexOf('--base') + 1], base);
  assert.equal(args[args.indexOf('--workdir') + 1], root);
  assert.equal(result.calls[1].input, JSON.stringify(record));
});

for (const [name, override] of [
  ['invalid source SHA', {HEAD_SHA: 'head-from-output'}],
  ['invalid base SHA', {BASE_SHA: 'refs/heads/main'}],
  ['unknown event', {PLAN_EVENT: 'execute'}],
  ['non-numeric PR', {PR_NUMBER: '; touch marker'}],
  ['wrong repository', {GITHUB_REPOSITORY: 'other/repository'}],
]) {
  test(`plan rejects ${name} before any CLI execution`, t => {
    const result = runStep(planAction, 'plan', {env: {...environment(temporary(t)), ...override}});
    assert.ok(result.error);
    assert.deepEqual(result.calls, []);
    assert.deepEqual(result.outputs, {});
  });
}

for (const field of ['headSha', 'version']) {
  test(`plan rejects validated record with mismatched ${field} before outputs`, t => {
    const record = {...planned(), [field]: 'mismatched'};
    const result = runStep(planAction, 'plan', {env: environment(temporary(t)), tools: [
      tool(['components', 'plan'], planned()),
      tool(['components', 'contracts', 'validate'], {record}),
    ]});
    assert.equal(result.error?.message, 'plan-link');
    assert.deepEqual(result.outputs, {});
  });
}

test('planner subprocess failure cannot become a successful empty selection', t => {
  const result = runStep(planAction, 'plan', {env: environment(temporary(t)),
    tools: [tool(['components', 'plan'], '{}', 1)]});
  assert.equal(result.error?.message, 'plan-cli');
  assert.deepEqual(result.outputs, {});
  assert.equal(result.calls.length, 1);
});

function buildEnvironment(root) {
  const filename = path.join(root, 'plan.json');
  fs.writeFileSync(filename, JSON.stringify(planned()));
  return {...environment(root), PLAN_PATH: filename, COMPONENT: 'api'};
}
function buildTools(record = {componentId: 'api', status: 'succeeded'}) {
  return [tool(['components', 'build'], {}), tool(['components', 'test'], {}),
    tool(['components', 'package'], record),
    tool(['components', 'contracts', 'validate', '--kind', 'ComponentResult'], {record})];
}

test('build action runs typed build then test then package and validates the result', t => {
  const root = temporary(t), env = buildEnvironment(root);
  const result = runStep(buildAction, 'build', {env, tools: buildTools()});
  assert.equal(result.error, undefined);
  assert.deepEqual(result.calls.map(call => call.args[1]), ['build', 'test', 'package', 'contracts']);
  for (const call of result.calls.slice(0, 3)) {
    assert.equal(call.command, 'tronador');
    assert.equal(call.args[2], 'api');
    assert.ok(call.args.includes('--no-install-tools'));
  }
  assert.equal(JSON.parse(fs.readFileSync(result.outputs.result)).componentId, 'api');
  assert.equal(fs.statSync(result.outputs.result).mode & 0o777, 0o600);
});

test('a failed component test stops before packaging or exposing a result', t => {
  const result = runStep(buildAction, 'build', {env: buildEnvironment(temporary(t)), tools: [
    tool(['components', 'build'], {}), tool(['components', 'test'], {}, 1),
  ]});
  assert.equal(result.error?.message, 'component-test-failed');
  assert.equal(result.calls.length, 2);
  assert.deepEqual(result.outputs, {});
});

for (const record of [{componentId: 'other', status: 'succeeded'}, {componentId: 'api', status: 'failed'}]) {
  test(`build denies result owner/status ${JSON.stringify(record)}`, t => {
    const result = runStep(buildAction, 'build', {
      env: buildEnvironment(temporary(t)), tools: buildTools(record),
    });
    assert.equal(result.error?.message, 'build-result-owner');
    assert.deepEqual(result.outputs, {});
  });
}

test('component bundle refuses traversal before invoking payload verifier', t => {
  const root = temporary(t), resultPath = path.join(root, 'result.json');
  fs.writeFileSync(resultPath, JSON.stringify({componentId: 'api', mainArtifact: {
    location: {kind: 'local', path: '.cloudopsworks/out/../../escape.zip'},
  }}));
  const result = runStep(buildAction, 'bundle', {
    env: {...environment(root), RESULT_PATH: resultPath},
  });
  assert.equal(result.error?.message, 'bundle-payload-path');
  assert.deepEqual(result.outputs, {});
  assert.deepEqual(result.calls, []);
});

test('bundle output is withheld when inner payload verification fails', t => {
  const root = temporary(t), payload = '.cloudopsworks/out/api/1.2.3/main.zip';
  fs.mkdirSync(path.dirname(path.join(root, payload)), {recursive: true});
  fs.writeFileSync(path.join(root, payload), 'not-verified');
  const resultPath = path.join(root, 'result.json');
  fs.writeFileSync(resultPath, JSON.stringify({componentId: 'api', mainArtifact: {
    location: {kind: 'local', path: payload},
  }}));
  const result = runStep(buildAction, 'bundle', {
    env: {...environment(root), RESULT_PATH: resultPath},
    tools: [tool(['components', 'artifacts', 'verify', '--mode', 'payload'], {payloadVerified: false})],
  });
  assert.equal(result.error?.message, 'bundle-payload-validation');
  assert.deepEqual(result.outputs, {});
});
