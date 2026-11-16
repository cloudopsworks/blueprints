"""Normal main-build's read-only, complete-set physical-ownership barrier.

Markers are evidence only inside independently prepared current-run job logs.
Manual operations and Kubernetes previews have different scope/ownership rules
and deliberately cannot use this normal-deployment barrier.
"""
from __future__ import annotations

import copy

from authorization import PreparedAuthorization, MAX_LOG_BYTES, _digest, _job, _records, _stage_locator
from contracts import canonical_bytes, claims_overlap, digest, fail
from operations import _claims

BINDING_MARKER = 'CLOUDOPSWORKS_PREFLIGHT_V1 '
BARRIER_MARKER = 'CLOUDOPSWORKS_PREFLIGHT_BARRIER_V1 '
BINDING_FIELDS = {'stage', 'policyDigest', 'targetId', 'componentId', 'bindingDigest',
                  'providerIdentity', 'resourceClaims', 'stateHandleDigest'}
BARRIER_FIELDS = {'stage', 'policyDigest', 'bindingsDigest', 'bindings'}
PREFIX = 'lifecycle / '


def _require(condition, code):
    if not condition:
        fail('preflight-' + code, 'Normal deployment preflight evidence does not bind the complete current stage')


def _context(prepared):
    _require(isinstance(prepared, PreparedAuthorization) and not prepared._inspection
             and prepared.scan_results is not None, 'authorization')
    host = prepared.current_host
    caller = host['workflowRef'].split('@', 1)[0]
    _require(caller == prepared.repository['fullName'] + '/.github/workflows/main-build.yml'
             and prepared.host.get('callerPath') == '.github/workflows/main-build.yml', 'caller')
    _stage_locator(prepared.stage)
    targets = {target['id']: target for target in prepared.manifest['targets']}
    _require(len(targets) == len(prepared.manifest['targets']), 'targets')
    expected = {}
    names = set()
    for component in prepared.manifest['components']:
        for target_id in component['targetIds']:
            key = (target_id, component['componentId'])
            name = PREFIX + 'monorepo-preflight-' + target_id + '-' + component['componentId']
            _require(target_id in targets and key not in expected and name not in names, 'bindings')
            expected[key] = digest({'target': targets[target_id], 'component': component})
            names.add(name)
    return expected


def _record(prepared, expected, record):
    _require(isinstance(record, dict) and set(record) == BINDING_FIELDS, 'record')
    key = (record['targetId'], record['componentId'])
    _require(all(isinstance(value, str) for value in key) and key in expected, 'binding')
    _require(record['stage'] == prepared.stage and record['policyDigest'] == digest(prepared.resolved)
             and record['bindingDigest'] == expected[key], 'stage-policy-binding')
    _require(isinstance(record['providerIdentity'], str) and bool(record['providerIdentity'])
             and len(record['providerIdentity']) <= 2048 and not any(ord(ch) <= 32 or ord(ch) == 127 for ch in record['providerIdentity'])
             and _digest(record['stateHandleDigest']), 'identity')
    _require(record['resourceClaims'] == _claims(record['resourceClaims']), 'canonical-claims')
    return key


def _complete(prepared, expected, records):
    _require(isinstance(records, list), 'records')
    seen = set()
    claims = []
    for record in records:
        key = _record(prepared, expected, record)
        _require(key not in seen, 'duplicate-binding')
        seen.add(key)
        for claim in record['resourceClaims']:
            _require(not any(claims_overlap(claim, old) for old in claims), 'claim-overlap')
            claims.append(claim)
    _require(seen == set(expected), 'incomplete')
    return sorted(copy.deepcopy(records), key=lambda record: (record['targetId'], record['componentId']))


def binding_marker(prepared, request, resolved, operation):
    """Serialize only the actual authorize() result's exact pending handle/claims."""
    expected = _context(prepared)
    _require(prepared._bound, 'unbound')
    plan = operation['plan']
    handle = plan['stateHandle']
    handle_digest = digest(handle)
    claims = _claims(resolved.get('resourceClaims'))
    _require(plan == operation['canonical'] and plan['operation'] == 'apply'
             and plan['stateHandleDigest'] == handle_digest
             and operation['store'] is prepared.store
             and operation['resourceClaims'] == claims
             and prepared._pending.get(handle_digest) == {'handle': handle, 'claims': claims}, 'pending-operation')
    _require(handle['targetId'] == request['target']['id']
             and handle['componentId'] == request['componentId']
             and handle['providerIdentity'] == resolved.get('providerIdentity'), 'pending-binding')
    key = (request['target']['id'], request['componentId'])
    _require(key in expected, 'binding')
    record = {'stage': copy.deepcopy(prepared.stage), 'policyDigest': digest(prepared.resolved),
              'targetId': key[0], 'componentId': key[1], 'bindingDigest': expected[key],
              'providerIdentity': resolved['providerIdentity'], 'resourceClaims': claims,
              'stateHandleDigest': handle_digest}
    _record(prepared, expected, record)
    return BINDING_MARKER + canonical_bytes(record).decode()


def _read(github, prepared, name, marker):
    host = prepared.current_host
    job = _job(github, host['runId'], host['runAttempt'], name)
    records = _records(github.repo('GET', '/actions/jobs/' + str(job['id']) + '/logs',
                                  raw=True, limit=MAX_LOG_BYTES), marker)
    _require(len(records) == 1, 'marker-count')
    return records[0]


def verify_preflight_barrier(prepared, github, *, emit=print):
    """Aggregate all successful exact workers before the first normal apply."""
    expected = _context(prepared)
    records = []
    for target_id, component_id in sorted(expected):
        record = _read(github, prepared, PREFIX + 'monorepo-preflight-' + target_id + '-' + component_id,
                       BINDING_MARKER)
        _require(isinstance(record, dict) and record.get('targetId') == target_id
                 and record.get('componentId') == component_id, 'worker-binding')
        records.append(record)
    records = _complete(prepared, expected, records)
    barrier = {'stage': copy.deepcopy(prepared.stage), 'policyDigest': digest(prepared.resolved),
               'bindingsDigest': digest(records), 'bindings': records}
    emit(BARRIER_MARKER + canonical_bytes(barrier).decode(), flush=True)
    return records


def require_preflight_barrier(prepared, github):
    """Independently re-fetch the successful current barrier before native apply.

    The caller must additionally re-resolve its provider claims and compare its
    freshly authorized Go handle digest to the returned binding immediately
    before IaC; this module neither authorizes mutation nor changes a store.
    """
    expected = _context(prepared)
    barrier = _read(github, prepared, PREFIX + 'monorepo-preflight-barrier', BARRIER_MARKER)
    _require(isinstance(barrier, dict) and set(barrier) == BARRIER_FIELDS, 'barrier-record')
    _require(barrier['stage'] == prepared.stage and barrier['policyDigest'] == digest(prepared.resolved),
             'barrier-stage-policy')
    records = _complete(prepared, expected, barrier['bindings'])
    _require(barrier['bindings'] == records and barrier['bindingsDigest'] == digest(records), 'barrier-digest')
    return records
