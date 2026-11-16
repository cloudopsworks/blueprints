"""Private, independently captured workload/backend cloud credentials.

These files are process-local secrets, never contract records or artifacts. A
second login cannot change the first context. Native backend parameters have
explicit precedence over the workload provider environment and ambient caches.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import shutil
from contracts import fail, canonical_bytes
from executor import checked, Runner

PROVIDERS={'s3':'aws','gcs':'gcp','azurerm':'azure'}
UUID=r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'


def _private_file(path, data):
    path=Path(path)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(data)
    return str(path)


def _read(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>4*1024*1024:
        fail('credential-file','selected credential file is invalid')
    return path.read_bytes()


def capture(provider,binding,executor,*,root,environment,oidc_token=None):
    """Capture ONE selected principal after its existing OIDC action completed.

    Caller supplies normalized protected binding and an isolated actual Runner.
    Native read-only identity checks run against exactly the captured context.
    No credential appears in argv, output, record or error text.
    """
    if provider not in ('aws','gcp','azure') or binding.get('provider')!=provider:
        fail('credential-provider','selected cloud binding differs')
    if isinstance(executor,Runner) and executor.inherit_environment:
        fail('credential-environment','credential capture requires isolated execution')
    root=Path(root).resolve()
    if root.exists():fail('credential-collision','private credential destination exists')
    root.mkdir(mode=0o700,parents=True)
    home=root/'home';home.mkdir(mode=0o700)
    empty=_private_file(home/'empty',b'')
    env={'PATH':environment.get('PATH',os.environ.get('PATH','')),'HOME':str(home),
         'AWS_EC2_METADATA_DISABLED':'true','AWS_SHARED_CREDENTIALS_FILE':empty,'AWS_CONFIG_FILE':empty,
         'CLOUDSDK_CONFIG':str(home/'gcloud'),'AZURE_CONFIG_DIR':str(home/'azure')}
    def get(argv):
        try:return json.loads(checked(executor,argv,env=env))
        except (ValueError,TypeError):fail('credential-identity','native selected identity is invalid')
    if provider=='aws':
        keys=('AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','AWS_SESSION_TOKEN')
        if any(not isinstance(environment.get(k),str) or not environment[k] for k in keys):
            fail('credential-missing','temporary AWS credential tuple is incomplete')
        env.update({k:environment[k] for k in keys})
        env.update(AWS_REGION=binding['region'],AWS_DEFAULT_REGION=binding['region'])
        live=get(['aws','sts','get-caller-identity','--region',binding['region'],'--no-cli-pager','--output','json'])
        role=re.fullmatch(r'arn:aws(?:-us-gov|-cn)?:iam::([0-9]{12}):role/(.+)',binding['roleArn'])
        account=live.get('Account');arn=live.get('Arn','')
        if not role or account!=role[1] or not re.fullmatch(r'arn:aws(?:-us-gov|-cn)?:sts::'+account+r':assumed-role/'+re.escape(role[2].split('/')[-1])+r'/[^/]+',arn):
            fail('credential-identity','actual AWS principal differs from selected role')
        identity={'provider':'aws','accountId':account}
    elif provider=='gcp':
        raw=_read(environment.get('GOOGLE_APPLICATION_CREDENTIALS',''))
        try:document=json.loads(raw)
        except (ValueError,TypeError):fail('credential-file','selected GCP credentials are invalid')
        # Existing google auth action produces external-account WIF credentials
        # with exact service-account impersonation, not a developer ADC cache.
        expected='https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/'+binding['serviceAccount']+':generateAccessToken'
        if (document.get('type')!='external_account' or document.get('service_account_impersonation_url')!=expected
                or document.get('audience')!='//iam.googleapis.com/'+binding['workloadIdentityProvider']):
            fail('credential-identity','GCP impersonation principal differs from selected binding')
        source=document.get('credential_source',{})
        if 'file' in source:
            source['file']=_private_file(root/'subject-token',_read(source['file']))
        credential=_private_file(root/'gcp.json',canonical_bytes(document))
        env.update(GOOGLE_APPLICATION_CREDENTIALS=credential,CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE=credential)
        live=get(['gcloud','projects','describe',binding['project'],'--quiet','--format=json'])
        number=str(live.get('projectNumber',''))
        if live.get('projectId')!=binding['project'] or not re.fullmatch(r'[1-9][0-9]*',number):
            fail('credential-identity','configured GCP project identity differs')
        identity={'provider':'gcp','projectNumber':number}
    else:
        source=Path(environment.get('AZURE_CONFIG_DIR',''))
        if not source.is_dir() or source.is_symlink():fail('credential-file','selected Azure CLI context is missing')
        destination=Path(env['AZURE_CONFIG_DIR'])
        # Native CLI cache is secret-bearing too; no symlink/cache alias survives.
        for path in source.rglob('*'):
            if path.is_symlink():fail('credential-file','selected Azure CLI context contains a link')
            if path.is_file() and path.stat().st_size>16*1024*1024:fail('credential-file','selected Azure CLI context is too large')
        shutil.copytree(source,destination)
        for path in destination.rglob('*'):path.chmod(0o700 if path.is_dir() else 0o600)
        live=get(['az','account','show','--only-show-errors','--output','json'])
        tenant=binding['tenantId'].lower();subscription=binding['subscriptionId'].lower()
        if (live.get('id','').lower()!=subscription or live.get('tenantId','').lower()!=tenant
            or live.get('user',{}).get('type')!='servicePrincipal'
            or live.get('user',{}).get('name','').lower()!=binding['clientId'].lower()):
            fail('credential-identity','actual Azure principal differs from selected binding')
        if not isinstance(oidc_token,str) or not oidc_token or len(oidc_token)>1024*1024 or any(c.isspace() for c in oidc_token):
            fail('credential-missing','selected Azure OIDC assertion is missing')
        token=_private_file(root/'oidc-token',oidc_token.encode())
        env.update(ARM_CLIENT_ID=binding['clientId'],ARM_TENANT_ID=tenant,ARM_SUBSCRIPTION_ID=subscription,
            ARM_USE_OIDC='true',ARM_USE_AZUREAD='true',ARM_USE_CLI='false',ARM_USE_MSI='false',ARM_OIDC_TOKEN_FILE_PATH=token)
        identity={'provider':'azure','tenantId':tenant,'subscriptionId':subscription}
    principal_keys={'aws':('provider','roleArn','region'),'gcp':('provider','workloadIdentityProvider','serviceAccount','project'),
        'azure':('provider','clientId','tenantId','subscriptionId')}[provider]
    value={'provider':provider,'identity':identity,'binding':{key:binding[key] for key in principal_keys},'environment':env}
    _private_file(root/'context.json',canonical_bytes(value))
    return value


def backend_configuration(handle,backend_context):
    """Native-only secret options; never human passthrough or exported record."""
    provider=PROVIDERS[handle['backend']['kind']]
    if (not isinstance(backend_context,dict) or backend_context.get('provider')!=provider
        or backend_context.get('identity')!=handle.get('backendIdentity')):
        fail('backend-credential-identity','selected backend identity differs from frozen handle')
    env=backend_context['environment']
    if provider=='aws':
        return {'access_key':env['AWS_ACCESS_KEY_ID'],'secret_key':env['AWS_SECRET_ACCESS_KEY'],
                'token':env['AWS_SESSION_TOKEN'],'skip_metadata_api_check':True,
                'shared_credentials_files':[],'shared_config_files':[]}
    if provider=='gcp':return {'credentials':env['GOOGLE_APPLICATION_CREDENTIALS'],'access_token':''}
    return {'client_id':env['ARM_CLIENT_ID'],'tenant_id':env['ARM_TENANT_ID'],
            'subscription_id':env['ARM_SUBSCRIPTION_ID'],'oidc_token_file_path':env['ARM_OIDC_TOKEN_FILE_PATH'],
            'use_oidc':True,'use_azuread_auth':True,'use_cli':False,'use_msi':False,'use_aks_workload_identity':False,
            'access_key':'','sas_token':'','client_secret':'','client_secret_file_path':'','client_id_file_path':'',
            'client_certificate':'','client_certificate_password':'','client_certificate_path':'',
            'oidc_token':'','oidc_request_url':'','oidc_request_token':''}


def validate_pair(handle,workload,backend):
    """Credential context is not bucket ownership or resource adoption proof."""
    provider=handle['resourceIdentity']['kind'].split('.')[0]
    actual=workload.get('identity',{})
    canonical=actual.get({'aws':'accountId','gcp':'projectNumber','azure':'subscriptionId'}[provider])
    if workload.get('provider')!=provider or canonical!=handle['providerIdentity']:
        fail('workload-credential-identity','selected workload identity differs from frozen handle')
    backend_configuration(handle,backend)
    return {'workload':workload,'backend':backend}


def _azure_assertion(environment):
    """Use existing job OIDC authority; never infer authority from JWT claims."""
    from urllib.parse import urlsplit,urlencode,parse_qsl,urlunsplit
    from urllib.request import Request,build_opener,HTTPRedirectHandler
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    url=environment.get('ACTIONS_ID_TOKEN_REQUEST_URL','');parts=urlsplit(url)
    if (parts.scheme!='https' or not parts.hostname or not parts.hostname.endswith('.actions.githubusercontent.com')
            or parts.username or parts.password or parts.fragment):
        fail('credential-oidc','job OIDC endpoint is invalid')
    query=[(k,v) for k,v in parse_qsl(parts.query) if k!='audience']
    query.append(('audience','api://AzureADTokenExchange'))
    url=urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(query),''))
    try:
        request=Request(url,headers={'Authorization':'Bearer '+environment['ACTIONS_ID_TOKEN_REQUEST_TOKEN']})
        with build_opener(NoRedirect).open(request,timeout=30) as response:
            raw=response.read(1024*1024+1)
        if len(raw)>1024*1024:raise ValueError('bound')
        value=json.loads(raw)['value']
        if not isinstance(value,str) or not value:raise ValueError('missing')
        return value
    except Exception:fail('credential-oidc','selected job OIDC acquisition failed')


def main():
    import subprocess
    environment=dict(os.environ);provider=environment.get('PROVIDER');ref=environment.get('AUTH_REF')
    name=environment.get('CONTEXT_NAME')
    if name not in ('workload','backend','root-backend') or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}',ref or ''):
        fail('credential-context','fixed private credential context is invalid')
    try:
        normalized=subprocess.run(['tronador','components','settings','--kind','auth','--json'],
            input=environment.get('BINDINGS',''),text=True,capture_output=True,timeout=15,check=False,
            env={'PATH':environment.get('PATH','')})
        if normalized.returncode or len(normalized.stdout.encode())>4*1024*1024:raise ValueError('settings')
        binding=json.loads(normalized.stdout)[ref]
    except Exception:fail('credential-context','selected protected binding is invalid')
    root=Path(environment['RUNNER_TEMP']).resolve()/('cloudopsworks-credentials-'+name)
    value=capture(provider,binding,Runner(inherit_environment=False),root=root,environment=environment,
        oidc_token=_azure_assertion(environment) if provider=='azure' else None)
    with open(environment['GITHUB_OUTPUT'],'a') as output:output.write('context-path='+str(root/'context.json')+'\n')


CREDENTIAL_ENVIRONMENT={'PATH','AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','AWS_SESSION_TOKEN','AWS_REGION','AWS_DEFAULT_REGION',
    'GOOGLE_APPLICATION_CREDENTIALS','CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE','AZURE_CONFIG_DIR',
    'ARM_CLIENT_ID','ARM_TENANT_ID','ARM_SUBSCRIPTION_ID','ARM_USE_OIDC','ARM_OIDC_TOKEN','ARM_OIDC_TOKEN_FILE_PATH',
    'ARM_USE_AZUREAD','ARM_USE_CLI','ARM_USE_MSI','KUBECONFIG','TF_VAR_package_read_sas'}
ISOLATION_ENVIRONMENT={'HOME','AWS_EC2_METADATA_DISABLED','AWS_SHARED_CREDENTIALS_FILE','AWS_CONFIG_FILE','CLOUDSDK_CONFIG'}


def credential_environment(context):
    env=context.get('environment') if isinstance(context,dict) else None
    if not isinstance(env,dict) or any(k not in CREDENTIAL_ENVIRONMENT|ISOLATION_ENVIRONMENT or not isinstance(v,str) for k,v in env.items()):
        fail('credential-environment','captured credential environment is invalid')
    return {k:v for k,v in env.items() if k in CREDENTIAL_ENVIRONMENT}


def execution_credentials(handle,credentials):
    if isinstance(credentials,dict) and set(credentials)=={'workload','backend'}:
        if 'backendIdentity' not in handle:fail('backend-legacy-identity','legacy handle cannot infer a separate backend principal')
        validate_pair(handle,credentials['workload'],credentials['backend'])
        return credential_environment(credentials['workload']),backend_configuration(handle,credentials['backend'])
    if 'backendIdentity' in handle:fail('backend-credential-pair','new handle requires independently captured credential pair')
    if not isinstance(credentials,dict):fail('credential-environment','credential context is invalid')
    return dict(credentials),{}


def read_context(path, *, runner_temp):
    """Read only the private exact action-created file, never a wire locator."""
    from contracts import _pairs,_constant
    original=Path(path);root=Path(runner_temp).resolve()
    if original.is_symlink() or not original.is_absolute():fail('credential-file','private credential path is invalid')
    path=original.resolve()
    if (not path.is_relative_to(root) or path.name!='context.json'
        or path.parent.name not in ('cloudopsworks-credentials-workload','cloudopsworks-credentials-backend')
        or path.stat().st_mode&0o077 or path.parent.stat().st_mode&0o077):
        fail('credential-file','private credential path is not action-owned')
    try:value=json.loads(_read(path),object_pairs_hook=_pairs,parse_constant=_constant)
    except (ValueError,TypeError):fail('credential-file','private credential bytes are invalid')
    if not isinstance(value,dict) or set(value)!={'provider','identity','binding','environment'} or value['provider'] not in ('aws','gcp','azure'):
        fail('credential-file','private credential context is invalid')
    credential_environment(value)
    return value

if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit('protected-credential-capture-failed') from None
