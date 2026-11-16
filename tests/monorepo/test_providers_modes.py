"""Read-only probe protocols, ownership resolution and retired SDK denial.

These helpers do not establish IaC/cloud activation. Positive complete shared
execution tests live in test_iac_lifecycle and selected provider root tests.
"""
import contextlib
import hashlib
import http.server
import json
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from test_providers import request, Fake, IMAGE, contracts, common, aws, gcp, azure
from providers import kubernetes


class Handler:
    """Real in-process handler fixture: completion includes literal baked build identity."""
    def __init__(self, r):
        self.baked = common.build_identity(r)
    def handle(self, envelope, *, marker, source=None):
        # Handler executes payload semantics; mere accepted event is never completion.
        if envelope.get('payload') != 'exercise-handler':
            raise ValueError('handler payload not supported')
        completion = {k:envelope[k] for k in ('nonce','artifactDigest','release')}
        completion.update(marker=marker,status='completed')
        if source:
            completion['sourceResource'] = source
        else:
            completion.update(functionName=envelope['functionName'],resourceId=envelope['resourceId'])
            completion.update({'build_'+key:value for key,value in self.baked.items()})
        return completion


class ModeFake(Fake):
    def __init__(self,r,mutation=None):
        super().__init__(r); self.mutation=mutation; self.envelope=None; self.handler=Handler(r)
    def run(self,a,**kw):
        if a[:3]==['az','account','get-access-token']:
            self.calls.append((a,kw)); return subprocess.CompletedProcess(a,0,'protected-scm-token','')
        return super().run(a,**kw)
    def response(self,a):
        value=super().response(a); r=self.r; t=r['target']; revision=common.version(r)
        if a[:3]==['aws','lambda','get-alias']:value={'RevisionId':'alias-rev','FunctionVersion':'7'}
        if a[:3]==['aws','lambda','update-alias']:value={'FunctionVersion':'7'}
        if a[:3]==['gcloud','functions','describe'] and t.get('trigger',{}).get('kind')=='eventarc':
            probe=t['readiness']['probe']; value['eventTrigger']={'eventType':'google.cloud.pubsub.topic.v1.messagePublished' if probe['source']=='pubsub' else 'google.cloud.storage.object.v1.finalized'}
            if probe['source']=='pubsub':value['eventTrigger']['pubsubTopic']=t['trigger']['value']
            else:value['eventTrigger']['eventFilters']=[{'attribute':'bucket','value':t['trigger']['value']}]
        if a[:4]==['gcloud','pubsub','topics','publish']:
            self.envelope=json.loads(a[a.index('--message')+1])
        if a[:3]==['gcloud','storage','cp'] and '.cloudopsworks-probes/' in a[4]:
            self.envelope=json.loads(Path(a[3]).read_text())
        if a[:3]==['gcloud','logging','read']:
            probe=t['readiness']['probe']
            completion=self.handler.handle(self.envelope,marker=probe['successLogMarker'],source=probe['resource'])
            value=[{'jsonPayload':completion,'resource':{'labels':{'revision_name':'handler-'+revision,'service_name':'handler'}}}]
        if a[:3] in (['az','webapp','show'],['az','functionapp','show']):
            name='app-'+t['slot'].lower() if t.get('slot','production').lower()!='production' else 'app'
            value['id']=value['id'].split('/slots/')[0]+('/slots/'+t['slot'] if t.get('slot','production').lower()!='production' else '')
            value.update(defaultHostName=name+'.azurewebsites.net',enabledHostNames=[name+'.azurewebsites.net'],hostNameSslStates=[{'hostType':'Repository','name':name+'.scm.azurewebsites.net'}],functionAppConfig={'runtime':{'name':t.get('workerRuntime','python'),'version':'3.12'}})
        if a[:4]==['az','appservice','plan','show']:
            tier={'premium':'ElasticPremium','dedicated':'Standard','flex-consumption':'FlexConsumption'}[t['hostingPlan']];value={'sku':{'tier':tier}}
        if a[:4]==['az','monitor','app-insights','query']:
            completion=self.handler.handle(self.envelope,marker=t['readiness']['probe']['successLogMarker'])
            value={'tables':[{'columns':[{'name':k} for k in completion],'rows':[list(completion.values())]}]}
        if self.mutation:value=self.mutation(a,value)
        return value


