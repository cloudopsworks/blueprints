"""Shared fail-closed staging, native polling and bounded serving verification."""
from __future__ import annotations

import json
from pathlib import Path
import re
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import contracts
from executor import checked, Runner


class ProviderError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def require(condition, code='native-readiness', message='intended deployment is not ready'):
    if not condition:
        raise ProviderError(code, message)


def command(executor, argv, *, json_output=True, **kwargs):
    raw = checked(executor, argv, **kwargs)
    if not json_output:
        return raw
    try:
        require(len(raw.encode()) <= 4 * 1024 * 1024, 'native-response', 'provider JSON exceeds bound')
        return json.loads(raw, object_pairs_hook=contracts._pairs, parse_constant=contracts._constant)
    except (ValueError, TypeError) as exc:
        raise ProviderError('native-response', 'provider returned invalid JSON') from exc


def version(request):
    # Stable, bounded native revision identity; semver punctuation is not portable.
    return 'r-' + request['idempotencyKey'].split(':')[1][:24]


def result(request, *, url=None, error=None):
    value = dict(apiVersion='cloudopsworks.io/v1', kind='DeploymentResult',
        repository=request['repository'], componentId=request['componentId'],
        targetId=request['target']['id'], releaseVersion=request['releaseVersion'],
        artifactDigest=request['artifact']['digest'], targetConfigDigest=request['target']['configDigest'],
        idempotencyKey=request['idempotencyKey'], status='failed' if error else 'succeeded',
        ready=not bool(error), resourceUrl=url if not error else None,
        error=None if not error else dict(code=getattr(error, 'code', 'provider-failure'),
            message='Native deployment or serving verification failed', retryable=False))
    contracts.validate_record(value)
    return value


def execute(request, executor, resolve, apply, *, context=None, resolved=None):
    context = context or {}
    try:
        # Shape/runtime compatibility validation happens before any credentialed process.
        validate_request(request)
        require(callable(context.get('iac_authorize')), 'iac-authorization-required',
                'independent protected IaC authorization is required before provider access')
        with tempfile.TemporaryDirectory(prefix='monorepo-provider-', dir=context.get('workDir')) as root:
            local = dict(context, workDir=Path(root))
            local['overallDeadline'] = local.get('clock', time.monotonic)() + request['target']['readiness']['deadlineSeconds']
            payload, directory, image = stage(request, local)
            require(callable(context.get('iac_resolve')), 'iac-preflight-required',
                    'independent native inventory and historical state preflight is required')
            fresh = context['iac_resolve'](request, executor)
            if resolved is not None:
                require(fresh['providerIdentity'] == resolved['providerIdentity'] and
                        fresh['resourceClaims'] == resolved['resourceClaims'], 'identity-changed',
                        'resolved account or resource changed before mutation')
            if context.get('expectedIdentity') is not None:
                require(fresh['providerIdentity'] == context['expectedIdentity'], 'account-mismatch', 'unexpected cloud account')
            local['expectedIdentity'] = fresh['providerIdentity']
            url = apply(request, DeadlineExecutor(executor, local), fresh, local, payload, directory, image)
            require(local.get('clock', time.monotonic)() <= local['overallDeadline'], 'readiness-timeout', 'deployment exceeded overall readiness deadline')
        return result(request, url=url)
    except Exception as exc:
        # Provider diagnostics, argv, secret values, bodies and raw logs never cross wire.
        return result(request, error=exc)


