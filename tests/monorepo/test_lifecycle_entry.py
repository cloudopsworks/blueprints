import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from lifecycle_entry import prepare
from contracts import ContractError


class SourcePreparationTests(unittest.TestCase):
    def test_frozen_host_head_and_exact_version_command_no_event_before_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);event=root/'event.json';event.write_text(json.dumps({'before':'b'*40}))
            out=root/'outputs';calls=[]
            class Process:
                def run(self,argv,**kwargs):
                    calls.append(argv)
                    if argv[:2]==['git','rev-parse']:return subprocess.CompletedProcess(argv,0,'a'*40+'\n','')
                    (root/'VERSION').write_text('1.2.3+build.7\n')
                    return subprocess.CompletedProcess(argv,0,'{}','')
            host={'GITHUB_EVENT_PATH':str(event),'GITHUB_EVENT_NAME':'push','GITHUB_SHA':'a'*40,'GITHUB_REPOSITORY_ID':'123','GITHUB_REPOSITORY':'example/app'}
            with patch.dict(os.environ,{'GITHUB_OUTPUT':str(out)}):prepare(root,Process(),host)
            outputs=dict(line.split('=',1) for line in out.read_text().splitlines())
            self.assertEqual(outputs['version'],'1.2.3+build.7');self.assertEqual(outputs['base'],'')
            self.assertEqual(outputs['materialize-all'],'true')
            self.assertEqual(calls[1],['tronador','project','version','--workdir',str(root),'--allow-network','--json'])
    def test_wrong_checkout_cannot_select_head_or_create_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);event=root/'event.json';event.write_text('{}')
            class Process:
                def run(self,argv,**kwargs):return subprocess.CompletedProcess(argv,0,'b'*40,'')
            host={'GITHUB_EVENT_PATH':str(event),'GITHUB_EVENT_NAME':'push','GITHUB_SHA':'a'*40,'GITHUB_REPOSITORY_ID':'123','GITHUB_REPOSITORY':'example/app'}
            with self.assertRaises(ContractError):prepare(root,Process(),host)
            self.assertFalse((root/'VERSION').exists())


if __name__=='__main__':unittest.main()
