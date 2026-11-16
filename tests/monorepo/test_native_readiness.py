"""Read-only intended-native and serving proof; injected APIs, no cloud mutation."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from providers import common as c, readiness
from test_providers import request

OWNER='sha256:'+'9'*64


class Native:
    def __init__(self):self.calls=[];self.responses={}
    def run(self,argv,**kwargs):
        self.calls.append(argv)
        for key,value in self.responses.items():
            if tuple(argv[:len(key)])==key:return SimpleNamespace(returncode=0,stdout=json.dumps(value),stderr='')
        raise AssertionError('Unexpected native command: '+str(argv))


class NativeReadinessTests(unittest.TestCase):
    def immediate(self,r,ctx,check):
        value=check();c.require(bool(value));return value
    def context(self,root):
        return {'workDir':root,'iacOwnerDigest':OWNER,'expectedIdentity':'123456789012',
            'http':lambda *args,**kwargs:(200,b'ready')}

    def test_beanstalk_exact_native_version_bundle_and_http_probe_no_writes(self):
        r=request('aws.beanstalk');t=r['target'];version=r['artifact']['digest'][7:];ex=Native()
        environment={'EnvironmentName':t['environmentName'],'ApplicationName':t['application'],'VersionLabel':version,
            'Status':'Ready','Health':'Green','CNAME':'component.elasticbeanstalk.com'}
        bundle={'S3Bucket':t['bucket'],'S3Key':t['prefix'].strip('/')+'/'+version+'/application.zip'}
        ex.responses={('aws','elasticbeanstalk','describe-environments'):{'Environments':[environment]},
            ('aws','elasticbeanstalk','describe-application-versions'):{'ApplicationVersions':[{'SourceBundle':bundle}]}}
        owned={'environmentId':'e-1','environmentName':t['environmentName'],'version':version}
        with tempfile.TemporaryDirectory() as directory,patch.object(c,'poll',side_effect=self.immediate):
            self.assertEqual(readiness.verify(r,ex,self.context(Path(directory)),{'owned':owned}),'http://component.elasticbeanstalk.com')
            bundle['S3Key']='wrong-package.zip'
            with self.assertRaises(c.ProviderError):readiness.verify(r,ex,self.context(Path(directory)),{'owned':owned})
        self.assertTrue(all('describe-' in argv[2] for argv in ex.calls))

    def test_rest_fresh_generated_id_stage_and_output_url_exact(self):
        r=request('aws.apigateway-rest');t=r['target'];t.pop('restApiId');ex=Native()
        ex.responses={('aws','apigateway','get-stage'):{'deploymentId':'immutable'}}
        base='https://newapi.execute-api.'+t['region']+'.amazonaws.com'
        owned={'restApiId':'newapi','deploymentId':'immutable','stage':t['stage'],'invokeUrl':base+'/'+t['stage']}
        with tempfile.TemporaryDirectory() as directory,patch.object(c,'poll',side_effect=self.immediate):
            self.assertEqual(readiness.verify(r,ex,self.context(Path(directory)),{'owned':owned}),base)
            owned['invokeUrl']='https://attacker.invalid'
            with self.assertRaises(c.ProviderError):readiness.verify(r,ex,self.context(Path(directory)),{'owned':owned})
        self.assertTrue(all(argv[2]=='get-stage' for argv in ex.calls))

    def test_s3_static_verifies_every_served_byte_plus_exact_marker(self):
        r=request('aws.s3-static');ex=Native()
        with tempfile.TemporaryDirectory() as directory,patch.object(c,'poll',side_effect=self.immediate):
            root=Path(directory);(root/'index.html').write_text('ready');ctx=self.context(root)
            ctx['http']=lambda url,**kw:(200,c.marker(r) if url.endswith('.cloudopsworks-release.json') else b'ready')
            self.assertTrue(readiness.verify(r,ex,ctx,{'owned':{'objects':['index.html']}},directory=root).startswith('http://'))
            ctx['http']=lambda url,**kw:(200,b'stale')
            with self.assertRaises(c.ProviderError):readiness.verify(r,ex,ctx,{'owned':{'objects':['index.html']}},directory=root)
        self.assertEqual(ex.calls,[])

    def test_gen2_exact_package_runtime_account_current_traffic_and_source(self):
        r=request('gcp.functions-gen2');t=r['target'];t['iac']={'sourceBucket':'packages'};ex=Native()
        name='projects/'+t['project']+'/locations/'+t['region']+'/functions/'+t['functionName']
        live={'name':name,'state':'ACTIVE','labels':{'cloudopsworks-owner':OWNER[7:47]},
            'buildConfig':{'runtime':r['package']['runtime'],'entryPoint':r['package']['entryPoint'],
                'source':{'storageSource':{'bucket':'packages','object':'cloudopsworks/'+OWNER[7:]+'/'+r['artifact']['digest'][7:]+'/main.zip'}}},
            'serviceConfig':{'allTrafficOnLatestRevision':True,'serviceAccountEmail':t['serviceAccount'],'uri':'https://function.run.app'}}
        ex.responses={('gcloud','functions','describe'):live}
        with tempfile.TemporaryDirectory() as directory,patch.object(c,'poll',side_effect=self.immediate):
            self.assertEqual(readiness.verify(r,ex,self.context(Path(directory)),{'owned':{'function':name}}),'https://function.run.app')
            for key,value in [('runtime','wrong'),('entryPoint','wrong')]:
                previous=live['buildConfig'][key];live['buildConfig'][key]=value
                with self.assertRaises(c.ProviderError):readiness.verify(r,ex,self.context(Path(directory)),{'owned':{'function':name}})
                live['buildConfig'][key]=previous
        self.assertTrue(all(argv[1:3]==['functions','describe'] for argv in ex.calls))

    def test_appengine_exact_owned_version_traffic_native_zip_and_container(self):
        for image in (None,'region-docker.pkg.dev/project/repo/api@sha256:'+'b'*64):
            r=request('gcp.appengine');t=r['target'];t['iac']={'sourceBucket':'packages'};ex=Native();version='v-'+'a'*40
            live={'id':version,'servingStatus':'SERVING','versionUrl':'https://version.appspot.com','env':'flex',
                'deployment':{'container':{'image':image}} if image else {'zip':{'sourceUrl':'https://storage.googleapis.com/packages/cloudopsworks/'+OWNER[7:]+'/'+r['artifact']['digest'][7:]+'/main.zip'}}}
            service={'split':{'allocations':{version:1}}}
            ex.responses={('gcloud','app','versions','describe'):live,('gcloud','app','services','describe'):service}
            owned={'version':'apps/'+t['project']+'/services/'+t['service']+'/versions/'+version}
            with tempfile.TemporaryDirectory() as directory,patch.object(c,'poll',side_effect=self.immediate):
                self.assertEqual(readiness.verify(r,ex,self.context(Path(directory)),{'owned':owned},image=image),'https://version.appspot.com')
                service['split']['allocations']={'foreign':1}
                with self.assertRaises(c.ProviderError):readiness.verify(r,ex,self.context(Path(directory)),{'owned':owned},image=image)
            self.assertTrue(all('describe' in argv for argv in ex.calls))

if __name__=='__main__':unittest.main()