def stage(request, context):
    artifact = request['artifact']
    if artifact['location']['kind'] == 'oci':
        ref = artifact['location']['reference']
        require(ref.endswith('@' + artifact['digest']), 'artifact-digest', 'container reference must be immutable')
        return None, None, ref
    path = context.get('artifactPath')
    require(path is not None, 'artifact-missing', 'trusted downloaded artifact path is required')
    path = Path(path)
    contracts.validate_artifact(path, artifact)
    if artifact['format'] == 'oci':
        # Staged OCI bytes have no registry ref in the frozen manifest. Only
        # protected publication/readback supplies this process-local value; the
        # request descriptor remains unchanged for independent authorization.
        image = context.get('artifactImageReference')
        require(isinstance(image, str) and image.endswith('@' + artifact['digest'])
                and re.fullmatch(r'[a-z0-9][a-z0-9.:-]*/[a-z0-9._/-]+@sha256:[0-9a-f]{64}', image),
                'artifact-image-publication', 'staged OCI requires verified immutable registry publication')
        return path.resolve(), None, image
    directory = context['workDir'] / 'payload'
    directory.mkdir()
    if artifact['format'] == 'zip':
        with zipfile.ZipFile(path) as archive:
            context['_entryModes'] = {entry.filename: entry.external_attr >> 16 for entry in archive.infolist()}
            archive.extractall(directory)  # validated entries: no symlink/traversal/duplicates
    elif artifact['format'] == 'tar.gz':
        with tarfile.open(path, 'r:gz') as archive:
            archive.extractall(directory, filter='data')
    if artifact['kind'] == 'openapi':
        verify_api_route(path, request['target']['readiness']['probe'])
    if artifact['kind'] == 'static':
        require(not (directory / '.cloudopsworks-release.json').exists(), 'reserved-path', 'static marker path is reserved')
    return path.resolve(), directory, None


def poll(request, context, check):
    readiness = request['target']['readiness']
    clock = context.get('clock', time.monotonic)
    sleep = context.get('sleep', time.sleep)
    deadline = context.get('overallDeadline', clock() + readiness['deadlineSeconds'])
    while True:
        if clock() > deadline:
            raise ProviderError('readiness-timeout', 'deployment exceeded readiness deadline')
        try:
            value = check()
            if value and clock() <= deadline:
                return value
        except ProviderError as exc:
            if exc.code != 'native-readiness':
                raise
        if clock() >= deadline:
            raise ProviderError('readiness-timeout', 'deployment did not become ready before deadline')
        sleep(min(readiness['intervalSeconds'], max(0, deadline - clock())))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ProviderError('probe-redirect', 'serving probes cannot follow redirects')


def http_request(url, *, method='GET', body='', headers=None, timeout=10):
    request = urllib.request.Request(url, data=(body.encode() if isinstance(body, str) else body) if method != 'GET' else None,
                                     headers=headers or {}, method=method)
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
            raw = response.read(1024 * 1024 + 1)
            require(len(raw) <= 1024 * 1024, 'probe-size', 'probe response exceeds bound')
            return response.status, raw
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(1024 * 1024)


def origin(value, *, host_suffix=None, allow_http=False, loopback=False):
    parsed = urllib.parse.urlsplit(value)
    require(parsed.scheme == 'https' or (allow_http and parsed.scheme == 'http'), 'probe-origin', 'origin must use HTTPS')
    require(parsed.hostname and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment,
            'probe-origin', 'invalid native origin')
    require(not parsed.path or parsed.path == '/', 'probe-origin', 'native origin contains an unexpected path')
    if loopback:
        require(parsed.hostname == '127.0.0.1', 'probe-origin', 'only owned loopback forwarding is permitted')
    else:
        require(parsed.port in (None, 443) or (allow_http and parsed.port == 80), 'probe-origin', 'unexpected native port')
        require(host_suffix is None or parsed.hostname.endswith(host_suffix), 'probe-origin', 'native hostname does not match provider')
    return value.rstrip('/')


