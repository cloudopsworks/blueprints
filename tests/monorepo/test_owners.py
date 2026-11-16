"""Owners API fixtures are local contract proof, not GitHub activation proof."""
import copy
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'cd/monorepo/runtime'))
from owners import preflight, apply_environments, OwnersError

class API:
    repository='acme/app'
    def __init__(self):
        self.writes=[];self.private=True;self.admin=True;self.environments={};self.variables={};self.branches=[];self.rules=[]
    def request(self,method,path,data=None):
        if path=='/graphql':return {'data':{'repository':{'branchProtectionRules':{'totalCount':len(self.branches),'pageInfo':{'hasNextPage':False},'nodes':self.branches}}}}
        return {'id':7}
    def pages(self,path):
        assert path=='/rulesets';return self.rules
    def repo(self,method,path,data=None):
        if method=='GET':
            if path=='':return {'private':self.private,'permissions':{'admin':self.admin}}
            if path.startswith('/rulesets/'):return next(r for r in self.rules if str(r['id'])==path.split('/')[-1])
            if path.endswith('/variables'):return {'variables':[{'name':k,'value':v} for k,v in self.variables.items()]}
            return self.environments.get(path)
        self.writes.append((method,path,copy.deepcopy(data)))
        if path.endswith('/variables') or '/variables/' in path:self.variables[data['name']]=data['value']
        return {}


def policy():
    return {'branchProtection':True,'requiredReviewers':1,'reviewers':['alice'],'owners':['admin'],
        'protectedSources':['.github/**','.cloudopsworks/**'],'contributors':{'push':['acme/devs']},
        'environments':[{'name':n,'reviewers':n.startswith(('release/','support/')),'variables':{'NAME':n}} for n in ['develop/dev','release/prod','release/blue/prod','prerelease/demo','support/uat','pull_request/preview']]}

