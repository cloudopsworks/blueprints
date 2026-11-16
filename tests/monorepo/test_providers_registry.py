"""Offline registry transport, credential boundary and immutable identity tests."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_providers import request, Fake, common, ROOT, gcp, aws
from providers import registry

DIGEST='sha256:'+'b'*64
SOURCE='ghcr.io/owner/repo/api@'+DIGEST
ECR='123456789012.dkr.ecr.us-east-1.amazonaws.com/app'

class RegistryFake(Fake):
    def __init__(self,r,*,wrong=None):
        super().__init__(r); self.wrong=wrong; self.authfiles=[]
    def run(self,a,**kw):
        if '--authfile' in a:
            path=Path(a[a.index('--authfile')+1]);self.authfiles.append(path)
            assert path.stat().st_mode & 0o777 == 0o600
        if a[:3]==['gcloud','auth','print-access-token']:
            self.calls.append((a,kw));return subprocess.CompletedProcess(a,0,'native-token','')
        if self.wrong=='private' and a[:2]==['skopeo','inspect'] and '--no-creds' in a:
            self.calls.append((a,kw));return subprocess.CompletedProcess(a,1,'','unauthorized')
        if a[:3]==['gcloud','app','deploy']:
            self.app_config=json.loads(Path(a[3]).read_text())
        return super().run(a,**kw)
    def response(self,a):
        value=super().response(a)
        if a[:4]==['gcloud','artifacts','repositories','describe']:
            value={'name':'projects/project/locations/us/repositories/images','format':'DOCKER','mode':'STANDARD_REPOSITORY'}
        if a[:4]==['gcloud','app','versions','describe']:
            value.update(env='flex',deployment={'container':{'image':'us-docker.pkg.dev/project/images/api@'+DIGEST}})
        if a[:3]==['az','acr','show']:
            value={'id':'/subscriptions/sub/resourceGroups/rg/providers/Microsoft.ContainerRegistry/registries/native','loginServer':'native.azurecr.io'}
        if a[:3]==['az','acr','login']:
            value={'loginServer':'native.azurecr.io','accessToken':'native-token'}
        if self.wrong=='account' and a[:3]==['aws','ecr','describe-repositories']:value['repositories'][0]['registryId']='999999999999'
        if self.wrong=='index' and '--raw' in a:value={'mediaType':'application/vnd.oci.image.index.v1+json','manifests':[]}
        if self.wrong=='destination' and a[:2]==['skopeo','inspect'] and ':sha256-' in a[-1]:value='sha256:'+'a'*64
        if self.wrong=='native-digest' and a[:3]==['aws','ecr','describe-images']:value['imageDetails'][0]['imageDigest']='sha256:'+'a'*64
        return value

class RegistryTests(unittest.TestCase):
    def fixture(self,kind):
        r=request(kind);r['artifact'].update(format='oci',kind='container',digest=DIGEST,location={'kind':'oci','reference':SOURCE})
        return r
    def test_lambda_existing_ecr_promotion_stdin_and_cleanup(self):
        r=self.fixture('aws.lambda');ex=RegistryFake(r)
        with tempfile.TemporaryDirectory() as root:
            ctx={'workDir':root,'expectedIdentity':'123456789012','registrySourceToken':'source-secret','registrySourceUser':'actor'}
            resource={'Code':{'ResolvedImageUri':ECR+'@sha256:'+'a'*64}}
            image=registry.materialize(r,ex,ctx,SOURCE,lambda_resource=resource)
            self.assertEqual(image,ECR+'@'+DIGEST)
            self.assertEqual(r['artifact']['location']['reference'],SOURCE)
            self.assertEqual(list(Path(root).iterdir()),[])
        logins=[(a,k) for a,k in ex.calls if a[:2]==['skopeo','login']]
        self.assertEqual([k['input'] for a,k in logins],['source-secret','native-token'])
        for a,k in ex.calls:
            self.assertNotIn('source-secret',' '.join(a));self.assertNotIn('native-token',' '.join(a))
        copies=[a for a,k in ex.calls if a[:2]==['skopeo','copy']]
        self.assertEqual(len(copies),1)
        self.assertIn('--all',copies[0]);self.assertIn('--preserve-digests',copies[0])
        self.assertEqual(copies[0][-2:],['docker://'+SOURCE,'docker://'+ECR+':sha256-'+'b'*64])
        self.assertTrue(all(not p.exists() for p in ex.authfiles))
    def test_fresh_managed_lambda_uses_only_protected_existing_ecr(self):
        r=self.fixture('aws.lambda');r['target']['ownership']='managed'
        mapping={r['target']['authRef']:{'provider':'aws','repository':ECR}}
        ex=RegistryFake(r)
        resolution={'providerIdentity':'123456789012','resource':{},'existing':{'exists':False}}
        bound=registry.bind_resolution(r,resolution,ex,mapping)
        self.assertEqual(bound['registryConfig']['destination']['repository'],ECR)
        registry.assert_mapping(r,bound,mapping)
        with tempfile.TemporaryDirectory() as root:
            ctx={'workDir':root,'expectedIdentity':'123456789012','registries':mapping}
            self.assertEqual(registry.materialize(r,ex,ctx,SOURCE,lambda_resource={}),ECR+'@'+DIGEST)
        for changes in ({'ownership':'external'},):
            bad=copy.deepcopy(r);bad['target'].update(changes)
            with self.assertRaises(Exception):registry.bind_resolution(bad,resolution,ex,mapping)
        for badmap in ({},{r['target']['authRef']:{'provider':'gcp','repository':ECR}}):
            with self.assertRaises(Exception):registry.bind_resolution(r,resolution,ex,badmap)

    def test_lambda_wrong_identity_format_and_digest_fail_closed(self):
        for wrong in ('account','index','destination','native-digest'):
            with self.subTest(wrong=wrong), tempfile.TemporaryDirectory() as root:
                r=self.fixture('aws.lambda');ex=RegistryFake(r,wrong=wrong)
                with self.assertRaises(Exception):registry.materialize(r,ex,{'workDir':root,'expectedIdentity':'123456789012'},SOURCE,lambda_resource={'Code':{'ResolvedImageUri':ECR+'@'+DIGEST}})
                self.assertFalse(any(a[:3]==['aws','lambda','update-function-code'] for a,k in ex.calls))
                if wrong in ('account','index'):self.assertFalse(any(a[:2]==['skopeo','copy'] for a,k in ex.calls))
                if wrong=='account':self.assertFalse(any(a[:2]==['skopeo','login'] for a,k in ex.calls))
    def test_lambda_adapter_failure_never_mutates_function_or_succeeds(self):
        for wrong in (None,'destination'):
            with self.subTest(wrong=wrong),tempfile.TemporaryDirectory() as root:
                r=self.fixture('aws.lambda');r['artifact']['kind']='function'
                r['target']['packageMode']='image';r['package']['mode']='aws-image'
                ex=RegistryFake(r,wrong=wrong)
                result=aws.deploy(r,ex,context={'workDir':root})
                self.assertEqual(result['artifactDigest'],DIGEST)
                self.assertEqual(result['status'],'failed',result)
                self.assertEqual(result['error']['code'],'iac-authorization-required')
                self.assertEqual(ex.calls,[])
                if wrong:
                    self.assertFalse(any(a[:3] in (['aws','lambda','invoke'],['aws','lambda','update-function-code']) for a,k in ex.calls))
    def test_retries_use_same_content_tag_and_digest(self):
        r=self.fixture('aws.lambda');ex=RegistryFake(r)
        with tempfile.TemporaryDirectory() as root:
            ctx={'workDir':root,'expectedIdentity':'123456789012'}
            resource={'Code':{'ResolvedImageUri':ECR+'@'+DIGEST}}
            for _ in range(2):self.assertEqual(registry.materialize(r,ex,ctx,SOURCE,lambda_resource=resource),ECR+'@'+DIGEST)
        copies=[a[-1] for a,k in ex.calls if a[:2]==['skopeo','copy']]
        self.assertEqual(copies,[copies[0]]*2)
    def test_lambda_region_and_account_rejected_before_credentials(self):
        for repository in (ECR.replace('us-east-1','us-west-2'),ECR.replace('123456789012','999999999999')):
            r=self.fixture('aws.lambda');ex=RegistryFake(r)
            with self.assertRaises(common.ProviderError):registry.destination(r,ex,{'expectedIdentity':'123456789012'},repository,'aws')
            self.assertEqual(ex.calls,[])
    def test_gar_acr_protected_promotion(self):
        cases=[('gcp.cloudrun','123','us-docker.pkg.dev/project/images','us-docker.pkg.dev/project/images/api'),('azure.containerapps','sub','native.azurecr.io/api','native.azurecr.io/api')]
        for kind,account,repo,expected in cases:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as root:
                r=self.fixture(kind);ex=RegistryFake(r)
                ctx={'workDir':root,'expectedIdentity':account,'registries':{'prod':{'provider':r['target']['provider'],'repository':repo}}}
                self.assertEqual(registry.materialize(r,ex,ctx,SOURCE),expected+'@'+DIGEST)
                self.assertEqual(r['artifact']['digest'],DIGEST)
    def test_all_native_registry_transports_fail_closed_on_rewrite_auth_and_upload_denial(self):
        cases=[('aws.lambda','123456789012',ECR),
               ('gcp.cloudrun','123','us-docker.pkg.dev/project/images'),
               ('azure.containerapps','sub','native.azurecr.io/api')]
        for kind,account,repository in cases:
            for failure in ('destination','login','copy'):
                r=self.fixture(kind);ex=RegistryFake(r,wrong=failure)
                execute=ex.run
                def denied(argv,**kwargs):
                    if argv[:2]==['skopeo',failure]:
                        ex.calls.append((argv,kwargs))
                        return subprocess.CompletedProcess(argv,1,'','SECRET-NATIVE-TOKEN denial')
                    return execute(argv,**kwargs)
                ex.run=denied
                with self.subTest(kind=kind,failure=failure),tempfile.TemporaryDirectory() as root:
                    ctx={'workDir':root,'expectedIdentity':account,
                         'registries':{r['target']['authRef']:{'provider':r['target']['provider'],'repository':repository}}}
                    resource={'Code':{'ResolvedImageUri':ECR+'@'+DIGEST}} if kind=='aws.lambda' else None
                    with self.assertRaises(Exception) as caught:
                        registry.materialize(r,ex,ctx,SOURCE,lambda_resource=resource)
                    self.assertNotIn('SECRET-NATIVE-TOKEN',str(caught.exception))
                    self.assertEqual(list(Path(root).iterdir()),[])
                    self.assertEqual(r['artifact']['location']['reference'],SOURCE)
                    if failure=='login':self.assertFalse(any(argv[:2]==['skopeo','copy'] for argv,_ in ex.calls))

    def test_default_public_only_even_with_source_token(self):
        r=self.fixture('azure.aks');ex=RegistryFake(r)
        self.assertEqual(registry.materialize(r,ex,{'registrySourceToken':'secret'},SOURCE),SOURCE)
        self.assertIn('--no-creds',ex.calls[0][0]);self.assertNotIn('--authfile',ex.calls[0][0])
        with self.assertRaises(Exception):registry.materialize(r,RegistryFake(r,wrong='private'),{},SOURCE)
    def test_protected_context_and_identity_rejections(self):
        for raw in ('[]','{"prod":{"provider":"aws","repository":"evil/../repo"}}','{"prod":{"provider":"gcp","repository":"good/repo","extra":1}}'):
            with self.assertRaises(common.ProviderError):registry.protected_context({'CLOUDOPSWORKS_REGISTRIES':raw})
        r=self.fixture('gcp.cloudrun');ex=RegistryFake(r)
        with self.assertRaises(common.ProviderError):registry.destination(r,ex,{'expectedIdentity':'123'},'us-docker.pkg.dev/other/images','gcp')
        self.assertEqual(ex.calls,[])
    def test_stable_primary_resource_lock_across_release_staging_objects(self):
        first=request('aws.beanstalk');second=copy.deepcopy(first)
        second['releaseVersion']='2.0.0';second['idempotencyKey']='sha256:'+'d'*64;second['artifact']['digest']='sha256:'+'e'*64
        a=aws.resolve(first,RegistryFake(first));b=aws.resolve(second,RegistryFake(second))
        self.assertNotEqual(a['resourceClaims'],b['resourceClaims'])
        self.assertEqual(a['resourceLock'],b['resourceLock'])
        self.assertIn(a['resourceLock'],a['resourceClaims'])
    def test_appengine_sdk_publication_cannot_bypass_iac_authorization(self):
        r=self.fixture('gcp.appengine')
        r['package']={'kind':'container','context':'.','dockerfile':'Dockerfile','platform':'linux/amd64'}
        r['workload']['port']=8080
        ex=RegistryFake(r)
        with tempfile.TemporaryDirectory() as root:
            result=gcp.deploy(r,ex,context={'workDir':root})
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['error']['code'],'iac-authorization-required')
        self.assertEqual(ex.calls,[])

    def test_registry_change_reconciles_same_artifact_without_build(self):
        from deploy import effective_digest
        from receipts import ReceiptStore
        r=self.fixture('gcp.cloudrun');base=gcp.resolve(r,RegistryFake(r))
        first=dict(base,registryConfig={'mapping':{'provider':'gcp','repository':'us-docker.pkg.dev/project/old'},'destination':{'repository':'us-docker.pkg.dev/project/old/api'}})
        second=dict(base,registryConfig={'mapping':{'provider':'gcp','repository':'us-docker.pkg.dev/project/new'},'destination':{'repository':'us-docker.pkg.dev/project/new/api'}})
        old_digest=effective_digest(r['target'],r['workload'],first)
        r['target']['configDigest']=effective_digest(r['target'],r['workload'],second)
        self.assertNotEqual(old_digest,r['target']['configDigest'])
        store=ReceiptStore.__new__(ReceiptStore)
        store.attempts=lambda *args:[{'status':{'state':'success'},'deployment':{'id':41},'payload':{'artifactDigest':DIGEST,'targetConfigDigest':old_digest}}]
        self.assertEqual(store.convergence(r),('target-changed','41'))
        self.assertEqual(r['artifact']['digest'],DIGEST)
        with self.assertRaises(common.ProviderError):registry.assert_mapping(r,first,{'prod':{'provider':'gcp','repository':'us-docker.pkg.dev/project/new'}})
    def test_global_readonly_registry_resolution_precedes_any_copy(self):
        r=self.fixture('gcp.cloudrun');ex=RegistryFake(r)
        resolved=gcp.resolve(r,ex)
        result=registry.bind_resolution(r,resolved,ex,{'prod':{'provider':'gcp','repository':'us-docker.pkg.dev/project/images'}})
        self.assertEqual(result['registryConfig']['destination']['repository'],'us-docker.pkg.dev/project/images/api')
        self.assertFalse(any(a[:2] in (['skopeo','copy'],['skopeo','login']) for a,k in ex.calls))
        ex=RegistryFake(r)
        with self.assertRaises(common.ProviderError):registry.bind_resolution(r,resolved,ex,{'prod':{'provider':'gcp','repository':'us-docker.pkg.dev/other/images'}})
        self.assertEqual(ex.calls,[])
    def test_workflow_permissions_and_protected_context_wiring(self):
        workflows=ROOT/'.github/workflows'
        for name in ('main-build','manual-apply'):
            text=(workflows/f'monorepo-{name}.yml').read_text()
            self.assertIn('CLOUDOPSWORKS_REGISTRIES: ${{ vars.CLOUDOPSWORKS_REGISTRIES }}',text)
            self.assertIn('GH_TOKEN: ${{ github.token }}',text)
            self.assertRegex(text,r'packages: (read|write)')
        # Legacy entry remains fail-closed; new normal entry obtains registry
        # settings only after independently prepared host/config/scan authority.
        self.assertIn('protected_context(os.environ)',(ROOT/'cd/monorepo/runtime/workflow.py').read_text())
        normal=(ROOT/'cd/monorepo/runtime/normal_entry.py').read_text()
        self.assertIn('prepare_verified_context',normal)
        self.assertIn('materialize(prepared,publisher,request',normal)
        self.assertIn('bind_resolution(fresh_request',normal)

if __name__=='__main__':unittest.main()
