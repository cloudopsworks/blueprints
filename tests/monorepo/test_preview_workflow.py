"""Local admission/saved-plan recording boundaries, NOT hosted/CNI proof."""
import copy
import os
import sys
import tempfile
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from authorization import PreparedAuthorization
from contracts import ContractError,digest
from preview import IaCPreview,namespace,owner
from preview_workflow import dispatch_admitted
from test_preview import GitHub,Kube,preview_plan,policy
from test_release import fixture


class Engine:
    def __init__(self):self.calls=[];self.before=None;self.after=None;self.failure=False
    def execute(self,plan,**kwargs):
        # Represents a saved plan becoming ready, not a native CLI/provider run.
        if self.before:self.before(plan)
        kwargs['before_apply']()
        self.calls.append(copy.deepcopy(plan))
        if self.failure:raise RuntimeError('uncertain provider submission')
        if self.after:self.after(plan)
        return {'phase':plan['operation']}


def runtime(gh=None):
    gh=gh or GitHub();repo=preview_plan()['repository'];ex=Kube();engine=Engine()
    prepared=object.__new__(PreparedAuthorization)
    handle=fixture_handle(repo)
    owned={'namespace':handle['resourceIdentity']['namespace'],'uid':'uid-1','owner_digest':digest(handle)}
    ex.ns={'metadata':{'name':owned['namespace'],'uid':owned['uid'],'labels':owner(repo,42,'prod-run'),
        'annotations':{'cloudopsworks.io/owner-digest':digest(handle)}}}
    native={digest(handle):owned};handles=[handle]
    def recover(h):
        return {'plan':{'operation':'destroy','stateHandle':copy.deepcopy(h)},'canonical':{},'store':object(),
            'resourceClaims':['claim'],'existing':{},'credentials':{},'engine':engine}
    context={'prepared':prepared,'credentials':{},'cloud':ex,'kubeconfigPath':'/private/kubeconfig','engine':engine,
        'resolve_preview':lambda *a:None,'recover_preview':recover,'preview_handles':lambda target:copy.deepcopy(handles),
        'native_owned':lambda h:copy.deepcopy(native.get(digest(h)))}
    return gh,repo,ex,engine,context,handles,native


def fixture_handle(repo):
    from contracts import load_record
    h=load_record(Path(__file__).with_name('fixtures')/'operations/state-preview.json')
    h['origin']['repository']=repo;h['targetId']='prod-run';h['prNumber']=42
    h['resourceIdentity']['namespace']=namespace(repo['id'],42,'prod-run')
    return h


