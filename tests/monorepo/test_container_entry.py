"""Manual publication cannot substitute a green publisher for required scans."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
import container_entry
from contracts import ContractError
from test_normal_entry_integration import ConnectedAPI
from release import ArtifactPublisher
from test_operation_entry import ManualProcess

class ContainerAPI(ConnectedAPI):
    def repo(self,method,path,value=None,**kwargs):
        if path.startswith('/actions/runs/200/') and '/jobs?' not in path:
            run=copy.deepcopy(self.run);run.update(id=200,event='workflow_dispatch',path='.github/workflows/deploy-container.yml',
                referenced_workflows=[{'path':'cloudopsworks/blueprints/.github/workflows/monorepo-container.yml@v5.11.0','sha':self.bp}])
            return run
        if path.startswith('/actions/workflows/main-build.yml/runs?'):return {'workflow_runs':[copy.deepcopy(self.run)]}
        response=super().repo(method,path,value,**kwargs)
        if '/actions/runs/100/' in path and '/jobs?' in path:
            response=copy.deepcopy(response)
            response['jobs'].append({'id':301,'run_id':100,'run_attempt':1,'status':'completed',
                'conclusion':'failure' if self.fail_mode=='scanner' else 'success','name':'lifecycle / monorepo-scan-barrier'})
        return response

@unittest.skipUnless(os.environ.get('TRONADOR_TEST_BINARY'),'reviewed CLI required')
class ContainerEntryTests(unittest.TestCase):
    def setUp(self):
        self.api=ContainerAPI();h=self.api.host
        h.update(event='workflow_dispatch',workflowRef=self.api.repository+'/.github/workflows/deploy-container.yml@refs/heads/develop')
        self.runner=ManualProcess(self.api)
        self.env={'GITHUB_REPOSITORY_ID':h['repository']['id'],'GITHUB_REPOSITORY':h['repository']['fullName'],
            'GITHUB_RUN_ID':h['runId'],'GITHUB_RUN_ATTEMPT':h['runAttempt'],'GITHUB_EVENT_NAME':h['event'],
            'GITHUB_REF':h['ref'],'GITHUB_SHA':h['headSha'],'GITHUB_WORKFLOW_REF':h['workflowRef'],
            'GITHUB_WORKFLOW_SHA':h['workflowSha'],'GITHUB_ACTOR':h['actor']}
    def test_actual_go_api_stage_original_completed_scan_proof(self):
        prepared,artifact=container_entry.prepare(self.api,self.runner,self.env,'api')
        self.assertEqual(prepared.host['runId'],'100');self.assertEqual(prepared.current_host['runId'],'200')
        self.assertTrue(any(r['required'] and r['status']=='passed' for r in prepared.scan_results))
        self.assertEqual(artifact['format'],'oci');self.assertFalse(self.runner.mutations())
    def test_fresh_actions_payload_publishes_verified_bytes_only_after_gate(self):
        artifact=self.api.manifest['components'][0]['mainArtifact']
        artifact['location']={'kind':'actions-artifact','repositoryId':'12345','runId':'100','runAttempt':'1',
            'artifactId':'600','artifactName':'components-100-1-api','path':'.cloudopsworks/out/api/main.oci.tar'}
        self.api.rebuild_stage();original=copy.deepcopy(artifact)
        prepared,selected=container_entry.prepare(self.api,self.runner,self.env,'api')
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'CLOUDOPSWORKS_DIAGNOSTICS':directory}):
            result=container_entry.publish(prepared,selected,'api',ArtifactPublisher(self.api,self.runner,'ghcr.io/example/mixed-app'))
        self.assertEqual(result['location']['reference'],'ghcr.io/example/mixed-app/api@'+artifact['digest'])
        self.assertEqual(selected,original)
        self.assertIn(('GET','/actions/artifacts/600/zip'),self.api.api_calls)
        calls=[argv for argv,_ in self.runner.calls]
        self.assertTrue(any(argv[:2]==['skopeo','copy'] and argv[-1].startswith('docker://') for argv in calls))
        self.assertTrue(any(argv[:2]==['skopeo','inspect'] for argv in calls))
        self.assertFalse(any(argv[0] in ('terragrunt','tofu','aws','gcloud','az') for argv in calls))

    def test_missing_pending_failed_wrong_attempt_or_policy_marker_denies_before_registry(self):
        for mode in ('scanner','scan-pending','scan-attempt','scan-policy','missing-component'):
            with self.subTest(mode=mode):
                api=ContainerAPI();api.host.update(self.api.host)
                original=api.repo
                def boundary(method,path,value=None,**kwargs):
                    response=original(method,path,value,**kwargs)
                    if '/actions/runs/100/' in path and '/jobs?' in path and mode in ('scan-pending','scan-attempt'):
                        response=copy.deepcopy(response)
                        for job in response['jobs']:
                            if job['name'].endswith('monorepo-scan-barrier'):
                                if mode=='scan-pending':job.update(status='in_progress',conclusion=None)
                                else:job['run_attempt']=2
                    if path.startswith('/actions/jobs/') and mode=='scan-policy' and isinstance(response,bytes) and b'CLOUDOPSWORKS_SCAN_V1 ' in response:
                        response=response.replace(b'"policyDigest":"sha256:',b'"policyDigest":"sha256:0')
                    return response
                api.repo=boundary
                if mode=='scanner':api.fail_mode='scanner'
                runner=ManualProcess(api)
                with self.assertRaises(ContractError):container_entry.prepare(api,runner,self.env,'missing' if mode=='missing-component' else 'api')
                self.assertFalse(any(a[0]=='skopeo' for a,_ in runner.calls));self.assertEqual(api.records,[])

if __name__=='__main__':unittest.main()