class OwnerTests(unittest.TestCase):
    def test_actual_canonical_environment_and_variable_writes(self):
        a=API();p=policy();prepared=preflight(a,p);self.assertEqual(a.writes,[]);apply_environments(a,prepared)
        puts=[w for w in a.writes if w[0]=='PUT'];self.assertEqual(len(puts),6)
        self.assertEqual(puts[1][1],'/environments/release%2Fprod');self.assertEqual(puts[1][2]['reviewers'],[{'type':'User','id':7}]);self.assertTrue(puts[1][2]['prevent_self_review'])
        self.assertEqual(puts[0][2]['reviewers'],[])
        self.assertTrue(all(w[2]['deployment_branch_policy']['protected_branches'] for w in puts))
    def test_equal_variables_no_duplicate_mutation(self):
        a=API();p=policy();p['environments']=p['environments'][:1];prepared=preflight(a,p);apply_environments(a,prepared);a.writes=[];apply_environments(a,prepared)
        self.assertEqual(len(a.writes),1);self.assertEqual(a.writes[0][0],'PUT')
    def test_all_preflight_denials_before_any_write(self):
        for bad in ('public','admin','disabled','paths','count','reviewers','duplicate','noncanonical','variable','weaker_env','branches','contexts','sources','commits'):
            with self.subTest(bad=bad):
                a=API();p=policy()
                if bad=='public':a.private=False
                if bad=='admin':a.admin=False
                if bad=='disabled':p['branchProtection']=False
                if bad=='paths':p['protectedSources']=['*.tf']
                if bad=='count':p['requiredReviewers']=0
                if bad=='reviewers':p['reviewers']=[]
                if bad=='duplicate':p['environments'].append(p['environments'][0])
                if bad=='noncanonical':p['environments'][0]['name']='prod'
                if bad=='variable':p['environments'][-1]['variables']={'BAD\nKEY':'x'}
                if bad=='weaker_env':a.environments['/environments/release%2Fprod']={'protection_rules':[{'type':'required_reviewers','reviewers':[{'type':'User','reviewer':{'id':8}}]}]}
                if bad in ('branches','contexts'):
                    a.branches=[{'pattern':'main','requiresApprovingReviews':True,'requiredApprovingReviewCount':0 if bad=='branches' else 1,'isAdminEnforced':True,'requiredStatusCheckContexts':[],'requiresStatusChecks':True,'requiresStrictStatusChecks':True,'allowsForcePushes':False}]
                if bad=='sources':a.rules=[{'id':1,'name':'protected-sources','target':'push','enforcement':'active','rules':[{'type':'file_path_restriction','parameters':{'restricted_file_paths':['*.tf']}}]}]
                if bad=='commits':p['conventionalCommitsEnabled']=True;a.rules=[{'id':1,'name':'commit-message-rules','enforcement':'evaluate','rules':[]}]
                with self.assertRaises(OwnersError):preflight(a,p)
                self.assertEqual(a.writes,[])
    def test_stronger_branch_policy_preserved(self):
        a=API();p=policy();a.branches=[{'pattern':'main','requiresApprovingReviews':True,'requiredApprovingReviewCount':2,'dismissesStaleReviews':True,'bypassPullRequestAllowances':{'totalCount':0,'nodes':[],'pageInfo':{'hasNextPage':False}},'bypassForcePushAllowances':{'totalCount':0,'nodes':[],'pageInfo':{'hasNextPage':False}},'isAdminEnforced':True,'requiredStatusCheckContexts':['checkpr / Check Pull Request','Security'],'requiresStatusChecks':True,'requiresStrictStatusChecks':True,'allowsForcePushes':False}]
        preflight(a,p);self.assertEqual(a.writes,[])
    def test_existing_stricter_or_reviewers_retained(self):
        a=API();p=policy();p['reviewers']=['alice','bob'];p['environments']=p['environments'][1:2]
        a.request=lambda method,path,data=None: ({'data':{'repository':{'branchProtectionRules':{'totalCount':0,'pageInfo':{'hasNextPage':False},'nodes':[]}}}} if path=='/graphql' else {'id':7 if path.endswith('/alice') or path.endswith('/admin') else 8})
        a.environments['/environments/release%2Fprod']={'protection_rules':[{'type':'required_reviewers','prevent_self_review':True,'reviewers':[{'type':'User','reviewer':{'id':7}}]}]}
        apply_environments(a,preflight(a,p));self.assertEqual(a.writes[0][2]['reviewers'],[{'type':'User','id':7}])
    def test_api_failure_stops_before_mutations(self):
        from github import GitHubError
        a=API();a.pages=lambda path: (_ for _ in ()).throw(GitHubError('API unavailable'))
        with self.assertRaises(GitHubError):preflight(a,policy())
        self.assertEqual(a.writes,[])
    def test_environment_wait_timer_preserved(self):
        a=API();p=policy();p['environments']=p['environments'][1:2];a.environments['/environments/release%2Fprod']={'protection_rules':[{'type':'wait_timer','wait_timer':30}], 'deployment_branch_policy':{'protected_branches':True,'custom_branch_policies':False}}
        apply_environments(a,preflight(a,p));self.assertEqual(a.writes[0][2]['wait_timer'],30)
    def test_legacy_and_component_local_helper_dispatch_static(self):
        text=(Path(__file__).resolve().parents[2]/'cd/tasks/repo/owners/action.yml').read_text()
        for action in ('contributors','protect/gitflow','protect/commits','protect/sources'):
            self.assertIn('uses: ./bp/cd/tasks/repo/owners/'+action,text)
            self.assertIn('uses: cloudopsworks/blueprints/cd/tasks/repo/owners/'+action+'@v5.10',text)


