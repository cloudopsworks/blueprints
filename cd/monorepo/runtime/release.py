"""Immutable complete-manifest assembly and resumable draft publication."""
from __future__ import annotations
import copy
from contextlib import contextmanager, ExitStack
import os
from pathlib import Path
import re
import tempfile
from contracts import (API_VERSION, ContractError, canonical_bytes, digest, fail, load_record,
                       payload_digest, rooted_path, validate_artifact, validate_linked, validate_record)
from executor import checked


class ArtifactPublisher:
    def __init__(self, github, executor, registry):
        if not re.fullmatch(r'[a-z0-9][a-z0-9./_-]+', registry) or '..' in registry:
            fail('registry', 'registry repository prefix is invalid')
        self.github, self.executor, self.registry = github, executor, registry

    @contextmanager
    def read_auth(self, reference):
        """Fresh-job credentials, scoped to this publisher's trusted GHCR prefix."""
        token = os.environ.get('GH_TOKEN')
        trusted = (self.registry.startswith('ghcr.io/') and reference.startswith(self.registry.rstrip('/') + '/')
                   and not any(part in ('.','..') for part in reference.split('/')))
        if not token or not trusted:
            # Never consult ambient Docker/Skopeo credentials for external hosts.
            yield ['--src-no-creds']
            return
        actor = os.environ.get('GITHUB_ACTOR')
        if not actor or any(ch in token for ch in '\r\n'):
            fail('registry-auth', 'workflow registry identity is unavailable')
        with tempfile.TemporaryDirectory(prefix='monorepo-read-auth-') as directory:
            authfile = Path(directory) / 'auth.json'
            authfile.write_text('{"auths":{}}')
            authfile.chmod(0o600)
            checked(self.executor, ['skopeo','login','--authfile',str(authfile),
                '--username',actor,'--password-stdin','ghcr.io'], input=token)
            yield ['--src-authfile',str(authfile)]

    def fetch_oci(self, artifact, destination):
        """Read a verified digest into a private file for token-isolated scanners."""
        location=artifact.get('location',{})
        path=Path(destination)
        if artifact.get('format')!='oci' or location.get('kind')!='oci' or path.exists() or path.is_symlink():
            fail('registry-read','OCI read requires an immutable descriptor and new private file')
        with self.read_auth(location['reference']) as auth:
            checked(self.executor,['skopeo','copy','--all','--preserve-digests',*auth,
                'docker://'+location['reference'],'oci-archive:'+str(path)])
        path.chmod(0o600)
        validate_artifact(path,artifact)
        return path

    def verify(self, artifact):
        location = artifact['location']
        if location['kind'] == 'oci':
            with self.read_auth(location['reference']) as auth, tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'image.tar'
                checked(self.executor, ['skopeo', 'copy', '--all', '--preserve-digests', *auth,
                    'docker://' + location['reference'], 'oci-archive:' + str(path)])
                validate_artifact(path, artifact)
        elif location['kind'] == 'release-asset':
            if location['repositoryId'] != str(self.github.repo('GET', '')['id']):
                fail('repository-mismatch', 'published asset belongs to another repository')
            release = self.github.release(location['tag'])
            if not release:
                fail('artifact-missing', 'referenced release does not exist')
            assets = self.github.pages(f'/releases/{release["id"]}/assets')
            matches = [a for a in assets if a['name'] == location['name']]
            if len(matches) != 1:
                fail('artifact-missing', 'published release asset is missing or ambiguous')
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'asset'
                path.write_bytes(self.github.asset_bytes(matches[0]))
                validate_artifact(path, artifact)
        else:
            fail('artifact-location', 'published artifact cannot have a local location')

    def publish(self, artifact, component_id, role, root, release, tag, repository):
        result = copy.deepcopy(artifact)
        if artifact['location']['kind'] not in ('local', 'actions-artifact'):
            self.verify(artifact)
            return result
        # Actions locators are a staged transport, never a public release. Their
        # exact immutable ID and bytes are freshly checked before copying them.
        # Caller/stage/scan authorization is required at the orchestration seam.
        with ExitStack() as stack:
            if artifact['location']['kind'] == 'actions-artifact':
                from actions_payload import fetch_payload
                directory = stack.enter_context(tempfile.TemporaryDirectory(prefix='monorepo-publish-'))
                path = fetch_payload(self.github, artifact, repository, Path(directory) / 'payload')
            else:
                path = rooted_path(root, artifact['location']['path'], output=True)
                validate_artifact(path, artifact)
            return self._publish_path(result, component_id, role, path, release, tag, repository)

    def _publish_path(self, result, component_id, role, path, release, tag, repository):
        artifact = result
        if artifact['format'] == 'oci':
            name = f'{self.registry}/{component_id}:{role}-{artifact["digest"][7:]}'
            with self.read_auth(name) as auth:
                from providers.registry import _publication, _publication_run
                try:
                    _publication.publish(_publication_run(self.executor),transport='oci-archive',
                        source='oci-archive:'+str(path),repository=name.rsplit(':',1)[0],
                        tags=(name.rsplit(':',1)[1],),expected_digest=artifact['digest'],
                        authfile=auth[1] if auth[0]=='--src-authfile' else None)
                except _publication.PublicationError:
                    fail('registry-publication','immutable registry readback differs')
            result['location'] = {'kind': 'oci', 'reference': name.rsplit(':', 1)[0] + '@' + artifact['digest']}
            self.verify(result)
        else:
            extension = {'zip': 'zip', 'tar.gz': 'tar.gz', 'openapi-json': 'json', 'openapi-yaml': 'yaml'}[artifact['format']]
            name = f'{component_id}-{role}-{artifact["digest"][7:]}.{extension}'
            assets = self.github.pages(f'/releases/{release["id"]}/assets')
            prior = [a for a in assets if a['name'] == name]
            if prior:
                if len(prior) != 1 or self.github.asset_bytes(prior[0]) != path.read_bytes():
                    fail('asset-conflict', 'existing immutable release asset differs')
            else:
                self.github.upload_asset(release, name, path)
            result['location'] = {'kind': 'release-asset', 'repositoryId': repository['id'], 'tag': tag, 'name': name}
            self.verify(result)
        return result


