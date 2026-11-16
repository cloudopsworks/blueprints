"""Scripted native command + real artifact tests; never calls a cloud account."""
import base64
import contextlib
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'cd/monorepo/runtime'))
import contracts
from providers import common, aws, gcp, azure

CORPUS = Path(__file__).with_name('contracts')
IMAGE = 'registry.example.com/app@sha256:' + 'b' * 64


def request(kind):
    r = json.loads((CORPUS / 'valid/deployment-request.json').read_text())
    definition = next(x for x in contracts.schema()['$defs']['Target']['oneOf'] if x['properties']['kind']['const'] == kind)
    values = dict(id='prod', environment='prod', provider=kind.split('.')[0], authRef='prod', configDigest='sha256:' + 'c'*64,
        kind=kind, region='us-central1', cluster='cluster', namespace='apps', application='app', environmentName='env',
        bucket='bucket', prefix='site', functionName='handler', packageMode='zip', alias=None, restApiId='api', stage='prod',
        project='project', service='api', serviceAccount='runtime@project.iam.gserviceaccount.com', location='us-central1',
        appConfig='app.yaml', trigger={'kind':'http','value':'http'}, api='api', gateway='gateway', backendServiceAccount='backend@project.iam.gserviceaccount.com',
        subscriptionId='sub', resourceGroup='rg', appName='app', containerName='app', slot='production', hostingPlan='premium', workerRuntime='python', account='storage', container='$web', serviceName='gateway', apiId='api', apiPath='api')
    t = {key: values[key] for key in definition['required'] if key != 'readiness'}
    probe = dict(kind='http', path='/ready', method='GET', requestBody='', expectedStatus=200, responseContains='ready', auth={'kind':'none'})
    p = dict(kind='container', dockerfile='Dockerfile', context='.', platform='linux/amd64')
    workload = dict(kind='http', port=3000, healthPath='/ready')
    artifact = dict(r['artifact'], kind='container', format='oci', digest='sha256:'+'b'*64,
        location={'kind':'oci','reference':IMAGE})
    if kind in contracts.STATIC:
        p = dict(kind='static', directory='dist', index='index.html')
        workload = dict(kind='static')
        probe = dict(kind='static-http', path='/index.html')
        artifact.update(kind='static', format='zip', location={'kind':'release-asset','repositoryId':r['repository']['id'],'tag':'v1.2.3','name':'static.zip'})
    elif kind in contracts.API_TARGETS:
        p = dict(kind='openapi', file='openapi.json', version='3.0')
        workload = dict(kind='api')
        artifact.update(kind='openapi', format='openapi-json', location={'kind':'release-asset','repositoryId':r['repository']['id'],'tag':'v1.2.3','name':'spec.json'})
    elif kind in contracts.FUNCTIONS:
        provider = kind.split('.')[0]
        p = dict(kind='function', provider=provider, mode={'aws':'aws-zip','gcp':'gcp-gen2','azure':'azure-zip'}[provider], runtime='python312', entryPoint='handler', architecture='amd64', source='src')
        workload = dict(kind='function')
        artifact.update(kind='function', format='zip', location={'kind':'release-asset','repositoryId':r['repository']['id'],'tag':'v1.2.3','name':'handler.zip'})
        if provider == 'aws':
            probe = dict(kind='lambda-invoke',requestBody='{}',responseContains='ready')
    elif kind in ('aws.beanstalk','gcp.appengine','azure.appservice'):
        p = dict(kind='archive',format='zip',include=['app.yaml'])
        artifact.update(kind='archive',format='zip',location={'kind':'release-asset','repositoryId':r['repository']['id'],'tag':'v1.2.3','name':'app.zip'})
    if kind.startswith('aws.'):
        t['region']='us-east-1'
    t['readiness'] = dict(deadlineSeconds=30,intervalSeconds=1,probe=probe)
    r.update(target=t,package=p,workload=workload,artifact=artifact)
    return r


