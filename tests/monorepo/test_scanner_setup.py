"""Actual scanner composite bodies with LOCAL tool doubles, never a hosted install."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

from test_composite_boundary import ROOT, audit_graph, yaml_file

ACTION = ROOT/'ci/monorepo/scanners/action.yml'
WORKER = ROOT/'tests/monorepo/actions/script_worker.mjs'
DIGEST = '979172ee128903f50e43fff221f22a0689579f22c086dabaa0d1a5416485b9ba'


def step(name):
    return next(item for item in yaml_file(ACTION)['runs']['steps'] if item.get('id') == name)


def prepare(root, **overrides):
    env = dict(PATH=os.environ['PATH'], RUNNER_TEMP=str(root), RUNNER_OS='Linux', RUNNER_ARCH='X64',
               SONAR_ENABLED='true', DOTNET_ENABLED='true', SNYK_ENABLED='true', SEMGREP_ENABLED='true', TRIVY_ENABLED='true',
               GH_TOKEN='secret-sentinel', SONAR_TOKEN='secret-sentinel', PIP_INDEX_URL='https://attacker.invalid')
    env.update(overrides)
    result = subprocess.run(['node', str(WORKER)], input=json.dumps({'script':step('prepare')['with']['script']}),
                            env=env, capture_output=True, text=True, check=True, timeout=20)
    return json.loads(result.stdout)


class ScannerSetupTests(unittest.TestCase):
    def command(self, directory, name, text):
        executable = directory/name
        executable.write_text('#!/bin/bash\nset -euo pipefail\n'+text)
        executable.chmod(0o755)

    def run_native(self, which, *, corrupt=False, curl_version='8.7.1', fail_tool=False, tool_version=None,
                   tool_output='', fail_code=23, tool_missing=False):
        with tempfile.TemporaryDirectory(prefix='scanner setup ') as temporary:
            root = Path(temporary).resolve()
            prepared = prepare(root)
            self.assertNotIn('error', prepared, prepared)
            outputs = prepared['outputs']; installed = Path(outputs['root'])
            commands = root/'commands'; commands.mkdir()
            # Native installer protocol doubles record their full clean environment and cwd.
            record = '''
printf '%s\\n' "$0 $*" >> "$HOME/../events"
/usr/bin/env > "$HOME/../environment"
pwd > "$HOME/../cwd"
'''
            self.command(commands, 'curl', '''
if [ "$1" = --version ]; then echo 'curl '''+curl_version+''' (fixed test tool)'; exit; fi
'''+record+('exit 23\n' if fail_tool else '')+'''
while [ "$1" != --output ]; do shift; done
shift
printf '#!/bin/bash\\nprintf executed >> "$HOME/../executed"\\necho '''+(tool_version or '1.1308.4')+'''\\n' > "$1"
''')
            if not corrupt:
                # Positive checksum is a finite protocol double, not a claim these fixture bytes are the release.
                self.command(commands, 'sha256sum', '''
test "$*" = '--check --strict'
read -r digest file
test "$digest" = '''+DIGEST+'''
test -s "$file"
printf 'checksum\\n' >> "$HOME/../events"
''')
            package_output = "printf '%s' " + shlex.quote(tool_output) + ' >&2\n'
            package_failure = 'exit '+str(fail_code)+'\n' if fail_tool else ''
            self.command(commands, 'pipx', record+package_output+package_failure+'''
test "$PIPX_HOME" = "${HOME%/*}/semgrep"
test "$PIPX_BIN_DIR" = "${HOME%/*}/bin"
test "$PIP_CONFIG_FILE" = /dev/null
test "$PYTHONNOUSERSITE" = 1
mkdir -p "$PIPX_HOME/venvs/semgrep/bin"
printf '#!/bin/bash\\nprintf semgrep-version >> "$HOME/../executed"\\necho '''+(tool_version or '1.185.0')+'''\\n' > "$PIPX_HOME/venvs/semgrep/bin/semgrep"
chmod +x "$PIPX_HOME/venvs/semgrep/bin/semgrep"
ln -s "$PIPX_HOME/venvs/semgrep/bin/semgrep" "$PIPX_BIN_DIR/semgrep"
''')
            self.command(commands, 'dotnet', record+package_output+package_failure+'''
test "$DOTNET_CLI_TELEMETRY_OPTOUT" = 1
test "$DOTNET_SKIP_FIRST_TIME_EXPERIENCE" = 1
''')
            native_path = str(commands)+':'+os.environ['PATH']
            if tool_missing:
                (commands/('pipx' if which == 'semgrep' else 'dotnet')).unlink()
                # Real timeout/exec lookup, with no ambient package-manager fallback.
                for name in ('env', 'timeout', 'tr', 'tail', 'grep'):
                    (commands/name).symlink_to(shutil.which(name))
                native_path = str(commands)
            env = dict(os.environ, PATH=native_path, SCANNER_ROOT=str(installed),
                       SCANNER_HOME=outputs['home'], GITHUB_PATH=str(root/'published-paths'),
                       GH_TOKEN='secret-sentinel', SONAR_TOKEN='secret-sentinel',
                       PIP_INDEX_URL='https://attacker.invalid', NUGET_AUTH_TOKEN='secret-sentinel',
                       PYTHONPATH='/attacker', PIPX_HOME='/attacker', DOTNET_STARTUP_HOOKS='/attacker')
            result = subprocess.run(['/bin/bash', '-c', step(which)['run']], cwd=outputs['cwd'],
                                    env=env, capture_output=True, text=True, timeout=20)
            observed = {name:(installed/name).read_text() if (installed/name).is_file() else ''
                        for name in ('events','environment','cwd','executed')}
            observed['published'] = (root/'published-paths').read_text() if (root/'published-paths').exists() else ''
            observed['config'] = (installed/'NuGet.Config').read_text()
            observed['snyk_mode'] = oct((installed/'bin/snyk').stat().st_mode & 0o777) if (installed/'bin/snyk').exists() else ''
            return result, observed, str(installed)

    def test_fixed_installs_empty_cwd_isolated_environment_and_published_paths(self):
        for which in ('snyk', 'semgrep', 'dotnet'):
            with self.subTest(tool=which):
                result, seen, installed = self.run_native(which)
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                self.assertEqual(seen['cwd'].strip(), installed+'/empty-sonar-project')
                self.assertNotIn('secret-sentinel', str(seen))
                self.assertNotIn('attacker', str(seen))
                for variable in ('GH_TOKEN=', 'SONAR_TOKEN=', 'PYTHONPATH=', 'DOTNET_STARTUP_HOOKS='):
                    self.assertNotIn(variable, seen['environment'])
                self.assertIn('HOME='+installed+'/home', seen['environment'])
                if which == 'snyk':
                    self.assertIn('/v1.1308.4/snyk-linux', seen['events'])
                    self.assertIn('checksum\n', seen['events'])
                    self.assertEqual(seen['executed'], 'executed')
                    self.assertEqual(seen['snyk_mode'], '0o755')
                    for option in ('--max-filesize 268435456','--max-time 60','--max-redirs 5','--proto =https','--proto-redir =https','--tlsv1.2'):
                        self.assertIn(option, seen['events'])
                elif which == 'semgrep':
                    for argument in ('--backend pip', '--python python3', '--fetch-python never',
                                     '--index-url https://pypi.org/simple', '--isolated', 'semgrep==1.185.0'):
                        self.assertIn(argument, seen['events'])
                    self.assertEqual(seen['executed'], 'semgrep-version')
                else:
                    self.assertIn('tool install dotnet-sonarscanner --version 12.1.0', seen['events'])
                    self.assertIn('--configfile '+installed+'/NuGet.Config', seen['events'])
                    self.assertEqual(seen['config'], '<configuration><packageSources><clear/><add key="nuget" value="https://api.nuget.org/v3/index.json"/></packageSources></configuration>')
                self.assertEqual(seen['published'].strip(), installed+('/dotnet' if which == 'dotnet' else '/bin'))

    def test_checksum_failure_never_executes_download_and_reused_directory_denied(self):
        result, seen, _ = self.run_native('snyk', corrupt=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(seen['executed'], '')
        self.assertEqual(seen['published'], '')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            self.assertNotIn('error', prepare(root))
            result = prepare(root)
            self.assertIn('error', result)
            self.assertEqual(result['outputs'], {})
            self.assertEqual(result['calls'], [])

    def test_invalid_inputs_and_nonfixed_runner_fail_before_install(self):
        inputs = [(field,value) for field in ('SONAR_ENABLED','DOTNET_ENABLED','SNYK_ENABLED','SEMGREP_ENABLED','TRIVY_ENABLED')
                  for value in ('', 'TRUE', 'false\ntrue', '$(evil)')]
        inputs += [('RUNNER_ARCH','ARM64'),('RUNNER_OS','macOS')]
        for field, value in inputs:
            with self.subTest(field=field,value=value), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                result = prepare(root, **{field:value})
                self.assertIn('error', result)
                self.assertEqual(result['outputs'], {})
                self.assertEqual(result['calls'], [])
                self.assertEqual(list(root.iterdir()), [])

    def test_official_actions_are_pinned_and_source_free(self):
        document = yaml_file(ACTION)
        self.assertEqual(document['inputs'].keys(), {'sonarqube','dotnet','snyk','semgrep','trivy'})
        self.assertTrue(all(item['default'] == 'false' for item in document['inputs'].values()))
        self.assertEqual(document['runs']['steps'][0]['uses'], 'actions/github-script@v9')
        sonar = next(item for item in document['runs']['steps'] if item.get('uses') == 'sonarsource/sonarqube-scan-action@v8')
        self.assertEqual(sonar['with'], {'scannerVersion':'8.3.1.16491','projectBaseDir':'${{ steps.prepare.outputs.cwd }}','args':'--version','skipSignatureVerification':'false'})
        self.assertTrue(all(value == '' for value in sonar['env'].values()))
        trivy = next(item for item in document['runs']['steps'] if item.get('uses') == 'aquasecurity/setup-trivy@v0.3.1')
        self.assertEqual(trivy['with'], {'cache':False,'version':'v0.69.3'})
        for which, condition in [('snyk',"inputs.snyk == 'true'"),('semgrep',"inputs.semgrep == 'true'"),('dotnet',"inputs.sonarqube == 'true' && inputs.dotnet == 'true'")]:
            self.assertEqual(step(which)['if'], condition)
            self.assertEqual(step(which)['working-directory'], '${{ steps.prepare.outputs.cwd }}')
        self.assertNotIn('install.py', ACTION.read_text())
        self.assertNotIn('secrets.', ACTION.read_text())
        self.assertEqual(audit_graph('ci/monorepo/scanners/action.yml')['violations'], [])

    def test_private_preparation_files_and_disabled_flags(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            result = prepare(root, **{field:'false' for field in ('SONAR_ENABLED','DOTNET_ENABLED','SNYK_ENABLED','SEMGREP_ENABLED','TRIVY_ENABLED')})
            self.assertNotIn('error', result, result)
            self.assertEqual(result['calls'], [])
            outputs = result['outputs']; installed = Path(outputs['root'])
            for directory in (installed, Path(outputs['home']), Path(outputs['cwd']), installed/'bin'):
                self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
            self.assertEqual(list(Path(outputs['cwd']).iterdir()), [])
            self.assertEqual((installed/'NuGet.Config').stat().st_mode & 0o777, 0o600)

    def test_old_curl_does_not_download_and_versions_must_match(self):
        for version in ('7.88.1', '8.3.0', 'invalid'):
            with self.subTest(curl=version):
                result, seen, _ = self.run_native('snyk', curl_version=version)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(seen['events'], '')
                self.assertEqual(seen['published'], '')
        for which in ('snyk','semgrep'):
            with self.subTest(tool=which):
                result, seen, _ = self.run_native(which, tool_version='0.0.0')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(seen['published'], '')

    def test_native_package_manager_failure_does_not_publish_tools(self):
        for which in ('snyk', 'semgrep', 'dotnet'):
            with self.subTest(tool=which):
                result, seen, _ = self.run_native(which, fail_tool=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(seen['published'], '')
                self.assertNotIn('secret-sentinel', result.stdout+result.stderr)

    def test_package_failure_diagnostics_are_visible_bounded_and_control_safe(self):
        diagnostic = 'discarded-start '+('z'*12000)+'\x1b[31mnative dependency TLS failure\x1b[0m\r\n::error::untrusted\x07\n'
        for which in ('semgrep', 'dotnet'):
            with self.subTest(tool=which):
                result, seen, _ = self.run_native(which, fail_tool=True, tool_output=diagnostic)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(seen['published'], '')
                self.assertEqual(result.stdout, '')
                self.assertIn('native dependency TLS failure', result.stderr)
                self.assertIn('exit 23; timeout 600s', result.stderr)
                self.assertIn('Semgrep' if which == 'semgrep' else 'dotnet Sonar', result.stderr)
                self.assertNotIn('discarded-start', result.stderr)
                self.assertLessEqual(len(result.stderr.encode()), 4352)
                self.assertTrue(all(char == '\n' or 32 <= ord(char) <= 126 for char in result.stderr))
                self.assertFalse(any(line.startswith('::') for line in result.stderr.splitlines()))
                self.assertNotIn('secret-sentinel', result.stderr+seen['environment'])

    def test_timeout_and_missing_package_tools_have_actionable_diagnostics(self):
        for which in ('semgrep', 'dotnet'):
            with self.subTest(tool=which, reason='timeout'):
                result, seen, _ = self.run_native(which, fail_tool=True, fail_code=124)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('exit 124; timeout 600s', result.stderr)
                self.assertEqual(seen['published'], '')
            with self.subTest(tool=which, reason='missing'):
                result, seen, _ = self.run_native(which, tool_missing=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('exit 127; timeout 600s', result.stderr)
                self.assertIn('No such file or directory', result.stderr)
                self.assertEqual(seen['published'], '')

    def test_successful_package_installs_keep_native_output_quiet(self):
        for which in ('semgrep', 'dotnet'):
            with self.subTest(tool=which):
                result, seen, _ = self.run_native(which, tool_output='ordinary native installation progress\n')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout+result.stderr, '')
                self.assertNotEqual(seen['published'], '')


if __name__ == '__main__': unittest.main()
