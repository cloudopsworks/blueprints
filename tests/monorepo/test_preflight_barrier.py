"""Complete-set barrier tests with actual helpers and read-only GitHub doubles.

The focused corpus records trusted pending contexts; the separately enabled
integration case uses the real Go authorizer and API snapshot fixtures.
"""
import copy
import json
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'cd/monorepo/runtime'))
import authorization as auth
import preflight_barrier as barrier
from contracts import ContractError, canonical_bytes, digest


class GitHub:
    def __init__(self, attempt=2):
        self.attempt = attempt
        self.jobs = []; self.logs = {}; self.reads = []
    def add(self, name, line):
        job = {'id': len(self.jobs)+1, 'name': name, 'run_id': 200, 'run_attempt': self.attempt,
               'status': 'completed', 'conclusion': 'success'}
        self.jobs.append(job); self.logs[job['id']] = (line+'\n').encode()
    def repo(self, method, path, **kwargs):
        self.reads.append((method,path,kwargs))
        if path == '/actions/runs/200/attempts/'+str(self.attempt)+'/jobs?per_page=100&page=1':
            return {'jobs': copy.deepcopy(self.jobs)}
        if path.startswith('/actions/jobs/') and path.endswith('/logs'):
            assert kwargs == {'raw': True, 'limit': 8*1024*1024}
            return self.logs[int(path.split('/')[3])]
        raise AssertionError(path)


