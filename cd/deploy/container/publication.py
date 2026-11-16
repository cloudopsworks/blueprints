"""Shared registry publication commands for legacy and immutable deployments.

Legacy callers inherit docker/login-action's credential config. Immutable callers
supply a private authfile and bounded command adapter; tokens are never arguments.
No cloud acquisition or application source execution belongs in this primitive.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys

DIGEST = re.compile(r'sha256:[0-9a-f]{64}')


class PublicationError(Exception):
    pass


def inspect_digest(run, reference, *, authfile=None, anonymous=False):
    args = ['skopeo', 'inspect']
    if anonymous:
        args += ['--no-creds']
    elif authfile is not None:
        args += ['--authfile', str(authfile)]
    value = run(args + ['--format', '{{.Digest}}', 'docker://' + reference], json_output=False).strip()
    if not DIGEST.fullmatch(value):
        raise PublicationError('Registry returned an invalid digest')
    return value


def publish(run, *, transport, source, repository, tags=(), authfile=None,
            expected_digest=None, notice=print):
    """Perform the publication, rather than wrapping independent implementations.

    The legacy transports preserve their original commands and tagging behavior.
    Immutable transport always checks source, preserves bytes, then checks tag
    readback; it never accepts a rewritten digest or returns a mutable reference.
    """
    if transport == 'docker':
        run(['docker', 'image', 'load', '--input', source], json_output=False)
        run(['docker', 'image', 'push', '--all-tags', repository], json_output=False)
        return None
    if transport == 'crane':
        first, *remaining = tags
        target = repository + ':' + first
        run(['crane', 'push', source, target], json_output=False)
        notice('::notice::Pushed Docker image to ' + target)
        for tag in remaining:
            if tag != first:
                run(['crane', 'tag', target, tag], json_output=False)
                notice('::notice::Tagged Docker image to ' + repository + ':' + tag)
        return None
    if transport == 'oci-archive':
        if (not isinstance(expected_digest,str) or not DIGEST.fullmatch(expected_digest)
                or not source.startswith('oci-archive:') or not Path(source[len('oci-archive:'):]).is_file()
                or len(tags)!=1 or tags[0] not in ('main-'+expected_digest[7:],'preview-'+expected_digest[7:])):
            raise PublicationError('Verified archive publication requires an exact content tag')
        target=repository+':'+tags[0]
        auth=['--dest-authfile',str(authfile)] if authfile is not None else ['--dest-no-creds']
        run(['skopeo','copy','--all','--preserve-digests',*auth,source,'docker://'+target],json_output=False)
        if inspect_digest(run,target,authfile=authfile,anonymous=authfile is None)!=expected_digest:
            raise PublicationError('Destination registry rewrote the image digest')
        return repository+'@'+expected_digest
    if transport != 'skopeo' or not isinstance(expected_digest, str) or not DIGEST.fullmatch(expected_digest):
        raise PublicationError('Immutable publication requires an exact digest')
    if not source.endswith('@' + expected_digest) or authfile is None or tuple(tags) != ('sha256-' + expected_digest[7:],):
        raise PublicationError('Immutable source, tag or credentials differ')
    if inspect_digest(run, source, authfile=authfile) != expected_digest:
        raise PublicationError('Source image digest differs')
    target = repository + ':' + tags[0]
    run(['skopeo', 'copy', '--all', '--preserve-digests', '--authfile', str(authfile),
         'docker://' + source, 'docker://' + target], json_output=False)
    if inspect_digest(run, target, authfile=authfile) != expected_digest:
        raise PublicationError('Destination registry rewrote the image digest')
    return repository + '@' + expected_digest


def _legacy_run(argv, **kwargs):
    # Existing docker/login-action credentials are inherited, never reconstructed.
    subprocess.run(argv, check=True)
    return ''


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv not in (['legacy-docker'], ['legacy-crane']):
        raise PublicationError('Unknown legacy publication command')
    repository = '/'.join(os.environ[name] for name in
                          ('STEPS_DOCKER_REGISTRY_RESULT', 'INPUTS_PROJECT_OWNER', 'INPUTS_PROJECT_KEY'))
    if argv == ['legacy-docker']:
        publish(_legacy_run, transport='docker', source='docker-image.tar', repository=repository)
    else:
        print('::group::Push Docker image from tar using Crane', flush=True)
        # head -1 selects the first full line; the shell's original tag loop
        # splits every whitespace-delimited value, including repeated tags.
        text = Path('docker-tags.list').read_bytes().decode()
        first = text.split('\n', 1)[0]
        publish(_legacy_run, transport='crane', source='docker-image.tar', repository=repository,
                tags=[first, *[value for value in re.split(r'[ \t\n]+', text) if value]],
                notice=lambda value: print(value, flush=True))
        print('::endgroup::', flush=True)


if __name__ == '__main__':
    main()