def serving(request, executor, context, base, *, allow_http=False, static=False, path_prefix=''):
    probe = request['target']['readiness']['probe']
    base = origin(base, allow_http=allow_http, loopback=base.startswith('http://127.0.0.1:'))
    headers = {}
    if not static:
        auth = probe['auth']
        if auth['kind'] == 'secret-header':
            secret = context.get('secrets', {}).get(auth['secretRef'])
            require(isinstance(secret, str) and secret and '\r' not in secret and '\n' not in secret, 'probe-auth', 'protected probe secret is unavailable')
            headers[auth['header']] = auth['prefix'] + secret
        elif auth['kind'] == 'gcp-id-token':
            token = command(executor, ['gcloud', 'auth', 'print-identity-token', '--audiences=' + base], json_output=False).strip()
            require(bool(token) and '\n' not in token, 'probe-auth', 'invalid identity token')
            headers['Authorization'] = 'Bearer ' + token
    if allow_http and not base.startswith('http://127.0.0.1:'):
        require(not headers and (static or (probe['method'] == 'GET' and not probe['requestBody'])), 'probe-auth', 'native HTTP is credential-free only')
    path = probe['path'] if probe.get('path') is not None else request['workload']['healthPath']
    contracts._relative_http_path(path)
    url = base + '/' + path_prefix.strip('/') + path if path_prefix else base + path
    transport = context.get('http', http_request)
    def check():
        try:
            status, body = transport(url, method='GET' if static else probe['method'],
                body='' if static else probe['requestBody'], headers=headers,
                timeout=remaining(context))
            body = body.encode() if isinstance(body, str) else body
            return status == (200 if static else probe['expectedStatus']) and (static or probe['responseContains'].encode() in body)
        except (OSError, TimeoutError):
            return False
    poll(request, context, check)
    return base


def marker(request):
    return json.dumps({'artifactDigest': request['artifact']['digest'], 'releaseVersion': request['releaseVersion'],
                       'idempotencyKey': request['idempotencyKey']}, sort_keys=True, separators=(',', ':')).encode()


def verify_static(request, executor, context, directory, base, prefix):
    # Every uploaded byte plus marker must be externally served; stale marker alone cannot pass.
    transport = context.get('http', http_request)
    files = [(p.relative_to(directory).as_posix(), p.read_bytes()) for p in sorted(directory.rglob('*')) if p.is_file()]
    require(bool(files), 'static-empty', 'static artifact has no files')
    files.append(('.cloudopsworks-release.json', marker(request)))
    def check():
        for name, expected in files:
            url = base.rstrip('/') + '/' + '/'.join(filter(None, [prefix.strip('/'), urllib.parse.quote(name, safe='/')]))
            status, actual = transport(url, method='GET', body='', headers={}, timeout=remaining(context))
            actual = actual.encode() if isinstance(actual, str) else actual
            if status != 200 or actual != expected:
                return False
        return True
    poll(request, context, check)
    serving(request, executor, context, base, allow_http=base.startswith('http:'), static=True, path_prefix=prefix)
    return base


def resource_id(value):
    require(isinstance(value, str) and value and not any(c.isspace() for c in value), 'resource-identity', 'native resource has no canonical identity')
    return value.casefold()


def verify_api_route(path, probe):
    """Require a concrete deployed OpenAPI operation, never an unrelated health URL."""
    text = path.read_text(encoding='utf-8')
    require(len(text) <= 4 * 1024 * 1024, 'spec-size', 'OpenAPI exceeds bound')
    try:
        spec = json.loads(text)
        paths = {route: set(value) for route, value in spec.get('paths', {}).items()}
    except json.JSONDecodeError:
        # Bounded YAML OpenAPI subset: ordinary block paths and operation keys.
        # Complex aliases/tags/flow mappings require canonical JSON publication.
        require(not re.search(r'(^|\s)[&*!]|^\s*<<:', text, re.M), 'spec-format', 'OpenAPI YAML aliases/tags are unsupported; publish JSON')
        paths = {}; current = None; in_paths = False
        for line in text.splitlines():
            if line == 'paths:': in_paths = True; continue
            if in_paths and line and not line[0].isspace(): in_paths = False
            if not in_paths: continue
            route = re.fullmatch(r'  [\'\"]?(/[^:]*?)[\'\"]?:\s*', line)
            if route: current = route.group(1); paths[current] = set(); continue
            method = re.fullmatch(r'    (get|post|put|patch|delete|head|options):\s*', line)
            if method and current: paths[current].add(method.group(1))
    route = probe['path']
    require(route is not None, 'spec-route', 'API probes require an explicit operation route')
    def matches(pattern):
        expression = re.escape(pattern)
        expression = re.sub(r'\\\{[^}]+\\\}', '[^/]+', expression)
        return re.fullmatch(expression, route) is not None
    require(any(matches(name) and probe['method'].lower() in methods for name, methods in paths.items()),
            'spec-route', 'probe path/method is not a deployed OpenAPI operation')


