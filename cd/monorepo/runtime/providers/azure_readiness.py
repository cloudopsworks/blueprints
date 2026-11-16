"""Read-only Azure native identity/configuration and serving verification.

Uses the selected Azure CLI through the existing bounded command adapter. No
provisioning, ListKeys, publishing credentials, SAS acquisition or SDK fallback.
ZIP proof joins exact owned blob bytes and successful owned ARM extension
operation with serving build identity; deployment names alone are not evidence.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
import tempfile
from urllib.parse import quote, urlsplit

from . import common as c
from .azure import admin_probe, app_args, cli

# Field semantics: Microsoft Learn Container Apps revisions / App Service GET /
# resource deployment operations. FX encoding mirrors captured provider source
# azure_source.json appservice_helpers_fx_strings.go (commit 63106056a9395332…).


def _id(value):
    return c.resource_id(value).rstrip('/')


def _arm(t, provider, name):
    return '/subscriptions/' + t['subscriptionId'] + '/resourceGroups/' + t['resourceGroup'] + '/providers/' + provider + '/' + name


def _owned(outputs, expected):
    values = outputs.get('owned_ids')
    c.require(isinstance(values, list) and all(isinstance(value, str) for value in values),
              'iac-readiness-output', 'Azure root requires normalized owned_ids')
    c.require(len(values) == len(expected) and {value if value.startswith('https://') else _id(value) for value in values} == {value if value.startswith('https://') else _id(value) for value in expected},
              'iac-readiness-output', 'Azure root output identities differ from exact intended resources')


def _same(actual, expected):
    c.require(_id(actual) == _id(expected), 'resource-identity', 'Azure native resource identity differs')


def _owner(live, ctx):
    c.require(live.get('tags', {}).get('cloudopsworks-owner') == ctx['iacOwnerDigest'],
              'resource-owner', 'Azure native owner differs from frozen state')


def _identity(live, t):
    identity = live.get('identity', {})
    assigned = identity.get('userAssignedIdentities', {})
    c.require(identity.get('type') == 'UserAssigned' and isinstance(assigned, dict)
              and {_id(value) for value in assigned} == {_id(t['iac']['identityId'])},
              'intended-identity', 'Assigned managed identity differs')


def _host(live):
    host = live.get('defaultHostName')
    c.require(isinstance(host, str) and host in live.get('enabledHostNames', []) and '.scm.' not in host,
              'probe-origin', 'Exact app/slot serving hostname is unavailable')
    return c.origin('https://' + host, host_suffix='.azurewebsites.net')


def _package(r, ex, ctx, ids, site):
    """Independent AAD blob GET/hash plus exact native deployment operation."""
    t = r['target']; storage = t['iac']['packageStorage']; digest = r['artifact']['digest'][7:]
    account = storage['accountId'].split('/')[-1]
    name = storage['prefix'].strip('/') + '/' + digest + ('/released-package.zip' if t.get('hostingPlan') == 'flex-consumption' else '/main.zip')
    blob = 'https://' + account + '.blob.core.windows.net/' + storage['container'] + '/' + name
    parent = site.split('/slots/')[0]
    deployment = 'cow-' + hashlib.sha256((parent + '/' + t['slot']).encode()).hexdigest()[:16] + '-' + digest[:24]
    deployment_id = _arm(t, 'Microsoft.Resources/deployments', deployment)
    _owned({'owned_ids': ids}, [site, blob, deployment_id])
    properties = cli(ex, t, 'storage', 'blob', 'show', '--account-name', account, '--container-name', storage['container'], '--name', name, '--auth-mode', 'login')
    size = r['artifact']['sizeBytes']
    etag = properties.get('properties', {}).get('etag')
    c.require(isinstance(etag, str) and etag and not re.search(r'[\r\n]', etag), 'intended-package', 'Immutable package snapshot ETag is unavailable')
    c.require(properties.get('name') == name and properties.get('properties', {}).get('contentLength') == size,
              'intended-package', 'Exact immutable package blob size/name differs')
    work = Path(ctx['workDir'])
    c.require(work.is_dir() and not work.is_symlink(), 'intended-package', 'Trusted private package verification directory is required')
    with tempfile.TemporaryDirectory(prefix='azure-package-read-', dir=work) as temporary:
        path = Path(temporary) / 'package.zip'
        cli(ex, t, 'storage', 'blob', 'download', '--account-name', account, '--container-name', storage['container'], '--name', name,
            '--auth-mode', 'login', '--file', str(path), '--no-progress', '--if-match', etag)
        c.require(path.is_file() and not path.is_symlink() and path.stat().st_size == size,
                  'intended-package', 'Downloaded immutable package size differs')
        sha = hashlib.sha256()
        with path.open('rb') as stream:
            while chunk := stream.read(1024 * 1024):
                sha.update(chunk)
        c.require(sha.hexdigest() == digest, 'intended-package', 'Downloaded package does not match the immutable artifact digest')
    deployed = cli(ex, t, 'deployment', 'group', 'show', '--resource-group', t['resourceGroup'], '--name', deployment)
    _same(deployed.get('id'), deployment_id)
    c.require(deployed.get('properties', {}).get('provisioningState') == 'Succeeded',
              'intended-package', 'Owned immutable package ARM deployment has not succeeded')
    operations = cli(ex, t, 'deployment', 'operation', 'group', 'list', '--resource-group', t['resourceGroup'], '--name', deployment)
    extension = site + '/extensions/' + ('onedeploy' if t.get('hostingPlan') == 'flex-consumption' else 'ZipDeploy')
    targets = [item.get('properties', {}) for item in operations if item.get('properties', {}).get('targetResource')]
    c.require(bool(targets) and all(_id(item['targetResource'].get('id')) == _id(extension) and item.get('provisioningState') == 'Succeeded' for item in targets),
              'intended-package', 'Successful exact app/slot package extension operation is missing')


def _settings(ex, t, group):
    # Return only the nonsecret fields this verifier needs, not arbitrary app secrets.
    names = ('FUNCTIONS_WORKER_RUNTIME', 'WEBSITE_RUN_FROM_PACKAGE', 'WEBSITE_NODE_DEFAULT_VERSION',
             'WEBSITES_PORT', 'AzureWebJobsStorage__credential', 'FUNCTIONS_EXTENSION_VERSION')
    query = '[?' + ' || '.join("name=='" + name + "'" for name in names) + ']'
    pairs = cli(ex, t, group, 'config', 'appsettings', 'list', *app_args(t), '--query', query)
    c.require(isinstance(pairs, list) and len({item['name'] for item in pairs}) == len(pairs),
              'intended-runtime', 'App settings are ambiguous')
    return {item['name']: item['value'] for item in pairs}


def _runtime(r, cfg, settings):
    t = r['target']; linux = t.get('os', 'linux') == 'linux'
    if t['kind'] == 'azure.functions':
        worker = t['workerRuntime']; version = t.get('runtime', '').split('|')[-1]
        c.require(settings.get('FUNCTIONS_WORKER_RUNTIME') == worker,
                  'intended-runtime', 'Function worker runtime differs')
        if linux:
            expected = '' if worker == 'custom' else {'dotnet-isolated': 'DOTNET-ISOLATED', 'powershell': 'POWERSHELL'}.get(worker, worker.upper()) + '|' + version
            c.require(cfg.get('linuxFxVersion', '') == expected, 'intended-runtime', 'Function runtime stack differs')
        else:
            key = {'node': 'nodeVersion', 'java': 'javaVersion', 'powershell': 'powerShellVersion', 'dotnet': 'netFrameworkVersion', 'dotnet-isolated': 'netFrameworkVersion', 'custom': None}[worker]
            if key:
                actual = settings.get('WEBSITE_NODE_DEFAULT_VERSION') if worker == 'node' else cfg.get(key)
                c.require(actual in (version, 'v' + version), 'intended-runtime', 'Windows function runtime stack differs')
    else:
        runtime = t.get('runtime', '')
        c.require('|' in runtime, 'intended-runtime', 'Explicit App Service runtime is required')
        name, version = runtime.split('|', 1)
        if linux:
            # The reviewed root selects JAVA server and equal Java/server version.
            expected = name.upper() + '|' + version
            if name.upper() == 'JAVA':
                suffix = 'jre8' if version == '8' else ('java' + version if version in ('11', '17', '21', '25') else version)
                expected += '-' + suffix
            c.require(cfg.get('linuxFxVersion') == expected, 'intended-runtime', 'App Service runtime stack differs')
        else:
            actual = settings.get('WEBSITE_NODE_DEFAULT_VERSION') if name.upper() == 'NODE' else cfg.get({'JAVA': 'javaVersion', 'DOTNET': 'netFrameworkVersion'}[name.upper()])
            c.require(actual in (version, 'v' + version), 'intended-runtime', 'Windows App Service runtime stack differs')


def _app(r, ex, ctx, outputs, image):
    t = r['target']; function = t['kind'] == 'azure.functions'; flex = t.get('hostingPlan') == 'flex-consumption'
    c.require(not flex or (function and t['slot'] == 'production' and t.get('os', 'linux') == 'linux' and image is None and t.get('packageMode') == 'zip'), 'intended-runtime', 'Flex supports only the exact Linux production ZIP mode')
    group = 'functionapp' if function else 'webapp'
    parent = _arm(t, 'Microsoft.Web/sites', t['appName'])
    site = parent if t['slot'] == 'production' else parent + '/slots/' + t['slot']
    ids = outputs.get('owned_ids')
    c.require(isinstance(ids, list), 'iac-readiness-output', 'Azure root requires owned identities')
    if image:
        _owned(outputs, [site])
    else:
        c.require(t.get('packageMode') == 'zip' and r['artifact']['format'] == 'zip', 'intended-package', 'App ZIP mode differs')
        _package(r, ex, ctx, ids, site)
    def check():
        live = cli(ex, t, group, 'show', *app_args(t))
        _same(live.get('id'), site); _owner(live, ctx); _identity(live, t)
        c.require(('functionapp' in live.get('kind', '').lower().split(',')) == function, 'intended-runtime', 'Azure app resource family differs')
        c.require(_id(live.get('serverFarmId', live.get('appServicePlanId'))) == _id(t['iac']['servicePlanId']), 'intended-plan', 'App/slot service plan differs')
        c.require(live.get('reserved') is (t.get('os', 'linux') == 'linux'), 'intended-runtime', 'App/slot operating system differs')
        cfg = {} if flex else cli(ex, t, group, 'config', 'show', *app_args(t))
        settings = {} if flex else _settings(ex, t, group)
        if function and not flex:
            c.require(settings.get('FUNCTIONS_WORKER_RUNTIME') == t['workerRuntime'] and settings.get('AzureWebJobsStorage__credential') == 'managedidentity' and settings.get('FUNCTIONS_EXTENSION_VERSION') == '~4', 'intended-runtime', 'Function worker or runtime storage identity mode differs')
        if image:
            c.require(t.get('packageMode') == 'image' and t.get('os', 'linux') == 'linux' and cfg.get('linuxFxVersion') == 'DOCKER|' + image,
                      'intended-image', 'App/slot does not reference exact immutable image')
            c.require(cfg.get('acrUseManagedIdentityCreds') is True, 'intended-image', 'Registry access must use managed identity')
        elif flex:
            config = live.get('functionAppConfig', {})
            version = t.get('runtime', '').split('|')[-1]
            c.require(config.get('runtime') == {'name': t['workerRuntime'], 'version': version}, 'intended-runtime', 'Flex runtime differs')
            storage = config.get('deployment', {}).get('storage', {})
            expected = 'https://' + t['iac']['storageAccountId'].split('/')[-1] + '.blob.core.windows.net/' + t['iac']['deploymentContainer']
            c.require(storage.get('type') == 'blobContainer' and storage.get('value', '').rstrip('/') == expected,
                      'intended-package', 'Flex deployment storage differs')
            authentication = storage.get('authentication', {})
            c.require(authentication.get('type') == 'UserAssignedIdentity' and _id(authentication.get('userAssignedIdentityResourceId')) == _id(t['iac']['identityId']), 'intended-identity', 'Flex deployment storage managed identity differs')
        else:
            _runtime(r, cfg, settings)
            if function:
                c.require(settings.get('WEBSITE_RUN_FROM_PACKAGE') == '1', 'intended-package', 'Function ZIP mode differs')
        if not function:
            if image:
                c.require(settings.get('WEBSITES_PORT') == str(r['workload']['port']), 'intended-config', 'Container App Service port differs')
            c.require(cfg.get('healthCheckPath') == r['workload']['healthPath'], 'intended-config', 'App health path differs')
        return live if live.get('state') == 'Running' and live.get('enabled') is True and live.get('httpsOnly') is True else False
    live = c.poll(r, ctx, check)
    base = _host(live)
    probe = t['readiness']['probe']
    if function and probe['kind'] == 'azure-function-admin':
        admin_probe(r, ex, ctx, live, base)
    else:
        c.verify_build_identity(r, ex, ctx, base)
        c.serving(r, ex, ctx, base)
    return base


def _container(r, ex, ctx, outputs, image):
    t = r['target']; identity = _arm(t, 'Microsoft.App/containerApps', t['appName'])
    _owned(outputs, [identity])
    revision = t['appName'] + '--v-' + r['artifact']['digest'][7:27]
    def check():
        live = cli(ex, t, 'containerapp', 'show', '--resource-group', t['resourceGroup'], '--name', t['appName'])
        _same(live.get('id'), identity); _owner(live, ctx); _identity(live, t)
        properties = live.get('properties', {})
        c.require(_id(properties.get('managedEnvironmentId')) == _id(t['iac']['managedEnvironmentId']), 'intended-environment', 'Container Apps environment differs')
        template = properties.get('template', {}); containers = template.get('containers', [])
        c.require(len(containers) == 1 and containers[0].get('name') == t['containerName'] and containers[0].get('image') == image,
                  'intended-image', 'Container App image/container differs')
        probes = containers[0].get('probes', [])
        c.require(all(any(probe.get('type') == kind and probe.get('httpGet', {}).get('path') == r['workload']['healthPath'] and probe['httpGet'].get('port') == r['workload']['port'] for probe in probes) for kind in ('Liveness', 'Readiness')),
                  'intended-config', 'Container App probes differ')
        ingress = properties.get('configuration', {}).get('ingress', {}); traffic = ingress.get('traffic', [])
        c.require(properties.get('configuration', {}).get('activeRevisionsMode') == 'Single' and ingress.get('external') is True and ingress.get('targetPort') == r['workload']['port'], 'intended-config', 'Container App revision/ingress configuration differs')
        ready = properties.get('provisioningState') == 'Succeeded' and properties.get('latestRevisionName') == revision and properties.get('latestReadyRevisionName') == revision
        ready = ready and len(traffic) == 1 and traffic[0].get('weight') == 100 and traffic[0].get('revisionName', revision) == revision and (traffic[0].get('revisionName') == revision or traffic[0].get('latestRevision') is True)
        native = cli(ex, t, 'containerapp', 'revision', 'show', '--resource-group', t['resourceGroup'], '--name', t['appName'], '--revision', revision)
        _same(native.get('id'), identity + '/revisions/' + revision)
        rp = native.get('properties', {})
        ready = ready and rp.get('active') is True and rp.get('healthState') == 'Healthy' and rp.get('provisioningState') == 'Provisioned' and rp.get('trafficWeight') == 100 and len(rp.get('template', {}).get('containers', [])) == 1 and rp['template']['containers'][0].get('name') == t['containerName'] and rp['template']['containers'][0].get('image') == image
        return live if ready else False
    live = c.poll(r, ctx, check)
    environment = cli(ex, t, 'resource', 'show', '--ids', t['iac']['managedEnvironmentId'])
    _same(environment.get('id'), t['iac']['managedEnvironmentId'])
    domain = environment.get('properties', {}).get('defaultDomain')
    host = live['properties']['configuration']['ingress'].get('fqdn')
    c.require(isinstance(domain, str) and isinstance(host, str) and host == t['appName'] + '.' + domain,
              'probe-origin', 'Container App hostname differs from exact managed environment')
    base = c.origin('https://' + host, host_suffix='.azurecontainerapps.io')
    c.verify_build_identity(r, ex, ctx, base)
    return c.serving(r, ex, ctx, base)


def _verify(r, ex, ctx, outputs, *, image=None, directory=None):
    """Verify normalized native outputs and canonical DeploymentRequest; no writes."""
    t = r['target']; kind = t['kind']
    c.require(kind in ('azure.containerapps', 'azure.appservice', 'azure.functions', 'azure.blob-static', 'azure.apim') and t['provider'] == 'azure', 'provider', 'Azure normal readiness family is required')
    c.require(str(ctx.get('expectedIdentity', '')).casefold() == t['subscriptionId'].casefold(), 'account-mismatch', 'Verified Azure subscription differs')
    c.require(re.fullmatch(r'sha256:[0-9a-f]{64}', ctx.get('iacOwnerDigest', '')), 'resource-owner', 'Verified native state owner digest is required')
    if image is not None:
        c.require(r['artifact']['format'] == 'oci' and image.endswith('@' + r['artifact']['digest']) and not re.search(r'[\s?#]', image) and '://' not in image,
                  'intended-image', 'Exact immutable OCI reference is required')
    if kind == 'azure.containerapps':
        c.require(image is not None, 'intended-image', 'Container App requires exact immutable image')
        return _container(r, ex, ctx, outputs, image)
    if kind in ('azure.appservice', 'azure.functions'):
        return _app(r, ex, ctx, outputs, image)
    if kind == 'azure.blob-static':
        c.require(isinstance(directory, Path) and directory.is_dir() and not directory.is_symlink(), 'static-empty', 'Verified extracted static directory is required')
        c.require(t.get('container') == '$web' and re.fullmatch(r'[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*', t['prefix']), 'static-path', 'Static content must remain inside the exact owned website prefix')
        prefix = t['prefix'].strip('/')
        files = [path.relative_to(directory).as_posix() for path in directory.rglob('*') if path.is_file()]
        c.require(all(not path.is_symlink() for path in directory.rglob('*')), 'static-path', 'Static content cannot contain symlinks')
        expected = ['https://' + t['account'] + '.blob.core.windows.net/$web/' + prefix + '/' + quote(name, safe='/') for name in files + ['.cloudopsworks-release.json']]
        _owned(outputs, expected)
        account = cli(ex, t, 'storage', 'account', 'show', '--resource-group', t['resourceGroup'], '--name', t['account'])
        _same(account.get('id'), _arm(t, 'Microsoft.Storage/storageAccounts', t['account']))
        endpoint = account.get('primaryEndpoints', {}).get('web', '')
        host = urlsplit(endpoint).hostname
        c.require(isinstance(host, str) and host.startswith(t['account'] + '.'), 'probe-origin', 'Static website endpoint differs from exact account')
        base = c.origin(endpoint, host_suffix='.web.core.windows.net')
        return c.verify_static(r, ex, ctx, directory, base, prefix)
    c.require(r['artifact']['kind'] == 'openapi' and r['artifact']['format'] in ('openapi-json', 'openapi-yaml'), 'intended-api', 'APIM requires the verified OpenAPI artifact')
    api = _arm(t, 'Microsoft.ApiManagement/service', t['serviceName']) + '/apis/' + t['apiId']
    ids = outputs.get('owned_ids', [])
    c.require(len(ids) == 1 and _id(ids[0]) in (_id(api), _id(api + ';rev=1')), 'iac-readiness-output', 'Owned APIM API identity differs')
    live = cli(ex, t, 'apim', 'api', 'show', '--resource-group', t['resourceGroup'], '--service-name', t['serviceName'], '--api-id', t['apiId'])
    c.require(_id(live.get('id')).split(';rev=')[0] == _id(api) and str(live.get('apiRevision')) == '1' and live.get('isCurrent') is True and live.get('path') == t['apiPath'] and live.get('protocols') == ['https'] and live.get('subscriptionRequired') is False,
              'intended-api', 'APIM current revision/path/protocol configuration differs')
    service = cli(ex, t, 'apim', 'show', '--resource-group', t['resourceGroup'], '--name', t['serviceName'])
    _same(service.get('id'), api.rsplit('/apis/', 1)[0])
    base = c.origin(service.get('gatewayUrl', ''), host_suffix='.azure-api.net')
    c.require(urlsplit(base).hostname == t['serviceName'] + '.azure-api.net', 'probe-origin', 'APIM gateway hostname differs from exact service')
    return c.serving(r, ex, ctx, base, path_prefix=t['apiPath'])


def verify(r, ex, ctx, outputs, *, image=None, directory=None):
    """Fail closed on malformed native data without exposing raw values/tokens."""
    try:
        return _verify(r, ex, ctx, outputs, image=image, directory=directory)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise c.ProviderError('native-response', 'Azure native readiness evidence is incomplete or malformed') from None
