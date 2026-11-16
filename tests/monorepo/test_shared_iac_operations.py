"""Actual legacy Terragrunt steps, without a hosted source-code transport.

Only a recording local executable runs: no provider, backend or workload mutation.
Python is local test infrastructure, never a dependency of the production actions.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_legacy_action_contracts import ROOT, read_yaml, step_by_name


CLOUDS = ('aws', 'gcp')
STEP_NAMES = ('Terragrunt Plan', 'Terragrunt Plan to JSON', 'Terragrunt Apply')
SELECTOR_RUNNER = r"""
const fs = require('node:fs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const outputs = {};
const core = {setOutput: (key, value) => outputs[key] = value};
const quiet = {log: () => {}};
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
(async () => {
  await new AsyncFunction('core', 'console', input.script)(core, quiet);
  process.stdout.write(JSON.stringify(outputs));
})().catch(() => { process.exitCode = 1; });
"""


class SharedOperationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.record = self.root / 'record'
        binary = self.root / 'terragrunt'
        binary.write_text(
            '#!' + sys.executable + '\n'
            'import json,os,sys\n'
            'keys=("TG_TF_PATH","AWS_ACCESS_KEY_ID","AWS_SECRET_ACCESS_KEY",'
            '"GOOGLE_CREDENTIALS","HELM_CREDS_USER","HELM_CREDS_PASSWORD",'
            '"HELM_EXPERIMENTAL_OCI","GITHUB_API_TOKEN")\n'
            'with open(os.environ["RECORD"],"a") as f:\n'
            ' f.write(json.dumps({"argv":sys.argv[1:],"cwd":os.getcwd(),'
            '"env":{k:os.environ[k] for k in keys if k in os.environ}})+"\\n")\n'
            'print(json.dumps({"format_version":"1.2","mock":True}))\n'
            'raise SystemExit(int(os.environ.get("TOOL_EXIT","0")))\n')
        binary.chmod(0o700)

    def action(self, cloud):
        return read_yaml(ROOT / f'cd/deploy/app/{cloud}/action.yml')

    def selector(self, cloud, *, destroy='false', unlock='false', lock=''):
        step = step_by_name(self.action(cloud), 'Determine Plan Action')
        result = subprocess.run(
            ['node', '-e', SELECTOR_RUNNER],
            input=json.dumps({'script': step['with']['script']}),
            env={'PATH': os.environ['PATH'], 'INPUTS_DESTROY': destroy,
                 'INPUTS_UNLOCK': unlock, 'INPUTS_LOCK_ID': lock},
            text=True, capture_output=True, timeout=10, check=True)
        return json.loads(result.stdout)['value']

    def run_step(self, cloud, name, *, selector='', tool_exit=0):
        step = step_by_name(self.action(cloud), name)
        # Emulate runner expression resolution with unmistakably fake values.
        environment = {
            key: ('tofu' if key == 'TG_TF_PATH' else
                  '1' if key == 'HELM_EXPERIMENTAL_OCI' else f'fake-{key}')
            for key in step.get('env', {})
        }
        environment.update({
            'PATH': str(self.root) + os.pathsep + os.environ['PATH'],
            'RECORD': str(self.record),
            'TOOL_EXIT': str(tool_exit),
            'STEPS_PLAN_ACTION_VALUE': selector,
        })
        return subprocess.run(
            ['bash', '--noprofile', '--norc', '-e', '-o', 'pipefail', '-c', step['run']],
            cwd=self.root, env=environment, text=True, capture_output=True, timeout=10)

    def calls(self):
        return [json.loads(line) for line in self.record.read_text().splitlines()]

    def test_actual_selectors_keep_apply_destroy_unlock_and_destroy_precedence(self):
        cases = (
            ({}, ['plan', '-no-color', '-input=false']),
            ({'destroy': 'true'}, ['plan', '-destroy', '-no-color', '-input=false']),
            ({'unlock': 'true', 'lock': 'exact-native-lock'},
             ['force-unlock', '-force', 'exact-native-lock']),
            ({'destroy': 'true', 'unlock': 'true', 'lock': 'ignored'},
             ['plan', '-destroy', '-no-color', '-input=false']),
            ({'destroy': 'TRUE'}, ['plan', '-destroy', '-no-color', '-input=false']),
        )
        for cloud in CLOUDS:
            for inputs, arguments in cases:
                with self.subTest(cloud=cloud, inputs=inputs):
                    selected = self.selector(cloud, **inputs)
                    result = self.run_step(cloud, 'Terragrunt Plan', selector=selected)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(self.calls()[-1]['argv'],
                                     ['--non-interactive', 'run', '--', *arguments])
                    self.assertEqual(self.calls()[-1]['cwd'], str(self.root))

    def test_actual_show_json_and_apply_use_the_existing_saved_plan(self):
        for cloud in CLOUDS:
            for name, arguments in (
                    ('Terragrunt Plan to JSON', ['show', '-json', 'plan.tfplan']),
                    ('Terragrunt Apply', ['apply', '-no-color', 'plan.tfplan'])):
                with self.subTest(cloud=cloud, step=name):
                    result = self.run_step(cloud, name)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(self.calls()[-1]['argv'],
                                     ['--non-interactive', 'run', '--', *arguments])
                    self.assertEqual(self.calls()[-1]['cwd'], str(self.root))
            self.assertEqual(json.loads((self.root / 'tfplan.json').read_text()),
                             {'format_version': '1.2', 'mock': True})

    def test_native_steps_preserve_credentials_and_tool_environment(self):
        for cloud in CLOUDS:
            for name in STEP_NAMES:
                with self.subTest(cloud=cloud, step=name):
                    step = step_by_name(self.action(cloud), name)
                    expected = {'TG_TF_PATH': 'tofu', 'GITHUB_API_TOKEN': '${{ inputs.token }}'}
                    if cloud == 'aws':
                        expected.update({
                            'AWS_ACCESS_KEY_ID': '${{ inputs.aws_access_key_id }}',
                            'AWS_SECRET_ACCESS_KEY': '${{ inputs.aws_secret_access_key }}',
                        })
                    else:
                        expected['GOOGLE_CREDENTIALS'] = '${{ inputs.gcp_credentials }}'
                    if name != 'Terragrunt Plan to JSON':
                        expected.update({
                            'HELM_CREDS_USER': '${{ inputs.aws_access_key_id }}' if cloud == 'aws' else '_json_key',
                            'HELM_CREDS_PASSWORD': '${{ inputs.aws_secret_access_key }}' if cloud == 'aws' else '${{ inputs.gcp_credentials }}',
                            'HELM_EXPERIMENTAL_OCI': '1',
                        })
                    actual = dict(step['env'])
                    actual.pop('STEPS_PLAN_ACTION_VALUE', None)
                    actual.pop('CLOUDOPSWORKS_IAC_OPERATIONS', None)
                    self.assertEqual(actual, expected)
                    selected = self.selector(cloud)
                    result = self.run_step(cloud, name, selector=selected)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(self.calls()[-1]['env'], {
                        key: ('tofu' if key == 'TG_TF_PATH' else
                              '1' if key == 'HELM_EXPERIMENTAL_OCI' else f'fake-{key}')
                        for key in expected
                    })

    def test_working_directory_guards_and_failure_policy_are_unchanged(self):
        for cloud in CLOUDS:
            for name in STEP_NAMES:
                with self.subTest(cloud=cloud, step=name):
                    step = step_by_name(self.action(cloud), name)
                    self.assertEqual(step['working-directory'],
                                     '${{ inputs.blueprint_path }}/terraform/' + cloud + '/${{ inputs.cloud_type }}')
                    self.assertEqual(step['shell'], 'bash')
                    expected = {
                        'Terragrunt Plan': '${{ ! cancelled() }}',
                        'Terragrunt Plan to JSON': "${{ inputs.unlock != 'true' && steps.plan.outcome == 'success' }}",
                        'Terragrunt Apply': "${{ inputs.unlock != 'true' && ! cancelled() && steps.plan.outcome == 'success' }}",
                    }
                    self.assertEqual(step['if'], expected[name])
                    self.assertFalse(step.get('continue-on-error', False))
                    if name == 'Terragrunt Plan':
                        self.assertEqual(step['id'], 'plan')
                        self.assertEqual(step['env']['STEPS_PLAN_ACTION_VALUE'],
                                         '${{ steps.plan_action.outputs.value }}')
                    elif name == 'Terragrunt Apply':
                        self.assertEqual(step['id'], 'apply')

    def test_native_failure_propagates_without_success_group_tail(self):
        for cloud in CLOUDS:
            for name in STEP_NAMES:
                with self.subTest(cloud=cloud, step=name):
                    result = self.run_step(cloud, name, selector=self.selector(cloud), tool_exit=7)
                    self.assertEqual(result.returncode, 7, result.stderr)
                    self.assertNotIn('::endgroup::', result.stdout)

    def test_unlock_shell_syntax_is_not_evaluated_as_code(self):
        for cloud in CLOUDS:
            with self.subTest(cloud=cloud):
                hostile = 'native-lock;touch SHELL_INJECTED;$(touch SUBSTITUTED)'
                selected = self.selector(cloud, unlock='true', lock=hostile)
                result = self.run_step(cloud, 'Terragrunt Plan', selector=selected)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.calls()[-1]['argv'], [
                    '--non-interactive', 'run', '--', 'force-unlock', '-force',
                    'native-lock;touch', 'SHELL_INJECTED;$(touch', 'SUBSTITUTED)',
                ])
                self.assertFalse((self.root / 'SHELL_INJECTED').exists())
                self.assertFalse((self.root / 'SUBSTITUTED').exists())

    def test_legacy_steps_have_no_rejected_transport_dependency(self):
        for cloud in CLOUDS:
            for name in STEP_NAMES:
                with self.subTest(cloud=cloud, step=name):
                    step = step_by_name(self.action(cloud), name)
                    self.assertNotIn('CLOUDOPSWORKS_IAC_OPERATIONS', step.get('env', {}))
                    self.assertNotIn('python', step['run'])
                    self.assertIn('terragrunt --non-interactive run -- ', step['run'])


if __name__ == '__main__':
    unittest.main()
