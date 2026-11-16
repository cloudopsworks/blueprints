"""Read-only merged-PR continuation checks; version preparation is source-lane only.

A closure record is private source provenance, never deployment authority. All
GitHub operations here are reads (including branch-policy GraphQL queries).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile

from authorization import (_ancestor, _blueprint, _current_host, _id, _json_cli,
                           _protected_branch, _repository, _sha, require)
from executor import checked
from scan_entry import host
from snapshot import materialize_snapshot

ROOT = Path(__file__).resolve().parents[3]
_VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?')


def _merge(github, environ, *, source_sha=None, allow_unmerged=False):
    require(environ.get('GITHUB_EVENT_NAME') == 'pull_request_target', 'closure-event')
    repo, identity = _repository(github)
    require(identity == {'id': environ.get('GITHUB_REPOSITORY_ID'),
                         'fullName': environ.get('GITHUB_REPOSITORY')}, 'closure-repository')
    data = Path(environ['GITHUB_EVENT_PATH']).read_bytes()
    require(len(data) <= 2 * 1024 * 1024, 'closure-event-bound')
    event = json.loads(data)
    require(isinstance(event, dict) and event.get('action') == 'closed', 'closure-action')
    number = event.get('number')
    require(type(number) is int and _id(str(number)), 'closure-pr-number')
    pr = github.repo('GET', '/pulls/' + str(number))
    require(isinstance(pr, dict) and pr.get('number') == number
            and pr.get('state') == 'closed' and type(pr.get('merged')) is bool,
            'closure-pr')
    base = pr.get('base', {})
    require(isinstance(base, dict) and isinstance(base.get('repo'), dict)
            and str(base['repo'].get('id')) == identity['id']
            and base['repo'].get('full_name') == identity['fullName'], 'closure-base-repository')
    branch = base.get('ref')
    require(isinstance(branch, str) and 0 < len(branch) <= 256
            and environ.get('GITHUB_REF') == 'refs/heads/' + branch, 'closure-base')
    base_head = _protected_branch(github, branch)
    if not pr['merged']:
        require(allow_unmerged and source_sha is None, 'closure-not-merged')
        return {'prNumber': number, 'mergeSha': '', 'baseRef': branch}, pr
    merge = pr.get('merge_commit_sha')
    require(_sha(merge) and (source_sha is None or source_sha == merge), 'closure-merge-sha')
    _ancestor(github, merge, base_head)
    return {'prNumber': number, 'mergeSha': merge, 'baseRef': branch}, pr


def verify_merge(github, environ, source_sha=None):
    """Verify API merge provenance; callers separately establish current host trust."""
    return _merge(github, environ, source_sha=source_sha)[0]


def _current(github, runner, environ):
    blueprint = checked(runner, ['git', 'rev-parse', 'HEAD'], cwd=ROOT).strip()
    _blueprint(github, blueprint)
    repo, identity = _repository(github)
    require(identity == {'id': environ.get('GITHUB_REPOSITORY_ID'),
                         'fullName': environ.get('GITHUB_REPOSITORY')}, 'closure-repository')
    default_sha = _protected_branch(github, repo['default_branch'])
    current = host(environ, blueprint)
    run = _current_host(github, current, identity, blueprint, default_sha, continuation=True)
    # GitHub can omit run associations. A contradictory published association
    # cannot be ignored; empty-list host-event sufficiency remains activation-
    # gated pending independent review of this fixed canonical publisher path.
    associations = run.get('pull_requests', [])
    require(isinstance(associations, list), 'closure-run-pr')
    if associations:
        data = Path(environ['GITHUB_EVENT_PATH']).read_bytes()
        require(len(data) <= 2 * 1024 * 1024, 'closure-event-bound')
        event = json.loads(data)
        require(isinstance(event, dict) and type(event.get('number')) is int
                and len(associations) == 1 and isinstance(associations[0], dict)
                and type(associations[0].get('number')) is int
                and associations[0]['number'] == event['number'], 'closure-run-pr')


def _classify(github, runner, record, pr, *, version=None):
    # Source is immutable API data; executable source files are empty placeholders.
    with tempfile.TemporaryDirectory(prefix='closure-snapshot-') as directory:
        root = Path(directory).resolve()
        materialize_snapshot(github, record['mergeSha'], root)
        if version is None:
            branch = pr.get('head', {}).get('ref')
            require(isinstance(branch, str) and 0 < len(branch) <= 256
                    and not branch.startswith('refs/'), 'closure-head-ref')
            args = ['--event', 'pull_request_closed', '--ref', 'refs/heads/' + branch,
                    '--base-ref', record['baseRef']]
        else:
            require(isinstance(version, str) and _VERSION.fullmatch(version), 'closure-version')
            args = ['--event', 'push', '--ref', 'refs/tags/v' + version, '--base-ref', '']
        return _json_cli(runner, ['lifecycle', '--workdir', str(root), *args, '--json'])


def discover(github, runner, environ=os.environ):
    """Check the actual closure host and independently classify the merged source."""
    _current(github, runner, environ)
    record, pr = _merge(github, environ, allow_unmerged=True)
    eligible = bool(record['mergeSha']) and _classify(github, runner, record, pr).get('eligible') is True
    return {'eligible': eligible, **record}


def prepare(github, runner, environ, root):
    """Source-build job only: freeze one version before any component is built."""
    selected = discover(github, runner, environ)
    require(selected['eligible'], 'closure-ineligible')
    record, pr = _merge(github, environ, source_sha=selected['mergeSha'])
    root = Path(root).resolve()
    require(checked(runner, ['git', 'rev-parse', 'HEAD'], cwd=root).strip() == record['mergeSha'],
            'closure-checkout')
    checked(runner, ['tronador', 'project', 'version', '--workdir', str(root), '--allow-network', '--json'])
    version = (root / 'VERSION').read_text().strip().removeprefix('v')
    require(_classify(github, runner, record, pr, version=version).get('eligible') is True,
            'closure-tag-policy')
    return {'eligible': True, 'head': record['mergeSha'], 'version': version,
            'event': 'release', 'base': '', 'materialize-all': 'true'}


def verify_tag(github, runner, environ, *, head, version):
    """Recheck the current merge relationship and independently read the frozen tag."""
    _current(github, runner, environ)
    record, pr = _merge(github, environ, source_sha=head)
    require(_classify(github, runner, record, pr).get('eligible') is True, 'closure-ineligible')
    require(_classify(github, runner, record, pr, version=version).get('eligible') is True,
            'closure-tag-policy')
    require(github.tag_sha('v' + version) == record['mergeSha'], 'closure-tag-readback')
    return record


def main(argv=None):
    import argparse
    from executor import Runner
    from github import GitHub
    from normal_entry import output
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['discover','prepare','verify-tag'])
    parser.add_argument('--head');parser.add_argument('--version');args=parser.parse_args(argv)
    github=GitHub(os.environ['GITHUB_REPOSITORY'],os.environ['GH_TOKEN']);runner=Runner()
    if args.command=='discover':value=discover(github,runner,os.environ)
    elif args.command=='prepare':value=prepare(github,runner,os.environ,Path.cwd())
    else:value=verify_tag(github,runner,os.environ,head=args.head,version=args.version)
    if args.command!='verify-tag':
        output({key:str(item).lower() if isinstance(item,bool) else str(item) for key,item in value.items()},os.environ['GITHUB_OUTPUT'])


if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('closure-preparation-failed') from None
