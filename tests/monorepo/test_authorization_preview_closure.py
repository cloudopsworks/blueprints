"""Actual API/snapshot/Go historical closure with private native recordings.

No source artifact, scan result, callback True, or fabricated principal attests
historical origin. Native mutation is recorded, not live/hosted/CNI evidence.
"""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"cd/monorepo/runtime"))
import authorization as auth
from contracts import ContractError,digest,load_record
from iac import IaCExecutor
from operations import validate_operation
from preview import IaCPreview
from preview_runtime import context
from snapshot import materialize_snapshot
from test_authorization import RecoveryAPI,Process,captured,ROOT,FIXTURES
from test_preview_runtime import native_state


class PreviewHistoryAPI(RecoveryAPI):
    def __init__(self):
        self.converted=False
        super().__init__()
        self.state_logs={};self.records=[];self.artifact_reads=0;self.closed=False;self.wrong_caller=False
        self.host.update(event='workflow_run',workflowRef=self.repository+'/.github/workflows/pr-build.yml@refs/heads/develop')
    def rewrite(self):
        self.converted=True
        for entry in self.entries:
            path=entry['path']
            if path not in ('.cloudopsworks/cloudopsworks-ci.yaml','.cloudopsworks/preview.yaml','.cloudopsworks/vars/inputs-dev.yaml'):continue
            data=base64.b64decode(self.blobs[entry['sha']]['content'])
            if path.endswith('cloudopsworks-ci.yaml'):
                data=data.replace(b'    develop:\n      env: dev\n',b'    develop:\n      env: dev\n    pull_request:\n      env: dev\n')
            elif path.endswith('inputs-dev.yaml'):
                data=b'''monorepo:
  targets:
    dev-run:
      provider: gcp
      kind: gcp.gke
      authRef: gcp-dev
      project: example-dev
      region: us-central1
      location: us-central1
      cluster: cluster
      namespace: normal
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
            kind: none
'''
            else:
                data=b'''enabled: true
targets:
- targetId: dev-run
  baseDomain: preview.example.com
  ingressClass: nginx
  isolation:
    mode: gke-dataplane-v2
    probeImage: ghcr.io/example/probe@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    controlNamespace: control
    controlEndpoint: {host: control.control.svc.cluster.local, port: 8000}
    metadataEndpoints:
    - {host: 169.254.169.254, port: 80}
    - {host: metadata.google.internal, port: 80}
    ingressNamespaceSelector: {role: ingress}
    ingressPodSelector: {app: ingress}
    dnsNamespaceSelector: {role: dns}
    dnsPodSelector: {app: dns}
'''
            sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            entry.update(sha=sha,size=len(data));self.blobs[sha]={'sha':sha,'size':len(data),'encoding':'base64','content':base64.b64encode(data).decode()}
    def repo(self,method,path,value=None,**kwargs):
        if path.startswith('/git/commits/') and not self.converted:self.rewrite()
        if path.startswith('/actions/artifacts/'):
            self.artifact_reads+=1
            raise AssertionError('standing closure must not read expired source artifacts')
        if path=='/pulls/42':
            return {'number':42,'state':'closed' if self.closed else 'open','base':{'ref':'develop','sha':'a'*40,'repo':{'id':12345}},
                'head':{'ref':'feature/test','sha':'f'*40 if self.closed else 'a'*40,'repo':{'id':12345}}}
        if path=='/deployments' and method=='POST':
            record={**copy.deepcopy(value),'id':900+len(self.records),'creator':{'id':42}}
            self.records.append(record);return record
        if path.startswith('/deployments/') and method=='GET':
            return copy.deepcopy(next(r for r in self.records if str(r['id'])==path.split('/')[2]))
        if path.startswith('/actions/jobs/') and path.endswith('/logs'):
            job=path.split('/')[3]
            if job=='300':return self.publisher_log
            if job in ('302','303'):return self.state_logs.get('' if job=='302' else 'api',b'')
        if path.startswith('/actions/runs/'):
            identity=int(path.split('/')[3])
            if 'jobs?' in path:
                return {'jobs':[{'id':300,'run_id':100,'run_attempt':1,'status':'completed','conclusion':'success','name':'ci / monorepo-stage-publisher'}]}
            run=copy.deepcopy(self.run);run['id']=identity
            event,caller,called=('pull_request','pr-build.yml','monorepo-pr-build.yml') if identity==100 else (
                ('workflow_run','pr-build.yml','monorepo-preview.yml') if identity==200 else ('pull_request_target','pr-close.yaml','monorepo-pr-close.yml'))
            if identity==201 and self.wrong_caller:caller='main-build.yml'
            run.update(event=event,path='.github/workflows/'+caller,
                referenced_workflows=[{'path':'cloudopsworks/blueprints/.github/workflows/'+called+'@v5.11.0','sha':self.bp}])
            if identity==100:run.update(head_repository={'id':12345},pull_requests=[{'number':42}])
            if identity in (200,201):
                run['referenced_workflows'] += [{'path':'cloudopsworks/blueprints/.github/workflows/'+name+'@v5.11.0','sha':self.bp} for name in ('monorepo-preview.yml','monorepo-preview-target.yml') if name!=called]
            return run
        return super().repo(method,path,value,**kwargs)
    def pages(self,path):
        if path=='/actions/runs/200/attempts/1/jobs':
            return [{'id':ident,'run_id':200,'run_attempt':1,'name':'preview / monorepo-preview-dev-run / '+('monorepo-preview-root-dev-run' if not component else 'monorepo-preview-component-dev-run-'+component),
                'status':'completed','conclusion':'failure'} for ident,component in ((302,''),(303,'api'))]
        if path.startswith('/deployments/') and path.endswith('/statuses'):return []
        return super().pages(path)


