"""Complete successful native inventories distinguish absence from API failure."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from providers import preflight
from contracts import digest
from test_providers import request,Fake

KINDS=('aws.eks','aws.lambda','aws.beanstalk','aws.s3-static','aws.apigateway-rest',
'gcp.gke','gcp.cloudrun','gcp.appengine','gcp.functions-gen2','gcp.storage-static','gcp.apigateway',
'azure.aks','azure.containerapps','azure.appservice','azure.functions','azure.blob-static','azure.apim')

class Inventory(Fake):
    def __init__(self,r):super().__init__(r);self.list_failure=None;self.existing=None
    def run(self,argv,**kwargs):
        if self.list_failure:
            return SimpleNamespace(returncode=1,stdout='',stderr=self.list_failure)
        return super().run(argv,**kwargs)
    def response(self,a):
        t=self.r['target']
        if a[:3]==['aws','lambda','list-functions']:return {'Functions':[] if self.existing is None else [self.existing]}
        if a[:3]==['aws','elasticbeanstalk','describe-applications']:return {'Applications':[{'ApplicationName':t['application']}]}
        if a[:3]==['aws','elasticbeanstalk','describe-environments']:return {'Environments':[]}
        if a[:3]==['aws','apigateway','get-rest-apis']:return {'items':[]}
        if a[:3]==['aws','s3api','list-objects-v2']:return {'IsTruncated':False,'KeyCount':0}
        if a[0]=='gcloud' and 'list' in a:return []
        if a[0]=='az' and 'list' in a:return []
        if a[:3]==['kubectl','get','namespace']:return {'metadata':{'name':t['namespace']}}
        if a[:2]==['helm','list']:return []
        return super().response(a)

class NativePreflightTests(unittest.TestCase):
    def test_all17_complete_empty_workload_inventories_allow_explicit_managed_creation_only(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                r=request(kind);r['target']['ownership']='managed';ex=Inventory(r)
                result=preflight.resolve(r,ex,kubeconfig='/private/config')
                self.assertFalse(result['existing']['exists']);self.assertIsNone(result['existing']['ownerDigest'])
                self.assertTrue(result['resourceClaims'])
                self.assertFalse(any(word in argv for argv,kwargs in ex.calls for word in ('apply','create','delete','update','import')))
                r['target']['ownership']='external'
                with self.assertRaises(Exception):preflight.resolve(r,Inventory(r),kubeconfig='/private/config')
    def test_normal_kubernetes_rejects_preview_parent_before_release_inventory(self):
        for kind in ('aws.eks','gcp.gke','azure.aks'):
            for marker in ({'labels':{'cloudopsworks.io/pr':'17'}},
                           {'labels':{'cloudopsworks.io/managed-by':'blueprints-monorepo'}},
                           {'annotations':{'cloudopsworks.io/owner-digest':'sha256:'+'a'*64}}):
                with self.subTest(kind=kind,marker=marker):
                    r=request(kind);r['target']['ownership']='managed';ex=Inventory(r);original=ex.response
                    def response(argv):
                        if argv[:3]==['kubectl','get','namespace']:
                            return {'metadata':{'name':r['target']['namespace'],**marker}}
                        return original(argv)
                    ex.response=response
                    with self.assertRaisesRegex(Exception,'normal workloads cannot claim'):
                        preflight.resolve(r,ex,kubeconfig='/private/config')
                    self.assertFalse(any(a[:2]==['helm','list'] for a,_ in ex.calls))

    def test_existing_owned_and_foreign_private_native_ids_for_all17(self):
        primary={'aws.eks':'helm_release.component','gcp.gke':'helm_release.component','azure.aks':'helm_release.component',
            'aws.lambda':'aws_lambda_function.component','aws.beanstalk':'aws_elastic_beanstalk_environment.component','aws.s3-static':'aws_s3_object.files','aws.apigateway-rest':'aws_api_gateway_rest_api.component',
            'gcp.cloudrun':'google_cloud_run_v2_service.component','gcp.appengine':'google_app_engine_standard_app_version.component','gcp.functions-gen2':'google_cloudfunctions2_function.component','gcp.storage-static':'google_storage_bucket_object.files','gcp.apigateway':'google_api_gateway_gateway.component',
            'azure.containerapps':'azurerm_container_app.component','azure.appservice':'azurerm_linux_web_app.linux','azure.functions':'azurerm_linux_function_app.linux','azure.blob-static':'azurerm_storage_blob.static','azure.apim':'azurerm_api_management_api.component'}
        for kind in KINDS:
            with self.subTest(kind=kind):
                r=request(kind);t=r['target'];t['ownership']='managed';ex=Inventory(r)
                account=preflight.resolve(r,ex,kubeconfig='/private/config')['providerIdentity']
                h=json.loads((Path(__file__).parent/'fixtures/operations/state-handle.json').read_text())
                h.update(moduleId=kind.replace('.','-'),componentId=r['componentId'],targetId=t['id'],providerIdentity=account,ownership='managed')
                h['origin']['repository']=r['repository']
                h['backend']['authRef']='aws-state'
                h['backendIdentity']={'provider':'aws','accountId':'999999999999'}
                h['authRefs']=sorted(set(h['authRefs']+['aws-state']))
                schema=json.loads((ROOT/'cd/monorepo/runtime/schema/operations-v1.schema.json').read_text())
                variant=next(v for v in schema['$defs']['ResourceIdentity']['oneOf'] if v['properties']['kind']['const']==kind and set(v['required'])<=set(t))
                h['resourceIdentity']={k:v for k,v in t.items() if k in variant['properties']}
                owner=digest(h);old=ex.response
                native_id='owned-id';additional=[]
                def response(a):
                    nonlocal native_id,additional
                    if kind.endswith(('.eks','.gke','.aks')) and a[:2]==['helm','list']:
                        native_id=t['namespace']+'/'+r['componentId'];return [{'name':r['componentId'],'namespace':t['namespace']}]
                    if a[:3]==['aws','lambda','list-functions']:
                        native_id='arn:aws:lambda:'+t['region']+':'+account+':function:'+t['functionName'];return {'Functions':[{'FunctionName':t['functionName'],'FunctionArn':native_id}]}
                    if a[:3]==['aws','elasticbeanstalk','describe-environments']:
                        native_id='e-owned';return {'Environments':[{'EnvironmentId':native_id,'EnvironmentName':t['environmentName'],'ApplicationName':t['application'],'EnvironmentArn':'arn:aws:elasticbeanstalk:'+t['region']+':'+account+':environment/'+t['application']+'/'+t['environmentName']}]}
                    if a[:3]==['aws','apigateway','get-rest-apis']:
                        native_id=t['restApiId'];return {'items':[{'id':native_id,'name':'owned','tags':{'cloudopsworks-owner':owner}}]}
                    if a[:3]==['aws','s3api','list-objects-v2']:
                        native_id=t['prefix'].strip('/')+'/index.html';return {'IsTruncated':False,'KeyCount':1,'Contents':[{'Key':native_id}]}
                    if a[0]=='gcloud' and 'list' in a:
                        prefix='projects/'+t['project']+'/locations/'+t.get('region','')
                        if kind=='gcp.cloudrun':native_id=prefix+'/services/'+t['service'];return [{'metadata':{'name':t['service'],'labels':{'cloudopsworks-owner':owner[7:47]}}}]
                        if kind=='gcp.appengine':
                            native_id='apps/'+t['project']+'/services/'+t['service']+'/versions/owned';return [{'id':t['service']}] if 'services' in a else [{'id':'owned'}]
                        if kind=='gcp.functions-gen2':native_id=prefix+'/functions/'+t['functionName'];return [{'name':native_id,'labels':{'cloudopsworks-owner':owner[7:47]}}]
                        if kind=='gcp.storage-static':native_id=t['bucket']+'/'+t['prefix'].strip('/')+'/index.html';return [{'name':t['prefix'].strip('/')+'/index.html'}]
                        if kind=='gcp.apigateway':
                            native_id=prefix+'/gateways/'+t['gateway'];api='projects/'+t['project']+'/locations/global/apis/'+t['api'];additional=[{'mode':'managed','type':'google_api_gateway_api','name':'component','instances':[{'attributes':{'id':api}}]}]
                            return [{'name':api}] if 'apis' in a else [{'name':native_id}]
                    if a[0]=='az' and 'list' in a:
                        base='/subscriptions/'+account+'/resourcegroups/'+t['resourceGroup'].casefold()+'/providers/'
                        if kind=='azure.blob-static':native_id='https://'+t['account']+'.blob.core.windows.net/$web/'+t['prefix'].strip('/')+'/index.html';return [{'name':t['prefix'].strip('/')+'/index.html'}]
                        native_id=base+({'azure.containerapps':'microsoft.app/containerapps/'+t.get('appName',''),'azure.appservice':'microsoft.web/sites/'+t.get('appName',''),'azure.functions':'microsoft.web/sites/'+t.get('appName',''),'azure.apim':'microsoft.apimanagement/service/'+t.get('serviceName','')+'/apis/'+t.get('apiId','')}[kind]).casefold()
                        return [{'id':native_id,'tags':{'cloudopsworks-owner':owner}}]
                    return old(a)
                ex.response=response
                # First enumeration discovers exact immutable native IDs only;
                # absence of independently verified history must never adopt.
                with self.assertRaises(Exception):preflight.resolve(r,ex,kubeconfig='/private/config')
                resource_type,name=primary[kind].split('.',1)
                state={'version':4,'resources':[{'mode':'managed','type':resource_type,'name':name,'instances':[{'attributes':{'id':native_id}}]}]+additional}
                if kind=='gcp.appengine':
                    state['resources'][0]['instances'][0]['attributes'].update(project=t['project'],service=t['service'],delete_service_on_destroy=True,noop_on_destroy=False)
                result=preflight.resolve(r,ex,historical_handle=h,private_state=state,kubeconfig='/private/config')
                self.assertTrue(result['existing']['exists']);self.assertEqual(result['existing']['ownerDigest'],owner)
                state['resources'][0]['instances'][0]['attributes']['id']='foreign-native-id'
                with self.assertRaises(Exception):preflight.resolve(r,ex,historical_handle=h,private_state=state,kubeconfig='/private/config')

    def test_appengine_exclusive_history_foreign_versions_and_timeout_survivor(self):
        r=request('gcp.appengine');t=r['target'];t['ownership']='managed'
        ex=Inventory(r);account=preflight.resolve(r,ex)['providerIdentity']
        h=json.loads((Path(__file__).parent/'fixtures/operations/state-handle.json').read_text())
        h.update(moduleId='gcp-appengine',componentId=r['componentId'],targetId=t['id'],providerIdentity=account,ownership='managed')
        h['origin']['repository']=r['repository'];h['backend']['authRef']='aws-state'
        h['backendIdentity']={'provider':'aws','accountId':'999999999999'}
        h['authRefs']=sorted(set(h['authRefs']+['aws-state']))
        document=json.loads((ROOT/'cd/monorepo/runtime/schema/operations-v1.schema.json').read_text())
        variant=next(v for v in document['$defs']['ResourceIdentity']['oneOf'] if v['properties']['kind']['const']==t['kind'])
        h['resourceIdentity']={k:v for k,v in t.items() if k in variant['properties']}
        original=ex.response;versions=[{'id':'owned-v1'}]
        def response(argv):
            if argv[:4]==['gcloud','app','services','list']:return [{'id':t['service']}]
            if argv[:4]==['gcloud','app','versions','list']:return versions
            return original(argv)
        ex.response=response
        state={'version':4,'resources':[{'mode':'managed','type':'google_app_engine_standard_app_version','name':'component',
            'instances':[{'index_key':0,'attributes':{'id':'apps/'+t['project']+'/services/'+t['service']+'/versions/owned-v1',
                'project':t['project'],'service':t['service'],'delete_service_on_destroy':True,'noop_on_destroy':False}}]}]}
        result=preflight.resolve(r,ex,historical_handle=h,private_state=state)
        self.assertTrue(result['existing']['exists'])
        self.assertEqual(result['resourceClaims'],['//appengine.googleapis.com/apps/'+account+'/services/'+t['service']])
        for key,value in [('delete_service_on_destroy',False),('noop_on_destroy',True)]:
            wrong=copy.deepcopy(state);wrong['resources'][0]['instances'][0]['attributes'][key]=value
            with self.subTest(key=key),self.assertRaises(Exception):preflight.resolve(r,ex,historical_handle=h,private_state=wrong)
        versions.append({'id':'foreign-or-timeout-survivor'})
        with self.assertRaises(Exception):preflight.resolve(r,ex,historical_handle=h,private_state=state)
        versions.pop()
        # A creation timeout with a visible native service but no independently
        # verified private state is not auto-imported by name or owner labels.
        for handle,private in [(None,None),(h,None),(h,{'version':4,'resources':[]})]:
            with self.subTest(private=private),self.assertRaises(Exception):preflight.resolve(r,ex,historical_handle=handle,private_state=private)
        wrong=copy.deepcopy(state);wrong['resources'][0]['type']='google_app_engine_flexible_app_version'
        with self.assertRaises(Exception):preflight.resolve(r,ex,historical_handle=h,private_state=wrong)
        self.assertFalse(any(word in argv for argv,_ in ex.calls for word in ('apply','create','delete','update','import')))

    def test_permissions_404_text_and_malformed_inventory_never_become_absence(self):
        for kind in KINDS:
            r=request(kind);r['target']['ownership']='managed';ex=Inventory(r)
            for error in ('AccessDenied secret-sentinel','ResourceNotFoundException secret-sentinel','ERROR: (ResourceNotFound) secret-sentinel'):
                ex.list_failure=error
                with self.subTest(kind=kind,error=error),self.assertRaises(Exception) as caught:
                    preflight.resolve(r,ex,kubeconfig='/private/config')
                self.assertNotIn('sentinel',str(caught.exception))
        for value in ({},None,{'error':{'code':404}},'not found'):
            with self.assertRaises(Exception):preflight._items(value)
    def test_existing_full_or_truncated_owner_requires_exact_private_native_state(self):
        handle=json.loads((Path(__file__).parent/'fixtures/operations/state-handle.json').read_text())
        owner=digest(handle);native='projects/example/locations/us-central1/services/api'
        state={'version':4,'resources':[{'mode':'managed','type':'google_cloud_run_v2_service','name':'component','instances':[{'attributes':{'id':native}}]}]}
        for tag in (owner,owner[7:47]):
            self.assertEqual(preflight._owned(handle,state,{native},{'google_cloud_run_v2_service.component'},{'labels':{'cloudopsworks-owner':tag}}),owner)
        for bad_state,ids,tags in ((None,{native},{'cloudopsworks-owner':owner[7:47]}),
            (state,{'different-native-id'},{'cloudopsworks-owner':owner}),
            (state,{native},{'cloudopsworks-owner':'foreign-owner'})):
            with self.assertRaises(Exception):preflight._owned(handle,bad_state,ids,{'google_cloud_run_v2_service.component'},{'labels':tags})
    def test_malformed_items_and_page_tokens_do_not_prove_absence(self):
        for values in ([{}],[{'error':404}],[{'name':'wrong-shape-for-id'}]):
            with self.assertRaises(Exception):preflight._one(values,lambda item:False)
        with self.assertRaises(Exception):preflight._items({'items':[],'nextPageToken':'more'},'items')

    def test_truncated_static_inventory_is_not_fresh(self):
        r=request('aws.s3-static');r['target']['ownership']='managed';ex=Inventory(r);old=ex.response
        ex.response=lambda a: {'IsTruncated':True,'Contents':[]} if a[:3]==['aws','s3api','list-objects-v2'] else old(a)
        with self.assertRaises(Exception):preflight.resolve(r,ex)

if __name__=='__main__':unittest.main()
