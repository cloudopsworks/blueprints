"""Connected normal lifecycle with actual Go/authorization/IaC orchestration.

Only GitHub, cloud/registry/native subprocess and HTTP boundaries are doubles.
The one concrete Cloud Run root uses a TEST-ONLY catalog activation copy. This
is neither a hosted workflow run nor credentialed provider/registry evidence.
"""
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
import authorization as auth
import normal_entry
from contracts import ContractError,digest
from iac import IaCExecutor
from preflight_barrier import verify_preflight_barrier
from providers import common
from staging import marker_record
from test_authorization import RecoveryAPI,captured

BINARY=os.environ.get('TRONADOR_TEST_BINARY')
CORPUS=Path(__file__).with_name('contracts')


class ConnectedAPI(RecoveryAPI):
    def __init__(self):
        self.source_ready=False
        super().__init__()
        self.token='';self.jobs=[];self.logs={};self.statuses={};self.api_calls=[]
        image=json.loads((CORPUS/'valid/oci-image-valid.json').read_text())['mainArtifact']
        self.image=(CORPUS/'artifacts/image.oci.tar').read_bytes()
        with zipfile.ZipFile(io.BytesIO(self.archive)) as archive:
            files={name:json.loads(archive.read(name)) for name in archive.namelist()}
        self.manifest=files['manifest.json']
        for component in self.manifest['components']:
            for role in ('mainArtifact','previewArtifact'):
                if component[role]:
                    component[role].update(digest=image['digest'],sizeBytes=image['sizeBytes'],
                        location={'kind':'oci','reference':'registry.example/public/api@'+image['digest']})
        self.files=files
        self.rebuild_stage()
    def rebuild_stage(self):
        files=self.files
        files['host.json']['manifestDigest']=digest(self.manifest)
        archive=io.BytesIO()
        with zipfile.ZipFile(archive,'w') as output:
            for name,value in files.items():output.writestr(name,json.dumps(value))
        self.archive=archive.getvalue();self.stage['archiveDigest']='sha256:'+hashlib.sha256(self.archive).hexdigest()
        self.publisher_log=marker_record('12345','100','1','500',self.stage['archiveDigest']).encode()
        scan=json.loads(self.scan_log.decode().split(' ',1)[1]);scan['stage']=self.stage
        from scanners import _identity
        for result in scan['results']:
            component=next(c for c in files['build-plan.json']['components'] if c['id']==result['componentId'])
            identity=_identity(files['build-plan.json'],self.manifest,component,result['scanner'],self.resolved['scanners'])
            result.update({key:value for key,value in identity.items() if key not in ('status','errorCode')})
        self.scan_log=auth.scan_marker(self.stage,self.resolved,scan['results']).encode()
    def _source(self):
        if self.source_ready:return
        self.source_ready=True
        # Trusted YAML enables a required completed Sonar gate; result evidence
        # below remains an API job/log double, not an executed scanner claim.
        data=b'sonarqube:\n  enabled: true\n  quality_gate_enabled: true\n  fail_on_quality_gate: true\n'
        sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        self.entries.append({'path':'.cloudopsworks/vars/inputs-global.yaml','mode':'100644','type':'blob','sha':sha,'size':len(data)})
        self.blobs[sha]={'sha':sha,'encoding':'base64','size':len(data),'content':base64.b64encode(data).decode()}
        for entry in self.entries:
            if entry['path']!='.cloudopsworks/vars/inputs-dev.yaml':continue
            data=base64.b64decode(self.blobs[entry['sha']]['content'])
            data=data.replace(b'kind: gcp.cloudrun',b'kind: gcp.cloudrun\n      ownership: managed')
            sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            entry.update(sha=sha,size=len(data));self.blobs[sha]={'sha':sha,'encoding':'base64','size':len(data),'content':base64.b64encode(data).decode()}
    def add_job(self,name,line):
        identity=400+len(self.jobs)
        self.jobs.append({'id':identity,'run_id':200,'run_attempt':1,'status':'completed','conclusion':'success','name':name})
        self.logs[identity]=(line+'\n').encode()
    def repo(self,method,path,value=None,**kwargs):
        self._source()
        if getattr(self,'manual',False) and path.startswith('/actions/runs/200/') and '/jobs?' not in path:
            run=copy.deepcopy(self.run);run.update(id=200,event='workflow_dispatch',path='.github/workflows/deploy.yml',referenced_workflows=[{'path':'cloudopsworks/blueprints/.github/workflows/monorepo-manual-apply.yml@v5.11.0','sha':self.bp}]);return run
        if getattr(self,'manual',False) and path.startswith('/actions/workflows/main-build.yml/runs?'):
            return {'workflow_runs':[copy.deepcopy(self.run)]}
        if hasattr(self,'api_calls'):self.api_calls.append((method,path))
        if path=='/actions/artifacts/600':
            return {'id':600,'name':'components-100-1-api','expired':False,'workflow_run':{'id':100,'head_sha':self.manifest['components'][0]['mainArtifact']['sourceSha']}}
        if path=='/actions/artifacts/600/zip':
            data=io.BytesIO()
            with zipfile.ZipFile(data,'w') as archive:archive.writestr('.cloudopsworks/out/api/main.oci.tar',self.image)
            return data.getvalue()
        if path=='/deployments' and method=='POST':
            record={**copy.deepcopy(value),'id':900+len(self.records),'creator':{'id':42}}
            self.records.append(record);return copy.deepcopy(record)
        if path.startswith('/deployments/'):
            identity=int(path.split('/')[2])
            if path.endswith('/statuses') and method=='POST':
                status={**copy.deepcopy(value),'id':1000+sum(map(len,self.statuses.values())),'creator':{'id':42}}
                self.statuses.setdefault(identity,[]).append(status);return copy.deepcopy(status)
            if method=='GET':return copy.deepcopy(next(r for r in self.records if r['id']==identity))
        if hasattr(self,'jobs') and '/actions/runs/200/' in path and '/jobs?' in path:
            response=super().repo(method,path,value,**kwargs);response['jobs']+=copy.deepcopy(self.jobs)
            if getattr(self,'manual',False):
                for job in response['jobs']:job['name']=job['name'].replace('lifecycle / ','operation / ')
            return response
        if hasattr(self,'logs') and path.startswith('/actions/jobs/') and int(path.split('/')[3]) in self.logs:
            return self.logs[int(path.split('/')[3])]
        return super().repo(method,path,value,**kwargs)
    def pages(self,path):
        if path=='/deployments?task=cloudopsworks-state':return copy.deepcopy([r for r in self.records if r.get('task')=='cloudopsworks-state'])
        if path.startswith('/deployments?environment='):
            return copy.deepcopy([r for r in self.records if r.get('environment')==path.split('=',1)[1]])
        if path.startswith('/deployments/') and path.endswith('/statuses'):
            return copy.deepcopy(self.statuses.get(int(path.split('/')[2]),[]))
        return super().pages(path)


