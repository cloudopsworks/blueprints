"""Protected authorization boundary; local process/API doubles, no cloud proof."""
import base64
import copy
import hashlib
import io
import zipfile
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'cd/monorepo/runtime'))
import authorization as auth
from contracts import ContractError, digest
from snapshot import materialize_snapshot
from test_operations import FakeGitHub

FIXTURES = Path(__file__).with_name('fixtures') / 'operations'
BINARY = os.environ.get('TRONADOR_TEST_BINARY')


class Process:
    def run(self, argv, **kwargs):
        return subprocess.run([BINARY, *argv[1:]], text=True, capture_output=True, **kwargs)




def captured(provider,account,principal='selected',*,project='example-dev'):
    if provider=='aws':
        binding={'provider':'aws','roleArn':'arn:aws:iam::'+account+':role/'+principal,'region':'us-east-1'}
        identity={'provider':'aws','accountId':account}
        env={'AWS_ACCESS_KEY_ID':'CANARY-'+principal,'AWS_SECRET_ACCESS_KEY':'CANARY-SECRET-'+principal,'AWS_SESSION_TOKEN':'CANARY-TOKEN-'+principal}
    elif provider=='gcp':
        binding={'provider':'gcp','project':project,'serviceAccount':principal+'@'+project+'.iam.gserviceaccount.com',
                 'workloadIdentityProvider':'projects/999/locations/global/workloadIdentityPools/pool/providers/provider'}
        identity={'provider':'gcp','projectNumber':account}
        env={'GOOGLE_APPLICATION_CREDENTIALS':'/private/CANARY-'+principal+'.json'}
    else:
        binding={'provider':'azure','clientId':('33333333-3333-3333-3333-333333333333' if principal=='state' else '11111111-1111-1111-1111-111111111111'),
                 'tenantId':'22222222-2222-2222-2222-222222222222','subscriptionId':account}
        identity={'provider':'azure','tenantId':binding['tenantId'],'subscriptionId':account}
        env={'ARM_CLIENT_ID':binding['clientId'],'ARM_TENANT_ID':binding['tenantId'],'ARM_SUBSCRIPTION_ID':account,
             'ARM_OIDC_TOKEN_FILE_PATH':'/private/CANARY-'+principal}
    return {'provider':provider,'identity':identity,'environment':env,'binding':binding}

class TemplateAPI:
    bind_target=False
    def __init__(self):
        source=ROOT.parent/'monorepo-app-template'
        self.entries=[];self.blobs={};self.requested=[]
        for p in sorted(source.rglob('*')):
            rel=p.relative_to(source).as_posix()
            if '.git' in p.relative_to(source).parts:continue
            if p.is_dir():self.entries.append({'path':rel,'mode':'040000','type':'tree','sha':'c'*40});continue
            data=p.read_bytes()
            if rel=='.cloudopsworks/cloudopsworks-ci.yaml':
                data=data.replace(b'owners: []',b'owners: [admin]').replace(b'reviewers: []',b'reviewers: [alice]')
            if self.bind_target and rel=='.cloudopsworks/cloudopsworks-ci.yaml':
                data=data.replace(b'targets: []',b'targets: [dev-run]',1)
            if self.bind_target and rel=='.cloudopsworks/vars/inputs-dev.yaml':
                data=b'''monorepo:
  targets:
    dev-run:
      provider: gcp
      kind: gcp.cloudrun
      authRef: gcp-dev
      project: example-dev
      region: us-central1
      service: api
      serviceAccount: api@example-dev.iam.gserviceaccount.com
      readiness:
        deadlineSeconds: 600
        intervalSeconds: 5
        probe:
          kind: http
          path: /health
          method: GET
          requestBody: ""
          expectedStatus: 200
          responseContains: ok
          auth:
            kind: gcp-id-token
'''
            sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            self.entries.append({'path':rel,'mode':'100644','type':'blob','sha':sha,'size':len(data)})
            self.blobs[sha]={'sha':sha,'encoding':'base64','size':len(data),'content':base64.b64encode(data).decode()}
    def repo(self,method,path,**kwargs):
        self.requested.append(path)
        if path=='/git/commits/'+'a'*40:return {'sha':'a'*40,'tree':{'sha':'b'*40}}
        if path=='/git/trees/'+'b'*40+'?recursive=1':return {'sha':'b'*40,'truncated':False,'tree':self.entries}
        return self.blobs[path.rsplit('/',1)[1]]

class AuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.context = json.loads((FIXTURES/'operation-context-frozen.json').read_text())
        self.context['backend']['authRef']='aws-state'
        self.context['authRefs']=sorted({'gcp-prod','aws-state'})
        self.handle = json.loads((FIXTURES/'state-develop.json').read_text())
        self.host = {'repository': self.handle['origin']['repository'], 'runId': '200', 'runAttempt': '2',
                     'workflowSha': 'e'*40, 'workflowRef': 'example/monorepo/.github/workflows/main-build.yml@refs/heads/develop'}
        self.source_context = {'event':'push','ref':'refs/heads/develop','baseRef':'',
                               'sourceSha':self.handle['origin']['sourceSha'],'prNumber':None}
        self.stage = {'runId': '100', 'runAttempt': '1', 'artifactId': '500', 'archiveDigest': 'sha256:'+'f'*64}
        self.entry = {'id': 900, 'payload': {'stateHandle': self.handle,
            'stateHandleDigest': digest(self.handle), 'resourceClaims': ['aws:fixture']}}

    def prepared(self, *, inspection=False):
        c = copy.deepcopy(self.context)
        current = {**c['invocation'], 'event': 'push', 'ref': 'refs/tags/v1.0.0',
                   'headSha': c['plan']['headSha'], 'workflowSha': 'e'*40,
                   'workflowRef': 'example/mixed-app/.github/workflows/main-build.yml@refs/tags/v1.0.0'}
        obj = auth.PreparedAuthorization(FakeGitHub(), Process(), None, c['origin']['repository'],
            self.stage, {}, current, {}, c['plan'], {}, {}, c['lifecycle'], [] if not inspection else None, inspection)
        obj._source_context = self.source_context
        obj._credentials={'workload':captured('gcp','123456789012',project='example-prod'),
                          'backend':captured('aws','123456789012')}
        return obj

    def test_state_marker_current_host_distinct_from_source_and_owner(self):
        line = auth.state_marker(self.handle, self.entry, host=self.host, source_stage=self.stage, source_context=self.source_context)
        value = auth.parse_state_marker(line.encode(), self.handle, self.entry, run_id='200', attempt='2')
        self.assertEqual(value['runId'], '200')
        self.assertEqual(value['sourceStage']['runId'], '100')
        self.assertNotIn('state-example', line)
        self.assertNotIn('backend', line)

    def test_state_marker_forged_receipt_attempt_handle_claims_and_duplicates(self):
        line = auth.state_marker(self.handle, self.entry, host=self.host, source_stage=self.stage, source_context=self.source_context)
        for mutate in (lambda v: v.update(runAttempt='3'), lambda v:v.update(receiptId='901'),
                       lambda v:v.update(stateHandleDigest='sha256:'+'0'*64),
                       lambda v:v.update(resourceClaims=['aws:foreign']), lambda v:v.update(extra=True)):
            value = json.loads(line[len(auth.STATE_MARKER):]); mutate(value)
            with self.subTest(value=value), self.assertRaises(ContractError):
                auth.parse_state_marker((auth.STATE_MARKER+json.dumps(value)).encode(), self.handle,
                                        self.entry, run_id='200', attempt='2')
        with self.assertRaises(ContractError):
            auth.parse_state_marker((line+'\n'+line).encode(), self.handle, self.entry, run_id='200', attempt='2')

    def test_inspection_cannot_bind_or_authorize(self):
        obj = self.prepared(inspection=True)
        with self.assertRaises(ContractError):obj.bind('s3: {}', {}, {}, automation_id=42)
        with self.assertRaises(ContractError):obj.authorize({}, {})
        view=obj.inspect(); view['stage']['artifactId']='999'
        self.assertEqual(obj.stage['artifactId'], '500')

    def test_exact_local_readback_not_current_run_or_bot_is_authority(self):
        obj=self.prepared(); obj.current_host=self.host
        obj._pending[digest(self.handle)]={'handle':self.handle,'claims':['aws:fixture']}
        lines=[];obj._on_readback=lines.append
        with patch.object(obj, '_verify_historical', side_effect=ContractError('unverified','unverified')):
            with self.assertRaises(ContractError):obj._verify_origin(self.handle,self.entry)
            obj.record_readback(self.handle,self.entry)
            self.assertTrue(obj._verify_origin(self.handle,self.entry))
            forged=copy.deepcopy(self.entry);forged['id']=901
            with self.assertRaises(ContractError):obj._verify_origin(self.handle,forged)
            forged=copy.deepcopy(self.entry);forged['payload']['resourceClaims']=['aws:foreign']
            self.assertFalse(obj._verify_origin(self.handle,forged))
        self.assertEqual(len(lines),1)

    def test_failed_marker_retains_reservation_without_local_exemption(self):
        obj=self.prepared();obj.current_host=self.host
        obj._pending[digest(self.handle)]={'handle':self.handle,'claims':['aws:fixture']}
        def fail(_):raise OSError('marker unavailable')
        obj._on_readback=fail
        with self.assertRaises(OSError):obj.record_readback(self.handle,self.entry)
        self.assertEqual(obj._readbacks,{})

    def test_wrong_local_claims_rejected_before_marker(self):
        obj=self.prepared();obj.current_host=self.host;obj._on_readback=lambda _: self.fail('printed invalid proof')
        obj._pending[digest(self.handle)]={'handle':self.handle,'claims':['aws:other']}
        with self.assertRaises(ContractError):obj.record_readback(self.handle,self.entry)

    def test_forged_bot_receipt_without_exact_protected_job_is_rejected(self):
        obj=self.prepared()
        class API:
            def pages(self,path):return []
            def repo(self,method,path,**kwargs):
                return {'id':100,'run_attempt':1,'head_sha':'a'*40,'path':'.github/workflows/attacker.yml'}
        obj.github=API()
        with self.assertRaises(ContractError):obj._writer_proof(self.handle,self.entry)

    @unittest.skipUnless(BINARY,'set TRONADOR_TEST_BINARY to the reviewed Go binary')
    def test_private_metadata_transport_preserves_complete_go_handle(self):
        obj=self.prepared(); c=self.context
        obj._module_origin=lambda _:copy.deepcopy(c['origin'])
        args=dict(target=c['plan']['targets'][0],component='api',provider_identity=c['providerIdentity'],
                  backend=c['backend'],auth_refs=c['authRefs'])
        original=obj._operation(**args)['stateHandle']
        obj.plan=auth._metadata_plan(c['origin']['repository'],c['plan']['headSha'],
            {k:c['plan'][k] for k in ('components','targets','previewPolicy')})
        self.assertNotEqual(obj.plan['version'],c['plan']['version'])
        self.assertNotEqual(obj.plan['buildSelection'],c['plan']['buildSelection'])
        self.assertEqual(original,obj._operation(**args)['stateHandle'])

    @unittest.skipUnless(BINARY,'set TRONADOR_TEST_BINARY to the reviewed Go binary')
    def test_metadata_transport_both_native_api_identity_variants(self):
        for fixture in ('rest-existing-id','rest-managed-fresh-no-id'):
            with self.subTest(fixture=fixture):
                obj=self.prepared(); c=self.context
                obj.plan=json.loads((ROOT/'tests/monorepo/contracts/valid'/(fixture+'.json')).read_text())
                obj._module_origin=lambda _:copy.deepcopy(c['origin'])
                target=obj.plan['targets'][0]
                if fixture=='rest-existing-id':
                    target.pop('apiName');target.pop('apiVersion')
                args=dict(target=target,component='api',provider_identity=c['providerIdentity'],
                          backend=c['backend'],auth_refs=[target['authRef']])
                original=obj._operation(**args)['stateHandle']
                obj.plan=auth._metadata_plan(c['origin']['repository'],obj.plan['headSha'],
                    {k:obj.plan[k] for k in ('components','targets','previewPolicy')})
                self.assertEqual(original,obj._operation(**args)['stateHandle'])
                self.assertEqual(set(original['apiIdentity']),{'restApiId'} if fixture=='rest-existing-id' else {'name','version'})

    @unittest.skipUnless(BINARY,'set TRONADOR_TEST_BINARY to the reviewed Go binary')
    def test_generated_rest_alias_updates_only_at_verified_creation_gate(self):
        from operations import StateHandleStore
        obj=self.prepared(); c=self.context
        obj.plan=json.loads((ROOT/'tests/monorepo/contracts/valid/rest-managed-fresh-no-id.json').read_text())
        obj._module_origin=lambda _:copy.deepcopy(c['origin'])
        target=obj.plan['targets'][0]
        handle=obj._operation(target=target,component='api',provider_identity=c['providerIdentity'],
            backend=c['backend'],auth_refs=[target['authRef']])['stateHandle']
        claim='aws:123456789012:us-east-1:rest-api:new-name:public-api'
        obj._bound=True; obj._on_readback=lambda _:None
        obj._pending[digest(handle)]={'handle':handle,'claims':[claim]}
        obj.store=StateHandleStore(obj.github,obj.repository,42,verify_origin=obj._verify_origin,
                                  after_readback=obj.record_readback)
        obj.store.reserve(handle,[claim])
        with self.assertRaises(ContractError):
            obj.bind_created_rest_api(handle,'generated123',verify_creation=lambda *_:False)
        self.assertEqual(len(obj.github.records),1)
        verified=[]
        def creation(h,identity):
            verified.append((h,identity))
            return h==handle and identity=='generated123'  # local private-state/host double, not cloud proof
        entry=obj.bind_created_rest_api(handle,'generated123',verify_creation=creation)
        self.assertEqual(len(verified),1)
        self.assertEqual(len(entry['payload']['resourceClaims']),2)
        self.assertEqual(obj._pending[digest(handle)]['claims'],entry['payload']['resourceClaims'])
        self.assertEqual(len(obj.github.records),2)

    @unittest.skipUnless(BINARY,'set TRONADOR_TEST_BINARY to the reviewed Go binary')
    def test_real_go_frozen_operation_and_historical_backend_preservation(self):
        obj=self.prepared(); c=self.context
        obj._module_origin=lambda _:copy.deepcopy(c['origin'])
        target=c['plan']['targets'][0]
        fresh=obj._operation(target=target,component='api',provider_identity=c['providerIdentity'],
                             backend=c['backend'],auth_refs=c['authRefs'])
        historical=fresh['stateHandle']
        obj.current_host['runId']='201'
        recovered=obj._operation(target=target,component='api',provider_identity=c['providerIdentity'],
                      backend=c['backend'],auth_refs=c['authRefs'],historical=historical)
        self.assertEqual(recovered['stateHandle'],historical)
        self.assertEqual(recovered['invocation']['runId'],'201')
        wrong=copy.deepcopy(c['backend']);wrong['bucket']='redirected'
        with self.assertRaises(ContractError):obj._operation(target=target,component='api',
            provider_identity=c['providerIdentity'],backend=wrong,auth_refs=c['authRefs'],historical=historical)

    @unittest.skipUnless(BINARY,'set TRONADOR_TEST_BINARY to the reviewed Go binary')
    def test_yaml_settings_sole_go_normalization_and_secret_safe_errors(self):
        self.assertEqual(auth._settings(Process(),'identities','gcp-prod: "123456789012"\n'),
                         {'gcp-prod':'123456789012'})
        with self.assertRaises(ContractError) as caught:
            auth._settings(Process(),'identities','gcp-prod: {secret: SUPER_SECRET_CANARY}\n')
        self.assertNotIn('SUPER_SECRET_CANARY',str(caught.exception))

    @unittest.skipUnless(BINARY,'set TRONADOR_TEST_BINARY to the reviewed Go binary')
    def test_api_snapshot_real_go_validate_never_fetches_source_code(self):
        source=ROOT.parent/'monorepo-app-template'
        api=TemplateAPI()
        with tempfile.TemporaryDirectory() as directory:
            materialize_snapshot(api,'a'*40,Path(directory).resolve())
            normalized=auth._json_cli(Process(),['validate','--workdir',str(Path(directory).resolve()),'--json'])
            self.assertEqual(len(normalized['resolved']['components']),3)
            for p in Path(directory).rglob('*.go'):self.assertEqual(p.read_bytes(),b'')




