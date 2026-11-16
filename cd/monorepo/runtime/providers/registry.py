"""Protected native registry promotion. Credentials are stdin-only, identities native-verified."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import tempfile

from . import common as c


REPOSITORY = re.compile(r'[a-z0-9][a-z0-9.-]*/[a-z0-9][a-z0-9._/-]*')
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')

# Fixed reviewed Blueprint primitive, also executed by the legacy composite.
_spec = importlib.util.spec_from_file_location('blueprints_registry_publication',
    Path(__file__).resolve().parents[3] / 'deploy/container/publication.py')
_publication = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_publication)


def _publication_run(executor):
    return lambda argv, **kwargs: c.command(executor, argv, **kwargs)


def protected_context(environ):
    try:
        mappings = json.loads(environ.get('CLOUDOPSWORKS_REGISTRIES', '{}'))
    except ValueError as exc:
        raise c.ProviderError('registry-config', 'protected registry mapping is invalid JSON') from exc
    c.require(isinstance(mappings, dict), 'registry-config', 'protected registry mapping must be an object')
    for key, value in mappings.items():
        c.require(isinstance(key, str) and isinstance(value, dict) and set(value) == {'provider','repository'} and value['provider'] in ('aws','gcp','azure') and isinstance(value['repository'], str) and REPOSITORY.fullmatch(value['repository']) and '..' not in value['repository'].split('/'), 'registry-config', 'protected registry destination is invalid')
    return {'registries': mappings, 'registrySourceToken': environ.get('GH_TOKEN'),
            'registrySourceUser': environ.get('GITHUB_ACTOR')}


def inspect(executor, reference, *, authfile=None, anonymous=False):
    try:
        return _publication.inspect_digest(_publication_run(executor), reference,
                                           authfile=authfile, anonymous=anonymous)
    except _publication.PublicationError:
        raise c.ProviderError('registry-digest', 'registry did not return a valid content digest') from None


def anonymous_image(executor, image, digest):
    c.require(inspect(executor, image, anonymous=True) == digest, 'registry-digest', 'anonymous registry digest differs')
    return image


def ecr_destination(request, executor, account, repository):
    t = request['target']
    match = re.fullmatch(r'([0-9]{12})\.dkr\.ecr\.([a-z0-9-]+)\.(amazonaws\.com(?:\.cn)?)/([a-z0-9][a-z0-9._/-]*)', repository)
    c.require(match and match[1] == account and match[2] == t['region'], 'registry-identity', 'ECR destination must match actual AWS account and target region')
    name = match[4]
    data = c.command(executor, ['aws','ecr','describe-repositories','--registry-id',account,'--repository-names',name,'--region',t['region'],'--output','json'])
    repos = data.get('repositories', [])
    c.require(len(repos) == 1 and repos[0].get('registryId') == account and repos[0].get('repositoryUri') == repository and repos[0].get('repositoryArn','').split(':')[3:5] == [t['region'],account], 'registry-identity', 'ECR repository identity differs')
    return name


def destination(request, executor, context, repository, provider):
    """Read-only native resource resolution before any registry login/copy."""
    t = request['target']
    c.require(provider == t['provider'], 'registry-identity', 'protected registry provider differs from target')
    c.require(REPOSITORY.fullmatch(repository) and '..' not in repository.split('/'), 'registry-config', 'invalid native registry repository')
    account = context.get('expectedIdentity')
    c.require(account, 'registry-identity', 'protected resolved account identity is required for promotion')
    if provider == 'aws':
        name = ecr_destination(request, executor, account, repository)
        return {'provider':provider,'repository':repository,'name':name,'account':account}
    if provider == 'gcp':
        match = re.fullmatch(r'([a-z0-9-]+)-docker\.pkg\.dev/([^/]+)/([^/]+)',repository)
        c.require(match and match[2] in (t['project'],account), 'registry-identity', 'Artifact Registry project differs from resolved target')
        location, project, name = match.groups()
        data = c.command(executor, ['gcloud','artifacts','repositories','describe',name,'--location',location,'--project',t['project'],'--format=json'])
        expected = ['projects/' + project + '/locations/' + location + '/repositories/' + name for project in (t['project'], account)]
        c.require(data.get('name') in expected and data.get('format') == 'DOCKER' and data.get('mode','STANDARD_REPOSITORY') == 'STANDARD_REPOSITORY', 'registry-identity', 'existing writable Artifact Registry repository differs')
        return {'provider':provider,'repository':repository + '/' + request['componentId'],'name':name,'account':account}
    match = re.fullmatch(r'([a-z0-9]+)\.azurecr\.io/([a-z0-9][a-z0-9._/-]*)',repository)
    c.require(match, 'registry-identity', 'ACR destination must use a native registry hostname')
    name = match[1]
    data = c.command(executor, ['az','acr','show','--name',name,'--subscription',t['subscriptionId'],'--output','json'])
    c.require(data.get('id','').casefold().startswith('/subscriptions/' + account.casefold() + '/') and data.get('loginServer') == name + '.azurecr.io', 'registry-identity', 'ACR belongs to another subscription or hostname')
    return {'provider':provider,'repository':repository,'name':name,'account':account}


def login(executor, authfile, registry, username, password):
    c.require(isinstance(password,str) and password and not any(ch in password for ch in '\r\n'), 'registry-auth', 'native registry credential is unavailable')
    c.command(executor, ['skopeo','login','--authfile',str(authfile),'--username',username,'--password-stdin',registry], input=password, json_output=False)


def promote(request, executor, context, source, resolved):
    """Copy without rewriting manifests, verify destination tag digest, deploy by digest."""
    digest = request['artifact']['digest']
    c.require(source.endswith('@' + digest), 'registry-digest', 'promotion source must be immutable')
    repo, provider = resolved['repository'], resolved['provider']
    tag = 'sha256-' + digest.split(':')[1]
    with tempfile.TemporaryDirectory(prefix='registry-',dir=context['workDir']) as directory:
        authfile = Path(directory) / 'auth.json'
        authfile.write_text('{"auths":{}}')
        authfile.chmod(0o600)
        # GHCR source authentication is workflow identity, never PR metadata.
        if source.startswith('ghcr.io/') and context.get('registrySourceToken'):
            c.require(context.get('registrySourceUser'), 'registry-auth', 'GHCR source principal is unavailable')
            login(executor,authfile,'ghcr.io',context['registrySourceUser'],context['registrySourceToken'])
        if provider == 'aws':
            password = c.command(executor,['aws','ecr','get-login-password','--region',request['target']['region']],json_output=False).strip()
            user = 'AWS'
        elif provider == 'gcp':
            password = c.command(executor,['gcloud','auth','print-access-token'],json_output=False).strip()
            user = 'oauth2accesstoken'
        else:
            data = c.command(executor,['az','acr','login','--name',resolved['name'],'--subscription',request['target']['subscriptionId'],'--expose-token','--output','json'])
            c.require(data.get('loginServer') == repo.split('/')[0], 'registry-identity', 'ACR token hostname differs')
            password = data.get('accessToken')
            user = '00000000-0000-0000-0000-000000000000'
        login(executor,authfile,repo.split('/')[0],user,password)
        if request['target']['kind'] == 'aws.lambda':
            manifest = c.command(executor, ['skopeo','inspect','--authfile',str(authfile),'--raw','docker://' + source])
            c.require(manifest.get('mediaType') in ('application/vnd.oci.image.manifest.v1+json','application/vnd.docker.distribution.manifest.v2+json') and 'manifests' not in manifest, 'registry-format', 'Lambda requires a single-platform image manifest')
        try:
            _publication.publish(_publication_run(executor), transport='skopeo', source=source,
                repository=repo, tags=[tag], authfile=authfile, expected_digest=digest)
        except _publication.PublicationError:
            raise c.ProviderError('registry-digest', 'immutable registry publication digest differs') from None
        if provider == 'aws':
            data = c.command(executor,['aws','ecr','describe-images','--registry-id',resolved['account'],'--repository-name',resolved['name'],'--image-ids','imageTag=' + tag,'--region',request['target']['region'],'--output','json'])
            c.require(len(data.get('imageDetails',[])) == 1 and data['imageDetails'][0].get('imageDigest') == digest, 'registry-digest', 'native ECR digest readback differs')
    return repo + '@' + digest


def materialize(request, executor, context, image, *, lambda_resource=None):
    """No protected destination means public anonymous pull only, never assumed private access."""
    if not image: return image
    t = request['target']
    if lambda_resource is not None:
        current = lambda_resource.get('Code', {}).get('ResolvedImageUri', '')
        if '@sha256:' in current:
            repository = current.split('@')[0]
        else:
            mapping = context.get('registries', {}).get(t['authRef'])
            c.require(t.get('ownership','external') == 'managed' and not lambda_resource
                and isinstance(mapping,dict) and set(mapping)=={'provider','repository'} and mapping['provider']=='aws',
                'registry-identity','fresh managed Lambda requires the protected existing ECR binding')
            repository = mapping['repository']
        native = destination(request,executor,context,repository,'aws')
        return promote(request,executor,context,image,native)
    mapping = context.get('registries', {}).get(t['authRef'])
    if mapping:
        c.require(isinstance(mapping,dict) and set(mapping) == {'provider','repository'}, 'registry-config', 'protected registry map entry is invalid')
        native = destination(request,executor,context,mapping['repository'],mapping['provider'])
        return promote(request,executor,context,image,native)
    # Managed targets/Kubernetes receive no workflow GHCR pull credential. Prove public access.
    return anonymous_image(executor,image,request['artifact']['digest'])


def bind_resolution(request, resolution, executor, mappings):
    """Resolve protected destinations globally/read-only before any binding applies."""
    if request['artifact']['format'] != 'oci':
        return dict(resolution, registryConfig=None)
    t = request['target']
    mapping = mappings.get(t['authRef'])
    context = {'expectedIdentity':resolution['providerIdentity']}
    if t['kind'] == 'aws.lambda':
        current = resolution['resource'].get('Code',{}).get('ResolvedImageUri','')
        if '@sha256:' in current:
            native = destination(request,executor,context,current.split('@')[0],'aws')
            mapping = None  # Owned updates preserve the existing native repository.
        else:
            c.require(t.get('ownership','external')=='managed' and not resolution['existing']['exists']
                and isinstance(mapping,dict) and set(mapping)=={'provider','repository'} and mapping['provider']=='aws',
                'registry-identity','fresh managed Lambda requires the protected existing ECR binding')
            native = destination(request,executor,context,mapping['repository'],'aws')
    elif mapping:
        native = destination(request,executor,context,mapping['repository'],mapping['provider'])
    else:
        native = None
    return dict(resolution, registryConfig={'mapping':mapping,'destination':native})


def assert_mapping(request, resolution, mappings):
    expected = None if request['artifact']['format'] != 'oci' else mappings.get(request['target']['authRef'])
    if request['target']['kind']=='aws.lambda' and resolution.get('existing',{}).get('exists',True):expected=None
    config = resolution.get('registryConfig')
    c.require((config or {}).get('mapping') == expected, 'registry-config-changed', 'protected registry destination changed after read-only resolution')