class Native:
    def __init__(self,handle):
        self.handle=handle;self.state=native_state(handle);self.ns=self.state['outputs']['owned']['value']['namespace'];self.uid='namespace-uid';self.calls=[]
    def run(self,argv,**kwargs):
        self.calls.append(argv)
        if 'projects' in argv:value={'projectId':'example-dev','projectNumber':'123456789012'}
        elif 'clusters' in argv:value={'name':'cluster','selfLink':'https://container.googleapis.com/v1/projects/example-dev/locations/us-central1/clusters/cluster','endpoint':'cluster.example','masterAuth':{'clusterCaCertificate':'ca'}}
        elif 'config' in argv:value={'current-context':'trusted','contexts':[{'name':'trusted','context':{'cluster':'cluster'}}],
            'clusters':[{'name':'cluster','cluster':{'server':'https://cluster.example','certificate-authority-data':'ca'}}]}
        elif argv[1:3]==['get','namespace']:
            value={'metadata':{'name':self.ns,'uid':self.uid,'labels':{'cloudopsworks.io/managed-by':'blueprints-monorepo',
                'cloudopsworks.io/repository-id':'12345','cloudopsworks.io/pr':'42','cloudopsworks.io/target-id':'dev-run'},
                'annotations':{'cloudopsworks.io/owner-digest':digest(self.handle)}}} if self.ns else None
        elif argv[1:3]==['get','pod']:
            probe=next(p for p in self.state.get('outputs',{}).get('owned',{}).get('value',{}).get('ownedIds',{}).get('probes',{}).values() if p['name']==argv[3])
            value={'metadata':{'name':probe['name'],'namespace':probe['namespace'],'uid':probe['uid'],
                'annotations':{'cloudopsworks.io/owner-digest':digest(self.handle),'cloudopsworks.io/environment-uid':'namespace-uid'}}}
        else:raise AssertionError(argv)
        return subprocess.CompletedProcess(argv,0,'' if value is None else json.dumps(value),'')


