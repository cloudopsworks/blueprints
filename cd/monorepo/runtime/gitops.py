"""Authenticated, PR-scoped GitOps intent. Never executes pull-request source."""
from __future__ import annotations
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote
from github import GitHub, GitHubError


class GitOpsError(RuntimeError):
    pass


ALIASES = {'approve': 'approve', 'approved': 'approve', 'lgtm': 'approve', 'retry': 'retry', 'help': 'help'}
HELP = 'Supported PR commands: /approve (aliases /approved, /lgtm), /retry, /help. Other legacy commands are unsupported; no operation was dispatched.'


def require(value, message):
    if not value:
        raise GitOpsError(message)


def comment_context(api, event, dispatched=False):
    require(event.get('repository', {}).get('full_name') == api.repository, 'repository mismatch')
    if dispatched:
        payload = event.get('client_payload', {})
        number, comment_id = payload.get('number'), payload.get('comment_id')
    else:
        require(event.get('action') == 'created', 'only original comment creation is accepted')
        payload = event
        number, comment_id = event.get('issue', {}).get('number'), event.get('comment', {}).get('id')
        require(event.get('issue', {}).get('pull_request'), 'commands require a pull request')
    require(type(number) is int and number > 0 and type(comment_id) is int and comment_id > 0, 'invalid PR/comment identity')
    comment = api.repo('GET', f'/issues/comments/{comment_id}')
    require(comment and comment.get('issue_url') == f'https://api.github.com/repos/{api.repository}/issues/{number}', 'foreign or missing comment')
    require(isinstance(comment.get('created_at'), str) and comment.get('created_at') == comment.get('updated_at'), 'edited comments are not authorization')
    if not dispatched:
        require(comment.get('body') == event.get('comment', {}).get('body') and comment.get('user', {}).get('id') == event.get('sender', {}).get('id'), 'comment identity changed')
    else:
        require(comment.get('body') == payload.get('body') and comment.get('user', {}).get('id') == payload.get('author_id'), 'dispatch does not match original comment')
    match = re.fullmatch(r'/([a-z-]+)\s*', comment.get('body', ''))
    require(match, 'commands take no arguments')
    name = match[1]
    command = ALIASES.get(name, 'unsupported')
    if dispatched:
        require(event.get('action') == name + '-command', 'forged dispatch command')
    pr = api.repo('GET', f'/pulls/{number}')
    require(pr and pr.get('number') == number and pr.get('base', {}).get('repo', {}).get('full_name') == api.repository and pr.get('state') == 'open', 'PR is not current/open in this repository')
    head = pr.get('head', {}).get('sha', '')
    require(re.fullmatch('[0-9a-f]{40}', head), 'invalid head')
    if dispatched:
        require(payload.get('head_sha') == head, 'stale PR head')
    login = comment.get('user', {}).get('login', '')
    require(re.fullmatch('[A-Za-z0-9-]+', login), 'invalid author')
    permission = api.repo('GET', '/collaborators/' + quote(login, safe='') + '/permission')
    require(permission and permission.get('permission') in ('admin', 'maintain', 'write'), 'comment author lacks current write permission')
    return number, comment, pr, command, name


def current_reviews(api, number):
    latest = {}
    for review in sorted(api.pages(f'/pulls/{number}/reviews'), key=lambda r: r['id']):
        if review.get('state') != 'COMMENTED':
            latest[review['user']['login']] = review
    return latest


def approve_intent(api, number, login, sha, allow_requested=False):
    latest = current_reviews(api, number).get(login)
    revoked = latest and latest.get('state') in ('DISMISSED','CHANGES_REQUESTED')
    approved = latest and latest.get('state') == 'APPROVED' and latest.get('commit_id') == sha
    requested_now = False
    if allow_requested:
        requested = api.repo('GET', f'/pulls/{number}/requested_reviewers')
        requested_now = any(u.get('login') == login for u in requested.get('users', []))
        if not requested_now:
            for team in requested.get('teams', []):
                slug = team.get('slug', '')
                require(re.fullmatch('[A-Za-z0-9-]+',slug), 'invalid requested reviewer team')
                membership = api.request('GET', '/orgs/' + api.repository.split('/')[0] + '/teams/' + slug + '/memberships/' + login)
                if membership and membership.get('state') == 'active':
                    requested_now = True
                    break
    require(not revoked and (approved or requested_now), 'no current approval/reviewer intent')


