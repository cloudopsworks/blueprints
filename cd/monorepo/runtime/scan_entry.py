"""Fixed current-stage scan job entrypoint; no deployment credentials or writes."""
import argparse
import os
from pathlib import Path
import tempfile

from actions_payload import fetch_payload
from authorization import inspect_verified_context, scan_marker, _records, _job, preview_phase_name
from contracts import canonical_bytes, digest, fail, load_record
from diagnostics import event, error_category
from executor import Runner, checked
from github import GitHub
from iac import IaCExecutor
from scanners import run_scanners, require_completed_gates

ROOT=Path(__file__).resolve().parents[3]


class ScanRunner(Runner):
    def run(self, argv, **kwargs):
        # Preserve executable discovery only, never the parent's credentials.
        kwargs['env'] = {'PATH': os.environ.get('PATH', os.defpath), **kwargs.get('env', {})}
        return super().run(argv, **kwargs)


def host(environ, blueprint_sha):
    return {'repository':{'id':environ['GITHUB_REPOSITORY_ID'],'fullName':environ['GITHUB_REPOSITORY']},
        'runId':environ['GITHUB_RUN_ID'],'runAttempt':environ['GITHUB_RUN_ATTEMPT'],
        'event':environ['GITHUB_EVENT_NAME'],'ref':environ['GITHUB_REF'],'headSha':environ['GITHUB_SHA'],
        'workflowRef':environ['GITHUB_WORKFLOW_REF'],'workflowSha':environ['GITHUB_WORKFLOW_SHA'],
        'blueprintSha':blueprint_sha,'actor':environ['GITHUB_ACTOR']}


def inspect(github, runner, artifact_id, environ, preview_target_id=None):
    blueprint_sha=checked(runner,['git','rev-parse','HEAD'],cwd=ROOT).strip()
    current=host(environ,blueprint_sha)
    source=github.repo('GET','/actions/runs/'+environ.get('SOURCE_RUN_ID',environ['GITHUB_RUN_ID'])+
        '/attempts/'+environ.get('SOURCE_RUN_ATTEMPT',environ['GITHUB_RUN_ATTEMPT']))
    engine=IaCExecutor(ROOT,load_record(ROOT/'terraform/monorepo/module-catalog.json'))
    return inspect_verified_context(github,source,blueprint_sha=blueprint_sha,executor=runner,
        engine=engine,current_host=current,current_artifact_id=artifact_id,preview_target_id=preview_target_id)


def outputs(prepared, destination, output, component_id=None):
    # The file is only tool setup data. The scan command re-fetches authority.
    data=prepared.inspect();Path(destination).write_bytes(canonical_bytes(data['plan']))
    config=data['resolved']['scanners']
    components = data['plan']['components']
    if component_id is not None:
        components = [component for component in components if component['id'] == component_id]
        if len(components) != 1: fail('scanner-component', 'scanner owner is not active')
    values={'environment':data['lifecycle']['protectedEnvironment'],'source-sha':data['plan']['headSha'],
        'sonarqube':config['sonarqubeEnabled'],'snyk':config['snykEnabled'],
        'semgrep':config['semgrepEnabled'] or config['secretScanEnabled'],'trivy':config['trivyEnabled'],
        'dotnet':config['sonarqubeEnabled'] and any(c['buildProfile']=='dotnet' for c in components),
        'matrix':canonical_bytes({'include':[{'component':c['id']} for c in components]}).decode(),
        'source-tools':any(config[key] for key in ('sonarqubeEnabled','snykEnabled','dependencyTrackEnabled'))}
    with Path(output).open('a') as stream:
        for key,value in values.items():
            if isinstance(value,bool):value=str(value).lower()
            if not isinstance(value,str) or '\n' in value or '\r' in value:
                fail('scanner-output','normalized scanner output is invalid')
            stream.write(key+'='+value+'\n')
    return values


