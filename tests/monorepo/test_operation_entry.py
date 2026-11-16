"""Exact manual source selection uses the real Go/API authority boundary."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
import operation_entry
from contracts import ContractError
from test_normal_entry_integration import ConnectedAPI,ConnectedProcess

BINARY=os.environ.get('TRONADOR_TEST_BINARY')

class ManualProcess(ConnectedProcess):
    def run(self,argv,**kwargs):
        if argv==['git','rev-parse','HEAD']:
            return subprocess.CompletedProcess(argv,0,self.api.bp+'\n','')
        return super().run(argv,**kwargs)

@unittest.skipUnless(BINARY,'set TRONADOR_TEST_BINARY to the reviewed Go binary')
class OperationEntryTests(unittest.TestCase):
    def setUp(self):
        self.api=ConnectedAPI();self.api.manual=True
        self.api.host.update(event='workflow_dispatch',workflowRef=self.api.repository+'/.github/workflows/deploy.yml@refs/heads/develop')
        self.runner=ManualProcess(self.api)
        h=self.api.host
        self.environment={'GITHUB_REPOSITORY_ID':h['repository']['id'],'GITHUB_REPOSITORY':h['repository']['fullName'],
            'GITHUB_RUN_ID':h['runId'],'GITHUB_RUN_ATTEMPT':h['runAttempt'],'GITHUB_EVENT_NAME':h['event'],
            'GITHUB_REF':h['ref'],'GITHUB_SHA':h['headSha'],'GITHUB_WORKFLOW_REF':h['workflowRef'],
            'GITHUB_WORKFLOW_SHA':h['workflowSha'],'GITHUB_ACTOR':h['actor']}
    def test_exact_current_source_stage_and_current_completed_scans(self):
        prepared=operation_entry.prepare_apply(self.api,self.runner,self.environment,'develop/dev','dev-run','api')
        self.assertEqual(prepared.stage['runId'],'100')
        self.assertEqual(prepared.current_host['runId'],'200')
        self.assertTrue(any(r['required'] and r['status']=='passed' for r in prepared.scan_results))
        self.assertFalse(prepared._bound)
        self.assertEqual(self.api.records,[])
        self.assertFalse(self.runner.mutations())
    def test_missing_current_scans_or_scope_never_authenticates(self):
        for environment,target,component,mode in [('release/prod','dev-run','api',None),
            ('develop/dev','missing','api',None),('develop/dev','dev-run','missing',None),
            ('develop/dev','dev-run','api','scanner')]:
            with self.subTest(environment=environment,target=target,component=component,mode=mode):
                self.api.fail_mode=mode
                with self.assertRaises(ContractError):
                    operation_entry.prepare_apply(self.api,self.runner,self.environment,environment,target,component)
                self.assertFalse(self.runner.mutations());self.assertEqual(self.api.records,[])
    def test_cleanup_confirmation_is_exact_and_unlock_requires_native_lock(self):
        for op,confirmation,lock in [('destroy','',''),('destroy','destroy develop/dev/dev-run/all',''),
                ('unlock','unlock develop/dev/dev-run/api',''),('unlock','unlock develop/dev/dev-run/api other','native-lock')]:
            with self.subTest(op=op,confirmation=confirmation),self.assertRaises(ContractError):
                operation_entry.confirmation(op,'develop/dev','dev-run','api',confirmation,lock)
        operation_entry.confirmation('destroy','develop/dev','dev-run','api','destroy develop/dev/dev-run/api','')
        operation_entry.confirmation('unlock','develop/dev','dev-run','api','unlock develop/dev/dev-run/api native-lock','native-lock')

if __name__=='__main__':unittest.main()