class PreflightBarrierTests(unittest.TestCase):
    def setUp(self):
        self.gh = GitHub()
        repository = {'id':'123','fullName':'example/app'}
        stage = {'runId':'100','runAttempt':'1','artifactId':'500','archiveDigest':'sha256:'+'f'*64}
        self.manifest = {'targets':[{'id':'dev','authRef':'cloud'}],
                         'components':[{'componentId':name,'targetIds':['dev'],'mainArtifact':{'digest':name}}
                                       for name in ('api','worker')]}
        host = {'runId':'200','runAttempt':'2','workflowRef':'example/app/.github/workflows/main-build.yml@refs/heads/develop'}
        self.prepared = auth.PreparedAuthorization(self.gh,None,None,repository,stage,
            {'callerPath':'.github/workflows/main-build.yml'},host,{}, {},self.manifest,
            {'policy':{'protected':True}}, {}, [], False)
        self.prepared._bound=True; self.prepared.store=object()
        self.lines=[]
        for component in self.manifest['components']:
            request,resolved,operation = self.operation(component['componentId'])
            line=barrier.binding_marker(self.prepared,request,resolved,operation)
            self.lines.append(line)
            self.gh.add('lifecycle / monorepo-preflight-dev-'+component['componentId'],line)
    def operation(self, component, claims=None):
        claims=claims or ['object:cloud/'+component]
        handle={'targetId':'dev','componentId':component,'providerIdentity':'123456789012'}
        plan={'operation':'apply','stateHandle':handle,'stateHandleDigest':digest(handle)}
        self.prepared._pending[digest(handle)]={'handle':copy.deepcopy(handle),'claims':sorted(claims)}
        request={'target':{'id':'dev'},'componentId':component}
        resolved={'providerIdentity':'123456789012','resourceClaims':claims}
        return request,resolved,{'plan':plan,'canonical':copy.deepcopy(plan),'store':self.prepared.store,'resourceClaims':sorted(claims)}
    def aggregate(self):
        emitted=[]
        records=barrier.verify_preflight_barrier(self.prepared,self.gh,emit=lambda line,**kw:emitted.append(line))
        return records,emitted[0]
    def mutate(self, index, change):
        value=json.loads(self.gh.logs[index].decode().split(' ',1)[1]);change(value)
        self.gh.logs[index]=(barrier.BINDING_MARKER+json.dumps(value)).encode()
    def test_actual_marker_aggregation_and_separate_apply_refetch(self):
        records,line=self.aggregate()
        self.assertEqual([row['componentId'] for row in records],['api','worker'])
        self.assertEqual(set(records[0]),barrier.BINDING_FIELDS)
        self.gh.add('lifecycle / monorepo-preflight-barrier',line)
        self.gh.reads=[]
        self.assertEqual(barrier.require_preflight_barrier(self.prepared,self.gh),records)
        self.assertIn('/actions/jobs/3/logs',[path for _,path,_ in self.gh.reads])
        self.assertTrue(all(method=='GET' for method,_,_ in self.gh.reads))
        self.assertEqual(len(self.prepared._pending),2)
    def test_missing_duplicate_nested_wrong_attempt_and_failed_jobs(self):
        original=copy.deepcopy(self.gh.jobs)
        for change in (lambda jobs:jobs.pop(), lambda jobs:jobs.append(copy.deepcopy(jobs[0])),
                       lambda jobs:jobs[0].update(name='outer / '+jobs[0]['name']),
                       lambda jobs:jobs[0].update(run_attempt=1),lambda jobs:jobs[0].update(run_id=100),
                       lambda jobs:jobs[0].update(conclusion='failure')):
            self.gh.jobs=copy.deepcopy(original);change(self.gh.jobs)
            with self.subTest(change=change),self.assertRaises(ContractError):self.aggregate()
    def test_marker_duplicates_bounds_and_closed_shape(self):
        original=self.gh.logs[1]
        for data in (original+original,b'x'*(8*1024*1024+1),b'\xff',b'no evidence'):
            self.gh.logs[1]=data
            with self.assertRaises(ContractError):self.aggregate()
        self.gh.logs[1]=original;self.mutate(1,lambda value:value.update(extra=True))
        with self.assertRaises(ContractError):self.aggregate()
    def test_stage_policy_binding_identity_and_worker_forgery(self):
        original=self.gh.logs[1]
        for field,value in [('stage',dict(self.prepared.stage,runAttempt='9')),('policyDigest','sha256:'+'0'*64),
                            ('bindingDigest','sha256:'+'0'*64),('componentId','worker'),
                            ('stateHandleDigest','fake'),('providerIdentity',''),('resourceClaims',[])]:
            self.gh.logs[1]=original;self.mutate(1,lambda record,f=field,v=value:record.update({f:v}))
            with self.subTest(field=field),self.assertRaises(ContractError):self.aggregate()
    def test_manifest_source_or_policy_drift_invalidates_evidence(self):
        for container in (self.prepared.resolved,self.manifest['components'][0],self.manifest['targets'][0]):
            container['drift']=True
            with self.assertRaises(ContractError):self.aggregate()
            del container['drift']
    def test_global_alias_prefix_object_and_canonical_claim_checks(self):
        for first,second in [(['same'],['same']),(['prefix:cloud/site/'],['object:cloud/site/index.html']),
                             (['prefix:cloud/site/'],['prefix:cloud/site/sub/']),(['object:cloud/api'],['object:cloud/api'])]:
            self.mutate(1,lambda value:value.update(resourceClaims=first))
            self.mutate(2,lambda value:value.update(resourceClaims=second))
            with self.subTest(first=first,second=second),self.assertRaises(ContractError):self.aggregate()
        for claims in (['z','a'],['a','a'],['bad claim'],[]):
            self.mutate(1,lambda value:value.update(resourceClaims=claims))
            with self.assertRaises(ContractError):self.aggregate()
    def test_binding_marker_requires_actual_pending_operation(self):
        r,resolved,op=self.operation('api')
        for change in (lambda:self.prepared._pending.clear(),lambda:op.update(resourceClaims=['foreign']),
                       lambda:op.update(store=object()),lambda:op['plan'].update(operation='destroy'),
                       lambda:resolved.update(providerIdentity='other')):
            r,resolved,op=self.operation('api');change()
            with self.assertRaises(ContractError):barrier.binding_marker(self.prepared,r,resolved,op)
        r,resolved,op=self.operation('api');self.prepared._pending[digest(op['plan']['stateHandle'])]['claims']=['foreign']
        with self.assertRaises(ContractError):barrier.binding_marker(self.prepared,r,resolved,op)
    def test_inspection_unprepared_manual_and_preview_contexts_fail_closed(self):
        with self.assertRaises(ContractError):barrier.verify_preflight_barrier(object(),self.gh)
        self.prepared._inspection=True
        with self.assertRaises(ContractError):self.aggregate()
        self.prepared._inspection=False
        for caller in ('deploy.yml','pr-build.yml','pr-close.yaml','environment-destroy.yml'):
            self.prepared.current_host['workflowRef']='example/app/.github/workflows/'+caller+'@refs/heads/develop'
            with self.subTest(caller=caller),self.assertRaises(ContractError):self.aggregate()
    def test_apply_barrier_rejects_missing_or_forged_complete_set(self):
        records,line=self.aggregate();self.gh.add('lifecycle / monorepo-preflight-barrier',line)
        original=json.loads(line[len(barrier.BARRIER_MARKER):])
        for change in (lambda v:v['bindings'].pop(),lambda v:v['bindings'].append(v['bindings'][0]),
                       lambda v:v.update(bindingsDigest='sha256:'+'0'*64),lambda v:v.update(extra=True),
                       lambda v:v.update(policyDigest='sha256:'+'0'*64)):
            value=copy.deepcopy(original);change(value)
            # Even recomputing digest cannot grant an incomplete/duplicated set.
            if value['bindings']!=original['bindings']:value['bindingsDigest']=digest(value['bindings'])
            self.gh.logs[3]=(barrier.BARRIER_MARKER+canonical_bytes(value).decode()).encode()
            with self.assertRaises(ContractError):barrier.require_preflight_barrier(self.prepared,self.gh)
        self.gh.jobs.pop()
        with self.assertRaises(ContractError):barrier.require_preflight_barrier(self.prepared,self.gh)


