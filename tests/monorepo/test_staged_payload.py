"""Verified byte/publication composition, not a substitute for host authority tests."""
import copy
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
from authorization import PreparedAuthorization
from contracts import ContractError
from providers.common import stage
from release import ArtifactPublisher
from staged_payload import materialize
from test_actions_payload import PayloadHost


class StagedPayloadTests(unittest.TestCase):
    def fixture(self):
        artifact=json.loads((Path(__file__).with_name('contracts')/'valid/oci-image-valid.json').read_text())['mainArtifact']
        artifact['location']={'kind':'actions-artifact','repositoryId':'12345','runId':'12','runAttempt':'1','artifactId':'99','artifactName':'components-12-1-api','path':'.cloudopsworks/out/api/1.2.3/main.oci.tar'}
        request={'repository':{'id':'12345','fullName':'example/mixed-app'},'componentId':'api','artifact':artifact}
        prepared=object.__new__(PreparedAuthorization);prepared._bound=True;prepared._inspection=False
        prepared.plan={'repository':copy.deepcopy(request['repository'])}
        prepared.manifest={'components':[{'componentId':'api','mainArtifact':copy.deepcopy(artifact)}]}
        host=PayloadHost(artifact)
        image=(Path(__file__).with_name('contracts')/'artifacts/image.oci.tar').read_bytes()
        buffer=io.BytesIO()
        with zipfile.ZipFile(buffer,'w') as archive:archive.writestr(artifact['location']['path'],image)
        host.data=buffer.getvalue()
        return prepared,request,host,image

    def test_actions_oci_becomes_registry_image_without_release_or_request_mutation(self):
        prepared,request,host,image=self.fixture();before=copy.deepcopy(request)
        class Registry:
            def __init__(self):self.calls=[];self.authfiles=set()
            def run(self,argv,**kwargs):
                self.calls.append((argv,kwargs))
                if argv[:2]==['skopeo','login']:
                    self.authfiles.add(argv[argv.index('--authfile')+1])
                    self.assert_secret=kwargs['input']
                elif argv[-1].startswith('docker://'):
                    assert '--dest-authfile' in argv
                    assert argv[argv.index('--dest-authfile')+1] in self.authfiles
                    assert Path(argv[-2].removeprefix('oci-archive:')).read_bytes()==image
                else:
                    assert '--src-authfile' in argv
                    Path(argv[-1].removeprefix('oci-archive:')).write_bytes(image)
                return SimpleNamespace(returncode=0,stdout='',stderr='')
        executor=Registry();publisher=ArtifactPublisher(host,executor,'ghcr.io/example/mixed-app')
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'GH_TOKEN':'only-stdin-secret','GITHUB_ACTOR':'publisher'},clear=True):
            ctx=materialize(prepared,publisher,request,workdir=directory)
            ctx['workDir']=Path(directory)
            path,expanded,reference=stage(request,ctx)
            self.assertIsNone(expanded)
            self.assertTrue(reference.endswith('@'+request['artifact']['digest']))
            self.assertEqual(path.read_bytes(),image)
        self.assertEqual(request,before)
        self.assertTrue(all('only-stdin-secret' not in str(argv) for argv,_ in executor.calls))
        self.assertFalse(any('release' in str(argv) for argv,_ in executor.calls))

    def test_no_authority_or_artifact_drift_fails_before_transport(self):
        prepared,request,host,_=self.fixture();publisher=ArtifactPublisher(host,None,'ghcr.io/example/mixed-app')
        for value in ({'authorized':True},prepared):
            if value is prepared:request['artifact']['sourceSha']='f'*40
            with tempfile.TemporaryDirectory() as directory,self.assertRaises(ContractError):
                materialize(value,publisher,request,workdir=directory)

    def test_verified_oci_bytes_without_published_reference_fail_closed(self):
        _,request,_,image=self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'image';path.write_bytes(image)
            for ref in (None,'ghcr.io/example/api:latest','ghcr.io/example/api@sha256:'+'f'*64):
                with self.assertRaises(Exception):stage(request,{'workDir':Path(directory),'artifactPath':path,'artifactImageReference':ref})

if __name__=='__main__':unittest.main()
