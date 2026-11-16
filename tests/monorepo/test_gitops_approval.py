"""Fresh-head automerge security contracts; offline GitHub doubles, not hosted proof."""
import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'cd/monorepo/runtime'))
from gitops import automerge_gate, process, GitOpsError
from owners import preflight, OwnersError
from test_gitops import API, SHA
from test_owners import API as OwnersAPI, policy
import test_owners as owner_fixtures


def native_rule():
    return {'requiresApprovingReviews':True,'requiredApprovingReviewCount':1,'dismissesStaleReviews':True,
        'requiredStatusCheckContexts':['checkpr / Check Pull Request'],'requiresStatusChecks':True,
        'requiresStrictStatusChecks':True,'allowsForcePushes':False,'isAdminEnforced':True,
        **{k:{'totalCount':0,'nodes':[],'pageInfo':{'hasNextPage':False}} for k in ('bypassPullRequestAllowances','bypassForcePushAllowances')}}


class MergeAPI(API):
    def __init__(self):
        super().__init__('/retry')
        self.pr.update({'user':{'login':'author'},'draft':False,'labels':[{'name':'approved'}]})
        self.pr['head']['ref']='feature/x';self.pr['base'].update({'ref':'develop','sha':'b'*40})
        self.original={**copy.deepcopy(self.comment),'id':13,'body':'/approve'}
        self.comments=[{'body':f'<!-- cloudopsworks-gitops:13:{SHA}:approve -->\nApproval accepted.','user':{'id':99},'created_at':'now','updated_at':'now'}]
        self.reviews=[{'id':1,'user':{'login':'reviewer'},'state':'APPROVED','commit_id':SHA}]
        self.rule=native_rule();self.pr_reads=0;self.race=False;self.queries=[]
    def repo(self,method,path,data=None):
        if method=='GET' and path=='/issues/comments/13':return copy.deepcopy(self.original)
        if method=='GET' and path=='/pulls/3':
            self.pr_reads+=1
            if self.race and self.pr_reads>=3:self.pr['head']['sha']='c'*40
            return copy.deepcopy(self.pr)
        return super().repo(method,path,data)
    def request(self,method,path,data=None):
        if path=='/graphql':
            self.queries.append(data)
            return {'data':{'repository':{'ref':{'branchProtectionRule':copy.deepcopy(self.rule)}}}}
        return super().request(method,path,data)
    def pages(self,path):
        if path=='/pulls?state=open':return [copy.deepcopy(self.pr)]
        return super().pages(path)
    def merge_event(self):
        return {'repository':{'full_name':self.repository},'pull_request':{'number':3,'head':{'sha':SHA}}}


