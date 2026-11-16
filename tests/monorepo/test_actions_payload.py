import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from actions_payload import fetch_payload
from contracts import ContractError


class PayloadHost:
    repository='example/mixed-app'
    def __init__(self,artifact):
        self.run={'id':12,'run_attempt':1,'repository':{'id':12345},'head_sha':artifact['sourceSha'],'status':'completed','conclusion':'failure'}
        self.metadata={'id':99,'name':'components-12-1-api','expired':False,'workflow_run':{'id':12,'head_sha':artifact['sourceSha']}}
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:
            archive.writestr(artifact['location']['path'],(Path(__file__).parent/'contracts/artifacts/app.zip').read_bytes())
        self.data=buffer.getvalue()
    def repo(self,method,path,**kwargs):
        if path.endswith('/zip'):return self.data
        return copy.deepcopy(self.run if '/runs/' in path else self.metadata)


class ActionsPayloadTests(unittest.TestCase):
    def setUp(self):
        self.artifact=json.loads((Path(__file__).parent/'contracts/valid/zip-valid.json').read_text())['mainArtifact']
        self.artifact['location']={'kind':'actions-artifact','repositoryId':'12345','runId':'12','runAttempt':'1','artifactId':'99','artifactName':'components-12-1-api','path':'.cloudopsworks/out/api/1.2.3/main.zip'}
        self.host=PayloadHost(self.artifact)
    def test_exact_payload_is_rehashed_on_every_carry_even_later_run_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            path=fetch_payload(self.host,self.artifact,{'id':'12345','fullName':self.host.repository},Path(directory)/'payload')
            self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertEqual(path.read_bytes(),(Path(__file__).parent/'contracts/artifacts/app.zip').read_bytes())
    def test_publication_copies_actions_payload_to_immutable_release_asset(self):
        from release import ArtifactPublisher
        class PublisherHost(PayloadHost):
            def __init__(self, artifact):
                super().__init__(artifact);self.assets=[];self.uploaded={}
            def pages(self, path):return copy.deepcopy(self.assets)
            def release(self, tag):return {'id':7, 'tag_name':tag}
            def upload_asset(self, release, name, path):
                self.assets.append({'id':1,'name':name});self.uploaded[1]=Path(path).read_bytes()
            def asset_bytes(self, asset):return self.uploaded[asset['id']]
            def repo(self, method, path, **kwargs):
                if path=='':return {'id':12345}
                return super().repo(method,path,**kwargs)
        host=PublisherHost(self.artifact)
        publisher=ArtifactPublisher(host,None,'ghcr.io/example/mixed-app')
        repository={'id':'12345','fullName':host.repository}
        result=publisher.publish(self.artifact,'api','main',Path('/never-source-checkout'),{'id':7},'v1.2.3',repository)
        self.assertEqual(result['location']['kind'],'release-asset')
        self.assertEqual(result['digest'],self.artifact['digest'])
        self.assertEqual(result['location']['tag'],'v1.2.3')
        self.assertEqual(len(host.assets),1)
        publisher.publish(self.artifact,'api','main',Path('/never-source-checkout'),{'id':7},'v1.2.3',repository)
        self.assertEqual(len(host.assets),1)
        with self.assertRaises(ContractError):publisher.verify(self.artifact)

    def test_complete_staged_manifest_publication_preserves_version_and_rejects_target_drift(self):
        from release import publish_staged_release
        from test_release import MemoryGitHub, Publisher, fixture
        plan=fixture('build-plan');staged=fixture('release-manifest')
        # Producer fixture's complete record is the same component contract.
        staged.update(repository=plan['repository'],version=plan['version'],headSha=plan['headSha'],targets=plan['targets'])
        host=MemoryGitHub();publisher=Publisher()
        result=publish_staged_release(plan,staged,host,publisher,Path('/no-source'))
        self.assertFalse(host.release_value['draft'])
        self.assertEqual(result['version'],plan['version'])
        self.assertEqual(result['headSha'],plan['headSha'])
        self.assertEqual(result['components'][0]['mainArtifact']['digest'],staged['components'][0]['mainArtifact']['digest'])
        changed=copy.deepcopy(staged);changed['targets'][0]['configDigest']='sha256:'+'9'*64
        with self.assertRaises(ContractError):publish_staged_release(plan,changed,MemoryGitHub(),publisher,Path('/no-source'))

    def test_expired_replaced_wrong_attempt_or_wrong_bytes_fail_closed(self):
        for mutate in (lambda h:h.metadata.update(expired=True),lambda h:h.metadata.update(id=100),lambda h:h.run.update(run_attempt=2),lambda h:setattr(h,'data',b'invalid-secret-sentinel')):
            self.host=PayloadHost(self.artifact);mutate(self.host)
            with tempfile.TemporaryDirectory() as directory,self.assertRaises(ContractError) as caught:
                fetch_payload(self.host,self.artifact,{'id':'12345','fullName':self.host.repository},Path(directory)/'payload')
            self.assertNotIn('sentinel',str(caught.exception))


if __name__=='__main__':unittest.main()