def scan(prepared,github,runner,source,credentials,*,component_id=None,emit=print):
    data=prepared.inspect();source=Path(source).resolve()
    if component_id is not None:
        data['plan']['components']=[c for c in data['plan']['components'] if c['id']==component_id]
        if len(data['plan']['components'])!=1:fail('scanner-component','scanner owner is not active')
    # Only independently protected main lineage may execute source-dependent
    # scanner preparation with scanner credentials. PR preview has no such right.
    trusted=prepared.host['event'] in ('push','create','workflow_dispatch')
    if trusted and checked(runner,['git','rev-parse','HEAD'],cwd=source).strip()!=data['plan']['headSha']:
        fail('scanner-source','source checkout differs from independently verified immutable head')
    with tempfile.TemporaryDirectory(prefix='cloudopsworks-scan-payloads-') as directory:
        paths={}
        for component in data['manifest']['components']:
            artifact=component['mainArtifact']
            if data['resolved']['scanners']['trivyEnabled'] and artifact['format']=='oci':
                if artifact['location']['kind']=='actions-artifact':
                    paths[component['componentId']]=fetch_payload(github,artifact,data['plan']['repository'],Path(directory)/component['componentId'])
                elif artifact['location']['kind']=='oci':
                    from release import ArtifactPublisher
                    publisher=ArtifactPublisher(github,runner,'ghcr.io/'+github.repository.lower())
                    paths[component['componentId']]=publisher.fetch_oci(artifact,Path(directory)/component['componentId'])
                else:fail('scanner-artifact','OCI scanner transport is not supported')
        results=run_scanners(data['plan'],data['manifest'],data['resolved']['scanners'],runner,
            workdir=source,credentials=credentials,trusted_source=trusted,artifact_paths=paths)
    for result in results:
        event('scan',result['status'],component=result['componentId'],source=result['sourceSha'],
            digest=result['artifactDigest'],reason=result['scanner'],
            errorCategory=result['errorCode'] or 'none')
    if component_id is None:
        require_completed_gates(data['plan'],data['manifest'],data['resolved']['scanners'],results)
        emit(scan_marker(data['stage'],data['resolved'],results),flush=True)
    else:
        value={'stage':data['stage'],'componentId':component_id,'results':results}
        emit('CLOUDOPSWORKS_COMPONENT_SCAN_V1 '+canonical_bytes(value).decode(),flush=True)
    return results


def barrier(prepared,github,*,emit=print):
    data=prepared.inspect();results=[]
    caller=prepared.current_host['workflowRef'].split('@',1)[0].rsplit('/',1)[-1]
    prefixes={'main-build.yml':'lifecycle / ','pr-build.yml':'preview / ','pr-close.yaml':'close / lifecycle / ','deploy.yml':'operation / '}
    prefix=prefixes.get(caller)
    if prefix is None:fail('scanner-caller','scanner barrier caller is not supported')
    nested_preview=caller=='pr-build.yml' or caller=='pr-close.yaml' and getattr(prepared,'preview_target_id',None) is not None
    if nested_preview:
        target=getattr(prepared,'preview_target_id',None)
        if not isinstance(target,str) or not any(t['targetId']==target for t in data['plan']['previewPolicy']['targets']):
            fail('scanner-target','nested preview scanner requires its verified target')
    for component in data['plan']['components']:
        name=(preview_phase_name(caller,target,'component-scan',component['id']) if nested_preview
            else prefix+'monorepo-component-scan-'+component['id'])
        job=_job(github,prepared.current_host['runId'],prepared.current_host['runAttempt'],name)
        records=_records(github.repo('GET','/actions/jobs/'+str(job['id'])+'/logs',raw=True,limit=8*1024*1024),
            'CLOUDOPSWORKS_COMPONENT_SCAN_V1 ')
        if (len(records)!=1 or set(records[0])!={'stage','componentId','results'}
                or records[0]['stage']!=data['stage'] or records[0]['componentId']!=component['id']
                or not isinstance(records[0]['results'],list)
                or any(record.get('componentId')!=component['id'] for record in records[0]['results'])):
            fail('scanner-worker-binding','exact completed scanner worker does not bind current stage')
        results.extend(records[0]['results'])
    require_completed_gates(data['plan'],data['manifest'],data['resolved']['scanners'],results)
    emit(scan_marker(data['stage'],data['resolved'],results),flush=True)
    return results


def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=('inspect','run','barrier'))
    parser.add_argument('--stage-artifact-id',required=True);parser.add_argument('--target');parser.add_argument('--component');parser.add_argument('--source',type=Path,default=Path('source'))
    parser.add_argument('--plan-out',type=Path,default=Path('scan-plan.json'));args=parser.parse_args()
    runner=ScanRunner(inherit_environment=False,timeout=600,output_limit=4*1024*1024)
    gh=GitHub(os.environ['GITHUB_REPOSITORY'])
    prepared=inspect(gh,runner,args.stage_artifact_id,os.environ,args.target)
    if args.command=='inspect':outputs(prepared,args.plan_out,os.environ['GITHUB_OUTPUT'],args.component)
    elif args.command=='barrier':barrier(prepared,gh)
    else:
        credentials={key:os.environ[name] for key,name in {
            'sonarqube_url':'SONARQUBE_URL','sonarqube_token':'SONARQUBE_TOKEN',
            'dtrack_url':'DEPENDENCYTRACK_URL','dtrack_token':'DEPENDENCYTRACK_TOKEN',
            'snyk_token':'SNYK_TOKEN','semgrep_token':'SEMGREP_TOKEN'}.items() if os.environ.get(name)}
        scan(prepared,gh,runner,args.source,credentials,component_id=args.component)

if __name__=='__main__':
    try:main()
    except Exception as error:
        event('scan','failed',failed=1,errorCategory=error_category(error))
        raise SystemExit(1)