class FreshAutomergeTests(unittest.TestCase):
    def test_current_intent_and_review_reserve_exact_pr_without_mutation(self):
        a=MergeAPI();self.assertEqual(automerge_gate(a,a.merge_event(),'pull_request_target'),3)
        self.assertEqual(a.writes,[]);self.assertEqual(a.queries[0]['variables']['ref'],'refs/heads/develop')
        for field in ('dismissesStaleReviews','bypassPullRequestAllowances','bypassForcePushAllowances','totalCount','hasNextPage'):
            self.assertIn(field,a.queries[0]['query'])
    def test_stale_revoked_edited_or_lost_permission_approval_is_not_a_label(self):
        for bad in ('head','marker','revoked','permission','edited','receipt-edited','old-review','no-review','forged-marker','race'):
            with self.subTest(bad=bad):
                a=MergeAPI();event=a.merge_event()
                if bad=='head':a.pr['head']['sha']='c'*40
                if bad=='marker':a.comments[0]['body']=a.comments[0]['body'].replace(SHA,'c'*40)
                if bad=='revoked':a.reviews.append({'id':2,'user':{'login':'reviewer'},'state':'DISMISSED','commit_id':SHA})
                if bad=='permission':a.permission='read'
                if bad=='edited':a.original['updated_at']='edited'
                if bad=='receipt-edited':a.comments[0]['updated_at']='edited'
                if bad=='old-review':a.reviews[0]['commit_id']='c'*40
                if bad=='no-review':a.reviews=[]
                if bad=='forged-marker':a.comments[0]['user']['id']=7
                if bad=='race':a.race=True
                with self.assertRaises(GitOpsError):automerge_gate(a,event,'pull_request_target')
                self.assertEqual(a.writes,[])
    def test_native_stale_review_admin_and_bypass_policy_independently_checked(self):
        for bad in ('dismiss','admin','bypass','force-bypass','truncated','missing','zero-count'):
            with self.subTest(bad=bad):
                a=MergeAPI()
                if bad=='dismiss':a.rule['dismissesStaleReviews']=False
                if bad=='admin':a.rule['isAdminEnforced']=False
                if bad=='zero-count':a.rule['requiredApprovingReviewCount']=0
                if bad in ('bypass','force-bypass'):
                    key='bypassPullRequestAllowances' if bad=='bypass' else 'bypassForcePushAllowances'
                    a.rule[key]={'totalCount':1,'nodes':[{'actor':{'__typename':'User'}}],'pageInfo':{'hasNextPage':False}}
                if bad=='truncated':a.rule['bypassPullRequestAllowances']['pageInfo']['hasNextPage']=True
                if bad=='missing':a.rule.pop('bypassPullRequestAllowances')
                with self.assertRaises(GitOpsError):automerge_gate(a,a.merge_event(),'pull_request_target')
                self.assertEqual(a.writes,[])
    def test_retry_runs_same_fresh_gate_before_success_receipt(self):
        a=MergeAPI();self.assertTrue(process(a,a.event(True),'retry'))
        self.assertTrue(any('retry -->' in c['body'] for c in a.comments))
        a=MergeAPI();a.reviews=[]
        with self.assertRaises(GitOpsError):process(a,a.event(True),'retry')
        self.assertEqual(a.writes,[])
    def test_status_and_check_suite_cannot_scan_or_merge_unrelated_pr(self):
        for name,event in [('status',{'sha':SHA}),('check_suite',{'action':'completed','check_suite':{'head_sha':SHA}})]:
            a=MergeAPI();event['repository']={'full_name':a.repository};self.assertEqual(automerge_gate(a,event,name),3)
        a=MergeAPI();a.pages=lambda path:[copy.deepcopy(a.pr),{**copy.deepcopy(a.pr),'number':4}]
        with self.assertRaises(GitOpsError):automerge_gate(a,{'repository':{'full_name':a.repository},'sha':SHA},'status')
    def test_automatic_labels_require_trusted_base_policy_and_current_reviews(self):
        for automatic,head,expected in [(True,'feature/x',True),(False,'release/1.2.3',True),(False,'feature/x',False)]:
            a=MergeAPI();a.comments=[];a.pr['labels'].append({'name':'automatic-environment'});a.pr['head']['ref']=head
            def trusted(api,event,mode):
                self.assertEqual(mode,'automerge-policy');self.assertEqual(event['pull_request']['base']['sha'],'b'*40)
                return {'automatic':automatic}
            if expected:self.assertEqual(automerge_gate(a,a.merge_event(),'pull_request_target',policy_loader=trusted),3)
            else:
                with self.assertRaises(GitOpsError):automerge_gate(a,a.merge_event(),'pull_request_target',policy_loader=trusted)
        a=MergeAPI();a.comments=[];a.reviews=[];a.pr['labels'].append({'name':'automatic-environment'})
        with self.assertRaises(GitOpsError):automerge_gate(a,a.merge_event(),'pull_request_target',policy_loader=lambda *args:{'automatic':True})
    def test_current_native_review_quorum_is_not_one_approval_marker(self):
        a=MergeAPI();a.rule['requiredApprovingReviewCount']=2
        with self.assertRaises(GitOpsError):automerge_gate(a,a.merge_event(),'pull_request_target')
        a.reviews.append({'id':2,'user':{'login':'second-reviewer'},'state':'APPROVED','commit_id':SHA})
        self.assertEqual(automerge_gate(a,a.merge_event(),'pull_request_target'),3)
    def test_workflow_reuses_action_only_after_gate_and_scoped_number(self):
        import subprocess
        workflow=json.loads(subprocess.check_output(['yq','-o=json','-I=0','.',str(Path(__file__).resolve().parents[2]/'.github/workflows/monorepo-automerge.yml')],text=True))
        steps=workflow['jobs']['automerge']['steps'];action=steps[-1]
        self.assertEqual(action['uses'],'cloudopsworks/automerge-action@v0.17.0')
        self.assertEqual(action['env']['PULL_REQUEST'],'${{ steps.approval.outputs.pull_request }}')
        self.assertIn('authorized',action['if']);self.assertIn('gitops.py automerge',steps[-2]['run'])
        self.assertEqual(steps[0]['with']['checkout_source'],'false')


