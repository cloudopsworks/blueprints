"""Offline scanner protocol doubles: no live credentials, network or cloud."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'cd/monorepo/runtime'))
from contracts import ContractError
from executor import Runner
from scanners import run_scanners, require_completed_gates, validate_results

FIXTURES = Path(__file__).with_name('fixtures') / 'operations'


class Commands:
    def __init__(self):
        self.calls = []
        self.replies = {}
    def run(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if argv[0] == 'sonar-scanner':
            report = next(x.split('=', 1)[1] for x in argv if x.startswith('-Dsonar.scanner.metadataFilePath='))
            Path(report).write_text('ceTaskId=task1\nceTaskUrl=https://evil.invalid/leak\n')
        if argv[:3] == ['dotnet', 'sonarscanner', 'end']:
            report = Path(kwargs['cwd']) / '.sonarqube/out/.sonar/report-task.txt'
            report.parent.mkdir(parents=True); report.write_text('ceTaskId=task1\n')
        code, output = self.replies.get(argv[0], (0, '{}'))
        return subprocess.CompletedProcess(argv, code, output, 'SECRET-CANARY')


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name); self.source = self.work / 'components/api'; self.source.mkdir(parents=True)
        self.plan = json.loads((FIXTURES / 'operation-context-frozen.json').read_text())['plan']
        self.manifest = {'components': [{'componentId': 'api', 'mainArtifact': {'digest': 'sha256:' + '1' * 64}}]}
        self.config = json.loads((FIXTURES / 'scanners.json').read_text())
        self.executor = Commands()
        self.credentials = dict(snyk_token='SECRET-CANARY', sonarqube_token='SECRET-CANARY',
                                sonarqube_url='https://sonar.invalid', semgrep_token='SECRET-CANARY',
                                dtrack_token='SECRET-CANARY', dtrack_url='https://dtrack.invalid')
        self.http_calls = []
        self.gate = 'OK'; self.ce = 'SUCCESS'
    def http(self, method, url, headers, body):
        self.http_calls.append((method, url, headers, body))
        if url.endswith('/api/languages/list'):
            value = {'languages': [{'key': 'go'}, {'key': 'cs'}]}
        elif '/api/ce/task?' in url:
            value = {'task': {'status': self.ce, 'analysisId': 'analysis1'}}
        elif '/api/qualitygates/' in url:
            value = {'projectStatus': {'status': self.gate}}
        elif url.endswith('/api/version'):
            value = {'version': '4.11.1'}
        elif url.endswith('/api/v1/bom'):
            value = {'token': '12345678-1234-1234-1234-123456789abc'}
        else:
            value = {'processing': False}
        return 200, json.dumps(value).encode()
    def run_scans(self, trusted=True, **kwargs):
        return run_scanners(self.plan, self.manifest, self.config, self.executor,
                            workdir=self.work, credentials=self.credentials, trusted_source=trusted, http=self.http, **kwargs)
    def selected(self, scanner, **kwargs):
        return next(r for r in self.run_scans(**kwargs) if r['scanner'] == scanner)
    def test_disabled_complete_coverage_and_closed_projection(self):
        results = self.run_scans()
        self.assertEqual(len(results), 5); self.assertTrue(all(r['status'] == 'disabled' for r in results))
        require_completed_gates(self.plan, self.manifest, self.config, results)
        self.config['newKnob'] = True
        with self.assertRaises(ContractError): self.run_scans()
    def test_barrier_rejects_missing_duplicate_and_tampered_identity(self):
        results = self.run_scans()
        mutations = [results[:-1], results + [results[0]]]
        for field, value in [('required', True), ('sourceSha', '0' * 40), ('artifactDigest', None), ('profile', 'other')]:
            altered = copy.deepcopy(results); altered[0][field] = value; mutations.append(altered)
        for altered in mutations:
            with self.assertRaises(ContractError): validate_results(self.plan, self.manifest, self.config, altered)
    def test_required_recomputed_from_current_policy(self):
        self.config.update(sonarqubeEnabled=True, sonarqubeFailOnQualityGate=True)
        results = self.run_scans(trusted=False)
        with self.assertRaises(ContractError): require_completed_gates(self.plan, self.manifest, self.config, results)
        results[1]['required'] = False
        with self.assertRaises(ContractError): require_completed_gates(self.plan, self.manifest, self.config, results)
    def test_untrusted_does_not_execute_credentialed_source(self):
        self.config.update(snykEnabled=True, sonarqubeEnabled=True, semgrepEnabled=True, dependencyTrackEnabled=True)
        results = self.run_scans(trusted=False)
        self.assertEqual(self.executor.calls, []); self.assertEqual(self.http_calls, [])
        self.assertEqual(sum(r['status'] == 'unavailable-untrusted-context' for r in results), 4)
    def test_snyk_exit_status_protocol(self):
        self.config['snykEnabled'] = True; (self.source / 'go.mod').write_text('module example/api')
        for code, status in [(0, 'passed'), (1, 'findings-advisory'), (2, 'infrastructure-error'),
                             (3, 'unsupported-profile'), (69, 'infrastructure-error'), (75, 'infrastructure-error'), (77, 'infrastructure-error')]:
            self.executor.replies['snyk'] = code, json.dumps({'ok': code == 0, 'vulnerabilities': [] if code == 0 else [{}]})
            self.assertEqual(self.selected('snyk')['status'], status)
        prep, scan = self.executor.calls[:2]
        self.assertNotIn('SNYK_TOKEN', prep[1]['env']); self.assertIn('SNYK_TOKEN', scan[1]['env'])
        self.assertNotIn('GITHUB_TOKEN', scan[1]['env'])
    def test_snyk_malformed_inconsistent_and_missing_token(self):
        self.config['snykEnabled'] = True; (self.source / 'go.mod').touch()
        for output in ('not-json SECRET-CANARY', '{"ok":true,"vulnerabilities":[{}]}'):
            self.executor.replies['snyk'] = 0, output
            result = self.selected('snyk'); self.assertEqual(result['status'], 'infrastructure-error')
            self.assertNotIn('SECRET-CANARY', json.dumps(result))
        del self.credentials['snyk_token']
        self.assertEqual(self.selected('snyk')['errorCode'], 'missing-scanner-credential')
    def test_cargo_standard_test_explicit_unsupported(self):
        self.config['snykEnabled'] = True
        self.plan['components'][0].update(language='rust', buildProfile='cargo')
        self.assertEqual(self.selected('snyk')['status'], 'unsupported-profile'); self.assertEqual(self.executor.calls, [])
    def test_sonar_completed_quality_gate_and_warning_failure(self):
        self.config.update(sonarqubeEnabled=True, sonarqubeFailOnQualityGate=True)
        for gate, expected in [('OK', 'passed'), ('WARN', 'required-gate-failure'), ('ERROR', 'required-gate-failure')]:
            self.gate = gate; results = self.run_scans()
            self.assertEqual(results[1]['status'], expected)
            if gate == 'OK': require_completed_gates(self.plan, self.manifest, self.config, results)
            else:
                with self.assertRaises(ContractError): require_completed_gates(self.plan, self.manifest, self.config, results)
        self.assertTrue(all('evil.invalid' not in call[1] for call in self.http_calls))
    def test_sonar_failed_compute_not_quality_failure(self):
        self.config['sonarqubeEnabled'] = True; self.ce = 'FAILED'
        self.assertEqual(self.selected('sonar')['errorCode'], 'sonar-compute-failed')
    def test_sonar_poll_timeout_never_passes(self):
        self.config['sonarqubeEnabled'] = True; self.ce = 'PENDING'
        with patch('scanners.POLL_COUNT', 2), patch('scanners.time.sleep'):
            self.assertEqual(self.selected('sonar')['errorCode'], 'sonar-compute-timeout')
    def test_dotnet_real_build_between_begin_end_and_tokens_both_ends(self):
        self.config['sonarqubeEnabled'] = True
        self.plan['components'][0].update(language='dotnet', buildProfile='dotnet')
        (self.source / 'api.csproj').write_text('<Project/>')
        self.assertEqual(self.selected('sonar')['status'], 'passed')
        commands = [call[0] for call in self.executor.calls]
        self.assertEqual(commands[0][:3], ['dotnet', 'sonarscanner', 'begin'])
        self.assertEqual(commands[1], ['dotnet', 'build', 'api.csproj', '--no-incremental', '--disable-build-servers'])
        self.assertEqual(commands[2][:3], ['dotnet', 'sonarscanner', 'end'])
        self.assertTrue(any('SECRET-CANARY' in x for x in commands[0])); self.assertTrue(any('SECRET-CANARY' in x for x in commands[2]))
    def test_ruby_analyzer_unavailable(self):
        self.config['sonarqubeEnabled'] = True
        self.plan['components'][0].update(language='ruby', buildProfile='bundler')
        self.assertEqual(self.selected('sonar')['status'], 'unsupported-profile')
    def test_dtrack_correlated_processing_not_vulnerability_pass(self):
        self.config['dependencyTrackEnabled'] = True
        (self.source / 'bom.json').write_text('{"bomFormat":"CycloneDX","specVersion":"1.5","version":1}')
        result = self.selected('dependency-track'); self.assertEqual(result['status'], 'processed')
        self.assertTrue(self.http_calls[-1][1].endswith('/event/token/12345678-1234-1234-1234-123456789abc'))
        self.assertEqual(self.http_calls[-2][0], 'PUT')
    def test_dtrack_no_bom_is_not_green(self):
        self.config['dependencyTrackEnabled'] = True
        self.assertEqual(self.selected('dependency-track')['status'], 'unsupported-profile')
    def test_dtrack_malformed_token_and_old_server(self):
        self.config['dependencyTrackEnabled'] = True; (self.source / 'bom.xml').write_text('<bom xmlns="http://cyclonedx.org/schema/bom/1.5"/>')
        for value, error in [({'version': '4.10.0'}, 'dtrack-correlated-poll-unsupported'), ({'version': '4.11.0'}, 'dtrack-invalid-upload-token')]:
            def http(method, url, headers, body): return 200, json.dumps(value if url.endswith('/api/version') else {'token': 'evil'}).encode()
            self.http = http
            self.assertEqual(self.selected('dependency-track')['errorCode'], error)
    def test_semgrep_and_trivy_findings_visible_advisory(self):
        self.config.update(semgrepEnabled=True, trivyEnabled=True)
        self.executor.replies.update(semgrep=(1, '{"results":[{}],"errors":[]}'), trivy=(0, '{"Results":[{"Vulnerabilities":[{}]}]}'))
        results = self.run_scans()
        self.assertEqual([r['status'] for r in results[2:4]], ['findings-advisory'] * 2)
        require_completed_gates(self.plan, self.manifest, self.config, results)
    def test_ambient_inheriting_runner_rejected_before_execution(self):
        self.config['trivyEnabled'] = True; self.executor = Runner()
        self.assertEqual(self.selected('trivy')['errorCode'], 'scanner-environment-not-isolated')
    def test_all_active_components_not_build_selection(self):
        self.plan['buildSelection'] = []
        self.assertEqual(len(self.run_scans()), 5)
    def test_supported_snyk_profiles_prepare_without_credentials(self):
        cases = [('npm', 'node', 'package.json', 'npm'), ('pnpm', 'node', 'package.json', 'pnpm'),
                 ('yarn', 'node', 'package.json', 'yarn'), ('maven', 'java', 'pom.xml', 'mvn'),
                 ('gradle', 'java', 'build.gradle.kts', 'gradle'), ('dotnet', 'dotnet', 'api.csproj', 'dotnet'),
                 ('python', 'python', 'requirements.txt', 'python3'), ('bundler', 'ruby', 'Gemfile', 'bundle'),
                 ('rails', 'ruby', 'Gemfile', 'bundle')]
        self.config['snykEnabled'] = True
        self.executor.replies.update(snyk=(0, '{"ok":true,"vulnerabilities":[]}'), yarn=(0, '1.22.22'))
        for profile, language, filename, tool in cases:
            self.plan['components'][0].update(language=language, buildProfile=profile)
            (self.source / filename).touch(); self.executor.calls.clear()
            result = self.selected('snyk')
            self.assertEqual(result['status'], 'passed', (profile, result))
            self.assertEqual(self.executor.calls[0][0][0], tool)
            self.assertTrue(all('SNYK_TOKEN' not in call[1]['env'] for call in self.executor.calls[:-1]))
            # Preparation is isolated from the immutable source component.
            self.assertNotEqual(Path(self.executor.calls[0][1]['cwd']), self.source)
    def test_python_poetry_and_pipenv_distinct_preparation(self):
        self.config['snykEnabled'] = True
        self.plan['components'][0].update(language='python', buildProfile='python')
        self.executor.replies['snyk'] = 0, '{"ok":true,"vulnerabilities":[]}'
        for lock, manifest, tool in [('poetry.lock', 'pyproject.toml', 'poetry'), ('Pipfile.lock', 'Pipfile', 'pipenv')]:
            (self.source / lock).touch(); (self.source / manifest).touch(); self.executor.calls.clear()
            self.assertEqual(self.selected('snyk')['status'], 'passed')
            self.assertEqual(self.executor.calls[0][0][0], tool)
            self.assertIn('--file=' + manifest, self.executor.calls[-1][0])
            (self.source / lock).unlink(); (self.source / manifest).unlink()
    def test_dtrack_processing_timeout_and_auth_error(self):
        self.config['dependencyTrackEnabled'] = True
        (self.source / 'bom.json').write_text('{"bomFormat":"CycloneDX","specVersion":"1.5","version":1}')
        original = self.http
        def http(method, url, headers, body):
            return (200, b'{"processing":true}') if '/event/token/' in url else original(method, url, headers, body)
        self.http = http
        with patch('scanners.POLL_COUNT', 2), patch('scanners.time.sleep'):
            self.assertEqual(self.selected('dependency-track')['errorCode'], 'dtrack-processing-timeout')
        self.http = lambda *args: (403, b'SECRET-CANARY')
        result = self.selected('dependency-track')
        self.assertEqual(result['errorCode'], 'scanner-service-auth')
        self.assertNotIn('SECRET-CANARY', json.dumps(result))
    def test_real_subprocess_structured_output_and_environment_isolation(self):
        # Execute a real child process; no scanner/network dependency is needed.
        from scanners import Protocol
        protocol = Protocol(Runner(inherit_environment=False), self.credentials, self.work, None)
        result = protocol.run([sys.executable, '-c',
            'import json,os;print(json.dumps({"Results":[],"leaked": "GITHUB_TOKEN" in os.environ}))'], self.source)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(json.loads(result.stdout)['leaked'])
    def test_symlink_and_unbounded_source_are_rejected(self):
        self.config['trivyEnabled'] = True
        (self.source / 'escape').symlink_to('/etc/passwd')
        self.assertEqual(self.selected('trivy')['errorCode'], 'scanner-source-symlink')
    def test_endpoint_cannot_redirect_credentials_to_source_url(self):
        self.config['sonarqubeEnabled'] = True
        self.credentials['sonarqube_url'] = 'https://sonar.invalid/source-controlled/path'
        self.assertEqual(self.selected('sonar')['errorCode'], 'invalid-scanner-endpoint'); self.assertEqual(self.http_calls, [])

if __name__ == '__main__': unittest.main()
