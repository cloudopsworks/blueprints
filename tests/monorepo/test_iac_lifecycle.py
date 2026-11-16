"""Actual sole-Go operation -> pinned root renderer -> saved apply -> native probe.

Host/cloud APIs and processes are injected; no credentialed activation claim.
Catalog activation below is a TEST-ONLY copy, never the shipped blocked catalog.
"""
import copy
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
import hashlib

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from contracts import digest
from iac import IaCExecutor
from iac_deploy import apply
from operations import StateHandleStore
from providers import common,gcp
from test_operations import FakeGitHub
from test_providers import request,Fake


class Process(Fake):
    def run(self,argv,**kw):
        if argv[0] not in ('tofu','terragrunt'):return super().run(argv,**kw)
        self.calls.append((argv,kw));value={};code=0
        if argv[1:]==['version','-json']:value={'terraform_version':'1.11.4'}
        elif argv[1:]==['--version']:return subprocess.CompletedProcess(argv,0,'terragrunt version v0.99.4','')
        elif 'pull' in argv:
            kind,name=getattr(self,'address','google_cloud_run_v2_service.component').split('.',1)
            instance={}
            if '[' in name:
                name,index=name.split('[',1);instance['index_key']=json.loads(index[:-1])
            value={'version':4,'resources':[{'mode':'managed','type':kind,'name':name,'instances':[instance]}]}
        elif 'plan' in argv:code=2
        elif 'show' in argv:value={'resource_changes':[{'mode':'managed','address':getattr(self,'address','google_cloud_run_v2_service.component'),'change':{'actions':['update'],'before':{},'after':{}}}]}
        elif 'output' in argv:
            t=self.r['target'];default={'service':f'projects/{t.get("project")}/locations/{t.get("region",t.get("location"))}/services/{t.get("service")}'}
            value={'owned':{'sensitive':False,'value':getattr(self,'owned',default)}}
        return subprocess.CompletedProcess(argv,code,json.dumps(value),'')
    def response(self,argv):
        if getattr(self,'kube_owner',None):
            t=self.r['target'];name=self.r['componentId']
            annotations={'meta.helm.sh/release-name':name,'meta.helm.sh/release-namespace':t['namespace'],'deployment.kubernetes.io/revision':'1'}
            if argv[:2]==['helm','status']:return {'name':name,'namespace':t['namespace'],'info':{'status':'deployed','description':self.kube_owner}}
            if argv[:3]==['kubectl','get','deployment']:
                container={'image':self.r['artifact']['location']['reference'],'ports':[{'containerPort':self.r['workload']['port']}],
                    **{k:{'httpGet':{'path':self.r['workload']['healthPath']}} for k in ('startupProbe','readinessProbe','livenessProbe')}}
                return {'metadata':{'annotations':annotations},'spec':{'template':{'spec':{'containers':[container]}}}}
            if argv[:3]==['kubectl','get','service']:
                return {'metadata':{'name':name,'annotations':annotations},'spec':{'ports':[{'port':self.r['workload']['port']}],'selector':{'app.kubernetes.io/name':name}}}
        if argv[:4]==['gcloud','run','services','describe']:
            t=self.r['target']
            return {'metadata':{'generation':1,'name':t['service']},'status':{'conditions':[{'type':'Ready','status':'True'}],
                'observedGeneration':1,'latestReadyRevisionName':'api-configured','latestCreatedRevisionName':'api-configured',
                'traffic':[{'revisionName':'api-configured','percent':100}],'url':'https://api.run.app'},
                'spec':{'template':{'spec':{'containers':[{'image':self.r['artifact']['location']['reference']}]}}}}
        value=super().response(argv)
        if argv[:3]==['aws','lambda','get-function']:value['Configuration']['Runtime']=self.r['package']['runtime']
        if argv[:4]==['gcloud','api-gateway','gateways','describe']:value['apiConfig']=self.owned['config']
        return value