@unittest.skipUnless(BINARY,'set TRONADOR_TEST_BINARY to the reviewed Go binary')
class BackendPairTests(unittest.TestCase):
    setUp=AuthorizationTests.setUp
    prepared=AuthorizationTests.prepared
    def test_all_nine_fresh_and_frozen_backend_pairs_and_principal_checks(self):
        for workload in ('aws','gcp','azure'):
            for state in ('aws','gcp','azure'):
                with self.subTest(workload=workload,state=state):
                    obj=self.prepared(); original=self.context
                    work_account='44444444-4444-4444-4444-444444444444' if workload=='azure' else '123456789012'
                    state_account='99999999-9999-9999-9999-999999999999' if state=='azure' else '999999999999'
                    pair={'workload':captured(workload,work_account,'work'),'backend':captured(state,state_account,'state')}
                    obj._credentials=pair
                    work_ref=workload+'-work'; state_ref=state+'-state'
                    obj._settings={'auth':{work_ref:pair['workload']['binding'],state_ref:pair['backend']['binding']},
                                   'identities':{work_ref:work_account,state_ref:state_account}}
                    target=copy.deepcopy(obj.plan['targets'][0])
                    readiness=target['readiness']; readiness['probe']['auth']={'kind':'none'}
                    common={k:target[k] for k in ('id','environment','configDigest','readiness')}
                    if workload=='aws':
                        target={**common,'provider':'aws','kind':'aws.eks','authRef':work_ref,
                                'region':'us-east-1','cluster':'example','namespace':'api'}
                    elif workload=='azure':
                        target={**common,'provider':'azure','kind':'azure.aks','authRef':work_ref,
                                'subscriptionId':work_account,'resourceGroup':'rg','cluster':'example','namespace':'api'}
                    else:target.update(authRef=work_ref)
                    obj.plan['targets']=[target]
                    backend=json.loads((FIXTURES/('backend-auth-'+state+'context.json')).read_text())['backend']
                    obj._module_origin=lambda _:copy.deepcopy(original['origin'])
                    plan=obj._operation(target=target,component='api',provider_identity=work_account,
                        backend=backend,auth_refs=[work_ref])
                    handle=plan['stateHandle']
                    self.assertEqual(handle['authRefs'],sorted({work_ref,state_ref}))
                    self.assertEqual(handle['backendIdentity'],pair['backend']['identity'])
                    obj._validate_historical_auth(handle,work_ref)
                    self.assertEqual(obj._execution_credentials(handle),pair)
                    obj.current_host['runId']='201'
                    frozen=obj._operation(target=target,component='api',provider_identity=work_account,
                        backend={k:v for k,v in handle['backend'].items() if k not in ('key','prefix')},
                        auth_refs=handle['authRefs'],historical=handle)
                    self.assertEqual(frozen['stateHandle'],handle)
                    self.assertEqual(frozen['invocation']['runId'],'201')
                    serialized=json.dumps(plan)
                    self.assertNotIn('CANARY',serialized)
                    del obj._settings['auth'][state_ref]
                    with self.assertRaises(ContractError):obj._validate_historical_auth(handle,work_ref)
                    obj._settings['auth'][state_ref]=pair['backend']['binding']
                    obj._settings['identities'][state_ref]='retargeted'
                    with self.assertRaises(ContractError):obj._validate_historical_auth(handle,work_ref)
                    obj._settings['identities'][state_ref]=state_account
                    # Same canonical context permits principal rotation, not an
                    # old or unrelated principal selected by the last login.
                    new=copy.deepcopy(pair['backend'])
                    key={'aws':'roleArn','gcp':'serviceAccount','azure':'clientId'}[state]
                    new['binding'][key]=({'aws':'arn:aws:iam::'+state_account+':role/rotated',
                        'gcp':'rotated@example-dev.iam.gserviceaccount.com',
                        'azure':'55555555-5555-5555-5555-555555555555'})[state]
                    obj._settings['auth'][state_ref]=new['binding']
                    with self.assertRaises(ContractError):obj._execution_credentials(handle)
                    obj._credentials['backend']=new
                    self.assertEqual(obj._execution_credentials(handle)['backend']['identity'],handle['backendIdentity'])

    def test_same_provider_two_distinct_principals_in_same_canonical_context(self):
        for provider in ('aws','gcp','azure'):
            account='44444444-4444-4444-4444-444444444444' if provider=='azure' else '123456789012'
            work=captured(provider,account,'work'); state=captured(provider,account,'state')
            handle=json.loads((FIXTURES/('backend-auth-'+provider+'handle.json')).read_text())
            handle['providerIdentity']=account
            handle['backendIdentity']=copy.deepcopy(state['identity'])
            # This test isolates exact per-ref capture selection; actual Go
            # generation for all nine typed workload/backend pairs is above.
            handle['resourceIdentity']['provider']=provider
            handle['resourceIdentity']['kind']={'aws':'aws.eks','gcp':'gcp.cloudrun','azure':'azure.aks'}[provider]
            work_ref=provider+'-work'; state_ref=provider+'-state'
            handle['authRefs']=sorted({work_ref,state_ref});handle['backend']['authRef']=state_ref
            obj=self.prepared();obj._credentials={'workload':work,'backend':state}
            obj._settings={'auth':{work_ref:work['binding'],state_ref:state['binding']},
                           'identities':{work_ref:account,state_ref:account}}
            self.assertNotEqual(work['binding'],state['binding'])
            obj._validate_historical_auth(handle,work_ref)
            self.assertEqual(obj._execution_credentials(handle)['backend']['binding'],state['binding'])
            obj._credentials={'workload':state,'backend':work}
            with self.assertRaises(ContractError):obj._execution_credentials(handle)

    def test_actual_backend_yaml_projection_and_binding_failures_do_not_export_canaries(self):
        cases=(('s3:\n  bucket: state-example\n  region: us-east-1\n  auth_ref: aws-state\n','s3','aws-state'),
               ('gcs:\n  bucket: state-example\n  auth_ref: gcp-state\n','gcs','gcp-state'),
               ('azurerm:\n  storage_account_name: stateexample\n  container_name: state\n  auth_ref: azure-state\n  use_oidc: true\n  use_azuread_auth: true\n','azurerm','azure-state'))
        for text,kind,ref in cases:
            value=auth.inspect_backend_settings(text,Process())
            self.assertEqual((value['kind'],value['authRef']),(kind,ref))
            self.assertNotIn('backendIdentity',value)
        with self.assertRaises(ContractError) as caught:
            auth.inspect_backend_settings('s3:\n  bucket: state\n  access_key: SECRET_CANARY_VALUE\n',Process())
        self.assertNotIn('SECRET_CANARY_VALUE',str(caught.exception))
        obj=self.prepared()
        with self.assertRaises(ContractError) as caught:
            obj.bind('gcs: {}',{k:'{}' for k in ('auth','identities','registries','probe-secrets','host-keys')},
                     {'AWS_SECRET_ACCESS_KEY':'SECRET_CANARY_VALUE'},automation_id=42)
        self.assertNotIn('SECRET_CANARY_VALUE',str(caught.exception))

    def test_legacy_same_exact_binding_preserves_bytes_and_flattens_only_after_verification(self):
        obj=self.prepared()
        handle=json.loads((FIXTURES/'state-develop.json').read_text())
        pair=captured('aws',handle['providerIdentity'],'legacy')
        obj._credentials={'workload':pair,'backend':copy.deepcopy(pair)}
        obj._settings={'auth':{'aws-dev':pair['binding']},'identities':{'aws-dev':handle['providerIdentity']}}
        before=json.dumps(handle,sort_keys=True)
        obj._validate_historical_auth(handle,'aws-dev')
        self.assertEqual(obj._execution_credentials(handle),pair['environment'])
        self.assertEqual(json.dumps(handle,sort_keys=True),before)
        obj._credentials['backend']['binding']['roleArn']='arn:aws:iam::123456789012:role/other'
        with self.assertRaises(ContractError):obj._execution_credentials(handle)


