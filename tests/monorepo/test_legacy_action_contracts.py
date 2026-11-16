"""Pre-v5.11 compatibility characterization, not new monorepo behavior.

The frozen JavaScript fixtures execute the actual old action bodies with bounded,
offline GitHub doubles. They document quirks that the Go legacy classifier must
preserve. YAML checks cover observable action defaults and reference triggers;
they do not emulate GitHub Actions or prove provider/cloud execution.
"""

from functools import lru_cache
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).with_name('fixtures') / 'legacy_actions'
REFERENCES = tuple(f'{language}-app-template' for language in (
    'dotnet', 'go', 'java', 'node', 'python', 'rust'))
NODE = shutil.which('node')
YQ = shutil.which('yq')


@lru_cache(maxsize=None)
def read_yaml(path):
    return json.loads(subprocess.check_output(
        [YQ, '-o=json', '-I=0', '.', str(path)], timeout=10))


def step_by_id(action, identifier):
    return next(step for step in action['runs']['steps']
                if step.get('id') == identifier)


def step_by_name(action, name):
    return next(step for step in action['runs']['steps']
                if step.get('name') == name)


def reference_workflow(repository, filename):
    """Frozen historical semantics: no sibling checkout is required to run tests."""
    snapshot = read_yaml(FIXTURES / 'reference-workflows.yaml')[repository]
    return snapshot['workflows'][filename]['contract']


NODE_HARNESS = r"""
const fs = require('fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const outputs = {}, failures = [], calls = [];
const core = {
  setOutput: (key, value) => outputs[key] = value == null ? '' :
    (typeof value === 'string' ? value : JSON.stringify(value)),
  setFailed: message => failures.push(message)
};
const github = {
  graphql: async (query, args) => {
    calls.push({kind: 'graphql', query, args});
    if (query.includes('teams(first:'))
      return {organization: {teams: {nodes: []}}};
    if (query.includes('membersWithRole(first:'))
      return {organization: {membersWithRole: {nodes:
        [{login: 'alice', id: 'user-alice'}]}}};
    if (query.includes('environments(first:'))
      return {repository: {id: 'repo-id', environments: {nodes: []}}};
    if (query.includes('createEnvironment(input:'))
      return {createEnvironment: {environment: {id: 'env:' + args.env}}};
    if (query.includes('updateEnvironment(input:')) return {};
    throw new Error('Unexpected GraphQL operation');
  },
  request: async (route, args) => {
    calls.push({kind: 'request', route, args});
    if (route.startsWith('GET '))
      return {status: 200, data: {total_count: 0, variables: []}};
    if (route.startsWith('POST ')) return {status: 201};
    throw new Error('Unexpected REST operation');
  }
};
const quietConsole = {log: () => {}, debug: () => {}};
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
(async () => {
  try {
    const fn = new AsyncFunction('core', 'github', 'context', 'console', input.script);
    const result = await fn(core, github,
      {repo: {owner: 'example', repo: 'app'}}, quietConsole);
    process.stdout.write(JSON.stringify({outputs, failures, calls, result}));
  } catch (error) {
    process.stdout.write(JSON.stringify({outputs, failures, calls,
      error: {name: error.name, message: error.message}}));
  }
})();
"""


def execute_legacy(script_name, environment):
    """Execute only a checked-in fixture, without inherited auth/config variables."""
    environment = {'PATH': os.environ.get('PATH', ''), **environment}
    result = subprocess.run(
        [NODE, '-e', NODE_HARNESS],
        input=json.dumps({'script': (FIXTURES / script_name).read_text()}),
        text=True, capture_output=True, timeout=10, env=environment, check=True)
    if len(result.stdout) > 128 * 1024:
        raise AssertionError('Legacy fixture output exceeded its bounded protocol')
    return json.loads(result.stdout)


def deployment_config():
    return {
        'develop': {'env': 'dev', 'targetName': 'dev-name'},
        'test': {'env': 'uat', 'targetName': 'test-name'},
        'prerelease': {'env': 'demo', 'targetName': 'demo-name',
                       'targets': {'blue': {'env': 'blue-demo'}}},
        'release': {'env': 'prod', 'targetName': 'prod-name',
                    'targets': {'blue': {'env': 'blue-prod'}}},
        'support': [{'match': r'1\.2', 'env': 'support-first',
                     'targetName': 'first', 'enabled': False},
                    {'match': '.*', 'env': 'support-fallback'}],
    }


