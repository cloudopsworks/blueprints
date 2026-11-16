"""Read-only selection/carry of an exact completed trusted stage ancestor.

An event.before SHA is not a materialization baseline. Missing/expired/changed
host evidence or payload bytes means an unprivileged all-build, never a guessed
artifact-by-name carry. Later deployment failure does not invalidate a successful
exact publisher in the same completed attempt.
"""
from pathlib import Path
import tempfile
from urllib.parse import quote
from actions_payload import fetch_payload
from authorization import _archive, _file, HOST_FIELDS
from contracts import digest, fail, validate_record
from staging import trusted_stage_bundle


def load(github,run,*,repository,blueprint_sha,pr_number=None):
    caller=run.get('path','').split('@',1)[0].removeprefix('.github/workflows/')
    if caller not in ('main-build.yml','pr-build.yml'):
        fail('baseline-caller','baseline caller is not a source publisher')
    if str(run.get('repository',{}).get('id'))!=repository['id'] or github.repository!=repository['fullName']:
        fail('baseline-repository','baseline belongs to another repository')
    repo=github.repo('GET','');branch=repo.get('default_branch')
    if not isinstance(branch,str):fail('baseline-default','baseline trusted branch is missing')
    trusted=github.repo('GET','/branches/'+quote(branch,safe=''))
    trust_sha=trusted.get('commit',{}).get('sha')
    if pr_number is not None:
        pr=github.repo('GET','/pulls/'+str(pr_number))
        if (str(pr.get('base',{}).get('repo',{}).get('id'))!=repository['id']
                or str(pr.get('head',{}).get('repo',{}).get('id'))!=repository['id']):
            fail('baseline-fork','foreign repository baseline is not carried')
        trust_sha=pr['base']['sha']
        if not any(item.get('number')==pr_number for item in run.get('pull_requests',[])):
            fail('baseline-pr','baseline belongs to another pull request')
    _,data=trusted_stage_bundle(github,run,caller=caller,blueprint_sha=blueprint_sha,
        source_caller_bytes=_file(github,'.github/workflows/'+caller,run['head_sha']),
        trusted_caller_bytes=_file(github,'.github/workflows/'+caller,trust_sha))
    files=_archive(data);plan=validate_record(files['build-plan.json']);manifest=validate_record(files['manifest.json'])
    capsule=files['host.json']
    if (not isinstance(capsule,dict) or set(capsule)!=HOST_FIELDS or plan['repository']!=repository or manifest['repository']!=repository
            or plan['headSha']!=manifest['headSha'] or plan['headSha']!=capsule.get('sourceSha')
            or plan['prNumber']!=pr_number or capsule.get('runId')!=str(run['id'])
            or capsule.get('runAttempt')!=str(run['run_attempt'])
            or capsule.get('blueprintSha')!=blueprint_sha or capsule.get('planDigest')!=digest(plan)
            or capsule.get('manifestDigest')!=digest(manifest)):
        fail('baseline-stage-binding','baseline capsule and immutable source records disagree')
    planned={component['id']:component for component in plan['components']}
    if manifest['targets']!=plan['targets'] or {c['componentId'] for c in manifest['components']}!=set(planned):
        fail('baseline-membership','baseline plan and manifest membership disagree')
    for component in manifest['components']:
        if any(component[key]!=planned[component['componentId']][key] for key in ('package','workload','targetIds')):
            fail('baseline-component','baseline component contract differs from source plan')
    # Fresh payload availability/digest check for ALL carried components, not just
    # a manifest's self-declared success. Stage transport is intentionally Actions.
    with tempfile.TemporaryDirectory(prefix='cloudopsworks-baseline-bytes-') as directory:
        for component in manifest['components']:
            for role in ('mainArtifact','previewArtifact'):
                artifact=component[role]
                if artifact is None:continue
                if artifact['location']['kind']!='actions-artifact':
                    fail('baseline-transport','baseline does not have verifiable staged Actions bytes')
                fetch_payload(github,artifact,repository,Path(directory)/(component['componentId']+'-'+role))
    return manifest


def find(github,current,*,repository,head,root,runner,blueprint_sha,pr_number=None,exact_head=None):
    caller=current.get('path','').split('@',1)[0].rsplit('/',1)[-1]
    if caller not in ('main-build.yml','pr-build.yml'):return None
    branch=current.get('head_branch')
    if not isinstance(branch,str) or not branch:return None
    response=github.repo('GET','/actions/workflows/'+caller+'/runs?branch='+quote(branch,safe='')+'&per_page=100')
    runs=response.get('workflow_runs',[]) if isinstance(response,dict) else []
    if not isinstance(runs,list) or len(runs)>100:return None
    for run in runs:
        if (run.get('id')==current.get('id') or run.get('status')!='completed'
                or (exact_head is not None and pr_number is None and run.get('head_sha')!=exact_head)):
            continue
        try:
            manifest=load(github,run,repository=repository,blueprint_sha=blueprint_sha,pr_number=pr_number)
            if exact_head is not None and manifest['headSha']!=exact_head:continue
            if root is None:
                relation=github.repo('GET','/compare/'+manifest['headSha']+'...'+head)
                ancestor=(isinstance(relation,dict) and relation.get('status') in ('ahead','identical')
                    and relation.get('merge_base_commit',{}).get('sha')==manifest['headSha'])
            else:
                ancestor=runner.run(['git','merge-base','--is-ancestor',manifest['headSha'],head],cwd=root).returncode==0
            if ancestor:return manifest
        except Exception:
            # Unknown/expired/forged evidence cannot become a partial baseline.
            continue
    return None
