"""Trusted data-only stage assembly; no source command or public release writes.

The plan artifact ID is the exact needs output of the trusted plan job, never a
name lookup supplied by source code. Selected payloads are rehashed, canonical
source YAML is independently normalized, and only Actions transport is rewritten.
A prior complete manifest may be supplied ONLY by the verified prior-stage host
loader; the standalone entry intentionally cannot accept an arbitrary prior file.
"""
from __future__ import annotations
import argparse
import copy
import json
import os
from pathlib import Path
import tempfile

from contracts import _check, canonical_bytes, digest, fail, load_record, validate_record
from executor import Runner, checked
from github import GitHub
from preview import download_bundle
from release import assemble_manifest
from snapshot import materialize_snapshot
from staging import marker_record


def assemble_stage(github,run,plan_artifact_id,*,repository,version,event,pr_number,
                   work,runner,previous=None,expected_source_sha=None):
    if (str(run.get('id'))!=os.environ.get('GITHUB_RUN_ID',str(run.get('id')))
            or str(run.get('repository',{}).get('id'))!=repository['id']
            or not str(plan_artifact_id).isdigit() or int(plan_artifact_id)<1):
        fail('stage-run','current publisher and plan job identity disagree')
    work=Path(work)
    if work.is_symlink() or not work.is_dir() or any(work.iterdir()):
        fail('stage-workspace','stage requires an empty private directory')
    bundle=work/'bundle';bundle.mkdir(mode=0o700)
    origins={}
    plan,results=download_bundle(github,run,bundle,pr_number,expected_event=event,
        plan_artifact_id=plan_artifact_id,artifact_origins=origins,expected_source_sha=expected_source_sha)
    if plan['repository']!=repository or plan['version']!=version:
        fail('stage-plan','plan disagrees with actual trusted preparation outputs')
    source=work/'source-data';source.mkdir(mode=0o700)
    source=source.resolve()
    origin=materialize_snapshot(github,plan['headSha'],source)
    normalized=load_record(checked(runner,['tronador','components','validate','--workdir',str(source),'--json']))
    resolved=normalized.get('resolved',{})
    for key in ('components','targets','previewPolicy'):
        if resolved.get(key)!=plan[key]:
            fail('stage-configuration','source plan differs from immutable independently normalized YAML')
    def actions_location(artifact,ident,role):
        value=copy.deepcopy(artifact)
        if value['location']['kind']!='local':
            # Carry is an already independently verified staged/public record.
            return value
        path=value['location']['path'];metadata=origins[path]
        expected=f'components-{run["id"]}-{run["run_attempt"]}-{ident}'
        if metadata['name']!=expected:
            fail('stage-component-artifact','component bytes belong to another build bundle')
        value['location']={'kind':'actions-artifact','repositoryId':repository['id'],
            'runId':str(run['id']),'runAttempt':str(run['run_attempt']),
            'artifactId':str(metadata['id']),'artifactName':expected,'path':path}
        return value
    document=json.loads(Path(__file__).with_name('schema').joinpath('operations-v1.schema.json').read_text())
    _check(resolved.get('scanners'),document['$defs']['ScannerConfiguration'],'$.scanners',document=document)
    if previous is None and len(plan['buildSelection']) < len(plan['components']):
        # Re-fetch the same exact source ancestor independently in this trusted
        # publisher. A plan's base SHA alone is never evidence of carried bytes.
        from stage_baseline import find
        blueprint=Path(__file__).resolve().parents[3]
        blueprint_sha=checked(runner,['git','rev-parse','HEAD'],cwd=blueprint).strip()
        previous=find(github,run,repository=repository,head=plan['headSha'],root=None,runner=runner,
            blueprint_sha=blueprint_sha,pr_number=pr_number,exact_head=plan['baseSha'])
        if previous is None:fail('stage-baseline','verified ancestor payloads expired; unprivileged rebuild is required')
    manifest=assemble_manifest(plan,results,previous,actions_location)
    out=work/'stage';out.mkdir(mode=0o700)
    for name,value in [('build-plan.json',plan),('manifest.json',manifest),('source-origin.json',origin),('scanners.json',resolved['scanners'])]:
        (out/name).write_bytes(canonical_bytes(value))
    return manifest,out


