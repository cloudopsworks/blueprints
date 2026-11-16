"""Composition-only injected context tests, not host authorization proof."""
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from authorization import PreparedAuthorization
from protected_runtime import context,CloudExecutor
from executor import Runner
from test_native_preflight import Inventory
from test_providers import request

class ProtectedRuntimeTests(unittest.TestCase):
    def prepared(self):
        # Explicit injected trusted-process fixture; the production constructor
        # is supplied only by independently API-verified authorization.prepare.
        value=object.__new__(PreparedAuthorization);value._bound=True;value._inspection=False
        value.authorize=lambda *args:None
        value.resolve_context=lambda request:{'historical_handle':None}
        return value
    def test_fresh_canonical_inventory_uses_only_explicit_cloud_environment(self):
        r=request('gcp.cloudrun');r['target']['ownership']='managed';ex=Inventory(r)
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'GH_TOKEN':'never-native-secret','HOME':'/canary-home'}):
            ctx,cloud=context(self.prepared(),ex,workdir=directory,credentials={'PATH':'/trusted','GOOGLE_APPLICATION_CREDENTIALS':'/private/credential.json'})
            result=ctx['iac_resolve'](r,ex)
            self.assertFalse(result['existing']['exists'])
            self.assertEqual(ctx['privateStateDigests'],{})
            for argv,kwargs in ex.calls:
                self.assertNotIn('GH_TOKEN',kwargs['env'])
                self.assertNotEqual(kwargs['env']['HOME'],'/canary-home')
                self.assertEqual(kwargs['env']['CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE'],'/private/credential.json')
    def test_readiness_deadline_retains_isolation_and_bounds_real_cloud_runner(self):
        from providers.common import DeadlineExecutor
        from executor import ExecutionError
        with patch.dict(os.environ,{'GH_TOKEN':'parent-canary'}):
            for underlying in (Runner(inherit_environment=False),CloudExecutor(Runner(inherit_environment=False),{'PATH':os.environ['PATH']})):
                wrapped=DeadlineExecutor(underlying,{'overallDeadline':time.monotonic()+2})
                result=wrapped.run([sys.executable,'-c','import os;print(os.getenv("GH_TOKEN"))'])
                self.assertEqual(result.stdout,'None\n')
            wrapped=DeadlineExecutor(CloudExecutor(Runner(timeout=60,inherit_environment=False),{'PATH':os.environ['PATH']}),{'overallDeadline':time.monotonic()+.1})
            started=time.monotonic()
            with self.assertRaises(ExecutionError):wrapped.run([sys.executable,'-c','import time;time.sleep(5)'])
            self.assertLess(time.monotonic()-started,1)

    def test_wire_or_inspection_context_and_ambient_runner_cannot_authorize_native_preflight(self):
        for prepared in ({'authorized':True},self.prepared()):
            with tempfile.TemporaryDirectory() as directory,self.assertRaises(Exception):
                context(prepared,Runner(),workdir=directory,credentials={})
        value=self.prepared();value._inspection=True
        with tempfile.TemporaryDirectory() as directory,self.assertRaises(Exception):
            context(value,Inventory(request('aws.lambda')),workdir=directory,credentials={})
if __name__=='__main__':unittest.main()
