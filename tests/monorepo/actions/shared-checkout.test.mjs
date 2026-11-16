import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import {root, runStep} from './action_test_support.mjs';

const action = 'cd/checkout/action.yml';
const parsed = spawnSync('yq', ['-o=json', '-I=0', '.', path.join(root, action)], {encoding: 'utf8'});
assert.equal(parsed.status, 0, parsed.stderr);
const definition = JSON.parse(parsed.stdout);
const validation = definition.runs.steps[0];
const defaults = {
  SOURCE_PATH: 'source', BLUEPRINT_PATH: 'bp', CHECKOUT_SOURCE: 'true',
  PERSIST_CREDENTIALS: 'true', CHECK_MODULE_VERSION: 'true',
};
function validate(overrides = {}) {
  const env = {...defaults, ...overrides};
  return runStep(action, 'validate', {env});
}

test('checkout validation is an inline v9 action, before every checkout', () => {
  assert.equal(validation.uses, 'actions/github-script@v9');
  assert.equal(validation.id, 'validate');
  assert.equal(validation.run, undefined);
  assert.equal(validation.shell, undefined);
});

for (const [name, values] of [
  ['legacy defaults', {}],
  ['root source reserves fixed bp', {SOURCE_PATH: '.'}],
  ['explicit nested disjoint paths', {SOURCE_PATH: 'work/source', BLUEPRINT_PATH: 'work/platform', CHECK_MODULE_VERSION: 'false'}],
  ['custom blueprint without legacy lookup', {BLUEPRINT_PATH: 'platform', CHECK_MODULE_VERSION: 'false'}],
  ['data only', {CHECKOUT_SOURCE: 'false', CHECK_MODULE_VERSION: 'false', PERSIST_CREDENTIALS: 'false'}],
  ['disabled credential persistence', {PERSIST_CREDENTIALS: 'false'}],
  ['ASCII dots underscores and hyphens', {SOURCE_PATH: '.work/source_1-2.3'}],
  ['maximum path length', {SOURCE_PATH: 'a'.repeat(256)}],
  ['similar nonoverlapping names', {SOURCE_PATH: 'bp-source'}],
]) test(`checkout accepts ${name}`, () => {
  const result = validate(values);
  assert.equal(result.error, undefined, JSON.stringify(result));
  assert.deepEqual(result.calls, []);
  assert.deepEqual(result.outputs, {});
});

for (const [name, values] of [
  ['empty source', {SOURCE_PATH: ''}], ['empty blueprint', {BLUEPRINT_PATH: ''}],
  ['absolute source', {SOURCE_PATH: '/source'}], ['absolute blueprint', {BLUEPRINT_PATH: '/bp'}],
  ['parent traversal', {SOURCE_PATH: '../source'}], ['nested parent traversal', {SOURCE_PATH: 'work/../source'}],
  ['dot segment', {SOURCE_PATH: 'work/./source'}], ['empty segment', {SOURCE_PATH: 'work//source'}],
  ['trailing slash', {SOURCE_PATH: 'source/'}], ['backslash', {SOURCE_PATH: 'work\\source'}],
  ['unicode', {SOURCE_PATH: 'sourcé'}], ['newline', {SOURCE_PATH: 'source\nnext'}],
  ['trailing newline', {SOURCE_PATH: 'source\n'}], ['trailing carriage return', {SOURCE_PATH: 'source\r'}],
  ['trailing CRLF', {BLUEPRINT_PATH: 'bp\r\n'}],
  ['shell punctuation', {SOURCE_PATH: 'source;echo'}], ['git root', {SOURCE_PATH: '.git'}],
  ['nested git path', {SOURCE_PATH: 'work/.git/source'}], ['blueprint git path', {BLUEPRINT_PATH: '.git/bp'}],
  ['oversized path', {SOURCE_PATH: 'a'.repeat(257)}], ['blueprint root', {BLUEPRINT_PATH: '.'}],
  ['same destination', {SOURCE_PATH: 'bp'}], ['blueprint under source', {SOURCE_PATH: 'work', BLUEPRINT_PATH: 'work/bp', CHECK_MODULE_VERSION: 'false'}],
  ['source under blueprint', {SOURCE_PATH: 'bp/source'}], ['root custom blueprint', {SOURCE_PATH: '.', BLUEPRINT_PATH: 'platform', CHECK_MODULE_VERSION: 'false'}],
  ['custom legacy blueprint', {BLUEPRINT_PATH: 'platform'}],
  ['data-only legacy lookup', {CHECKOUT_SOURCE: 'false'}],
  ...['CHECKOUT_SOURCE', 'PERSIST_CREDENTIALS', 'CHECK_MODULE_VERSION'].flatMap(key =>
    ['', 'TRUE', '1', 'false\ntrue'].map(value => [`invalid ${key} ${JSON.stringify(value)}`, {[key]: value}])) ,
]) test(`checkout rejects ${name} before checkout or any tool call`, () => {
  const result = validate(values);
  assert.ok(result.error, JSON.stringify(result));
  assert.deepEqual(result.calls, []);
  assert.deepEqual(result.outputs, {});
});

test('checkout preserves all public input defaults, outputs, refs and native checkout behavior', () => {
  assert.deepEqual(Object.fromEntries(Object.entries(definition.inputs).map(([key, value]) => [key, value.default])), {
    source_path: 'source', blueprint_path: 'bp', source_ref: '${{ github.ref }}', blueprint_ref: 'v5.10',
    token: '', checkout_source: 'true', persist_credentials: 'true', check_module_version: 'true',
  });
  assert.equal(definition.outputs.source_path.value, '${{ inputs.source_path }}');
  assert.equal(definition.outputs.blueprint_path.value, '${{ inputs.blueprint_path }}');
  const source = definition.runs.steps.find(step => step.name === 'Checkout Source Code');
  const pat = definition.runs.steps.find(step => step.name === 'Checkout Source Code w/PAT');
  const blueprint = definition.runs.steps.find(step => step.name === 'Checkout Blueprint');
  const module = definition.runs.steps.find(step => step.name === 'Check Source Module version');
  for (const step of [source, pat]) {
    assert.equal(step.uses, 'actions/checkout@v6');
    assert.equal(step.with.ref, '${{ inputs.source_ref }}');
    assert.equal(step.with.path, '${{ inputs.source_path }}');
    assert.equal(step.with['fetch-depth'], 0);
    assert.equal(step.with['fetch-tags'], true);
    assert.equal(step.with['persist-credentials'], '${{ inputs.persist_credentials }}');
    assert.ok(step.if.includes("inputs.checkout_source == 'true'"));
  }
  assert.equal(source.if, "${{ inputs.checkout_source == 'true' && inputs.token == '' }}");
  assert.equal(pat.if, "${{ inputs.checkout_source == 'true' && inputs.token != '' }}");
  assert.equal(pat.with.token, '${{ inputs.token }}');
  assert.equal(blueprint.uses, 'actions/checkout@v6');
  assert.equal(blueprint.with.repository, 'cloudopsworks/blueprints');
  assert.equal(blueprint.with.ref, '${{ inputs.blueprint_ref }}');
  assert.equal(blueprint.with.path, '${{ inputs.blueprint_path }}');
  assert.equal(blueprint.with['fetch-depth'], 1);
  assert.equal(blueprint.with['persist-credentials'], '${{ inputs.persist_credentials }}');
  assert.equal(module.if, "${{ inputs.check_module_version == 'true' }}");
  assert.equal(module.uses, './bp/cd/checkout/check-module-version');
});