def classify_legacy(ref='develop', *, config=None, base='', head=''):
    return execute_legacy('workspace.js', {
        'STEPS_DEPLOY_CONF_RESULT': json.dumps(
            deployment_config() if config is None else config),
        'GITHUB_REF_NAME': ref, 'GITHUB_BASE_REF': base,
        'GITHUB_HEAD_REF': head,
    })


@unittest.skipUnless(NODE, 'Node is required to execute frozen legacy JavaScript')
class LegacyClassifierCharacterization(unittest.TestCase):
    def test_familiar_reference_classes_keep_their_existing_names(self):
        for ref, env, name, release, pre in (
                ('develop', 'dev', 'develop/dev', False, False),
                ('release/1.2', 'uat', 'test/uat', False, True),
                ('v1.2.3', 'prod', 'release/prod', True, False),
                ('v1.2.3-rc.1', 'demo', 'prerelease/demo', True, True),
                ('master', 'prod', 'release/prod', True, False),
                ('main', 'prod', 'release/prod', True, False)):
            with self.subTest(ref=ref):
                result = classify_legacy(ref)
                self.assertNotIn('error', result)
                self.assertEqual(result['failures'], [])
                value = result['result']
                self.assertEqual((value['environment'], value['deploymentName'],
                                  value['isRelease'], value['isPreRelease']),
                                 (env, name, release, pre))

    def test_string_true_and_boolean_true_have_different_legacy_meanings(self):
        for branch, key in (('develop', 'develop'), ('release/1.2', 'test'),
                            ('v1.2.3-rc.1', 'prerelease')):
            for enabled, expected in (('true', True), (True, False),
                                      ('false', False), (False, False),
                                      (None, True)):
                with self.subTest(branch=branch, enabled=enabled):
                    config = deployment_config()
                    config[key]['enabled'] = enabled
                    result = classify_legacy(branch, config=config)
                    self.assertEqual(result['result']['isEnabled'], expected)
                    self.assertEqual(result['outputs']['isEnabled'],
                                     str(expected).lower())

    def test_release_enabled_flag_is_ignored_by_the_legacy_classifier(self):
        config = deployment_config()
        config['release']['enabled'] = False
        for ref in ('v1.2.3', 'master', 'v1.2.3+deploy-blue'):
            with self.subTest(ref=ref):
                self.assertTrue(classify_legacy(ref, config=config)
                                ['result']['isEnabled'])

    def test_support_uses_first_regex_match_but_omits_deployment_name(self):
        result = classify_legacy('support/1.2-suffix')['result']
        self.assertEqual(result['environment'], 'support-first')
        self.assertEqual(result['targetName'], 'first')
        self.assertEqual(result['deploymentName'], '')
        self.assertTrue(result['isEnabled'])  # disabled support match is ignored

    def test_missing_support_match_or_mapping_throws_instead_of_defaulting(self):
        config = deployment_config()
        config['support'] = []
        self.assertEqual(classify_legacy('support/9', config=config)
                         ['error']['name'], 'TypeError')
        del config['support']
        self.assertEqual(classify_legacy('support/9', config=config)
                         ['error']['name'], 'TypeError')

    def test_invalid_support_regex_throws_before_later_matches(self):
        config = deployment_config()
        config['support'][0]['match'] = '['
        self.assertEqual(classify_legacy('support/9', config=config)
                         ['error']['name'], 'SyntaxError')

    def test_pr_base_takes_precedence_over_head_and_ref(self):
        result = classify_legacy('feature/ref', base='develop', head='feature/pr')
        self.assertEqual(result['result']['environment'], 'dev')
        self.assertEqual(result['outputs']['workspace_upper'], 'DEV')

    def test_missing_develop_mapping_throws_and_does_not_select_production(self):
        config = deployment_config()
        del config['develop']
        result = classify_legacy(config=config)
        self.assertEqual(result['error']['name'], 'TypeError')
        self.assertEqual(result['outputs'], {})

    def test_unsupported_branch_sets_failure_with_empty_environment(self):
        result = classify_legacy('feature/example')
        self.assertEqual(result['failures'], ['Branch not supported'])
        self.assertEqual(result['result']['environment'], '')
        self.assertFalse(result['result']['isRelease'])

    def test_qualifiers_preserve_existing_names_and_prerelease_flag_quirk(self):
        for ref, environment, name, release, pre in (
                ('v1.2.3+deploy-blue', 'blue-prod', 'release/blue/blue-prod', True, False),
                ('v1.2.3-rc.1+deploy-blue', 'blue-demo',
                 'prerelease/blue/blue-demo', False, True)):
            with self.subTest(ref=ref):
                value = classify_legacy(ref)['result']
                self.assertEqual((value['environment'], value['deploymentName'],
                                  value['isRelease'], value['isPreRelease'],
                                  value['hasQualifier']),
                                 (environment, name, release, pre, True))

    def test_legacy_semver_match_is_not_end_anchored(self):
        self.assertEqual(classify_legacy('v1.2.3trailing')['result']
                         ['deploymentName'], 'release/prod')

    def test_unknown_or_non_deploy_metadata_throws_in_legacy_mode(self):
        for ref in ('v1.2.3+deploy-unknown', 'v1.2.3+other'):
            with self.subTest(ref=ref):
                self.assertEqual(classify_legacy(ref)['error']['name'], 'TypeError')