class ReusedActionExecutionTests(unittest.TestCase):
    def action(self,path):
        import subprocess
        root=Path(__file__).resolve().parents[2]
        return json.loads(subprocess.check_output(['yq','-o=json','-I=0','.',str(root/path)],text=True))
    def execute(self,script,env=None):
        import subprocess,os
        harness=r'''
const fs=require('fs');const script=fs.readFileSync(0,'utf8');const calls=[];
const github={graphql:async(query,args)=>{calls.push({query,args});if(query.includes('teams(first:'))return {organization:{teams:{nodes:[]}}};if(query.includes('membersWithRole(first:'))return {organization:{membersWithRole:{nodes:[{login:'alice',id:'A'}]}}};if(query.includes('branchProtectionRules(first:'))return {repository:{id:'R',branchProtectionRules:{nodes:[]}}};if(query.includes('rulesets(first:'))return {repository:{id:'R',rulesets:{nodes:[]}}};return {};},rest:{issues:{listMilestones:async()=>({data:[]}),createMilestone:async(args)=>{calls.push({op:'milestone',args});return {data:{number:8}}},update:async(args)=>calls.push({op:'update',args}),addLabels:async(args)=>calls.push({op:'labels',args})},pulls:{requestReviewers:async(args)=>calls.push({op:'reviewers',args})},teams:{addOrUpdateRepoPermissionsInOrg:async(args)=>calls.push({op:'team',args})},repos:{addCollaborator:async(args)=>calls.push({op:'collaborator',args})}}};
const F=Object.getPrototypeOf(async function(){}).constructor;const core={info:()=>{},setOutput:()=>{}};new F('github','context','core','console',script)(github,{repo:{owner:'acme',repo:'app'},issue:{number:3}},core,{log:()=>{},debug:()=>{}}).then(()=>process.stdout.write(JSON.stringify(calls))).catch(e=>{process.stderr.write(e.stack);process.exit(1)});
'''
        return json.loads(subprocess.check_output(['node','-e',harness],input=script,text=True,env={**os.environ,**(env or {})}))
    def test_checkpr_reuses_actual_milestone_label_and_reviewer_scripts(self):
        action=self.action('cd/tasks/repo/checkpr/action.yml');steps=action['runs']['steps']
        milestone=next(s for s in steps if s.get('name')=='Assign Milestone to the PR')
        calls=self.execute(milestone['with']['script'],{'GITHUB_HEAD_REF':'release/1.2.3'})
        self.assertEqual(calls[0]['args']['title'],'1.2.3');self.assertEqual(calls[1]['args']['milestone'],8)
        calls=self.execute(steps[-2]['with']['script']);self.assertEqual(calls[0]['args']['labels'],['approved','automatic-environment'])
        calls=self.execute(steps[-1]['with']['script'],{'STEPS_REVIEWERS_RESULT':'["alice","bob"]','STEPS_REVIEWERS_COUNT_RESULT':'1','GITHUB_EVENT_PULL_REQUEST_USER_LOGIN':'alice'})
        self.assertEqual(calls[0]['args']['reviewers'],['bob']);self.assertEqual(calls[1]['args']['labels'],['approval-required','review-required'])
    def test_component_contributors_team_and_collaborator_actual_calls(self):
        action=self.action('cd/tasks/repo/owners/contributors/action.yml')
        calls=self.execute(action['runs']['steps'][0]['with']['script'],{'STEPS_CONTRIB_LIST_RESULT':'{"push":["acme/devs","alice"]}'})
        self.assertEqual([c['op'] for c in calls],['team','collaborator']);self.assertEqual(calls[0]['args']['permission'],'push')
    def test_component_branch_helper_requires_count_and_never_deletes(self):
        action=self.action('cd/tasks/repo/owners/protect/gitflow/action.yml')
        calls=self.execute(action['runs']['steps'][0]['with']['script'],{'COMPONENT_MODE':'true','STEPS_REVIEWERS_LIST_RESULT':'["alice"]','STEPS_OWNERS_LIST_RESULT':'["alice"]','STEPS_CONTRIB_LIST_RESULT':'{}','STEPS_REVIEWERS_COUNT_RESULT':'2','STEPS_REPO_TYPE_RESULT':'sourcecode'})
        writes=[c for c in calls if 'createBranchProtectionRule' in c['query']]
        self.assertTrue(writes);self.assertTrue(all(c['args']['reviewers_count']==2 for c in writes));self.assertFalse(any('deleteBranchProtectionRule' in c['query'] for c in calls));self.assertTrue(all(c['args']['contexts']==['checkpr / Check Pull Request'] for c in writes));self.assertTrue(all('isAdminEnforced: true' in c['query'] and 'dismissesStaleReviews: true' in c['query'] and 'bypassPullRequestActorIds: []' in c['query'] and 'bypassForcePushActorIds: []' in c['query'] for c in writes))
    def test_component_source_and_commit_helpers_execute_actual_rules(self):
        env={'COMPONENT_MODE':'true','STEPS_REVIEWERS_LIST_RESULT':'["alice"]','STEPS_OWNERS_LIST_RESULT':'["alice"]','STEPS_CONTRIB_LIST_RESULT':'{}','STEPS_REVIEWERS_COUNT_RESULT':'1','STEPS_REPO_TYPE_RESULT':'sourcecode','STEPS_ENFORCE_CONVENTIONAL_COMMITS_RESULT':'true','STEPS_CUSTOM_COMMITS_PATTERN_RESULT':'false','STEPS_PROTECTED_SOURCES_RESULT':'[".github/**",".cloudopsworks/**"]'}
        for kind in ('commits','sources'):
            action=self.action('cd/tasks/repo/owners/protect/'+kind+'/action.yml');calls=self.execute(action['runs']['steps'][0]['with']['script'],env)
            writes=[c for c in calls if 'createRepositoryRuleset(input:' in c['query']]
            self.assertEqual(len(writes),1);self.assertEqual(writes[0]['args']['input']['enforcement'],'ACTIVE')