class PreviewWorkflowTests(unittest.TestCase):
    def test_three_invocations_pending_close_replaced_converges_before_artifacts(self):
        gh,repo,ex,engine,context,handles,native=runtime()
        attempts=[]
        def admit(r,p,t):
            self.assertEqual((r,p,t),(repo,42,'prod-run'));attempts.append('admit-C')
        def close(*args):attempts.append('standing-close');return context
        def artifacts(*args):raise AssertionError('expired artifacts/scans/stale head must not gate closure')
        class Group:
            # Model GitHub's one-active/one-replaceable-pending semantics, not a
            # lossless queue and not hosted scheduling evidence.
            def __init__(self):self.active=None;self.pending=None;self.replaced=[]
            def submit(self,name,callback):
                if self.active:
                    if self.pending:self.replaced.append(self.pending[0])
                    self.pending=(name,callback)
                else:self.active=name;callback()
            def release(self):
                self.active=None
                if self.pending:
                    name,callback=self.pending;self.pending=None;self.submit(name,callback)
        group=Group()
        group.submit('A',lambda:attempts.append('A-active'))
        gh.pr['state']='closed'
        group.submit('B',lambda:self.fail('replaced close B must never be admitted'))
        gh.pr['head']['sha']='f'*40
        outcomes=[]
        group.submit('C',lambda:outcomes.append(dispatch_admitted(gh,repo,42,'prod-run',
            admit=admit,close_runtime=close,preview_runtime=artifacts)))
        self.assertEqual(group.replaced,['B']);self.assertFalse(engine.calls)
        engine.after=lambda plan:(setattr(ex,'ns',None),native.clear())
        group.release()
        self.assertEqual(outcomes[0]['phase'],'closed')
        self.assertEqual(attempts,['A-active','admit-C','standing-close'])
        self.assertEqual(len(engine.calls),1)
        self.assertEqual(engine.calls[0]['stateHandle'],handles[0])
        self.assertFalse(any(a[1] in ('delete','create','apply','label') for a,_ in ex.calls))

    def test_reopened_replacement_does_not_delete(self):
        gh,repo,ex,engine,context,_,_=runtime();events=[]
        # Same A/B/C replacement sequence, but C observes reopened PR.
        gh.pr['state']='open'
        result=dispatch_admitted(gh,repo,42,'prod-run',admit=lambda *a:None,
            close_runtime=lambda *a:self.fail('reopened must not authorize closure'),
            preview_runtime=lambda *a:events.append('preview-current-state'))
        self.assertIsNone(result);self.assertEqual(events,['preview-current-state']);self.assertFalse(engine.calls)

    def test_wrong_caller_denied_before_api_artifact_or_cleanup(self):
        gh,repo,ex,engine,context,_,_=runtime()
        def deny(*a):raise ContractError('caller','unapproved caller')
        with self.assertRaises(ContractError):
            dispatch_admitted(gh,repo,42,'prod-run',admit=deny,
                close_runtime=lambda *a:self.fail('wrong caller'),preview_runtime=lambda *a:self.fail('wrong caller'))
        self.assertFalse(engine.calls);self.assertFalse(ex.calls)

    def test_exact_manual_scope_is_not_borrowed_for_standing_closure(self):
        gh,repo,ex,engine,context,handles,_=runtime();gh.pr['state']='closed'
        def manual(h):
            bound=context_original(h)
            bound['plan']['operation']='unlock'
            return bound
        context_original=context['recover_preview'];context['recover_preview']=manual
        with self.assertRaises(ContractError):IaCPreview(gh,repo,42,'prod-run','a'*40,context).close()
        self.assertFalse(engine.calls)

    def test_child_failure_stops_root_destroy_retains_all_handles(self):
        gh,repo,ex,engine,context,handles,_=runtime();gh.pr['state']='closed'
        child=copy.deepcopy(handles[0]);child.update(scope='preview-component',componentId='api')
        handles.append(child);engine.failure=True
        with self.assertRaises(RuntimeError):IaCPreview(gh,repo,42,'prod-run','a'*40,context).close()
        self.assertEqual(len(engine.calls),1);self.assertEqual(engine.calls[0]['stateHandle']['componentId'],'api')
        self.assertEqual(len(handles),2);self.assertIsNotNone(ex.ns)

    def test_fresh_guard_detects_reopen_or_uid_replacement_before_submission(self):
        for change in ('reopen','uid','owner','state','history'):
            gh,repo,ex,engine,context,handles,native=runtime();gh.pr['state']='closed'
            def before(plan):
                if change=='reopen':gh.pr['state']='open'
                elif change=='uid':ex.ns['metadata']['uid']='replacement'
                elif change=='owner':ex.ns['metadata']['annotations']['cloudopsworks.io/owner-digest']='sha256:'+'0'*64
                elif change=='state':native.clear()
                else:handles[0]['origin']['repository']['id']='999'
            engine.before=before
            if change=='history':handles[0]['origin']['repository']={'id':'999','fullName':'foreign/repo'}
            with self.assertRaises(ContractError):IaCPreview(gh,repo,42,'prod-run','a'*40,context).close()
            self.assertFalse(engine.calls)

    def test_postsubmission_reopen_stops_later_mutation_without_atomic_claim(self):
        gh,repo,ex,engine,context,handles,_=runtime();gh.pr['state']='closed'
        child=copy.deepcopy(handles[0]);child.update(scope='preview-component',componentId='api');handles.append(child)
        engine.after=lambda plan:gh.pr.update(state='open')
        with self.assertRaises(ContractError):IaCPreview(gh,repo,42,'prod-run','a'*40,context).close()
        self.assertEqual(len(engine.calls),1);self.assertEqual(len(handles),2)

    def test_empty_historical_group_closed_is_idempotent(self):
        gh,repo,ex,engine,context,handles,_=runtime();gh.pr['state']='closed';handles.clear();ex.ns=None
        IaCPreview(gh,repo,42,'prod-run','a'*40,context).close()
        self.assertFalse(engine.calls)

    @unittest.skipUnless(os.environ.get('TRONADOR_TEST_BINARY'),'actual reviewed Go binary required')
    def test_actual_go_root_inputs_and_managed_children_from_external_cluster(self):
        from test_authorization import AuthorizationTests
        harness=AuthorizationTests();harness.setUp();obj=harness.prepared()
        obj.plan=preview_plan();obj.lifecycle=copy.deepcopy(harness.context['lifecycle'])
        obj.lifecycle.update(refClass='preview',environment='prod',deploymentName='pull_request/prod',protectedEnvironment='pull_request/prod')
        obj._module_origin=lambda module:copy.deepcopy(harness.context['origin'])
        target=obj.plan['targets'][0];target['ownership']='external'
        for component in ('','api'):
            operation=obj._operation(target=target,component=component,operation='preview',
                provider_identity=harness.context['providerIdentity'],backend=harness.context['backend'],auth_refs=harness.context['authRefs'])
            self.assertEqual(operation['stateHandle']['ownership'],'managed')
            self.assertEqual(operation['stateHandle']['resourceIdentity']['namespace'],namespace(obj.repository['id'],42,target['id']))
            if not component:self.assertEqual(operation['inputs']['workload'],{'kind':'artifact'})
            else:self.assertEqual(operation['inputs']['workload'],{'kind':'http','port':8080,'healthPath':'/health'})
            # Feed the actual Go operation into the actual pinned root metadata
            # renderer. This is a local values proof, not a Terraform/cloud apply.
            import json
            catalog=json.loads((ROOT/'terraform/monorepo/module-catalog.json').read_text())
            # Catalog activation is R3's integration gate, not supplied by this
            # values-only test. Point the test row at the existing actual root.
            if not component:catalog['modules'][operation['stateHandle']['moduleId']]['path']='terraform/monorepo/modules/kubernetes-preview-environment'
            engine=SimpleNamespace(root=ROOT,catalog=catalog)
            gh,repo,ex,_,context,_,_=runtime()
            context.update(prepared=obj,engine=engine)
            controller=IaCPreview(gh,repo,42,target['id'],'a'*40,context)
            artifact=fixture('component-result')['previewArtifact']
            artifact['location']={'kind':'oci','reference':'ghcr.io/example/api@'+artifact['digest']}
            with tempfile.TemporaryDirectory() as directory:
                values=controller._values({'plan':operation,'engine':engine},artifact,policy(),directory)
            self.assertEqual(values['resource']['namespace'],operation['stateHandle']['resourceIdentity']['namespace'])
            if component:
                self.assertEqual(values['workload'],operation['inputs']['workload'])
                self.assertEqual(values['preview_options']['host'],'api.'+values['resource']['namespace']+'.preview.example.com')
            else:
                self.assertEqual(values['workload'],{'kind':'artifact'})
                self.assertEqual(values['namespace'],values['resource']['namespace'])
                self.assertEqual(values['isolation']['ingressNamespace'],'ingress-nginx')
        self.assertEqual(target['ownership'],'external')


if __name__=='__main__':unittest.main()
