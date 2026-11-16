"""Ready metadata/spec transport regression; no host/Go/OIDC proof claim."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from contracts import ContractError,digest,validate_record
from preview import PreviewStore,namespace
from preview_entry import save_ready,prefix
from test_preview import preview_plan,policy
from test_preview_workflow import fixture_handle
from test_release import fixture,MemoryGitHub


@unittest.skipUnless(os.environ.get('TRONADOR_TEST_BINARY'),'reviewed Go data validator required')
class PreviewMetadataTests(unittest.TestCase):
    def test_fixed_entry_spec_carry_rehash_link_ready_receipt_and_expiry(self):
        spec=b'{"openapi":"3.0.3","info":{"title":"API","version":"1"},"paths":{}}'
        plan=preview_plan();component=plan['components'][0]
        component.update(package={'kind':'openapi','file':'openapi.json','version':'3.0'},
            preview={'mode':'artifact-only','reason':'openapi'},workload={'kind':'artifact'},targetIds=[])
        validate_record(plan)
        artifact=fixture('component-result')['mainArtifact'];artifact.update(kind='openapi',format='openapi-json',
            digest='sha256:'+hashlib.sha256(spec).hexdigest(),sizeBytes=len(spec),location={'kind':'actions-artifact',
                'repositoryId':'12345','runId':'12','runAttempt':'1','artifactId':'99','artifactName':'components-12-1-api',
                'path':'.cloudopsworks/out/api/1.2.3/main.json'})
        root=fixture_handle(plan['repository']);root['resourceIdentity']['namespace']=namespace('12345',42,'prod-run')
        owned={'namespace':root['resourceIdentity']['namespace'],'uid':'namespace-uid','ownedIds':{'policies':['ns/deny']}}
        isolation=fixture('preview-state')['isolation'];isolation['policyDigest']=digest({'isolation':policy()['isolation'],
            'ownerDigest':digest(root),'policies':owned['ownedIds']['policies']})
        route={'repository':plan['repository'],'pr':42,'host':{'runId':'201','runAttempt':'1',
            'workflowRef':'example/mixed-app/.github/workflows/pr-build.yml@refs/heads/develop'}}
        proof={'repositoryId':'12345','runId':'201','runAttempt':'1','pr':42,'target':'prod-run','sourceSha':plan['headSha'],
            'rootDigest':digest(root),'namespaceUid':owned['uid'],'isolation':isolation}
        class API(MemoryGitHub):
            repository='example/mixed-app';expired=False;corrupt=False;downloads=0
            def request(self,method,path):return {'id':99,'login':'github-actions[bot]'}
            def repo(self,method,path,data=None,**kwargs):
                if '/attempts/1/jobs?' in path:return {'jobs':[{'id':700,'run_id':201,'run_attempt':1,'status':'completed','conclusion':'success',
                    'name':prefix(route,'prod-run')+'monorepo-preview-root-prod-run'}]}
                if path=='/actions/jobs/700/logs':return b'CLOUDOPSWORKS_PREVIEW_READY_ISOLATION_V1 '+json.dumps(proof).encode()
                if path=='/actions/runs/12':return {'event':'pull_request','status':'completed','conclusion':'success','repository':{'id':12345},
                    'head_repository':{'id':12345},'head_sha':plan['headSha'],'pull_requests':[{'number':42}]}
                if path=='/actions/artifacts/99':return {'name':'components-12-1-api','expired':self.expired,'workflow_run':{'id':12,'head_sha':plan['headSha']}}
                if path=='/actions/artifacts/99/zip':
                    self.downloads+=1;out=io.BytesIO()
                    with zipfile.ZipFile(out,'w') as z:z.writestr(artifact['location']['path'],b'corrupt' if self.corrupt else spec)
                    return out.getvalue()
                return super().repo(method,path,data)
        api=API();guards=[]
        ctrl=SimpleNamespace(root_handle=root,owned=owned,context={},_guard=lambda:guards.append('fresh'))
        prepared=SimpleNamespace(plan=plan,manifest={'components':[{'componentId':'api','mainArtifact':artifact,'previewArtifact':None}]},repository=plan['repository'])
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'CLOUDOPSWORKS_DIAGNOSTICS':directory}):
            work=Path(directory)
            for _ in range(2):save_ready(api,None,route,prepared,'prod-run',ctrl,policy(),work)
            self.assertEqual(api.downloads,2)
            saved=PreviewStore(api,plan['repository'],42,'prod-run',99).load()
            self.assertEqual(saved['state']['components'][0]['status'],'artifact-only')
            self.assertIsNone(saved['state']['components'][0]['releaseName'])
            self.assertEqual(saved['artifactSources']['api']['url'],'https://github.com/example/mixed-app/actions/runs/12/artifacts/99')
            events=[json.loads(row) for row in (work/'events.jsonl').read_text().splitlines()]
            self.assertEqual(events[0]['artifactUrl'],saved['artifactSources']['api']['url'])
            self.assertEqual(events[0]['namespace'],owned['namespace']);self.assertEqual(events[0]['provider'],root['resourceIdentity']['provider'])
            for mode in ('expired','corrupt','wrong-root-uid'):
                api.expired=mode=='expired';api.corrupt=mode=='corrupt';old=proof['namespaceUid']
                if mode=='wrong-root-uid':proof['namespaceUid']='replacement'
                before=len(api.deployments)
                with self.subTest(mode=mode),self.assertRaises(ContractError):save_ready(api,None,route,prepared,'prod-run',ctrl,policy(),work)
                self.assertEqual(len(api.deployments),before);proof['namespaceUid']=old
        self.assertEqual(guards,['fresh','fresh'])
