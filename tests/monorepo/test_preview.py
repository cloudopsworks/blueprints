import diagnostic_support
import copy
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from contracts import ContractError, load_record, validate_record
from preview import (cleanup, concurrency_key, ensure_namespace, isolation_preflight,
    namespace, network_policy, owner, reconcile_preview, verify_run, PreviewStore, validate_metadata, _verify_component, IaCPreview)
from preview import reconcile_preview as real_reconcile
from test_release import MemoryGitHub, Publisher, fixture


def policy():
    return {'targetId':'prod-run','baseDomain':'preview.example.com','ingressClass':'nginx','isolation':{
        'mode':'gke-dataplane-v2','probeImage':'ghcr.io/example/probe@sha256:'+'a'*64,
        'controlNamespace':'isolation-control','controlEndpoint':{'host':'control.isolation-control.svc.cluster.local','port':8000},
        'metadataEndpoints':[{'host':'169.254.169.254','port':80},{'host':'metadata.google.internal','port':80}],
        'ingressNamespaceSelector':{'kubernetes.io/metadata.name':'ingress-nginx'},'ingressPodSelector':{'app':'ingress'},
        'dnsNamespaceSelector':{'kubernetes.io/metadata.name':'kube-system'},'dnsPodSelector':{'k8s-app':'kube-dns'}}}


def preview_plan():
    plan=fixture('build-plan')
    plan.update(event='pull-request',prNumber=42)
    old=plan['targets'][0]
    plan['targets']=[{k:v for k,v in old.items() if k in ('id','environment','provider','authRef','configDigest','readiness','project')}]
    plan['targets'][0].update(kind='gcp.gke',region='us-central1',location='us-central1',cluster='cluster',namespace='normal')
    plan['targets'][0]['readiness']['probe']['auth']={'kind':'none'}
    plan['previewPolicy']={'enabled':True,'targets':[policy()]}
    return validate_record(plan)


class GitHub:
    def __init__(self):
        self.pr={'number':42,'state':'open','base':{'repo':{'id':12345}},'head':{'sha':'a'*40,'repo':{'id':12345}}}
        self.run={'id':12,'run_attempt':1,'workflow_id':100,'event':'pull_request','status':'completed','conclusion':'success',
            'repository':{'id':12345},'head_repository':{'id':12345},'head_sha':'a'*40,'pull_requests':[{'number':42}]}
    def repo(self, method, path, data=None):
        return self.run if path.startswith('/actions/runs/') else copy.deepcopy(self.pr)


class Kube:
    def __init__(self):
        self.calls=[]
        self.ns=None
        self.reject=True
        self.egress_denied=True
    def run(self,argv,**kwargs):
        self.calls.append((argv,kwargs))
        args=argv[1:]
        value=''
        code=0
        stderr=''
        if args[:2]==['get','namespace']:
            value=json.dumps(self.ns) if self.ns else ''
        elif args[:2]==['get','daemonset']:
            value=json.dumps({'status':{'numberReady':2,'desiredNumberScheduled':2}})
        elif args[:2]==['create','--dry-run=server']:
            code=1 if self.reject else 0
            stderr='violates PodSecurity restricted: hostNetwork'
        elif args[:2]==['create','-f']:
            document=json.loads(kwargs['input'])
            if document['kind']=='Namespace':
                self.ns=copy.deepcopy(document)
                self.ns['metadata'].update(uid='uid-1',resourceVersion='7')
        elif args[:1]==['logs']:
            value='reachable\n'
        elif args[:1]==['exec']:
            value=json.dumps({'dns':True,'controlDenied':self.egress_denied,'metadataDenied':True})
        elif args[:2]==['get','pod']:
            value=json.dumps({'status':{'podIP':'10.0.0.8'}})
        elif args[:2]==['get','namespaces']:
            value=json.dumps({'items':[{'metadata':{'name':'ingress-nginx'}}]})
        return subprocess.CompletedProcess(argv,code,value,stderr)