class ConnectedProcess:
    """Real Go child, deterministic read-only cloud and saved native-plan boundary."""
    def __init__(self,api):self.api=api;self.calls=[];self.fail_apply=False;self.project_number='123456789012';self.project_reads=0;self.drift_before_apply=False;self.published_image=None
    def run(self,argv,**kwargs):
        self.calls.append((argv,kwargs))
        if argv[0]=='tronador':return subprocess.run([BINARY,*argv[1:]],capture_output=True,text=True,**kwargs)
        value={};code=0
        if argv[:3]==['gcloud','auth','print-identity-token']:return subprocess.CompletedProcess(argv,0,'TEST-ONLY-ID-TOKEN','')
        elif argv[:3]==['gcloud','projects','describe']:
            self.project_reads+=1
            number='999999999999' if self.drift_before_apply and self.project_reads>=4 else self.project_number
            value={'projectId':'example-dev','projectNumber':number,'lifecycleState':'ACTIVE'}
        elif argv[:4]==['gcloud','run','services','list']:value=[]
        elif argv[:4]==['gcloud','run','services','describe']:
            image=self.published_image or self.api.manifest['components'][0]['mainArtifact']['location'].get('reference')
            value={'metadata':{'name':'api','generation':1},'spec':{'template':{'spec':{'containers':[{'image':image}]}}},
                   'status':{'conditions':[{'type':'Ready','status':'True'}],'observedGeneration':1,'latestReadyRevisionName':'api-00001','latestCreatedRevisionName':'api-00001','traffic':[{'revisionName':'api-00001','percent':100}],'url':'https://api.run.app'}}
        elif argv[:2]==['skopeo','copy']:
            if argv[-1].startswith('oci-archive:'):Path(argv[-1][len('oci-archive:'):]).write_bytes(self.api.image)
            elif argv[-1].startswith('docker://'):
                self.published_image=argv[-1][len('docker://'):].rsplit(':',1)[0]+'@'+self.api.manifest['components'][0]['mainArtifact']['digest']
        elif argv[:2]==['skopeo','inspect']:return subprocess.CompletedProcess(argv,0,self.api.manifest['components'][0]['mainArtifact']['digest'],'')
        elif argv==['tofu','version','-json']:value={'terraform_version':'1.11.4'}
        elif argv==['terragrunt','--version']:return subprocess.CompletedProcess(argv,0,'terragrunt version v0.99.4','')
        elif argv[0]=='terragrunt':
            if 'pull' in argv:code=1
            elif 'plan' in argv:
                code=2;(Path(kwargs['cwd'])/'operation.tfplan').write_bytes(b'opaque native saved plan')
            elif 'show' in argv:value={'resource_changes':[{'mode':'managed','address':'google_cloud_run_v2_service.component','change':{'actions':['create'],'before':None,'after':{}}}]}
            elif 'apply' in argv:
                assert argv[-1]=='operation.tfplan' and (Path(kwargs['cwd'])/'operation.tfplan').read_bytes()==b'opaque native saved plan'
                if self.fail_apply:code=1
            elif 'output' in argv:value={'owned':{'sensitive':False,'value':{'service':'projects/example-dev/locations/us-central1/services/api'}}}
        else:raise AssertionError('Unexpected boundary command: '+str(argv[:5]))
        return subprocess.CompletedProcess(argv,code,json.dumps(value),'')
    def mutations(self):
        return [a for a,_ in self.calls if (a[0]=='terragrunt' and 'apply' in a) or (a[:2]==['skopeo','copy'] and a[-1].startswith('docker://'))]