@unittest.skipUnless(os.environ.get('TRONADOR_TEST_BINARY'),'actual reviewed Go binary required')
class PreviewClosureIntegrationTests(unittest.TestCase):
    def setup_history(self,*,separate_backend=False):
        api=PreviewHistoryAPI();process=Process()
        catalog=json.loads((ROOT/'terraform/monorepo/module-catalog.json').read_text())
        # Test-only gate opening proves connected authorization; it is NOT
        # production root activation or credentialed provider evidence.
        for module in ('gcp-preview-environment','gcp-gke'):catalog['modules'][module]['activationBlocked']=False
        engine=IaCExecutor(ROOT,catalog)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();materialize_snapshot(api,'a'*40,root)
            resolved=auth._json_cli(process,['validate','--workdir',str(root),'--json'])['resolved']
            lifecycle=auth._json_cli(process,['lifecycle','--workdir',str(root),'--event','pull_request','--ref','refs/heads/feature/test','--base-ref','develop','--json'])
        plan=auth._metadata_plan(api.repo_id,'a'*40,resolved,pr_number=42)
        prepared=auth.PreparedAuthorization(api,process,engine,api.repo_id,api.stage,{},api.host,{},plan,{},resolved,lifecycle,[],False)
        prepared._source_context={'event':'pull_request','ref':'refs/heads/feature/test','baseRef':'develop','sourceSha':'a'*40,'prNumber':42}
        settings={'auth':'gcp-dev:\n  provider: gcp\n  project: example-dev\n  serviceAccount: api@example-dev.iam.gserviceaccount.com\n  workloadIdentityProvider: projects/123/locations/global/workloadIdentityPools/pool/providers/provider\naws-state:\n  provider: aws\n  roleArn: arn:aws:iam::222222222222:role/state\n  region: us-east-1\n',
            'identities':'gcp-dev: "123456789012"\naws-state: "222222222222"\n','registries':'{}','probe-secrets':'{}','host-keys':'{}'}
        backend=(FIXTURES/'backend-native-s3.yaml').read_text()+'  auth_ref: aws-state\n'
        pair={'workload':captured('gcp','123456789012','api'),'backend':captured('aws','222222222222','state')}
        pair['workload']['binding']['workloadIdentityProvider']='projects/123/locations/global/workloadIdentityPools/pool/providers/provider'
        if separate_backend:
            settings['auth']+='gcp-state:\n  provider: gcp\n  project: state-project\n  serviceAccount: state@state-project.iam.gserviceaccount.com\n  workloadIdentityProvider: projects/999/locations/global/workloadIdentityPools/pool/providers/provider\n'
            settings['identities']+='gcp-state: \"555555555555\"\n'
            api.child_backend='gcs:\n  bucket: child-state-example\n  auth_ref: gcp-state\n'
            api.child_pair={'workload':copy.deepcopy(pair['workload']),'backend':captured('gcp','555555555555','state',project='state-project')}
        prepared.bind(backend,settings,pair,automation_id=42,on_readback=lambda line:api.state_logs.__setitem__('api' if '"receiptId":"901"' in line else '',line.encode()))
        handles=[]
        for component in ('','api'):
            if component and separate_backend:
                fresh=auth.PreparedAuthorization(api,process,engine,api.repo_id,api.stage,{},api.host,{},plan,{},resolved,lifecycle,[],False)
                fresh._source_context=copy.deepcopy(prepared._source_context)
                fresh.bind(api.child_backend,settings,api.child_pair,automation_id=42,on_readback=lambda line:api.state_logs.__setitem__('api',line.encode()))
                prepared=fresh
            bound=prepared.authorize_preview('dev-run',component,{'providerIdentity':'123456789012','resourceClaims':['gcp:verified:'+('root' if not component else 'api')],
                'existing':{'providerIdentity':'123456789012','exists':False,'ownerDigest':None}})
            handle=bound['plan']['stateHandle'];prepared.store.reserve(handle,bound['resourceClaims']);handles.append(handle)
        api.open_context=(copy.deepcopy(plan),copy.deepcopy(resolved),copy.deepcopy(lifecycle),copy.deepcopy(prepared._source_context))
        api.closed=True
        host={**api.host,'runId':'201','event':'pull_request_target','workflowRef':api.repository+'/.github/workflows/pr-close.yaml@refs/heads/develop'}
        return api,process,engine,handles,settings,backend,pair,host

    def test_actual_api_go_expired_artifact_stale_head_standing_closure_and_runtime(self):
        api,process,engine,handles,settings,backend,pair,host=self.setup_history()
        prepared=auth.prepare_preview_closure(api,handles,'dev-run',42,blueprint_sha=api.bp,executor=process,engine=engine,current_host=host)
        prepared.bind(backend,settings,pair,automation_id=42)
        self.assertEqual(api.artifact_reads,0)
        native=Native(handles[0]);recorded=[]
        def execute(plan,**kwargs):
            validate_operation(plan,canonical=kwargs['canonical']);kwargs['before_apply']()
            recorded.append(copy.deepcopy(plan))
            if plan['stateHandle']['scope']=='preview-environment':native.ns=None;native.state={'version':4,'resources':[],'outputs':{}}
            return {'phase':'destroy'}
        engine.execute=execute
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);root.chmod(0o700);kube=root/'kubeconfig';kube.write_text('private');kube.chmod(0o600)
            with patch('preview_runtime.read_private_state',side_effect=lambda *a,**kw:copy.deepcopy(native.state)):
                runtime=context(prepared,native,target_id='dev-run',pr=42,workdir=root,credentials=pair,kubeconfig=kube)
                controller=IaCPreview(api,prepared.repository,42,'dev-run','f'*40,runtime)
                controller.close()
        self.assertEqual([p['stateHandle']['componentId'] for p in recorded],['api',None])
        self.assertEqual([p['stateHandle'] for p in recorded],[handles[1],handles[0]])
        self.assertTrue(all(p['invocation']['runId']=='201' for p in recorded))
        self.assertEqual(api.artifact_reads,0)
        self.assertFalse(any(argv[1] in ('create','apply','delete','label') for argv in native.calls))

    def test_actual_api_wrong_caller_reopened_and_forged_writer_denied(self):
        api,process,engine,handles,settings,backend,pair,host=self.setup_history()
        for mode in ('caller','reopened','marker'):
            api.wrong_caller=mode=='caller';api.closed=mode!='reopened'
            original=copy.deepcopy(api.state_logs)
            if mode=='marker':api.state_logs['']=b''
            with self.subTest(mode=mode),self.assertRaises(ContractError):
                auth.prepare_preview_closure(api,handles,'dev-run',42,blueprint_sha=api.bp,executor=process,engine=engine,current_host=host)
            api.state_logs=original
        self.assertEqual(api.artifact_reads,0)

    def test_actual_closure_factory_uid_swap_before_saved_apply_denies_all_writes(self):
        api,process,engine,handles,settings,backend,pair,host=self.setup_history()
        prepared=auth.prepare_preview_closure(api,handles,'dev-run',42,blueprint_sha=api.bp,executor=process,engine=engine,current_host=host)
        prepared.bind(backend,settings,pair,automation_id=42)
        native=Native(handles[0]);submitted=[]
        def execute(plan,**kwargs):
            validate_operation(plan,canonical=kwargs['canonical'])
            # Model a namespace recreation after plan, before savedapply. The
            # native backend still records its original UID; matching labels
            # and name do not authorize deleting the replacement namespace.
            native.uid='replacement-uid'
            kwargs['before_apply']()
            submitted.append(plan)
        engine.execute=execute
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);root.chmod(0o700);kube=root/'kubeconfig';kube.write_text('private');kube.chmod(0o600)
            with patch('preview_runtime.read_private_state',side_effect=lambda *a,**kw:copy.deepcopy(native.state)):
                runtime=context(prepared,native,target_id='dev-run',pr=42,workdir=root,credentials=pair,kubeconfig=kube)
                with self.assertRaises(ContractError):
                    IaCPreview(api,prepared.repository,42,'dev-run','f'*40,runtime).close()
        self.assertEqual(submitted,[])
        self.assertEqual(len(prepared.store.entries()),2)
        self.assertEqual(api.artifact_reads,0)

    def test_actual_isolation_failure_host_proof_only_not_generic_failed_job(self):
        # This fixture supplies the scan-gated source-context precondition; this
        # test exercises the additional independent isolation-failure host proof,
        # actual historical API/Go regeneration and canonical destroy, not a
        # claim to have executed scanners or hosted OIDC here.
        api,process,engine,handles,settings,backend,pair,_=self.setup_history()
        api.closed=False
        plan,resolved,lifecycle,source=api.open_context
        prepared=auth.PreparedAuthorization(api,process,engine,api.repo_id,api.stage,{},api.host,{},plan,{},resolved,lifecycle,[],False)
        prepared._source_context=source
        prepared.bind(backend,settings,pair,automation_id=42)
        root,child=handles
        marker={'repositoryId':api.repo_id['id'],'prNumber':42,'targetId':'dev-run','sourceSha':plan['headSha'],
            'namespace':root['resourceIdentity']['namespace'],'namespaceUid':'namespace-uid','stateHandleDigest':digest(root),
            'status':'isolation-failed','checks':[{'id':'isolation-network','status':'failed'}]}
        original=api.state_logs[''];pages=api.pages;repo=api.repo
        conclusion='failure';head='a'*40
        def jobs(path):
            value=pages(path)
            if path=='/actions/runs/200/attempts/1/jobs':
                for job in value:
                    if job['id']==302:job['conclusion']=conclusion
            return value
        def read(method,path,value=None,**kwargs):
            result=repo(method,path,value,**kwargs)
            if path=='/pulls/42':result['head']['sha']=head
            return result
        api.pages=jobs;api.repo=read
        def emit():api.state_logs['']=original+b'\nCLOUDOPSWORKS_PREVIEW_ISOLATION_V1 '+json.dumps(marker).encode()
        emit()
        for handle in handles:
            bound=prepared.failure_preview(handle,root_handle=root,namespace_uid='namespace-uid')
            self.assertEqual(bound['plan']['operation'],'destroy');self.assertEqual(bound['plan']['stateHandle'],handle)
        for mode in ('no-marker','healthy','uid','head','unknown-apply','forged-source'):
            saved=copy.deepcopy(marker)
            conclusion='success' if mode=='healthy' else 'failure';head='f'*40 if mode=='head' else 'a'*40
            if mode=='unknown-apply':marker['checks'][0]['id']='provider-timeout'
            if mode=='forged-source':marker['sourceSha']='f'*40
            emit()
            if mode=='no-marker':api.state_logs['']=original
            with self.subTest(mode=mode),self.assertRaises(ContractError):
                prepared.failure_preview(child,root_handle=root,namespace_uid='replacement' if mode=='uid' else 'namespace-uid')
            marker=saved
        self.assertEqual(api.artifact_reads,0)
