"""Global read-only ownership preflight then per-binding durable convergence."""
from __future__ import annotations
import copy
import importlib
from pathlib import Path
import tempfile
from contracts import API_VERSION, claims_overlap, digest, fail, validate_record


def provider(name):
    if name not in ('aws', 'gcp', 'azure'):
        fail('provider', 'unknown provider')
    return importlib.import_module('providers.' + name)


def effective_digest(target, workload, resolution):
    normalized = {key: value for key, value in target.items() if key != 'configDigest'}
    return digest({'domain': 'effective-target/v1', 'target': normalized, 'workload': workload,
                   'providerIdentity': resolution['providerIdentity'], 'resourceClaims': sorted(resolution['resourceClaims']), 'registryConfig': resolution.get('registryConfig')})


def request_for(manifest, component, target):
    return {'apiVersion': API_VERSION, 'kind': 'DeploymentRequest', 'repository': manifest['repository'],
            'operation': 'apply', 'componentId': component['componentId'], 'releaseVersion': manifest['version'],
            'releaseHeadSha': manifest['headSha'], 'manifestDigest': digest(manifest), 'target': copy.deepcopy(target),
            'package': component['package'], 'workload': component['workload'], 'artifact': component['mainArtifact'],
            'idempotencyKey': 'sha256:' + '0'*64, 'previousReceiptId': None, 'reason': 'first-deploy'}


def prepare(manifest, executor, identities, *, resolver=None, registries=None):
    """Resolve every binding before ANY adapter mutation; claims are global."""
    validate_record(manifest)
    targets = {target['id']: target for target in manifest['targets']}
    rows, claims = [], {}
    for component in manifest['components']:
        for target_id in component['targetIds']:
            target = targets[target_id]
            request = validate_record(request_for(manifest, component, target))
            resolution = (resolver or provider(target['provider']).resolve)(request, executor)
            expected = identities.get(target['authRef'])
            if not expected or resolution.get('providerIdentity') != expected:
                fail('resolved-account-mismatch', 'actual account does not match protected auth binding')
            from providers.registry import bind_resolution
            resolution = bind_resolution(request,resolution,executor,registries or {})
            resources = resolution.get('resourceClaims')
            if not isinstance(resources, list) or not resources or any(not isinstance(r, str) or not r for r in resources):
                fail('resource-ownership', 'provider did not resolve every mutable resource claim')
            for claim in resources:
                # Provider claims normalize prefixes as trailing slash. Same or
                # ancestor directory claims conflict; unrelated prefixes do not.
                for old in claims:
                    if claims_overlap(claim, old):
                        fail('resource-ownership', 'multiple bindings own the same canonical mutable resource')
                claims[claim] = (target_id, component['componentId'])
            request['target']['configDigest'] = effective_digest(target, component['workload'], resolution)
            request['idempotencyKey'] = digest({'repositoryId': manifest['repository']['id'], 'targetId': target_id,
                'componentId': component['componentId'], 'artifactDigest': request['artifact']['digest'],
                'targetConfigDigest': request['target']['configDigest']})
            rows.append({'request': validate_record(request), 'resolved': resolution})
    return rows


def reconcile(rows, executor, store, *, context=None, deployer=None, force=False):
    from diagnostics import event
    results = []
    for row in rows:
        request, resolution = copy.deepcopy(row['request']), row['resolved']
        reason, previous = store.convergence(request)
        if reason is None and not force:
            event('convergence','reused',component=request['componentId'],target=request['target']['id'],reason='already-converged',source=request['artifact']['sourceSha'],version=request['releaseVersion'],digest=request['artifact']['digest'],reused=1)
            continue
        request['reason'] = 'explicit-reconcile' if force else reason
        event('convergence','selected',component=request['componentId'],target=request['target']['id'],reason=request['reason'],source=request['artifact']['sourceSha'],version=request['releaseVersion'],digest=request['artifact']['digest'],selected=1)
        request['previousReceiptId'] = previous
        validate_record(request)
        attempt = store.begin(request)
        try:
            result = (deployer or provider(request['target']['provider']).deploy)(request, executor,
                context={**(context or {}), 'expectedIdentity': resolution['providerIdentity']}, resolved=resolution)
            validate_record(result)
            for field, wanted in [('repository', request['repository']), ('componentId', request['componentId']),
                ('targetId', request['target']['id']), ('artifactDigest', request['artifact']['digest']),
                ('targetConfigDigest', request['target']['configDigest']), ('idempotencyKey', request['idempotencyKey'])]:
                if result[field] != wanted:
                    fail('deployment-result', 'provider result identity differs from requested deployment')
            if result['status'] != 'succeeded' and (context or {}).get('result_sink'):(context['result_sink'])(result)
            store.finish(attempt, request, result)
            if result['status'] == 'succeeded' and (context or {}).get('result_sink'):(context['result_sink'])(result)
            results.append(result)
        except Exception as error:
            if (context or {}).get('result_sink'):
                from providers.common import result as failed_result
                context['result_sink'](failed_result(request,error=error))
            store.status(attempt['id'], 'failure')
            raise
    return results
