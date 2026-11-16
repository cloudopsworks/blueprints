"""Connect independently prepared authorization to read-only ownership preflight.

No serialized context can stand in for PreparedAuthorization. Source jobs never
call this boundary. Cloud credentials are explicit process-local inputs only.
"""
import os
from pathlib import Path
from authorization import PreparedAuthorization
from contracts import fail,digest
from executor import Runner
from private_state import read_private_state
from providers.preflight import resolve


class CloudExecutor:
    def __init__(self,executor,environment):self.executor,self.environment=executor,environment
    def bounded(self,seconds):
        if callable(getattr(self.executor,'bounded',None)):
            return CloudExecutor(self.executor.bounded(seconds),self.environment)
        if type(self.executor) is Runner:
            return CloudExecutor(Runner(timeout=min(self.executor.timeout,seconds),
                output_limit=self.executor.output_limit,inherit_environment=False),self.environment)
        return self
    def run(self,argv,**kwargs):
        kwargs['env']={**self.environment,**kwargs.get('env',{})}
        return self.executor.run(argv,**kwargs)


def context(prepared,executor,*,workdir,credentials,kubeconfig=None):
    if not isinstance(prepared,PreparedAuthorization) or not prepared._bound or prepared._inspection:
        fail('protected-runtime-authorization','independently prepared protected context is required')
    if isinstance(executor,Runner) and executor.inherit_environment:
        fail('protected-runtime-environment','protected native execution cannot inherit ambient credentials')
    credential_pair=credentials if isinstance(credentials,dict) and set(credentials)=={'workload','backend'} else None
    backend_credentials=credentials
    if isinstance(credentials,dict) and set(credentials)=={'workload','backend'}:
        from credential_context import credential_environment
        backend_credentials=credential_environment(credentials['backend'])
        credentials=credential_environment(credentials['workload'])
    allowed={'PATH','KUBECONFIG','AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','AWS_SESSION_TOKEN','AWS_REGION','AWS_DEFAULT_REGION',
        'GOOGLE_APPLICATION_CREDENTIALS','CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE','AZURE_CONFIG_DIR',
        'ARM_CLIENT_ID','ARM_TENANT_ID','ARM_SUBSCRIPTION_ID','ARM_USE_OIDC','ARM_OIDC_TOKEN','ARM_OIDC_TOKEN_FILE_PATH','ARM_USE_AZUREAD','ARM_USE_CLI','ARM_USE_MSI'}
    if not isinstance(credentials,dict) or any(k not in allowed or not isinstance(v,str) for k,v in credentials.items()):
        fail('protected-runtime-environment','native credential environment is not allowlisted')
    root=Path(workdir).resolve();root.mkdir(mode=0o700,parents=True,exist_ok=True)
    if root.is_symlink() or root.stat().st_mode&0o077:
        fail('protected-runtime-workspace','protected native workspace must be private')
    home=root/'native-home';home.mkdir(mode=0o700,exist_ok=False)
    empty=home/'empty';empty.write_text('');empty.chmod(0o600)
    environment={**credentials,'PATH':credentials.get('PATH',os.environ.get('PATH','')),'HOME':str(home),
        'AWS_EC2_METADATA_DISABLED':'true','AWS_SHARED_CREDENTIALS_FILE':str(empty),'AWS_CONFIG_FILE':str(empty),
        'CLOUDSDK_CONFIG':str(home/'gcloud'),'AZURE_CONFIG_DIR':credentials.get('AZURE_CONFIG_DIR',str(home/'azure'))}
    if credentials.get('GOOGLE_APPLICATION_CREDENTIALS'):
        environment.setdefault('CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE',credentials['GOOGLE_APPLICATION_CREDENTIALS'])
    cloud=CloudExecutor(executor,environment)
    result={'workDir':root,'iac_authorize':prepared.authorize,'privateStateDigests':{}}
    native_snapshots={}
    def preflight(request,unused_executor):
        historical=prepared.resolve_context(request)['historical_handle']
        if historical and 'backendIdentity' in historical:
            from credential_context import backend_configuration
            backend_configuration(historical,credential_pair['backend'])
        state=read_private_state(historical,executor,workdir=root,env=backend_credentials) if historical else None
        native=resolve(request,cloud,historical_handle=historical,private_state=state,kubeconfig=kubeconfig)
        native_snapshots[(request['target']['id'],request['componentId'])]=(historical,state)
        if state is not None:result['privateStateDigests'][(request['target']['id'],request['componentId'])]=digest(state)
        if request['target']['kind']=='aws.apigateway-rest' and historical and native['existing']['exists']:
            resource=native['resource']
            if not isinstance(resource.get('name'),str) or not isinstance(resource.get('description',''),str):
                fail('protected-api-configuration','verified native REST configuration is invalid')
            native['verifiedApiConfiguration']={'name':resource['name'],'description':resource.get('description','')}
        return native
    def refresh(request):
        key=(request['target']['id'],request['componentId'])
        if key not in native_snapshots:fail('protected-runtime-inventory','native inventory has not been established')
        historical,state=native_snapshots[key]
        # Re-read actual cloud inventory immediately before submission against
        # the exact already verified private-state snapshot, not a newly created
        # reservation mistaken for prior native ownership.
        return resolve(request,cloud,historical_handle=historical,private_state=state,kubeconfig=kubeconfig)
    result['iac_refresh']=refresh
    result['iac_resolve']=preflight
    return result,cloud
