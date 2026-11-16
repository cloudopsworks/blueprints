"""Exact trusted publisher job/API log binding for cross-run staged artifacts.

Artifacts selected only by name are never trusted. Current-run callers should
use needs.stage.outputs.artifact-id directly. Cross-run callers obtain that ID
from the exact successful publisher job's host-owned logs after independently
checking source caller bytes and immutable called-code identity. Expired logs
or a deleted/replaced artifact fail closed; no name fallback exists.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

from contracts import ContractError, canonical_bytes, load_record

FIXTURE = Path(__file__).resolve().parents[3] / 'tests/monorepo/fixtures/revision_callers.json'
MARKER = 'CLOUDOPSWORKS_STAGE_V1 '
FIELDS = {'repositoryId','runId','runAttempt','artifactId','artifactName','archiveDigest'}
MAX_LOG_BYTES = 8*1024*1024


def parse_stage_marker(data, *, repository_id, run_id, attempt):
    if not isinstance(data,bytes) or len(data)>MAX_LOG_BYTES:
        raise ContractError('stage-log-bound','publisher logs are unavailable or exceed bound')
    try: text=data.decode('utf-8',errors='strict')
    except UnicodeError: raise ContractError('stage-log-format','publisher logs are not UTF-8') from None
    records=[]
    pattern=re.compile(r'^(?:[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z )?'+re.escape(MARKER)+r'(\{.*\})$')
    for line in text.splitlines():
        match=pattern.fullmatch(line)
        if match: records.append(load_record(match.group(1)))
    if len(records)!=1:
        raise ContractError('stage-log-marker','publisher must emit exactly one closed artifact binding')
    value=records[0]
    if (set(value)!=FIELDS or any(not isinstance(v,str) for v in value.values())
            or any(not re.fullmatch(r'[1-9][0-9]*',value[k]) for k in ('repositoryId','runId','runAttempt','artifactId'))
            or value['repositoryId']!=str(repository_id) or value['runId']!=str(run_id)
            or value['runAttempt']!=str(attempt)
            or value['artifactName']!=f'monorepo-stage-{run_id}-{attempt}'
            or not re.fullmatch(r'sha256:[0-9a-f]{64}',value['archiveDigest'])):
        raise ContractError('stage-log-binding','publisher artifact binding disagrees with trusted host run')
    return value


def marker_record(repository_id, run_id, attempt, artifact_id, archive_digest):
    value={'repositoryId':str(repository_id),'runId':str(run_id),'runAttempt':str(attempt),
           'artifactId':str(artifact_id),'artifactName':f'monorepo-stage-{run_id}-{attempt}',
           'archiveDigest':archive_digest if archive_digest.startswith('sha256:') else 'sha256:'+archive_digest}
    # Producer and consumer share exact closed semantics, no arbitrary log fields.
    parse_stage_marker(MARKER.encode()+canonical_bytes(value),repository_id=repository_id,run_id=run_id,attempt=attempt)
    return MARKER+canonical_bytes(value).decode()


def trusted_stage_bundle(github, run, *, caller, blueprint_sha, source_caller_bytes, trusted_caller_bytes, current_artifact_id=None):
    """Caller bytes must be independently API-fetched at immutable commits.

    For PRs trusted_caller_bytes come from the eligible trusted base commit.
    Main callers additionally require upstream protected host/ref eligibility;
    byte equality is not proof of branch protection. Called-code identity comes
    from the trusted published Blueprint ref resolution, never an artifact.
    """
    contract=json.loads(FIXTURE.read_text())
    names=contract['stagePublisher']['expectedFullNames']
    if caller not in names or not source_caller_bytes or source_caller_bytes!=trusted_caller_bytes:
        raise ContractError('stage-caller','source caller differs from independently trusted workflow')
    terminal=('success','failure','cancelled','timed_out','neutral','skipped','action_required','stale')
    completed=run.get('status')=='completed' and run.get('conclusion') in terminal
    current=(current_artifact_id is not None and str(run.get('id'))==os.environ.get('GITHUB_RUN_ID')
             and str(run.get('run_attempt'))==os.environ.get('GITHUB_RUN_ATTEMPT')
             and run.get('status')=='in_progress' and run.get('conclusion') is None)
    if (not re.fullmatch(r'[0-9a-f]{40}',blueprint_sha)
            or run.get('path','').split('@',1)[0]!='.github/workflows/'+caller
            or not (completed or current)):
        raise ContractError('stage-run','source host run is not an eligible canonical caller')
    mapping={'main-build.yml':'monorepo-main-build.yml','pr-build.yml':'monorepo-pr-build.yml','pr-close.yaml':'monorepo-pr-close.yml'}
    path='cloudopsworks/blueprints/.github/workflows/'+mapping[caller]+'@'+contract['blueprintRef']
    refs=[r for r in run.get('referenced_workflows',[]) if r.get('path')==path and r.get('sha')==blueprint_sha]
    if len(refs)!=1:
        raise ContractError('stage-called-code','host run does not corroborate exact immutable called code')
    run_id,attempt=run.get('id'),run.get('run_attempt')
    if not re.fullmatch(r'[1-9][0-9]*',str(run_id)) or not re.fullmatch(r'[1-9][0-9]*',str(attempt)):
        raise ContractError('stage-run','host run identity is invalid')
    jobs=[]
    for page in range(1,101):
        response=github.repo('GET',f'/actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100&page={page}')
        if not isinstance(response,dict) or not isinstance(response.get('jobs'),list):
            raise ContractError('stage-jobs','host jobs response is invalid')
        entries=response['jobs'];jobs.extend(entries)
        if len(entries)<100: break
    else: raise ContractError('stage-jobs','host jobs pagination exceeds bound')
    selected=[j for j in jobs if j.get('name')==names[caller]]
    if len(selected)!=1:
        raise ContractError('stage-job-identity','publisher full job identity is missing or duplicated')
    job=selected[0]
    if (job.get('run_id')!=run_id or job.get('run_attempt')!=attempt
            or job.get('status')!='completed' or job.get('conclusion')!='success'
            or not re.fullmatch(r'[1-9][0-9]*',str(job.get('id')))):
        raise ContractError('stage-job-status','publisher job did not complete successfully in exact attempt')
    logs=github.repo('GET',f'/actions/jobs/{job["id"]}/logs',raw=True,limit=MAX_LOG_BYTES)
    binding=parse_stage_marker(logs,repository_id=run['repository']['id'],run_id=run_id,attempt=attempt)
    if current_artifact_id is not None and str(current_artifact_id)!=binding['artifactId']:
        raise ContractError('stage-current-artifact','publisher artifact differs from trusted needs output')
    artifact=github.repo('GET','/actions/artifacts/'+binding['artifactId'])
    if (not artifact or str(artifact.get('id'))!=binding['artifactId'] or artifact.get('name')!=binding['artifactName']
            or artifact.get('expired') is not False or artifact.get('workflow_run',{}).get('id')!=run_id):
        raise ContractError('stage-artifact','exact publisher artifact was deleted, replaced or expired')
    data=github.repo('GET','/actions/artifacts/'+binding['artifactId']+'/zip',raw=True,limit=64*1024*1024)
    if not isinstance(data,bytes) or 'sha256:'+hashlib.sha256(data).hexdigest()!=binding['archiveDigest']:
        raise ContractError('stage-archive-digest','publisher artifact archive bytes disagree with host log binding')
    return binding,data