class HostAPI(TemplateAPI):
    repository='example/mixed-app'
    def __init__(self):
        super().__init__()
        self.fail_mode=None
        self.bp='b'*40
        self.repo_id={'id':'12345','fullName':self.repository}
        self.host={'repository':self.repo_id,'runId':'200','runAttempt':'1','event':'push',
            'ref':'refs/heads/develop','headSha':'a'*40,'workflowSha':'e'*40,'blueprintSha':self.bp,
            'workflowRef':self.repository+'/.github/workflows/main-build.yml@refs/heads/develop','actor':'operator'}
        self.run={'id':100,'run_attempt':1,'repository':{'id':12345},'event':'push','head_sha':'a'*40,
            'head_branch':'develop','path':'.github/workflows/main-build.yml','status':'completed','conclusion':'success',
            'actor':{'login':'operator'}, 'referenced_workflows':[{'path':'cloudopsworks/blueprints/.github/workflows/monorepo-main-build.yml@v5.11.0','sha':self.bp}]}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve()
            origin=materialize_snapshot(self,'a'*40,root)
            self.resolved=auth._json_cli(Process(),['validate','--workdir',str(root),'--json'])['resolved']
            self.lifecycle=auth._json_cli(Process(),['lifecycle','--workdir',str(root),'--event','push',
                '--ref','refs/heads/develop','--base-ref','','--json'])
        plan=auth._metadata_plan(self.repo_id,'a'*40,self.resolved)
        manifest=json.loads((ROOT/'tests/monorepo/contracts/valid/release-manifest.json').read_text())
        component=manifest['components'][0]
        manifest.update(version=plan['version'],tag='v'+plan['version'],previousTag=None,targets=plan['targets'],components=[])
        for c in plan['components']:
            item=copy.deepcopy(component)
            item.update(componentId=c['id'],package=c['package'],workload=c['workload'],targetIds=c['targetIds'])
            for artifact in ('mainArtifact','previewArtifact'):
                if item[artifact]:item[artifact]['builtVersion']=plan['version']
            manifest['components'].append(item)
        capsule={**{k:v for k,v in self.host.items() if k not in ('actor',)}, 'runId':'100',
            'sourceSha':'a'*40,'callerPath':'.github/workflows/main-build.yml','lifecycle':self.lifecycle,
            'planDigest':digest(plan),'manifestDigest':digest(manifest)}
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w') as z:
            for name,value in [('build-plan.json',plan),('manifest.json',manifest),('source-origin.json',origin),
                               ('scanners.json',self.resolved['scanners']),('host.json',capsule)]:
                z.writestr(name,json.dumps(value))
        self.archive=archive.getvalue()
        self.stage={'runId':'100','runAttempt':'1','artifactId':'500',
                    'archiveDigest':'sha256:'+hashlib.sha256(self.archive).hexdigest()}
        from staging import marker_record
        self.publisher_log=marker_record('12345','100','1','500',self.stage['archiveDigest']).encode()
        flags=self.resolved['scanners']
        enabled={'sonar':flags['sonarqubeEnabled'],'snyk':flags['snykEnabled'],'semgrep':flags['semgrepEnabled'],
                 'trivy':flags['trivyEnabled'],'dependency-track':flags['dependencyTrackEnabled']}
        results=[]
        for c in plan['components']:
            for scanner,on in enabled.items():
                results.append({'apiVersion':'cloudopsworks.io/operations/v1','kind':'ScannerResult',
                    'scanner':scanner,'profile':c['buildProfile'],'componentId':c['id'],'sourceSha':plan['headSha'],
                    'status':'passed' if on else 'disabled','required':bool(scanner=='sonar' and on and
                    flags['sonarqubeFailOnQualityGate'] and flags['sonarqubeQualityGateEnabled']),
                    'artifactDigest':None,'correlationId':'scan-'+c['id'],'errorCode':None})
        from scanners import _identity
        for index,result in enumerate(results):
            component=next(c for c in plan['components'] if c['id']==result['componentId'])
            identity=_identity(plan,manifest,component,result['scanner'],flags)
            result.update({k:v for k,v in identity.items() if k not in ('status','errorCode')})
        self.scan_log=auth.scan_marker(self.stage,self.resolved,results).encode()

    def repo(self,method,path,value=None,**kwargs):
        if path=='':return {'id':12345,'full_name':self.repository,'default_branch':'develop'}
        if path.startswith('/branches/'):
            return {'protected':self.fail_mode!='protection','commit':{'sha':'a'*40}}
        if path.startswith('/compare/'):return {'status':'identical','merge_base_commit':{'sha':'a'*40}}
        if path.startswith('/contents/'):
            data=b'name: trusted-caller\n'
            if self.fail_mode=='caller' and 'ref='+'e'*40 in path:data=b'name: forged-caller\n'
            sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            return {'encoding':'base64','content':base64.b64encode(data).decode(),'sha':sha}
        if path.startswith('/actions/runs/'):
            identity=int(path.split('/')[3])
            if '/jobs?' in path:
                job={'id':300 if identity==100 else 301,'run_id':identity,'run_attempt':1,'status':'completed',
                    'conclusion':'success','name':'lifecycle / '+('monorepo-stage-publisher' if identity==100 else 'monorepo-scan-barrier')}
                if self.fail_mode=='scanner' and identity==200:job['conclusion']='failure'
                return {'jobs':[job]}
            run=copy.deepcopy(self.run);run['id']=identity
            if self.fail_mode=='source' and identity==100:run['head_sha']='f'*40
            if self.fail_mode=='attempt':run['run_attempt']=2
            return run
        if path=='/actions/jobs/300/logs':return self.publisher_log
        if path=='/actions/jobs/301/logs':return self.scan_log
        if path=='/actions/artifacts/500':
            return {'id':500,'name':'monorepo-stage-100-1','expired':False,'workflow_run':{'id':100}}
        if path=='/actions/artifacts/500/zip':return self.archive
        if path.startswith('/environments/'):
            return {'deployment_branch_policy':{'protected_branches':True,'custom_branch_policies':False},'protection_rules':[]}
        if path=='/rulesets/10':return {'target':'push','enforcement':'active','rules':[
            {'type':'file_path_restriction','parameters':{'restricted_file_paths':['.github/**','.cloudopsworks/**']}}]}
        return super().repo(method,path,**kwargs)

    def pages(self,path):
        if path=='/rulesets':return [{'id':10,'name':'protected-sources'}]
        raise AssertionError(path)

    def request(self,method,path,data=None):
        if path.startswith('/repos/cloudopsworks/blueprints/'):
            return {'object':{'type':'commit','sha':self.bp}}
        if path=='/graphql':
            guard={'requiresApprovingReviews':True,'requiredApprovingReviewCount':1,'requiredStatusCheckContexts':['checkpr / Check Pull Request'],
                'isAdminEnforced':True,'dismissesStaleReviews':True,'requiresStatusChecks':True,'requiresStrictStatusChecks':True,
                'allowsForcePushes':False,'bypassPullRequestAllowances':{'totalCount':0,'pageInfo':{'hasNextPage':False},'nodes':[]},
                'bypassForcePushAllowances':{'totalCount':0,'pageInfo':{'hasNextPage':False},'nodes':[]}}
            return {'data':{'repository':{'ref':{'branchProtectionRule':guard},
                'branchProtectionRules':{'totalCount':1,'pageInfo':{'hasNextPage':False},'nodes':[{'pattern':'develop',**guard}]}}}}
        raise AssertionError(path)


