"""Exact manual convergence with fresh gates, or artifact-free native recovery."""
import argparse
import copy
import os
from pathlib import Path
import tempfile
from authorization import prepare_recovery_context,inspect_verified_context,prepare_verified_context
from contracts import digest, fail, load_record
from credential_context import read_context
from diagnostics import event,error_category
from executor import checked
from github import GitHub
from iac import IaCExecutor
from normal_entry import NativeRunner, ROOT, automation_id, output, select, settings
from scan_entry import host


def candidate(github,repository,actor,environment,target,component):
    if not all(isinstance(v,str) and v for v in (environment,target,component)):
        fail('operation-scope','explicit protected environment, target and component are required')
    matches={}
    for entry in github.pages('/deployments?task=cloudopsworks-state'):
        if str(entry.get('creator',{}).get('id'))!=str(actor):continue
        handle=entry.get('payload',{}).get('stateHandle',{})
        if (handle.get('origin',{}).get('repository')==repository
                and handle.get('protectedEnvironment')==environment and handle.get('targetId')==target
                and handle.get('componentId')==component):matches[digest(handle)]=handle
    if len(matches)!=1:fail('operation-owner','exact historical owner is missing or ambiguous')
    # Candidate bytes are NOT authority: prepare_recovery_context independently
    # verifies exact writer jobs, immutable source YAML and full canonical handle.
    return copy.deepcopy(next(iter(matches.values())))


def confirmation(operation,environment,target,component,value,lock_id):
    if operation not in ('destroy','unlock'):fail('operation-kind','manual recovery operation is invalid')
    if operation=='unlock' and not lock_id:fail('operation-lock-id','native lock ID is mandatory')
    expected=operation+' '+environment+'/'+target+'/'+component
    if operation=='unlock':expected+=' '+lock_id
    if value!=expected:fail('operation-confirmation','confirmation must match the exact historical scope')


def prepare(github,runner,environ,operation,environment,target,component,value,lock_id):
    confirmation(operation,environment,target,component,value,lock_id)
    repository={'id':environ['GITHUB_REPOSITORY_ID'],'fullName':environ['GITHUB_REPOSITORY']}
    actor=automation_id(github)
    handle=candidate(github,repository,actor,environment,target,component)
    blueprint=checked(runner,['git','rev-parse','HEAD'],cwd=ROOT).strip()
    engine=IaCExecutor(ROOT,load_record(ROOT/'terraform/monorepo/module-catalog.json'))
    prepared=prepare_recovery_context(github,handle,operation=operation,blueprint_sha=blueprint,
        executor=runner,engine=engine,current_host=host(environ,blueprint))
    return prepared,handle,actor



def completed_source_runs(github, head_sha):
    """Candidate locators only; callers independently prove publisher/policy."""
    candidates=[]
    from urllib.parse import quote
    for page in range(1,101):
        response=github.repo('GET','/actions/workflows/main-build.yml/runs?head_sha='+quote(head_sha,safe='')+f'&per_page=100&page={page}')
        rows=response.get('workflow_runs') if isinstance(response,dict) else None
        if not isinstance(rows,list):fail('operation-source-runs','source run inventory is malformed')
        candidates.extend(r for r in rows if r.get('head_sha')==head_sha and r.get('status')=='completed')
        if len(rows)<100:break
    else:fail('operation-source-runs','source run inventory exceeds its bound')
    return sorted(candidates,key=lambda r:(int(r['id']),int(r['run_attempt'])),reverse=True)


def prepare_apply(github,runner,environ,environment,target,component,*,inspection=False):
    """Find an exact completed protected source stage, never a name-only payload."""
    if not all(isinstance(v,str) and v for v in (environment,target,component)):
        fail('operation-scope','explicit protected environment, target and component are required')
    blueprint=checked(runner,['git','rev-parse','HEAD'],cwd=ROOT).strip()
    current=host(environ,blueprint)
    if current['event']!='workflow_dispatch' or current['workflowRef'].split('@',1)[0]!=current['repository']['fullName']+'/.github/workflows/deploy.yml':
        fail('operation-apply-caller','manual apply requires its fixed protected caller')
    engine=IaCExecutor(ROOT,load_record(ROOT/'terraform/monorepo/module-catalog.json'))
    # This endpoint selects candidates only. The factory independently checks the
    # actual attempt, successful exact publisher log/ID, caller/config and scans.
    candidates=completed_source_runs(github,current['headSha'])
    factory=inspect_verified_context if inspection else prepare_verified_context
    for source in candidates:
        try:
            prepared=factory(github,source,blueprint_sha=blueprint,executor=runner,engine=engine,current_host=current)
        except Exception:
            continue # Missing/expired/failed publisher cannot become fallback authority.
        if (prepared.plan['headSha']!=current['headSha'] or prepared.host['ref']!=current['ref']
                or prepared.lifecycle['protectedEnvironment']!=environment):continue
        from normal_entry import binding_request
        binding_request(prepared,target,component)
        return prepared
    fail('operation-source-stage','no exact current-source stage and policy proof is available; rebuild unprivileged')


