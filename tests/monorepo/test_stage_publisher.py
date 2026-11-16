"""Stage assembly protocol doubles; exact provider/source validation is separate."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from contracts import ContractError,validate_record
from stage_publisher import assemble_stage
from test_workflows import ArchiveGitHub
from test_snapshot import API
from test_preview import GitHub,preview_plan


class Host:
    def __init__(self,plan):
        self.artifacts=ArchiveGitHub(GitHub().run,plan);self.source=API()
    def repo(self,method,path,**kw):
        return (self.source if path.startswith('/git/') else self.artifacts).repo(method,path,**kw)


class StageTests(unittest.TestCase):
    def setUp(self):
        self.plan=preview_plan();self.host=Host(self.plan);self.run=GitHub().run
        self.scanners=json.loads((Path(__file__).parent/'fixtures/operations/scanners.json').read_text())
        self.resolved={key:copy.deepcopy(self.plan[key]) for key in ('components','targets','previewPolicy')}
        self.resolved['scanners']=self.scanners
        self.calls=[]
    def runner(self):
        owner=self
        class Run:
            def run(self,argv,**kwargs):
                owner.calls.append(argv)
                return subprocess.CompletedProcess(argv,0,json.dumps({'resolved':owner.resolved}),'')
        return Run()
    def assemble(self,root,plan_id='1'):
        return assemble_stage(self.host,self.run,plan_id,repository=self.plan['repository'],version=self.plan['version'],event='pull-request',pr_number=42,work=Path(root),runner=self.runner())
    def test_data_only_source_revalidation_payload_digest_and_closed_actions_location(self):
        with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{'GITHUB_RUN_ID':'12'}):
            manifest,path=self.assemble(root)
            validate_record(manifest)
            artifact=manifest['components'][0]['mainArtifact']
            self.assertEqual(artifact['location']['kind'],'actions-artifact')
            self.assertEqual(artifact['location']['artifactId'],'2')
            self.assertEqual(artifact['location']['artifactName'],'components-12-1-api')
            self.assertEqual(artifact['digest'],self.plan['components'][0].get('digest',artifact['digest']))
            self.assertEqual({p.name for p in path.iterdir()},{'build-plan.json','manifest.json','source-origin.json','scanners.json'})
            self.assertEqual(len(self.calls),1)
            self.assertEqual(self.calls[0][:3],['tronador','components','validate'])
            self.assertNotIn('build',self.calls[0]);self.assertNotIn('test',self.calls[0])
            self.assertEqual((Path(root)/'source-data/components/api/app.py').read_bytes(),b'')
    def test_deleted_plan_id_config_override_and_payload_replacement_fail_closed(self):
        with tempfile.TemporaryDirectory() as root,self.assertRaises(ContractError):self.assemble(root,'999')
        self.resolved['targets'][0]['authRef']='forged-secret-ref'
        with tempfile.TemporaryDirectory() as root,self.assertRaises(ContractError):self.assemble(root)
        self.resolved['targets']=self.plan['targets']
        self.host.artifacts.data[2]=b'not a ZIP'
        with tempfile.TemporaryDirectory() as root,self.assertRaises(Exception):self.assemble(root)


if __name__=='__main__':unittest.main()
