import test from 'node:test';
import assert from 'node:assert/strict';
import {runStep, loadStep} from './action_test_support.mjs';

const action = 'ci/config/lifecycle/action.yml';
const result = {
  eligible: true, reason: '', refClass: 'develop', environment: 'dev',
  protectedEnvironment: 'develop/dev', deploymentEnabled: true, isRelease: false,
  isPreRelease: true, hasQualifier: false, targetName: '', deploymentName: 'develop',
};
const legacy = {INPUT_MODE: 'legacy', INPUT_DEPLOYMENTS: '{"develop":{"enabled":"true"}}',
  HOST_EVENT: 'push', HOST_REF: 'refs/heads/develop', HOST_BASE_REF: ''};
function classify(env = {}, value = result, response = {}) {
  return runStep(action, 'classify', {env: {...legacy, ...env}, tools: [
    {result: {stdout: JSON.stringify(value), ...response}},
  ]});
}

test('shared lifecycle executes exact installed native classifier with legacy map on stdin', () => {
  const outcome = classify();
  assert.equal(outcome.error, undefined, JSON.stringify(outcome));
  assert.deepEqual(outcome.calls, [{kind: 'exec', command: 'tronador',
    args: ['components', 'lifecycle', '--event', 'push', '--ref', 'refs/heads/develop', '--base-ref', '', '--json', '--deployments-stdin', '--compat', 'legacy'],
    input: legacy.INPUT_DEPLOYMENTS}]);
  assert.deepEqual(outcome.outputs, {
    lifecycle: JSON.stringify(result), workspace: 'dev', workspace_upper: 'DEV',
    isEnabled: 'true', isRelease: 'false', isPreRelease: 'true', hasQualifier: 'false',
    targetName: '', deploymentName: 'develop', protectedEnvironment: 'develop/dev',
  });
});

test('schema-v2 mode passes only explicit workdir, not legacy parser or shell input', () => {
  const outcome = classify({INPUT_MODE: 'schema-v2', INPUT_SOURCE_PATH: 'source path'});
  assert.equal(outcome.error, undefined, JSON.stringify(outcome));
  assert.deepEqual(outcome.calls[0].args, ['components', 'lifecycle', '--event', 'push', '--ref', 'refs/heads/develop', '--base-ref', '', '--json', '--workdir', 'source path']);
  assert.equal(outcome.calls[0].input, undefined);
});

for (const [name, env] of [
  ['unknown mode', {INPUT_MODE: 'arbitrary'}],
  ['unsupported event', {HOST_EVENT: 'issue_comment'}],
]) test(`shared lifecycle denies ${name} before native execution`, () => {
  const outcome = runStep(action, 'classify', {env: {...legacy, ...env}});
  assert.ok(outcome.error);
  assert.deepEqual(outcome.calls, []);
  assert.deepEqual(outcome.outputs, {});
});

test('oversized legacy map denies before native execution', async () => {
  // An OS environment block cannot carry 4 MiB; invoke this actual body locally
  // without spawning the isolated worker to exercise its explicit input bound.
  const script = loadStep(action, 'classify').script;
  const original = Object.fromEntries(Object.keys(legacy).map(key => [key, process.env[key]]));
  const calls = [];
  try {
    Object.assign(process.env, legacy, {INPUT_DEPLOYMENTS: 'x'.repeat(4 * 1024 * 1024 + 1)});
    const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
    await assert.rejects(new AsyncFunction('exec', script)({getExecOutput: async (...args) => calls.push(args)}), /lifecycle-input-bound/);
    assert.deepEqual(calls, []);
  } finally {
    for (const [key, value] of Object.entries(original)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
  }
});

for (const [name, value, response] of [
  ['native failure', result, {exitCode: 1, stderr: 'secret-sentinel'}],
  ['oversized output', result, {stdout: 'x'.repeat(65537)}],
  ['unknown output field', {...result, unexpected: true}, {}],
  ['nonboolean eligibility', {...result, eligible: 'true'}, {}],
  ['nonstring environment', {...result, environment: 123}, {}],
  ['ineligible unsupported legacy ref', {...result, eligible: false, reason: 'unsupported-ref'}, {}],
]) test(`shared lifecycle denies ${name} without exposing outputs or stderr`, () => {
  const outcome = classify({}, value, response);
  assert.ok(outcome.error);
  assert.deepEqual(outcome.outputs, {});
  assert.doesNotMatch(JSON.stringify(outcome), /secret-sentinel/);
});

test('disabled legacy deployment remains an explicit classified result', () => {
  const outcome = classify({}, {...result, eligible: false, reason: 'deployment-disabled', deploymentEnabled: false});
  assert.equal(outcome.error, undefined, JSON.stringify(outcome));
  assert.equal(outcome.outputs.isEnabled, 'false');
});

test('shared lifecycle reads event/ref/base only through declared environment inputs', () => {
  const step = loadStep(action, 'classify');
  assert.equal(step.env.INPUT_MODE, '${{ inputs.mode }}');
  assert.equal(step.env.INPUT_SOURCE_PATH, '${{ inputs.source_path }}');
  assert.equal(step.env.INPUT_DEPLOYMENTS, '${{ inputs.deployments }}');
  assert.equal(step.env.HOST_BASE_REF, '${{ github.base_ref }}');
  assert.doesNotMatch(step.script, /\$\{\{/);
});