def build_identity(request):
    """Non-self-referential identity baked before immutable package hashing."""
    return {key: request['artifact'][key] for key in ('sourceSha', 'builtVersion')} | {'componentId': request['componentId']}


def verify_build_identity(request, executor, context, base):
    """Running/config alone cannot prove the intended App Service/Flex bytes serve."""
    probe = request['target']['readiness']['probe']
    headers = {}
    auth = probe.get('auth', {'kind': 'none'})
    if auth['kind'] == 'secret-header':
        secret = context.get('secrets', {}).get(auth['secretRef'])
        require(isinstance(secret, str) and secret and not any(c in secret for c in '\r\n'), 'probe-auth', 'protected marker secret unavailable')
        headers[auth['header']] = auth['prefix'] + secret
    transport = context.get('http', http_request)
    def check():
        status, raw = transport(base + '/.well-known/cloudopsworks-build.json', method='GET', body='', headers=headers, timeout=remaining(context))
        if status != 200: return False
        try:
            return contracts.load_record(raw if isinstance(raw, (str, bytes)) else b'') == build_identity(request)
        except ValueError:
            return False
    poll(request, context, check)


def validate_request(request):
    contracts.validate_record(request)
    def resource_values(value):
        if isinstance(value, str):
            require(not value.startswith('-'), 'unsafe-resource', 'resource values cannot begin with an option prefix')
        elif isinstance(value, dict):
            for key, item in value.items():
                if key != 'readiness': resource_values(item)
    resource_values(request['target'])
    target, artifact = request['target'], request['artifact']
    if target['kind'] in ('aws.beanstalk', 'aws.lambda', 'azure.appservice', 'azure.functions') and artifact['format'] != 'oci':
        require(artifact['format'] == 'zip', 'artifact-format', 'native ZIP mode requires actual ZIP payload')
    if artifact['format'] == 'oci':
        require(artifact['location']['kind'] in ('oci','actions-artifact','release-asset'), 'artifact-location',
            'native image deployment requires a durable immutable source descriptor')
        # A staged descriptor deliberately stays unchanged. stage() separately
        # requires the protected publisher's digest-bound process-local image
        # reference before the sole IaC mutation boundary can execute.
    return request


def remaining(context, maximum=10):
    left = context.get('overallDeadline', float('inf')) - context.get('clock', time.monotonic)()
    require(left > 0, 'readiness-timeout', 'deployment exceeded readiness deadline')
    return min(maximum, left)


class DeadlineExecutor:
    """Use the existing production Runner with each command's remaining budget."""
    def __init__(self, executor, context):
        self.executor, self.context = executor, context
    def run(self, argv, **kwargs):
        budget = remaining(self.context, float('inf'))
        executor = self.executor
        if type(executor) is Runner:
            executor = Runner(timeout=min(executor.timeout, budget), output_limit=executor.output_limit,
                inherit_environment=executor.inherit_environment)
        elif callable(getattr(executor,'bounded',None)):
            executor=executor.bounded(budget)
        output = executor.run(argv, **kwargs)
        remaining(self.context)
        return output


def cleanup_executor(executor):
    """A separate bounded cleanup budget cannot turn failed serving into success."""
    underlying = executor.executor if isinstance(executor, DeadlineExecutor) else executor
    return Runner(timeout=min(underlying.timeout, 10), output_limit=underlying.output_limit,inherit_environment=underlying.inherit_environment) if type(underlying) is Runner else underlying