@unittest.skipUnless(BINARY,'set TRONADOR_TEST_BINARY to the reviewed Go binary')
class NormalEntryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name);self.api=ConnectedAPI();self.runner=ConnectedProcess(self.api)
        catalog=json.loads((ROOT/'terraform/monorepo/module-catalog.json').read_text())
        self.assertTrue(catalog['modules']['gcp-cloudrun']['activationBlocked'])
        catalog['modules']['gcp-cloudrun']['activationBlocked']=False # TEST ONLY, production bytes unchanged
        self.engine=IaCExecutor(ROOT,catalog,executor=self.runner)
        self.credentials={'workload':captured('gcp','123456789012','api'),'backend':captured('aws','222222222222','state')}
        self.credentials['workload']['binding']['workloadIdentityProvider']='projects/123/locations/global/workloadIdentityPools/pool/providers/provider'
        self.settings={'auth':'gcp-dev:\n  provider: gcp\n  project: example-dev\n  serviceAccount: api@example-dev.iam.gserviceaccount.com\n  workloadIdentityProvider: projects/123/locations/global/workloadIdentityPools/pool/providers/provider\naws-state:\n  provider: aws\n  roleArn: arn:aws:iam::222222222222:role/state\n  region: us-east-1\n','identities':'gcp-dev: "123456789012"\naws-state: "222222222222"\n','registries':'{}','probe-secrets':'{}','host-keys':'{}'}
        self.backend=(Path(__file__).with_name('fixtures')/'operations/backend-native-s3.yaml').read_text()+'  auth_ref: aws-state\n'
    def prepare(self):
        prepared=auth.prepare_verified_context(self.api,self.api.run,blueprint_sha=self.api.bp,
            executor=self.runner,engine=self.engine,current_host=self.api.host)
        normal_entry.select(prepared,'dev-run','api',self.backend,self.settings,42)
        prepared.bind(self.backend,self.settings,self.credentials,automation_id=42,
            on_readback=lambda line:setattr(self.api,'state_log',line.encode()))
        return prepared
    def barrier(self,prepared):
        work=self.root/'preflight';work.mkdir(mode=0o700)
        lines=[]
        operation=normal_entry.preflight(prepared,self.runner,'dev-run','api',self.credentials,work,
            emit=lambda line,**kw:lines.append(line))
        self.api.add_job('lifecycle / monorepo-preflight-dev-run-api',lines[0])
        emitted=[];records=verify_preflight_barrier(prepared,self.api,emit=lambda line,**kw:emitted.append(line))
        self.api.add_job('lifecycle / monorepo-preflight-barrier',emitted[0])
        return records,operation
    def apply(self,prepared):
        work=self.root/'apply';work.mkdir(mode=0o700)
        with patch.dict(os.environ,{'GITHUB_ACTOR':'operator'}),patch.object(common,'http_request',return_value=(200,b'ok')) as http:
            result=normal_entry.apply(prepared,self.api,self.runner,'dev-run','api',self.credentials,work,42)
        self.assertEqual(http.call_args.args[0],'https://api.run.app/health')
        return result
    def test_connected_actual_go_stage_preflight_saved_apply_readiness_and_durable_receipt(self):
        prepared=self.prepare();records,operation=self.barrier(prepared)
        self.assertEqual(operation['plan']['stateHandle']['ownership'],'managed')
        self.assertTrue(any(record['required'] and record['status']=='passed' for record in prepared.scan_results))
        self.assertEqual(records[0]['stateHandleDigest'],operation['plan']['stateHandleDigest'])
        result=self.apply(prepared)
        self.assertEqual(result[0]['status'],'succeeded')
        self.assertEqual(result[0]['resourceUrl'],'https://api.run.app')
        reservations=prepared.store.entries();self.assertEqual(len(reservations),1)
        self.assertEqual(reservations[0]['payload']['stateHandle'],operation['plan']['stateHandle'])
        self.assertTrue(any(s['state']=='success' for statuses in self.api.statuses.values() for s in statuses))
        native=[a for a,_ in self.runner.calls if a[0]=='terragrunt']
        self.assertTrue(any('show' in a for a in native));self.assertTrue(any('apply' in a for a in native))
        self.assertTrue(any(a[:2]==['skopeo','copy'] and a[-1].startswith('oci-archive:') for a,_ in self.runner.calls))
        self.assertFalse(any(a[:3]==['gcloud','run','deploy'] for a,_ in self.runner.calls))
    def test_fresh_actions_oci_publication_preserves_wire_and_applies(self):
        artifact=self.api.manifest['components'][0]['mainArtifact']
        artifact['location']={'kind':'actions-artifact','repositoryId':'12345','runId':'100','runAttempt':'1',
            'artifactId':'600','artifactName':'components-100-1-api','path':'.cloudopsworks/out/api/main.oci.tar'}
        self.api.rebuild_stage();original=copy.deepcopy(artifact)
        prepared=self.prepare();self.barrier(prepared)
        result=self.apply(prepared)
        self.assertEqual(result[0]['status'],'succeeded')
        self.assertEqual(prepared.manifest['components'][0]['mainArtifact'],original)
        self.assertTrue(self.runner.published_image.endswith('@'+artifact['digest']))
        self.assertTrue(any(a[0]=='terragrunt' and 'apply' in a for a,_ in self.runner.calls))
        self.assertIn(('GET','/actions/artifacts/600/zip'),self.api.api_calls)

    def test_manual_current_scan_exact_binding_applies_without_expanding_manifest(self):
        self.api.manual=True
        self.api.host.update(event='workflow_dispatch',workflowRef=self.api.repository+'/.github/workflows/deploy.yml@refs/heads/develop')
        prepared=self.prepare()
        self.assertTrue(prepared.scan_results)
        # No global preflight jobs are manufactured for a manual exact binding.
        self.assertEqual(self.api.jobs,[])
        result=self.apply(prepared)
        self.assertEqual(result[0]['status'],'succeeded')
        self.assertTrue(self.runner.mutations())
        self.assertFalse(any('monorepo-preflight' in str(call) for call in self.api.api_calls))
        self.assertEqual({r['payload']['stateHandle']['componentId'] for r in self.api.records
            if r.get('task')=='cloudopsworks-state'},{'api'})

    def test_stale_claims_native_handle_and_barrier_stop_all_mutation(self):
        for drift in ('claims','handle','barrier'):
            with self.subTest(drift=drift):
                self.setUp();prepared=self.prepare();self.barrier(prepared)
                if drift=='claims':self.runner.project_number='999999999999'
                elif drift=='handle':prepared._backend=self.backend.replace('state-example','another-state-bucket')
                else:
                    identity=self.api.jobs[-1]['id'];value=json.loads(self.api.logs[identity].decode().split(' ',1)[1])
                    value['stage']['runAttempt']='9';self.api.logs[identity]=('CLOUDOPSWORKS_PREFLIGHT_BARRIER_V1 '+json.dumps(value)).encode()
                with self.assertRaises(ContractError):self.apply(prepared)
                self.assertEqual(self.runner.mutations(),[])
                self.assertEqual(self.api.records,[])
                self.assertFalse(any(a[:2]==['skopeo','copy'] for a,_ in self.runner.calls),'artifact materialization must not precede drift guard')
    def test_unknown_apply_retains_verified_historical_handle_without_success(self):
        prepared=self.prepare();_,operation=self.barrier(prepared);self.runner.fail_apply=True
        with self.assertRaises(ContractError):self.apply(prepared)
        self.assertTrue(any(a[0]=='terragrunt' and 'apply' in a for a,_ in self.runner.calls))
        entries=prepared.store.entries();self.assertEqual(len(entries),1)
        self.assertEqual(entries[0]['payload']['stateHandle'],operation['plan']['stateHandle'])
        self.assertEqual(entries[0]['payload']['stateHandleDigest'],operation['plan']['stateHandleDigest'])
        self.assertFalse(any(s['state']=='success' for statuses in self.api.statuses.values() for s in statuses))
        self.assertTrue(any(s['state']=='failure' for statuses in self.api.statuses.values() for s in statuses))
    def test_native_drift_at_last_saved_plan_guard_prevents_apply(self):
        prepared=self.prepare();self.barrier(prepared);self.runner.drift_before_apply=True
        with self.assertRaises(ContractError):self.apply(prepared)
        self.assertGreaterEqual(self.runner.project_reads,4)
        self.assertTrue(any(a[0]=='terragrunt' and 'show' in a for a,_ in self.runner.calls))
        self.assertEqual(self.runner.mutations(),[])
        self.assertEqual(len(prepared.store.entries()),1,'reserved owner survives rejected saved apply')

    def test_completed_current_scans_are_required_before_preflight_or_mutation(self):
        original=self.api.scan_log
        for failure in ('incomplete-job','required-gate-failure','infrastructure-error'):
            self.api.fail_mode='scanner' if failure=='incomplete-job' else None
            value=json.loads(original.decode().split(' ',1)[1])
            if failure!='incomplete-job':
                result=next(row for row in value['results'] if row['required'])
                result['status']=failure;result['errorCode']='tool-error' if failure=='infrastructure-error' else None
            self.api.scan_log=('CLOUDOPSWORKS_SCAN_V1 '+json.dumps(value)).encode()
            with self.subTest(failure=failure),self.assertRaises(ContractError):self.prepare()
            self.assertEqual(self.runner.mutations(),[]);self.assertEqual(self.api.records,[])


if __name__=='__main__':unittest.main()
