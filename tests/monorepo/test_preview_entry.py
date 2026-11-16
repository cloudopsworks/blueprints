"""Connected fixed preview entry/Go/API evidence; never live OIDC or CNI proof."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
import authorization as auth
from contracts import ContractError,digest
from preview_entry import admission,discover,prepare_target,selected,empty_marker,require_children_empty,no_failed_predecessor,prefix
import test_authorization_preview_closure as closure
from test_authorization import Process,captured


class HostProcess(Process):
    def run(self,argv,**kwargs):
        if argv==['git','rev-parse','HEAD']:return subprocess.CompletedProcess(argv,0,'b'*40+'\n','')
        return super().run(argv,**kwargs)


def environ(host):
    return {dest:host[source] for dest,source in {'GITHUB_RUN_ID':'runId','GITHUB_RUN_ATTEMPT':'runAttempt',
        'GITHUB_EVENT_NAME':'event','GITHUB_REF':'ref','GITHUB_SHA':'headSha',
        'GITHUB_WORKFLOW_REF':'workflowRef','GITHUB_WORKFLOW_SHA':'workflowSha','GITHUB_ACTOR':'actor'}.items()}|{
            'GITHUB_REPOSITORY_ID':host['repository']['id'],'GITHUB_REPOSITORY':host['repository']['fullName']}


@unittest.skipUnless(os.environ.get('TRONADOR_TEST_BINARY'),'actual reviewed Go binary required')
class PreviewEntryTests(unittest.TestCase):
    def fixture(self,*,separate_backend=False):
        result=closure.PreviewClosureIntegrationTests().setup_history(separate_backend=separate_backend)
        api=result[0];original=api.request
        def request(method,path,data=None):
            if path=='/users/github-actions%5Bbot%5D':return {'id':42,'login':'github-actions[bot]'}
            return original(method,path,data)
        api.request=request
        return result

    def test_closed_discovery_proves_actual_history_before_any_artifact_or_scan(self):
        api,_,engine,handles,settings,backend,pair,host=self.fixture()
        route,matrix=discover(api,HostProcess(),environ(host),{'action':'closed','number':42},engine=engine)
        self.assertEqual(matrix,{'include':[{'id':'dev-run','pr':42,'environment':handles[0]['protectedEnvironment']}]})
        prepared,history,root,actor=prepare_target(api,HostProcess(),route,'dev-run')
        self.assertEqual(history,handles);self.assertEqual(root,handles[0]);self.assertEqual(actor,'42')
        choice=selected(prepared,'dev-run','api','INVALID: [YAML',settings,actor,historical=handles[1],root=root)
        self.assertEqual(choice['backend-ref'],'aws-state');self.assertEqual(choice['root-backend-ref'],'aws-state')
        self.assertEqual(choice['root-same-backend'],'true');self.assertEqual(api.artifact_reads,0)
        for target,component,old in [('other','api',handles[1]),('dev-run','wrong',handles[1])]:
            with self.subTest(target=target,component=component),self.assertRaises(ContractError):
                prepared.select_preview_bindings(target,component,backend,settings,automation_id=actor,historical_handle=old)

    def test_independent_root_backend_capture_never_accepts_wrong_principal(self):
        api,process,engine,handles,settings,backend,pair,host=self.fixture()
        prepared=auth.prepare_preview_closure(api,handles,'dev-run',42,blueprint_sha=api.bp,executor=process,engine=engine,current_host=host)
        # Frozen old backend wins invalid/moved current YAML before acquisition.
        chosen=prepared.select_preview_bindings('dev-run','','not backend YAML',settings,automation_id=42,historical_handle=handles[0])
        self.assertEqual(chosen['backend']['authRef'],'aws-state')
        prepared.bind(backend,settings,pair,automation_id=42)
        env=prepared.backend_read_credentials(handles[0],pair['backend'])
        self.assertIsInstance(env,dict)
        for kind in ('alias','account','provider'):
            bad=copy.deepcopy(pair['backend'])
            if kind=='alias':bad['binding']['roleArn']='arn:aws:iam::222222222222:role/not-state'
            elif kind=='account':bad['identity']['accountId']='999999999999'
            else:bad=captured('gcp','123456789012','api')
            with self.subTest(kind=kind),self.assertRaises(ContractError):prepared.backend_read_credentials(handles[0],bad)

    def test_open_discovery_uses_trusted_base_go_policy_and_reopened_close_never_deletes(self):
        api,_,engine,handles,settings,backend,pair,host=self.fixture();api.closed=False
        route,matrix=discover(api,HostProcess(),environ(api.host),{'workflow_run':{'id':100,'run_attempt':1}},engine=engine)
        self.assertEqual(matrix['include'][0]['id'],'dev-run')
        self.assertEqual(route['source']['id'],100);self.assertEqual(api.artifact_reads,0)
        route,matrix=discover(api,HostProcess(),environ(host),{'action':'closed','number':42},engine=engine)
        self.assertEqual(matrix,{'include':[]})
        self.assertEqual(api.artifact_reads,0)

    def test_bad_host_denied_before_stage_even_for_closed_pr(self):
        api,_,engine,handles,settings,backend,pair,host=self.fixture();api.wrong_caller=True
        with self.assertRaises(ContractError):admission(api,HostProcess(),environ(host),{'action':'closed','number':42},engine=engine)
        self.assertEqual(api.artifact_reads,0)

    def test_root_requires_each_exact_attempt_native_empty_receipt(self):
        api,_,engine,handles,settings,backend,pair,host=self.fixture()
        route=admission(api,HostProcess(),environ(host),{'action':'closed','number':42},engine=engine)
        root,child=handles
        marker=empty_marker(route,child,root,{'version':4,'resources':[],'outputs':{}},'namespace-uid')
        original=api.repo
        proof={'id':700,'run_id':201,'run_attempt':1,'name':prefix(route,'dev-run')+'monorepo-preview-cleanup-dev-run-api','status':'completed','conclusion':'success'}
        def repo(method,path,value=None,**kwargs):
            if path.startswith('/actions/runs/201/attempts/1/jobs?'):return {'jobs':[proof]}
            if path=='/actions/jobs/700/logs':return marker.encode()
            return original(method,path,value,**kwargs)
        api.repo=repo
        require_children_empty(api,route,'dev-run',handles,root,'namespace-uid')
        for wrong in ('uid','attempt','failed','missing'):
            old=copy.deepcopy(proof)
            if wrong=='attempt':proof['run_attempt']=2
            if wrong=='failed':proof['conclusion']='failure'
            saved=marker
            if wrong=='missing':marker=''
            with self.subTest(wrong=wrong),self.assertRaises(ContractError):
                require_children_empty(api,route,'dev-run',handles,root,'replacement' if wrong=='uid' else 'namespace-uid')
            proof.clear();proof.update(old);marker=saved
        with self.assertRaises(ContractError):empty_marker(route,child,root,{'version':4,'resources':[{'mode':'managed','type':'helm_release','name':'component','instances':[{'attributes':{}}]}]},'namespace-uid')

    def test_failed_queued_predecessor_cannot_submit_and_other_target_is_independent(self):
        api,_,engine,handles,settings,backend,pair,host=self.fixture()
        route=admission(api,HostProcess(),environ(host),{'action':'closed','number':42},engine=engine)
        original=api.repo
        job={'id':700,'run_id':201,'run_attempt':1,'name':prefix(route,'dev-run')+'monorepo-preview-cleanup-dev-run-api','status':'completed','conclusion':'failure'}
        api.repo=lambda method,path,value=None,**kw: {'jobs':[job]} if '/jobs?' in path else original(method,path,value,**kw)
        with self.assertRaises(ContractError):no_failed_predecessor(api,route,'dev-run','cleanup','worker')
        no_failed_predecessor(api,route,'other-target','cleanup','worker')
        job['status']='in_progress';job['conclusion']=None
        with self.assertRaises(ContractError):no_failed_predecessor(api,route,'dev-run','cleanup','worker')

    def test_actual_phase_entry_uses_private_destroy_values_and_child_empty_guard(self):
        from unittest.mock import patch
        from preview_entry import execute_phase
        from test_authorization_preview_closure import Native
        from operations import validate_operation
        api,process,engine,handles,settings,backend,pair,host=self.fixture(separate_backend=True)
        route=admission(api,HostProcess(),environ(host),{'action':'closed','number':42},engine=engine)
        root,child=handles
        native=Native(root);states={digest(root):native.state,digest(child):{'version':4,'resources':[
            {'mode':'managed','type':'helm_release','name':'component','instances':[{'attributes':{
                'id':'api','namespace':root['resourceIdentity']['namespace'],'description':digest(child),
                'image':'ghcr.io/example/api@sha256:'+'1'*64}}]}],'outputs':{}}}
        original_native=native.run
        def run(argv,**kwargs):
            if argv[:4]==['gcloud','container','clusters','get-credentials']:
                Path(kwargs['env']['KUBECONFIG']).write_text('private')
                return subprocess.CompletedProcess(argv,0,'','')
            return original_native(argv,**kwargs)
        native.run=run;submitted=[];logs=[]
        def execute(plan,**kwargs):
            validate_operation(plan,canonical=kwargs['canonical']);kwargs['before_apply']()
            self.assertEqual(kwargs['values']['owner_digest'],digest(plan['stateHandle']))
            self.assertTrue(kwargs['values']['kubeconfig_path'])
            self.assertEqual(kwargs['credentials']['backend']['provider'],'gcp' if plan['stateHandle']['scope']=='preview-component' else 'aws')
            submitted.append(copy.deepcopy(plan));states[digest(plan['stateHandle'])]={'version':4,'resources':[],'outputs':{}}
            if plan['stateHandle']['scope']=='preview-environment':native.ns=None;native.state=states[digest(root)]
            return {'phase':'destroy'}
        engine.execute=execute
        original_repo=api.repo
        jobs=[{'id':700,'run_id':201,'run_attempt':1,'name':prefix(route,'dev-run')+'monorepo-preview-cleanup-dev-run-api','status':'completed','conclusion':'success'}]
        def repo(method,path,value=None,**kwargs):
            if path.startswith('/actions/runs/201/attempts/1/jobs?'):return {'jobs':jobs}
            if path=='/actions/jobs/700/logs':return '\n'.join(logs).encode()
            return original_repo(method,path,value,**kwargs)
        api.repo=repo
        for phase,component,handle in [('cleanup','api',child),('destroy','',None)]:
            # Separate native workspace/bound context models separate static-auth
            # jobs. No raw state, plan or credential artifact crosses the DAG.
            prepared=auth.prepare_preview_closure(api,handles,'dev-run',42,blueprint_sha=api.bp,executor=process,engine=engine,current_host=host)
            own_pair=api.child_pair if phase=='cleanup' else pair
            choices=selected(prepared,'dev-run',component,'INVALID: [YAML',settings,42,historical=handle,root=root)
            if phase=='cleanup':
                self.assertEqual(choices['backend-ref'],'gcp-state')
                self.assertEqual(choices['root-backend-ref'],'aws-state')
                self.assertEqual(choices['root-same-backend'],'false')
                self.assertEqual(choices['root-same-workload'],'false')
            prepared.bind(backend,settings,own_pair,automation_id=42)
            with tempfile.TemporaryDirectory() as directory:
                work=Path(directory);work.chmod(0o700)
                with patch('preview_runtime.read_private_state',side_effect=lambda h,*a,**kw:copy.deepcopy(states[digest(h)])):
                    execute_phase(api,native,route,prepared,'dev-run',phase,component,handle,own_pair,pair['backend'],work,
                        emit=lambda line,**kw:logs.append(line))
        self.assertEqual([p['stateHandle'] for p in submitted],[child,root])
        self.assertEqual(api.artifact_reads,0)
        self.assertNotIn('CANARY',''.join(logs))
        self.assertEqual(set(states[digest(root)]['resources']),set())