def assemble_manifest(plan, results, previous, publish):
    validate_record(plan)
    if previous:
        validate_record(previous)
        if previous['repository'] != plan['repository']:
            fail('repository-mismatch', 'baseline belongs to another repository')
    selected = {item['componentId'] for item in plan['buildSelection']}
    found = {}
    for result in results:
        validate_linked(result, {'plan': plan})
        ident = result['componentId']
        if ident in found or result['status'] != 'succeeded':
            fail('build-result', 'duplicate or unsuccessful selected build result')
        found[ident] = result
    if set(found) != selected:
        fail('build-result', 'selected build results are incomplete')
    old = {c['componentId']: c for c in previous['components']} if previous else {}
    entries = []
    for component in plan['components']:
        ident = component['id']
        source = found.get(ident) or old.get(ident)
        if not source or source.get('package', component['package']) != component['package']:
            fail('artifact-missing', 'active component has no compatible built or carried artifact')
        entry = {'componentId': ident, 'package': component['package'], 'workload': component['workload'],
                 'targetIds': component['targetIds']}
        for field, role in [('mainArtifact', 'main'), ('previewArtifact', 'preview')]:
            artifact = source[field]
            if field == 'previewArtifact' and component['preview']['mode'] == 'container' and artifact is None:
                fail('preview-artifact', 'container preview artifact is missing')
            entry[field] = publish(artifact, ident, role) if artifact else None
        entries.append(entry)
    manifest = {'apiVersion': API_VERSION, 'kind': 'ReleaseManifest', 'repository': plan['repository'],
                'version': plan['version'], 'tag': 'v' + plan['version'], 'headSha': plan['headSha'],
                'previousTag': previous['tag'] if previous else None, 'state': 'complete',
                'components': entries, 'targets': plan['targets']}
    return validate_record(manifest)


def verify_manifest(manifest, github, publisher, *, allow_draft=False):
    validate_record(manifest)
    release = github.release(manifest['tag'])
    if not release or release.get('tag_name') != manifest['tag']:
        fail('release-unverified', 'release tag/source/publication state differs')
    sha = github.tag_sha(manifest['tag'])
    if release['draft']:
        if not allow_draft or release.get('target_commitish') != manifest['headSha'] or sha not in (None,manifest['headSha']):
            fail('release-unverified', 'draft release target or existing tag differs')
    elif sha != manifest['headSha']:
        fail('release-unverified', 'published release tag does not resolve to manifest source')
    for component in manifest['components']:
        for name in ('mainArtifact', 'previewArtifact'):
            if component[name]:
                publisher.verify(component[name])
    return release


