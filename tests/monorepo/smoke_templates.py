#!/usr/bin/env python3
"""Real, temporary-copy template smoke tests; never deploy or publish anything.

Example: python3 tests/monorepo/smoke_templates.py --tronador /path/tronador \
  --monorepo ../monorepo-app-template --ruby ../ruby-app-template --allow-network
Docker/OCI and absent exact optional runtimes are reported as gaps, never passes.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

BLUEPRINTS = Path(__file__).resolve().parents[2]
IGNORED = shutil.ignore_patterns('.git', '.idea', '.omx', 'out', 'node_modules',
    '.bundle', '.venv', '__pycache__', 'target', 'obj', 'log', 'tmp')


class Smoke:
    def __init__(self, args, temporary):
        self.args, self.root = args, temporary
        self.binary = str(args.tronador.resolve())
        self.checks, self.gaps = [], []
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(
            ('AWS_', 'AZURE_', 'ARM_', 'GOOGLE_', 'GCLOUD_', 'GH_', 'GITHUB_', 'CLOUDOPSWORKS_'))}
        for name in ('KUBECONFIG', 'BOT_TOKEN', 'BOT_TOKEN_SCOPED', 'DEPLOYMENT_STATE_CONF',
                'SONARQUBE_TOKEN', 'SNYK_TOKEN', 'SEMGREP_TOKEN', 'DEPENDENCYTRACK_TOKEN',
                'DOCKER_AUTH_CONFIG', 'ACTIONS_ID_TOKEN_REQUEST_TOKEN', 'ACTIONS_ID_TOKEN_REQUEST_URL'):
            self.env.pop(name, None)
        self.env['GIT_TERMINAL_PROMPT'] = '0'
        self.env['GOTOOLCHAIN'] = 'local'

    def run(self, argv, root, *, env=None, json_output=False, timeout=600, input_text=None):
        start = time.monotonic()
        result = subprocess.run([str(a) for a in argv], cwd=root,
            env={**self.env, **(env or {})}, capture_output=True, text=True, timeout=timeout, input=input_text)
        if result.returncode:
            raise RuntimeError(f'{argv[:5]} in {root.name} failed ({result.returncode}): '
                               + result.stderr[-6000:] + result.stdout[-3000:])
        self.checks.append({'repository': root.name, 'command': [str(a) for a in argv],
                            'seconds': round(time.monotonic()-start, 3), 'status': 'passed'})
        return json.loads(result.stdout) if json_output else result.stdout

    def cli(self, root, *arguments, **kwargs):
        return self.run([self.binary, 'components', *arguments, '--workdir', root, '--json'],
                        root, json_output=True, **kwargs)

    def initialize(self, root):
        self.run(['git', 'init', '-b', 'main'], root)
        self.run(['git', 'add', '.'], root)
        self.run(['git', '-c', 'user.name=Template smoke', '-c', 'user.email=smoke@example.invalid',
                  '-c', 'commit.gpgsign=false', 'commit', '-m', 'Temporary smoke fixture'], root)

    def plan(self, root):
        record = self.cli(root, 'plan', '--all', '--event', 'manual', '--version', '0.1.0',
                         '--repository-id', '12345', '--repository-name', 'example/template-smoke')
        path = root / 'build-plan.json'
        path.write_text(json.dumps(record))
        return record, path

    def operation(self, root, component, operation, *, env=None):
        argv = [operation, component, '--no-install-tools']
        if self.args.allow_network:
            argv.append('--allow-network')
        return self.cli(root, *argv, env=env)

    def java_environment(self):
        if sys.platform != 'darwin':
            return {}
        # Homebrew's unrelated executable named `test` breaks the official mvnw
        # POSIX script. Do not modify the wrapper or require a global workaround.
        java = subprocess.run(['/usr/libexec/java_home', '-v', '17'], capture_output=True, text=True)
        return {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin',
                'JAVA_HOME': java.stdout.strip()} if java.returncode == 0 else {}

    def structure(self, root):
        assert not list(root.rglob('Makefile')), 'template must not contain a Makefile'
        for filename in ('AGENTS.md', 'CLAUDE.md', 'README.yaml', 'README.md'):
            assert (root / filename).is_file(), filename
        assert '@AGENTS.md' in (root / 'CLAUDE.md').read_text()
        assert not list((root/'.cloudopsworks/examples').rglob('*.json')), 'human examples must be YAML'
        self.cli(root, 'validate')
        self.cli(root, 'build', '--all', '--dry-run')
        self.cli(root, 'test', '--all', '--dry-run')
        labeler = (root / '.cloudopsworks/labeler.yml').read_text()
        for component in self.cli(root, 'list'):
            assert 'component/' + component['id'] + ':' in labeler
        schema = self.run([self.binary, 'components', 'schema', '--json'], root)
        assert json.loads(schema) == json.loads((root / '.cloudopsworks/schemas/cloudopsworks-ci-v2.schema.json').read_text())
        if shutil.which('actionlint'):
            self.run(['actionlint', *sorted((root/'.github/workflows').glob('*.yml')), *sorted((root/'.github/workflows').glob('*.yaml'))], root)
        else:
            self.gaps.append('actionlint unavailable: workflow static validation not executed')
        for ignored in ('components/example/node_modules/file.js', 'components/example/target/app',
                        '.cloudopsworks/out/example/result.json', 'components/example/.env'):
            self.run(['git', 'check-ignore', '--no-index', ignored], root)
        rails = subprocess.run(['git', 'check-ignore', '--no-index', 'bin/rails'], cwd=root, capture_output=True)
        assert rails.returncode == 1, 'bin/rails must be committable'

    def caller_contract(self, root):
        fixture = json.loads((BLUEPRINTS/'tests/monorepo/fixtures/revision_callers.json').read_text())
        for row in fixture['callers']:
            path = root/'.github/workflows'/row['caller']
            source = self.run(['ruby', '-ryaml', '-rjson', '-e',
                'd=YAML.safe_load(File.read(ARGV[0])); d["on"]=d.delete(true) if d.key?(true); puts JSON.generate(d)', path], root,
                json_output=True)
            job = source['jobs'][row['jobId']]
            assert job['name'] == row['displayName']
            assert job['uses'] == 'cloudopsworks/blueprints/'+row['reusable']+'@'+fixture['blueprintRef']
            assert job['permissions'] == row['permissions']
            assert job.get('secrets', {}) == {k: '${{ secrets.'+v+' }}' for k, v in row['secrets'].items()}
            assert set(job.get('with', {})) == set(row['inputs'])
            assert source['permissions'] == {}, 'permissions belong to bounded jobs'
            if row['jobId'] == 'preview':
                assert "github.event.workflow_run.event == 'pull_request'" in job['if']
                assert "github.event.workflow_run.conclusion == 'success'" in job['if']
        assert not any((root/'.github/workflows'/name).exists() for name in ('ci.yml','release.yml','preview.yml'))

    def examples(self, root):
        # Operator examples use the sole public YAML loader, not a second JSON tree.
        examples = sorted((root/'.cloudopsworks/examples/vars').glob('inputs-*.yaml'))
        assert len(examples) == 17
        destination = root/'.cloudopsworks/vars/inputs-prod.yaml'
        original = destination.read_text()
        try:
            for example in examples:
                destination.write_text(example.read_text())
                validated = self.cli(root, 'validate')
                if example.name == 'inputs-example-gcp-appengine.yaml':
                    target = validated['resolved']['targets'][0]
                    projection = target['appConfigResolved']
                    assert projection['sourceDigest'] == 'sha256:'+hashlib.sha256((root/target['appConfig']).read_bytes()).hexdigest()
                    assert projection['service'] == 'api' and projection['entrypoint'] == 'python app.py'
                    assert 'appConfigResolved' not in example.read_text(), 'projection must not be human authored'
                    for filename, runtime in [('app-flex-native.yaml', 'python'), ('app-flex-container.yaml', 'custom')]:
                        text = example.read_text().replace('app-standard.yaml', filename)
                        if runtime == 'custom':
                            text = text.replace('        entrypoint: python app.py\n', '')
                        destination.write_text(text)
                        resolved = self.cli(root, 'validate')['resolved']['targets'][0]
                        assert resolved['appConfigResolved']['environment'] == 'flexible'
                        assert resolved['appConfigResolved']['runtime'] == runtime
                        assert resolved['appConfigResolved']['sourceDigest'] == 'sha256:'+hashlib.sha256((root/resolved['appConfig']).read_bytes()).hexdigest()
        finally:
            destination.write_text(original)

    def yaml_write(self, path, value):
        # Ruby/Psych is already a declared smoke runtime; no PyYAML dependency.
        result = subprocess.run(['ruby', '-rjson', '-ryaml', '-e',
            'puts YAML.dump(JSON.parse(STDIN.read))'], input=json.dumps(value),
            capture_output=True, text=True, env=self.env, check=True)
        path.write_text(result.stdout)

    def settings(self, root):
        for path in sorted((root/'.cloudopsworks/examples/protected').glob('*.yaml')):
            self.run([self.binary, 'components', 'settings', '--kind', path.stem, '--json'],
                root, json_output=True, input_text=path.read_text())

    def owners(self, root, ids):
        for component, language in ids:
            env = self.java_environment() if language == 'java' else None
            self.operation(root, component, 'build', env=env)
            self.operation(root, component, 'test', env=env)

    def generation(self, root):
        for component, language, framework in [('dotnet-demo','dotnet','plain'),
                ('python-demo','python','plain'), ('rust-demo','rust','plain'),
                ('ruby-demo','ruby','plain'), ('rails-demo','ruby','rails')]:
            before = {p.relative_to(root) for p in root.rglob('*')}
            self.cli(root, 'add', component, '--language', language, '--framework', framework, '--dry-run')
            assert before == {p.relative_to(root) for p in root.rglob('*')}, 'add dry-run wrote files'
            self.cli(root, 'add', component, '--language', language, '--framework', framework)
            self.cli(root, 'validate')
            self.cli(root, 'build', component, '--dry-run')
            self.cli(root, 'test', component, '--dry-run')
            assert 'configuration:' in (root/'.cloudopsworks/labeler.yml').read_text(), 'add lost custom labels'
            if language == 'rust':
                version = subprocess.run(['rustc', '--version'], capture_output=True, text=True) if shutil.which('rustc') else None
                if not version or 'rustc 1.90.0 ' not in version.stdout:
                    self.gaps.append('Rust scaffold generated/dry-run validated; declared rustc1.90.0 not installed for real build')
                    continue
            tool = {'dotnet':'dotnet','python':'python3','rust':'rustc','ruby':'ruby'}[language]
            if shutil.which(tool):
                self.owners(root, [(component, language)])
            else:
                self.gaps.append(f'{language} scaffold generated/dry-run validated; {tool} absent for real build')

    def owner_closure(self, source):
        """Actual source CLI -> workflow build/test/package, without a Docker fake.

        The temporary fixture gives Go owner `api` a Node dependency and OpenAPI
        package projection; this does not claim an OCI build on a Dockerless host.
        """
        root = self.root/'owner-closure'
        shutil.copytree(source, root, ignore=IGNORED)
        components = self.cli(root, 'list')
        source_components = {}
        for c in components:
            tool = {'go':'go', 'node':'node', 'java':'java'}[c['language']]
            runtime = next(t['version'] for t in c['toolchains'] if t['tool']==tool)
            build = {'profile': c['buildProfile']}
            if tool == 'node':
                build['packageManagerVersion'] = next(t['version'] for t in c['toolchains'] if t['tool']=='npm')
            source_components[c['id']] = {'path':c['path'],'language':c['language'],
                'framework':c['framework'],'runtime':runtime,'build':build,'package':c['package'],
                'workload':c['workload'],'preview':c['preview'],'dependsOn':c['dependsOn'],
                'watch':[],'targets':[]}
        source_components['api'].update(dependsOn=['web'], package={'kind':'openapi','file':'openapi.json','version':'3.0'},
            workload={'kind':'api'}, preview={'mode':'artifact-only','reason':'openapi'})
        (root/'components/api/openapi.json').write_text(json.dumps({'openapi':'3.0.3',
            'info':{'title':'Owner closure fixture','version':'0.1.0'},'paths':{}}))
        self.yaml_write(root/'.cloudopsworks/cloudopsworks-ci.yaml', {'schemaVersion':2,
            'config':{'gitFlow':{'enabled':True}},'ci':{'sharedPaths':['.github/**'],'maxParallel':4},
            'components':source_components,'cd':{'deployments':{},'preview':{'config':''}}})
        self.initialize(root)
        record, path = self.plan(root)
        row = next(r for r in record['matrix']['include'] if r['componentId']=='api')
        assert row['closure'] == ['web', 'api'], row
        bindir = self.root/'tools';bindir.mkdir()
        (bindir/'tronador').symlink_to(self.binary)
        self.run([sys.executable, BLUEPRINTS/'cd/monorepo/runtime/workflow.py', 'build',
            '--root', root, '--plan', path, '--component', 'api', '--bundle', root/'bundle'], root,
            env={'PATH': str(bindir)+os.pathsep+self.env['PATH']})
        result = json.loads((root/'bundle/results/api.json').read_text())
        assert result['kind']=='ComponentResult' and result['componentId']=='api'
        assert not (root/'bundle/results/web.json').exists(), 'dependency emitted duplicate owner result'
        artifact = root/'bundle'/result['mainArtifact']['location']['path']
        assert 'sha256:'+hashlib.sha256(artifact.read_bytes()).hexdigest()==result['mainArtifact']['digest']
        assert result['previewArtifact'] is None

    def package(self, root):
        record, plan = self.plan(root)
        self.cli(root, 'package', '--all', '--plan', plan, '--dry-run')
        docker = shutil.which('docker')
        available = subprocess.run([docker, 'info'], capture_output=True, timeout=20).returncode == 0 if docker else False
        if not available:
            self.gaps.append(root.name+': actual OCI+container preview packaging not executed (Docker daemon unavailable)')
            return
        if not self.args.allow_network:
            self.gaps.append(root.name+': actual OCI packaging requires explicit --allow-network for base image resolution')
            return
        results = self.cli(root, 'package', '--all', '--plan', plan, '--allow-network')
        for result in results if isinstance(results,list) else [results]:
            assert result['status']=='succeeded'
            for role in ('mainArtifact','previewArtifact'):
                assert (root/result[role]['location']['path']).is_file()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tronador',type=Path,required=True)
    parser.add_argument('--monorepo',type=Path,required=True)
    parser.add_argument('--ruby',type=Path,required=True)
    parser.add_argument('--allow-network',action='store_true',help='Permit dependency restores and image base resolution')
    parser.add_argument('--report',type=Path,help='Optional JSON evidence output')
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='cloudopsworks-template-smoke-') as temporary:
        smoke=Smoke(args,Path(temporary).resolve())
        mono,ruby=smoke.root/'monorepo',smoke.root/'ruby'
        shutil.copytree(args.monorepo.resolve(),mono,ignore=IGNORED)
        shutil.copytree(args.ruby.resolve(),ruby,ignore=IGNORED)
        for root in (mono,ruby):
            smoke.initialize(root);smoke.structure(root);smoke.caller_contract(root);smoke.examples(root);smoke.settings(root)
        smoke.owners(mono,[('api','go'),('web','node'),('worker','java')])
        smoke.owners(ruby,[('app','ruby')])
        smoke.package(mono);smoke.package(ruby)
        smoke.owner_closure(mono)
        smoke.generation(mono)
        rails=smoke.root/'standalone-rails'
        smoke.run([smoke.binary,'components','new',rails,'--language','ruby','--framework','rails','--json'],smoke.root)
        smoke.cli(rails,'validate');smoke.owners(rails,[('app','ruby')])
        evidence={'status':'passed-with-explicit-gaps' if smoke.gaps else 'passed',
            'checks':smoke.checks,'gaps':smoke.gaps,
            'notExecuted':['live cloud deployments','hosted GitHub Actions','live Kubernetes isolation/cleanup']}
        if args.report:
            args.report.resolve().write_text(json.dumps(evidence,indent=2)+'\n')
        print(json.dumps(evidence,indent=2))


if __name__=='__main__':
    main()