def fresh_context(context):
    context['backend']['authRef']='aws-state'
    context['backendIdentity']={'provider':'aws','accountId':'999999999999'}
    context['authRefs']=sorted(set(context['authRefs']+['aws-state']))
    return context


def captured_pair(context,**extra):
    provider=context['plan']['targets'][0]['provider'];identity={'provider':provider,
        {'aws':'accountId','gcp':'projectNumber','azure':'subscriptionId'}[provider]:context['providerIdentity']}
    if provider=='azure':identity['tenantId']='11111111-1111-1111-1111-111111111111'
    return {'workload':{'provider':provider,'identity':identity,'environment':extra},
        'backend':{'provider':'aws','identity':context['backendIdentity'],'environment':{
            'AWS_ACCESS_KEY_ID':'STATE-key','AWS_SECRET_ACCESS_KEY':'STATE-secret','AWS_SESSION_TOKEN':'STATE-session'}}}


class LifecycleTests(unittest.TestCase):
    def test_real_operation_saved_update_and_readiness_without_sdk_writer(self):
        binary=os.environ.get('TRONADOR_TEST_BINARY')
        self.assertTrue(binary and Path(binary).is_file(),'TRONADOR_TEST_BINARY must name trusted source-built test CLI')
        context=json.loads((Path(__file__).with_name('fixtures')/'operations/operation-context-frozen.json').read_text())
        catalog=json.loads((ROOT/'terraform/monorepo/module-catalog.json').read_text())
        row=catalog['modules']['gcp-cloudrun'];row['activationBlocked']=False # injected TEST catalog only
        context['origin']['moduleRevision']=row['revision'];context['origin']['providerLockDigest']=row['providerLockDigest']
        context['plan']['targets'][0]['ownership']='managed'
        fresh_context(context)
        command=[binary,'components','operations','plan','--operation','apply','--environment','prod','--target','prod-run','--component','api','--json']
        output=subprocess.run(command,input=json.dumps(context),text=True,capture_output=True)
        self.assertEqual(output.returncode,0,output.stderr)
        plan=json.loads(output.stdout)
        r=request('gcp.cloudrun');r.update(repository=context['origin']['repository'],componentId='api',target=context['plan']['targets'][0],workload=context['plan']['components'][0]['workload'])
        ex=Process(r);store=StateHandleStore(FakeGitHub(),r['repository'],42,verify_origin=lambda h,e:True)
        store.reserve(plan['stateHandle'],['//run.googleapis.com/fixture'])
        engine=IaCExecutor(ROOT,catalog,executor=ex)
        authorization={'plan':plan,'canonical':copy.deepcopy(plan),'store':store,'resourceClaims':['//run.googleapis.com/fixture'],
            'existing':{'providerIdentity':context['providerIdentity'],'exists':True,'ownerDigest':digest(plan['stateHandle'])},'credentials':captured_pair(context),'engine':engine}
        with tempfile.TemporaryDirectory() as directory:
            local={'workDir':Path(directory),'expectedIdentity':context['providerIdentity'],'iac_authorize':lambda req,res:authorization,
                'http':lambda *a,**k:(200,b'ok'),'overallDeadline':float('inf')}
            # Probe requires GCP identity token; protected command is read-only.
            local['secrets']={}
            old=gcp.cli
            try:
                def cli(executor,target,*args,**kwargs):
                    return old(executor,target,*args,**kwargs)
                url=apply(r,ex,{'providerIdentity':context['providerIdentity'],'resource':{}},local,None,None,r['artifact']['location']['reference'])
            finally:gcp.cli=old
        self.assertEqual(url,'https://api.run.app')
        self.assertTrue(any(a[-3:]==['apply','-input=false','operation.tfplan'] for a,_ in ex.calls))
        self.assertFalse(any(a[:3]==['gcloud','run','deploy'] for a,_ in ex.calls))
        # Old positive SDK matrix is not execution authority for new entrypoints.
        self.assertEqual(len(store.github.records),1)

    def test_actual_frozen_operations_lambda_zip_static_and_api_saved_updates(self):
        binary=os.environ.get('TRONADOR_TEST_BINARY')
        self.assertTrue(binary and Path(binary).is_file())
        for kind,module_id,address in [('aws.lambda','aws-lambda','aws_lambda_function.component'),
                ('gcp.storage-static','gcp-storage-static','google_storage_bucket_object.files["index.html"]'),
                ('gcp.apigateway','gcp-apigateway','google_api_gateway_gateway.component')]:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                context=json.loads((Path(__file__).with_name('fixtures')/'operations/operation-context-frozen.json').read_text())
                catalog=json.loads((ROOT/'terraform/monorepo/module-catalog.json').read_text());row=catalog['modules'][module_id]
                row['activationBlocked']=False # TEST-only catalog, no production bypass.
                context['origin'].update(moduleRevision=row['revision'],providerLockDigest=row['providerLockDigest'])
                r=request(kind);target=r['target'];target.update(id='prod-run',ownership='managed',authRef='gcp-prod')
                if kind=='aws.lambda':
                    r['package']['runtime']='python3.12'
                    target.update(runtime='python3.12',iac={'roleArn':'arn:aws:iam::123456789012:role/runtime','sourceBucket':'source-bucket','sourcePrefix':'artifacts'})
                if kind=='gcp.apigateway':target.update(apiName='api',apiVersion='v1')
                component=context['plan']['components'][0];component.update(package=r['package'],workload=r['workload'])
                component['preview']={'mode':'artifact-only','reason':'openapi'} if kind=='gcp.apigateway' else {'mode':'container','source':'dockerfile','dockerfile':'Dockerfile','context':'.','port':8080,'healthPath':'/health'}
                if kind=='aws.lambda':component['preview'].update(source='function',adapter='aws-lambda-rie',entryPoint='handler',invokePath='/invoke',invokeTest={'requestBody':'{}','expectedStatus':200,'responseContains':'ready'})
                context['plan']['targets']=[target]
                fresh_context(context)
                result=subprocess.run([binary,'components','operations','plan','--operation','apply','--environment','prod','--target','prod-run','--component','api','--json'],input=json.dumps(context),text=True,capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr);plan=json.loads(result.stdout)
                r['repository']=context['origin']['repository']
                payload=root/'payload.zip'
                if kind=='gcp.apigateway':payload.write_text(json.dumps({'openapi':'3.0.3','info':{'title':'API','version':'1.0.0'},'paths':{'/ready':{'get':{'responses':{'200':{'description':'ok'}}}}}}))
                else:
                    with zipfile.ZipFile(payload,'w') as z:z.writestr('index.html' if kind=='gcp.storage-static' else 'handler.py','ready')
                r['artifact'].update(digest='sha256:'+hashlib.sha256(payload.read_bytes()).hexdigest(),sizeBytes=payload.stat().st_size)
                ex=Process(r);ex.address=address
                if kind=='aws.lambda':ex.owned={'function_arn':'arn:aws:lambda:us-east-1:123456789012:function:handler','version':'7'}
                elif kind=='gcp.storage-static':ex.owned={'objects':['bucket/site/index.html','bucket/site/.cloudopsworks-release.json']}
                else:
                    prefix='projects/project/locations/'
                    ex.owned={'api':prefix+'global/apis/api','config':prefix+'global/apis/api/configs/exact-config','gateway':prefix+'us-central1/gateways/gateway'}
                store=StateHandleStore(FakeGitHub(),r['repository'],42,verify_origin=lambda h,e:True)
                store.reserve(plan['stateHandle'],['fixture:'+module_id]);engine=IaCExecutor(ROOT,catalog,executor=ex)
                auth={'plan':plan,'canonical':copy.deepcopy(plan),'store':store,'resourceClaims':['fixture:'+module_id],
                    'existing':{'providerIdentity':context['providerIdentity'],'exists':True,'ownerDigest':digest(plan['stateHandle'])},'credentials':captured_pair(context),'engine':engine}
                def http(url,**kw):return 200,common.marker(r) if url.endswith('.cloudopsworks-release.json') else b'ready'
                local={'workDir':root,'expectedIdentity':context['providerIdentity'],'iac_authorize':lambda req,res:auth,'http':http,'overallDeadline':float('inf')}
                directory_path=None
                if kind=='gcp.storage-static':
                    directory_path=root/'static';directory_path.mkdir();(directory_path/'index.html').write_text('ready')
                apply(r,ex,{'providerIdentity':context['providerIdentity'],'resource':{}},local,payload,directory_path,None)
                self.assertTrue(any(a[-3:]==['apply','-input=false','operation.tfplan'] for a,_ in ex.calls))
                self.assertFalse(any(a[:3] in (['aws','lambda','update-function-code'],['gcloud','storage','rsync']) for a,_ in ex.calls))

    def test_three_kubernetes_families_use_pinned_authoritative_chart_saved_apply(self):
        binary=os.environ.get('TRONADOR_TEST_BINARY');self.assertTrue(binary and Path(binary).is_file())
        for kind,module_id in [('aws.eks','aws-eks'),('gcp.gke','gcp-gke'),('azure.aks','azure-aks')]:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);context=json.loads((Path(__file__).with_name('fixtures')/'operations/operation-context-frozen.json').read_text())
                catalog=json.loads((ROOT/'terraform/monorepo/module-catalog.json').read_text());row=catalog['modules'][module_id];row['activationBlocked']=False
                context['origin'].update(moduleRevision=row['revision'],providerLockDigest=row['providerLockDigest'])
                r=request(kind);r['repository']=context['origin']['repository'];r['target'].update(id='prod-run',ownership='managed',authRef='gcp-prod')
                context['plan']['targets']=[r['target']]
                context['plan']['components'][0].update(package=r['package'],workload=r['workload'])
                if kind=='azure.aks':context['providerIdentity']='sub'
                fresh_context(context)
                generated=subprocess.run([binary,'components','operations','plan','--operation','apply','--environment','prod','--target','prod-run','--component','api','--json'],input=json.dumps(context),text=True,capture_output=True)
                self.assertEqual(generated.returncode,0,generated.stderr);plan=json.loads(generated.stdout)
                ex=Process(r);ex.address='helm_release.component';ex.kube_owner=plan['stateHandleDigest']
                ex.owned={'release':'api','namespace':r['target']['namespace'],'owner_digest':ex.kube_owner}
                store=StateHandleStore(FakeGitHub(),r['repository'],42,verify_origin=lambda h,e:True);store.reserve(plan['stateHandle'],['fixture:'+module_id])
                kubeconfig=root/'kubeconfig';kubeconfig.write_text('mocked provider only')
                auth={'plan':plan,'canonical':copy.deepcopy(plan),'store':store,'resourceClaims':['fixture:'+module_id],
                    'existing':{'providerIdentity':context['providerIdentity'],'exists':True,'ownerDigest':ex.kube_owner},
                    'credentials':captured_pair(context,KUBECONFIG=str(kubeconfig)),'engine':IaCExecutor(ROOT,catalog,executor=ex)}
                @contextlib.contextmanager
                def forward(*args):yield 'http://127.0.0.1:12345'
                local={'workDir':root,'expectedIdentity':context['providerIdentity'],'iac_authorize':lambda req,res:auth,
                    'http':lambda *a,**k:(200,b'ready'),'forward':forward,'overallDeadline':float('inf')}
                self.assertIsNone(apply(r,ex,{'providerIdentity':context['providerIdentity'],'resource':{}},local,None,None,r['artifact']['location']['reference']))
                self.assertTrue(any(a[-3:]==['apply','-input=false','operation.tfplan'] for a,_ in ex.calls))
                self.assertFalse(any(a[:2]==['helm','upgrade'] for a,_ in ex.calls))
                self.assertEqual(row['chartPath'],'kubernetes/helm/charts')

if __name__=='__main__':unittest.main()