class StateStore:
    def __init__(self):self.value=None
    def load(self):return copy.deepcopy(self.value)
    def save(self,state,artifacts,component_configs=None,artifact_sources=None):self.value=copy.deepcopy({'state':validate_record(state),'artifacts':artifacts,'componentConfigs':component_configs or {},'artifactSources':artifact_sources or {}})


class RecordingController(IaCPreview):
    def __init__(self):pass
    def environment(self,artifact,policy,workdir):return {'namespace':namespace('12345',42,'prod-run')}
    def _guard(self,**kwargs):pass
    def remove(self,ident):pass


def reconcile_preview(*args,**kwargs):
    context=dict(kwargs.get('context',{}),controller=RecordingController())
    kwargs['context']=context
    with patch('preview.isolation_preflight',return_value=fixture('preview-state')['isolation']):
        return real_reconcile(*args,**kwargs)


class PreviewTests(unittest.TestCase):
    def test_run_fork_stale_workflow_failure_and_closed_denied(self):
        gh=GitHub();repo=fixture('build-plan')['repository']
        verify_run(gh,12,100,repo)
        for mutate in [lambda:setattr(gh,'run',{**gh.run,'workflow_id':101}),
            lambda:setattr(gh,'run',{**gh.run,'head_repository':{'id':999}}),
            lambda:setattr(gh,'run',{**gh.run,'conclusion':'failure'}),
            lambda:gh.pr['head'].update(sha='b'*40),lambda:gh.pr.update(state='closed')]:
            gh=GitHub();mutate()
            with self.assertRaises(ContractError):verify_run(gh,12,100,repo)

    def test_closure_bundle_distinguishes_actual_host_head_from_verified_merge_source(self):
        import io,zipfile
        from preview import download_bundle
        plan=fixture('build-plan');plan.update(event='release',prNumber=None,headSha='b'*40,
            buildSelection=[],buildNoop=True,matrix={'include':[]})
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w') as z:z.writestr('monorepo-plan.json',json.dumps(plan))
        run={'id':12,'run_attempt':1,'head_sha':'a'*40,'repository':{'id':12345}}
        artifact={'id':9,'name':'monorepo-plan-12-1','expired':False,'workflow_run':{'id':12,'head_sha':'a'*40}}
        class API:
            def repo(self,method,path,**kwargs):
                return {'artifacts':[artifact]} if '/runs/' in path else archive.getvalue()
        with tempfile.TemporaryDirectory() as directory:
            accepted,_=download_bundle(API(),run,Path(directory),expected_event='release',expected_source_sha='b'*40)
            self.assertEqual(accepted['headSha'],'b'*40)
        with tempfile.TemporaryDirectory() as directory,self.assertRaises(ContractError):
            download_bundle(API(),run,Path(directory),expected_event='release')
        artifact['workflow_run']['head_sha']='b'*40
        with tempfile.TemporaryDirectory() as directory,self.assertRaises(ContractError):
            download_bundle(API(),run,Path(directory),expected_event='release',expected_source_sha='b'*40)

    def test_namespace_identity_and_foreign_no_adoption(self):
        self.assertNotEqual(namespace('12345',42,'prod-run'),namespace('99999',42,'prod-run'))
        self.assertLessEqual(len(namespace('12345',42,'a'*48)),48)
        self.assertEqual(concurrency_key('12345',42,'prod-run'),'monorepo-preview-12345-42-prod-run')
        ex=Kube();ex.ns={'metadata':{'labels':{}}}
        with self.assertRaises(ContractError):ensure_namespace(ex,'some',owner({'id':'12345'},42,'prod-run'))
        self.assertEqual(len(ex.calls),1)

    def test_isolation_without_native_owned_probes_cannot_mutate(self):
        ex=Kube()
        with self.assertRaises(ContractError):isolation_preflight(ex,'preview',policy(),'gcp')
        self.assertFalse(any(a[1] in ('apply','delete','label') or (a[1]=='create' and '--dry-run=server' not in a) for a,_ in ex.calls))

    def test_readonly_native_probe_pair_checks_uid_owner_connectivity(self):
        ns='preview';hd='sha256:'+'b'*64
        probes={key:{'id':parent+'/'+key,'name':key,'namespace':parent,'uid':key+'-uid'}
            for key,parent in [('canary',ns),('control','isolation-control'),('ingress','ingress-nginx')]}
        owned={'namespace':ns,'uid':'namespace-uid','owner_digest':hd,'ownedIds':{'namespace':ns,
            'policies':[ns+'/'+p for p in ('cloudopsworks-default-deny','cloudopsworks-same-namespace','cloudopsworks-dns','cloudopsworks-ingress')],
            'probes':probes}}
        class ReadOnly(Kube):
            wrong_uid=False
            def run(self,argv,**kwargs):
                if argv[1:3]==['get','networkpolicy']:
                    self.calls.append((argv,kwargs))
                    return subprocess.CompletedProcess(argv,0,json.dumps({'metadata':{'namespace':ns,'annotations':{'cloudopsworks.io/owner-digest':hd}}}),'')
                if argv[1:3]==['get','pod']:
                    self.calls.append((argv,kwargs));probe=probes[argv[3]]
                    return subprocess.CompletedProcess(argv,0,json.dumps({'metadata':{'uid':'replacement' if self.wrong_uid else probe['uid'],
                        'annotations':{'cloudopsworks.io/owner-digest':hd,'cloudopsworks.io/environment-uid':'namespace-uid'}},'status':{'podIP':'10.0.0.8'}}),'')
                if argv[1]=='exec' and argv[2] in ('control','ingress'):
                    self.calls.append((argv,kwargs));return subprocess.CompletedProcess(argv,0,'reachable','')
                return super().run(argv,**kwargs)
        ex=ReadOnly();proof=isolation_preflight(ex,ns,policy(),'gcp',resolution=owned)
        self.assertTrue(proof['metadataDenied'])
        self.assertFalse(any(a[1] in ('delete','apply','label') or (a[1]=='create' and '--dry-run=server' not in a) for a,_ in ex.calls))
        ex=ReadOnly();ex.wrong_uid=True
        with self.assertRaises(ContractError):isolation_preflight(ex,ns,policy(),'gcp',resolution=owned)
        self.assertFalse(any(a[1]=='exec' for a,_ in ex.calls))
        ex=ReadOnly();ex.egress_denied=False
        with self.assertRaises(ContractError):isolation_preflight(ex,ns,policy(),'gcp',resolution=owned)

    def test_missing_metadata_and_broad_selector_fail_closed(self):
        for broken in ('metadata','selector'):
            p=policy()
            if broken=='metadata':p['isolation']['metadataEndpoints']=[]
            else:p['isolation']['dnsNamespaceSelector']={}
            ex=Kube()
            with self.assertRaises(ContractError):isolation_preflight(ex,'preview',p,'gcp')
            self.assertFalse(ex.calls)

    def test_normal_namespace_unused_preview_owner_and_fresh_proof(self):
        plan=preview_plan();gh=GitHub();ex=Kube();store=StateStore();calls=[]
        proof=fixture('preview-state')['isolation']
        with tempfile.TemporaryDirectory() as directory:
            state=reconcile_preview(ex,gh,plan['repository'],42,gh.run,plan,plan,[fixture('component-result')],
                'prod-run',Publisher(),Path(directory),store,context={'isolation':lambda *a:proof,
                'deploy_component':lambda *a,**kw:calls.append(a)})
        self.assertEqual(state['phase'],'ready')
        self.assertNotEqual(state['namespace'],plan['targets'][0]['namespace'])
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][1],state['namespace'])
        self.assertEqual(store.value['state'],state)

    def test_target_override_and_stale_state_no_workload(self):
        trusted=preview_plan();plan=copy.deepcopy(trusted);plan['targets'][0]['cluster']='attacker'
        ex=Kube();gh=GitHub()
        with tempfile.TemporaryDirectory() as directory,self.assertRaises(ContractError):
            reconcile_preview(ex,gh,plan['repository'],42,gh.run,trusted,plan,[fixture('component-result')],
                'prod-run',Publisher(),Path(directory),StateStore())
        self.assertFalse(ex.calls)

    def test_partial_failure_retains_namespace_and_successful_component(self):
        plan=preview_plan()
        component=copy.deepcopy(plan['components'][0]);component.update(id='web',path='components/web')
        component['toolchains'][0]['components']=['web']
        plan['components'].append(component)
        plan['buildSelection'].append({'componentId':'web','reasons':['changed']})
        row=copy.deepcopy(plan['matrix']['include'][0]);row.update(componentId='web',closure=['web']);row['toolchains'][0]['components']=['web']
        plan['matrix']['include'].append(row)
        result=fixture('component-result');other=copy.deepcopy(result);other['componentId']='web'
        gh=GitHub();ex=Kube();store=StateStore()
        def deploy(ex,ns,component,*args,**kwargs):
            if component['id']=='web':raise RuntimeError('native failure')
        with tempfile.TemporaryDirectory() as directory,self.assertRaises(RuntimeError):
            reconcile_preview(ex,gh,plan['repository'],42,gh.run,plan,plan,[result,other],'prod-run',Publisher(),Path(directory),store,
                context={'isolation':lambda *a:fixture('preview-state')['isolation'],'deploy_component':deploy})
        self.assertEqual(store.value['state']['phase'],'failed')
        self.assertEqual([c['status'] for c in store.value['state']['components']],['ready','failed'])
        self.assertFalse(any(a[:3]==['kubectl','delete','namespace'] for a,_ in ex.calls))

    def test_preview_metadata_actor_status_readback_and_strict_configs(self):
        gh=MemoryGitHub();state=fixture('preview-state');repo=state['repository']
        state['namespace']=namespace(repo['id'],state['prNumber'],state['targetId'])
        artifact=fixture('component-result')['previewArtifact']
        artifact['location']={'kind':'oci','reference':'ghcr.io/example/api@'+artifact['digest']}
        state['components'][0]['desiredDigest']=artifact['digest'];state['components'][0]['successfulDigest']=artifact['digest']
        store=PreviewStore(gh,repo,state['prNumber'],state['targetId'],99)
        store.save(state,{'api':artifact},{'api':'sha256:'+'a'*64})
        self.assertEqual(store.load()['componentConfigs'],{'api':'sha256:'+'a'*64})
        payload=copy.deepcopy(store.load());payload['unexpected']=True
        with self.assertRaises(ContractError):validate_metadata(payload)
        payload=copy.deepcopy(store.load());payload['componentConfigs']['api']='not-digest'
        with self.assertRaises(ContractError):validate_metadata(payload)
        # A later API failure cannot be masked by an older success status.
        gh.statuses[1].append({'id':999,'creator':{'id':99},'state':'failure'})
        with self.assertRaises(ContractError):store.load()

    def test_unchanged_verification_is_owned_live_readiness_without_helm(self):
        component=preview_plan()['components'][0];artifact=fixture('component-result')['previewArtifact']
        artifact['location']={'kind':'oci','reference':'ghcr.io/example/api@'+artifact['digest']}
        class Live:
            def __init__(self):self.calls=[];self.owned=True
            def run(self,argv,**kwargs):
                self.calls.append(argv)
                deployment={'metadata':{'annotations':{'meta.helm.sh/release-name':'api' if self.owned else 'foreign',
                    'meta.helm.sh/release-namespace':'preview','deployment.kubernetes.io/revision':'3'}},
                    'spec':{'template':{'spec':{'automountServiceAccountToken':False,'containers':[{'image':artifact['location']['reference'],'ports':[{'containerPort':component['preview']['port']}]}]}}}}
                return subprocess.CompletedProcess(argv,0,json.dumps(deployment) if argv[1]=='get' else '', '')
        @contextmanager
        def forward(*args):yield 'http://127.0.0.1:4567'
        ex=Live();context={'forward':forward,'http':lambda *args,**kwargs:(200,'ok')}
        _verify_component(ex,'preview',component,artifact,policy(),Path('.'),context=context)
        self.assertTrue(any('rollout' in argv for argv in ex.calls))
        self.assertFalse(any(argv[0]=='helm' for argv in ex.calls))
        ex.owned=False
        with self.assertRaises(ContractError):_verify_component(ex,'preview',component,artifact,policy(),Path('.'),context=context)

    def test_incremental_preview_updates_only_changed_config_or_failed(self):
        plan=preview_plan()
        web=copy.deepcopy(plan['components'][0]);web.update(id='web',path='components/web')
        web['toolchains'][0]['components']=['web'];plan['components'].append(web)
        plan['buildSelection'].append({'componentId':'web','reasons':['changed']})
        row=copy.deepcopy(plan['matrix']['include'][0]);row.update(componentId='web',closure=['web']);row['toolchains'][0]['components']=['web'];plan['matrix']['include'].append(row)
        api=fixture('component-result');other=copy.deepcopy(api);other['componentId']='web'
        gh=GitHub();store=StateStore();ex=Kube();updated=[];verified=[];broken=set()
        def deploy(ex,ns,component,*args,**kwargs):
            updated.append(component['id'])
            if component['id'] in broken:raise RuntimeError('not ready')
        def verify(ex,ns,component,*args,**kwargs):verified.append(component['id'])
        context={'isolation':lambda *a:fixture('preview-state')['isolation'],'deploy_component':deploy,'verify_component':verify}
        with tempfile.TemporaryDirectory() as directory:
            def run(results):
                return reconcile_preview(ex,gh,plan['repository'],42,gh.run,plan,plan,results,'prod-run',Publisher(),Path(directory),store,context=context)
            run([api,other]);self.assertEqual(updated,['api','web'])
            plan['baseSha']=plan['headSha'];plan['buildSelection']=[{'componentId':'web','reasons':['changed']}];plan['matrix']['include']=[plan['matrix']['include'][1]]
            other['previewArtifact']['digest']='sha256:'+'b'*64
            updated.clear();run([other]);self.assertEqual(updated,['web']);self.assertEqual(verified,['api'])
            updated.clear();verified.clear();run([other]);self.assertEqual(updated,[]);self.assertEqual(verified,['api','web'])
            plan['components'][0]['preview']['healthPath']='/new-health'
            updated.clear();verified.clear();run([other]);self.assertEqual(updated,['api']);self.assertEqual(verified,['web'])
            plan['components'][0]['preview']['healthPath']='/failing';broken.add('api')
            with self.assertRaises(RuntimeError):run([other])
            self.assertEqual(store.value['state']['phase'],'failed')
            broken.clear();updated.clear();verified.clear();run([other])
            self.assertEqual(updated,['api']);self.assertEqual(verified,['web'])
            # Legacy envelopes have no trustworthy effective config proof: reconcile.
            store.value.pop('componentConfigs');updated.clear();run([other]);self.assertEqual(updated,['api','web'])

    def test_cleanup_without_protected_runtime_never_uses_raw_delete(self):
        gh=GitHub();gh.pr['state']='closed';ex=Kube();repo=fixture('build-plan')['repository']
        ex.ns={'metadata':{'labels':owner(repo,42,'prod-run'),'uid':'owned-uid'}}
        with self.assertRaises(ContractError):cleanup(ex,gh,repo,42,'prod-run',lambda _:None)
        self.assertFalse(ex.calls)


if __name__=='__main__':unittest.main()
