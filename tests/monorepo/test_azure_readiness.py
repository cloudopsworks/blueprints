"""Actual Azure verifier invocation with process/HTTP doubles; never a cloud call."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'cd/monorepo/runtime'))
from providers import azure_readiness as readiness, common
from test_providers import request, IMAGE

OWNER = 'sha256:' + 'c' * 64
PAYLOAD = b'exact immutable native ZIP fixture'


class Process:
    def __init__(self, r, outputs):
        self.r = r; self.outputs = outputs; self.calls = []; self.change = None
        self.bad_bytes = False; self.bad_operation = False; self.completed = True
    def run(self, args, **kwargs):
        self.calls.append(args)
        value = self.response(args)
        if self.change:
            value = self.change(args, value)
        return SimpleNamespace(returncode=0, stdout=json.dumps(value), stderr='')
    def response(self, a):
        r = self.r; t = r['target']; site = readiness._arm(t, 'Microsoft.Web/sites', t.get('appName','unused'))
        if t.get('slot') != 'production' and t.get('slot'):
            site += '/slots/' + t['slot']
        family = a[1:3]
        if family in (['webapp','show'], ['functionapp','show']):
            live = dict(id=site, kind='functionapp,linux' if t['kind']=='azure.functions' else 'app,linux', state='Running', enabled=True, httpsOnly=True, reserved=t.get('os','linux')=='linux', serverFarmId=t['iac']['servicePlanId'], tags={'cloudopsworks-owner':OWNER}, identity={'type':'UserAssigned','userAssignedIdentities':{t['iac']['identityId']:{}}}, defaultHostName='app-staging.azurewebsites.net', enabledHostNames=['app-staging.azurewebsites.net'])
            if t.get('hostingPlan') == 'flex-consumption':
                live['functionAppConfig'] = dict(runtime={'name':t['workerRuntime'],'version':t['runtime']}, deployment={'storage':{'type':'blobContainer','value':'https://runtime.blob.core.windows.net/deployments','authentication':{'type':'UserAssignedIdentity','userAssignedIdentityResourceId':t['iac']['identityId']}}})
            return live
        if a[1:4] in (['webapp','config','show'], ['functionapp','config','show']):
            function = t['kind']=='azure.functions'; version=t.get('runtime','PYTHON|3.12')
            fx = 'DOCKER|'+IMAGE if t['packageMode']=='image' else (version if '|' in version else 'PYTHON|'+version)
            return dict(linuxFxVersion=fx, healthCheckPath=r['workload'].get('healthPath'), acrUseManagedIdentityCreds=True, netFrameworkVersion='v8.0', javaVersion='17')
        if a[1:4] in (['webapp','config','appsettings'], ['functionapp','config','appsettings']):
            return [{'name':'FUNCTIONS_WORKER_RUNTIME','value':t.get('workerRuntime','python')},{'name':'WEBSITE_RUN_FROM_PACKAGE','value':'1'},{'name':'WEBSITE_NODE_DEFAULT_VERSION','value':'20'},{'name':'AzureWebJobsStorage__credential','value':'managedidentity'},{'name':'FUNCTIONS_EXTENSION_VERSION','value':'~4'},{'name':'WEBSITES_PORT','value':str(r['workload'].get('port',3000))}]
        if a[1:4] == ['storage','blob','show']:
            return {'name':a[a.index('--name')+1],'properties':{'contentLength':len(PAYLOAD),'etag':'"immutable-etag"'}}
        if a[1:4] == ['storage','blob','download']:
            Path(a[a.index('--file')+1]).write_bytes(b'x'*len(PAYLOAD) if self.bad_bytes else PAYLOAD)
            return {}
        if a[1:4] == ['deployment','group','show']:
            return {'id':readiness._arm(t,'Microsoft.Resources/deployments',a[a.index('--name')+1]),'properties':{'provisioningState':'Succeeded'}}
        if a[1:5] == ['deployment','operation','group','list']:
            extension = 'onedeploy' if t.get('hostingPlan')=='flex-consumption' else 'ZipDeploy'
            return [{'properties':{'targetResource':{'id':site+'/extensions/'+extension},'provisioningState':'Failed' if self.bad_operation else 'Succeeded'}}]
        if a[1:3] == ['containerapp','show']:
            revision=t['appName']+'--v-'+r['artifact']['digest'][7:27]
            self.containers=[{'name':t['containerName'],'image':IMAGE,'probes':[{'type':kind,'httpGet':{'path':r['workload']['healthPath'],'port':r['workload']['port']}} for kind in ('Liveness','Readiness')]}]
            return {'id':self.outputs['owned_ids'][0],'tags':{'cloudopsworks-owner':OWNER},'identity':{'type':'UserAssigned','userAssignedIdentities':{t['iac']['identityId']:{}}},'properties':{'managedEnvironmentId':t['iac']['managedEnvironmentId'],'template':{'containers':self.containers},'configuration':{'activeRevisionsMode':'Single','ingress':{'external':True,'targetPort':r['workload']['port'],'traffic':[{'latestRevision':True,'weight':100}],'fqdn':t['appName']+'.environment.azurecontainerapps.io'}},'provisioningState':'Succeeded','latestRevisionName':revision,'latestReadyRevisionName':revision}}
        if a[1:4] == ['containerapp','revision','show']:
            return {'id':self.outputs['owned_ids'][0]+'/revisions/'+a[a.index('--revision')+1],'properties':{'active':True,'healthState':'Healthy','provisioningState':'Provisioned','trafficWeight':100,'template':{'containers':self.containers}}}
        if a[1:3] == ['resource','show']:
            return {'id':t['iac']['managedEnvironmentId'],'properties':{'defaultDomain':'environment.azurecontainerapps.io'}}
        if a[1:4] == ['storage','account','show']:
            return {'id':readiness._arm(t,'Microsoft.Storage/storageAccounts',t['account']),'primaryEndpoints':{'web':'https://'+t['account']+'.z1.web.core.windows.net/'}}
        if a[1:4] == ['apim','api','show']:
            return {'id':self.outputs['owned_ids'][0],'apiRevision':'1','isCurrent':True,'path':t['apiPath'],'protocols':['https'],'subscriptionRequired':False}
        if a[1:3] == ['apim','show']:
            return {'id':readiness._arm(t,'Microsoft.ApiManagement/service',t['serviceName']),'gatewayUrl':'https://'+t['serviceName']+'.azure-api.net'}
        if a[1:4] == ['monitor','app-insights','query']:
            # Parse the exact verifier-generated query: simulated structured log,
            # not a transport success or arbitrary marker substring.
            query=a[a.index('--analytics-query')+1]
            import re
            pairs=re.findall(r'tostring\(customDimensions\.([A-Za-z_]+)\) == ("(?:[^"\\]|\\.)*")',query)
            return {'tables':[{'columns':[{'name':key} for key,_ in pairs],'rows':[[json.loads(value) for _,value in pairs]] if self.completed else []}]}
        raise AssertionError('Unexpected command family: '+str(a[:5]))


class AzureReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.work=Path(self.temporary.name); self.time=0
    def fixture(self, kind, *, mode='zip', slot='production', os='linux', flex=False):
        r=request(kind);t=r['target'];t['subscriptionId']='sub';t['resourceGroup']='rg'
        t['iac']={'servicePlanId':'/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Web/serverfarms/plan','identityId':'/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/identity','managedEnvironmentId':'/subscriptions/sub/resourceGroups/rg/providers/Microsoft.App/managedEnvironments/env','storageAccountId':'/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/runtime','deploymentContainer':'deployments','packageStorage':{'accountId':'/subscriptions/sub/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/packages','container':'packages','prefix':'app'}}
        if kind in ('azure.appservice','azure.functions'):
            t.update(packageMode=mode,slot=slot,os=os,runtime='3.12' if kind=='azure.functions' else 'PYTHON|3.12')
            if kind=='azure.functions':t.update(workerRuntime='python',hostingPlan='flex-consumption' if flex else 'premium')
            site=readiness._arm(t,'Microsoft.Web/sites',t['appName'])+('' if slot=='production' else '/slots/'+slot)
            ids=[site]
            if mode=='zip':
                r['artifact'].update(digest='sha256:'+hashlib.sha256(PAYLOAD).hexdigest(),sizeBytes=len(PAYLOAD),format='zip')
                parent=site.split('/slots/')[0];digest=r['artifact']['digest'][7:]
                name='cow-'+hashlib.sha256((parent+'/'+slot).encode()).hexdigest()[:16]+'-'+digest[:24]
                ids += ['https://packages.blob.core.windows.net/packages/app/'+digest+('/released-package.zip' if flex else '/main.zip'),readiness._arm(t,'Microsoft.Resources/deployments',name)]
            else:r['artifact'].update(format='oci',digest=IMAGE.split('@')[1])
        elif kind=='azure.containerapps':
            ids=[readiness._arm(t,'Microsoft.App/containerApps',t['appName'])]
        elif kind=='azure.apim':
            ids=[readiness._arm(t,'Microsoft.ApiManagement/service',t['serviceName'])+'/apis/'+t['apiId']+';rev=1']
        else:
            t['account']='storage';t['prefix']='site';self.directory=self.work/'static';self.directory.mkdir(exist_ok=True);(self.directory/'index.html').write_bytes(b'index bytes')
            ids=['https://storage.blob.core.windows.net/$web/site/'+name for name in ('index.html','.cloudopsworks-release.json')]
        outputs={'owned_ids':ids};ex=Process(r,outputs)
        ctx={'expectedIdentity':'sub','iacOwnerDigest':OWNER,'workDir':self.work,'clock':lambda:self.time,'sleep':self.sleep,'overallDeadline':3,'http':lambda url,**kw:self.http(r,url,**kw)}
        return r,ex,ctx,outputs
    def sleep(self, value):self.time+=value
    def http(self, r, url, **kwargs):
        if url.endswith('/.well-known/cloudopsworks-build.json'):return 200,json.dumps(common.build_identity(r)).encode()
        if '/admin/functions/' in url:return 202,b''
        if url.endswith('/.cloudopsworks-release.json'):return 200,common.marker(r)
        if r['target']['kind']=='azure.blob-static':return 200,b'index bytes'
        return 200,b'ready'
    def verify(self, data, **kwargs):return readiness.verify(*data,**kwargs)

    def test_all_five_root_families_execute_native_and_serving_checks(self):
        for kind in ('azure.containerapps','azure.appservice','azure.functions','azure.blob-static','azure.apim'):
            with self.subTest(kind=kind):
                data=self.fixture(kind)
                result=self.verify(data,image=IMAGE if kind=='azure.containerapps' else None,directory=self.directory if kind=='azure.blob-static' else None)
                self.assertTrue(result.startswith('https://'))
                self.assertTrue(data[1].calls)
                self.assertTrue(all('--subscription' in args for args in data[1].calls))

    def test_app_slots_os_image_and_flex_modes(self):
        for kind in ('azure.appservice','azure.functions'):
            for slot in ('production','staging'):
                for mode in ('zip','image'):
                    with self.subTest(kind=kind,slot=slot,mode=mode):
                        data=self.fixture(kind,slot=slot,mode=mode)
                        self.verify(data,image=IMAGE if mode=='image' else None)
                        if slot!='production':self.assertTrue(all('--slot' in a for a in data[1].calls if a[1] in ('webapp','functionapp')))
            data=self.fixture(kind,os='windows');data[0]['target']['runtime']='DOTNET|8.0' if kind=='azure.appservice' else '8.0';data[0]['target']['workerRuntime']='dotnet-isolated'
            self.verify(data)
            data=self.fixture(kind,os='windows',slot='staging');data[0]['target']['runtime']='DOTNET|8.0' if kind=='azure.appservice' else '8.0';data[0]['target']['workerRuntime']='dotnet-isolated'
            self.verify(data)
        self.verify(self.fixture('azure.functions',flex=True))

    def test_linux_java_runtime_matches_selected_provider_encoder(self):
        for version in ('8', '11', '17', '21', '25'):
            data=self.fixture('azure.appservice');data[0]['target']['runtime']='JAVA|'+version
            fx='JAVA|'+version+('-jre8' if version=='8' else '-java'+version)
            data[1].change=lambda args,result,fx=fx:dict(result,linuxFxVersion=fx) if args[1:4]==['webapp','config','show'] else result
            with self.subTest(version=version):self.verify(data)

    def test_package_hash_and_extension_operation_fail_closed(self):
        for failure in ('bad_bytes','bad_operation'):
            data=self.fixture('azure.functions');setattr(data[1],failure,True)
            with self.assertRaises(common.ProviderError):self.verify(data)
        self.assertFalse(list(self.work.glob('azure-package-read-*')))

    def test_wrong_native_id_owner_host_and_output_are_rejected(self):
        for field,value in (('id','/subscriptions/other/sites/app'),('tags',{'cloudopsworks-owner':'wrong'}),('defaultHostName','evil.example?token=SECRET')):
            data=self.fixture('azure.appservice',mode='image');data[1].change=lambda args,result,f=field,v=value:dict(result,**{f:v}) if args[1:3]==['webapp','show'] else result
            with self.subTest(field=field),self.assertRaises(common.ProviderError) as caught:self.verify(data,image=IMAGE)
            self.assertNotIn('SECRET',str(caught.exception))
        data=self.fixture('azure.apim');data[3]['owned_ids']=['/subscriptions/other/api']
        with self.assertRaises(common.ProviderError):self.verify(data)

    def test_container_wrong_image_revision_traffic_and_port_never_pass(self):
        for field in ('image','revision','traffic','port'):
            data=self.fixture('azure.containerapps')
            def change(args,value):
                if args[1:3]==['containerapp','show']:
                    p=value['properties']
                    if field=='image':p['template']['containers'][0]['image']='registry/app:latest'
                    if field=='revision':p['latestReadyRevisionName']='stale'
                    if field=='traffic':p['configuration']['ingress']['traffic'][0]['weight']=50
                    if field=='port':p['configuration']['ingress']['targetPort']=9999
                return value
            data[1].change=change
            with self.subTest(field=field),self.assertRaises(common.ProviderError):self.verify(data,image=IMAGE)

    def test_baked_marker_static_bytes_and_timeout_are_not_availability(self):
        for kind in ('azure.appservice','azure.functions','azure.blob-static'):
            data=self.fixture(kind);data[2]['http']=lambda *a,**kw:(200,b'old bytes')
            with self.subTest(kind=kind),self.assertRaises(common.ProviderError) as caught:self.verify(data,directory=self.directory if kind=='azure.blob-static' else None)
            self.assertEqual(caught.exception.code,'readiness-timeout')
            self.time=0

    def test_admin_probe_requires_structured_completion_and_exact_app_key(self):
        data=self.fixture('azure.functions',slot='staging');r,ex,ctx,outputs=data
        r['target']['readiness']['probe']={'kind':'azure-function-admin','hostKeyRef':'key','functionName':'handler','requestBody':'{}','successLogMarker':'finished','appInsightsAppId':'insights'}
        site=outputs['owned_ids'][0]
        ctx['hostKeys']={'key':{'resourceId':site,'keyName':'_master','hostname':'app-staging.azurewebsites.net','value':'SECRET'}}
        self.verify(data)
        self.assertTrue(any(a[1:4]==['monitor','app-insights','query'] for a in ex.calls))
        ex.completed=False
        with self.assertRaises(common.ProviderError) as caught:self.verify(data)
        self.assertEqual(caught.exception.code,'readiness-timeout');self.time=0
        ctx['hostKeys']['key']['resourceId']=site.split('/slots/')[0]
        with self.assertRaises(common.ProviderError) as caught:self.verify(data)
        self.assertEqual(caught.exception.code,'probe-auth');self.assertNotIn('SECRET',str(caught.exception))

    def test_apim_current_revision_path_and_origin_are_exact(self):
        for field,value in [('isCurrent',False),('apiRevision','2'),('path','other')]:
            data=self.fixture('azure.apim')
            data[1].change=lambda args,result,f=field,v=value:dict(result,**{f:v}) if args[1:4]==['apim','api','show'] else result
            with self.subTest(field=field),self.assertRaises(common.ProviderError):self.verify(data)
        data=self.fixture('azure.apim');data[1].change=lambda args,result:dict(result,gatewayUrl='https://other.azure-api.net') if args[1:3]==['apim','show'] else result
        with self.assertRaises(common.ProviderError):self.verify(data)

    def test_native_config_modes_identity_and_incomplete_evidence_fail_closed(self):
        for kind,field,value in [('azure.functions','reserved',False),('azure.appservice','identity',{'type':'SystemAssigned'}),('azure.appservice','serverFarmId','/other/plan')]:
            data=self.fixture(kind,mode='image')
            data[1].change=lambda args,result,f=field,v=value:dict(result,**{f:v}) if args[1:3] in (['webapp','show'],['functionapp','show']) else result
            with self.subTest(kind=kind,field=field),self.assertRaises(common.ProviderError):self.verify(data,image=IMAGE)
        data=self.fixture('azure.functions');data[1].change=lambda args,result:{} if args[1:4]==['deployment','group','show'] else result
        with self.assertRaises(common.ProviderError):self.verify(data)
        data=self.fixture('azure.appservice',mode='image');data[0]['target']['packageMode']='zip'
        with self.assertRaises(common.ProviderError):self.verify(data,image=IMAGE)

    def test_no_cloud_mutating_cli_or_secret_key_acquisition(self):
        data=self.fixture('azure.functions');self.verify(data)
        for args in data[1].calls:
            self.assertFalse({'set','create','update','delete','deploy','list-keys','list-publishing-credentials'} & set(args))
            if args[1:3]==['storage','blob']:self.assertEqual(args[args.index('--auth-mode')+1],'login')
        source=(ROOT/'cd/monorepo/runtime/providers/azure_readiness.py').read_text()
        self.assertNotIn('boto',source);self.assertNotIn('azure.mgmt',source)


if __name__=='__main__':unittest.main()