class OwnersFreshHeadTests(unittest.TestCase):
    def test_existing_weak_or_unbounded_rules_fail_before_any_write(self):
        for bad in ('dismiss','bypass','force-bypass','truncated','missing'):
            with self.subTest(bad=bad):
                a=OwnersAPI();rule={**native_rule(),'pattern':'main'}
                if bad=='dismiss':rule['dismissesStaleReviews']=False
                if bad=='bypass':rule['bypassPullRequestAllowances']['totalCount']=1
                if bad=='force-bypass':rule['bypassForcePushAllowances']['totalCount']=1
                if bad=='truncated':rule['bypassPullRequestAllowances']['pageInfo']['hasNextPage']=True
                if bad=='missing':rule.pop('bypassPullRequestAllowances')
                a.branches=[rule]
                with self.assertRaises(OwnersError):preflight(a,policy())
                self.assertEqual(a.writes,[])
    def test_stronger_native_policy_retained_without_writes(self):
        a=OwnersAPI();a.branches=[{**native_rule(),'pattern':'main','requiredApprovingReviewCount':2}]
        preflight(a,policy());self.assertEqual(a.writes,[])
    def test_legacy_actual_js_keeps_original_defaults_and_bypass_arguments(self):
        executor=owner_fixtures.ReusedActionExecutionTests();action=executor.action('cd/tasks/repo/owners/protect/gitflow/action.yml')
        calls=executor.execute(action['runs']['steps'][0]['with']['script'],{'COMPONENT_MODE':'false','STEPS_REVIEWERS_LIST_RESULT':'["alice"]','STEPS_OWNERS_LIST_RESULT':'["alice"]','STEPS_CONTRIB_LIST_RESULT':'{}','STEPS_REVIEWERS_COUNT_RESULT':'2','STEPS_REPO_TYPE_RESULT':'sourcecode'})
        writes=[c for c in calls if 'createBranchProtectionRule' in c['query']]
        self.assertTrue(writes);self.assertTrue(all('dismissesStaleReviews' not in c['query'] and 'bypassPullRequestActorIds: $admin_ids' in c['query'] and 'isAdminEnforced: false' in c['query'] for c in writes))
        strict=next(c for c in writes if c['args']['branch']=='main');self.assertEqual(strict['args']['reviewers_count'],0)

