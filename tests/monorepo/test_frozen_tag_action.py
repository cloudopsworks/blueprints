"""Actual frozen adapter command protocol; legacy body remains unchanged."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
PATH=ROOT/'cd/tasks/repo/push-tag/frozen.py'
spec=importlib.util.spec_from_file_location('frozen_tag_adapter',PATH)
adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)

class FrozenTagActionTests(unittest.TestCase):
    def environment(self,output):
        return {'EXPECTED_SHA':'a'*40,'EXPECTED_VERSION':'1.2.3','TRONADOR_VERSION':'v0.6.0',
            'GITHUB_TOKEN':'token-sentinel','INPUTS_BOT_USER':'automation','INPUTS_BOT_EMAIL':'bot@example.test','GITHUB_OUTPUT':str(output)}
    def test_partial_or_wrong_pin_denies_before_any_process(self):
        with tempfile.TemporaryDirectory() as directory:
            good=self.environment(Path(directory)/'out')
            for delta in ({'EXPECTED_SHA':''},{'EXPECTED_VERSION':''},{'EXPECTED_SHA':'bad'},
                    {'EXPECTED_VERSION':'1.2.3\nEVIL=yes'},{'TRONADOR_VERSION':'latest'}):
                with self.subTest(delta=delta),patch.object(adapter.subprocess,'run') as run,self.assertRaises(ValueError):
                    adapter.tag({**good,**delta})
                run.assert_not_called()
        self.assertIsNone(adapter.validate({}))
    def test_actual_adapter_uses_only_frozen_cli_and_closed_readback(self):
        calls=[]
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'out';env=self.environment(output)
            record={'tag':'v1.2.3','version':'1.2.3','sha':'a'*40}
            def process(argv,**kwargs):
                calls.append(argv)
                if argv[0]=='tronador':
                    self.assertEqual(kwargs['env']['GIT_CONFIG_COUNT'],'1')
                    self.assertNotIn('token-sentinel',str(argv))
                return subprocess.CompletedProcess(argv,0,json.dumps(record) if argv[0]=='tronador' else '', '')
            with patch.object(adapter.subprocess,'run',side_effect=process):
                self.assertEqual(adapter.tag(env),record)
            self.assertEqual(calls[-1],['tronador','versions','tag','--expected-sha','a'*40,
                '--expected-version','1.2.3','--publish','--allow-network','--json'])
            self.assertTrue(all(argv[:3]==['git','config','--local'] for argv in calls[:-1]))
            self.assertEqual(output.read_text(),'tag=v1.2.3\nversion=1.2.3\nsha='+'a'*40+'\n')
            record['sha']='b'*40
            output.unlink()
            with patch.object(adapter.subprocess,'run',side_effect=process),self.assertRaises(ValueError):adapter.tag(env)
            self.assertFalse(output.exists())
    def test_legacy_sync_retry_body_and_default_installer_preserved(self):
        source=PATH.with_name('action.yml').read_text()
        legacy=source.split('    - name: Push TAG\n',1)[1]
        self.assertIn("if: inputs.expected_sha == '' && inputs.expected_version == ''",legacy)
        self.assertEqual(legacy.count('git pull --rebase'),2)
        self.assertIn('count=3',legacy);self.assertIn('sleep 10',legacy)
        installer=source.split('    - name: Install Tronador CLI\n',1)[1].split('    - name: Push TAG',1)[0]
        self.assertNotIn('version:',installer)
        self.assertIn('version: ${{ inputs.tronador_version }}',source)
        self.assertLess(source.index('frozen.py" validate'),source.index('Install frozen compatible'))

if __name__=='__main__':unittest.main()
