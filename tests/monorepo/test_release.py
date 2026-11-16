import diagnostic_support
import copy
import importlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'cd/monorepo/runtime'))
from contracts import ContractError, canonical_bytes, load_record, validate_record
from release import ArtifactPublisher, assemble_manifest, publish_release, verify_manifest
from deploy import prepare, reconcile
from receipts import ReceiptStore

FIXTURES = Path(__file__).with_name('contracts') / 'valid'

def fixture(name):
    return load_record(FIXTURES / (name + '.json'))


class MemoryGitHub:
    def __init__(self):
        self.release_value = None
        self.sha = None
        self.assets = []
        self.data = {}
        self.deployments = []
        self.statuses = {}
        self.calls = []
        self.fail_publish = False

    def release(self, tag):
        return copy.deepcopy(self.release_value)

    def tag_sha(self, tag):
        return self.sha

    def pages(self, suffix):
        if suffix.startswith('/releases/'):
            return self.assets
        if suffix.startswith('/deployments?'):
            environment = suffix.split('environment=')[1]
            return [d for d in self.deployments if d['environment'] == environment]
        if suffix.endswith('/statuses'):
            return self.statuses.get(int(suffix.split('/')[2]), [])
        raise AssertionError(suffix)

    def repo(self, method, suffix, data=None):
        self.calls.append((method, suffix, data))
        if method == 'POST' and suffix == '/releases':
            self.release_value = {'id': 1, 'tag_name': data['tag_name'], 'target_commitish': data['target_commitish'], 'draft': True}
            return copy.deepcopy(self.release_value)
        if method == 'PATCH':
            if self.fail_publish:
                raise RuntimeError('simulated interruption')
            self.release_value.update(data)
            if data.get('draft') is False:
                self.sha = self.release_value['target_commitish']
            return self.release_value
        if method == 'POST' and suffix == '/deployments':
            deployment = {**copy.deepcopy(data), 'id': len(self.deployments) + 1, 'creator': {'id': 99}}
            self.deployments.append(deployment)
            return deployment
        if method == 'POST' and suffix.endswith('/statuses'):
            ident = int(suffix.split('/')[2])
            status = {**data, 'id': sum(len(s) for s in self.statuses.values()) + 1, 'creator': {'id': 99}}
            self.statuses.setdefault(ident, []).append(status)
            return status
        raise AssertionError((method, suffix))

    def upload_asset(self, release, name, path):
        asset = {'id': len(self.assets) + 1, 'name': name}
        self.assets.append(asset)
        self.data[asset['id']] = Path(path).read_bytes()
        return asset

    def asset_bytes(self, asset):
        return self.data[asset['id']]


class Publisher:
    def __init__(self):
        self.verified = []

    def publish(self, artifact, component, role, *args):
        result = copy.deepcopy(artifact)
        result['location'] = {'kind': 'oci', 'reference': 'ghcr.io/example/' + component + '@' + artifact['digest']}
        return result

    def verify(self, artifact):
        self.verified.append(artifact['digest'])