# Offline upstream protocol fixture, copied without function-body changes from
# cloudopsworks/automerge-action v0.17.0, commit 5df35eae89cb1a40ad6f34a8dd9de8e4155dbb34.
# lib/common.js createConfig: only the module export keyword is removed;
# lib/api.js executeGitHubActionImpl and handleArbitraryPullRequestUpdate unchanged.
# All network/update/merge boundaries are injected local doubles below.
# The MIT License (upstream fixture only)
# Copyright 2019 Pascal
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of
# this software and associated documentation files (the "Software"), to deal in
# the Software without restriction, including without limitation the rights to
# use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
# the Software, and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
# FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
# COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
# IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
UPSTREAM_SCOPE_PROTOCOL = 'function createConfig(env = {}) {\n  function parseMergeLabels(str, defaultValue) {\n    const arr = (str == null ? defaultValue : str)\n      .split(",")\n      .map(s => s.trim());\n    return {\n      required: arr.filter(s => !s.startsWith("!") && s.length > 0),\n      blocking: arr\n        .filter(s => s.startsWith("!"))\n        .map(s => s.substr(1).trim())\n        .filter(s => s.length > 0)\n    };\n  }\n\n  function parseLabelMethods(str) {\n    return (str ? str.split(",") : []).map(lm => {\n      const [label, method] = lm.split("=");\n      if (!label || !method) {\n        throw new Error(\n          `Couldn\'t parse "${lm}" as "<label>=<method>" expression`\n        );\n      }\n      return { label, method };\n    });\n  }\n\n  function parseArray(str, defaultArray = []) {\n    return str ? str.split(",") : defaultArray;\n  }\n\n  function parseBranches(str, defaultValue) {\n    return (str == null ? defaultValue : str)\n      .split(",")\n      .map(s => s.trim())\n      .filter(s => s);\n  }\n\n  function parsePositiveInt(name, defaultValue) {\n    const val = env[name];\n    if (val == null || val === "") {\n      return defaultValue;\n    } else {\n      const number = parseInt(val, 10);\n      if (isNaN(number) || number < 0) {\n        throw new ClientError(`Not a positive integer: ${val}`);\n      } else {\n        return number;\n      }\n    }\n  }\n\n  function parsePullRequest(pullRequest) {\n    if (!pullRequest) {\n      return null;\n    }\n\n    logger.info(`Parsing PULL_REQUEST input: ${pullRequest}`);\n\n    const error = new ClientError(\n      `Invalid value provided for input PULL_REQUEST: ${pullRequest}. Must be a positive integer, optionally prefixed by a repo slug.`\n    );\n\n    if (typeof pullRequest === "string") {\n      let repoOwner;\n      let repoName;\n      let pullRequestNumber;\n\n      const destructuredPullRequest = pullRequest.split("/");\n      if (destructuredPullRequest.length === 3) {\n        [repoOwner, repoName, pullRequestNumber] = destructuredPullRequest;\n      } else if (destructuredPullRequest.length === 1) {\n        [pullRequestNumber] = destructuredPullRequest;\n      } else {\n        throw error;\n      }\n\n      pullRequestNumber = parseInt(pullRequestNumber, 10);\n      if (isNaN(pullRequestNumber) || pullRequestNumber <= 0) {\n        throw error;\n      }\n\n      return {\n        repoOwner,\n        repoName,\n        pullRequestNumber\n      };\n    }\n\n    if (typeof pullRequest === "number" && pullRequest > 0) {\n      return { pullRequestNumber: pullRequest };\n    }\n\n    throw error;\n  }\n\n  const mergeLabels = parseMergeLabels(env.MERGE_LABELS, "automerge");\n  const mergeRemoveLabels = parseArray(env.MERGE_REMOVE_LABELS);\n  const mergeMethod = env.MERGE_METHOD || "merge";\n  const mergeForks = env.MERGE_FORKS !== "false";\n  const mergeCommitMessage = env.MERGE_COMMIT_MESSAGE || "automatic";\n  const mergeCommitMessageRegex = env.MERGE_COMMIT_MESSAGE_REGEX || "";\n  const mergeFilterAuthor = env.MERGE_FILTER_AUTHOR || "";\n  const mergeRetries = parsePositiveInt("MERGE_RETRIES", 6);\n  const mergeRetrySleep = parsePositiveInt("MERGE_RETRY_SLEEP", 5000);\n  const mergeRequiredApprovals = parsePositiveInt(\n    "MERGE_REQUIRED_APPROVALS",\n    0\n  );\n  const mergeDeleteBranch = env.MERGE_DELETE_BRANCH === "true";\n  const mergeDeleteBranchFilter = parseArray(env.MERGE_DELETE_BRANCH_FILTER);\n  const mergeMethodLabels = parseLabelMethods(env.MERGE_METHOD_LABELS);\n  const mergeMethodLabelRequired = env.MERGE_METHOD_LABEL_REQUIRED === "true";\n  const mergeErrorFail = env.MERGE_ERROR_FAIL === "true";\n  const mergeReadyState = parseArray(env.MERGE_READY_STATE, [\n    "clean",\n    "has_hooks",\n    "unknown",\n    "unstable"\n  ]);\n\n  const updateLabels = parseMergeLabels(env.UPDATE_LABELS, "automerge");\n  const updateMethod = env.UPDATE_METHOD || "merge";\n  const updateRetries = parsePositiveInt("UPDATE_RETRIES", 1);\n  const updateRetrySleep = parsePositiveInt("UPDATE_RETRY_SLEEP", 5000);\n\n  const baseBranches = parseBranches(env.BASE_BRANCHES, "");\n\n  const pullRequest = parsePullRequest(env.PULL_REQUEST);\n\n  return {\n    mergeLabels,\n    mergeRemoveLabels,\n    mergeMethod,\n    mergeMethodLabels,\n    mergeMethodLabelRequired,\n    mergeForks,\n    mergeCommitMessage,\n    mergeCommitMessageRegex,\n    mergeFilterAuthor,\n    mergeRetries,\n    mergeRetrySleep,\n    mergeRequiredApprovals,\n    mergeDeleteBranch,\n    mergeDeleteBranchFilter,\n    mergeErrorFail,\n    mergeReadyState,\n    updateLabels,\n    updateMethod,\n    updateRetries,\n    updateRetrySleep,\n    baseBranches,\n    pullRequest\n  };\n}\n\nasync function executeGitHubActionImpl(context, eventName, eventData) {\n  logger.info("Event name:", eventName);\n  logger.trace("Event data:", eventData);\n\n  if (context.config.pullRequest != null) {\n    return await handleArbitraryPullRequestUpdate(context, eventData);\n  } else if (["push"].includes(eventName)) {\n    await handleBaseBranchUpdate(context, eventName, eventData);\n  } else if (["status"].includes(eventName)) {\n    return await handleStatusUpdate(context, eventName, eventData);\n  } else if (["pull_request", "pull_request_target"].includes(eventName)) {\n    return await handlePullRequestUpdate(context, eventName, eventData);\n  } else if (["check_suite", "check_run", "workflow_run"].includes(eventName)) {\n    return await handleCheckOrWorkflowUpdate(context, eventName, eventData);\n  } else if (["pull_request_review"].includes(eventName)) {\n    return await handlePullRequestReviewUpdate(context, eventName, eventData);\n  } else if (["schedule", "repository_dispatch"].includes(eventName)) {\n    return await handleScheduleTriggerOrRepositoryDispatch(context);\n  } else if (["issue_comment"].includes(eventName)) {\n    return await handleIssueComment(context, eventName, eventData);\n  } else if (["workflow_dispatch"].includes(eventName)) {\n    return await handleWorkflowDispatch(context, eventName, eventData);\n  } else {\n    throw new ClientError(`invalid event type: ${eventName}`);\n  }\n}\n\nasync function handleArbitraryPullRequestUpdate(context, eventData) {\n  const { config, octokit } = context;\n\n  const repoOwner =\n    config.pullRequest.repoOwner || eventData.repository.owner.login;\n  const repoName = config.pullRequest.repoName || eventData.repository.name;\n  const { pullRequestNumber } = config.pullRequest;\n\n  logger.info(`Looking for pull request #${pullRequestNumber}...`);\n\n  try {\n    const { data: pullRequest } = await octokit.pulls.get({\n      owner: repoOwner,\n      repo: repoName,\n      pull_number: pullRequestNumber,\n      headers: { "If-None-Match": "" }\n    });\n    logger.trace("Full PR:", pullRequest);\n\n    return updateAndMerge(context, pullRequest);\n  } catch (e) {\n    logger.error(\n      `Error fetching pull request: ${repoOwner}/${repoName}/${pullRequestNumber}`\n    );\n    throw e;\n  }\n}\n'

