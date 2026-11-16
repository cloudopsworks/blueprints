"""Fixed normal lifecycle: verified stage -> selected credentials -> IaC convergence.

Only nonsecret selectors cross step outputs. Every privileged invocation rebuilds
its authority from exact host jobs, immutable source YAML and current scans.
"""
import argparse
import copy
import os
from pathlib import Path
import tempfile

from authorization import prepare_verified_context
from contracts import canonical_bytes, digest, fail, load_record, validate_record
from credential_context import read_context
from deploy import request_for, effective_digest, reconcile
from diagnostics import event, error_category
from executor import Runner, checked
from github import GitHub
from iac import IaCExecutor
from protected_runtime import context
from receipts import ReceiptStore
from release import ArtifactPublisher
from scan_entry import host
from staged_payload import materialize

ROOT=Path(__file__).resolve().parents[3]


class NativeRunner(Runner):
    def bounded(self,seconds):
        return NativeRunner(timeout=min(self.timeout,seconds),output_limit=self.output_limit,inherit_environment=False)
    def run(self, argv, **kwargs):
        kwargs['env']={'PATH':os.environ.get('PATH',os.defpath),**kwargs.get('env',{})}
        return super().run(argv,**kwargs)


def prepare(github,runner,artifact_id,environ):
    blueprint=checked(runner,['git','rev-parse','HEAD'],cwd=ROOT).strip()
    current=host(environ,blueprint)
    source=github.repo('GET','/actions/runs/'+environ['GITHUB_RUN_ID']+'/attempts/'+environ['GITHUB_RUN_ATTEMPT'])
    return prepare_verified_context(github,source,blueprint_sha=blueprint,executor=runner,
        engine=IaCExecutor(ROOT,load_record(ROOT/'terraform/monorepo/module-catalog.json')),
        current_host=current,current_artifact_id=artifact_id)


def settings(environ):
    return {kind:environ.get(name,'{}') for kind,name in {
        'auth':'CLOUDOPSWORKS_AUTH','identities':'CLOUDOPSWORKS_IDENTITIES',
        'registries':'CLOUDOPSWORKS_REGISTRIES','probe-secrets':'CLOUDOPSWORKS_PROBE_SECRETS',
        'host-keys':'CLOUDOPSWORKS_HOST_KEYS'}.items()}


def automation_id(github):
    # Deployment creator is the workflow token's fixed automation identity, not
    # the human actor which caused the run. Resolve it independently via API.
    user=github.request('GET','/users/github-actions%5Bbot%5D')
    if user.get('login')!='github-actions[bot]' or not str(user.get('id','')).isdigit():
        fail('automation-identity','workflow automation identity is unavailable')
    return str(user['id'])


def output(values,path):
    with Path(path).open('a') as stream:
        for key,value in values.items():
            if not isinstance(value,str) or any(c in value for c in '\r\n'):
                fail('normal-output','nonsecret output must be single-line')
            stream.write(key+'='+value+'\n')


def matrix(prepared):
    targets={t['id']:t for t in prepared.manifest['targets']}
    return {'include':[{'target':target,'component':c['componentId']}
        for c in prepared.manifest['components'] for target in c['targetIds']
        if target in targets]}


def select(prepared,target_id,component_id,backend,protected,actor):
    # Must finish BEFORE either OIDC action. Historical independently verified
    # handles choose the original backend even after current YAML changes.
    chosen=prepared.select_bindings(target_id,component_id,backend,protected,automation_id=actor)
    return {'workload-provider':chosen['workload']['provider'],
        'workload-ref':chosen['workload']['authRef'],'backend-provider':chosen['backend']['provider'],
        'backend-ref':chosen['backend']['authRef'],
        'same-binding':str(chosen['workload']=={k:chosen['backend'][k] for k in ('provider','authRef')}).lower()}


def binding_request(prepared,target_id,component_id):
    components=[c for c in prepared.manifest['components'] if c['componentId']==component_id and target_id in c['targetIds']]
    targets=[t for t in prepared.manifest['targets'] if t['id']==target_id]
    if len(components)!=1 or len(targets)!=1:fail('normal-binding','binding is not in the verified complete manifest')
    return validate_record(request_for(prepared.manifest,components[0],targets[0]))