@unittest.skipUnless(BINARY,'set TRONADOR_TEST_BINARY to the reviewed Go binary')
class HostIntegrationTests(unittest.TestCase):
    def test_actual_api_snapshot_go_stage_and_scan_prepare(self):
        api=HostAPI()
        prepared=auth.prepare_verified_context(api,api.run,blueprint_sha=api.bp,executor=Process(),engine=None,current_host=api.host)
        self.assertEqual(prepared.stage['runId'],'100')
        self.assertEqual(prepared.current_host['runId'],'200')
        self.assertEqual(len(prepared.scan_results),15)

    def test_host_source_caller_attempt_scan_and_native_protection_fail_closed(self):
        for mode in ('source','caller','attempt','scanner','protection'):
            api=HostAPI();api.fail_mode=mode
            with self.subTest(mode=mode),self.assertRaises((ContractError,ValueError,RuntimeError)):
                auth.prepare_verified_context(api,api.run,blueprint_sha=api.bp,executor=Process(),engine=None,current_host=api.host)


class RecoveryAPI(HostAPI):
    bind_target=True
    def __init__(self):
        self.recovery=False
        super().__init__()
        self.records=[];self.state_log=b'';self.recovery=False
    def expire_and_remove_current_component(self):
        self.recovery=True
        current=TemplateAPI()
        self.current_entries=copy.deepcopy(current.entries)
        self.current_blobs=copy.deepcopy(current.blobs)
        entry=next(e for e in self.current_entries if e['path']=='.cloudopsworks/cloudopsworks-ci.yaml')
        data=base64.b64decode(self.current_blobs[entry['sha']]['content'])
        start=data.index(b'  api:\n',data.index(b'components:\n'))
        end=data.index(b'  web:\n',start)
        data=data[:start]+data[end:]
        sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        entry.update(sha=sha,size=len(data))
        self.current_blobs[sha]={'sha':sha,'encoding':'base64','size':len(data),'content':base64.b64encode(data).decode()}

    def pages(self,path):
        if path=='/deployments?task=cloudopsworks-state':return copy.deepcopy(self.records)
        if path.endswith('/statuses'):return []
        if path=='/actions/runs/200/attempts/1/jobs':
            return [{'id':302,'run_id':200,'run_attempt':1,'name':'lifecycle / monorepo-apply-dev-run-api',
                     'status':'completed','conclusion':'failure'}]
        return super().pages(path)
    def repo(self,method,path,value=None,**kwargs):
        if path=='/deployments' and method=='POST':
            entry={**copy.deepcopy(value),'id':900,'creator':{'id':42}}
            self.records.append(entry);return entry
        if path=='/deployments/900':return copy.deepcopy(self.records[0])
        if path=='/actions/jobs/302/logs':return self.state_log
        if path.startswith('/actions/artifacts/') and self.recovery:
            raise AssertionError('expired source artifact must not be fetched')
        if self.recovery and path=='/git/commits/'+'c'*40:return {'sha':'c'*40,'tree':{'sha':'d'*40}}
        if self.recovery and path=='/git/trees/'+'d'*40+'?recursive=1':
            return {'sha':'d'*40,'truncated':False,'tree':self.current_entries}
        if self.recovery and path.startswith('/git/blobs/') and path.rsplit('/',1)[1] in self.current_blobs:
            return self.current_blobs[path.rsplit('/',1)[1]]
        if self.recovery and path.startswith('/branches/'):
            return {'protected':True,'commit':{'sha':'c'*40}}
        if self.recovery and path.startswith('/compare/'+'c'*40):
            return {'status':'identical','merge_base_commit':{'sha':'c'*40}}
        if path in ('/actions/runs/201/attempts/1','/actions/runs/202/attempts/1'):
            run=copy.deepcopy(self.run);run.update(id=int(path.split('/')[3]),event='workflow_dispatch',head_sha='c'*40,
                path='.github/workflows/environment-'+('unlock.yml' if '/202/' in path else 'destroy.yml'),referenced_workflows=[{
                'path':'cloudopsworks/blueprints/.github/workflows/monorepo-operation.yml@v5.11.0','sha':self.bp}])
            return run
        return super().repo(method,path,value,**kwargs)


