"""Architectural regression boundary for the isolated composite-first slice.

This checks actual transitive production YAML, not a hand-written equivalent.
The old graph can be audited explicitly; it is not an allowed fallback.
"""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SLICE = '.github/workflows/monorepo-delivery-slice.yml'
EXPECTED = (
    'cd/tasks/repo/context/action.yml',
    'ci/monorepo/source/action.yml',
    'ci/monorepo/plan/action.yml',
    'ci/monorepo/build/action.yml',
    'ci/monorepo/artifact/action.yml',
    'ci/monorepo/stage/action.yml',
)
INTERPRETER = re.compile(
    r'\b(?:python(?:3(?:\.\d+)?)?|node|ruby|perl)\b\s*(?:[,\x27\x22]|-c\b|-e\b|<<|[^\n]*\.(?:py|[cm]?js|rb|pl)\b)')
DIRECT_INTERPRETER = re.compile(r'(?:^|[;\n])\s*(?:python3?|node|ruby|perl)\s+')
FIXTURE_AUTHORITY = re.compile(r'(?:tests/monorepo/fixtures|cd/monorepo/runtime)')
BUILTINS = {'fs', 'path', 'os', 'crypto', 'buffer', 'stream', 'url', 'util', 'zlib'}
# Do not interpret escaped delimiters; ambiguous quoted data is not exempt.
QUOTED_SHELL_DATA = r"(?:\"[^\"\\\n]*\"|'[^'\\\n]*')"
SHELL_DATA_STATEMENT = re.compile(
    r'\s*(?:echo\s+' + QUOTED_SHELL_DATA +
    r'(?:\s*>>?\s*(?:' + QUOTED_SHELL_DATA + r'|[A-Za-z0-9_./-]+))?'
    r'|(?:if|elif)\s+\[\s+-f\s+' + QUOTED_SHELL_DATA +
    r'\s+\]\s*;\s*then)\s*')


def shell_interpreter_invocation(text):
    # These complete builtin statements only inspect a path or emit quoted data.
    # Permit only plain variable expansion, never executable/special expansion.
    for line in text.replace('\\\n', '').splitlines():
        if not (INTERPRETER.search(line) or DIRECT_INTERPRETER.search(line)):
            continue
        special_expansion = re.search(r'`|\$(?![A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*\})', line)
        if not special_expansion and SHELL_DATA_STATEMENT.fullmatch(line):
            continue
        return True
    return False


# Only this signature-authenticated fixed vendor block may execute local binaries.
# All surrounding shell remains subject to every detector; changes require review.
AWS_VENDOR_SETUP = r'''if [ "$PROVIDER" = aws ]; then
  dir=$(mktemp -d "$RUNNER_TEMP/aws-cli.XXXXXX")
  curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 https://awscli.amazonaws.com/awscli-exe-linux-x86_64-2.40.1.zip -o "$dir/aws.zip"
  # AWS CLI Team signature verified: FB5DB77FD5C118B80511ADA8A6310ACC4672475C.
  printf '%s  %s\n' fddb097a8ea197dc9beed9e4426ef99aded612a52df64581e079b6e8817e1d24 "$dir/aws.zip" | sha256sum --check --strict
  unzip -q "$dir/aws.zip" -d "$dir"
  "$dir/aws/install" --install-dir "$dir/install" --bin-dir "$dir/bin"
  echo "$dir/bin" >> "$GITHUB_PATH"
  "$dir/bin/aws" --version | grep -F 'aws-cli/2.40.1 '
'''


def yaml_file(path):
    result = subprocess.run(
        ['yq', '-o=json', '-I=0', '.', str(path)], capture_output=True,
        text=True, timeout=10, check=True,
        env={'PATH': os.environ.get('PATH', '')})
    if len(result.stdout) > 4 * 1024 * 1024:
        raise ValueError('Production YAML exceeds boundary inspection limit')
    return json.loads(result.stdout)