def configure_kubeconfig(t,cloud,kubeconfig):
    kind=t['kind']
    if kind=='aws.eks':
        checked(cloud,['aws','eks','update-kubeconfig','--name',t['cluster'],'--region',t['region'],'--kubeconfig',str(kubeconfig)])
    elif kind=='gcp.gke':
        checked(cloud,['gcloud','container','clusters','get-credentials',t['cluster'],'--location',t['location'],'--project',t['project']],env={'KUBECONFIG':str(kubeconfig)})
    else:
        checked(cloud,['az','aks','get-credentials','--name',t['cluster'],'--resource-group',t['resourceGroup'],'--subscription',t['subscriptionId'],'--file',str(kubeconfig)])
        checked(cloud,['kubelogin','convert-kubeconfig','--login','azurecli','--kubeconfig',str(kubeconfig)])
    if not kubeconfig.is_file() or kubeconfig.is_symlink():fail('normal-kubeconfig','selected cluster credentials are unavailable')
    kubeconfig.chmod(0o600)

def resolve_binding(prepared,runner,target_id,component_id,credentials,workdir):
    request=binding_request(prepared,target_id,component_id)
    kind=request['target']['kind'];kubeconfig=None
    if kind in ('aws.eks','gcp.gke','azure.aks'):
        kubeconfig=Path(workdir)/'kubeconfig'
        credentials['workload']['environment']['KUBECONFIG']=str(kubeconfig)
    local,cloud=context(prepared,runner,workdir=workdir,credentials=credentials,kubeconfig=kubeconfig)
    if kubeconfig:
        local['kubeconfigPath']=kubeconfig
        configure_kubeconfig(request['target'],cloud,kubeconfig)
    native_resolve=local['iac_resolve']
    def with_registry(fresh_request,unused_executor):
        from providers.registry import bind_resolution
        return bind_resolution(fresh_request,native_resolve(fresh_request,cloud),cloud,prepared._settings['registries'])
    local['iac_resolve']=with_registry
    resolved=with_registry(request,cloud)
    request['target']['configDigest']=effective_digest(request['target'],request['workload'],resolved)
    request['idempotencyKey']=digest({'repositoryId':request['repository']['id'],'targetId':target_id,
        'componentId':component_id,'artifactDigest':request['artifact']['digest'],
        'targetConfigDigest':request['target']['configDigest']})
    return validate_record(request),resolved,local,cloud


def preflight(prepared,runner,target_id,component_id,credentials,workdir,*,emit=print):
    from preflight_barrier import binding_marker
    request,resolved,_,_=resolve_binding(prepared,runner,target_id,component_id,credentials,workdir)
    operation=prepared.authorize(request,resolved)
    emit(binding_marker(prepared,request,resolved,operation),flush=True)
    return operation


def apply(prepared,github,runner,target_id,component_id,credentials,workdir,actor):
    from preflight_barrier import require_preflight_barrier
    manual=(prepared.current_host['event']=='workflow_dispatch'
        and prepared.current_host['workflowRef'].split('@',1)[0]==prepared.repository['fullName']+'/.github/workflows/deploy.yml')
    # Exact manual scope is serialized by the same whole-graph repository group;
    # it must NOT authenticate unrelated manifest bindings or expand into an all-
    # target preflight. Current host/config/all-component scan proof is unchanged.
    records=None if manual else require_preflight_barrier(prepared,github)
    request,resolved,local,cloud=resolve_binding(prepared,runner,target_id,component_id,credentials,workdir)
    authorized=prepared.authorize(request,resolved)
    if manual:
        records=[{'targetId':target_id,'componentId':component_id,
            'stateHandleDigest':authorized['plan']['stateHandleDigest'],
            'resourceClaims':sorted(resolved['resourceClaims']),'providerIdentity':resolved['providerIdentity']}]
    matches=[r for r in records if r['targetId']==target_id and r['componentId']==component_id]
    if len(matches)!=1 or matches[0]['stateHandleDigest']!=authorized['plan']['stateHandleDigest'] or matches[0]['resourceClaims']!=sorted(resolved['resourceClaims']) or matches[0]['providerIdentity']!=resolved['providerIdentity']:
        fail('preflight-drift','fresh native binding changed after the global barrier')
    publisher=ArtifactPublisher(github,runner,'ghcr.io/'+github.repository.lower())
    local.update(materialize(prepared,publisher,request,workdir=Path(workdir)/'payload'))
    local.update(registries=prepared._settings['registries'],registrySourceToken=github.token,
        registrySourceUser=os.environ['GITHUB_ACTOR'],secrets=prepared._settings['probe-secrets'],
        hostKeys=prepared._settings['host-keys'])
    # Re-authorize inside the sole mutation boundary and compare fresh inventory
    # there too; no serialized barrier record is mutation authority on its own.
    def authorize(fresh_request,fresh_resolved):
        result=prepared.authorize(fresh_request,fresh_resolved)
        if result['plan']['stateHandleDigest']!=matches[0]['stateHandleDigest'] or sorted(result['resourceClaims'])!=matches[0]['resourceClaims']:
            fail('preflight-drift','binding changed immediately before IaC')
        return result
    local['iac_authorize']=authorize
    local['bind_created_rest_api']=prepared.bind_created_rest_api
    def before_apply():
        from providers.registry import bind_resolution
        fresh=bind_resolution(request,local['iac_refresh'](request),cloud,prepared._settings['registries'])
        if (fresh['providerIdentity']!=matches[0]['providerIdentity'] or
                sorted(fresh['resourceClaims'])!=matches[0]['resourceClaims'] or
                fresh['existing']!=resolved['existing']):
            fail('preflight-drift','native ownership changed immediately before saved apply')
    local['before_apply']=before_apply
    results=reconcile([{'request':request,'resolved':resolved}],cloud,
        ReceiptStore(github,prepared.repository,actor),context=local)
    for result in results:
        event('apply',result['status'],component=component_id,target=target_id,
            source=request['releaseHeadSha'],version=request['releaseVersion'],digest=request['artifact']['digest'])
    if any(r['status']!='succeeded' for r in results):fail('deployment-failed','native convergence or serving verification failed')
    return results