@unittest.skipUnless(BINARY,'set TRONADOR_TEST_BINARY to the reviewed Go binary')
class HistoricalIntegrationTests(unittest.TestCase):
    def test_actual_api_go_fresh_reservation_then_expired_stage_destroy(self):
        from iac import IaCExecutor
        from deploy import prepare
        api=RecoveryAPI()
        engine=IaCExecutor(ROOT,json.loads((ROOT/'terraform/monorepo/module-catalog.json').read_text()))
        prepared=auth.prepare_verified_context(api,api.run,blueprint_sha=api.bp,executor=Process(),engine=engine,current_host=api.host)
        settings={'auth':"gcp-dev:\n  provider: gcp\n  project: example-dev\n  serviceAccount: api@example-dev.iam.gserviceaccount.com\n  workloadIdentityProvider: projects/123/locations/global/workloadIdentityPools/pool/providers/provider\n",
                  'identities':'gcp-dev: "123456789012"\n','registries':'{}','probe-secrets':'{}','host-keys':'{}'}
        backend=(FIXTURES/'backend-native-s3.yaml').read_text()+'  auth_ref: aws-state\n'
        pair={'workload':captured('gcp','123456789012','api'), 'backend':captured('aws','222222222222','state')}
        pair['workload']['binding']['workloadIdentityProvider']='projects/123/locations/global/workloadIdentityPools/pool/providers/provider'
        settings['auth']+='aws-state:\n  provider: aws\n  roleArn: arn:aws:iam::222222222222:role/state\n  region: us-east-1\n'
        settings['identities']+='aws-state: "222222222222"\n'
        selected=prepared.select_bindings('dev-run','api',backend,settings,automation_id=42)
        self.assertEqual(selected['workload'],{'provider':'gcp','authRef':'gcp-dev'})
        self.assertEqual(selected['backend']['authRef'],'aws-state')
        self.assertIsNone(selected['historicalHandle'])
        prepared.bind(backend,settings,pair,automation_id=42,on_readback=lambda line:setattr(api,'state_log',line.encode()))
        component=next(c for c in prepared.manifest['components'] if c['componentId']=='api')
        target=next(t for t in prepared.plan['targets'] if t['id']=='dev-run')
        from deploy import request_for,effective_digest
        request=request_for(prepared.manifest,component,target)
        resolved={'providerIdentity':'123456789012','resourceClaims':['gcp:123456789012:run:api'],
            'existing':{'providerIdentity':'123456789012','exists':False,'ownerDigest':None}}
        request['target']['configDigest']=effective_digest(target,component['workload'],resolved)
        request['idempotencyKey']=digest({'repositoryId':prepared.repository['id'],'targetId':'dev-run',
            'componentId':'api','artifactDigest':request['artifact']['digest'],'targetConfigDigest':request['target']['configDigest']})
        context=prepared.authorize(request,resolved)
        handle=context['plan']['stateHandle']
        prepared.store.reserve(handle,context['resourceClaims'])
        self.assertEqual(len(api.records),1)
        api.expire_and_remove_current_component()
        host={**api.host,'runId':'201','event':'workflow_dispatch','headSha':'c'*40,
              'workflowRef':api.repository+'/.github/workflows/environment-destroy.yml@refs/heads/develop'}
        recovered=auth.prepare_recovery_context(api,handle,operation='destroy',blueprint_sha=api.bp,
                    executor=Process(),engine=engine,current_host=host)
        # Pre-acquisition selection must authenticate history BEFORE parsing
        # current YAML or acquiring the backend principal.
        selected=recovered.select_bindings('dev-run','api','INVALID: [YAML',settings,automation_id=42)
        self.assertEqual(selected['historicalHandle'],handle)
        self.assertEqual(selected['backend']['settings']['bucket'],'state-example')
        self.assertEqual(selected['backend']['authRef'],'aws-state')
        # Even a changed current backend cannot redirect recovery's native state.
        recovered.bind(backend.replace('state-example','changed-current-backend'),settings,pair,automation_id=42,on_readback=lambda _:None)
        result=recovered.recover(handle,operation='destroy',confirmation='destroy develop/dev/dev-run/api')
        self.assertEqual(result['plan']['stateHandle'],handle)
        self.assertEqual(result['plan']['invocation']['runId'],'201')
        self.assertNotIn('api',[c['id'] for c in recovered.resolved['components']])
        self.assertEqual(recovered.resolved['targets'],[])
        unlock_host={**host,'runId':'202','workflowRef':host['workflowRef'].replace('environment-destroy','environment-unlock')}
        unlocked=auth.prepare_recovery_context(api,handle,operation='unlock',blueprint_sha=api.bp,
                    executor=Process(),engine=engine,current_host=unlock_host).bind(backend,settings,pair,automation_id=42)
        unlock=unlocked.recover(handle,operation='unlock',lock_id='exact-native-lock',
            confirmation='unlock develop/dev/dev-run/api exact-native-lock')
        self.assertEqual(unlock['plan']['stateHandle'],handle)
        self.assertEqual(unlock['plan']['lockId'],'exact-native-lock')
        with self.assertRaises(ContractError):
            recovered.recover(handle,operation='destroy',confirmation='destroy prod/dev-run/api')
        wrong_settings={**settings,'identities':'gcp-dev: "999999999999"\n'}
        wrong_auth=auth.prepare_recovery_context(api,handle,operation='destroy',blueprint_sha=api.bp,
                    executor=Process(),engine=engine,current_host=host).bind(backend,wrong_settings,pair,automation_id=42)
        with self.assertRaises(ContractError):
            wrong_auth.recover(handle,operation='destroy',confirmation='destroy develop/dev/dev-run/api')
        with self.assertRaises(ContractError):
            recovered.recover(handle,operation='unlock',lock_id='wrong-operation',
                confirmation='unlock develop/dev/dev-run/api wrong-operation')
        # A self-consistent but independently different historical API YAML must
        # regenerate a different COMPLETE handle and cannot be blessed by bot ID.
        entry=next(e for e in api.entries if e['path']=='.cloudopsworks/vars/inputs-dev.yaml')
        data=base64.b64decode(api.blobs[entry['sha']]['content']).replace(b'service: api\n',b'service: foreign\n')
        sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        entry.update(sha=sha,size=len(data))
        api.blobs[sha]={'sha':sha,'encoding':'base64','size':len(data),'content':base64.b64encode(data).decode()}
        with self.assertRaises(ContractError):
            auth.prepare_recovery_context(api,handle,operation='destroy',blueprint_sha=api.bp,
                    executor=Process(),engine=engine,current_host=host)



if __name__=='__main__':unittest.main()