class Fake:
    def __init__(self, r, *, fail_command=None):
        self.r, self.calls, self.fail_command = r, [], fail_command
        self.digest = None
    def run(self, argv, **kw):
        self.calls.append((argv,kw))
        if self.fail_command and self.fail_command in ' '.join(argv):
            return SimpleNamespace(returncode=1,stdout='',stderr='secret-never-report')
        value = self.response(argv)
        return SimpleNamespace(returncode=0,stdout=value if (isinstance(value,str) and argv[0] == 'skopeo') or argv[:3] == ['aws','ecr','get-login-password'] else json.dumps(value),stderr='')
    def response(self,a):
        r,t = self.r,self.r['target']; revision=common.version(r)
        if a[:2] == ['skopeo','inspect']:
            if '--raw' in a:return {'mediaType':'application/vnd.oci.image.manifest.v1+json'}
            return r['artifact']['digest']
        if a[:3] == ['aws','ecr','get-login-password']:return 'native-token'
        if a[:3] == ['aws','ecr','describe-repositories']:return {'repositories':[{'registryId':'123456789012','repositoryUri':'123456789012.dkr.ecr.us-east-1.amazonaws.com/app','repositoryArn':'arn:aws:ecr:us-east-1:123456789012:repository/app'}]}
        if a[:3] == ['aws','ecr','describe-images']:return {'imageDetails':[{'imageDigest':r['artifact']['digest']}]}
        if a[:3] == ['aws','sts','get-caller-identity']: return {'Account':'123456789012'}
        if a[:3] == ['aws','eks','describe-cluster']: return {'cluster':{'arn':'arn:aws:eks:us-east-1:123456789012:cluster/cluster'}}
        if a[:3] == ['aws','lambda','get-function']:
            cfg=dict(FunctionArn='arn:aws:lambda:us-east-1:123456789012:function:handler',PackageType='Image' if r['artifact']['format']=='oci' else 'Zip',Architectures=['x86_64'],Runtime='python312',Handler='handler',RevisionId='revision',Version='7',State='Active',LastUpdateStatus='Successful',CodeSha256=base64.b64encode(bytes.fromhex(r['artifact']['digest'][7:])).decode())
            return {'Configuration':cfg,'Code':{'ResolvedImageUri':'123456789012.dkr.ecr.us-east-1.amazonaws.com/app@'+r['artifact']['digest']}}
        if a[:3] == ['aws','lambda','update-function-code']: return {'CodeSha256':'code-sha','RevisionId':'updated-revision'}
        if a[:3] == ['aws','lambda','list-versions-by-function']:return {'Versions':[]}
        if a[:3] == ['aws','lambda','publish-version']:return {'Version':'7'}
        if a[:3] == ['aws','lambda','invoke']:
            Path(a[a.index('--region')-1]).write_text('ready')
            return {'StatusCode':200,'ExecutedVersion':'7'}
        if a[:3] == ['aws','elasticbeanstalk','describe-environments']:
            return {'Environments':[dict(ApplicationName='app',EnvironmentArn='arn:aws:elasticbeanstalk:us-east-1:123456789012:environment/app/env',VersionLabel=revision,Status='Ready',Health='Green',CNAME='env.elasticbeanstalk.com')]}
        if a[:3] == ['aws','elasticbeanstalk','describe-application-versions']: return {'ApplicationVersions':[]}
        if a[:3] == ['aws','apigateway','get-rest-api'] or a[:3] == ['aws','apigateway','put-rest-api']: return {'id':'api'}
        if a[:3] == ['aws','apigateway','create-deployment']: return {'id':'deployment'}
        if a[:3] == ['aws','apigateway','get-stage']: return {'deploymentId':'deployment'}
        if a[:3] == ['gcloud','projects','describe']: return {'projectId':'project','projectNumber':'123'}
        if a[:4] == ['gcloud','container','clusters','describe']: return {'selfLink':'https://container.googleapis.com/projects/123/locations/us-central1/clusters/cluster'}
        if a[:4] == ['gcloud','run','services','describe']:
            return dict(metadata={'name':'api','generation':1},spec={'template':{'spec':{'containers':[{'image':IMAGE}]}}},status=dict(conditions=[{'type':'Ready','status':'True'}],observedGeneration=1,latestReadyRevisionName='api-'+revision,traffic=[{'revisionName':'api-'+revision,'percent':100}],url='https://api.run.app'))
        if a[:4] == ['gcloud','app','services','describe']: return {'split':{'allocations':{revision:1}}}
        if a[:4] == ['gcloud','app','versions','describe']: return {'id':revision,'servingStatus':'SERVING','versionUrl':'https://api.appspot.com'}
        if a[:3] == ['gcloud','functions','describe']:
            return dict(name='projects/project/locations/us-central1/functions/handler',state='ACTIVE',labels={'cloudopsworks-release':revision},buildConfig={'runtime':'python312','entryPoint':'handler'},serviceConfig={'service':'projects/project/locations/us-central1/services/handler','revision':'handler-'+revision,'allTrafficOnLatestRevision':True,'serviceAccountEmail':t['serviceAccount'],'uri':'https://handler.run.app'})
        if a[:4] == ['gcloud','storage','buckets','describe']: return {'project_number':'123','website':{'mainPageSuffix':'index.html'}}
        if a[:4] == ['gcloud','api-gateway','gateways','describe']: return dict(name='projects/project/locations/us-central1/gateways/gateway',state='ACTIVE',apiConfig='projects/project/locations/global/apis/api/configs/'+revision,defaultHostname='api.gateway.dev')
        if a[:4] == ['gcloud','api-gateway','api-configs','list']: return []
        arm='/subscriptions/sub/resourceGroups/rg/providers/'
        if a[:3]==['az','account','show']: return {'id':'sub','state':'Enabled'}
        if a[:3]==['az','aks','show']: return {'id':arm+'Microsoft.ContainerService/managedClusters/cluster'}
        if a[:3]==['az','containerapp','show']:
            return dict(id=arm+'Microsoft.App/containerApps/app',properties=dict(template={'containers':[{'name':'app','image':IMAGE}]},latestRevisionName='app--'+revision,configuration={'ingress':{'targetPort':3000,'fqdn':'app.azurecontainerapps.io','traffic':[{'revisionName':'app--'+revision,'weight':100}]}}))
        if a[:4]==['az','containerapp','revision','show']: return {'properties':{'provisioningState':'Provisioned','healthState':'Healthy','template':{'containers':[{'name':'app','image':IMAGE}]}}}
        if a[:3] in (['az','webapp','show'],['az','functionapp','show']):
            return dict(id=arm+'Microsoft.Web/sites/app'+('/slots/staging' if t.get('slot')=='staging' else ''),state='Running',defaultHostName='app.azurewebsites.net',enabledHostNames=['app.azurewebsites.net'],serverFarmId=arm+'Microsoft.Web/serverfarms/plan')
        if a[:4] in (['az','webapp','config','show'],['az','functionapp','config','show']):return {'linuxFxVersion':'PYTHON|3.12' if t.get('packageMode')=='zip' else 'DOCKER|'+IMAGE}
        if a[:5]==['az','functionapp','config','appsettings','list']:return [{'name':'FUNCTIONS_WORKER_RUNTIME','value':t['workerRuntime']}]
        if a[:4]==['az','appservice','plan','show']:return {'sku':{'tier':'ElasticPremium'}}
        if a[:3]==['az','webapp','deploy'] or a[:5]==['az','functionapp','deployment','source','config-zip']:return {'id':'deploy-id','active':True,'status':4}
        if a[:4]==['az','storage','account','show']:return {'id':arm+'Microsoft.Storage/storageAccounts/storage','primaryEndpoints':{'web':'https://storage.z1.web.core.windows.net/'}}
        if a[:5]==['az','storage','blob','service-properties','show']:return {'staticWebsite':{'enabled':True}}
        if a[:4] in (['az','apim','api','show'],['az','apim','api','import']):return {'id':arm+'Microsoft.ApiManagement/service/gateway/apis/api','path':'api','isCurrent':True}
        if a[:3]==['az','apim','show']:return {'id':arm+'Microsoft.ApiManagement/service/gateway','gatewayUrl':'https://gateway.azure-api.net'}
        if a[:2] == ['kubectl','version']:return {'clientVersion':{'major':'1','minor':'37'},'serverVersion':{'major':'1','minor':'37'}}
        if a[:3] == ['kubectl','get','namespace']: return {'metadata':{'name':'apps'}}
        if a[:3] == ['kubectl','get','deployment']: return {'metadata':{'annotations':{'deployment.kubernetes.io/revision':'1'}},'spec':{'template':{'spec':{'containers':[{'image':IMAGE,'ports':[{'containerPort':3000}]}]}}}}
        if a[:3] == ['kubectl','get','service']: return {'metadata':{'name':'api'},'spec':{'ports':[{'port':3000}]}}
        return {}