def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    prepare=sub.add_parser('assemble');prepare.add_argument('--plan-artifact-id',required=True)
    prepare.add_argument('--version',required=True);prepare.add_argument('--event',required=True,choices=('push','pull-request','release','manual'))
    prepare.add_argument('--out',required=True,type=Path)
    marker=sub.add_parser('marker');marker.add_argument('--artifact-id',required=True);marker.add_argument('--digest',required=True)
    args=parser.parse_args()
    try:
        if args.command=='marker':
            print(marker_record(os.environ['GITHUB_REPOSITORY_ID'],os.environ['GITHUB_RUN_ID'],os.environ['GITHUB_RUN_ATTEMPT'],args.artifact_id,args.digest))
            return
        gh=GitHub(os.environ['GITHUB_REPOSITORY']);run=gh.repo('GET','/actions/runs/'+os.environ['GITHUB_RUN_ID'])
        host=json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_bytes())
        pr=host.get('pull_request',{}).get('number',host.get('number')) if args.event=='pull-request' else None
        closure=None
        if os.environ['GITHUB_EVENT_NAME']=='pull_request_target':
            from closure_entry import verify_tag
            from authorization import verify_closure_record
            # Tag and merge metadata come from independent API reads, never the
            # untrusted plan. The latter must exactly match this frozen source.
            from closure_entry import verify_merge
            closure=verify_merge(gh,os.environ)
            verify_tag(gh,Runner(),os.environ,head=closure['mergeSha'],version=args.version)
        args.out.mkdir(mode=0o700,parents=False,exist_ok=False)
        manifest,stage=assemble_stage(gh,run,args.plan_artifact_id,repository={'id':os.environ['GITHUB_REPOSITORY_ID'],'fullName':os.environ['GITHUB_REPOSITORY']},
            version=args.version,event=args.event,pr_number=pr,work=args.out.resolve(),runner=Runner(),expected_source_sha=closure['mergeSha'] if closure else None)
        plan=load_record(stage/'build-plan.json')
        source_ref='refs/heads/'+host['pull_request']['head']['ref'] if args.event=='pull-request' else os.environ['GITHUB_REF']
        base_ref=host['pull_request']['base']['ref'] if args.event=='pull-request' else ''
        lifecycle=load_record(checked(Runner(),['tronador','components','lifecycle','--workdir',str(args.out.resolve()/'source-data'),
            '--event','push' if closure else os.environ['GITHUB_EVENT_NAME'],'--ref','refs/tags/v'+args.version if closure else source_ref,'--base-ref',base_ref,'--json']))
        blueprint=Path(__file__).resolve().parents[3]
        blueprint_sha=checked(Runner(),['git','rev-parse','HEAD'],cwd=blueprint).strip()
        capsule={'repository':plan['repository'],'runId':os.environ['GITHUB_RUN_ID'],'runAttempt':os.environ['GITHUB_RUN_ATTEMPT'],
            'event':os.environ['GITHUB_EVENT_NAME'],'ref':os.environ['GITHUB_REF'],'headSha':os.environ['GITHUB_SHA'],
            'workflowRef':os.environ['GITHUB_WORKFLOW_REF'],'workflowSha':os.environ['GITHUB_WORKFLOW_SHA'],
            'sourceSha':plan['headSha'],'blueprintSha':blueprint_sha,'callerPath':run['path'].split('@',1)[0],
            'lifecycle':lifecycle,'planDigest':digest(plan),'manifestDigest':digest(manifest)}
        if closure:capsule['closure']=closure
        (stage/'host.json').write_bytes(canonical_bytes(capsule))
    except Exception:
        raise SystemExit('stage-publication-failed') from None


if __name__=='__main__':main()
