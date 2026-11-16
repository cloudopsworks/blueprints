"""Bounded scanner protocols. Configuration is Tronador's typed YAML projection.

Results describe completed operations, not tool installation or upload attempts.
No source-executing credentialed command is permitted for untrusted source.
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

from contracts import ContractError, _check, canonical_bytes, load_record, rooted_path
from executor import ExecutionError

SCANNERS = ('snyk', 'sonar', 'semgrep', 'trivy', 'dependency-track')
FLAGS = dict(zip(SCANNERS, ('snykEnabled', 'sonarqubeEnabled', 'semgrepEnabled', 'trivyEnabled', 'dependencyTrackEnabled')))
DOCUMENT = load_record(Path(__file__).with_name('schema') / 'operations-v1.schema.json')
LIMIT = 4 * 1024 * 1024
POLL_COUNT = 30
POLL_INTERVAL = 2
CREDENTIALS = {'snyk_token', 'sonarqube_url', 'sonarqube_token', 'semgrep_token', 'dtrack_url', 'dtrack_token'}


class ScanFailure(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


def _fail(code, status='infrastructure-error'):
    raise ScanFailure(status, code)


def _configuration(value):
    _check(value, DOCUMENT['$defs']['ScannerConfiguration'], '$', document=DOCUMENT)


def _required(config, scanner):
    return scanner == 'sonar' and config['sonarqubeEnabled'] and config['sonarqubeFailOnQualityGate'] and config['sonarqubeQualityGateEnabled']


def _identity(plan, manifest, component, scanner, config):
    artifacts = {x['componentId']: x['mainArtifact'] for x in manifest['components']}
    artifact = artifacts.get(component['id'])
    if artifact is None:
        raise ContractError('scanner-artifact', 'active component has no verified artifact')
    identity = {'componentId': component['id'], 'profile': component['buildProfile'], 'scanner': scanner,
                'sourceSha': plan['headSha'], 'artifactDigest': artifact['digest']}
    return {'apiVersion': 'cloudopsworks.io/operations/v1', 'kind': 'ScannerResult', **identity,
            'required': _required(config, scanner), 'correlationId': 'scan-' + hashlib.sha256(canonical_bytes(identity)).hexdigest()[:32],
            'status': 'disabled', 'errorCode': None}


def validate_results(plan, manifest, resolved_scanners, results):
    """Reject missing/duplicate/tampered coverage using CURRENT trusted policy."""
    _configuration(resolved_scanners)
    expected = {(c['id'], s): _identity(plan, manifest, c, s, resolved_scanners)
                for c in plan['components'] for s in SCANNERS}
    seen = set()
    if not isinstance(results, list):
        raise ContractError('scanner-results', 'scanner results must be an array')
    for result in results:
        _check(result, DOCUMENT['$defs']['ScannerResult'], '$', document=DOCUMENT)
        key = result['componentId'], result['scanner']
        if key not in expected or key in seen:
            raise ContractError('scanner-coverage', 'unexpected or duplicate scanner coverage')
        seen.add(key)
        if any(result[k] != v for k, v in expected[key].items() if k not in ('status', 'errorCode')):
            raise ContractError('scanner-identity', 'scanner identity or current policy mismatch')
        if result['status'] in ('passed', 'processed', 'disabled', 'findings-advisory', 'required-gate-failure') and result['errorCode'] is not None:
            raise ContractError('scanner-status', 'completed scanner result has an error code')
        if result['status'] in ('infrastructure-error', 'unsupported-profile', 'unavailable-untrusted-context') and result['errorCode'] is None:
            raise ContractError('scanner-status', 'failed scanner result requires a bounded reason')
        enabled = resolved_scanners[FLAGS[result['scanner']]]
        if (result['status'] == 'disabled') != (not enabled):
            raise ContractError('scanner-policy', 'scanner enabled policy mismatch')
        if result['status'] in ('uploaded', 'processing', 'processed') and result['scanner'] != 'dependency-track':
            raise ContractError('scanner-status', 'upload status is not valid for this scanner')
        if result['scanner'] == 'dependency-track' and result['status'] == 'passed':
            raise ContractError('scanner-status', 'upload processing is not vulnerability clearance')
        if result['status'] == 'required-gate-failure' and not result['required']:
            raise ContractError('scanner-policy', 'advisory scanner cannot claim required gate failure')
    if seen != set(expected):
        raise ContractError('scanner-coverage', 'scanner coverage is incomplete')
    return results


def require_completed_gates(plan, manifest, resolved_scanners, results):
    validate_results(plan, manifest, resolved_scanners, results)
    if any(r['required'] and r['status'] != 'passed' for r in results):
        raise ContractError('scanner-required-gate', 'required scanner gate did not complete successfully')
    return results


def _json(data):
    try:
        return load_record(data)
    except (ContractError, TypeError):
        _fail('invalid-scanner-report')


def _read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > LIMIT:
        _fail('missing-or-unbounded-report')
    return path.read_bytes()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _http(method, url, headers, body):
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect).open(request, timeout=20) as response:
            data = response.read(LIMIT + 1)
            if len(data) > LIMIT:
                _fail('http-response-limit')
            return response.status, data
    except urllib.error.HTTPError as exc:
        return exc.code, b''
    except (OSError, ValueError):
        _fail('scanner-service-unavailable')


class Protocol:
    def __init__(self, executor, credentials, home, http):
        self.executor, self.credentials, self.home, self.http = executor, credentials, home, http or _http

    def run(self, argv, cwd, token=None):
        # Caller must select an isolated Runner: never inherit deployment/GitHub credentials.
        if getattr(self.executor, 'inherit_environment', False):
            _fail('scanner-environment-not-isolated')
        env = {'PATH': os.environ.get('PATH', os.defpath), 'HOME': str(self.home),
               'DOTNET_CLI_HOME': str(self.home), 'GOTOOLCHAIN': 'local', 'CI': 'true',
               'BUNDLE_PATH': str(self.home / 'bundle'), 'PIPENV_VENV_IN_PROJECT': '1',
               'POETRY_VIRTUALENVS_IN_PROJECT': 'true'}
        if token:
            key, credential = token
            env[key] = self.secret(credential)
        try:
            result = self.executor.run(argv, cwd=cwd, env=env)
        except (ExecutionError, OSError):
            _fail('scanner-tool-unavailable')
        if len(result.stdout.encode()) > LIMIT:
            _fail('scanner-output-limit')
        return result

    def secret(self, key):
        value = self.credentials.get(key)
        if not isinstance(value, str) or not value or '\x00' in value:
            _fail('missing-scanner-credential')
        return value

    def request(self, service, path, *, method='GET', value=None):
        endpoint = self.secret(service + '_url')
        parsed = urllib.parse.urlsplit(endpoint if '://' in endpoint else 'https://' + endpoint)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
            _fail('invalid-scanner-endpoint')
        headers = {'Content-Type': 'application/json'}
        token = self.secret(service + '_token')
        if service == 'dtrack':
            headers['X-Api-Key'] = token
        else:
            headers['Authorization'] = 'Basic ' + base64.b64encode((token + ':').encode()).decode()
        try:
            status, body = self.http(method, urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path.split('?')[0], path.partition('?')[2], '')), headers,
                                     None if value is None else canonical_bytes(value))
        except ScanFailure:
            raise
        except Exception:
            _fail('scanner-service-unavailable')
        if status != 200:
            _fail('scanner-service-auth' if status in (401, 403) else 'scanner-service-error')
        return _json(body)

    def checked(self, argv, cwd):
        if self.run(argv, cwd).returncode:
            _fail('scanner-prerequisite-failed')


def _one(source, pattern):
    paths = sorted(p for p in source.glob(pattern) if p.is_file() and not p.is_symlink())
    if len(paths) != 1:
        _fail('ambiguous-scanner-project', 'unsupported-profile')
    return paths[0]


def _dotnet_project(source):
    solutions = list(source.glob('*.sln')) + list(source.glob('*.slnx'))
    if len(solutions) == 1 and not solutions[0].is_symlink():
        return solutions[0]
    return _one(source, '**/*.csproj')


def _snyk(protocol, component, source):
    profile = component['buildProfile']
    protocol.secret('snyk_token')
    # Standard Snyk Open Source has no Cargo profile. An entitled SBOM service is
    # distinct and is not silently substituted without a verified SBOM artifact.
    if profile == 'cargo':
        _fail('snyk-cargo-test-unsupported', 'unsupported-profile')
    files = {'npm': 'package.json', 'pnpm': 'package.json', 'yarn': 'package.json', 'go': 'go.mod',
             'maven': 'pom.xml', 'gradle': 'build.gradle', 'bundler': 'Gemfile', 'rails': 'Gemfile'}
    manifest = files.get(profile)
    if profile == 'dotnet':
        manifest = str(_dotnet_project(source).relative_to(source))
        protocol.checked(['dotnet', 'restore', manifest], source)
    elif profile == 'python':
        if (source / 'poetry.lock').is_file():
            manifest = 'pyproject.toml'; protocol.checked(['poetry', 'install', '--no-interaction'], source)
        elif (source / 'Pipfile.lock').is_file():
            manifest = 'Pipfile'; protocol.checked(['pipenv', 'sync'], source)
        elif (source / 'requirements.txt').is_file():
            manifest = 'requirements.txt'
            protocol.checked(['python3', '-m', 'venv', str(protocol.home / 'venv')], source)
            protocol.checked([str(protocol.home / 'venv/bin/pip'), 'install', '-r', manifest], source)
        else:
            _fail('python-dependency-profile-unsupported', 'unsupported-profile')
    elif profile == 'npm':
        protocol.checked(['npm', 'ci', '--ignore-scripts'], source)
    elif profile == 'pnpm':
        protocol.checked(['pnpm', 'install', '--frozen-lockfile', '--ignore-scripts'], source)
    elif profile == 'yarn':
        # Immutable lock installation is supported for modern Yarn; do not run
        # arbitrary repository yarnPath plugins with scanner credentials.
        version = protocol.run(['yarn', '--version'], source)
        if version.returncode or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?\s*', version.stdout):
            _fail('yarn-version-unavailable')
        args = ['--frozen-lockfile', '--ignore-scripts'] if int(version.stdout.split('.')[0]) == 1 else ['--immutable', '--mode=skip-builds']
        protocol.checked(['yarn', 'install', *args], source)
    elif profile == 'go':
        protocol.checked(['go', 'mod', 'download'], source)
    elif profile == 'maven':
        protocol.checked(['mvn', '-B', '-q', '-DskipTests', 'package'], source)
    elif profile == 'gradle':
        if not (source / 'build.gradle').is_file():
            manifest = 'build.gradle.kts'
        protocol.checked(['gradle', '--no-daemon', 'assemble', '-x', 'test'], source)
    elif profile in ('bundler', 'rails'):
        protocol.checked(['bundle', 'config', 'set', '--local', 'path', str(protocol.home / 'bundle')], source)
        protocol.checked(['bundle', 'install'], source)
    if not manifest or not (source / manifest).is_file():
        _fail('snyk-project-unsupported', 'unsupported-profile')
    argv = ['snyk', 'test', '--json', '--file=' + manifest]
    if profile == 'python' and manifest == 'requirements.txt':
        argv.append('--command=' + str(protocol.home / 'venv/bin/python'))
    result = protocol.run(argv, source, ('SNYK_TOKEN', 'snyk_token'))
    codes = {2: ('infrastructure-error', 'snyk-execution-error'), 3: ('unsupported-profile', 'snyk-no-project'),
             69: ('infrastructure-error', 'snyk-service-unavailable'), 75: ('infrastructure-error', 'snyk-temporary-failure'),
             77: ('infrastructure-error', 'snyk-permission-denied')}
    if result.returncode not in (0, 1):
        status, code = codes.get(result.returncode, ('infrastructure-error', 'snyk-execution-error'))
        _fail(code, status)
    envelope = _json('{"reports":' + result.stdout + '}')
    if set(envelope) != {'reports'}:
        _fail('invalid-snyk-report')
    reports = envelope['reports'] if isinstance(envelope['reports'], list) else [envelope['reports']]
    if not reports:
        _fail('invalid-snyk-report')
    findings = False
    for report in reports:
        if not isinstance(report, dict) or type(report.get('ok')) is not bool or not isinstance(report.get('vulnerabilities'), list):
            _fail('invalid-snyk-report')
        if report['ok'] == bool(report['vulnerabilities']):
            _fail('inconsistent-snyk-report')
        findings |= bool(report['vulnerabilities'])
    if (result.returncode == 1) != findings:
        _fail('inconsistent-snyk-report')
    return 'findings-advisory' if findings else 'passed'


def _sonar(protocol, component, source, plan, required):
    language = {'dotnet': 'cs', 'java': 'java', 'node': 'js', 'python': 'py', 'go': 'go', 'ruby': 'ruby', 'rust': 'rust'}[component['language']]
    capabilities = protocol.request('sonarqube', '/api/languages/list')
    if not isinstance(capabilities.get('languages'), list):
        _fail('invalid-sonar-capabilities')
    if language not in {x.get('key') for x in capabilities['languages'] if isinstance(x, dict)}:
        _fail('sonar-analyzer-unavailable', 'unsupported-profile')
    key = 'monorepo-' + hashlib.sha256((plan['repository']['fullName'] + ':' + component['id']).encode()).hexdigest()[:32]
    # Analyze a separate copy: Scanner for .NET modifies build state. Reject
    # symlinks rather than copying source-controlled paths outside the component.
    analysis = protocol.home / 'analysis'
    shutil.copytree(source, analysis, ignore=shutil.ignore_patterns('.git', 'node_modules', '.venv', '.sonarqube', '.scannerwork'))
    settings = protocol.home / 'sonar.properties'; settings.write_text('')
    report = protocol.home / 'report-task.txt'
    token = protocol.secret('sonarqube_token')
    endpoint = protocol.secret('sonarqube_url')
    if '://' not in endpoint:
        endpoint = 'https://' + endpoint
    cloud = urllib.parse.urlsplit(endpoint).hostname in ('sonarcloud.io', 'sonarcloud.us')
    organization = plan['repository']['fullName'].split('/')[0]
    if component['buildProfile'] == 'dotnet':
        project = _dotnet_project(analysis)
        begin = ['dotnet', 'sonarscanner', 'begin', '/k:' + key, '/d:sonar.host.url=' + endpoint,
                 '/d:sonar.token=' + token, '/d:sonar.scanner.scanAll=false', '/v:' + plan['version']]
        if cloud:
            begin.append('/o:' + organization)
        if protocol.run(begin, analysis).returncode:
            _fail('sonar-begin-failed')
        protocol.checked(['dotnet', 'build', str(project.relative_to(analysis)), '--no-incremental', '--disable-build-servers'], analysis)
        if protocol.run(['dotnet', 'sonarscanner', 'end', '/d:sonar.token=' + token], analysis).returncode:
            _fail('sonar-end-failed')
        report = analysis / '.sonarqube/out/.sonar/report-task.txt'
    else:
        profile = component['buildProfile']
        if profile == 'maven':
            protocol.checked(['mvn', '-B', '-DskipTests', 'compile'], analysis)
        elif profile == 'gradle':
            protocol.checked(['gradle', '--no-daemon', 'classes'], analysis)
        args = ['sonar-scanner', '-Dproject.settings=' + str(settings), '-Dsonar.projectKey=' + key,
                '-Dsonar.projectVersion=' + plan['version'], '-Dsonar.projectBaseDir=' + str(analysis), '-Dsonar.sources=.', '-Dsonar.host.url=' + endpoint,
                '-Dsonar.scanner.metadataFilePath=' + str(report)]
        if cloud:
            args.append('-Dsonar.organization=' + organization)
        if profile in ('maven', 'gradle'):
            args.append('-Dsonar.java.binaries=' + ('target/classes' if profile == 'maven' else 'build/classes'))
        if protocol.run(args, analysis, ('SONAR_TOKEN', 'sonarqube_token')).returncode:
            _fail('sonar-analysis-failed')
    properties = {}
    for line in _read(report).decode('utf-8').splitlines():
        if '=' in line:
            k, v = line.split('=', 1)
            if k in properties:
                _fail('invalid-sonar-task-report')
            properties[k] = v
    task_id = properties.get('ceTaskId', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', task_id):
        _fail('invalid-sonar-task-report')
    for attempt in range(POLL_COUNT):
        task = protocol.request('sonarqube', '/api/ce/task?id=' + task_id).get('task', {})
        state = task.get('status')
        if state == 'SUCCESS':
            analysis_id = task.get('analysisId', '')
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', analysis_id):
                _fail('invalid-sonar-analysis-id')
            gate = protocol.request('sonarqube', '/api/qualitygates/project_status?analysisId=' + analysis_id).get('projectStatus', {}).get('status')
            if gate == 'OK':
                return 'passed'
            if gate in ('WARN', 'ERROR'):
                return 'required-gate-failure' if required else 'findings-advisory'
            _fail('invalid-sonar-quality-gate')
        if state in ('FAILED', 'CANCELED'):
            _fail('sonar-compute-failed')
        if state not in ('PENDING', 'IN_PROGRESS'):
            _fail('invalid-sonar-compute-status')
        if attempt + 1 < POLL_COUNT:
            time.sleep(POLL_INTERVAL)
    _fail('sonar-compute-timeout')


def _dtrack(protocol, component, source, plan):
    version = protocol.request('dtrack', '/api/version').get('version', '')
    match = re.fullmatch(r'(\d+)\.(\d+)(?:\.[0-9]+)?(?:[-+].*)?', version)
    if not match or tuple(map(int, match.groups())) < (4, 11):
        _fail('dtrack-correlated-poll-unsupported', 'unsupported-profile')
    candidates = [source / x for x in ('bom.json', 'bom.xml', 'target/bom.json', 'target/bom.xml') if (source / x).exists()]
    if len(candidates) != 1:
        _fail('dtrack-existing-bom-required', 'unsupported-profile')
    bom = _read(candidates[0])
    if candidates[0].suffix == '.json':
        document = _json(bom)
        if document.get('bomFormat') != 'CycloneDX' or not re.fullmatch(r'1\.[0-9]+', str(document.get('specVersion', ''))):
            _fail('dtrack-invalid-bom')
    else:
        if b'<!DOCTYPE' in bom.upper() or b'<!ENTITY' in bom.upper():
            _fail('dtrack-invalid-bom')
        try:
            tag = ET.fromstring(bom).tag
        except ET.ParseError:
            _fail('dtrack-invalid-bom')
        if not re.fullmatch(r'\{http://cyclonedx.org/schema/bom/1\.[0-9]+\}bom', tag):
            _fail('dtrack-invalid-bom')
    response = protocol.request('dtrack', '/api/v1/bom', method='PUT', value={
        'autoCreate': True, 'projectName': plan['repository']['fullName'] + ':' + component['id'],
        'projectVersion': plan['version'], 'bom': base64.b64encode(bom).decode()})
    token = response.get('token')
    try:
        if not isinstance(token, str) or str(uuid.UUID(token)) != token:
            _fail('dtrack-invalid-upload-token')
    except ValueError:
        _fail('dtrack-invalid-upload-token')
    for attempt in range(POLL_COUNT):
        processing = protocol.request('dtrack', '/api/v1/event/token/' + token).get('processing')
        if processing is False:
            return 'processed'  # Upload processing only; NOT vulnerability clearance.
        if processing is not True:
            _fail('dtrack-invalid-processing-response')
        if attempt + 1 < POLL_COUNT:
            time.sleep(POLL_INTERVAL)
    _fail('dtrack-processing-timeout')


def _semgrep(protocol, source):
    result = protocol.run(['semgrep', 'ci', '--json'], source, ('SEMGREP_APP_TOKEN', 'semgrep_token'))
    if result.returncode not in (0, 1):
        _fail('semgrep-execution-error')
    report = _json(result.stdout)
    if not isinstance(report.get('results'), list) or not isinstance(report.get('errors'), list):
        _fail('invalid-semgrep-report')
    if report['errors']:
        _fail('semgrep-analysis-error')
    if result.returncode == 1 and not report['results']:
        _fail('inconsistent-semgrep-report')
    return 'findings-advisory' if report['results'] else 'passed'


def _trivy(protocol, source, artifact):
    if artifact is None:
        args = ['trivy', 'fs', '--format', 'json', '--scanners', 'vuln,misconfig,secret', str(source)]
    elif isinstance(artifact, Path):
        if artifact.is_symlink() or not artifact.is_file():
            _fail('invalid-trivy-artifact')
        args = ['trivy', 'image', '--format', 'json', '--input', str(artifact)]
    elif isinstance(artifact, str) and re.fullmatch(r'[^\s@]+@sha256:[0-9a-f]{64}', artifact):
        args = ['trivy', 'image', '--format', 'json', artifact]
    else:
        _fail('invalid-trivy-artifact')
    result = protocol.run(args, source)
    if result.returncode:
        _fail('trivy-execution-error')
    report = _json(result.stdout)
    if not isinstance(report.get('Results'), list):
        _fail('invalid-trivy-report')
    findings = False
    for item in report['Results']:
        if not isinstance(item, dict):
            _fail('invalid-trivy-report')
        for key in ('Vulnerabilities', 'Misconfigurations', 'Secrets'):
            if item.get(key) is not None and not isinstance(item[key], list):
                _fail('invalid-trivy-report')
            findings |= bool(item.get(key))
    return 'findings-advisory' if findings else 'passed'


def _bounded_source(source):
    count = size = 0
    for path in source.rglob('*'):
        count += 1
        if path.is_symlink():
            _fail('scanner-source-symlink')
        if path.is_file():
            size += path.stat().st_size
        if count > 100000 or size > 1024 * 1024 * 1024:
            _fail('scanner-source-limit')


def run_scanners(plan, manifest, resolved_scanners, executor, *, workdir, credentials,
                 trusted_source=False, artifact_paths=None, http=None):
    _configuration(resolved_scanners)
    if not isinstance(credentials, dict) or set(credentials) - CREDENTIALS:
        raise ContractError('scanner-credentials', 'unknown scanner credential context')
    results = []
    checked_sources = set()
    for component in plan['components']:
        for scanner in SCANNERS:
            result = _identity(plan, manifest, component, scanner, resolved_scanners)
            if resolved_scanners[FLAGS[scanner]]:
                try:
                    if not trusted_source and scanner != 'trivy':
                        _fail('credentialed-source-scan-forbidden', 'unavailable-untrusted-context')
                    source = rooted_path(Path(workdir), component['path'])
                    if source not in checked_sources:
                        _bounded_source(source)
                        checked_sources.add(source)
                    with tempfile.TemporaryDirectory(prefix='blueprints-scan-') as home:
                        protocol = Protocol(executor, credentials, Path(home), http)
                        if scanner == 'snyk':
                            prepared = Path(home) / 'source'
                            shutil.copytree(source, prepared, ignore=shutil.ignore_patterns('.git', 'node_modules', '.venv', '.sonarqube', '.scannerwork'))
                            status = _snyk(protocol, component, prepared)
                        elif scanner == 'sonar':
                            status = _sonar(protocol, component, source, plan, result['required'])
                        elif scanner == 'semgrep':
                            status = _semgrep(protocol, source)
                        elif scanner == 'dependency-track':
                            status = _dtrack(protocol, component, source, plan)
                        else:
                            status = _trivy(protocol, source, (artifact_paths or {}).get(component['id']))
                        result['status'] = status
                except ScanFailure as exc:
                    result.update(status=exc.status, errorCode=exc.code)
                except (ContractError, OSError, UnicodeError, ValueError, TypeError, KeyError, AttributeError):
                    result.update(status='infrastructure-error', errorCode='scanner-protocol-error')
            results.append(result)
    return validate_results(plan, manifest, resolved_scanners, results)
