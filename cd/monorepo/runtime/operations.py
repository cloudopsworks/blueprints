"""Closed operation/state contract boundary, never a source configuration parser.

Only independently generated canonical plans may cross this boundary. A valid
JSON object, self-declared actor or artifact hash is not execution authority.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import re
from urllib.parse import quote

from contracts import ContractError, _check, canonical_bytes, claims_overlap, digest

SCHEMA = Path(__file__).with_name('schema') / 'operations-v1.schema.json'


def validate_operation(value, *, canonical=None):
    document = json.loads(SCHEMA.read_text())
    kind = value.get('kind') if isinstance(value, dict) else None
    if kind not in ('OperationPlan', 'StateHandle'):
        raise ContractError('operation-kind', 'unsupported operation record')
    _check(value, document['$defs'][kind], '$', document=document)
    if kind == 'OperationPlan':
        handle = value['stateHandle']
        if value['stateHandleDigest'] != digest(handle):
            raise ContractError('operation-handle-digest', 'operation handle binding disagrees')
        if value['invocation']['repository'] != handle['origin']['repository']:
            raise ContractError('operation-repository', 'operation recovery crosses repository identity')
        needs_inputs = value['operation'] in ('apply', 'preview')
        if needs_inputs != (value['inputs'] is not None):
            raise ContractError('operation-inputs', 'operation input presence disagrees')
        if value['operation'] == 'unlock' and not value['lockId']:
            raise ContractError('operation-lock', 'unlock requires exact native lock identity')
        if value['operation'] != 'unlock' and value['lockId'] is not None:
            raise ContractError('operation-lock', 'lock identity is only valid for unlock')
        if needs_inputs and value['inputs']['resource'] != handle['resourceIdentity']:
            raise ContractError('operation-resource', 'operation resource differs from frozen owner')
    handle=value['stateHandle'] if kind=='OperationPlan' else value
    expected_provider={'s3':'aws','gcs':'gcp','azurerm':'azure'}[handle['backend']['kind']]
    refs=handle['authRefs'];workload_provider=handle['resourceIdentity']['provider']
    if 'backendIdentity' in handle:
        identity=handle['backendIdentity']
        backend_canonical=identity.get({'aws':'accountId','gcp':'projectNumber','azure':'subscriptionId'}[identity['provider']])
        if (identity['provider']!=expected_provider or handle['backend']['authRef'] not in refs
            or refs!=sorted(set(refs)) or len(refs)>2
            or (len(refs)==1 and (expected_provider!=workload_provider or backend_canonical!=handle['providerIdentity']))):
            raise ContractError('operation-backend-auth','backend identity or selected reference membership disagrees')
    elif (expected_provider!=workload_provider or len(refs)!=1
          or (expected_provider=='azure' and any(handle['backend'][key]!=refs[0]
              for key in ('tenantIdRef','subscriptionIdRef','clientIdRef')))):
        raise ContractError('operation-backend-legacy','legacy backend requires its exact workload principal')
    if canonical is not None and canonical_bytes(value) != canonical_bytes(canonical):
        raise ContractError('operation-canonical', 'operation differs from independently regenerated canonical data')
    return value


def assert_confirmation(plan, *, environment, target, component, confirmation):
    """Protected environment selector is exact, never split/defaulted to prod."""
    validate_operation(plan)
    handle = plan['stateHandle']
    if not component or (environment, target, component) != (
            handle['protectedEnvironment'], handle['targetId'], handle['componentId']):
        raise ContractError('operation-scope', 'manual operation scope is not exact')
    operation = plan['operation']
    if operation in ('destroy', 'unlock'):
        expected = f'{operation} {environment}/{target}/{component}'
        if operation == 'unlock':
            expected += ' ' + plan['lockId']
        if confirmation != expected:
            raise ContractError('operation-confirmation', 'destructive confirmation does not match exact scope')


def _claims(values):
    if (not isinstance(values, list) or not values or len(values) > 256
            or any(not isinstance(v, str) or len(v) > 2048 or not v
                   or re.search(r'[\x00-\x20\x7f?#]', v) for v in values)
            or len(set(values)) != len(values)):
        raise ContractError('state-claims', 'resolved physical claims are invalid')
    return sorted(values)


class StateHandleStore:
    """Actor-protected durable handle reservation, read back before backend INIT.

    Claims come from the global read-only provider resolver, not operation JSON.
    Failed/in-progress attempts still reserve ownership; inactive records are not
    released here. Only a verified successful destroy may release ownership in a
    future lifecycle integration. Recovery can always retrieve the frozen handle.
    """
    def __init__(self, github, repository, automation_id, *, verify_origin=None, after_readback=None):
        if not re.fullmatch(r'[1-9][0-9]*', str(automation_id)):
            raise ContractError('state-actor', 'state store requires trusted numeric automation identity')
        self.github, self.repository, self.actor = github, repository, str(automation_id)
        self.verify_origin = verify_origin
        if after_readback is not None and not callable(after_readback):
            raise ContractError('state-readback-hook', 'state read-back observer must be trusted callable code')
        self.after_readback = after_readback

    def _origin(self, handle, deployment):
        # Host verification must also regenerate the COMPLETE canonical handle
        # and canonical resolved claims; checking a self-declared run ID or actor
        # is not sufficient. This callback is trusted code, never a wire field.
        if self.verify_origin is None or self.verify_origin(handle, deployment) is not True:
            raise ContractError('state-host-unverified', 'state handle lacks independently verified host and canonical origin')

    def entries(self):
        if self.verify_origin is None:
            raise ContractError('state-host-unverified', 'state store has no independent host verifier')
        found = []
        for entry in self.github.pages('/deployments?task=cloudopsworks-state'):
            if str(entry.get('creator', {}).get('id')) != self.actor:
                continue
            payload = entry.get('payload')
            if entry.get('task') != 'cloudopsworks-state':
                continue
            if (not isinstance(payload, dict) or set(payload) != {'apiVersion','kind','stateHandle','stateHandleDigest','resourceClaims'}
                    or payload.get('apiVersion') != 'cloudopsworks.io/operations/v1'
                    or payload.get('kind') != 'StateHandleReservation'):
                raise ContractError('state-store-corrupt', 'trusted state reservation has an unsupported envelope')
            handle = validate_operation(payload['stateHandle'])
            if handle['origin']['repository'] != self.repository:
                raise ContractError('state-store-corrupt', 'trusted state reservation repository identity disagrees')
            self._origin(handle, entry)
            if payload['stateHandleDigest'] != digest(handle):
                raise ContractError('state-store-corrupt', 'trusted stored handle has inconsistent digest')
            _claims(payload['resourceClaims'])
            if entry.get('environment') != self.environment(handle):
                raise ContractError('state-store-corrupt', 'trusted stored handle has inconsistent environment')
            found.append(entry)
        return found

    @staticmethod
    def environment(handle):
        return 'cloudopsworks-state/' + digest(handle['native'])[7:]

    def reserve(self, handle, resource_claims):
        validate_operation(handle)
        if handle['origin']['repository'] != self.repository:
            raise ContractError('state-repository', 'state store repository identity disagrees')
        self._origin(handle, None)
        claims = _claims(resource_claims)
        owned=[]
        for entry in self.entries():
            payload=entry['payload'];previous=payload['stateHandle']
            if previous['native']==handle['native']:
                if previous!=handle:
                    raise ContractError('state-owner-drift','native state is already reserved by another frozen owner')
                owned.append(entry)
            elif any(claims_overlap(a,b) for a in claims for b in payload['resourceClaims']):
                raise ContractError('state-ownership-collision','another state owns an overlapping physical workload')
        if owned:
            latest=max(owned,key=lambda e:len(e['payload']['resourceClaims']))
            known=set(latest['payload']['resourceClaims'])
            if not set(claims)<=known or any(not set(e['payload']['resourceClaims'])<=known for e in owned):
                raise ContractError('state-owner-drift','physical claims cannot change without verified generated identity binding')
            # Check ALL aliases before returning; do not stop at the first same
            # backend and overlook a later conflicting state reservation.
            for entry in self.entries():
                if entry['payload']['stateHandle']['native']!=handle['native'] and any(
                        claims_overlap(a,b) for a in known for b in entry['payload']['resourceClaims']):
                    raise ContractError('state-ownership-collision','generated physical identity is already owned')
            return latest
        return self._persist(handle,claims)

    def bind_created_rest_api(self,handle,api_id,*,verify_creation):
        """Append a generated ID alias, never change the frozen name owner.

        Trusted verify_creation must compare exact private native state ID,
        provider GET name/owner, and independently verified actual creation host.
        Name/tag existence alone is NOT authorization. Failure leaves the original
        reservation for exact owned-state recovery, never implicit adoption.
        """
        validate_operation(handle)
        resource=handle['resourceIdentity']
        if (handle['moduleId']!='aws-apigateway-rest' or resource.get('kind')!='aws.apigateway-rest'
                or resource.get('ownership')!='managed' or resource.get('restApiId')
                or not resource.get('apiName') or not resource.get('apiVersion')
                or not isinstance(api_id,str) or not re.fullmatch(r'[a-z0-9]{1,64}',api_id)):
            raise ContractError('state-generated-id','generated API identity is not a fresh managed REST owner')
        owned=[e for e in self.entries() if e['payload']['stateHandle']==handle]
        if not owned:
            raise ContractError('state-generated-id','initial immutable state reservation is missing')
        if not callable(verify_creation) or verify_creation(handle,api_id) is not True:
            raise ContractError('state-generated-id','generated identity lacks independent native-state and host creation proof')
        current=max(owned,key=lambda e:len(e['payload']['resourceClaims']))
        alias='arn:aws:apigateway:'+resource['region']+':'+handle['providerIdentity']+':/restapis/'+api_id
        claims=_claims(sorted(set(current['payload']['resourceClaims'])|{alias}))
        for entry in self.entries():
            if entry['payload']['stateHandle']['native']!=handle['native'] and any(
                    claims_overlap(a,b) for a in claims for b in entry['payload']['resourceClaims']):
                raise ContractError('state-ownership-collision','generated API identity is already owned')
        if alias in current['payload']['resourceClaims']:return self.reserve(handle,claims)
        # No different generated ID may be silently appended on ambiguous retry.
        if any(c.startswith('arn:aws:apigateway:') for c in current['payload']['resourceClaims']):
            raise ContractError('state-generated-id','another generated API ID is already frozen for this owner')
        self._origin(handle,None)
        return self._persist(handle,claims)

    def _persist(self,handle,claims):
        payload = {'apiVersion':'cloudopsworks.io/operations/v1','kind':'StateHandleReservation',
                   'stateHandle':copy.deepcopy(handle),'stateHandleDigest':digest(handle),'resourceClaims':claims}
        entry = self.github.repo('POST', '/deployments', {'ref':handle['origin']['sourceSha'],
            'task':'cloudopsworks-state', 'environment':self.environment(handle),
            'auto_merge':False,'required_contexts':[], 'production_environment':False,
            'transient_environment':False, 'payload':payload,
            'description':'CloudOpsWorks frozen component state handle'})
        identity = str(entry.get('id', '')) if isinstance(entry, dict) else ''
        if not re.fullmatch(r'[1-9][0-9]*', identity):
            raise ContractError('state-store-write', 'state handle reservation did not return durable identity')
        fresh = self.github.repo('GET', '/deployments/' + quote(identity, safe=''))
        if (not fresh or fresh.get('payload') != payload or fresh.get('task') != 'cloudopsworks-state'
                or fresh.get('environment') != self.environment(handle)
                or str(fresh.get('creator', {}).get('id')) != self.actor):
            raise ContractError('state-store-readback', 'state handle durable read-back failed before INIT')
        # The trusted current-process observer may emit a host-bound marker only
        # AFTER exact durable read-back. It cannot bless any other reservation.
        # Observer failure retains the reservation and prevents backend INIT.
        if self.after_readback is not None:
            self.after_readback(copy.deepcopy(handle), copy.deepcopy(fresh))
        # Re-enumerate global ownership after persistence; never initialize a
        # backend after a concurrent conflicting reservation becomes visible.
        for other in self.entries():
            if str(other['id']) != identity and other['payload']['stateHandle']['native'] != handle['native']:
                if any(claims_overlap(a,b) for a in claims for b in other['payload']['resourceClaims']):
                    raise ContractError('state-ownership-collision', 'concurrent physical ownership conflict')
        return fresh
