#!/usr/bin/env python3
"""Actual Go-template migration in a disposable copy; no importer or cloud calls."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from smoke_templates import Smoke, IGNORED


def yaml_read(path):
    return json.loads(subprocess.check_output(['ruby', '-ryaml', '-rjson', '-e',
        'puts JSON.generate(YAML.safe_load(File.read(ARGV[0])))', str(path)], text=True))


def hashes(root, pattern):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.glob(pattern) if p.is_file()}


def freeze_fixture(smoke, root):
    """Commit intended migrated sources, never restored/build outputs, for HEAD planning."""
    smoke.run(['git', 'add', '.'], root)
    staged = smoke.run(['git', 'diff', '--cached', '--name-only'], root).splitlines()
    generated = {'.bundle', 'target', 'build', 'node_modules', 'dist', 'obj'}
    assert not any(generated.intersection(Path(name).parts) or
        name.startswith('.cloudopsworks/out/') for name in staged), 'staged generated output'
    smoke.run(['git', '-c', 'user.name=Template smoke', '-c', 'user.email=smoke@example.invalid',
        '-c', 'commit.gpgsign=false', 'commit', '-m', 'Temporary migrated sources and bindings'], root)
    smoke.run(['git', 'ls-files', '--error-unmatch', 'components/rails-app/bin/rails'], root)


def bind_and_plan(smoke, root, path):
    """Exercise ordinary YAML bindings through the existing local manual planner."""
    updated = yaml_read(path)
    for component_id in ('api', 'web', 'worker'):
        updated['components'][component_id]['targets'] = ['aws-eks']
    smoke.yaml_write(path, updated)
    smoke.cli(root, 'validate')
    freeze_fixture(smoke, root)
    plan, _ = smoke.plan(root)
    expected = {name: component['targets'] for name, component in updated['components'].items()}
    assert {component['id']: component['targetIds'] for component in plan['components']} == expected, \
        'planned component bindings differ'
    assert [(target['id'], target['environment']) for target in plan['targets']] == [('aws-eks', 'dev')], \
        'planned target environment differs'
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tronador', type=Path, required=True)
    parser.add_argument('--go-template', type=Path, required=True)
    parser.add_argument('--monorepo', type=Path, required=True)
    parser.add_argument('--allow-network', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='cloudopsworks-go-migration-') as temporary:
        smoke = Smoke(args, Path(temporary).resolve())
        root = smoke.root/'migration'
        shutil.copytree(args.go_template.resolve(), root, ignore=IGNORED)
        (root/'Makefile').unlink(missing_ok=True)  # New component workflow is CLI-managed.
        workflows = hashes(root, '.github/workflows/*')
        versions = hashes(root, '.cloudopsworks/gitversion*')
        path = root/'.cloudopsworks/cloudopsworks-ci.yaml'
        legacy = yaml_read(path)
        original_deployments = legacy['cd']['deployments']
        original_gitflow = legacy['config']['gitFlow']
        api = root/'components/api'
        api.mkdir(parents=True)
        for name in ['go.mod', 'go.sum', 'main.go', 'version.go', 'internal']:
            if (root/name).exists():
                shutil.move(root/name, api/name)
        # Retain actual application source and version/GitFlow policy, not scaffold copies.
        component = yaml_read(args.monorepo.resolve()/'.cloudopsworks/cloudopsworks-ci.yaml')['components']['api']
        component['targets'] = []
        # A container projection is an explicit migration asset; application source stays untouched.
        shutil.copyfile(args.monorepo.resolve()/'components/api/Dockerfile', api/'Dockerfile')
        # Legacy template embeds a generated VERSION, normally supplied by its old CI.
        (api/'VERSION').write_text('0.1.0\n')
        dockerfile = api/'Dockerfile'
        dockerfile.write_text(dockerfile.read_text().replace('COPY .well-known /.well-known\n', ''))
        # Legacy application has no marker endpoint: preview activation is NOT proved here.
        smoke.yaml_write(path, {'schemaVersion': 2, 'config': legacy['config'],
            'components': {'api': component}, 'cd': {'deployments': original_deployments}})
        # Configure a previously provisioned target once; adding components needs no credentials.
        example = args.monorepo.resolve()/'.cloudopsworks/examples/vars/inputs-example-aws-eks.yaml'
        shutil.copyfile(example, root/'.cloudopsworks/vars/inputs-dev.yaml')
        # Legacy Go ignores all bin/ directories; adopt the existing monorepo policy
        # so Rails bin/rails remains source while nested native outputs stay ignored.
        shutil.copyfile(args.monorepo.resolve()/'.gitignore', root/'.gitignore')
        smoke.initialize(root)
        smoke.cli(root, 'validate')
        smoke.owners(root, [('api', 'go')])
        for component_id, language, framework in [('web', 'node', 'plain'),
                ('worker', 'java', 'plain'), ('ruby-app', 'ruby', 'plain'), ('rails-app', 'ruby', 'rails')]:
            smoke.cli(root, 'add', component_id, '--language', language, '--framework', framework)
            updated = yaml_read(path)
            assert updated['components'][component_id]['targets'] == []
            smoke.cli(root, 'validate')
            smoke.owners(root, [(component_id, language)])
            assert hashes(root, '.github/workflows/*') == workflows, 'add changed workflows'
        plan = bind_and_plan(smoke, root, path)
        assert yaml_read(path)['cd']['deployments'] == original_deployments
        assert yaml_read(path)['config']['gitFlow'] == original_gitflow
        assert hashes(root, '.cloudopsworks/gitversion*') == versions
        assert hashes(root, '.github/workflows/*') == workflows
        assert not (root/'Makefile').exists()
        evidence = {'status': 'passed', 'checks': smoke.checks,
            'plannedBindings': {component['id']: component['targetIds'] for component in plan['components']},
            'plannedTargetEnvironment': plan['targets'][0]['environment'],
            'migrationAssets': ['monorepo .gitignore', 'api Dockerfile', 'dev target YAML'],
            'preserved': ['GitFlow policy', 'cd.deployments', 'GitVersion files', 'workflow bytes'],
            'notExecuted': ['adapted hosted caller execution (central interface pending)',
                'Docker OCI package', 'live cloud mutation', 'live Kubernetes preview'],
            'scope': 'actual Go reference source migration and four CLI additions; not an arbitrary-hook importer'}
        if args.report:
            args.report.resolve().write_text(json.dumps(evidence, indent=2)+'\n')
        print(json.dumps(evidence, indent=2))


if __name__ == '__main__':
    main()