@unittest.skipUnless(os.environ.get('TRONADOR_TEST_BINARY'),'set TRONADOR_TEST_BINARY to reviewed Go binary')
class ActualGoPendingTests(unittest.TestCase):
    def test_actual_api_snapshot_go_authorize_pending_marker(self):
        from test_authorization import RecoveryAPI, Process, captured, FIXTURES
        from iac import IaCExecutor
        from deploy import request_for, effective_digest
        api=RecoveryAPI()
        engine=IaCExecutor(ROOT,json.loads((ROOT/'terraform/monorepo/module-catalog.json').read_text()))
        prepared=auth.prepare_verified_context(api,api.run,blueprint_sha=api.bp,executor=Process(),engine=engine,current_host=api.host)
        settings={'auth':'gcp-dev:\n  provider: gcp\n  project: example-dev\n  serviceAccount: api@example-dev.iam.gserviceaccount.com\n  workloadIdentityProvider: projects/123/locations/global/workloadIdentityPools/pool/providers/provider\naws-state:\n  provider: aws\n  roleArn: arn:aws:iam::222222222222:role/state\n  region: us-east-1\n',
                  'identities':'gcp-dev: "123456789012"\naws-state: "222222222222"\n','registries':'{}','probe-secrets':'{}','host-keys':'{}'}
        backend=(FIXTURES/'backend-native-s3.yaml').read_text()+'  auth_ref: aws-state\n'
        pair={'workload':captured('gcp','123456789012','api'),'backend':captured('aws','222222222222','state')}
        pair['workload']['binding']['workloadIdentityProvider']='projects/123/locations/global/workloadIdentityPools/pool/providers/provider'
        prepared.select_bindings('dev-run','api',backend,settings,automation_id=42)
        prepared.bind(backend,settings,pair,automation_id=42)
        component=next(c for c in prepared.manifest['components'] if c['componentId']=='api')
        target=next(t for t in prepared.manifest['targets'] if t['id']=='dev-run')
        request=request_for(prepared.manifest,component,target)
        resolved={'providerIdentity':'123456789012','resourceClaims':['gcp:123456789012:run:api'],
                  'existing':{'providerIdentity':'123456789012','exists':False,'ownerDigest':None}}
        request['target']['configDigest']=effective_digest(target,component['workload'],resolved)
        request['idempotencyKey']=digest({'repositoryId':prepared.repository['id'],'targetId':'dev-run',
            'componentId':'api','artifactDigest':request['artifact']['digest'],'targetConfigDigest':request['target']['configDigest']})
        operation=prepared.authorize(request,resolved)
        line=barrier.binding_marker(prepared,request,resolved,operation)
        record=json.loads(line[len(barrier.BINDING_MARKER):])
        self.assertEqual(record['stateHandleDigest'],digest(operation['plan']['stateHandle']))
        self.assertEqual(api.records,[],'preflight must not reserve or write state')
        gh=GitHub(attempt=int(prepared.current_host['runAttempt']));gh.add('lifecycle / monorepo-preflight-dev-run-api',line)
        emitted=[]
        records=barrier.verify_preflight_barrier(prepared,gh,emit=lambda line,**kw:emitted.append(line))
        gh.add('lifecycle / monorepo-preflight-barrier',emitted[0])
        self.assertEqual(barrier.require_preflight_barrier(prepared,gh),records)


if __name__=='__main__':unittest.main()
