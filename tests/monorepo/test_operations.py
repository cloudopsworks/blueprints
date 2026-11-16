"""Data/ownership boundary tests; no cloud mutation or Terraform subprocess."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'cd/monorepo/runtime'))
from contracts import ContractError, digest
from operations import StateHandleStore, assert_confirmation, validate_operation

FIXTURES = Path(__file__).with_name('fixtures')/'operations'


class FakeGitHub:
    def __init__(self):
        self.records = []
        self.break_readback = False
    def pages(self, path):
        return copy.deepcopy(self.records)
    def repo(self, method, path, value=None):
        if method == 'POST':
            entry = {**copy.deepcopy(value), 'id':len(self.records)+1,'creator':{'id':42}}
            self.records.append(entry)
            return entry
        result = copy.deepcopy(next(x for x in self.records if str(x['id']) == path.rsplit('/',1)[1]))
        if self.break_readback:
            result['creator']['id'] = 999
        return result


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads((FIXTURES/'destroy-plan.json').read_text())
        self.handle = self.plan['stateHandle']

    def test_authoritative_backend_auth_structural_and_semantic_corpus(self):
        from contracts import _check
        schema=json.loads((ROOT/'cd/monorepo/runtime/schema/operations-v1.schema.json').read_text())
        cases=json.loads((FIXTURES/'backend-auth-cases.json').read_text())['cases']
        for case in cases:
            value=json.loads((FIXTURES/case['payload']).read_text())
            def check():
                if case['definition']=='StateHandle':validate_operation(value)
                else:_check(value,schema['$defs'][case['definition']],'$',document=schema)
            with self.subTest(case=case['id']):
                if case['expected']=='accept':check()
                else:
                    with self.assertRaises(ContractError):check()

    def test_authoritative_goldens_nullable_and_local_schema_refs(self):
        validate_operation(self.plan)
        for name in ('state-handle','state-develop','state-release','state-support','state-preview','state-qualified'):
            validate_operation(json.loads((FIXTURES/(name+'.json')).read_text()))
        self.assertEqual(digest(self.handle), self.plan['stateHandleDigest'])

    def test_closed_operation_schema_rejects_unknown_and_duplicate_auth_refs(self):
        for mutate in (lambda h:h.update(extra="forbidden"), lambda h:h.update(authRefs=["aws-dev","aws-dev"])):
            value=copy.deepcopy(self.handle);mutate(value)
            with self.assertRaises(ContractError):validate_operation(value)

    def test_forged_plan_and_recovery_owner_drift_rejected(self):
        for mutate in (lambda p:p.update(stateHandleDigest='sha256:'+'0'*64),
                       lambda p:p['invocation']['repository'].update(id='999'),
                       lambda p:p.update(inputs={}), lambda p:p.update(lockId='not-unlock')):
            value = copy.deepcopy(self.plan)
            mutate(value)
            with self.assertRaises(ContractError):
                validate_operation(value)
        value = copy.deepcopy(self.plan)
        value['stateHandle']['protectedEnvironment'] = 'release/prod'
        value['stateHandleDigest'] = digest(value['stateHandle'])
        with self.assertRaises(ContractError):
            validate_operation(value, canonical=self.plan)
        # New recovery invocation is allowed; frozen original owner is retained.
        value = copy.deepcopy(self.plan)
        value['invocation']['runId'] = '999'
        validate_operation(value)

    def test_exact_manual_scope_and_confirmation(self):
        h = self.handle
        args = dict(environment=h['protectedEnvironment'],target=h['targetId'],component=h['componentId'])
        assert_confirmation(self.plan, **args, confirmation=f"destroy {args['environment']}/{args['target']}/{args['component']}")
        for confirmation in ('', 'destroy all', 'destroy prod/dev-kube/api'):
            with self.assertRaises(ContractError):
                assert_confirmation(self.plan, **args, confirmation=confirmation)
        with self.assertRaises(ContractError):
            assert_confirmation(self.plan, **{**args,'component':''},confirmation='')

    def test_handle_is_read_back_and_reused_before_any_init(self):
        gh = FakeGitHub()
        store = StateHandleStore(gh,self.handle['origin']['repository'],42,verify_origin=lambda handle,entry:True)
        first = store.reserve(self.handle,['aws:123:cluster:example:namespace:example:release:api'])
        self.assertEqual(first['payload']['stateHandle'],self.handle)
        self.assertEqual(store.reserve(self.handle,first['payload']['resourceClaims']),first)
        self.assertEqual(len(gh.records),1)
        other = FakeGitHub(); other.break_readback = True
        with self.assertRaisesRegex(ContractError,'read-back'):
            StateHandleStore(other,self.handle['origin']['repository'],42,verify_origin=lambda handle,entry:True).reserve(self.handle,['aws:fixture'])

    def test_current_readback_observer_precedes_origin_enumeration_and_never_runs_on_partial_write(self):
        gh = FakeGitHub(); recorded = {}
        def origin(handle, entry):
            return entry is None or recorded.get(str(entry['id'])) == entry['payload']
        def observe(handle, entry):
            self.assertEqual(handle, self.handle)
            recorded[str(entry['id'])] = copy.deepcopy(entry['payload'])
            # A callback cannot alter the store's verified fresh record.
            entry['payload']['resourceClaims'].append('malicious:local-mutation')
        store = StateHandleStore(gh, self.handle['origin']['repository'], 42,
                                 verify_origin=origin, after_readback=observe)
        result = store.reserve(self.handle, ['aws:fixture'])
        self.assertEqual(result['payload']['resourceClaims'], ['aws:fixture'])
        self.assertEqual(len(recorded), 1)
        store.reserve(self.handle, ['aws:fixture'])
        self.assertEqual(len(recorded), 1)
        broken = FakeGitHub(); broken.break_readback = True
        with self.assertRaises(ContractError):
            StateHandleStore(broken, self.handle['origin']['repository'], 42,
                verify_origin=lambda *_: True,
                after_readback=lambda *_: self.fail('observer ran before verified GET')).reserve(self.handle, ['aws:fixture'])
        failed = FakeGitHub()
        def unavailable(*_):
            raise ContractError('state-marker-unavailable', 'host marker could not be emitted')
        with self.assertRaisesRegex(ContractError, 'host marker'):
            StateHandleStore(failed, self.handle['origin']['repository'], 42,
                verify_origin=lambda *_: True, after_readback=unavailable).reserve(self.handle, ['aws:fixture'])
        self.assertEqual(len(failed.records), 1)  # Ownership is not erased on failure.

    def test_cross_category_state_and_static_prefix_collisions(self):
        gh = FakeGitHub();store = StateHandleStore(gh,self.handle['origin']['repository'],42,verify_origin=lambda handle,entry:True)
        store.reserve(self.handle,['prefix:arn:aws:s3:::fixture/site/'])
        changed = copy.deepcopy(self.handle)
        changed['backend']['key'] = changed['backend']['key'].replace('develop/dev','release/prod')
        changed['native']['stateAddress'] += '-another'
        changed['protectedEnvironment'] = 'release/prod'
        with self.assertRaises(ContractError):
            store.reserve(changed,['prefix:arn:aws:s3:::fixture/site/sub/'])
        store.reserve(changed,['prefix:arn:aws:s3:::fixture/sibling/'])
        drift = copy.deepcopy(self.handle);drift['providerIdentity'] = '999'
        with self.assertRaises(ContractError):
            store.reserve(drift,['prefix:arn:aws:s3:::fixture/site/'])

    def test_actor_alone_and_malformed_trusted_envelope_fail_closed(self):
        gh=FakeGitHub()
        for verifier in (None, lambda handle,entry:False):
            with self.assertRaisesRegex(ContractError,'origin|verifier'):
                StateHandleStore(gh,self.handle['origin']['repository'],42,verify_origin=verifier).reserve(self.handle,['aws:fixture'])
        self.assertEqual(gh.records,[])
        store=StateHandleStore(gh,self.handle['origin']['repository'],42,verify_origin=lambda handle,entry:True)
        store.reserve(self.handle,['aws:fixture'])
        gh.records[0]['payload']['unexpected']='untrusted'
        with self.assertRaises(ContractError):store.entries()

    def test_generated_rest_id_monotonic_alias_and_ambiguous_survivor_denied(self):
        handle=copy.deepcopy(self.handle)
        handle['moduleId']='aws-apigateway-rest'
        handle['ownership']='managed'
        handle['resourceIdentity']={'provider':'aws','kind':'aws.apigateway-rest','region':'us-east-1',
            'stage':'prod','ownership':'managed','apiName':'component-api','apiVersion':'v1'}
        validate_operation(handle)
        gh=FakeGitHub();store=StateHandleStore(gh,handle['origin']['repository'],42,verify_origin=lambda h,e:True)
        name='aws:123456789012:us-east-1:rest-api:new-name:component-api'
        original=store.reserve(handle,[name])
        for verifier in (None,lambda h,i:False):
            with self.assertRaises(ContractError):store.bind_created_rest_api(handle,'generated123',verify_creation=verifier)
        self.assertEqual(len(gh.records),1) # surviving cloud name/tag alone cannot adopt
        bound=store.bind_created_rest_api(handle,'generated123',verify_creation=lambda h,i:True)
        self.assertEqual(bound['payload']['stateHandle'],original['payload']['stateHandle'])
        self.assertEqual(bound['payload']['stateHandleDigest'],original['payload']['stateHandleDigest'])
        self.assertIn(name,bound['payload']['resourceClaims'])
        alias='arn:aws:apigateway:us-east-1:'+handle['providerIdentity']+':/restapis/generated123'
        self.assertIn(alias,bound['payload']['resourceClaims'])
        self.assertEqual(store.reserve(handle,[name]),bound)
        self.assertEqual(store.bind_created_rest_api(handle,'generated123',verify_creation=lambda h,i:True),bound)
        self.assertEqual(len(gh.records),2)
        with self.assertRaises(ContractError):store.bind_created_rest_api(handle,'foreign456',verify_creation=lambda h,i:True)
        other=copy.deepcopy(handle);other['native']['stateAddress']+='-other'
        with self.assertRaises(ContractError):store.reserve(other,[alias])

    def test_spoofed_actor_is_not_trusted_ownership(self):
        gh=FakeGitHub();store=StateHandleStore(gh,self.handle['origin']['repository'],42,verify_origin=lambda handle,entry:True)
        store.reserve(self.handle,['aws:fixture'])
        gh.records[0]['creator']['id']=999
        self.assertEqual(store.entries(),[])


if __name__ == '__main__': unittest.main()
