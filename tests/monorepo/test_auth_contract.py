"""Actual sole-Go protected YAML bridge; no OIDC or cloud mutation executed."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_legacy_action_contracts import ROOT,read_yaml


class AuthContractTests(unittest.TestCase):
    def test_source_yaml_is_normalized_by_exact_cli_before_fixed_auth_actions(self):
        action=read_yaml(ROOT/'cd/monorepo/auth/action.yml')
        self.assertEqual(action['runs']['steps'][0]['with']['version'],'v0.6.0')
        step=next(s for s in action['runs']['steps'] if s.get('id')=='binding')
        binary=os.environ.get('TRONADOR_TEST_BINARY');self.assertTrue(binary and Path(binary).is_file())
        with tempfile.TemporaryDirectory() as directory:
            work=Path(directory);(work/'tronador').symlink_to(binary);out=work/'outputs'
            env={**os.environ,'PATH':str(work)+os.pathsep+os.environ['PATH'],'PROVIDER':'aws','AUTH_REF':'aws-dev','GITHUB_OUTPUT':str(out),
                 'BINDINGS':'aws-dev:\n  provider: aws\n  roleArn: arn:aws:iam::123456789012:role/Deploy\n  region: us-east-1\n'}
            completed=subprocess.run(['bash','-e','-c',step['run']],env=env,capture_output=True,text=True)
            self.assertEqual(completed.returncode,0,completed.stderr)
            self.assertEqual(completed.stdout,'')
            self.assertEqual(out.read_text(),'roleArn=arn:aws:iam::123456789012:role/Deploy\nregion=us-east-1\n')
            out.unlink();env['BINDINGS']+='  unknownCredential: sentinel-private-value\n'
            failed=subprocess.run(['bash','-e','-c',step['run']],env=env,capture_output=True,text=True)
            self.assertNotEqual(failed.returncode,0)
            self.assertNotIn('sentinel',failed.stdout+failed.stderr)
            self.assertFalse(out.exists())


if __name__=='__main__':unittest.main()
