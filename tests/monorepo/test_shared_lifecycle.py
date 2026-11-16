"""Execute the actual legacy parent/shared classifier through the sole Go CLI."""
import json
import os
from pathlib import Path
import subprocess
import unittest

from test_legacy_action_contracts import classify_legacy,deployment_config,read_yaml,step_by_id

ROOT=Path(__file__).resolve().parents[2]
SUPPORT = (ROOT/'tests/monorepo/actions/action_test_support.mjs').as_uri()
INLINE_RUNNER = f"""
import {{readFileSync}} from 'node:fs';
import {{runStep}} from {json.dumps(SUPPORT)};
const options = JSON.parse(readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(runStep('ci/config/lifecycle/action.yml', 'classify', options)));
"""


class SharedLifecycleTests(unittest.TestCase):
    def inline(self, environment, *, tools=None):
        options = {'env': environment}
        if tools is None:
            binary=os.environ.get('TRONADOR_TEST_BINARY')
            self.assertTrue(binary and Path(binary).is_file(),'Exact source-built CLI required for local proof')
            options['realCli'] = binary
        else:
            options['tools'] = tools
        completed = subprocess.run(['node', '--input-type=module', '-e', INLINE_RUNNER],
            input=json.dumps(options), text=True, capture_output=True, timeout=30, check=True)
        return json.loads(completed.stdout)

    def test_actual_parent_dispatch_bootstrap_and_removed_duplicate_body(self):
        parent=read_yaml(ROOT/'ci/config/action.yml');workspace=step_by_id(parent,'workspace')
        self.assertEqual(workspace['uses'],'cloudopsworks/blueprints/ci/config/lifecycle@v5.11.0')
        self.assertEqual(workspace['with']['mode'],'legacy')
        self.assertNotIn('script',workspace.get('with',{}))
        shared=read_yaml(ROOT/'ci/config/lifecycle/action.yml')
        self.assertEqual(shared['runs']['steps'][0]['uses'],'cloudopsworks/install-tronador-cli@v1')
        self.assertEqual(shared['runs']['steps'][0]['with']['version'],'v0.6.0')
        self.assertEqual(set(shared['outputs']),{'lifecycle','workspace','workspace_upper','isEnabled','isRelease','isPreRelease','hasQualifier','targetName','deploymentName','protectedEnvironment'})

    def test_extracted_legacy_operation_matches_frozen_javascript(self):
        for ref,base in [('develop',''),('release/1.2',''),('v1.2.3',''),('v1.2.3-rc.1',''),('v1.2.3+deploy-blue',''),('support/1.0',''),('feature/test','develop'),('master','')]:
            for enabled in ('true',True,None):
                with self.subTest(ref=ref,enabled=enabled,base=base):
                    config=deployment_config();config['develop']['enabled']=enabled
                    frozen=classify_legacy(ref,base=base,config=config)
                    self.assertNotIn('error',frozen)
                    result=self.inline({'INPUT_MODE':'legacy','INPUT_DEPLOYMENTS':json.dumps(config),'HOST_EVENT':'push','HOST_REF':ref,'HOST_BASE_REF':base})
                    self.assertNotIn('error',result,result)
                    self.assertEqual([call['command'] for call in result['calls']], ['tronador'])
                    value=result['outputs']
                    for key in ('workspace','workspace_upper','isEnabled','isRelease','isPreRelease','targetName','hasQualifier','deploymentName'):
                        expected=frozen['outputs'][key];actual=value[key]
                        if isinstance(actual,bool):actual=str(actual).lower()
                        self.assertEqual(actual,expected)

    def test_bad_mode_unsupported_ref_and_failure_do_not_print_raw_data(self):
        invalid=self.inline({'INPUT_MODE':'arbitrary'},tools=[])
        self.assertEqual(invalid['error']['message'],'lifecycle-input')
        self.assertEqual(invalid['calls'],[])
        unsupported=self.inline({'INPUT_MODE':'legacy','HOST_EVENT':'push','HOST_REF':'feature/unsupported','INPUT_DEPLOYMENTS':json.dumps(deployment_config())})
        self.assertEqual(unsupported['error']['message'],'lifecycle-ineligible')
        self.assertEqual(unsupported['outputs'],{})
        failure=self.inline({'INPUT_MODE':'legacy','HOST_EVENT':'push'},tools=[{'result':{'exitCode':1,'stderr':'secret-sentinel'}}])
        self.assertEqual(failure['error']['message'],'lifecycle-classification')
        self.assertEqual(failure['outputs'],{})
        self.assertNotIn('secret-sentinel',json.dumps(failure))


if __name__=='__main__':unittest.main()
