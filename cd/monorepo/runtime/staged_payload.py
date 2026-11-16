"""Materialize a host-authorized stage without creating a visible GitHub release."""
import copy
from pathlib import Path
from authorization import PreparedAuthorization
from actions_payload import fetch_payload
from contracts import fail, validate_artifact


def materialize(prepared, publisher, request, *, workdir):
    """Return private provider context, preserving the original wire descriptor.

    This seam runs only AFTER independent host/config/current scanner authority.
    Registry publication is separate from workload IaC mutation. It never turns
    a self-declared stage artifact into publication or deployment authority.
    """
    if (not isinstance(prepared, PreparedAuthorization) or not prepared._bound
            or prepared._inspection):
        fail('staged-payload-authorization', 'independently prepared protected context is required')
    if request['repository'] != prepared.plan['repository']:
        fail('staged-payload-repository', 'requested repository differs from authorized stage')
    records = [record for record in prepared.manifest['components']
               if record['componentId'] == request['componentId']]
    if len(records) != 1 or records[0]['mainArtifact'] != request['artifact']:
        fail('staged-payload-binding', 'requested artifact differs from independently verified stage')
    original = copy.deepcopy(request['artifact'])
    location = original['location']
    if location['kind'] == 'oci':
        publisher.verify(original)
        return {'artifactImageReference': location['reference']}
    root = Path(workdir).resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.stat().st_mode & 0o077:
        fail('staged-payload-workspace', 'payload workspace must be private')
    path = root / 'payload'
    if location['kind'] == 'actions-artifact':
        fetch_payload(publisher.github, original, request['repository'], path)
    elif location['kind'] == 'release-asset':
        publisher.verify(original)
        release = publisher.github.release(location['tag'])
        matches = [asset for asset in publisher.github.pages(f'/releases/{release["id"]}/assets')
                   if asset['name'] == location['name']]
        if len(matches) != 1:
            fail('staged-payload-asset', 'immutable release payload is missing or ambiguous')
        with path.open('xb') as output:
            path.chmod(0o600); output.write(publisher.github.asset_bytes(matches[0]))
        validate_artifact(path, original)
    else:
        fail('staged-payload-location', 'privileged materialization rejects local source paths')
    result = {'artifactPath': path}
    if original['format'] == 'oci':
        # Publish exact already-verified bytes; no draft/visible Release is used.
        published = publisher._publish_path(copy.deepcopy(original), request['componentId'],
            'main', path, None, None, request['repository'])
        if published['digest'] != original['digest'] or published['location']['kind'] != 'oci':
            fail('staged-payload-image', 'registry publication changed artifact identity')
        result['artifactImageReference'] = published['location']['reference']
    if request['artifact'] != original:
        fail('staged-payload-mutation', 'publication changed the authorized request descriptor')
    return result
