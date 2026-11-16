"""Baseline selection composes existing exact host-log and byte-verification seams."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from contracts import ContractError,canonical_bytes,digest
from stage_baseline import load,find
from staging import marker_record
from test_staging import Host
from test_actions_payload import PayloadHost
from test_release import fixture


class BaselineHost(Host):
    repository='example/mixed-app'
    def __init__(self):
        super().__init__();self.plan=fixture('build-plan');self.manifest=fixture('release-manifest')
        artifact=fixture('oci-image-valid')['mainArtifact']
        artifact['location']={'kind':'actions-artifact','repositoryId':'12345','runId':'12','runAttempt':'1','artifactId':'99','artifactName':'components-12-1-api','path':'.cloudopsworks/out/api/1.2.3/main.oci.tar'}
        self.manifest.update(repository=self.plan['repository'],headSha=self.plan['headSha'],version=self.plan['version'],targets=self.plan['targets'])
        self.manifest['components'][0].update(mainArtifact=artifact,previewArtifact=copy.deepcopy(artifact))
        capsule={'repository':self.plan['repository'],'runId':'100','runAttempt':'2','event':'push','ref':'refs/heads/develop',
            'headSha':self.plan['headSha'],'workflowRef':'example/mixed-app/.github/workflows/main-build.yml@refs/heads/develop',
            'workflowSha':self.plan['headSha'],'sourceSha':self.plan['headSha'],'blueprintSha':'b'*40,'callerPath':'.github/workflows/main-build.yml',
            'lifecycle':{},'planDigest':digest(self.plan),'manifestDigest':digest(self.manifest)}
        files={'build-plan.json':self.plan,'manifest.json':self.manifest,'source-origin.json':{},'scanners.json':{},'host.json':capsule}
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:
            for name,value in files.items():archive.writestr(name,canonical_bytes(value))
        self.archive=buffer.getvalue();self.marker=marker_record(12345,100,2,300,digest_bytes(self.archive))
        self.jobs[0]['name']='lifecycle / monorepo-stage-publisher'
        self.payload=PayloadHost(artifact)
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:archive.writestr(artifact['location']['path'],(Path(__file__).with_name('contracts')/'artifacts/image.oci.tar').read_bytes())
        self.payload.data=buffer.getvalue()
        self.run={'id':100,'run_attempt':2,'head_sha':self.plan['headSha'],'head_branch':'develop','path':'.github/workflows/main-build.yml',
            'status':'completed','conclusion':'failure','repository':{'id':12345},
            'referenced_workflows':[{'path':'cloudopsworks/blueprints/.github/workflows/monorepo-main-build.yml@v5.11.0','sha':'b'*40}]}
    def repo(self,method,path,**kwargs):
        if path=='':return {'default_branch':'main'}
        if path=='/branches/main':return {'commit':{'sha':'c'*40}}
        if path.startswith('/actions/workflows/'):return {'workflow_runs':[copy.deepcopy(self.run)]}
        if path.startswith('/compare/'):return {'status':'ahead','merge_base_commit':{'sha':self.plan['headSha']}}
        if '/artifacts/99' in path or '/runs/12/' in path:return self.payload.repo(method,path,**kwargs)
        return super().repo(method,path,**kwargs)


def digest_bytes(value):return 'sha256:'+__import__('hashlib').sha256(value).hexdigest()


class StageBaselineTests(unittest.TestCase):
    def test_completed_publisher_later_deploy_failed_still_carries_rehashed_oci(self):
        github=BaselineHost()
        with patch('stage_baseline._file',return_value=b'exact-reviewed-caller'):
            previous=load(github,github.run,repository=github.plan['repository'],blueprint_sha='b'*40)
            self.assertEqual(previous,github.manifest)
            github.payload.metadata['expired']=True
            with self.assertRaises(ContractError):load(github,github.run,repository=github.plan['repository'],blueprint_sha='b'*40)

    def test_source_and_data_only_publisher_choose_same_exact_ancestor_or_all_fallback(self):
        github=BaselineHost();current={'id':101,'path':'.github/workflows/main-build.yml','head_branch':'develop'}
        class Git:
            def run(self,argv,**kwargs):return subprocess.CompletedProcess(argv,0,'','')
        arguments=dict(repository=github.plan['repository'],head='d'*40,runner=Git(),blueprint_sha='b'*40)
        with patch('stage_baseline._file',return_value=b'exact-reviewed-caller'):
            selected=find(github,current,root=Path('/source'),**arguments)
            self.assertEqual(selected['headSha'],github.plan['headSha'])
            self.assertEqual(find(github,current,root=None,exact_head=selected['headSha'],**arguments),selected)
            github.payload.metadata['expired']=True
            self.assertIsNone(find(github,current,root=None,**arguments))

    def test_modified_caller_failed_publisher_and_nonancestor_never_authorize_carry(self):
        for mode in ('caller','publisher','ancestor'):
            github=BaselineHost();current={'id':101,'path':'.github/workflows/main-build.yml','head_branch':'develop'}
            class Git:
                def run(self,argv,**kwargs):return subprocess.CompletedProcess(argv,1 if mode=='ancestor' else 0,'','')
            if mode=='publisher':github.jobs[0]['conclusion']='failure'
            with patch('stage_baseline._file',side_effect=[b'hostile' if mode=='caller' else b'fixed',b'fixed']):
                self.assertIsNone(find(github,current,repository=github.plan['repository'],head='d'*40,root=Path('/source'),runner=Git(),blueprint_sha='b'*40))

if __name__=='__main__':unittest.main()
