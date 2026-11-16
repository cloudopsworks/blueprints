"""Actual Go/API-snapshot closure composition; GitHub/version processes are doubles.

No hosted runner, tag push, GitVersion calculation or cloud mutation is claimed.
"""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'cd/monorepo/runtime'))
import closure_entry as closure
from contracts import ContractError
from github import GitHub
from test_authorization import TemplateAPI, HostAPI

BINARY = os.environ.get('TRONADOR_TEST_BINARY')


class ClosureAPI(TemplateAPI):
    repository = 'example/mixed-app'
    request = HostAPI.request
    tag_sha = GitHub.tag_sha

    def __init__(self):
        super().__init__()
        self.bp = 'b' * 40
        self.calls = []
        self.pr = {'number': 17, 'state': 'closed', 'merged': True,
                   'merge_commit_sha': 'a' * 40,
                   'base': {'ref': 'master', 'repo': {'id': 12345, 'full_name': self.repository}},
                   'head': {'ref': 'feature/change'}}
        self.run = {'id': 200, 'run_attempt': 1, 'repository': {'id': 12345},
                    'event': 'pull_request_target', 'head_sha': 'c' * 40,
                    'path': '.github/workflows/pr-close.yaml', 'status': 'in_progress',
                    'referenced_workflows': [
                        {'path': 'cloudopsworks/blueprints/.github/workflows/' + name + '@v5.11.0', 'sha': self.bp}
                        for name in ('monorepo-pr-close.yml', 'monorepo-closure.yml')]}
        self.tag = 'a' * 40
        self.bad_caller = False
        self.bad_lineage = False
        self.protected = True

    def repo(self, method, path, **kwargs):
        self.calls.append((method, path))
        if method != 'GET':
            raise AssertionError('mutation attempted: ' + method)
        if path == '':
            return {'id': 12345, 'full_name': self.repository, 'default_branch': 'master'}
        if path == '/pulls/17':
            return copy.deepcopy(self.pr)
        if path.startswith('/git/ref/tags/'):
            return {'object': {'type': 'tag', 'sha': 'd' * 40}}
        if path == '/git/tags/' + 'd' * 40:
            return {'object': {'type': 'commit', 'sha': self.tag}}
        if path.startswith('/branches/'):
            return {'protected': self.protected, 'commit': {'sha': 'c' * 40}}
        if path.startswith('/compare/'):
            old = path.split('/compare/')[1].split('...')[0]
            return {'status': 'ahead', 'merge_base_commit': {'sha': 'f' * 40 if self.bad_lineage else old}}
        if path == '/actions/runs/200/attempts/1':
            return copy.deepcopy(self.run)
        if path.startswith('/contents/'):
            data = b'name: trusted-caller\n'
            if self.bad_caller and 'ref=' + 'e' * 40 in path:
                data = b'name: forged-caller\n'
            sha = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            return {'encoding': 'base64', 'content': base64.b64encode(data).decode(), 'sha': sha}
        return super().repo(method, path, **kwargs)


class Process:
    """Real components CLI, fixed native git/version boundary; no source commands."""
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.checkout = 'a' * 40
        self.version = '1.2.3'

    def run(self, argv, **kwargs):
        self.calls.append(argv)
        if argv == ['git', 'rev-parse', 'HEAD']:
            value = self.checkout if Path(kwargs['cwd']) == self.root else 'b' * 40
            return subprocess.CompletedProcess(argv, 0, value + '\n', '')
        if argv[:3] == ['tronador', 'project', 'version']:
            (self.root / 'VERSION').write_text(self.version + '\n')
            return subprocess.CompletedProcess(argv, 0, '{}', '')
        if argv[:3] == ['tronador', 'components', 'lifecycle']:
            snapshot = Path(argv[argv.index('--workdir') + 1])
            for item in snapshot.rglob('*'):
                if item.is_file() and item.suffix not in ('.yaml', '.yml') and item.name not in ('OWNERS', '.ruby'):
                    assert item.read_bytes() == b'', item
            return subprocess.run([BINARY, *argv[1:]], text=True, capture_output=True, **kwargs)
        raise AssertionError(argv)


