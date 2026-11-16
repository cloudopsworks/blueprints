"""Injected-process saved-plan/ownership tests, not live backend/provider proof."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from contracts import ContractError, digest
from executor import Runner
from iac import IaCError, IaCExecutor, module_tree, native_backend, verify_saved_plan
from operations import StateHandleStore
from test_operations import FakeGitHub

FIXTURES=Path(__file__).with_name('fixtures')/'operations'


class Process:
    def __init__(self, store, changes): self.store,self.changes,self.calls=store,changes,[]; self.state_addresses=[]; self.workspace_missing=False
    def run(self,argv,**kw):
        self.calls.append((argv,kw))
        self.assert_persisted = bool(self.store.entries())
        if argv[1:]==['version','-json']: output='{"terraform_version":"1.11.4"}'
        elif argv[1:]==['--version']: output='terragrunt version v0.99.4\n'
        elif 'show' in argv: output=json.dumps({'resource_changes':self.changes})
        elif 'state' in argv: output=json.dumps({'version':4,'resources':[{'mode':'managed','type':a.split('.')[0],'name':a.split('.')[1],'instances':[{}]} for a in self.state_addresses]})
        else: output='opaque-provider-output-sentinel'
        code=2 if 'plan' in argv else 1 if 'workspace' in argv and 'select' in argv and self.workspace_missing else 0
        return subprocess.CompletedProcess(argv,code,output,'opaque-secret-stderr')


def change(actions,address='helm_release.component',before=None,after=None):
    return {'mode':'managed','address':address,'change':{'actions':actions,'before':before,'after':after}}


class IaCExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name).resolve();self.module=self.root/'module';self.module.mkdir()
        (self.module/'main.tf').write_text('# fixed trusted fixture\n')
        (self.module/'.terraform.lock.hcl').write_text('# lock fixture\n')
        self.plan=json.loads((FIXTURES/'destroy-plan.json').read_text())
        self.plan['operation']='apply';h=self.plan['stateHandle'];h['ownership']='managed'
        h['origin']['moduleRevision']=module_tree(self.module,['.terraform.lock.hcl','main.tf'])
        h['origin']['providerLockDigest']='sha256:'+hashlib.sha256((self.module/'.terraform.lock.hcl').read_bytes()).hexdigest()
        self.plan['stateHandleDigest']=digest(h)
        self.plan['inputs']={'resource':h['resourceIdentity'],'workload':{'kind':'http','port':8080,'healthPath':'/health'},'configuration':{'kind':'aws.eks'}}
        self.catalog={'tools':{'opentofu':'1.11.4','terragrunt':'0.99.4'},'modules':{'aws-eks':{
            'path':'module','activationBlocked':False,'files':['.terraform.lock.hcl','main.tf'],'ownedResourceAddresses':['helm_release.component']}}}
        self.store=StateHandleStore(FakeGitHub(),h['origin']['repository'],42,verify_origin=lambda handle,entry:True)
        self.process=Process(self.store,[change(['create'])])
        self.executor=IaCExecutor(self.root,self.catalog,executor=self.process)

    def execute(self,**extra):
        return self.executor.execute(self.plan,canonical=copy.deepcopy(self.plan),store=self.store,
            resource_claims=['aws:resolved:example:release:api'],existing={'providerIdentity':'123456789012','exists':False},
            values={},credentials={},**extra)

    def test_new_pair_routes_private_backend_secrets_separately_from_provider_environment(self):
        handle=self.plan['stateHandle'];handle['backend']['authRef']='aws-state'
        handle['backendIdentity']={'provider':'aws','accountId':'999999999999'}
        handle['authRefs']=sorted(set(handle['authRefs']+['aws-state']))
        self.plan['stateHandleDigest']=digest(handle)
        pair={'workload':{'provider':'aws','identity':{'provider':'aws','accountId':handle['providerIdentity']},
            'environment':{'AWS_ACCESS_KEY_ID':'KEY-workload','AWS_SECRET_ACCESS_KEY':'WORKLOAD-CANARY','AWS_SESSION_TOKEN':'WORKLOAD-SESSION'}},
            'backend':{'provider':'aws','identity':handle['backendIdentity'],
            'environment':{'AWS_ACCESS_KEY_ID':'KEY-state','AWS_SECRET_ACCESS_KEY':'BACKEND-CANARY','AWS_SESSION_TOKEN':'BACKEND-SESSION'}}}
        original=self.process.run;captured=[]
        def run(argv,**kwargs):
            if 'init' in argv:
                captured.append((json.loads((kwargs['cwd']/'backend.tf.json').read_text()),dict(kwargs['env'])))
                self.assertEqual((kwargs['cwd']/'backend.tf.json').stat().st_mode&0o777,0o600)
            return original(argv,**kwargs)
        self.process.run=run
        result=self.executor.execute(self.plan,canonical=copy.deepcopy(self.plan),store=self.store,
            resource_claims=['aws:resolved:example:release:api'],existing={'providerIdentity':handle['providerIdentity'],'exists':False},
            values={},credentials=pair)
        native,env=captured[0]
        self.assertEqual(native['terraform']['backend']['s3']['secret_key'],'BACKEND-CANARY')
        self.assertEqual(env['AWS_SECRET_ACCESS_KEY'],'WORKLOAD-CANARY')
        self.assertNotIn('CANARY',json.dumps(result)+json.dumps(self.store.github.records))
        self.assertFalse(Path(self.process.calls[0][1]['cwd']).exists())
        # A new handle can never quietly fall back to legacy flat credentials.
        self.process.calls=[]
        with self.assertRaises(ContractError):
            self.executor.execute(self.plan,canonical=copy.deepcopy(self.plan),store=self.store,
                resource_claims=['aws:resolved:example:release:api'],existing={'providerIdentity':handle['providerIdentity'],'exists':False},values={},credentials={})
        self.assertEqual(self.process.calls,[])

    def test_fresh_pre_submit_guard_denial_retains_claim_but_submits_no_apply(self):
        def deny():
            self.assertTrue(any('show' in argv for argv,kw in self.process.calls))
            raise RuntimeError('native ownership drift')
        with self.assertRaisesRegex(RuntimeError,'native ownership drift'):
            self.execute(before_apply=deny)
        self.assertTrue(self.store.entries())
        self.assertFalse(any('apply' in argv for argv,kw in self.process.calls))

    def test_persist_before_init_then_exact_saved_apply_private_workspace(self):
        result=self.execute()
        self.assertTrue(self.process.assert_persisted)
        self.assertEqual(result['counts']['create'],1)
        apply=[v for v in self.process.calls if 'apply' in v[0]]
        self.assertEqual(apply[0][0][-3:],['apply','-input=false','operation.tfplan'])
        self.assertNotIn('opaque',json.dumps(result))
        work=Path(apply[0][1]['cwd']);self.assertFalse(work.exists())
        self.assertEqual(apply[0][1]['env']['TF_IN_AUTOMATION'],'true')

    def test_private_preflight_snapshot_must_match_fresh_backend_state_before_plan(self):
        self.execute(expected_state_digest=digest({'version':4,'resources':[]}))
        self.process.calls.clear()
        with self.assertRaisesRegex(IaCError,'state_changed_since_preflight'):
            self.execute(expected_state_digest='sha256:'+'1'*64)
        self.assertFalse(any('plan' in argv or 'apply' in argv for argv,kwargs in self.process.calls))

    def test_blocked_catalog_wrong_tree_account_and_unowned_existing_fail_before_init(self):
        self.catalog['modules']['aws-eks']['activationBlocked']=True
        with self.assertRaisesRegex(IaCError,'capability_blocked'):self.execute()
        self.assertEqual(self.process.calls,[])
        self.catalog['modules']['aws-eks']['activationBlocked']=False
        (self.module/'main.tf').write_text('# modified\n')
        with self.assertRaisesRegex(IaCError,'module_binding'):self.execute()
        self.assertEqual(self.process.calls,[])
        (self.module/'main.tf').write_text('# fixed trusted fixture\n')
        with self.assertRaisesRegex(IaCError,'unowned_existing'):
            self.executor.execute(self.plan,canonical=self.plan,store=self.store,resource_claims=['aws:fixture'],
                existing={'providerIdentity':'123456789012','exists':True,'ownerDigest':digest(self.plan['stateHandle'])},values={},credentials={})
        self.assertEqual(self.process.calls,[])

    def test_external_new_resource_requires_separate_adoption(self):
        self.plan['stateHandle']['ownership']='external';self.plan['stateHandleDigest']=digest(self.plan['stateHandle'])
        with self.assertRaisesRegex(IaCError,'adoption_prerequisite'):self.execute()
        self.assertEqual(self.process.calls,[])

    def test_plan_foreign_parent_replacement_and_unowned_update_rejected(self):
        for value in (change(['create'],'aws_iam_role.parent'),change(['delete','create']),change(['update'])):
            with self.subTest(value=value),self.assertRaises(IaCError):
                verify_saved_plan({'resource_changes':[value]},operation='apply',addresses=['helm_release.component'],owner_digest='owner',previously_owned=set())
        values={'resource_changes':[change(['delete'])]}
        with self.assertRaisesRegex(IaCError,'apply_delete'):
            verify_saved_plan(values,operation='apply',addresses=['helm_release.component'],owner_digest='owner',previously_owned={'helm_release.component'})
        self.assertEqual(verify_saved_plan(values,operation='destroy',addresses=['helm_release.component'],owner_digest='owner',previously_owned={'helm_release.component'})['delete'],1)

    def test_recovery_requires_durable_owner_and_uses_saved_destroy(self):
        self.plan['operation']='destroy';self.plan['inputs']=None
        with self.assertRaisesRegex(IaCError,'historical_handle'):self.execute()
        self.store.reserve(self.plan['stateHandle'],['aws:resolved:example:release:api'])
        self.process.changes=[change(['delete'])]
        self.process.state_addresses=['helm_release.component']
        result=self.execute()
        self.assertEqual(result['counts']['delete'],1)
        self.assertTrue(any('-destroy' in argv for argv,_ in self.process.calls))
        self.assertFalse(any('destroy' in argv for argv,_ in self.process.calls))

    def test_historical_unlock_uses_exact_native_lock_without_plan_or_apply(self):
        self.plan.update(operation='unlock',inputs=None,lockId='exact-native-lock')
        self.store.reserve(self.plan['stateHandle'],['aws:resolved:example:release:api'])
        result=self.execute()
        self.assertEqual(result['phase'],'unlock')
        operations=[argv for argv,_ in self.process.calls]
        self.assertTrue(any(argv[-3:]==['force-unlock','-force','exact-native-lock'] for argv in operations))
        self.assertFalse(any('plan' in argv or 'apply' in argv or 'destroy' in argv for argv in operations))

    def test_next_apply_reuses_frozen_handle_with_new_invocation_and_values(self):
        self.execute()
        original=copy.deepcopy(self.plan['stateHandle'])
        self.plan['invocation']['runId']='999'
        self.plan['invocation']['sourceSha']='f'*40
        self.process.changes=[change(['update'],before={'tags':{'cloudopsworks-owner':digest(original)}},after={'tags':{'cloudopsworks-owner':digest(original)}})]
        self.process.state_addresses=['helm_release.component']
        self.executor.execute(self.plan,canonical=copy.deepcopy(self.plan),store=self.store,
            resource_claims=['aws:resolved:example:release:api'],existing={'providerIdentity':'123456789012','exists':True,'ownerDigest':digest(original)},
            values={'artifact':{'digest':'sha256:'+'f'*64}},credentials={})
        self.assertEqual(self.plan['stateHandle'],original)
        self.assertEqual(len(self.store.github.records),1)
        self.assertEqual(self.store.github.records[0]['payload']['stateHandle']['native'],original['native'])

    def test_fresh_named_workspace_creation_but_historical_missing_fails(self):
        self.plan['stateHandle']['backend']['workspace']='isolated'
        self.plan['stateHandleDigest']=digest(self.plan['stateHandle'])
        self.process.workspace_missing=True
        self.execute()
        self.assertTrue(any(argv[-3:]==['workspace','new','isolated'] for argv,_ in self.process.calls))
        self.process.calls=[]
        with self.assertRaisesRegex(IaCError,'historical_workspace_missing'): self.execute()
        self.assertFalse(any('new' in argv for argv,_ in self.process.calls))
        self.assertFalse(any('plan' in argv or 'apply' in argv for argv,_ in self.process.calls))

    def test_private_home_disables_ambient_cloud_credentials(self):
        with mock.patch.dict(os.environ,{'HOME':'/host-home-credential-canary'}): self.execute()
        for _, call in self.process.calls:
            env=call['env']
            self.assertNotEqual(env['HOME'],'/host-home-credential-canary')
            self.assertEqual(env['AWS_EC2_METADATA_DISABLED'],'true')
            self.assertTrue(env['AWS_CONFIG_FILE'].startswith(env['HOME']+'/'))
            self.assertTrue(env['AWS_SHARED_CREDENTIALS_FILE'].startswith(env['HOME']+'/'))
            self.assertTrue(env['AZURE_CONFIG_DIR'].startswith(env['HOME']+'/'))
            self.assertTrue(env['CLOUDSDK_CONFIG'].startswith(env['HOME']+'/'))

    def test_no_ambient_terraform_environment_or_raw_output(self):
        with mock.patch.dict(os.environ,{'TF_CLI_ARGS':'secret-sentinel','TG_CONFIG':'untrusted.hcl'}):
            result=Runner(inherit_environment=False).run([sys.executable,'-c','import os;print(os.getenv("TF_CLI_ARGS"));print(os.getenv("TG_CONFIG"))'],env={})
        self.assertEqual(result.stdout,'None\nNone\n')
        with self.assertRaisesRegex(IaCError,'environment_override'):
            self.executor.execute(self.plan,canonical=self.plan,store=self.store,resource_claims=['aws:fixture'],
                existing={'providerIdentity':'123456789012','exists':False},values={},credentials={'TF_CLI_ARGS':'bad'})
        self.assertEqual(self.process.calls,[])
        self.assertNotIn('auth',json.dumps(native_backend(self.plan['stateHandle'])))


if __name__=='__main__':unittest.main()