@unittest.skipUnless(NODE, 'Node is required for legacy operation/owners fixtures')
class LegacyOperationalCharacterization(unittest.TestCase):
    def test_operation_selector_defaults_precedence_and_case_normalization(self):
        for destroy, unlock, expected in (
                ('', '', 'plan -no-color -input=false'),
                ('true', '', 'plan -destroy -no-color -input=false'),
                ('true', 'true', 'plan -destroy -no-color -input=false'),
                ('TRUE', 'true', 'plan -destroy -no-color -input=false'),
                ('', 'TRUE', 'force-unlock -force lock-123')):
            with self.subTest(destroy=destroy, unlock=unlock):
                result = execute_legacy('plan-action.js', {
                    'INPUTS_DESTROY': destroy, 'INPUTS_UNLOCK': unlock,
                    'INPUTS_LOCK_ID': 'lock-123'})
                self.assertEqual(result['outputs']['value'], expected)

    def test_owners_records_real_environment_policy_calls_and_skips_support(self):
        config = deployment_config()
        config['release']['variables'] = {'DEPLOY_COLOR': 'green'}
        result = execute_legacy('owners-envs.js', {
            'STEPS_DEPLOYMENTS_JSON_RESULT': json.dumps(config),
            'STEPS_REVIEWERS_LIST_RESULT': '["alice"]',
            'INPUTS_SOURCE_PATH': 'source'})
        self.assertNotIn('error', result)
        environments = json.loads(result['outputs']['env_list'])
        self.assertEqual(environments, sorted([
            'develop/dev', 'test/uat', 'prerelease/demo',
            'prerelease/blue/blue-demo', 'release/prod',
            'release/blue/blue-prod']))
        updates = [call['args'] for call in result['calls']
                   if call['kind'] == 'graphql'
                   and 'updateEnvironment(input:' in call['query']]
        release = next(item for item in updates
                       if item['environment_id'] == 'env:release/prod')
        develop = next(item for item in updates
                       if item['environment_id'] == 'env:develop/dev')
        self.assertEqual(release['reviewers'], ['user-alice'])
        self.assertTrue(release['no_self_review'])
        self.assertEqual(develop['reviewers'], [])
        self.assertFalse(develop['no_self_review'])
        variable_posts = [call for call in result['calls']
                          if call['kind'] == 'request'
                          and call['route'].startswith('POST ')]
        self.assertEqual({item['args']['environment_name']
                          for item in variable_posts},
                         {'release/prod', 'release/blue/blue-prod'})