class ProviderTests(unittest.TestCase):
    @contextlib.contextmanager
    def forward(self,*args):
        try: yield 'http://127.0.0.1:45678'
        finally: self.forward_closed = True
    def exercise(self, kind, *, smoke=True, fail_command=None):
        r=request(kind)
        with tempfile.TemporaryDirectory() as root:
            root=Path(root); path=root/'payload.zip'
            if r['artifact']['format'] == 'openapi-json': path.write_text('{"openapi":"3.0.0","info":{"title":"API","version":"1"},"paths":{"/ready":{"get":{}}}}')
            else:
                with zipfile.ZipFile(path,'w') as z:
                    z.writestr('index.html','ready');z.writestr('app.yaml','runtime: python312\nservice: api\n');z.writestr('host.json','{}');z.writestr('function_app.py','def handler(req): return "ready"\n')
            if r['artifact']['format'] != 'oci':
                r['artifact'].update(sizeBytes=path.stat().st_size,digest='sha256:'+hashlib.sha256(path.read_bytes()).hexdigest())
            ex=Fake(r,fail_command=fail_command)
            now=[0]
            def http(url,**kw):
                if not smoke: return 503,b'not-ready'
                if url.endswith('.cloudopsworks-release.json'): return 200,common.marker(r)
                if url.endswith('app.yaml'): return 200,b'runtime: python312\nservice: api\n'
                if url.endswith('host.json'): return 200,b'{}'
                if url.endswith('function_app.py'):return 200,b'def handler(req): return "ready"\n'
                return 200,b'ready'
            def sleep(seconds): now[0]+=seconds
            ctx=dict(artifactPath=path,workDir=root,http=http,clock=lambda:now[0],sleep=sleep,forward=self.forward)
            module={'aws':aws,'gcp':gcp,'azure':azure}[kind.split('.')[0]]
            resolved=module.resolve(r,ex)
            output=module.deploy(r,ex,context=ctx,resolved=resolved)
            return output,ex.calls
    def test_all_native_entrypoints_require_independent_iac_authorization(self):
        # The former SDK-success matrix is intentionally not v2 capability proof.
        # Positive canonical operation/root/readiness cases live in
        # test_iac_lifecycle plus real pinned-provider root tests.
        for definition in contracts.schema()['$defs']['Target']['oneOf']:
            kind=definition['properties']['kind']['const']
            with self.subTest(kind=kind):
                r=request(kind);ex=Fake(r)
                output={'aws':aws,'gcp':gcp,'azure':azure}[r['target']['provider']].deploy(r,ex)
                self.assertEqual(output['status'],'failed')
                self.assertEqual(output['error']['code'],'iac-authorization-required')
                self.assertEqual(ex.calls,[])

    def test_cli_failure_is_redacted(self):
        out,_=self.exercise('gcp.cloudrun',fail_command='run deploy')
        self.assertEqual(out['status'],'failed')
        self.assertNotIn('secret-never-report',json.dumps(out))
    def test_wrong_runtime_rejects_before_apply(self):
        r=request('aws.lambda');r['package']['runtime']='ruby3.3'
        ex=Fake(r)
        out=aws.deploy(r,ex)
        self.assertEqual(out['status'],'failed')
        self.assertFalse(any('update-function-code' in a for a,k in ex.calls))
    def test_bad_probe_rejects_before_credentials(self):
        r=request('gcp.cloudrun');r['target']['readiness']['probe']['path']='//metadata.google.internal/'
        ex=Fake(r)
        self.assertEqual(gcp.deploy(r,ex)['status'],'failed')
        self.assertEqual(ex.calls,[])

if __name__=='__main__':unittest.main()
