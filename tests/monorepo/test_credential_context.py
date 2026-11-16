import copy
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'cd/monorepo/runtime'))
from credential_context import capture,backend_configuration,validate_pair
from contracts import ContractError

class Native:
    def __init__(self,provider,binding):self.provider,self.binding,self.calls=provider,binding,[]
    def run(self,argv,**kwargs):
        self.calls.append((argv,kwargs));env=kwargs['env'];binding=self.binding
        assert 'GH_TOKEN' not in env and 'CANARY_AMBIENT' not in env
        assert env['HOME']!=os.environ.get('HOME')
        if self.provider=='aws':
            assert env['AWS_ACCESS_KEY_ID'].startswith('KEY-')
            value={'Account':binding['roleArn'].split(':')[4],'Arn':binding['roleArn'].replace(':iam:',':sts:').replace(':role/',':assumed-role/')+'/session'}
        elif self.provider=='gcp':
            path=Path(env['GOOGLE_APPLICATION_CREDENTIALS']);assert path.is_file()
            assert env['CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE']==str(path)
            value={'projectId':binding['project'],'projectNumber':'12345' if binding['project']=='state-project' else '67890'}
        else:
            assert Path(env['AZURE_CONFIG_DIR'],'token-cache').read_text().startswith('AZURE-CANARY')
            value={'id':binding['subscriptionId'],'tenantId':binding['tenantId'],'user':{'type':'servicePrincipal','name':binding['clientId']}}
        return SimpleNamespace(returncode=0,stdout=json.dumps(value),stderr='')

class CredentialContextTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve();self.count=0
    def tearDown(self):self.temp.cleanup()
    def captured(self,provider,label):
        self.count+=1;source=self.root/('source'+str(self.count));source.mkdir(mode=0o700)
        env={'PATH':os.environ['PATH'],'GH_TOKEN':'GH-CANARY','CANARY_AMBIENT':'FORBIDDEN'}
        if provider=='aws':
            account='111111111111' if label=='state' else '222222222222'
            binding={'provider':'aws','roleArn':'arn:aws:iam::'+account+':role/'+label,'region':'us-east-1'}
            env.update(AWS_ACCESS_KEY_ID='KEY-'+label,AWS_SECRET_ACCESS_KEY='SECRET-CANARY-'+label,AWS_SESSION_TOKEN='SESSION-CANARY-'+label)
        elif provider=='gcp':
            binding={'provider':'gcp','project':label+'-project','serviceAccount':label+'@iam.example','workloadIdentityProvider':'projects/123/locations/global/workloadIdentityPools/pool/providers/provider'}
            token=source/'token';token.write_text('GCP-CANARY-'+label)
            document={'type':'external_account','audience':'//iam.googleapis.com/'+binding['workloadIdentityProvider'],'service_account_impersonation_url':'https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/'+binding['serviceAccount']+':generateAccessToken','credential_source':{'file':str(token)}}
            credential=source/'adc';credential.write_text(json.dumps(document));env['GOOGLE_APPLICATION_CREDENTIALS']=str(credential)
        else:
            digit='1' if label=='state' else '2';uuid=digit*8+'-'+digit*4+'-'+digit*4+'-'+digit*4+'-'+digit*12
            binding={'provider':'azure','subscriptionId':uuid,'tenantId':'a'*8+'-'+'a'*4+'-'+'a'*4+'-'+'a'*4+'-'+'a'*12,'clientId':uuid}
            (source/'token-cache').write_text('AZURE-CANARY-'+label);env['AZURE_CONFIG_DIR']=str(source)
        ex=Native(provider,binding)
        result=capture(provider,binding,ex,root=self.root/('capture'+str(self.count)),environment=env,oidc_token='OIDC-CANARY-'+label)
        return result,ex,source
    def handle(self,workload,backend):
        provider=workload['provider'];identity=workload['identity']
        return {'resourceIdentity':{'kind':provider+'.example'},'providerIdentity':identity[{'aws':'accountId','gcp':'projectNumber','azure':'subscriptionId'}[provider]],'backend':{'kind':{'aws':'s3','gcp':'gcs','azure':'azurerm'}[backend['provider']]},'backendIdentity':copy.deepcopy(backend['identity'])}
    def test_all_nine_pairs_exact_native_capture_and_backend_precedence(self):
        for wp in ('aws','gcp','azure'):
            for bp in ('aws','gcp','azure'):
                with self.subTest(workload=wp,backend=bp):
                    workload,wex,_=self.captured(wp,'workload');backend,bex,_=self.captured(bp,'state')
                    handle=self.handle(workload,backend);pair=validate_pair(handle,workload,backend)
                    native=backend_configuration(handle,pair['backend'])
                    self.assertEqual(len(wex.calls),1);self.assertEqual(len(bex.calls),1)
                    self.assertNotIn('GH-CANARY',json.dumps(pair))
                    if bp=='aws':self.assertEqual(native['access_key'],'KEY-state');self.assertEqual(native['secret_key'],'SECRET-CANARY-state')
                    elif bp=='gcp':self.assertIn('GCP-CANARY-state',Path(json.loads(Path(native['credentials']).read_text())['credential_source']['file']).read_text())
                    else:self.assertEqual(Path(native['oidc_token_file_path']).read_text(),'OIDC-CANARY-state');self.assertIs(native['use_cli'],False)
    def test_same_provider_both_orders_no_cache_overwrite_private_entire_tree(self):
        for provider in ('aws','gcp','azure'):
            for order in (('state','workload'),('workload','state')):
                values={}
                for label in order:
                    values[label],_,source=self.captured(provider,label)
                    # Later changes/removal of original action cache cannot affect capture.
                    for file in source.rglob('*'):
                        if file.is_file():file.write_text('SOURCE-OVERWRITTEN')
                pair=validate_pair(self.handle(values['workload'],values['state']),values['workload'],values['state'])
                native=backend_configuration(self.handle(values['workload'],values['state']),pair['backend'])
                self.assertNotIn('SOURCE-OVERWRITTEN',json.dumps(native))
                if provider=='gcp':self.assertIn('GCP-CANARY-state',Path(json.loads(Path(native['credentials']).read_text())['credential_source']['file']).read_text())
                if provider=='azure':self.assertEqual(Path(pair['backend']['environment']['AZURE_CONFIG_DIR'],'token-cache').read_text(),'AZURE-CANARY-state')
        for file in self.root.glob('capture*/**/*'):
            self.assertEqual(stat.S_IMODE(file.stat().st_mode),0o700 if file.is_dir() else 0o600)
    def test_wrong_provider_identity_and_missing_tuple_fail_without_fallback(self):
        workload,_,_=self.captured('aws','workload');backend,_,_=self.captured('gcp','state')
        handle=self.handle(workload,backend);handle['backendIdentity']['projectNumber']='999'
        with self.assertRaises(ContractError):validate_pair(handle,workload,backend)
        with self.assertRaises(ContractError):capture('aws',{'provider':'aws','roleArn':'unused','region':'x'},Native('aws',{}),root=self.root/'empty',environment={})
    def test_native_credential_values_never_in_argv_or_public_identity(self):
        for provider in ('aws','gcp','azure'):
            result,executor,_=self.captured(provider,'state')
            self.assertNotIn('CANARY',json.dumps([call[0] for call in executor.calls]))
            self.assertNotIn('CANARY',json.dumps(result['identity']))

if __name__=='__main__':unittest.main()