def _start_release(plan, github):
    tag = 'v' + plan['version']
    sha = github.tag_sha(tag)
    if sha is not None and sha != plan['headSha']:
        fail('tag-conflict', 'release tag already points at another commit')
    release = github.release(tag)
    if not release:
        release = github.repo('POST', '/releases', {'tag_name': tag, 'target_commitish': plan['headSha'],
            'name': tag, 'draft': True, 'prerelease': '-' in plan['version']})
    if release.get('tag_name') != tag or (release['draft'] and release.get('target_commitish') != plan['headSha']):
        fail('draft-conflict', 'release draft is not frozen to the requested source')
    return release, tag


def _commit_manifest(manifest, github, publisher, release):
    tag = manifest['tag']
    assets = github.pages(f'/releases/{release["id"]}/assets')
    existing = [a for a in assets if a['name'] == 'monorepo-manifest.json']
    data = canonical_bytes(manifest)
    if existing:
        if len(existing) != 1 or github.asset_bytes(existing[0]) != data:
            fail('manifest-conflict', 'existing complete manifest differs; immutable publication refused')
    elif not release['draft']:
        fail('manifest-missing', 'published release cannot be repaired by silently adding a manifest')
    else:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'monorepo-manifest.json'
            path.write_bytes(data)
            github.upload_asset(release, path.name, path)
    # Read-back is the commit barrier; file creation/upload alone proves nothing.
    assets = github.pages(f'/releases/{release["id"]}/assets')
    uploaded = next((a for a in assets if a['name'] == 'monorepo-manifest.json'), None)
    if not uploaded or github.asset_bytes(uploaded) != data:
        fail('manifest-unverified', 'uploaded manifest failed read-back verification')
    verified = verify_manifest(manifest, github, publisher, allow_draft=True)
    if verified['id'] != release['id'] or verified['draft'] != release['draft']:
        fail('release-identity', 'release identity or publication state changed before commit')
    if release['draft']:
        github.repo('PATCH', f'/releases/{release["id"]}', {'draft': False})
    published = verify_manifest(manifest, github, publisher)
    if published['id'] != release['id']:
        fail('release-identity', 'published release identity differs from verified draft')
    return manifest


def publish_release(plan, results, previous, github, publisher, root):
    validate_record(plan)
    if previous:
        verify_manifest(previous, github, publisher)
    release, tag = _start_release(plan, github)
    manifest = assemble_manifest(plan, results, previous,
        lambda artifact, ident, role: publisher.publish(artifact, ident, role, root, release, tag, plan['repository']))
    return _commit_manifest(manifest, github, publisher, release)


def publish_staged_release(plan, staged, github, publisher, root):
    """Convert an independently authorized complete stage into public assets.

    Eligibility/caller/current scan authorization belongs to the protected entry;
    this data boundary neither invents a version nor executes repository source.
    All expiring Actions locations are copied and reverified before commit.
    """
    validate_record(plan); validate_record(staged)
    if any(staged[field] != plan[field] for field in ('repository','version','headSha','targets')):
        fail('stage-release-binding', 'complete stage differs from authorized build plan')
    expected = {component['id']: component for component in plan['components']}
    if {component['componentId'] for component in staged['components']} != set(expected):
        fail('stage-release-binding', 'complete stage component membership differs')
    for component in staged['components']:
        source = expected[component['componentId']]
        if any(component[field] != source[field] for field in ('package','workload','targetIds')):
            fail('stage-release-binding', 'complete stage component contract differs')
    release, tag = _start_release(plan, github)
    manifest = copy.deepcopy(staged)
    for component in manifest['components']:
        for field, role in (('mainArtifact','main'),('previewArtifact','preview')):
            if component[field] is not None:
                component[field] = publisher.publish(component[field], component['componentId'], role,
                    root, release, tag, plan['repository'])
    validate_record(manifest)
    return _commit_manifest(manifest, github, publisher, release)
