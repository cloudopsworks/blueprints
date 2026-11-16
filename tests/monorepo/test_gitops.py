"""Local GitHub doubles: no hosted or live mutation proof."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'cd/monorepo/runtime'))
from gitops import process, GitOpsError

SHA='a'*40
class API:
    repository='acme/app'
    def __init__(self, body='/approve'):
        self.comment={'id':12,'body':body,'user':{'id':7,'login':'reviewer'},'created_at':'now','updated_at':'now','issue_url':'https://api.github.com/repos/acme/app/issues/3'}
        self.pr={'number':3,'state':'open','mergeable':True,'head':{'sha':SHA},'base':{'repo':{'full_name':self.repository}}}
        self.permission='write'; self.reviews=[];self.requested=[{'login':'reviewer'}]; self.comments=[];self.writes=[]
    def request(self, method,path,data=None):
        assert (method,path)==('GET','/user');return {'id':99}
    def repo(self, method,path,data=None):
        if method!='GET':
            self.writes.append((method,path,copy.deepcopy(data)))
            if path.endswith('/comments'):self.comments.append({'body':data['body'],'user':{'id':99}})
            return {}
        if path=='/issues/comments/12':return self.comment
        if path=='/pulls/3':return self.pr
        if path.endswith('/permission'):return {'permission':self.permission}
        if path.endswith('/requested_reviewers'):return {'users':self.requested}
        raise AssertionError(path)
    def pages(self,path):
        return self.reviews if path.endswith('/reviews') else self.comments
    def event(self,dispatch=False):
        e={'repository':{'full_name':self.repository},'action':'created','issue':{'number':3,'pull_request':{}},'comment':copy.deepcopy(self.comment),'sender':{'id':7}}
        e['issue']['pull_request']={'url':'pr'}
        if dispatch:
            e['sender']={'id':99};e['action']=self.comment['body'][1:]+'-command';e['client_payload']={'number':3,'comment_id':12,'author_id':7,'body':self.comment['body'],'head_sha':SHA}
        return e

class GitOpsTests(unittest.TestCase):
    def test_command_dispatches_authenticated_snapshot(self):
        a=API();self.assertTrue(process(a,a.event(),'command'))
        self.assertEqual(a.writes[0][1],'/dispatches');self.assertEqual(a.writes[0][2]['client_payload']['head_sha'],SHA)
    def test_approval_actual_label_and_duplicate_is_noop(self):
        a=API();e=a.event(True);self.assertTrue(process(a,e,'approve'));self.assertIn(('POST','/issues/3/labels',{'labels':['approved']}),a.writes)
        count=len(a.writes);self.assertFalse(process(a,e,'approve'));self.assertEqual(len(a.writes),count)
    def test_current_head_review_accepts(self):
        a=API();a.requested=[];a.reviews=[{'id':1,'user':{'login':'reviewer'},'state':'APPROVED','commit_id':SHA}];self.assertTrue(process(a,a.event(True),'approve'))
    def test_retry_no_arbitrary_runs_and_dedup(self):
        from unittest.mock import patch
        a=API('/retry');e=a.event(True)
        with patch('gitops.automerge_gate',return_value=3) as gate:
            self.assertTrue(process(a,e,'retry'));self.assertFalse(process(a,e,'retry'))
            gate.assert_called_once_with(a,e,'repository_dispatch',number=3)
        self.assertFalse(any('/actions/runs/' in w[1] for w in a.writes))
    def test_denials_before_mutations(self):
        for mutation in ('forged','sender','stale','edited','revoked','permission','args','issue','repository','oldreview'):
            with self.subTest(mutation=mutation):
                a=API();e=a.event(True)
                if mutation=='forged':e['client_payload']['author_id']=8
                if mutation=='sender':e['sender']['id']=7
                if mutation=='stale':e['client_payload']['head_sha']='b'*40
                if mutation=='edited':a.comment['updated_at']='later'
                if mutation=='revoked':a.reviews=[{'id':2,'user':{'login':'reviewer'},'state':'DISMISSED','commit_id':SHA}]
                if mutation=='permission':a.permission='read'
                if mutation=='args':a.comment['body']='/approve admin';e['client_payload']['body']=a.comment['body']
                if mutation=='issue':a.pr['state']='closed'
                if mutation=='repository':e['repository']['full_name']='other/repo'
                if mutation=='oldreview':a.requested=[];a.reviews=[{'id':1,'user':{'login':'reviewer'},'state':'APPROVED','commit_id':'b'*40}]
                with self.assertRaises(GitOpsError):process(a,e,'approve')
                self.assertEqual(a.writes,[])
    def test_phantom_commands_report_unsupported_no_dispatch(self):
        for command in ('deploy','promote','cleanup','cancel','release','help'):
            a=API('/'+command);process(a,a.event(),'command');self.assertEqual(a.writes[0][1],'/issues/3/comments');self.assertIn('unsupported',a.writes[0][2]['body'])
    def test_user_forged_marker_does_not_suppress_authorized_action(self):
        a=API();a.comments=[{'body':f'<!-- cloudopsworks-gitops:12:{SHA}:approve -->','user':{'id':7}}]
        self.assertTrue(process(a,a.event(True),'approve'))
    def test_unsupported_installation_token_fails_before_mutation(self):
        from github import GitHubError
        a=API('/retry')
        def request(method,path,data=None):
            self.assertEqual(path,'/user');raise GitHubError('unsupported for installation')
        a.request=request
        with self.assertRaises(GitOpsError):process(a,a.event(True),'retry')
        self.assertEqual(a.writes,[])
    def test_api_label_error_does_not_write_success_receipt(self):
        from github import GitHubError
        a=API();original=a.repo
        def repo(method,path,data=None):
            if method=='POST' and path.endswith('/labels'):raise GitHubError('mutation failed')
            return original(method,path,data)
        a.repo=repo
        with self.assertRaises(GitHubError):process(a,a.event(True),'approve')
        self.assertEqual(a.comments,[])
    def test_issue_context_denied(self):
        a=API();e=a.event();e['issue'].pop('pull_request')
        with self.assertRaises(GitOpsError):process(a,e,'command')
    def test_forged_dispatch_name_denied(self):
        a=API();e=a.event(True);e['action']='lgtm-command'
        with self.assertRaises(GitOpsError):process(a,e,'approve')

if __name__=='__main__':unittest.main()
