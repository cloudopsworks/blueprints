"""Job-specific host evidence fixtures, not hosted Actions execution proof."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from contracts import ContractError
from staging import MARKER, marker_record, parse_stage_marker, trusted_stage_bundle


class Host:
    def __init__(self):
        self.archive=b'fixed-staged-archive-fixture'
        self.marker=marker_record(123,100,2,300,'sha256:'+hashlib.sha256(self.archive).hexdigest())
        self.jobs=[{'id':200,'name':'ci / monorepo-stage-publisher','run_id':100,'run_attempt':2,'status':'completed','conclusion':'success'}]
        self.artifact={'id':300,'name':'monorepo-stage-100-2','expired':False,'workflow_run':{'id':100}}
        self.calls=[]
    def repo(self,method,path,**kw):
        self.calls.append(path)
        if '/jobs?' in path:return {'jobs':copy.deepcopy(self.jobs)}
        if path.endswith('/logs'):return ('2026-11-13T00:00:00.0000000Z '+self.marker+'\n').encode()
        if path.endswith('/zip'):return self.archive
        return copy.deepcopy(self.artifact)


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.host=Host();self.run={'id':100,'run_attempt':2,'path':'.github/workflows/pr-build.yml','status':'completed','conclusion':'success','repository':{'id':123},'referenced_workflows':[{'path':'cloudopsworks/blueprints/.github/workflows/monorepo-pr-build.yml@v5.11.0','sha':'b'*40}]}
    def get(self):
        return trusted_stage_bundle(self.host,self.run,caller='pr-build.yml',blueprint_sha='b'*40,source_caller_bytes=b'fixed-reviewed-caller',trusted_caller_bytes=b'fixed-reviewed-caller')

    def test_exact_publisher_logs_bind_immutable_id_and_bytes(self):
        binding,data=self.get();self.assertEqual(binding['artifactId'],'300');self.assertEqual(data,self.host.archive)
        self.assertTrue(any('/attempts/2/jobs?' in p for p in self.host.calls))
        self.assertFalse(any('/artifacts?' in p for p in self.host.calls))

    def test_successful_publisher_remains_usable_after_later_job_failure(self):
        for conclusion in ('failure','cancelled','timed_out'):
            with self.subTest(conclusion=conclusion):
                self.run['conclusion']=conclusion
                binding,data=self.get()
                self.assertEqual(binding['artifactId'],'300')
                self.assertEqual(data,self.host.archive)
        self.run['status']='in_progress'
        with self.assertRaises(ContractError):self.get()

    def test_current_run_uses_exact_needs_output_without_waiting_for_own_deploy(self):
        self.run.update(status='in_progress',conclusion=None)
        args={'caller':'pr-build.yml','blueprint_sha':'b'*40,'source_caller_bytes':b'fixed-reviewed-caller','trusted_caller_bytes':b'fixed-reviewed-caller'}
        with patch.dict('os.environ',{'GITHUB_RUN_ID':'100','GITHUB_RUN_ATTEMPT':'2'}):
            binding,data=trusted_stage_bundle(self.host,self.run,current_artifact_id='300',**args)
            self.assertEqual(binding['artifactId'],'300')
            with self.assertRaises(ContractError):trusted_stage_bundle(self.host,self.run,current_artifact_id='999',**args)
            with self.assertRaises(ContractError):trusted_stage_bundle(self.host,self.run,**args)
        with patch.dict('os.environ',{'GITHUB_RUN_ID':'101','GITHUB_RUN_ATTEMPT':'2'}):
            with self.assertRaises(ContractError):trusted_stage_bundle(self.host,self.run,current_artifact_id='300',**args)

    def test_duplicate_suffix_extra_hop_failed_or_wrong_attempt_jobs_rejected(self):
        base=copy.deepcopy(self.host.jobs[0])
        for jobs in ([base,copy.deepcopy(base)],[{**base,'name':'evil / ci / monorepo-stage-publisher'}],[{**base,'name':'monorepo-stage-publisher'}],[{**base,'conclusion':'failure'}],[{**base,'run_attempt':1}]):
            with self.subTest(jobs=jobs),self.assertRaises(ContractError):
                self.host.jobs=jobs;self.get()

    def test_source_caller_modified_and_decoy_called_code_rejected(self):
        with self.assertRaises(ContractError):
            trusted_stage_bundle(self.host,self.run,caller='pr-build.yml',blueprint_sha='b'*40,source_caller_bytes=b'forged-workflow',trusted_caller_bytes=b'fixed-reviewed-caller')
        self.run['referenced_workflows'][0]['sha']='a'*40
        with self.assertRaises(ContractError):self.get()
        self.assertEqual(self.host.calls,[])

    def test_expired_deleted_replaced_or_changed_archive_no_name_fallback(self):
        for artifact in (None,{**self.host.artifact,'expired':True},{**self.host.artifact,'id':301},{**self.host.artifact,'workflow_run':{'id':99}}):
            self.host.artifact=artifact
            with self.assertRaises(ContractError):self.get()
        self.host=Host();self.host.archive=b'replaced-by-source-job'
        with self.assertRaises(ContractError):self.get()

    def test_closed_marker_no_duplicate_unknown_url_secret_or_identity_fields(self):
        valid=self.host.marker
        for data in ((valid+'\n'+valid).encode(),(valid[:-1]+',"url":"https://evil/?secret=sentinel"}').encode(),valid.replace('"runAttempt":"2"','"runAttempt":"1"').encode(),b'no-marker',b'\xff'):
            with self.subTest(data=data[:40]),self.assertRaises(ContractError) as caught:
                parse_stage_marker(data,repository_id=123,run_id=100,attempt=2)
            self.assertNotIn('sentinel',str(caught.exception))


if __name__=='__main__':unittest.main()