def public_release_eligible(prepared):
    # Branch convergence uses the complete stage and creates no public Release.
    # Only the independently verified exact version tag may publish.
    return (prepared.current_host['event'] in ('push','create')
        and prepared.current_host['ref']=='refs/tags/'+prepared.manifest['tag'] or
        prepared.current_host['event']=='pull_request_target' and prepared.host.get('closure') is not None
        and prepared.host['callerPath']=='.github/workflows/pr-close.yaml'
        and prepared._source_context['ref']=='refs/tags/'+prepared.manifest['tag'])


def publish(prepared,github,runner,workdir):
    if not public_release_eligible(prepared):
        fail('release-ineligible','public release requires the exact independently verified version tag')
    from release import publish_staged_release
    publisher=ArtifactPublisher(github,runner,'ghcr.io/'+github.repository.lower())
    result=publish_staged_release(prepared.plan,prepared.manifest,github,publisher,workdir)
    event('release','succeeded',source=prepared.plan['headSha'],version=prepared.plan['version'])
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=('inspect','configure','preflight','barrier','apply','publish'))
    parser.add_argument('--stage-artifact-id',required=True);parser.add_argument('--target');parser.add_argument('--component')
    args=parser.parse_args();runner=NativeRunner(inherit_environment=False)
    github=GitHub(os.environ['GITHUB_REPOSITORY']);prepared=prepare(github,runner,args.stage_artifact_id,os.environ)
    if args.command=='inspect':
        output({'environment':prepared.lifecycle['protectedEnvironment'],'matrix':canonical_bytes(matrix(prepared)).decode(),
            'has-bindings':str(bool(matrix(prepared)['include'])).lower(),
            'public-release':str(public_release_eligible(prepared)).lower()},os.environ['GITHUB_OUTPUT']);return
    if args.command=='publish':
        with tempfile.TemporaryDirectory(prefix='cloudopsworks-release-') as directory:
            publish(prepared,github,runner,Path(directory))
        return
    if args.command=='barrier':
        from preflight_barrier import verify_preflight_barrier
        verify_preflight_barrier(prepared,github);return
    if not args.target or not args.component:fail('normal-binding','explicit component and target are required')
    actor=automation_id(github);protected=settings(os.environ);backend=os.environ.get('DEPLOYMENT_STATE_CONF','')
    selected=select(prepared,args.target,args.component,backend,protected,actor)
    if args.command=='configure':output(selected,os.environ['GITHUB_OUTPUT']);return
    workload=read_context(os.environ['WORKLOAD_CONTEXT'],runner_temp=os.environ['RUNNER_TEMP'])
    backend_capture=(copy.deepcopy(workload) if selected['same-binding']=='true' else
        read_context(os.environ['BACKEND_CONTEXT'],runner_temp=os.environ['RUNNER_TEMP']))
    credentials={'workload':workload,'backend':backend_capture}
    prepared.bind(backend,protected,credentials,automation_id=actor)
    with tempfile.TemporaryDirectory(prefix='cloudopsworks-normal-') as directory:
        work=Path(directory);work.chmod(0o700)
        if args.command=='preflight':preflight(prepared,runner,args.target,args.component,credentials,work)
        else:apply(prepared,github,runner,args.target,args.component,credentials,work,actor)


if __name__=='__main__':
    try:main()
    except Exception as error:
        event('apply','failed',failed=1,errorCategory=error_category(error));raise SystemExit(1)