class UpstreamScopeProtocolTests(unittest.TestCase):
    def test_actual_upstream_parser_and_dispatch_refetch_only_gated_pr(self):
        import subprocess,hashlib
        self.assertEqual(hashlib.sha256(UPSTREAM_SCOPE_PROTOCOL.encode()).hexdigest(),'e9f2bee2c7ee1ca2d4d9c81c2898f7a669154e501fa187b58e05ef961590c326')
        harness = r"""
const fs=require('fs');const payload=JSON.parse(fs.readFileSync(0,'utf8'));
class ClientError extends Error{};const logger={info:()=>{},debug:()=>{},trace:()=>{},error:()=>{}};
const calls=[];async function updateAndMerge(context,pr){calls.push({kind:'merge-input',number:pr.number,sha:pr.head.sha});return {mergeResult:'fixture-only',pullRequestNumber:pr.number}};
""" + UPSTREAM_SCOPE_PROTOCOL + r"""
(async()=>{const config=createConfig({PULL_REQUEST:payload.number});const context={config,octokit:{pulls:{get:async args=>{calls.push({kind:'get',args});return {data:{number:Number(args.pull_number),head:{sha:'new-api-head'}}}}}}};await executeGitHubActionImpl(context,'status',{repository:{owner:{login:'acme'},name:'app'},pull_request:{number:999,head:{sha:'forged-event-head'}}});process.stdout.write(JSON.stringify(calls));})().catch(e=>{process.stderr.write(e.message);process.exit(1)});
"""
        calls=json.loads(subprocess.check_output(['node','-e',harness],input=json.dumps({'number':'3'}),text=True))
        self.assertEqual(calls[0]['args']['pull_number'],3)
        self.assertEqual(calls[0]['args']['owner'],'acme');self.assertEqual(calls[0]['args']['repo'],'app')
        self.assertEqual(calls[1],{'kind':'merge-input','number':3,'sha':'new-api-head'})
        # This proves actual upstream refetch/scoping, not native GitHub review
        # enforcement. Stale-review dismissal/no-bypass gate supplies that race
        # boundary; hosted protection semantics remain an activation check.

if __name__=='__main__':unittest.main()