def code_violations(text, *, github_script=False):
    failures = []
    # In inline JS, quoted language IDs are data, not executable entrypoints.
    # Shell quoted data is inert only in narrowly bounded builtin statements.
    if (not github_script and shell_interpreter_invocation(text)) or (
            github_script and DIRECT_INTERPRETER.search(text)):
        failures.append('custom source interpreter entrypoint')
    if FIXTURE_AUTHORITY.search(text):
        failures.append('rejected runtime or test-fixture production authority')
    if re.search(r'\bgo\s+run\b', text):
        failures.append('source compilation as orchestration')
    if re.search(r'[\x27\x22]go[\x27\x22]\s*,\s*\[\s*[\x27\x22](?:run|build|install)[\x27\x22]', text):
        failures.append('source compilation installer through executable API')
    # A bare JS `source = ...` assignment is data flow, not shell sourcing.
    # Keep the shell detector unchanged for actual run bodies.
    source = r'source(?!\s*=)\s+' if github_script else r'source\s+'
    if re.search(r'(?:^|[;\n])\s*(?:' + source + r'|\.\s+|(?:bash|sh)\s+(?:-[^\s]+\s+)*)(?:[^\n;]+)', text):
        failures.append('custom shell helper execution or sourcing')
    if re.search(r'\|\s*(?:bash|sh)(?:\s|$)', text):
        failures.append('custom shell installer pipeline')
    if re.search(r'(?:^|[;\n])\s*(?:\./[^\s;]+|[\x27\x22]?\$[A-Za-z_{])', text):
        failures.append('local or dynamic executable entrypoint')
    if github_script:
        if '${{' in text:
            failures.append('GitHub expression interpolated into JavaScript')
        if re.search(r'\b(?:eval\s*\(|new\s+Function\b|AsyncFunction\b|import\s*\()', text):
            failures.append('dynamic executable source')
        for module in re.findall(r'\brequire\s*\(\s*[\x27\x22]([^\x27\x22]+)[\x27\x22]\s*\)', text):
            if module.removeprefix('node:').split('/')[0] not in BUILTINS:
                failures.append(f'non-builtin imported implementation: {module}')
        if re.search(r'\brequire\s*\(\s*[^\s\x27\x22]', text):
            failures.append('dynamic module loader')
        if re.search(r'\b(?:exec|getExecOutput|execFile|spawn)\s*\(\s*[\x27\x22](?:bash|sh|node|python3?|ruby|perl)[\x27\x22]', text):
            failures.append('interpreter escape through executable API')
        if re.search(r'\bexec\.(?:exec|getExecOutput)\s*\(\s*(?![\x27\x22])[^\s]', text):
            failures.append('dynamic executable argv')
    return failures


def resolve_use(uses, root=ROOT):
    if uses.startswith('./bp/'):
        relative = uses[len('./bp/'):]
    elif uses.startswith('./'):
        relative = uses[2:]
    elif uses.startswith('cloudopsworks/blueprints/'):
        relative = uses.split('@', 1)[0][len('cloudopsworks/blueprints/'):]
    else:
        return None
    path = root / relative
    if path.is_dir():
        candidates = [path / name for name in ('action.yml', 'action.yaml')]
        path = next((item for item in candidates if item.is_file()), candidates[0])
    resolved = path.resolve()
    resolved.relative_to(root.resolve())
    return resolved


def audit_graph(entry, root=ROOT):
    pending = [root / entry]
    visited, violations = set(), []
    while pending:
        path = pending.pop().resolve()
        if path in visited:
            continue
        visited.add(path)
        relative = str(path.relative_to(root.resolve()))
        if not path.is_file():
            violations.append((relative, 'missing local workflow/action'))
            continue
        document = yaml_file(path)
        if not isinstance(document, dict):
            violations.append((relative, 'invalid workflow/action mapping'))
            continue
        is_workflow = 'jobs' in document
        if not is_workflow and document.get('runs', {}).get('using') != 'composite':
            violations.append((relative, 'local custom runtime action is not a maintained composite'))
        jobs = document.get('jobs', {}).values() if is_workflow else [document.get('runs', {})]
        for job in jobs:
            if not isinstance(job, dict):
                continue
            items = [job] if 'uses' in job else job.get('steps', [])
            for step in items:
                uses = step.get('uses', '')
                if uses:
                    try:
                        dependency = resolve_use(uses, root)
                    except ValueError:
                        violations.append((relative, 'local action escapes Blueprint root'))
                        continue
                    if dependency is not None:
                        pending.append(dependency)
                if 'run' in step:
                    if is_workflow:
                        violations.append((relative, 'workflow has direct run logic instead of composition'))
                    shell = step['run']
                    if (relative == 'cd/monorepo/tools/action.yml'
                            and step.get('shell') == 'bash'
                            and step.get('env') == {'PROVIDER': '${{ inputs.provider }}'}
                            and shell.startswith('set -euo pipefail\n')
                            and shell.count(AWS_VENDOR_SETUP) == 1):
                        shell = shell.replace(AWS_VENDOR_SETUP, '', 1)
                    for problem in code_violations(shell):
                        violations.append((relative, problem))
                if uses.startswith('actions/github-script@'):
                    if uses != 'actions/github-script@v9':
                        violations.append((relative, 'custom inline logic must use github-script v9'))
                    script = step.get('with', {}).get('script', '')
                    if not isinstance(script, str) or not script.strip():
                        violations.append((relative, 'missing inline action script'))
                    else:
                        for problem in code_violations(script, github_script=True):
                            violations.append((relative, problem))
    return {'paths': sorted(str(p.relative_to(root.resolve())) for p in visited),
            'violations': [{'path': p, 'reason': reason} for p, reason in violations]}