class TrustedPolicyTests(unittest.TestCase):
    def test_policy_is_typed_cli_over_protected_api_snapshot(self):
        import os,tempfile,subprocess
        from unittest.mock import patch
        from owners import trusted_policy
        sha='a'*40
        class Reader:
            repository='acme/app'
            def repo(self,method,path,data=None):
                if path=='/pulls/3':return {'state':'open','head':{'sha':sha,'ref':'feature/x'},'base':{'sha':sha,'ref':'develop','repo':{'full_name':self.repository}},'user':{'login':'alice'}}
                return {'protected':True,'commit':{'sha':sha}}
        calls=[]
        class CLI:
            def run(self,argv,**kwargs):
                calls.append(argv)
                return subprocess.CompletedProcess(argv,0,json.dumps({'resolved':{'policy':{**policy(),'automatic':False,'reviewers':['alice','bob']}}}),'')
        event={'repository':{'full_name':'acme/app'},'pull_request':{'number':3,'head':{'sha':sha,'ref':'feature/x'},'base':{'ref':'develop'}}}
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'GITHUB_EVENT_NAME':'pull_request_target','RUNNER_TEMP':tmp}),patch('snapshot.materialize_snapshot') as snapshot:
            result=trusted_policy(Reader(),event,'checkpr-policy',CLI())
            self.assertEqual(result['reviewers'],['bob'])
            self.assertEqual(snapshot.call_args.args[1],sha)
            self.assertEqual(calls[0][:3],['tronador','components','validate'])
            self.assertTrue(result['labeler_path'].startswith(str(Path(tmp).resolve())))
    def test_unprotected_and_stale_branch_denied_before_snapshot(self):
        import os
        from unittest.mock import patch
        from owners import trusted_policy
        class Reader:
            repository='acme/app'
            def repo(self,*args):return {'protected':False,'commit':{'sha':'a'*40}}
        with patch.dict(os.environ,{'GITHUB_EVENT_NAME':'push','GITHUB_REF':'refs/heads/develop','GITHUB_SHA':'a'*40}),patch('snapshot.materialize_snapshot') as snapshot:
            with self.assertRaises(OwnersError):trusted_policy(Reader(),{'repository':{'full_name':'acme/app'}},'preflight')
            snapshot.assert_not_called()

if __name__=='__main__':unittest.main()