@unittest.skipUnless(YQ, 'Existing yq CLI is required to parse action/workflow YAML')
class LegacyYamlContracts(unittest.TestCase):
    def test_executed_operational_fixtures_match_existing_action_bodies(self):
        for filename, action_path, identifier in (
                ('plan-action.js', 'cd/deploy/app/aws/action.yml', 'plan_action'),
                ('owners-envs.js', 'cd/tasks/repo/owners/envs/action.yml', 'envs')):
            with self.subTest(fixture=filename):
                frozen = (FIXTURES / filename).read_text().split('\n', 1)[1]
                actual = step_by_id(read_yaml(ROOT / action_path), identifier)
                self.assertEqual(frozen.strip(), actual['with']['script'].strip())

    def test_original_action_input_defaults_remain_compatible(self):
        expected = read_yaml(FIXTURES / 'action-defaults.yaml')
        for action_path, contract in expected.items():
            action = read_yaml(ROOT / action_path)
            for name, fields in contract['inputs'].items():
                with self.subTest(action=action_path, input=name):
                    for field, value in fields.items():
                        self.assertEqual(action['inputs'][name].get(field), value)

    def test_checkout_default_paths_and_local_module_lookup_are_real(self):
        action = read_yaml(ROOT / 'cd/checkout/action.yml')
        # Additive data-only component mode may select a checked destination;
        # legacy callers still resolve to the exact characterized paths.
        for key, expected in (('source_path', 'source'), ('blueprint_path', 'bp')):
            self.assertEqual(action['outputs'][key]['value'], '${{ inputs.' + key + ' }}')
            self.assertEqual(action['inputs'][key]['default'], expected)
        for name in ('Checkout Source Code', 'Checkout Source Code w/PAT'):
            step = step_by_name(action, name)
            self.assertEqual(step['with']['path'], '${{ inputs.source_path }}')
            self.assertEqual(action['inputs']['source_path']['default'], 'source')
            self.assertEqual(step['with']['fetch-depth'], 0)
            self.assertTrue(step['with']['fetch-tags'])
        module = step_by_name(action, 'Check Source Module version')
        self.assertEqual(module['uses'], './bp/cd/checkout/check-module-version')
        self.assertTrue((ROOT / 'cd/checkout/check-module-version/action.yml').is_file())

    def test_tag_ordinary_installer_and_retry_behavior_are_characterized(self):
        action = read_yaml(ROOT / 'cd/tasks/repo/push-tag/action.yml')
        install = step_by_name(action, 'Install Tronador CLI')
        self.assertEqual(install['uses'], 'cloudopsworks/install-tronador-cli@v1')
        self.assertNotIn('version', install['with'])
        script = step_by_name(action, 'Push TAG')['run']
        self.assertIn('git pull --rebase', script)
        self.assertIn('count=3', script)
        self.assertIn('tronador versions tag --publish --allow-network', script)

    def test_owners_helper_refs_remain_explicit_not_missing_local_actions(self):
        action = read_yaml(ROOT / 'cd/tasks/repo/owners/action.yml')
        helpers = [step['uses'] for step in action['runs']['steps']
                   if step.get('uses', '').startswith('cloudopsworks/blueprints/')]
        self.assertEqual(helpers, [
            f'cloudopsworks/blueprints/cd/tasks/repo/owners/{suffix}@v5.10'
            for suffix in ('contributors', 'protect/gitflow', 'protect/commits',
                           'protect/sources', 'envs')])

    def test_legacy_apps_select_same_operations_and_guard_saved_plan_apply(self):
        scripts = []
        for provider in ('aws', 'gcp'):
            action = read_yaml(ROOT / f'cd/deploy/app/{provider}/action.yml')
            scripts.append(step_by_id(action, 'plan_action')['with']['script'])
            apply = step_by_name(action, 'Terragrunt Apply')
            self.assertIn("inputs.unlock != 'true'", apply['if'])
            self.assertIn('steps.plan.outcome', apply['if'])
            self.assertIn('apply -no-color plan.tfplan', apply['run'])
            # Selection lowercases TRUE; the guard compares the original input.
            self.assertNotIn('toLowerCase', apply['if'])
            root = (ROOT / f'terraform/{provider}/root.hcl').read_text()
            self.assertIn('-out=${get_terragrunt_dir()}/plan.tfplan', root)
        self.assertEqual(scripts[0], scripts[1])

    def test_legacy_api_runs_all_for_plan_apply_but_unlocks_one_directory(self):
        action = read_yaml(ROOT / 'cd/deploy/api/aws/action.yml')
        unlock = step_by_name(action, 'Terragrunt Unlock')
        self.assertEqual(unlock['if'], "${{ inputs.unlock == 'true' }}")
        self.assertIn('${{ inputs.api_lock }}', unlock['working-directory'])
        self.assertNotIn('run --all', unlock['run'])
        for name in ('Terragrunt Plan', 'Terragrunt Apply'):
            self.assertIn('run --all', step_by_name(action, name)['run'])

    def test_missing_legacy_preview_apply_unlock_guard_is_not_safe_reuse(self):
        # This documents a legacy defect; component-mode tests must demand a guard.
        for provider in ('aws', 'gcp', 'azure'):
            with self.subTest(provider=provider):
                action = read_yaml(ROOT / f'cd/deploy/preview/{provider}/action.yml')
                self.assertNotIn('if', step_by_name(action, 'Terragrunt Apply'))

    def test_all_six_main_and_pr_trigger_filters_match_familiar_semantics(self):
        for repository in REFERENCES:
            with self.subTest(repository=repository):
                main = reference_workflow(repository, 'main-build.yml')
                self.assertEqual(main['on'], {
                    'create': None,
                    'push': {
                        'tags': ['v[0-9]+.[0-9]+.[0-9]+',
                                 'v[0-9]+.[0-9]+.[0-9]+**'],
                        'branches': ['develop', 'support/**', 'release/**'],
                        'paths': ['**', '.cloudopsworks/vars/**',
                                  '.cloudopsworks/values/**', '!.github/**',
                                  '!.cloudopsworks/*']},
                    'workflow_dispatch': None})
                guard = main['jobs']['code-build']['if']
                self.assertIn("github.event_name == 'create'", guard)
                self.assertIn("'refs/heads/support/'", guard)
                self.assertIn("'refs/heads/release/'", guard)
                pr = reference_workflow(repository, 'pr-build.yml')
                self.assertEqual(pr['on'], {'pull_request': {
                    'types': ['opened', 'synchronize', 'edited'],
                    'branches': ['hotfix/**', 'feature/**', 'master',
                                 'release/**', 'support/**', 'develop']}})
                guard = pr['jobs']['code-build']['if']
                for prefix in ('release/', 'support/', 'master'):
                    self.assertRegex(guard, r'!\s*startsWith\(github.head_ref,\s*'
                                     + re.escape(repr(prefix)) + r'\)')

    def test_all_six_closure_owners_and_destructive_entrypoints_are_familiar(self):
        for repository in REFERENCES:
            with self.subTest(repository=repository):
                close = reference_workflow(repository, 'pr-close.yaml')
                self.assertEqual(close['on'], {'pull_request': {'types': ['closed']}})
                self.assertIn('branch_deletion', close['jobs'])
                owners = reference_workflow(repository, 'process-owners.yml')
                self.assertEqual(owners['on'], {
                    'push': {'branches': ['master', 'main', 'develop'],
                             'paths': ['OWNERS', '.cloudopsworks/cloudopsworks-ci.yaml',
                                       '.cloudopsworks/cloudopsworks-cd.yaml']},
                    'workflow_dispatch': None})
                destroy = reference_workflow(repository, 'environment-destroy.yml')
                unlock = reference_workflow(repository, 'environment-unlock.yml')
                self.assertEqual(set(destroy['on']), {'workflow_dispatch'})
                self.assertEqual(set(unlock['on']), {'workflow_dispatch'})
                destroy_inputs = destroy['on']['workflow_dispatch']['inputs']
                unlock_inputs = unlock['on']['workflow_dispatch']['inputs']
                self.assertEqual(destroy_inputs['target']['options'], ['app', 'api', 'BOTH'])
                self.assertEqual(destroy_inputs['target']['default'], 'BOTH')
                self.assertEqual(unlock_inputs['target']['options'], ['app', 'api'])
                self.assertTrue(unlock_inputs['lockId']['required'])


if __name__ == '__main__':
    unittest.main()