class Modes(unittest.TestCase):
    def invoke(self,r,*,mutation=None,http_mutation=None,custom=False,context_update=None):
        with tempfile.TemporaryDirectory() as root:
            root=Path(root);path=root/'payload.zip'
            with zipfile.ZipFile(path,'w') as z:
                z.writestr('host.json',json.dumps({'customHandler':{'description':{'defaultExecutablePath':r['package'].get('entryPoint')}}}) if custom else '{}')
                z.writestr('function_app.py','def handler(req): return "ready"\n')
                if custom:
                    executable=zipfile.ZipInfo(r['package']['entryPoint']);executable.external_attr=0o100755 << 16
                    z.writestr(executable,'#!/bin/sh\nexit 0\n')
            if r['artifact']['format']!='oci':r['artifact'].update(digest='sha256:'+hashlib.sha256(path.read_bytes()).hexdigest(),sizeBytes=path.stat().st_size)
            ex=ModeFake(r,mutation);now=[0];http_calls=[]
            def http(url,**kw):
                http_calls.append((url,kw))
                if '/api/publish?' in url: value=(202,b'exact-deployment-id')
                elif '/api/deployments/' in url:value=(200,b'{"id":"exact-deployment-id","status":4}')
                elif '/admin/functions/' in url:
                    ex.envelope=json.loads(json.loads(kw['body'])['input']);value=(202,b'')
                elif url.endswith('/.well-known/cloudopsworks-build.json'):value=(200,json.dumps(common.build_identity(r)).encode())
                else:value=(200,b'ready')
                return http_mutation(url,kw,value) if http_mutation else value
            def sleep(n):now[0]+=n
            ctx=dict(workDir=root,artifactPath=path,http=http,clock=lambda:now[0],sleep=sleep)
            if r['target']['readiness']['probe']['kind']=='azure-function-admin':
                native=ex.response(['az','functionapp','show']);probe=r['target']['readiness']['probe']
                ctx['hostKeys']={probe['hostKeyRef']:{'value':'protected-master-key','keyName':'_master','resourceId':native['id'],'hostname':native['defaultHostName']}}
            if context_update:context_update(ctx)
            mod={'aws':aws,'gcp':gcp,'azure':azure}[r['target']['provider']]
            # Exercise only post-IaC readiness/probe helpers. Never simulate an
            # SDK apply to manufacture a successful DeploymentResult.
            ctx['overallDeadline']=30
            try:
                kind=r['target']['kind']
                if kind=='aws.lambda':
                    from providers.readiness import verify
                    image=None
                    if r['artifact']['format']=='oci':
                        from providers.registry import materialize
                        ctx['expectedIdentity']='123456789012'
                        image=materialize(r,ex,ctx,IMAGE,lambda_resource=ex.response(['aws','lambda','get-function']))
                    verify(r,ex,dict(ctx,expectedIdentity='123456789012'),{'owned':{'function_arn':'arn:aws:lambda:us-east-1:123456789012:function:handler','version':'7'}},image=image)
                elif kind=='gcp.functions-gen2' and r['target']['trigger']['kind']=='eventarc':
                    gcp.event_probe(r,ex,ctx,ex.response(['gcloud','functions','describe']))
                elif kind in ('azure.appservice','azure.functions') and r['target'].get('hostingPlan')!='flex-consumption':
                    if custom:
                        with zipfile.ZipFile(path) as archive:
                            metadata=json.loads(archive.read('host.json'))
                            if metadata.get('customHandler',{}).get('description',{}).get('defaultExecutablePath')!=r['package']['entryPoint'] or r['package']['entryPoint'] not in archive.namelist():
                                raise ValueError('custom-handler-metadata')
                    elif r['target'].get('workerRuntime')=='custom':raise ValueError('custom-handler-metadata')
                    live=ex.response(['az','functionapp' if kind=='azure.functions' else 'webapp','show'])
                    base=common.origin('https://'+live['defaultHostName'],host_suffix='.azurewebsites.net')
                    if r['target']['readiness']['probe']['kind']=='azure-function-admin':azure.admin_probe(r,ex,ctx,live,base)
                    else:
                        common.verify_build_identity(r,ex,ctx,base)
                        common.serving(r,ex,ctx,base)
                else:raise ValueError('iac-authorization-required')
                output=common.result(r)
            except Exception as error:output=common.result(r,error=error)
            return output,ex.calls,http_calls
    def test_lambda_image_alias_and_invocation_errors(self):
        for mode in ('zip','image'):
            r=request('aws.lambda');r['target']['alias']='live'
            if mode=='image':
                r['target']['packageMode']='image';r['package']['mode']='aws-image';r['artifact'].update(format='oci',location={'kind':'oci','reference':IMAGE},digest=IMAGE.split('@')[1])
            with self.subTest(mode=mode):
                output,calls,_=self.invoke(r)
                self.assertTrue(output['ready'],output)
                self.assertTrue(any('--qualifier' in a and a[a.index('--qualifier')+1]=='7' for a,k in calls))
                for wrong in ('error','version','body'):
                    def mutate(a,v):
                        if a[:3]==['aws','lambda','invoke']:
                            if wrong=='error':v['FunctionError']='Unhandled'
                            elif wrong=='version':v['ExecutedVersion']='6'
                            else:Path(a[a.index('--region')-1]).write_text('incorrect')
                        return v
                    out,_,_=self.invoke(r,mutation=mutate)
                    self.assertFalse(out['ready'])
    def test_eventarc_real_handler_profiles_and_wrong_completion(self):
        for source,resource in [('pubsub','projects/project/topics/probe'),('storage-finalize','probe-bucket')]:
            r=request('gcp.functions-gen2');r['target']['trigger']={'kind':'eventarc','value':resource}
            r['target']['readiness']['probe']=dict(kind='gcp-eventarc',source=source,resource=resource,requestBody='exercise-handler',successLogMarker='handler-completed')
            out,calls,_=self.invoke(r);self.assertTrue(out['ready'],out)
            if source=='storage-finalize':self.assertTrue(any(a[:3]==['gcloud','storage','rm'] and '.cloudopsworks-probes/' in a[3] for a,k in calls))
            for field in ('nonce','artifactDigest','release','sourceResource','marker'):
                def mutate(a,v):
                    if a[:3]==['gcloud','logging','read']:v[0]['jsonPayload'][field]='wrong'
                    return v
                out,_,_=self.invoke(r,mutation=mutate);self.assertFalse(out['ready'],field)
            def bad_revision(a,v):
                if a[:3]==['gcloud','logging','read']:v[0]['resource']['labels']['revision_name']='old-revision'
                return v
            out,_,_=self.invoke(r,mutation=bad_revision);self.assertFalse(out['ready'])
    def test_azure_modes_require_baked_build_identity(self):
        for kind in ('azure.appservice','azure.functions'):
            r=request(kind);r['target']['packageMode']='container'
            r['artifact'].update(format='oci',digest=IMAGE.split('@')[1],location={'kind':'oci','reference':IMAGE})
            if kind=='azure.appservice':
                r['package']=dict(kind='container',dockerfile='Dockerfile',context='.',platform='linux/amd64');r['artifact']['kind']='container'
            else:r['package']['mode']='azure-container'
            out,_,_=self.invoke(r);self.assertTrue(out['ready'],out)
            def stale(url,kw,v):return (200,b'{"componentId":"old"}') if url.endswith('cloudopsworks-build.json') else v
            out,_,_=self.invoke(r,http_mutation=stale);self.assertFalse(out['ready'])
    def test_azure_admin_real_handler_slots_and_wrong_key_completion(self):
        for slot in ('production','staging'):
            r=request('azure.functions');r['target']['slot']=slot
            r['target']['readiness']['probe']=dict(kind='azure-function-admin',functionName='handler',requestBody='exercise-handler',hostKeyRef='admin-key',appInsightsAppId='insights-app',successLogMarker='handler-completed')
            out,calls,http=self.invoke(r);self.assertTrue(out['ready'],out)
            self.assertFalse(any('protected-master-key' in str(a) for a,k in calls))
            self.assertNotIn('protected-master-key',json.dumps(out))
            self.assertTrue(any('app-staging.azurewebsites.net/admin/' in url for url,kw in http) if slot=='staging' else True)
            for field in ('nonce','artifactDigest','functionName','resourceId','build_sourceSha'):
                def mutate(a,v):
                    if a[:4]==['az','monitor','app-insights','query']:
                        names=[x['name'] for x in v['tables'][0]['columns']];v['tables'][0]['rows'][0][names.index(field)]='wrong'
                    return v
                out,_,_=self.invoke(r,mutation=mutate);self.assertFalse(out['ready'],field)
    def test_custom_handler_metadata_is_required(self):
        r=request('azure.functions');r['target']['workerRuntime']='custom';r['package'].update(runtime='rust-custom',entryPoint='handler')
        out,_,_=self.invoke(r,custom=True);self.assertTrue(out['ready'],out)
        out,calls,_=self.invoke(r,custom=False);self.assertFalse(out['ready'])
        self.assertFalse(any('config-zip' in a for a,k in calls))
    def test_retired_flex_scm_writer_is_unreachable_without_iac(self):
        r=request('azure.functions');r['target']['hostingPlan']='flex-consumption'
        ex=ModeFake(r)
        out=azure.deploy(r,ex)
        self.assertFalse(out['ready'])
        self.assertEqual(out['error']['code'],'iac-authorization-required')
        self.assertEqual(ex.calls,[])
        self.assertFalse(hasattr(azure,'flex_deploy'))

    def test_resource_aliases_and_hostile_options(self):
        for kind in ('aws.lambda','gcp.cloudrun','azure.containerapps'):
            r=request(kind);key={'aws.lambda':'functionName','gcp.cloudrun':'service','azure.containerapps':'appName'}[kind]
            r['target'][key]='--endpoint-url=http://localhost'
            ex=Fake(r)
            with self.assertRaises(common.ProviderError):{'aws':aws,'gcp':gcp,'azure':azure}[r['target']['provider']].resolve(r,ex)
            self.assertEqual(ex.calls,[])
        one=request('azure.functions');two=request('azure.appservice');two['target']['slot']='staging'
        a=azure.resolve(one,ModeFake(one));b=azure.resolve(two,ModeFake(two))
        self.assertTrue(contracts.claims_overlap(a['resourceClaims'][0],b['resourceClaims'][0]))
        with self.assertRaises(contracts.ContractError):contracts.validate_resource_ownership([dict(one,**a),dict(two,**b)])
        one['target']['slot']='blue';two['target']['slot']='green'
        a=azure.resolve(one,ModeFake(one));b=azure.resolve(two,ModeFake(two))
        contracts.validate_resource_ownership([dict(one,**a),dict(two,**b)])
        self.assertFalse(contracts.claims_overlap(a['resourceClaims'][0],b['resourceClaims'][0]))
        two['target']['slot']='BLUE';b=azure.resolve(two,ModeFake(two))
        with self.assertRaises(contracts.ContractError):contracts.validate_resource_ownership([dict(one,**a),dict(two,**b)])
    def test_key_scope_scm_origin_and_redirect_guards(self):
        r=request('azure.functions')
        r['target']['readiness']['probe']=dict(kind='azure-function-admin',functionName='handler',requestBody='exercise-handler',hostKeyRef='admin-key',appInsightsAppId='insights',successLogMarker='done')
        for bad in ('resourceId','keyName','hostname'):
            def change(ctx):ctx['hostKeys']['admin-key'][bad]='foreign'
            out,_,http=self.invoke(r,context_update=change)
            self.assertFalse(out['ready']);self.assertFalse(any('/admin/functions/' in url for url,k in http))
        r=request('azure.functions');r['target']['hostingPlan']='flex-consumption'
        def foreign(a,v):
            if a[:3]==['az','functionapp','show']:v['hostNameSslStates'][0]['name']='evil.scm.example.com'
            return v
        out,calls,http=self.invoke(r,mutation=foreign)
        self.assertFalse(out['ready']);self.assertEqual(http,[])
        self.assertFalse(any('get-access-token' in a for a,k in calls))
        def redirect(url,kw,v):return (302,b'') if '/api/publish?' in url else v
        out,_,_=self.invoke(r,http_mutation=redirect);self.assertFalse(out['ready'])
    def test_lambda_retry_reuses_exact_published_version(self):
        r=request('aws.lambda')
        def existing(a,v):
            if a[:3]==['aws','lambda','list-versions-by-function']:
                return {'Versions':[{'Description':'cloudopsworks:'+r['idempotencyKey'],'Version':'7'}]}
            return v
        out,calls,_=self.invoke(r,mutation=existing)
        self.assertTrue(out['ready'],out)
        self.assertFalse(any('update-function-code' in a or 'publish-version' in a for a,k in calls))
        # Configuration-only reconciliation can reuse matching immutable code without republishing.
        def identical(a,v):
            if a[:3]==['aws','lambda','list-versions-by-function']:
                cfg=Fake(r).response(['aws','lambda','get-function'])['Configuration']
                return {'Versions':[cfg]}
            return v
        out,calls,_=self.invoke(r,mutation=identical)
        self.assertTrue(out['ready'],out)
        self.assertFalse(any('update-function-code' in a for a,k in calls))
    def test_alias_backing_and_static_prefix_ownership(self):
        first=request('aws.lambda');second=request('aws.lambda');second['componentId']='second';second['target']['functionName']='arn:aws:lambda:us-east-1:123456789012:function:handler:live'
        a=aws.resolve(first,ModeFake(first));b=aws.resolve(second,ModeFake(second))
        self.assertEqual(a['resourceClaims'],b['resourceClaims'])
        with self.assertRaises(contracts.ContractError):contracts.validate_resource_ownership([dict(first,**a),dict(second,**b)])
        first=request('aws.s3-static');second=request('aws.s3-static');second['componentId']='second';second['target'].update(prefix='site/sub',region='other-region')
        a=aws.resolve(first,ModeFake(first));b=aws.resolve(second,ModeFake(second))
        with self.assertRaises(contracts.ContractError):contracts.validate_resource_ownership([dict(first,**a),dict(second,**b)])
        second['target']['prefix']='sibling'
        b=aws.resolve(second,ModeFake(second));contracts.validate_resource_ownership([dict(first,**a),dict(second,**b)])
    def test_deadline_and_changed_identity_precede_mutation(self):
        r=request('gcp.cloudrun');ex=Fake(r)
        resolved=gcp.resolve(r,ex);resolved['providerIdentity']='foreign'
        out=gcp.deploy(r,ex,resolved=resolved)
        self.assertFalse(out['ready']);self.assertFalse(any(a[:3]==['gcloud','run','deploy'] for a,k in ex.calls))
        now=[0]
        class Slow:
            def run(self,a,**kw):now[0]=31;return subprocess.CompletedProcess(a,0,'{}','')
        ctx={'clock':lambda:now[0],'overallDeadline':30}
        with self.assertRaises(common.ProviderError):common.DeadlineExecutor(Slow(),ctx).run(['provider'])
    def test_real_loopback_forwarding_cleanup_on_success_and_failure(self):
        # A real local HTTP socket is forwarded by a real child process. No Kubernetes/cloud needed.
        import os,sys
        code="import socket,sys,time;s=socket.socket();s.bind(('127.0.0.1',int(sys.argv[1])));s.listen();\nwhile True:\n c,a=s.accept();d=c.recv(4096);c.sendall(b'HTTP/1.1 200 OK\\r\\nContent-Length:5\\r\\n\\r\\nready') if d else None;c.close()"
        real=subprocess.Popen;children=[]
        def launch(argv,**kw):
            port=argv[-1].split(':')[0]
            p=real([sys.executable,'-c',code,port],**kw);children.append(p);return p
        for failure in (False,True):
            with patch.object(kubernetes.subprocess,'Popen',side_effect=launch):
                try:
                    with kubernetes.forward(None,'owned','api',3000,{}) as base:
                        self.assertEqual(common.http_request(base+'/ready'),(200,b'ready'))
                        if failure:raise RuntimeError('probe failed')
                except RuntimeError:
                    self.assertTrue(failure)
            self.assertIsNotNone(children[-1].poll())

if __name__=='__main__':unittest.main()