def execute(prepared,handle,operation,value,lock_id,*,values=None,expected_state_digest=None,before_apply=None):
    bound=prepared.recover(handle,operation=operation,confirmation=value,lock_id=lock_id)
    if operation=='destroy' and values is None:
        from credential_context import credential_environment
        from private_state import read_private_state
        from iac_values import recovery_values
        projection=prepared.recovery_inputs(handle)
        row=bound['engine'].catalog['modules'][handle['moduleId']]
        metadata=load_record(bound['engine'].root/row['path']/'inputs.json')
        with tempfile.TemporaryDirectory(prefix='cloudopsworks-destroy-values-') as directory:
            root=Path(directory);root.chmod(0o700)
            state=read_private_state(handle,prepared.executor,workdir=root,
                env=credential_environment(prepared._credentials['backend']))
            scaffold=root/'values';scaffold.mkdir(mode=0o700)
            kubeconfig=None;guard=None;resolved_api=None
            target=projection['target']
            if target['kind'] in ('aws.eks','gcp.gke','azure.aks'):
                from normal_entry import configure_kubeconfig
                from protected_runtime import context
                from providers.common import command
                from providers.preflight import require_external_namespace
                kubeconfig=root/'kubeconfig'
                credentials=copy.deepcopy(prepared._credentials)
                credentials['workload']['environment']['KUBECONFIG']=str(kubeconfig)
                local,cloud=context(prepared,prepared.executor,workdir=root/'native',credentials=credentials,kubeconfig=kubeconfig)
                configure_kubeconfig(target,cloud,kubeconfig)
                def guard():
                    namespace=command(cloud,['kubectl','get','namespace',handle['resourceIdentity']['namespace'],'-o','json'],env={'KUBECONFIG':str(kubeconfig)})
                    require_external_namespace(namespace,handle['resourceIdentity']['namespace'])
                guard() # Historical normal destroy must not cross preview ownership.
            if target['kind']=='aws.apigateway-rest':
                from protected_runtime import CloudExecutor
                from providers.common import command
                cloud=CloudExecutor(prepared.executor,credential_environment(prepared._credentials['workload']))
                api_id=target.get('restApiId')
                candidates=[i.get('attributes',{}) for r in state['resources'] if r.get('mode')=='managed'
                    and r.get('type')=='aws_api_gateway_rest_api' and r.get('name')=='component' for i in r.get('instances',[])]
                if len(candidates)!=1 or (api_id and candidates[0].get('id')!=api_id):
                    fail('operation-api-owner','exact historical REST private resource is required')
                native=command(cloud,['aws','apigateway','get-rest-api','--rest-api-id',candidates[0]['id'],
                    '--region',target['region'],'--no-cli-pager','--output','json'])
                if native.get('id')!=candidates[0]['id'] or native.get('tags',{}).get('cloudopsworks-owner')!=digest(handle):
                    fail('operation-api-owner','historical REST native owner differs')
                resolved_api={'name':native['name'],'description':native.get('description','')}
            values=recovery_values(projection['inputs'],metadata,handle,state,work=scaffold,
                package_handler=projection['packageHandler'],chart_path=ROOT/'kubernetes/helm/charts',
                kubeconfig_path=kubeconfig,resolved_api=resolved_api)
            return execute(prepared,handle,operation,value,lock_id,values=values,
                expected_state_digest=digest(state),before_apply=guard)


    result=bound['engine'].execute(bound['plan'],canonical=bound['canonical'],store=bound['store'],
        resource_claims=bound['resourceClaims'],existing=bound['existing'],values=values or {},
        credentials=bound['credentials'],expected_state_digest=expected_state_digest,before_apply=before_apply)
    event(operation,'succeeded',component=handle['componentId'],target=handle['targetId'])
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=('inspect','configure','run'))
    parser.add_argument('--operation',required=True,choices=('apply','destroy','unlock'));parser.add_argument('--environment',required=True)
    parser.add_argument('--target',required=True);parser.add_argument('--component',required=True)
    parser.add_argument('--confirmation',required=True);parser.add_argument('--lock-id',default='')
    args=parser.parse_args();runner=NativeRunner(inherit_environment=False)
    github=GitHub(os.environ['GITHUB_REPOSITORY'])
    if args.operation=='apply':
        prepared=prepare_apply(github,runner,os.environ,args.environment,args.target,args.component,inspection=args.command=='inspect')
        actor=automation_id(github);handle=None
        if args.command=='inspect':
            from scan_entry import outputs
            output({'source-run':prepared.stage['runId'],'source-attempt':prepared.stage['runAttempt'],
                'stage-artifact-id':prepared.stage['artifactId']},os.environ['GITHUB_OUTPUT'])
            outputs(prepared,'scan-plan.json',os.environ['GITHUB_OUTPUT']);return
    else:
        prepared,handle,actor=prepare(github,runner,os.environ,args.operation,args.environment,args.target,args.component,args.confirmation,args.lock_id)
    protected=settings(os.environ);backend=os.environ.get('DEPLOYMENT_STATE_CONF','')
    selected=select(prepared,args.target,args.component,backend,protected,actor)
    if args.command=='configure':output(selected,os.environ['GITHUB_OUTPUT']);return
    workload=read_context(os.environ['WORKLOAD_CONTEXT'],runner_temp=os.environ['RUNNER_TEMP'])
    backend_capture=(copy.deepcopy(workload) if selected['same-binding']=='true' else
        read_context(os.environ['BACKEND_CONTEXT'],runner_temp=os.environ['RUNNER_TEMP']))
    prepared.bind(backend,protected,{'workload':workload,'backend':backend_capture},automation_id=actor)
    if args.operation=='apply':
        from normal_entry import apply
        with tempfile.TemporaryDirectory(prefix='cloudopsworks-manual-apply-') as directory:
            root=Path(directory);root.chmod(0o700)
            apply(prepared,github,runner,args.target,args.component,{'workload':workload,'backend':backend_capture},root,actor)
    else:execute(prepared,handle,args.operation,args.confirmation,args.lock_id or None)


if __name__=='__main__':
    try:main()
    except Exception as error:
        event('operation','failed',failed=1,errorCategory=error_category(error));raise SystemExit(1)