def event_pull_request(api, event, event_name):
    require(event.get('repository', {}).get('full_name') == api.repository, 'foreign automerge repository')
    if event_name == 'pull_request_target':
        number = event.get('pull_request', {}).get('number')
        require(type(number) is int and number > 0, 'invalid automerge PR')
        return number, event['pull_request'].get('head', {}).get('sha')
    if event_name == 'check_suite':
        require(event.get('action') == 'completed', 'incomplete check suite')
        sha = event.get('check_suite', {}).get('head_sha')
    elif event_name == 'status':
        sha = event.get('sha')
    else:
        raise GitOpsError('unsupported automerge event')
    require(isinstance(sha,str) and re.fullmatch('[0-9a-f]{40}',sha), 'invalid automerge event head')
    candidates = api.pages('/pulls?state=open')
    require(len(candidates) <= 1000, 'automerge PR discovery exceeds bound')
    matches = [pr for pr in candidates if pr.get('head',{}).get('sha') == sha and pr.get('base',{}).get('repo',{}).get('full_name') == api.repository]
    require(len(matches) <= 1, 'ambiguous current-head PR; use PR-scoped retry')
    return (matches[0]['number'], sha) if matches else (None, sha)


def automerge_gate(api, event, event_name, *, number=None, policy_loader=None):
    """Reserve exactly one API-derived PR; native no-bypass review policy closes
    the head-change/revocation window before the existing action's merge call.
    Labels alone never authorize merging, and no source code is checked out.
    """
    if number is None:
        number, expected_sha = event_pull_request(api,event,event_name)
        if number is None:
            return None
    else:
        require(event_name == 'repository_dispatch' and type(number) is int and number > 0, 'invalid retry PR reservation')
        expected_sha = event.get('client_payload',{}).get('head_sha')
    pr = api.repo('GET', f'/pulls/{number}')
    require(pr and pr.get('number') == number and pr.get('state') == 'open' and pr.get('base',{}).get('repo',{}).get('full_name') == api.repository, 'foreign/closed automerge PR')
    sha = pr.get('head',{}).get('sha')
    require(isinstance(sha,str) and re.fullmatch('[0-9a-f]{40}',sha) and sha == expected_sha, 'automerge head changed')
    labels = {label['name'] for label in pr.get('labels',[])}
    if 'approved' not in labels or 'do-not-merge' in labels or pr.get('draft'):
        return None
    from owners import current_branch_policy, OwnersError
    try:
        rule = current_branch_policy(api,pr['base']['ref'])
    except OwnersError as exc:
        raise GitOpsError(str(exc)) from exc
    automation = api.request('GET','/user')
    require(automation and type(automation.get('id')) is int, 'BOT_TOKEN must authenticate a bot user')
    intent = False
    comments = api.pages(f'/issues/{number}/comments')
    for receipt in reversed(comments):
        if receipt.get('user',{}).get('id') != automation['id'] or not isinstance(receipt.get('created_at'),str) or receipt.get('created_at') != receipt.get('updated_at'):
            continue
        match = re.fullmatch(r'<!-- cloudopsworks-gitops:([1-9][0-9]*):([0-9a-f]{40}):approve -->\nApproval accepted\.',receipt.get('body',''))
        if not match or match[2] != sha:
            continue
        original = api.repo('GET','/issues/comments/'+match[1])
        require(original, 'original approval comment disappeared')
        name = original.get('body','').strip().removeprefix('/')
        context = {'repository':{'full_name':api.repository},'action':name+'-command','sender':automation,
            'client_payload':{'number':number,'comment_id':int(match[1]),'body':original.get('body'),
                'author_id':original.get('user',{}).get('id'),'head_sha':sha}}
        try:
            _, comment, _, command, _ = comment_context(api,context,True)
            require(command == 'approve', 'original comment is not approval intent')
            approve_intent(api,number,comment['user']['login'],sha)
        except GitOpsError:
            continue
        intent = True
        break
    if not intent and 'automatic-environment' in labels:
        if policy_loader is None:
            from owners import trusted_policy
            policy_loader = trusted_policy
        policy = policy_loader(api,{'repository':{'full_name':api.repository},'pull_request':pr},'automerge-policy')
        intent = policy['automatic'] is True or (pr['base']['ref'] == 'develop' and pr['head']['ref'].startswith('release/'))
    require(intent, 'approved label has no fresh authenticated current-head intent')
    # Independently count only latest current-head, non-author reviews with
    # current repository permissions; GitHub enforces the same gate at merge.
    approved = 0
    for login, review in current_reviews(api,number).items():
        if review.get('state') != 'APPROVED' or review.get('commit_id') != sha or login == pr['user']['login']:
            continue
        permission = api.repo('GET','/collaborators/'+quote(login,safe='')+'/permission')
        if permission and permission.get('permission') in ('admin','maintain','write'):
            approved += 1
    require(approved >= rule['requiredApprovingReviewCount'], 'not enough current-head authorized reviews')
    current = api.repo('GET',f'/pulls/{number}')
    require(current and current['head']['sha'] == sha and current['base']['sha'] == pr['base']['sha'] and current['base']['ref'] == pr['base']['ref'] and current.get('state') == 'open', 'PR changed after approval reservation')
    return number


