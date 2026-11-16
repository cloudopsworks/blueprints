"""Read-only exact frozen backend state transport, never INIT/import/adoption.

Only host-verified historical handles may enter. Object metadata and conditional
version/ETag reads bind one bounded private snapshot; raw state never leaves the
private workspace or appears in diagnostics. Errors never mean empty state.
"""
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit,unquote
from contracts import fail,_pairs,_constant
from executor import checked,Runner
from operations import validate_operation

MAX_STATE=64*1024*1024


def read_private_state(handle,executor,*,workdir,env):
    validate_operation(handle)
    if isinstance(executor,Runner) and executor.inherit_environment:
        fail('state-read-environment','private state reads require explicit protected credentials only')
    allowed={'PATH','AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','AWS_SESSION_TOKEN','AWS_REGION','AWS_DEFAULT_REGION',
        'GOOGLE_APPLICATION_CREDENTIALS','CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE','AZURE_CONFIG_DIR',
        'ARM_CLIENT_ID','ARM_TENANT_ID','ARM_SUBSCRIPTION_ID','ARM_USE_OIDC','ARM_OIDC_TOKEN','ARM_OIDC_TOKEN_FILE_PATH','ARM_USE_AZUREAD','ARM_USE_CLI','ARM_USE_MSI'}
    if not isinstance(env,dict) or any(k not in allowed or not isinstance(v,str) for k,v in env.items()):
        fail('state-read-environment','private state read environment is not allowlisted')
    env=dict(env)
    backend=handle['backend'];address=handle['native']['stateAddress'];parts=urlsplit(address)
    if parts.username or parts.password or parts.query or parts.fragment:
        fail('state-read-address','frozen backend address is invalid')
    def run(argv,json_output=True):
        output=checked(executor,argv,env=env)
        if not json_output:return output
        try:return json.loads(output,object_pairs_hook=_pairs,parse_constant=_constant)
        except (ValueError,TypeError):fail('state-read-metadata','private state metadata is invalid')
    with tempfile.TemporaryDirectory(prefix='cloudopsworks-state-read-',dir=workdir) as directory:
        root=Path(directory);root.chmod(0o700);path=root/'state.json'
        home=root/'home';home.mkdir(mode=0o700);empty=home/'empty';empty.write_text('');empty.chmod(0o600)
        env.update(HOME=str(home),AWS_EC2_METADATA_DISABLED='true',AWS_SHARED_CREDENTIALS_FILE=str(empty),
            AWS_CONFIG_FILE=str(empty),CLOUDSDK_CONFIG=str(home/'gcloud'))
        if 'GOOGLE_APPLICATION_CREDENTIALS' in env:
            env.setdefault('CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE',env['GOOGLE_APPLICATION_CREDENTIALS'])
        env.setdefault('AZURE_CONFIG_DIR',str(home/'azure'))
        if backend['kind']=='s3':
            if parts.scheme!='s3' or parts.netloc!=backend['bucket']:fail('state-read-address','frozen S3 address differs')
            key=unquote(parts.path.lstrip('/'))
            base=['aws','s3api'];suffix=['--region',backend['region'],'--no-cli-pager','--output','json']
            metadata=run(base+['head-object','--bucket',backend['bucket'],'--key',key]+suffix)
            size=metadata.get('ContentLength');etag=metadata.get('ETag')
            argv=base+['get-object','--bucket',backend['bucket'],'--key',key,'--if-match',etag,str(path)]+suffix
        elif backend['kind']=='gcs':
            if parts.scheme!='gs' or parts.netloc!=backend['bucket']:fail('state-read-address','frozen GCS address differs')
            metadata=run(['gcloud','storage','objects','describe',address,'--quiet','--format=json'])
            raw=metadata.get('size');size=int(raw) if isinstance(raw,(str,int)) and re.fullmatch(r'[0-9]+',str(raw)) else None
            generation=metadata.get('generation');etag=str(generation) if generation is not None else None
            if not isinstance(etag,str) or not re.fullmatch(r'[1-9][0-9]*',etag):fail('state-read-metadata','private state generation is invalid')
            argv=['gcloud','storage','cp',address+'#'+etag,str(path),'--quiet']
        else:
            expected=backend['storageAccountName']+'.blob.core.windows.net'
            if parts.scheme!='https' or parts.netloc!=expected:fail('state-read-address','frozen Azure address differs')
            prefix='/'+backend['containerName']+'/'
            if not parts.path.startswith(prefix):fail('state-read-address','frozen Azure container differs')
            key=unquote(parts.path[len(prefix):])
            base=['az','storage','blob'];identity=['--account-name',backend['storageAccountName'],'--container-name',backend['containerName'],'--name',key,'--auth-mode','login','--only-show-errors','--output','json']
            metadata=run(base+['show']+identity);properties=metadata.get('properties',{})
            size=properties.get('contentLength');etag=properties.get('etag')
            argv=base+['download']+identity+['--file',str(path),'--if-match',etag,'--no-progress']
        if type(size) is not int or not 0<size<=MAX_STATE or not isinstance(etag,str) or not etag or len(etag)>1024 or any(ord(c)<32 for c in etag):
            fail('state-read-bound','private state object metadata exceeds its boundary')
        run(argv,json_output=False)
        if not path.is_file() or path.is_symlink() or path.stat().st_size!=size:
            fail('state-read-bytes','private state changed or differs from bounded metadata')
        path.chmod(0o600)
        try:state=json.loads(path.read_bytes(),object_pairs_hook=_pairs,parse_constant=_constant)
        except (ValueError,TypeError):fail('state-read-bytes','private native state is invalid')
        if not isinstance(state,dict) or state.get('version')!=4 or not isinstance(state.get('resources'),list):
            fail('state-read-bytes','private native state is unsupported')
        return state
