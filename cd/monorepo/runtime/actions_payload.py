"""Fetch exact Actions payload bytes from an independently authorized manifest.

This is transport/digest verification, NEVER publication/caller/scan authority.
Callers must first verify the trusted stage host binding. No name-only artifact
selection, arbitrary URLs, extraction of sibling files, or raw logs are allowed.
"""
import io
import os
from pathlib import Path
import re
import zipfile
from contracts import fail,safe_path,validate_artifact

MAX_BUNDLE=1024*1024*1024


def fetch_payload(github,artifact,repository,destination):
    location=artifact.get('location',{})
    if (location.get('kind')!='actions-artifact' or location.get('repositoryId')!=repository['id']
            or github.repository!=repository['fullName']):
        fail('actions-payload-repository','payload transport crosses repository identity')
    for key in ('runId','runAttempt','artifactId'):
        if not isinstance(location.get(key),str) or not re.fullmatch(r'[1-9][0-9]*',location[key]):
            fail('actions-payload-identity','payload API identity is invalid')
    expected_prefix='components-'+location['runId']+'-'+location['runAttempt']+'-'
    if not isinstance(location.get('artifactName'),str) or not re.fullmatch(
            re.escape(expected_prefix)+r'[a-z][a-z0-9-]{0,47}',location['artifactName']):
        fail('actions-payload-name','component artifact name differs from fixed publication contract')
    relative=location['path'];safe_path(relative,output=True)
    run=github.repo('GET',f'/actions/runs/{location["runId"]}/attempts/{location["runAttempt"]}')
    current=(run and run.get('status')=='in_progress' and location['runId']==os.environ.get('GITHUB_RUN_ID')
             and location['runAttempt']==os.environ.get('GITHUB_RUN_ATTEMPT'))
    if (not run or str(run.get('id'))!=location['runId'] or str(run.get('run_attempt'))!=location['runAttempt']
            or str(run.get('repository',{}).get('id'))!=repository['id'] or run.get('head_sha')!=artifact['sourceSha']
            or not (run.get('status')=='completed' or current)):
        fail('actions-payload-run','immutable source run attempt is missing or mismatched')
    metadata=github.repo('GET','/actions/artifacts/'+location['artifactId'])
    if (not metadata or str(metadata.get('id'))!=location['artifactId'] or metadata.get('name')!=location['artifactName']
            or metadata.get('expired') is not False or str(metadata.get('workflow_run',{}).get('id'))!=location['runId']
            or metadata.get('workflow_run',{}).get('head_sha')!=artifact['sourceSha']):
        fail('actions-payload-artifact','exact source artifact expired, changed or disappeared')
    data=github.repo('GET','/actions/artifacts/'+location['artifactId']+'/zip',raw=True,limit=MAX_BUNDLE)
    destination=Path(destination)
    if destination.exists() or destination.is_symlink() or destination.parent.is_symlink():
        fail('actions-payload-destination','payload requires a new private destination')
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries=archive.infolist()
            if len(entries)>10000:fail('actions-payload-zip','bundle entry limit exceeded')
            seen=set();selected=None
            for entry in entries:
                name=entry.filename.rstrip('/');safe_path(name,output=True)
                if name in seen or (entry.external_attr>>16)&0o170000 not in (0,0o100000,0o040000):
                    fail('actions-payload-zip','bundle contains duplicate or unsafe paths')
                seen.add(name)
                if name==relative:
                    # OCI sizeBytes is the selected manifest/index size, NOT the
                    # transport tar size. Its graph/bytes are checked below.
                    expected = artifact['sizeBytes'] if artifact['format'] != 'oci' else None
                    if entry.is_dir() or entry.file_size > MAX_BUNDLE or (expected is not None and entry.file_size != expected):
                        fail('actions-payload-size','payload entry size differs')
                    selected=entry
            if selected is None:fail('actions-payload-path','exact payload entry is missing')
            with archive.open(selected) as incoming,destination.open('xb') as output:
                destination.chmod(0o600);total=0
                while chunk:=incoming.read(1024*1024):
                    total+=len(chunk)
                    if total > (artifact['sizeBytes'] if artifact['format'] != 'oci' else MAX_BUNDLE):
                        fail('actions-payload-size','payload expanded beyond transport bound')
                    output.write(chunk)
        validate_artifact(destination,artifact)
        return destination
    except (OSError,ValueError,zipfile.BadZipFile):
        fail('actions-payload-bytes','payload archive is invalid or unreadable')
