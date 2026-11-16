"""Selected OpenTofu native backend credential precedence, localhost only.

No cloud resource or remote backend is accessed. The loopback server observes
real native S3 signing and GCS external-account token exchange, not argv names.
"""
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'cd/monorepo/runtime'))
from credential_context import backend_configuration

class NativeBackendCredentialsTests(unittest.TestCase):
    def test_exact_tofu_s3_temporary_tuple_overrides_provider_and_home(self):
        observed=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                observed.append(dict(self.headers));self.send_response(200);self.send_header('Content-Type','application/xml');self.end_headers()
                self.wfile.write(b'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Name>test-bucket</Name><KeyCount>0</KeyCount><IsTruncated>false</IsTruncated></ListBucketResult>')
            def do_HEAD(self):
                observed.append(dict(self.headers));self.send_response(404);self.end_headers()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                env={'AWS_ACCESS_KEY_ID':'KEY-state','AWS_SECRET_ACCESS_KEY':'SECRET-CANARY-state','AWS_SESSION_TOKEN':'TOKEN-CANARY-state'}
                context={'provider':'aws','identity':{'provider':'aws','accountId':'111111111111'},'environment':env}
                handle={'backend':{'kind':'s3'},'backendIdentity':context['identity']}
                configuration=backend_configuration(handle,context)
                configuration.update(bucket='test-bucket',key='test.tfstate',region='us-east-1',skip_credentials_validation=True,
                    skip_region_validation=True,skip_requesting_account_id=True,use_path_style=True,endpoints={'s3':'http://127.0.0.1:'+str(server.server_port)})
                (root/'backend.tf.json').write_text(json.dumps({'terraform':{'backend':{'s3':configuration}}}));(root/'backend.tf.json').chmod(0o600)
                aws=root/'.aws';aws.mkdir();(aws/'credentials').write_text('[default]\naws_access_key_id=KEY-home\naws_secret_access_key=SECRET-home\n')
                result=self.run_init(root,{'AWS_ACCESS_KEY_ID':'KEY-workload','AWS_SECRET_ACCESS_KEY':'SECRET-workload','AWS_SESSION_TOKEN':'TOKEN-workload'})
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertTrue(observed)
                for headers in observed:
                    self.assertIn('Credential=KEY-state/',headers['Authorization']);self.assertEqual(headers['X-Amz-Security-Token'],'TOKEN-CANARY-state')
                self.assertNotIn('CANARY',result.stdout+result.stderr)
                # Native .terraform backend metadata DOES contain these secrets;
                # entire generated workspace, not only tfplan, must stay private.
                self.assertIn('SECRET-CANARY-state',(root/'.terraform/terraform.tfstate').read_text())
            finally:server.shutdown();server.server_close();thread.join()
    def test_exact_tofu_gcs_external_account_file_overrides_workload_adc(self):
        observed=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=self.rfile.read(int(self.headers.get('Content-Length',0)))
                if self.path=='/impersonate':
                    observed.append(('impersonate',self.headers.get('Authorization')))
                    value={'accessToken':'STATE-CANARY-TOKEN','expireTime':'2099-01-01T00:00:00Z'}
                else:
                    observed.append(('token',body.decode()))
                    value={'access_token':'FEDERATED-CANARY-TOKEN','expires_in':3600,'token_type':'Bearer','issued_token_type':'urn:ietf:params:oauth:token-type:access_token'}
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(value).encode())
            def do_GET(self):
                observed.append(('storage',self.headers.get('Authorization')))
                is_list=self.path.startswith('/b/test-bucket/o?')
                self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
                state={'version':4,'terraform_version':'1.11.4','serial':1,'lineage':'00000000-0000-0000-0000-000000000000','outputs':{},'resources':[]}
                self.wfile.write(b'{"items":[]}' if is_list else json.dumps(state).encode())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                base='http://127.0.0.1:'+str(server.server_port)
                (root/'subject').write_text('STATE-CANARY-SUBJECT')
                (root/'credentials').write_text(json.dumps({'type':'external_account',
                    'audience':'//iam.googleapis.com/projects/123/locations/global/workloadIdentityPools/test/providers/test',
                    'subject_token_type':'urn:ietf:params:oauth:token-type:jwt','token_url':base+'/token',
                    'service_account_impersonation_url':base+'/impersonate',
                    'credential_source':{'file':str(root/'subject')}}))
                (root/'workload-adc').write_text('INVALID-WORKLOAD-ADC')
                context={'provider':'gcp','identity':{'provider':'gcp','projectNumber':'123'},'environment':{'GOOGLE_APPLICATION_CREDENTIALS':str(root/'credentials')}}
                handle={'backend':{'kind':'gcs'},'backendIdentity':context['identity']}
                configuration=backend_configuration(handle,context);configuration.update(bucket='test-bucket',prefix='state',storage_custom_endpoint=base+'/')
                (root/'backend.tf.json').write_text(json.dumps({'terraform':{'backend':{'gcs':configuration}}}));(root/'backend.tf.json').chmod(0o600)
                result=self.run_init(root,{'GOOGLE_APPLICATION_CREDENTIALS':str(root/'workload-adc'),'GOOGLE_OAUTH_ACCESS_TOKEN':'WORKLOAD-CANARY-TOKEN'})
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertTrue(any(kind=='token' and 'subject_token=STATE-CANARY-SUBJECT' in value for kind,value in observed))
                self.assertTrue(any(kind=='impersonate' and value=='Bearer FEDERATED-CANARY-TOKEN' for kind,value in observed))
                self.assertTrue(any(kind=='storage' for kind,_ in observed))
                self.assertTrue(all(value=='Bearer STATE-CANARY-TOKEN' for kind,value in observed if kind=='storage'))
                self.assertNotIn('CANARY',result.stdout+result.stderr)
            finally:server.shutdown();server.server_close();thread.join()
    def test_exact_tofu_azure_selected_oidc_file_denial_never_falls_back_to_workload_secrets(self):
        # Deliberate missing selected assertion proves native precedence and
        # fail-closed behavior, NOT a successful Azure token exchange/cloud test.
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();missing=root/'backend-selected-token-missing'
            identity={'provider':'azure','tenantId':'22222222-2222-2222-2222-222222222222','subscriptionId':'33333333-3333-3333-3333-333333333333'}
            context={'provider':'azure','identity':identity,'environment':{
                'ARM_CLIENT_ID':'11111111-1111-1111-1111-111111111111','ARM_TENANT_ID':identity['tenantId'],
                'ARM_SUBSCRIPTION_ID':identity['subscriptionId'],'ARM_OIDC_TOKEN_FILE_PATH':str(missing)}}
            handle={'backend':{'kind':'azurerm'},'backendIdentity':identity}
            configuration=backend_configuration(handle,context)
            configuration.update(resource_group_name='rg-test',storage_account_name='stateaccount',container_name='state',key='state.tfstate',timeout_seconds=1)
            (root/'backend.tf.json').write_text(json.dumps({'terraform':{'backend':{'azurerm':configuration}}}))
            result=self.run_init(root,{'ARM_OIDC_TOKEN':'WORKLOAD-CANARY','ARM_ACCESS_KEY':'WORKLOAD-KEY-CANARY',
                'ARM_CLIENT_SECRET':'WORKLOAD-SECRET-CANARY','HTTPS_PROXY':'http://127.0.0.1:1','HTTP_PROXY':'http://127.0.0.1:1'})
            self.assertNotEqual(result.returncode,0)
            self.assertIn('backend-selected-token-missing',result.stderr)
            self.assertIn('Setting use_cli to false',result.stderr)
            self.assertNotIn('CANARY',result.stdout+result.stderr)

    def run_init(self,root,credentials):
        tofu=shutil.which('tofu');self.assertIsNotNone(tofu,'pinned local OpenTofu prerequisite')
        version=subprocess.run([tofu,'version','-json'],capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(version.stdout)['terraform_version'],'1.11.4')
        env={'PATH':os.environ['PATH'],'HOME':str(root),'AWS_EC2_METADATA_DISABLED':'true',**credentials}
        return subprocess.run([tofu,'init','-no-color','-input=false'],cwd=root,env=env,capture_output=True,text=True,timeout=20)

if __name__=='__main__':unittest.main()