@unittest.skipUnless(BINARY, 'set TRONADOR_TEST_BINARY to reviewed Go binary')
class ClosureEntryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        event = self.root / 'event.json'
        event.write_text(json.dumps({'action': 'closed', 'number': 17,
                                    'pull_request': {'merged': False, 'merge_commit_sha': 'f' * 40}}))
        self.env = {'GITHUB_REPOSITORY': 'example/mixed-app', 'GITHUB_REPOSITORY_ID': '12345',
                    'GITHUB_EVENT_NAME': 'pull_request_target', 'GITHUB_EVENT_PATH': str(event),
                    'GITHUB_RUN_ID': '200', 'GITHUB_RUN_ATTEMPT': '1', 'GITHUB_SHA': 'c' * 40,
                    'GITHUB_REF': 'refs/heads/master', 'GITHUB_WORKFLOW_SHA': 'e' * 40,
                    'GITHUB_WORKFLOW_REF': 'example/mixed-app/.github/workflows/pr-close.yaml@refs/heads/master',
                    'GITHUB_ACTOR': 'operator'}
        self.api = ClosureAPI()
        self.runner = Process(self.root)

    def test_connected_discover_prepare_verify_frozen_tag(self):
        expected = {'prNumber': 17, 'mergeSha': 'a' * 40, 'baseRef': 'master'}
        self.assertEqual(closure.discover(self.api, self.runner, self.env), {'eligible': True, **expected})
        prepared = closure.prepare(self.api, self.runner, self.env, self.root)
        self.assertEqual(prepared, {'eligible': True, 'head': 'a' * 40, 'version': '1.2.3',
                                    'event': 'release', 'base': '', 'materialize-all': 'true'})
        self.assertEqual(closure.verify_tag(self.api, self.runner, self.env,
                                           head=prepared['head'], version=prepared['version']), expected)
        self.assertEqual(sum(c[:3] == ['tronador', 'project', 'version'] for c in self.runner.calls), 1)
        self.assertTrue(all(method == 'GET' for method, _ in self.api.calls))
        self.assertTrue(any('--event' in c and 'pull_request_closed' in c for c in self.runner.calls))
        self.assertTrue(any('refs/tags/v1.2.3' in c for c in self.runner.calls))

    def test_actual_go_closed_policy_matches_push_tag_bases_not_open_pr_heads(self):
        for head, base in [('release/1.0', 'master'), ('support/1.x', 'master'),
                           ('feature/change', 'main'), ('feature/change', 'support/1.5.1')]:
            with self.subTest(head=head, base=base):
                self.api.pr['head']['ref'] = head
                self.api.pr['base']['ref'] = base
                self.env['GITHUB_REF'] = 'refs/heads/' + base
                self.env['GITHUB_WORKFLOW_REF'] = 'example/mixed-app/.github/workflows/pr-close.yaml@refs/heads/' + base
                self.assertTrue(closure.discover(self.api, self.runner, self.env)['eligible'])
        for base in ('develop', 'release/1.0'):
            with self.subTest(base=base):
                self.api.pr['base']['ref'] = base
                self.env['GITHUB_REF'] = 'refs/heads/' + base
                self.env['GITHUB_WORKFLOW_REF'] = 'example/mixed-app/.github/workflows/pr-close.yaml@refs/heads/' + base
                self.assertFalse(closure.discover(self.api, self.runner, self.env)['eligible'])
                with self.assertRaises(ContractError): closure.prepare(self.api, self.runner, self.env, self.root)
        self.assertFalse((self.root / 'VERSION').exists())

    def test_unmerged_close_skips_and_cannot_prepare_or_verify_tag(self):
        self.api.pr['merged'] = False
        self.assertEqual(closure.discover(self.api, self.runner, self.env),
                         {'eligible': False, 'prNumber': 17, 'mergeSha': '', 'baseRef': 'master'})
        for call in (lambda: closure.prepare(self.api, self.runner, self.env, self.root),
                     lambda: closure.verify_tag(self.api, self.runner, self.env, head='a' * 40, version='1.2.3')):
            with self.assertRaises(ContractError): call()
        self.assertFalse((self.root / 'VERSION').exists())

    def test_api_metadata_and_exact_current_host_fail_before_version(self):
        mutations = [lambda a, e: a.pr.update(number=18), lambda a, e: a.pr.update(state='open'),
                     lambda a, e: a.pr['base']['repo'].update(id=9),
                     lambda a, e: a.pr['base']['repo'].update(full_name='foreign/repo'),
                     lambda a, e: a.pr['base'].update(ref='main'),
                     lambda a, e: a.pr.update(merge_commit_sha='not-a-sha'),
                     lambda a, e: setattr(a, 'bad_lineage', True),
                     lambda a, e: setattr(a, 'protected', False),
                     lambda a, e: a.run.update(run_attempt=2),
                     lambda a, e: a.run.update(pull_requests=[{'number': 18}]),
                     lambda a, e: a.run.update(pull_requests=[{'number': True}]),
                     lambda a, e: a.run.update(head_sha='f' * 40),
                     lambda a, e: a.run.update(path='.github/workflows/main-build.yml'),
                     lambda a, e: a.run['referenced_workflows'].pop(),
                     lambda a, e: setattr(a, 'bad_caller', True),
                     lambda a, e: e.update(GITHUB_EVENT_NAME='pull_request'),
                     lambda a, e: e.update(GITHUB_REPOSITORY_ID='9')]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                api, env = ClosureAPI(), dict(self.env)
                mutate(api, env)
                with self.assertRaises(Exception): closure.prepare(api, self.runner, env, self.root)
                self.assertFalse((self.root / 'VERSION').exists())
                self.assertTrue(all(method == 'GET' for method, _ in api.calls))

    def test_nonempty_current_run_association_must_match_trusted_event(self):
        self.api.run['pull_requests'] = [{'number': 17}]
        self.assertTrue(closure.discover(self.api, self.runner, self.env)['eligible'])
        self.api.run['pull_requests'].append({'number': 18})
        with self.assertRaises(ContractError): closure.discover(self.api, self.runner, self.env)

    def test_closed_event_action_number_and_changed_merge_are_rechecked(self):
        event = Path(self.env['GITHUB_EVENT_PATH'])
        for payload in ({'action': 'opened', 'number': 17}, {'action': 'closed', 'number': True},
                        {'action': 'closed', 'number': '17'}):
            event.write_text(json.dumps(payload))
            with self.assertRaises(ContractError): closure.discover(self.api, self.runner, self.env)
        event.write_text(json.dumps({'action': 'closed', 'number': 17}))
        selected = closure.discover(self.api, self.runner, self.env)
        self.api.pr['merge_commit_sha'] = 'f' * 40
        with self.assertRaises(ContractError):
            closure.verify_tag(self.api, self.runner, self.env, head=selected['mergeSha'], version='1.2.3')
        self.assertFalse((self.root / 'VERSION').exists())

    def test_wrong_checkout_and_ineligible_base_do_not_calculate_version(self):
        self.runner.checkout = 'f' * 40
        with self.assertRaises(ContractError): closure.prepare(self.api, self.runner, self.env, self.root)
        self.runner.checkout = 'a' * 40
        self.api.pr['base']['ref'] = 'develop'
        self.env['GITHUB_REF'] = 'refs/heads/develop'
        self.env['GITHUB_WORKFLOW_REF'] = 'example/mixed-app/.github/workflows/pr-close.yaml@refs/heads/develop'
        self.assertFalse(closure.discover(self.api, self.runner, self.env)['eligible'])
        with self.assertRaises(ContractError): closure.prepare(self.api, self.runner, self.env, self.root)
        self.assertFalse((self.root / 'VERSION').exists())

    def test_verify_rechecks_api_merge_tag_and_version_without_version_process(self):
        cases = [('a' * 40, '1.2.3', 'f' * 40), ('f' * 40, '1.2.3', 'a' * 40),
                 ('a' * 40, '1.2.3;echo bad', 'a' * 40), ('a' * 40, '1.2.3+bad', 'a' * 40)]
        for head, version, tag in cases:
            with self.subTest(head=head, version=version):
                self.api.tag = tag
                with self.assertRaises(ContractError):
                    closure.verify_tag(self.api, self.runner, self.env, head=head, version=version)
        self.assertFalse(any(c[:3] == ['tronador', 'project', 'version'] for c in self.runner.calls))
        self.assertFalse((self.root / 'VERSION').exists())


if __name__ == '__main__':
    unittest.main()
