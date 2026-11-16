"""Schema-v2 owners preflight and canonical environments; legacy helpers retain access/rules operations."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path
import os
import re
import shutil
import sys
from urllib.parse import quote
from github import GitHub
from executor import Runner, checked


class OwnersError(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise OwnersError(message)


def reviewers(api, names):
    result = []
    for name in names:
        if '/' in name:
            org, team = name.split('/')
            require(org == api.repository.split('/')[0], 'foreign reviewer team')
            record = api.request('GET', f'/orgs/{quote(org,safe="")}/teams/{quote(team,safe="")}')
            kind = 'Team'
        else:
            record = api.request('GET', '/users/' + quote(name, safe=''))
            kind = 'User'
        require(record and type(record.get('id')) is int, 'reviewer cannot be resolved')
        result.append({'type':kind, 'id':record['id']})
    return result


BRANCH_POLICY_FIELDS = """requiresApprovingReviews requiredApprovingReviewCount requiredStatusCheckContexts
isAdminEnforced dismissesStaleReviews requiresStatusChecks requiresStrictStatusChecks allowsForcePushes
bypassPullRequestAllowances(first:100){totalCount pageInfo{hasNextPage} nodes{actor{__typename}}}
bypassForcePushAllowances(first:100){totalCount pageInfo{hasNextPage} nodes{actor{__typename}}}"""


def validate_branch_policy(record, required_reviews=1):
    require(record and record.get('requiresApprovingReviews') is True and type(record.get('requiredApprovingReviewCount')) is int and record['requiredApprovingReviewCount'] >= required_reviews, 'existing branch review policy requires explicit migration')
    require(record.get('requiresStatusChecks') is True and record.get('requiresStrictStatusChecks') is True and record.get('allowsForcePushes') is False and record.get('isAdminEnforced') is True and record.get('dismissesStaleReviews') is True and 'checkpr / Check Pull Request' in record.get('requiredStatusCheckContexts', []), 'existing required caller/head checks require explicit migration')
    for key in ('bypassPullRequestAllowances','bypassForcePushAllowances'):
        connection = record.get(key)
        require(isinstance(connection,dict) and type(connection.get('totalCount')) is int and connection['totalCount'] == 0 and connection.get('nodes') == [] and connection.get('pageInfo', {}).get('hasNextPage') is False, 'existing owner bypass policy requires explicit migration')


def current_branch_policy(api, branch):
    owner, repo = api.repository.split('/')
    query = 'query($owner:String!,$repo:String!,$ref:String!){repository(owner:$owner,name:$repo){ref(qualifiedName:$ref){branchProtectionRule{' + BRANCH_POLICY_FIELDS + '}}}}'
    response = api.request('POST','/graphql',{'query':query,'variables':{'owner':owner,'repo':repo,'ref':'refs/heads/'+branch}})
    require(response and not response.get('errors'), 'current branch protection cannot be verified')
    ref = response.get('data',{}).get('repository',{}).get('ref')
    require(ref, 'current base branch is not protected')
    record = ref.get('branchProtectionRule')
    validate_branch_policy(record)
    return record


def protection_preflight(api, policy):
    # Existing helpers preserve these records in component mode. Reject a policy
    # change they cannot safely reconcile instead of returning a green no-op.
    owner, repo = api.repository.split('/')
    query = 'query($owner:String!,$repo:String!){repository(owner:$owner,name:$repo){branchProtectionRules(first:100){totalCount pageInfo{hasNextPage} nodes{pattern ' + BRANCH_POLICY_FIELDS + '}}}}'
    response = api.request('POST','/graphql',{'query':query,'variables':{'owner':owner,'repo':repo}})
    require(response and not response.get('errors'), 'branch protection policy cannot be verified')
    records = response['data']['repository']['branchProtectionRules']
    require(type(records.get('totalCount')) is int and records['totalCount'] <= 100 and records.get('pageInfo',{}).get('hasNextPage') is False and len(records.get('nodes',[])) == records['totalCount'], 'branch protection enumeration exceeds supported bound')
    managed = {'main','master','develop','support/*','release/*','feature/*','hotfix/*','generatedocstring-*','generateunittests-','autofix-','sonarfix-'}
    for record in records['nodes']:
        if record['pattern'] not in managed and record['pattern'] != '*':
            require(not any(c in record['pattern'] for c in '*?['), 'overlapping unmanaged branch policy requires explicit migration')
            continue
        validate_branch_policy(record,policy['requiredReviewers'])
    for brief in api.pages('/rulesets'):
        if brief.get('name') not in ('protected-sources','commit-message-rules'):
            continue
        record = api.repo('GET','/rulesets/'+str(brief['id']))
        require(record and record.get('enforcement') in ('active','evaluate'), 'existing ruleset protection cannot be verified')
        if brief['name'] == 'protected-sources':
            require(record['enforcement']=='active' and record.get('target')=='push', 'existing source protection requires explicit migration')
            current = {p.replace('/**/*','/**') for rule in record.get('rules',[]) if rule['type']=='file_path_restriction' for p in rule['parameters']['restricted_file_paths']}
            require('**' in current or all(p.replace('/**/*','/**') in current for p in policy['protectedSources']), 'existing source paths require explicit migration')
        elif policy.get('conventionalCommitsEnabled'):
            pattern = r'^(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)(\([a-zA-Z0-9_\-]+\))?: '
            if policy.get('enforceCustomCommitsPattern'):
                pattern += policy['enforceCustomCommitsPatternRegex']
            pattern += '.*'
            rules = [r for r in record.get('rules',[]) if r['type']=='commit_message_pattern']
            require(len(rules)==1 and rules[0]['parameters'].get('pattern')==pattern and rules[0]['parameters'].get('operator')=='regex' and not rules[0]['parameters'].get('negate'), 'existing commit pattern requires explicit migration')
            require(not policy.get('enforceConventionalCommits') or record['enforcement']=='active', 'existing commit enforcement requires explicit migration')
            conditions = record.get('conditions',{}).get('ref_name',{})
            require(conditions.get('include')==['~ALL'] and not conditions.get('exclude'), 'existing commit coverage requires explicit migration')


def preflight(api, policy):
    """Read all protection prerequisites BEFORE any helper or environment write."""
    require(policy.get('branchProtection') is True, 'component callers require branch protection')
    require(type(policy.get('requiredReviewers')) is int and policy['requiredReviewers'] >= 1, 'component callers require review approval')
    require(policy.get('reviewers') and policy.get('owners'), 'reviewers and owners must be configured')
    paths = policy.get('protectedSources', [])
    normalized_paths = {p.replace('/**/*','/**') for p in paths}
    require('.github/**' in normalized_paths and '.cloudopsworks/**' in normalized_paths, 'required caller/config source protections are missing')
    repo = api.repo('GET', '')
    require(repo and repo.get('permissions', {}).get('admin') is True, 'owners requires repository administration permission')
    require(repo.get('private') is True, 'unsupported: public repositories cannot enforce required push source-path protections')
    protection_preflight(api,policy)
    reviewers(api, policy['owners'])
    resolved = reviewers(api, policy['reviewers'])
    require(len(resolved) <= 6, 'GitHub environments support at most six reviewers')
    environments = policy.get('environments', [])
    names = set()
    prepared = []
    for env in environments:
        name = env['name']
        require(re.fullmatch(r'(develop|test|prerelease|release|support|pull_request)/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?', name), 'noncanonical protected environment')
        require(name not in names, 'ambiguous environment protection policy')
        names.add(name)
        for key,value in env.get('variables',{}).items():
            require(re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',key) and isinstance(value,str), 'invalid environment variable')
        desired = resolved if env['reviewers'] else []
        suffix = '/environments/' + quote(name, safe='')
        existing = api.repo('GET', suffix)
        if existing:
            rules = existing.get('protection_rules', [])
            prior = next((r for r in rules if r.get('type') == 'required_reviewers'), {})
            prior_ids = {(r['type'],r['reviewer']['id']) for r in prior.get('reviewers', [])}
            desired_ids = {(r['type'],r['id']) for r in desired}
            if prior_ids:
                require(desired_ids and (prior_ids.issubset(desired_ids) or desired_ids.issubset(prior_ids)), 'environment reviewer policy would weaken')
                # Environment reviewers are OR, not a quorum: adding identities
                # weakens the gate. Retain a stronger existing allowed subset.
                if prior_ids.issubset(desired_ids):
                    desired = [{'type':r['type'],'id':r['reviewer']['id']} for r in prior['reviewers']]
            require(not prior.get('prevent_self_review') or bool(desired), 'environment self-review policy would weaken')
            branch = existing.get('deployment_branch_policy')
            require(not branch or branch == {'protected_branches':True,'custom_branch_policies':False}, 'existing environment branch restrictions cannot be replaced')
        prepared.append((suffix, env, desired, existing))
    return prepared


def apply_environments(api, prepared):
    for suffix, env, desired, existing in prepared:
        wait = next((r.get('wait_timer',0) for r in (existing or {}).get('protection_rules',[]) if r.get('type')=='wait_timer'),0)
        api.repo('PUT', suffix, {'wait_timer':wait, 'prevent_self_review':bool(desired), 'reviewers':desired,
            'deployment_branch_policy':{'protected_branches':True,'custom_branch_policies':False}})
        current = api.repo('GET', suffix+'/variables') or {'variables':[]}
        values = {v['name']:v['value'] for v in current['variables']}
        for key,value in env.get('variables',{}).items():
            require(re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',key) and isinstance(value,str), 'invalid environment variable')
            if values.get(key)==value:
                continue
            api.repo('PATCH' if key in values else 'POST', suffix+'/variables'+('/'+quote(key,safe='') if key in values else ''), {'name':key,'value':value})


def output_policy(policy):
    if not os.environ.get('GITHUB_OUTPUT'):
        return
    with open(os.environ['GITHUB_OUTPUT'],'a') as output:
        for key,value in policy.items():
            encoded = value if isinstance(value,str) else json.dumps(value,separators=(',',':'))
            require('\n' not in encoded and '\r' not in encoded, 'multiline outputs are not supported')
            output.write(key+'='+encoded+'\n')


def trusted_policy(api, event, mode, runner=None):
    require(event.get('repository', {}).get('full_name') == api.repository, 'foreign policy repository')
    if mode in ('checkpr-policy','automerge-policy'):
        require(os.environ.get('GITHUB_EVENT_NAME') in (('pull_request_target',) if mode == 'checkpr-policy' else ('pull_request_target','check_suite','status','repository_dispatch')), 'untrusted PR policy event')
        number = event.get('pull_request', {}).get('number')
        require(type(number) is int and number > 0, 'missing PR')
        pr = api.repo('GET', f'/pulls/{number}')
        require(pr and pr['state'] == 'open' and pr['base']['repo']['full_name'] == api.repository, 'foreign/closed PR')
        require(pr['head']['sha'] == event['pull_request']['head']['sha'] and pr['head']['ref'] == event['pull_request']['head']['ref'] and pr['base']['ref'] == event['pull_request']['base']['ref'], 'stale PR policy event')
        branch, sha = pr['base']['ref'], pr['base']['sha']
    else:
        require(os.environ.get('GITHUB_EVENT_NAME') in ('push','workflow_dispatch'), 'untrusted owners policy event')
        ref = os.environ.get('GITHUB_REF','')
        require(ref in ('refs/heads/master','refs/heads/main','refs/heads/develop'), 'owners requires protected branch')
        branch, sha = ref.removeprefix('refs/heads/'), os.environ.get('GITHUB_SHA','')
    require(re.fullmatch('[0-9a-f]{40}',sha), 'invalid policy source')
    record = api.repo('GET','/branches/'+quote(branch,safe=''))
    require(record and record.get('protected') is True and record['commit']['sha'] == sha, 'policy source is not the current protected branch')
    from snapshot import materialize_snapshot
    root = Path(tempfile.mkdtemp(prefix='monorepo-policy-',dir=os.environ.get('RUNNER_TEMP'))).resolve()
    try:
        materialize_snapshot(api,sha,root)
        result = json.loads(checked(runner or Runner(), ['tronador','components','validate','--workdir',str(root),'--json']))
        policy = result['resolved']['policy']
    finally:
        if mode != 'checkpr-policy':
            shutil.rmtree(root)
    if mode == 'checkpr-policy':
        policy = dict(policy)
        policy['reviewers'] = [r for r in policy['reviewers'] if r != pr['user']['login']]
        policy['labeler_path'] = str(root/'.cloudopsworks/labeler.yml')
    return policy


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    require(len(args)==1 and args[0] in ('preflight','environments','checkpr-policy'), 'invalid owners operation')
    api = GitHub(os.environ['GITHUB_REPOSITORY'])
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    reader = GitHub(os.environ['GITHUB_REPOSITORY'],token=os.environ.get('GH_POLICY_TOKEN') or api.token)
    policy = trusted_policy(reader,event,args[0])
    if args[0] != 'checkpr-policy':
        prepared = preflight(api,policy)
        if args[0] == 'environments':
            apply_environments(api,prepared)
    output_policy(policy)


if __name__ == '__main__':
    try:
        main()
    except (OwnersError,KeyError,ValueError) as exc:
        print('Owners authorization failed: '+str(exc),file=sys.stderr)
        sys.exit(1)
