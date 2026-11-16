#!/usr/bin/env python3
"""Extract actual inline action bodies for LOCAL Node tests; never used by CI actions."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


BLUEPRINTS = Path(__file__).resolve().parents[3]
SLICE_ACTIONS = (
    'cd/tasks/repo/context/action.yml',
    'ci/monorepo/source/action.yml',
    'ci/monorepo/plan/action.yml',
    'ci/monorepo/build/action.yml',
    'ci/monorepo/artifact/action.yml',
    'ci/monorepo/artifact/transport/action.yml',
    'ci/monorepo/stage/action.yml',
)


def read_yaml(path):
    result = subprocess.run(
        ['yq', '-o=json', '-I=0', '.', str(path)],
        capture_output=True, text=True, timeout=10, check=True,
        env={'PATH': os.environ.get('PATH', '')})
    if len(result.stdout) > 4 * 1024 * 1024:
        raise ValueError('Action YAML exceeds local extraction limit')
    return json.loads(result.stdout)


def extract(action_path):
    path = (BLUEPRINTS / action_path).resolve(strict=True)
    path.relative_to(BLUEPRINTS)
    action = read_yaml(path)
    if action.get('runs', {}).get('using') != 'composite':
        raise ValueError(f'{action_path}: expected a composite action')
    scripts = []
    for index, step in enumerate(action['runs'].get('steps', [])):
        if step.get('uses') != 'actions/github-script@v9':
            continue
        script = step.get('with', {}).get('script')
        if not isinstance(script, str) or not script.strip():
            raise ValueError(f'{action_path}: missing github-script body')
        identifier = step.get('id') or step.get('name') or f'step-{index}'
        scripts.append({'id': identifier, 'index': index,
                        'script': script, 'env': step.get('env', {})})
    return {'path': action_path, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'inputs': action.get('inputs', {}),
            'outputs': action.get('outputs', {}), 'scripts': scripts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--action', action='append', dest='actions')
    args = parser.parse_args()
    if not (BLUEPRINTS / 'AGENTS.md').is_file():
        parser.error('Blueprint repository root could not be verified')
    bundle = {'actions': {path: extract(path)
                          for path in (args.actions or SLICE_ACTIONS)}}
    args.out.mkdir(mode=0o700, parents=True, exist_ok=True)
    output = args.out / 'actions.json'
    output.write_text(json.dumps(bundle, indent=2) + '\n')
    output.chmod(0o600)
    print(output)


if __name__ == '__main__':
    main()