def process(api, event, mode):
    dispatched = mode in ('approve', 'retry')
    number, comment, pr, command, name = comment_context(api, event, dispatched)
    if dispatched:
        require(command == mode, 'wrong receiver')
    marker = f'<!-- cloudopsworks-gitops:{comment["id"]}:{pr["head"]["sha"]}:{command} -->'
    comments = api.pages(f'/issues/{number}/comments')
    try:
        automation = api.request('GET', '/user')
    except GitHubError:
        automation = None
    require(automation and type(automation.get('id')) is int, 'BOT_TOKEN must authenticate a bot user; installation-only tokens are unsupported')
    if dispatched:
        require(event.get('sender', {}).get('id') == automation['id'], 'dispatch was not emitted by the authenticated automation')
    ours = lambda c: c.get('user', {}).get('id') == automation['id']
    if any(marker in c.get('body', '') and ours(c) for c in comments):
        return False
    if command in ('help', 'unsupported'):
        api.repo('POST', f'/issues/{number}/comments', {'body': marker + '\n' + HELP})
        return False
    if not dispatched:
        api.repo('POST', '/dispatches', {'event_type': name + '-command', 'client_payload': {
            'number': number, 'comment_id': comment['id'], 'body': comment['body'],
            'author_id': comment['user']['id'], 'head_sha': pr['head']['sha']}})
        return True
    number, comment, current_pr, current_command, _ = comment_context(api,event,True)
    require(current_pr['head']['sha'] == pr['head']['sha'] and current_command == command, 'intent changed')
    if command == 'approve':
        approve_intent(api,number,comment['user']['login'],pr['head']['sha'],allow_requested=True)
        require(pr.get('mergeable') is True, 'PR is not mergeable')
        # Recheck the mutable head immediately before writing.
        require(api.repo('GET', f'/pulls/{number}')['head']['sha'] == pr['head']['sha'], 'head changed')
        api.repo('POST', f'/issues/{number}/labels', {'labels': ['approved']})
    if command == 'retry':
        require(automerge_gate(api,event,'repository_dispatch',number=number) == number, 'PR retry is not currently merge-authorized')
    api.repo('POST', f'/issues/{number}/comments', {'body': marker + '\n' + ('Approval accepted.' if command == 'approve' else 'Authenticated PR automerge retry accepted.')})
    return True


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    require(len(args) == 1 and args[0] in ('command', 'approve', 'retry', 'automerge'), 'invalid GitOps operation')
    event_name = os.environ.get('GITHUB_EVENT_NAME')
    require(event_name in ('pull_request_target','check_suite','status') if args[0] == 'automerge' else event_name == ('issue_comment' if args[0] == 'command' else 'repository_dispatch'), 'unexpected event')
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    api = GitHub(os.environ['GITHUB_REPOSITORY'])
    number = automerge_gate(api,event,event_name) if args[0] == 'automerge' else None
    authorized = number is not None if args[0] == 'automerge' else process(api,event,args[0])
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('authorized=' + str(authorized).lower() + '\n')
            if authorized and args[0] in ('retry','automerge'):
                output.write('pull_request=' + str(number if args[0] == 'automerge' else event['client_payload']['number']) + '\n')


if __name__ == '__main__':
    try:
        main()
    except (GitOpsError, KeyError, ValueError) as exc:
        print('GitOps authorization failed: ' + str(exc), file=sys.stderr)
        sys.exit(1)