class DetectorBehaviorTests(unittest.TestCase):
    def test_native_binary_calls_are_not_custom_source(self):
        for command in ['tronador components validate --json',
                        'terraform plan -out=private.tfplan',
                        "await exec.exec('tronador', ['components', 'validate']);"]:
            self.assertEqual(code_violations(command, github_script=True), [])

    def test_python_and_javascript_wrappers_are_rejected(self):
        for command in ['python3 runtime/workflow.py plan',
                        'node runtime/entry.mjs',
                        "await exec.exec('python3', ['runtime/entry.py']);",
                        "await exec.getExecOutput('python3', ['runtime/entry.py']);",
                        "await exec.getExecOutput('ruby', ['runtime/entry.rb']);"]:
            self.assertTrue(code_violations(command, github_script=True), command)

    def test_language_identifiers_are_data_not_custom_interpreter_calls(self):
        self.assertEqual(code_violations(
            "const allowed = ['node', 'go', 'python', 'ruby'];",
            github_script=True), [])

    def test_shell_quoted_language_and_application_data_are_not_entrypoints(self):
        for code in [
                'if [ -f ".cloudopsworks/.python" ]; then',
                'elif [ -f ".cloudopsworks/.node" ]; then',
                '  echo "Module type is python"',
                "echo 'Module type is ruby'",
                'echo "web: ${INPUTS_PYTHON_APM} python3 main.py" > Procfile',
                'echo "python3 main.py; node runtime.js" >> "$GITHUB_OUTPUT"']:
            with self.subTest(data=code):
                self.assertEqual(code_violations(code), [])

    def test_shell_data_statements_cannot_hide_executable_neighbors(self):
        for code in [
                'echo "python3 main.py"; node runtime.js',
                'echo "node runtime.js" && python3 runtime.py',
                'echo "python3 main.py" | node runtime.js',
                'echo "$(python3 runtime.py)"',
                'echo "`node runtime.js`"',
                'echo "${OUTPUT:-$(python3 runtime.py)}"',
                'echo "${GENERATED@P} python3 main.py"',
                'echo "python3 main.py" > "$(node runtime.js)"',
                'if [ -f "$(python3 runtime.py)" ]; then',
                'elif [ -f ".cloudopsworks/.node" ]; then node runtime.js',
                'echo "python3 main.py"\n"$CONTROL_BIN" argument',
                'echo "python3 main.py"\nsource ./runtime.sh',
                'echo "python3 main.py"\n. ./runtime.env',
                'echo "python3 main.py"\ncat install.sh | bash']:
            with self.subTest(code=code):
                self.assertTrue(code_violations(code), code)

    def test_escaped_quotes_cannot_hide_recorded_interpreter_execution(self):
        for redirect in ['>', '>>']:
            for interpreter in ['node', 'ruby', 'perl', 'python3']:
                code = f'echo "python3 main.py\\" {redirect} "; {interpreter} runtime.js #"'
                with self.subTest(code=code), tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    recorder = root / interpreter
                    recording = root / 'invocations'
                    recorder.write_text('#!/bin/sh\n' +
                                        'printf "%s\\n" "$@" >> "$RECORDING"\n')
                    recorder.chmod(0o700)
                    result = subprocess.run(
                        ['/bin/bash', '-c', code], cwd=root,
                        env={'PATH': str(root), 'RECORDING': str(recording)},
                        capture_output=True, text=True, timeout=10, check=False)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(recording.read_text().splitlines(), ['runtime.js'])
                    self.assertIn('custom source interpreter entrypoint', code_violations(code))

    def test_shell_interpreter_command_positions_remain_rejected(self):
        for code in [
                'python3 runtime.py', 'node runtime.mjs',
                "'python3' runtime.py", '"node" runtime.js',
                'env -i PATH="$PATH" python3 runtime.py',
                'env MODE=checked node runtime.mjs',
                'env -i python3 \\\n runtime.py',
                'no\\\nde runtime.mjs',
                'result=$(python3 runtime.py)', 'result=`node runtime.js`',
                'printf x | python3 runtime.py',
                "python3 <<'PY'\nprint('runtime')\nPY"]:
            with self.subTest(code=code):
                self.assertIn('custom source interpreter entrypoint', code_violations(code))

    def test_existing_legacy_data_graphs_do_not_execute_custom_interpreters(self):
        for entry in ['cd/checkout/action.yml', 'cd/deploy/app/aws/action.yml',
                      'cd/deploy/app/gcp/action.yml']:
            with self.subTest(entry=entry):
                report = audit_graph(entry)
                self.assertEqual(report['violations'], [], json.dumps(report, indent=2))

    def test_javascript_source_assignment_is_not_shell_sourcing(self):
        for code in ['source = pull.merge_commit_sha;',
                     'source  = pull.merge_commit_sha;',
                     'let source;\nsource = pull.merge_commit_sha;']:
            with self.subTest(code=code):
                self.assertEqual(code_violations(code, github_script=True), [])

    def test_shell_sourcing_and_javascript_shell_escapes_remain_rejected(self):
        for code in ['source ./control.sh', 'source  ./control.sh',
                     'source = ./control.sh', '. ./control.env']:
            with self.subTest(shell=code):
                self.assertIn('custom shell helper execution or sourcing',
                              code_violations(code))
        for code in ["await exec.exec('bash', ['-c', 'source ./control.sh']);",
                     "await exec.getExecOutput('sh', ['-c', '. ./control.env']);"]:
            with self.subTest(javascript=code):
                self.assertIn('interpreter escape through executable API',
                              code_violations(code, github_script=True))

    def test_local_implementation_imports_and_injected_expressions_are_rejected(self):
        for code in ["require('./runtime.js')", "require(name)",
                     "const x = '${{ inputs.command }}';", "eval(source)",
                     "await import('./runtime.mjs')"]:
            self.assertTrue(code_violations(code, github_script=True), code)
        self.assertEqual(code_violations("require('node:fs'); require('path');",
                                         github_script=True), [])

    def test_compilation_shell_helpers_and_dynamic_native_escape_are_rejected(self):
        for code in ['go run orchestration.go', 'source ./control.sh',
                     '. ./control.env', 'bash ./control.sh', './runtime/control',
                     '"$CONTROL_BIN" argument',
                     "await exec.exec('go', ['run', 'orchestration.go']);",
                     "await exec.exec('go', ['build', './cmd/control']);",
                     'await exec.getExecOutput(tool, args);']:
            self.assertTrue(code_violations(code, github_script=True), code)

    def test_local_node_and_docker_runtime_actions_cannot_pass_as_composites(self):
        for using in ['node24', 'node20', 'python', 'docker']:
            with self.subTest(using=using), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (root / 'action.yml').write_text(f'runs:\n  using: {using}\n  main: control.js\n')
                report = audit_graph('action.yml', root)
                self.assertIn('local custom runtime action is not a maintained composite',
                              [item['reason'] for item in report['violations']])

    def test_bp_local_action_mapping_and_missing_dependency_are_observable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'entry.yml').write_text('jobs:\n  build:\n    steps:\n      - uses: ./bp/ci/missing\n')
            report = audit_graph('entry.yml', root)
            self.assertIn('ci/missing', report['paths'])
            self.assertEqual(report['violations'][0]['reason'], 'missing local workflow/action')


class IsolatedSliceBoundaryTests(unittest.TestCase):
    def test_named_slice_composites_exist_before_the_slice_can_pass(self):
        for relative in EXPECTED:
            with self.subTest(action=relative):
                self.assertTrue((ROOT / relative).is_file(), f'missing slice composite: {relative}')

    def test_actual_slice_transitive_graph_has_no_rejected_runtime(self):
        report = audit_graph(SLICE)
        self.assertEqual(report['violations'], [], json.dumps(report, indent=2))
        self.assertTrue(set(EXPECTED).issubset(report['paths']),
                        'slice must execute named composites, not just add unused action files')


if __name__ == '__main__':
    if '--audit' in os.sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument('--audit', required=True)
        args = parser.parse_args()
        report = audit_graph(args.audit)
        print(json.dumps(report, indent=2))
        raise SystemExit(bool(report['violations']))
    unittest.main()
