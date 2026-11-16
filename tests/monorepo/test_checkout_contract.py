"""Additive checkout safety; defaults remain the characterized legacy behavior."""
import os
import subprocess
import unittest
from test_legacy_action_contracts import ROOT, read_yaml, step_by_name


class CheckoutContractTests(unittest.TestCase):
    def setUp(self):self.action=read_yaml(ROOT/'cd/checkout/action.yml')
    def test_legacy_defaults_and_data_only_guards(self):
        inputs=self.action['inputs']
        for name in ('checkout_source','persist_credentials','check_module_version'):
            self.assertEqual(inputs[name]['default'],'true')
        for name,token in (('Checkout Source Code',"''"),('Checkout Source Code w/PAT',"''")):
            step=step_by_name(self.action,name)
            self.assertIn("inputs.checkout_source == 'true'",step['if'])
            self.assertEqual(step['with']['persist-credentials'],'${{ inputs.persist_credentials }}')
        self.assertEqual(step_by_name(self.action,'Check Source Module version')['if'],"${{ inputs.check_module_version == 'true' }}")
        self.assertEqual(step_by_name(self.action,'Checkout Blueprint')['with']['path'],'${{ inputs.blueprint_path }}')
        self.assertEqual(inputs['blueprint_ref']['default'],'v5.10')
    def test_actual_mode_script_rejects_ambiguous_or_source_lookup_without_source(self):
        script=step_by_name(self.action,'Validate checkout mode')['run']
        for flags,expected in ((('true','true','true'),0),(('false','false','false'),0),(('false','false','true'),1),(('false;echo bad','false','false'),1)):
            env=dict(zip(('CHECKOUT_SOURCE','PERSIST_CREDENTIALS','CHECK_MODULE_VERSION'),flags))
            result=subprocess.run(['bash','-c',script],env={**os.environ,'SOURCE_PATH':'source','BLUEPRINT_PATH':'bp',**env},capture_output=True,text=True)
            self.assertEqual(result.returncode,expected)
            self.assertNotIn('bad\n',result.stdout)
    def test_root_reserved_blueprint_and_destination_overlap_are_checked(self):
        self.assertEqual(self.action['inputs']['source_path']['default'],'source')
        self.assertEqual(self.action['inputs']['blueprint_path']['default'],'bp')
        script=step_by_name(self.action,'Validate checkout mode')['run']
        for source,blueprint,ok in [('.', 'bp',True),('source','bp',True),('source','source/bp',False),('bp/source','bp',False),('../escape','bp',False),('.', '.blueprints',False),('.git','bp',False),('source','/bp',False)]:
            with self.subTest(source=source,blueprint=blueprint):
                env={**os.environ,'SOURCE_PATH':source,'BLUEPRINT_PATH':blueprint,'CHECKOUT_SOURCE':'true','PERSIST_CREDENTIALS':'false','CHECK_MODULE_VERSION':'false'}
                result=subprocess.run(['bash','-c',script],env=env,capture_output=True,text=True)
                self.assertEqual(result.returncode==0,ok)

    def test_data_only_central_helpers_request_all_safe_flags(self):
        for name in ('checkpr','process-owners','slash-command','approval','retry'):
            text=(ROOT/'.github/workflows'/('monorepo-'+name+'.yml')).read_text()
            for key in ('checkout_source','persist_credentials','check_module_version'):
                self.assertIn(key+": 'false'",text)


if __name__=='__main__':unittest.main()