class ReleaseTests(unittest.TestCase):
    def test_private_ghcr_manifest_verification_in_fresh_baseline_and_apply_jobs(self):
        class FreshExecutor:
            def __init__(self, fail_copy=False, public=False):
                self.calls=[];self.authorized=set();self.authfiles=[];self.fail_copy=fail_copy;self.public=public
            def run(self, argv, **kwargs):
                self.calls.append((argv,kwargs))
                if argv[:2]==['skopeo','login']:
                    path=Path(argv[argv.index('--authfile')+1])
                    self.authfiles.append(path)
                    assert path.stat().st_mode & 0o777 == 0o600
                    assert kwargs['input']=='private-token'
                    assert argv[-1]=='ghcr.io'
                    self.authorized.add(str(path))
                    return SimpleNamespace(returncode=0,stdout='',stderr='')
                assert argv[:2]==['skopeo','copy']
                authenticated='--src-authfile' in argv and argv[argv.index('--src-authfile')+1] in self.authorized
                if self.fail_copy or not (authenticated or self.public):
                    return SimpleNamespace(returncode=1,stdout='',stderr='private-token must not leak')
                Path(argv[-1].removeprefix('oci-archive:')).write_bytes((FIXTURES.parent/'artifacts/image.oci.tar').read_bytes())
                return SimpleNamespace(returncode=0,stdout='',stderr='')
        artifact=fixture('oci-image-valid')['mainArtifact']
        artifact['location']={'kind':'oci','reference':'ghcr.io/example/repo/api@'+artifact['digest']}
        manifest=fixture('release-manifest')
        manifest['components'][0].update(mainArtifact=artifact,previewArtifact=artifact)
        github=MemoryGitHub();github.sha=manifest['headSha'];github.release_value={'id':1,'draft':False,'tag_name':manifest['tag']}
        with patch.dict('os.environ',{'GH_TOKEN':'private-token','GITHUB_ACTOR':'trusted-actor'},clear=True):
            for job in ('baseline','apply'):
                with self.subTest(job=job):
                    ex=FreshExecutor()
                    verify_manifest(manifest,github,ArtifactPublisher(github,ex,'ghcr.io/example/repo'))
                    self.assertEqual(len(ex.authorized),2)
                    self.assertTrue(all(not path.exists() for path in ex.authfiles))
                    self.assertTrue(all('private-token' not in ' '.join(argv) for argv,kw in ex.calls))
            ex=FreshExecutor(fail_copy=True)
            with self.assertRaises(Exception) as error:ArtifactPublisher(github,ex,'ghcr.io/example/repo').verify(artifact)
            self.assertNotIn('private-token',str(error.exception))
            self.assertTrue(all(not path.exists() for path in ex.authfiles))
            for reference in ('ghcr.io/example/repo-evil/api','evil.example/api'):
                external=copy.deepcopy(artifact);external['location']['reference']=reference+'@'+artifact['digest']
                ex=FreshExecutor(public=True)
                ArtifactPublisher(github,ex,'ghcr.io/example/repo').verify(external)
                self.assertFalse(ex.authorized)
                self.assertIn('--src-no-creds',ex.calls[0][0])
        with patch.dict('os.environ',{},clear=True):
            ex=FreshExecutor()
            with self.assertRaises(Exception):ArtifactPublisher(github,ex,'ghcr.io/example/repo').verify(artifact)
            self.assertFalse(ex.authorized)
        prepare=(ROOT/'.github/workflows/monorepo-manual-apply.yml').read_text().split('  component-scan:')[1].split('    steps:')[0]
        self.assertIn('      packages: read',prepare)
        self.assertNotIn('id-token: write',prepare)
        self.assertNotIn('deployments: write',prepare)

    def test_draft_discovery_resume_when_tag_endpoint_is_published_only(self):
        from github import GitHub, GitHubError
        class DraftAPI(MemoryGitHub):
            release=GitHub.release
            def pages(self,suffix):
                if suffix=='/releases':return GitHub.pages(self,suffix)
                return super().pages(suffix)
            def repo(self,method,suffix,data=None):
                if method=='GET' and suffix.startswith('/releases/tags/'):
                    return copy.deepcopy(self.release_value) if self.release_value and not self.release_value['draft'] else None
                if method=='GET' and suffix.startswith('/releases?'):
                    if suffix.endswith('&page=1'):
                        return [{'id':i+100,'tag_name':'other','draft':False} for i in range(100)]
                    return [copy.deepcopy(self.release_value)] if self.release_value else []
                if method=='GET' and suffix=='/releases/1':return copy.deepcopy(self.release_value)
                return super().repo(method,suffix,data)
        plan,result=fixture('build-plan'),fixture('component-result')
        github=DraftAPI();github.fail_publish=True;publisher=Publisher()
        with self.assertRaises(RuntimeError):publish_release(plan,[result],None,github,publisher,Path('.'))
        self.assertIsNone(github.sha)
        self.assertTrue(github.release('v'+plan['version'])['draft'])
        github.fail_publish=False
        manifest=publish_release(plan,[result],None,github,publisher,Path('.'))
        self.assertEqual(github.sha,plan['headSha'])
        self.assertEqual(len([c for c in github.calls if c[:2]==('POST','/releases')]),1)
        self.assertFalse(github.release(manifest['tag'])['draft'])
        github.sha='f'*40
        with self.assertRaises(ContractError):verify_manifest(manifest,github,publisher)
        github=DraftAPI();github.release_value={'id':1,'tag_name':'v'+plan['version'],'draft':True,'target_commitish':'mutable-branch'}
        with self.assertRaises(ContractError):publish_release(plan,[result],None,github,publisher,Path('.'))
        self.assertEqual(github.assets,[])
        github.release_value['target_commitish']=plan['headSha'];github.sha='f'*40
        with self.assertRaises(ContractError):publish_release(plan,[result],None,github,publisher,Path('.'))
        self.assertEqual(github.assets,[])

    def test_registry_transport_tag_is_bounded_and_semver_independent(self):
        class Executor:
            def __init__(self): self.calls=[]
            def run(self, argv, **kwargs):
                self.calls.append(argv)
                return SimpleNamespace(returncode=0, stdout=artifact['digest'] if argv[:2]==['skopeo','inspect'] else '', stderr='')
        for version in ('1.2.3+build.456', '1.2.3-'+'a'*220):
            artifact=fixture('oci-image-valid')['mainArtifact']
            artifact['builtVersion']=version
            ex=Executor()
            publisher=ArtifactPublisher(None,ex,'ghcr.io/example')
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory).resolve()
                path=root/artifact['location']['path']
                path.parent.mkdir(parents=True)
                path.write_bytes((FIXTURES.parent/'artifacts/image.oci.tar').read_bytes())
                with patch.object(publisher,'verify'):
                    published=publisher.publish(artifact,'api','main',root,{},'v'+version,{'id':'1'})
            destination=ex.calls[0][-1]
            self.assertEqual(destination,'docker://ghcr.io/example/api:main-'+artifact['digest'][7:])
            self.assertNotIn('+',destination)
            self.assertEqual(published['builtVersion'],version)
            self.assertEqual(published['location']['reference'],'ghcr.io/example/api@'+artifact['digest'])

    def test_draft_verify_publish_and_idempotent_retry(self):
        plan, result = fixture('build-plan'), fixture('component-result')
        github, publisher = MemoryGitHub(), Publisher()
        manifest = publish_release(plan, [result], None, github, publisher, Path('.'))
        self.assertFalse(github.release_value['draft'])
        self.assertEqual(len(github.assets), 1)
        self.assertEqual(manifest, publish_release(plan, [result], None, github, publisher, Path('.')))
        self.assertEqual(len(github.assets), 1)
        self.assertGreaterEqual(len(publisher.verified), 4)

    def test_interrupted_draft_not_baseline_and_resume(self):
        github, publisher = MemoryGitHub(), Publisher()
        github.fail_publish = True
        with self.assertRaises(RuntimeError):
            publish_release(fixture('build-plan'), [fixture('component-result')], None, github, publisher, Path('.'))
        self.assertTrue(github.release_value['draft'])
        github.fail_publish = False
        publish_release(fixture('build-plan'), [fixture('component-result')], None, github, publisher, Path('.'))
        self.assertFalse(github.release_value['draft'])
        self.assertEqual(len(github.assets), 1)

    def test_config_only_carries_honest_provenance(self):
        plan, previous = fixture('build-plan'), fixture('release-manifest')
        plan.update(version='1.2.4', buildSelection=[], buildNoop=True, matrix={'include': []})
        plan['components'][0]['workload']['port'] = 4000
        manifest = assemble_manifest(plan, [], previous, lambda a, *_: copy.deepcopy(a))
        self.assertEqual(manifest['components'][0]['mainArtifact'], previous['components'][0]['mainArtifact'])
        self.assertEqual(manifest['components'][0]['workload']['port'], 4000)
        self.assertEqual(manifest['components'][0]['mainArtifact']['builtVersion'], '1.2.3')

    def test_missing_wrong_duplicate_or_failed_results_fail(self):
        plan, result = fixture('build-plan'), fixture('component-result')
        for results in ([], [result, result], [{**result, 'headSha': 'b'*40}], [{**result, 'status': 'failed', 'error': {'code': 'build', 'message': 'failed', 'retryable': False}}]):
            with self.subTest(results=len(results)), self.assertRaises(ContractError):
                assemble_manifest(plan, results, None, lambda a, *_: a)

    def test_global_ownership_precedes_mutation(self):
        manifest = fixture('release-manifest')
        component = copy.deepcopy(manifest['components'][0])
        component['componentId'] = 'second'
        manifest['components'].append(component)
        calls = []
        def resolve(request, executor):
            calls.append(request['componentId'])
            return {'providerIdentity': 'gcp:123', 'resourceClaims': ['gcp:123:service:api'], 'resource': {}}
        # Intrinsic ownership also detects obvious aliases, before API discovery.
        with self.assertRaises(ContractError):
            prepare(manifest, None, {'gcp-prod': 'gcp:123'}, resolver=resolve)

    def test_failed_attempt_retries_even_without_source_builds(self):
        manifest = fixture('release-manifest')
        rows = prepare(manifest, None, {'gcp-prod': 'gcp:123'}, resolver=lambda *args:
            {'providerIdentity': 'gcp:123', 'resourceClaims': ['gcp:123:service:api'], 'resource': {}})
        github = MemoryGitHub()
        store = ReceiptStore(github, manifest['repository'], '99')
        request = rows[0]['request']
        attempt = store.begin(request)
        store.status(attempt['id'], 'failure')
        self.assertEqual(store.convergence(request)[0], 'retry-unresolved')
        calls = []
        def deploy(request, executor, **kwargs):
            calls.append(request)
            base = fixture('deployment-result')
            base.update(targetConfigDigest=request['target']['configDigest'], idempotencyKey=request['idempotencyKey'])
            return base
        results = reconcile(rows, None, store, deployer=deploy)
        self.assertEqual(len(results), 1)
        self.assertEqual(calls[0]['reason'], 'retry-unresolved')
        self.assertEqual(store.convergence(request)[0], None)
        # New failed attempt after success must not be hidden by older success.
        attempt = store.begin(request)
        store.status(attempt['id'], 'failure')
        self.assertEqual(store.convergence(request)[0], 'retry-unresolved')

    def test_new_target_and_config_changes_without_rebuild(self):
        manifest = fixture('release-manifest')
        resolver = lambda *args: {'providerIdentity': 'gcp:123', 'resourceClaims': ['gcp:123:service:api'], 'resource': {}}
        before = prepare(manifest, None, {'gcp-prod': 'gcp:123'}, resolver=resolver)[0]['request']
        manifest['components'][0]['workload']['port'] = 4321
        after = prepare(manifest, None, {'gcp-prod': 'gcp:123'}, resolver=resolver)[0]['request']
        self.assertEqual(before['artifact'], after['artifact'])
        self.assertNotEqual(before['target']['configDigest'], after['target']['configDigest'])
        self.assertNotEqual(before['idempotencyKey'], after['idempotencyKey'])
        self.assertEqual(ReceiptStore(MemoryGitHub(), manifest['repository'], '99').convergence(after), ('first-deploy', None))


if __name__ == '__main__':
    unittest.main()
