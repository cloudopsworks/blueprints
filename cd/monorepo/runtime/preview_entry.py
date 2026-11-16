"""Fixed preview route discovery before source artifacts, scans or credentials.

Step outputs are nonsecret routing hints only. Each group-holder invocation must
re-fetch host/API/configuration authority; candidate deployment payloads never
constitute historical ownership proof.
"""
import copy
import os
from pathlib import Path
import tempfile

import authorization as auth
from contracts import canonical_bytes,digest,fail,load_record
from executor import checked
from iac import IaCExecutor
from normal_entry import ROOT,automation_id,output
from preview import verify_pr
from scan_entry import host
from snapshot import materialize_snapshot


def historical_candidates(github,repository,pr,actor):
    found={}
    for entry in github.pages('/deployments?task=cloudopsworks-state'):
        if str(entry.get('creator',{}).get('id'))!=str(actor):continue
        handle=entry.get('payload',{}).get('stateHandle',{})
        if (handle.get('origin',{}).get('repository')==repository
                and handle.get('prNumber')==pr
                and handle.get('scope') in ('preview-component','preview-environment')):
            # No skip for malformed records claiming the selected repository/PR.
            # Full historical origin/canonical handle proof happens independently
            # below, before environment/credential selection or any mutation.
            auth.validate_operation(handle)
            found[digest(handle)]=copy.deepcopy(handle)
    return list(found.values())


def admission(github,runner,environ,event,*,engine=None,preview_target_id=None):
    """Prove fixed caller + actual current host, then identify current PR by API.

    The native event locates a source run/PR, never attests source freshness,
    stage success, scan policy, target configuration or historical ownership.
    Closed PR discovery deliberately does not touch stage artifacts at all.
    """
    blueprint=checked(runner,['git','rev-parse','HEAD'],cwd=ROOT).strip()
    repo,repository=auth._repository(github)
    auth._blueprint(github,blueprint)
    current=host(environ,blueprint)
    default_sha=auth._protected_branch(github,repo['default_branch'])
    actual=auth._current_host(github,current,repository,blueprint,default_sha,preview_target_id=preview_target_id)
    caller=actual.get('path','').split('@',1)[0]
    source=None
    if current['event']=='workflow_run' and caller=='.github/workflows/pr-build.yml':
        locator=event.get('workflow_run',{})
        if not isinstance(locator,dict):fail('preview-source','source locator is unavailable')
        source=auth._run(github,str(locator.get('id')),str(locator.get('run_attempt')))
        prs=source.get('pull_requests',[])
        if (source.get('event')!='pull_request' or source.get('path','').split('@',1)[0]!='.github/workflows/pr-build.yml'
                or str(source.get('repository',{}).get('id'))!=repository['id']
                or str(source.get('head_repository',{}).get('id'))!=repository['id']
                or len(prs)!=1 or type(prs[0].get('number')) is not int):
            fail('preview-source','source is not an exact same-repository PR build')
        pr=prs[0]['number']
    elif current['event']=='pull_request_target' and caller=='.github/workflows/pr-close.yaml':
        pr=event.get('number')
        if event.get('action')!='closed' or type(pr) is not int:
            fail('preview-close-route','fixed close route requires a native closed PR event')
    else:fail('preview-caller','only the fixed PR build/close routes admit preview convergence')
    if type(pr) is not int or pr<1:fail('preview-pr','PR locator is invalid')
    if environ.get('PREVIEW_PR') and environ['PREVIEW_PR']!=str(pr):
        fail('preview-group','native PR differs from fixed holder group')
    fresh=github.repo('GET','/pulls/'+str(pr))
    verify_pr(fresh,repository,closed=fresh.get('state')=='closed')
    engine=engine or IaCExecutor(ROOT,load_record(ROOT/'terraform/monorepo/module-catalog.json'))
    return {'repository':repository,'pr':pr,'current':fresh,'source':source,
        'host':current,'blueprintSha':blueprint,'engine':engine}


def discover(github,runner,environ,event,*,engine=None):
    """Return verified target descriptors; never download source stage/artifacts."""
    route=admission(github,runner,environ,event,engine=engine)
    actor=automation_id(github)
    candidates=historical_candidates(github,route['repository'],route['pr'],actor)
    by_target={}
    for handle in candidates:by_target.setdefault(handle['targetId'],[]).append(handle)
    rows={}
    if route['current']['state']=='open' and route['source'] is None:
        return route,{'include':[]} # Reopened close route never deletes or deploys.
    for target,handles in by_target.items():
        # Closed standing authorization is stronger than candidate discovery.
        # For open/reopened PRs only fixed host-proven historical handles may
        # influence grouping; never borrow standing destructive authority.
        if route['current']['state']=='closed':
            auth.prepare_preview_closure(github,sorted(handles,key=lambda h:h['scope']!='preview-environment'),target,route['pr'],
                blueprint_sha=route['blueprintSha'],executor=runner,engine=route['engine'],current_host=route['host'])
        else:
            probe=auth.PreparedAuthorization(github,runner,route['engine'],route['repository'],{}, {},
                route['host'],{}, {},{}, {},{},None,True)
            for handle in handles:probe._writer_proof(handle,auth._find_handle_entry(github,handle))
        envs={h['protectedEnvironment'] for h in handles}
        if len(envs)!=1:fail('preview-environment','historical target crosses protected environments')
        rows[target]={'id':target,'pr':route['pr'],'environment':next(iter(envs))}
    if route['current']['state']=='open':
        # Target/policy bytes are immutable trusted BASE data, normalized solely
        # by Go. No source checkout, hooks, GitVersion or artifact is involved.
        base=route['current']['base']
        auth._protected_branch(github,base['ref'])
        with tempfile.TemporaryDirectory(prefix='cloudopsworks-preview-discovery-') as directory:
            root=Path(directory).resolve();materialize_snapshot(github,base['sha'],root)
            resolved=auth._json_cli(runner,['validate','--workdir',str(root),'--json'])['resolved']
            lifecycle=auth._json_cli(runner,['lifecycle','--workdir',str(root),'--event','pull_request',
                '--ref','refs/heads/'+route['current']['head']['ref'],'--base-ref',base['ref'],'--json'])
        if lifecycle.get('eligible') and lifecycle.get('deploymentEnabled') and resolved['previewPolicy']['enabled']:
            auth._environment(github,resolved['policy'],lifecycle)
            targets={t['id']:t for t in resolved['targets']}
            for policy in resolved['previewPolicy']['targets']:
                target=targets.get(policy['targetId'])
                if target is None or target['kind'] not in ('aws.eks','gcp.gke','azure.aks'):
                    fail('preview-target','trusted preview target must be Kubernetes')
                row={'id':target['id'],'pr':route['pr'],'environment':lifecycle['protectedEnvironment']}
                if target['id'] in rows and rows[target['id']]!=row:
                    fail('preview-environment','current and historical environments disagree')
                rows[target['id']]=row
    return route,{'include':[rows[key] for key in sorted(rows)]}


EMPTY_MARKER='CLOUDOPSWORKS_PREVIEW_EMPTY_V1 '

def prefix(route,target):
    caller=route['host']['workflowRef'].split('@',1)[0].rsplit('/',1)[-1]
    if caller not in ('pr-build.yml','pr-close.yaml'):fail('preview-caller','fixed preview caller required')
    name=auth.preview_phase_name(caller,target,'root')
    return name.removesuffix('monorepo-preview-root-'+target)


def target_history(github,route,target,actor):
    handles=[h for h in historical_candidates(github,route['repository'],route['pr'],actor) if h['targetId']==target]
    roots=[h for h in handles if h['scope']=='preview-environment']
    if len(roots)>1 or (handles and not roots):fail('preview-history','exact historical namespace root required')
    return handles,roots[0] if roots else None


def prepare_target(github,runner,route,target,*,inspection=False):
    actor=automation_id(github)
    handles,root=target_history(github,route,target,actor)
    if route['current']['state']=='closed':
        prepared=auth.prepare_preview_closure(github,sorted(handles,key=lambda h:h['scope']!='preview-environment'),target,route['pr'],
            blueprint_sha=route['blueprintSha'],executor=runner,engine=route['engine'],current_host=route['host'])
    else:
        source=route['source']
        if not source:fail('preview-source','reopened close event cannot roll out source')
        verify_pr(route['current'],route['repository'],source['head_sha'])
        factory=auth.inspect_verified_context if inspection else auth.prepare_verified_context
        prepared=factory(github,source,blueprint_sha=route['blueprintSha'],executor=runner,
            engine=route['engine'],current_host=route['host'],preview_target_id=target)
        if (prepared.plan['prNumber']!=route['pr'] or not prepared.plan['previewPolicy']['enabled']
                or target not in {t['targetId'] for t in prepared.plan['previewPolicy']['targets']}):
            fail('preview-scope','target not admitted by independently normalized trusted preview policy')
    return prepared,handles,root,actor


def selected(prepared,target,component,backend,protected,actor,*,historical=None,root=None):
    own=prepared.select_preview_bindings(target,component,backend,protected,automation_id=actor,historical_handle=historical)
    root_choice=prepared.select_preview_bindings(target,'',backend,protected,automation_id=actor,historical_handle=root)
    result={side+'-'+key:own[side][source] for side in ('workload','backend')
        for key,source in (('provider','provider'),('ref','authRef'))}
    result['same-binding']=str(own['workload']=={k:own['backend'][k] for k in ('provider','authRef')}).lower()
    result['root-backend-provider']=root_choice['backend']['provider'];result['root-backend-ref']=root_choice['backend']['authRef']
    for side in ('workload','backend'):
        result['root-same-'+side]=str(all(root_choice['backend'][k]==own[side][k] for k in ('provider','authRef'))).lower()
    return result


def current_jobs(github,route):
    jobs=[]
    for page in range(1,101):
        result=github.repo('GET','/actions/runs/'+route['host']['runId']+'/attempts/'+route['host']['runAttempt']+f'/jobs?per_page=100&page={page}')
        rows=result.get('jobs') if isinstance(result,dict) else None
        if not isinstance(rows,list):fail('preview-jobs','current attempt jobs unavailable')
        jobs.extend(rows)
        if len(rows)<100:break
    else:fail('preview-jobs','job inventory bound exceeded')
    for job in jobs:
        if str(job.get('run_id'))!=route['host']['runId'] or str(job.get('run_attempt'))!=route['host']['runAttempt']:
            fail('preview-jobs','job belongs to another host attempt')
    return jobs


def no_failed_predecessor(github,route,target,phase,component):
    """Fresh exact attempt checks supplement fail-fast + max-parallel:1.

    Jobs queued before cancellation still must not submit native mutations after
    a failed/uncertain earlier writer. Cleanup is independent of rollout failure,
    but a failed cleanup stops subsequent cleanup/root destruction.
    """
    stem=prefix(route,target)
    lane='monorepo-preview-cleanup-'+target+'-' if phase in ('cleanup','destroy') else 'monorepo-preview-component-'+target+'-'
    own=stem+lane+component
    for job in current_jobs(github,route):
        if not job.get('name','').startswith(stem+lane) or job.get('name')==own:continue
        if job.get('conclusion') in ('failure','cancelled','timed_out','action_required','stale'):
            fail('preview-predecessor','prior target mutation is failed or uncertain')
        # At max-parallel:1, a distinct executing lane peer is unexpected and
        # must not be interpreted as successfully ordered completion.
        if job.get('status')=='in_progress':fail('preview-predecessor','another target mutation remains active')


def empty_marker(route,handle,root,state,namespace_uid):
    from preview_runtime import _resources
    if _resources(state):fail('preview-cleanup','native managed resources remain after destroy')
    if not namespace_uid:fail('preview-cleanup','root generation UID required for cleanup proof')
    return EMPTY_MARKER+canonical_bytes({'repositoryId':route['repository']['id'],
        'runId':route['host']['runId'],'runAttempt':route['host']['runAttempt'],
        'pr':route['pr'],'target':handle['targetId'],'handleDigest':digest(handle),
        'rootDigest':digest(root),'namespaceUid':namespace_uid,'nativeStateDigest':digest(state)}).decode()


def require_children_empty(github,route,target,handles,root,namespace_uid):
    """Per-handle exact successful job + native-empty receipt, not matrix green."""
    for handle in handles:
        if handle['scope']!='preview-component':continue
        job=auth._job(github,route['host']['runId'],route['host']['runAttempt'],
            prefix(route,target)+'monorepo-preview-cleanup-'+target+'-'+handle['componentId'])
        records=auth._records(github.repo('GET','/actions/jobs/'+str(job['id'])+'/logs',raw=True,limit=auth.MAX_LOG_BYTES),EMPTY_MARKER)
        expected={'repositoryId':route['repository']['id'],'runId':route['host']['runId'],
            'runAttempt':route['host']['runAttempt'],'pr':route['pr'],'target':target,
            'handleDigest':digest(handle),'rootDigest':digest(root),'namespaceUid':namespace_uid}
        matching=[r for r in records if r.get('handleDigest')==digest(handle)]
        if (len(matching)!=1 or set(matching[0])!=set(expected)|{'nativeStateDigest'}
                or any(matching[0].get(k)!=v for k,v in expected.items())
                or not auth._digest(matching[0]['nativeStateDigest'])):
            fail('preview-cleanup-proof','exact current-attempt native-empty child proof missing')


def plan_phases(prepared,handles,root,closed):
    # Matrix descriptors carry no credential/native authority. Each phase
    # re-fetches the exact history and current host before selecting any login.
    cleanup=[{'component':h['componentId'],'handle':digest(h)} for h in handles if h['scope']=='preview-component']
    if len({r['component'] for r in cleanup})!=len(cleanup):fail('preview-history','component has multiple historical native owners')
    components=[] if closed else [{'component':c['id'],'handle':''} for c in prepared.plan['components']
        if c['preview']['mode']!='artifact-only']
    retire=[] if closed else [r for r in cleanup if r['component'] not in {c['id'] for c in prepared.plan['components']}]
    return {'components':{'include':components},'cleanup':{'include':cleanup},'retire':{'include':retire},
        'has-retire':str(bool(retire)).lower(),
        'has-components':str(bool(components)).lower(),'has-cleanup':str(bool(cleanup)).lower(),
        'root-handle':digest(root) if root else ''}


def find_handle(handles,component,handle_digest):
    if not handle_digest:return None
    matches=[h for h in handles if h['componentId']==(component or None) and digest(h)==handle_digest]
    if len(matches)!=1:fail('preview-history','exact selected historical tuple missing')
    return matches[0]


def controller(github,runner,route,prepared,target,credentials,root_capture,workdir):
    from normal_entry import configure_kubeconfig
    from protected_runtime import context as protected_context
    from preview_runtime import context as preview_context
    from preview import IaCPreview
    target_config=next((t for t in prepared.plan['targets'] if t['id']==target),None)
    if target_config is None:fail('preview-target','historical/current cluster target unavailable')
    native=Path(workdir)/'native';native.mkdir(mode=0o700)
    kube=native/'kubeconfig'
    setup=Path(workdir)/'setup';setup.mkdir(mode=0o700)
    pair=copy.deepcopy(credentials);pair['workload']['environment']['KUBECONFIG']=str(kube)
    _,cloud=protected_context(prepared,runner,workdir=setup,credentials=pair,kubeconfig=kube)
    configure_kubeconfig(target_config,cloud,kube)
    runtime=preview_context(prepared,runner,target_id=target,pr=route['pr'],workdir=native,
        credentials=pair,kubeconfig=kube,root_backend_capture=root_capture)
    # preview_context requires private kubeconfig inside its own workdir.
    return IaCPreview(github,route['repository'],route['pr'],target,prepared.plan['headSha'],runtime)


def attach_root(ctrl,*,closed):
    roots=[h for h in ctrl._handles() if h['scope']=='preview-environment']
    if len(roots)!=1:fail('preview-history','phase requires exact verified environment root')
    ctrl.root_handle=roots[0];ctrl.owned=ctrl._generation(roots[0],absent=closed)
    return roots[0]


def recover_values(prepared,ctrl,bound,work):
    from iac_values import recovery_values
    handle=bound['plan']['stateHandle'];projection=prepared.recovery_inputs(handle)
    state=ctrl.context['private_state'](handle)
    row=bound['engine'].catalog['modules'][handle['moduleId']]
    metadata=load_record(bound['engine'].root/row['path']/'inputs.json')
    scaffold=Path(work)/'evaluation';scaffold.mkdir(mode=0o700)
    isolation=None
    if handle['scope']=='preview-environment':
        history=prepared._writer_proof(handle,auth._find_handle_entry(prepared.github,handle))
        policy=next(p['isolation'] for p in history.plan['previewPolicy']['targets'] if p['targetId']==handle['targetId'])
        isolation={k:copy.deepcopy(policy[k]) for k in ('probeImage','controlNamespace','ingressNamespaceSelector','ingressPodSelector','dnsNamespaceSelector','dnsPodSelector')}
        if not ctrl.owned or 'ingress' not in ctrl.owned['ownedIds']['probes']:
            fail('preview-cleanup','historical native ingress parent unavailable')
        isolation['ingressNamespace']=ctrl.owned['ownedIds']['probes']['ingress']['namespace']
    return recovery_values(projection['inputs'],metadata,handle,state,work=scaffold,
        package_handler=projection['packageHandler'],chart_path=ROOT/'kubernetes/helm/charts',
        kubeconfig_path=ctrl.context['kubeconfigPath'],preview_isolation=isolation)


def execute_phase(github,runner,route,prepared,target,phase,component,historical,credentials,root_capture,workdir,*,failure_isolation=False,emit=print):
    """One static-auth job, one private native plan, no cross-job credentials."""
    from preview import isolation_preflight,current_namespace,owner
    closed=route['current']['state']=='closed'
    ctrl=controller(github,runner,route,prepared,target,credentials,root_capture,workdir)
    ctrl.context['before_apply']=lambda plan:no_failed_predecessor(github,route,target,phase,component)
    policy=next(p for p in prepared.plan['previewPolicy']['targets'] if p['targetId']==target)
    if phase=='root':
        if closed:fail('preview-phase','closed PR cannot create preview root')
        artifact=prepared.manifest['components'][0]['mainArtifact']
        ctrl.environment(artifact,policy,workdir)
        try:
            proof=isolation_preflight(ctrl.executor,ctrl.owned['namespace'],policy,
                ctrl.root_handle['resourceIdentity']['provider'],resolution=ctrl.owned)
        except auth.ContractError as error:
            if error.code in {'isolation-admission','isolation-network','isolation-ingress','isolation-enforcement','isolation-control'}:
                ctrl._guard()
                marker={'repositoryId':route['repository']['id'],'prNumber':route['pr'],'targetId':target,
                    'sourceSha':prepared.plan['headSha'],'namespace':ctrl.owned['namespace'],'namespaceUid':ctrl.owned['uid'],
                    'stateHandleDigest':digest(ctrl.root_handle),'status':'isolation-failed',
                    'checks':[{'id':error.code,'status':'failed'}]}
                emit('CLOUDOPSWORKS_PREVIEW_ISOLATION_V1 '+canonical_bytes(marker).decode(),flush=True)
                output({'failure-cleanup':'true'},os.environ['GITHUB_OUTPUT'])
            raise
        ctrl._guard()
        emit('CLOUDOPSWORKS_PREVIEW_READY_ISOLATION_V1 '+canonical_bytes({
            'repositoryId':route['repository']['id'],'runId':route['host']['runId'],'runAttempt':route['host']['runAttempt'],
            'pr':route['pr'],'target':target,'sourceSha':prepared.plan['headSha'],'rootDigest':digest(ctrl.root_handle),
            'namespaceUid':ctrl.owned['uid'],'isolation':proof}).decode(),flush=True)
        return
    root=attach_root(ctrl,closed=closed)
    if phase=='component':
        if closed:fail('preview-phase','closed PR cannot deploy a component')
        config=next((c for c in prepared.plan['components'] if c['id']==component),None)
        record=next((c for c in prepared.manifest['components'] if c['componentId']==component),None)
        if not config or not record or config['preview']['mode']=='artifact-only' or not record['previewArtifact']:
            fail('preview-component','component lacks authorized preview descriptor')
        from release import ArtifactPublisher
        publisher=ArtifactPublisher(github,runner,'ghcr.io/'+github.repository.lower())
        # Exact Actions bytes are transported by the existing publisher, never
        # source builds or a fabricated image/provenance record.
        artifact=publisher.publish(record['previewArtifact'],component,'preview',Path(workdir),None,None,prepared.repository)
        ctrl.component(config,artifact,policy,workdir)
        return
    if phase in ('cleanup','destroy'):
        handle=historical if phase=='cleanup' else root
        if handle is None or (phase=='cleanup' and handle['scope']!='preview-component'):
            fail('preview-cleanup','exact historical component required')
        if not closed:
            if failure_isolation:bound=prepared.failure_preview(handle,root_handle=root,namespace_uid=ctrl.owned['uid'])
            elif phase=='destroy':fail('preview-cleanup','open environment teardown lacks standing authority')
            else:bound=prepared.retire_preview(handle)
        else:bound=prepared.recover_preview(handle)
        if phase=='destroy':
            if not ctrl.owned:
                fail('preview-cleanup','root generation proof missing; no teardown submission')
            before=ctrl.context['before_apply']
            def all_children(plan):
                before(plan)
                require_children_empty(github,route,target,ctrl._handles(),root,ctrl.owned['uid'])
            ctrl.context['before_apply']=all_children
        values=recover_values(prepared,ctrl,bound,workdir)
        ctrl._execute(bound,values,closed=closed)
        state=ctrl.context['private_state'](handle)
        if phase=='cleanup':
            emit(empty_marker(route,handle,root,state,ctrl.owned['uid']),flush=True)
        else:
            from preview_runtime import _resources
            if _resources(state):fail('preview-cleanup','native root/probe resources remain after destroy')
            if current_namespace(ctrl.executor,root['resourceIdentity']['namespace'],owner(route['repository'],route['pr'],target)):
                fail('preview-cleanup','namespace remains after root destroy')
        return
    if phase=='readiness':
        if closed:fail('preview-phase','closed PR cannot be ready')
        ctrl._guard()
        save_ready(github,runner,route,prepared,target,ctrl,policy,workdir)
        return
    if phase=='absence':
        if not closed:fail('preview-phase','absence verification requires current closed PR')
        if current_namespace(ctrl.executor,root['resourceIdentity']['namespace'],owner(route['repository'],route['pr'],target)):
            fail('preview-cleanup','namespace absence not established')
        if ctrl.context['native_owned'](root) is not None:fail('preview-cleanup','root private owned state not empty')
        from contracts import API_VERSION
        from preview import PreviewStore
        state={'apiVersion':API_VERSION,'kind':'PreviewState','repository':route['repository'],'prNumber':route['pr'],
            'targetId':target,'namespace':root['resourceIdentity']['namespace'],'headSha':route['current']['head']['sha'],
            'runId':route['host']['runId'],'phase':'closed','isolation':None,'components':[]}
        PreviewStore(github,route['repository'],route['pr'],target,automation_id(github)).save(state,{})
        return
    fail('preview-phase','unsupported fixed preview phase')



def save_ready(github,runner,route,prepared,target,ctrl,policy,workdir):
    from contracts import API_VERSION
    from preview import PreviewStore,verify_spec_source,_verify_component
    from release import ArtifactPublisher
    from diagnostics import event
    job=auth._job(github,route['host']['runId'],route['host']['runAttempt'],prefix(route,target)+'monorepo-preview-root-'+target)
    proofs=auth._records(github.repo('GET','/actions/jobs/'+str(job['id'])+'/logs',raw=True,limit=auth.MAX_LOG_BYTES),
        'CLOUDOPSWORKS_PREVIEW_READY_ISOLATION_V1 ')
    expected={'repositoryId':route['repository']['id'],'runId':route['host']['runId'],'runAttempt':route['host']['runAttempt'],
        'pr':route['pr'],'target':target,'sourceSha':prepared.plan['headSha'],'rootDigest':digest(ctrl.root_handle),
        'namespaceUid':ctrl.owned['uid']}
    if len(proofs)!=1 or set(proofs[0])!=set(expected)|{'isolation'} or any(proofs[0].get(k)!=v for k,v in expected.items()):
        fail('preview-isolation-proof','exact current-attempt successful root isolation proof required')
    proof=proofs[0]['isolation']
    if proof.get('policyDigest')!=digest({'isolation':policy['isolation'],'ownerDigest':digest(ctrl.root_handle),
            'policies':sorted(ctrl.owned['ownedIds']['policies'])}):
        fail('preview-isolation-proof','current native policies differ from isolation verification')
    state={'apiVersion':API_VERSION,'kind':'PreviewState','repository':route['repository'],'prNumber':route['pr'],
        'targetId':target,'namespace':ctrl.owned['namespace'],'headSha':prepared.plan['headSha'],'runId':route['host']['runId'],
        'phase':'ready','isolation':proof,'components':[]}
    records={c['componentId']:c for c in prepared.manifest['components']}
    publisher=ArtifactPublisher(github,runner,'ghcr.io/'+github.repository.lower())
    artifacts={};sources={};configs={}
    for component in prepared.plan['components']:
        ident=component['id'];record=records[ident];artifact_only=component['preview']['mode']=='artifact-only'
        if artifact_only:
            artifact=record['mainArtifact'];location=artifact['location']
            if artifact['kind']!='openapi' or location['kind']!='actions-artifact':
                fail('preview-spec-source','artifact-only preview requires exact immutable Actions spec provenance')
            source={'artifactId':location['artifactId'],'runId':location['runId'],'runAttempt':location['runAttempt'],
                'headSha':artifact['sourceSha'],'componentId':ident,'path':location['path'],
                'name':location['artifactName'],'url':'https://github.com/'+route['repository']['fullName']+'/actions/runs/'+location['runId']+'/artifacts/'+location['artifactId']}
            link=verify_spec_source(github,route['repository'],route['pr'],ident,artifact,source);sources[ident]=source
            event('preview-spec','published',component=ident,target=target,namespace=ctrl.owned['namespace'],
                provider=ctrl.root_handle['resourceIdentity']['provider'],source=artifact['sourceSha'],version=artifact['builtVersion'],digest=artifact['digest'],artifactLink={'repository':route['repository']['fullName'],
                'runId':source['runId'],'artifactId':source['artifactId'],'url':link})
        else:
            artifact=publisher.publish(record['previewArtifact'],ident,'preview',Path(workdir),None,None,prepared.repository)
            _verify_component(ctrl.executor,ctrl.owned['namespace'],component,artifact,policy,workdir,context=ctrl.context)
        event('preview-readiness','artifact-only' if artifact_only else 'ready',component=ident,target=target,
            namespace=ctrl.owned['namespace'],provider=ctrl.root_handle['resourceIdentity']['provider'],digest=artifact['digest'])
        artifacts[ident]=artifact
        configs[ident]=digest({'domain':'effective-preview/v1','projection':component['preview'],'policy':policy,
            'target':next(t for t in prepared.plan['targets'] if t['id']==target),'chart':'blueprints@v5.11.0/kubernetes/helm/charts','runtime':{}})
        state['components'].append({'componentId':ident,'status':'artifact-only' if artifact_only else 'ready',
            'releaseName':None if artifact_only else ident,'desiredDigest':artifact['digest'],'successfulDigest':artifact['digest'],'error':None})
    ctrl._guard() # No ready receipt after a late PR/head/UID change.
    PreviewStore(github,route['repository'],route['pr'],target,automation_id(github)).save(state,artifacts,configs,sources)

def main():
    import argparse
    from credential_context import read_context
    from github import GitHub
    from normal_entry import NativeRunner,settings
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=('discover','admit','scan-inspect','scan-run','scan-barrier','configure','execute'))
    parser.add_argument('--target');parser.add_argument('--environment');parser.add_argument('--phase',choices=('root','component','cleanup','destroy','absence','readiness'))
    parser.add_argument('--component',default='');parser.add_argument('--handle',default='')
    parser.add_argument('--failure-isolation',action='store_true');args=parser.parse_args()
    runner=NativeRunner(inherit_environment=False);github=GitHub(os.environ['GITHUB_REPOSITORY'])
    native_event=load_record(Path(os.environ['GITHUB_EVENT_PATH']))
    if args.command=='discover':
        _,matrix=discover(github,runner,os.environ,native_event)
        output({'matrix':canonical_bytes(matrix).decode(),'has-targets':str(bool(matrix['include'])).lower()},os.environ['GITHUB_OUTPUT']);return
    if not args.target:fail('preview-target','explicit admitted target required')
    route=admission(github,runner,os.environ,native_event,preview_target_id=args.target)
    if args.command=='admit' and route['current']['state']=='open' and route['source'] is None:
        output({'phase':'reopened','components':'{\"include\":[]}','cleanup':'{\"include\":[]}','retire':'{\"include\":[]}',
            'has-components':'false','has-cleanup':'false','has-retire':'false'},os.environ['GITHUB_OUTPUT']);return
    inspection=args.command in ('admit','scan-inspect','scan-run','scan-barrier')
    prepared,handles,root,actor=prepare_target(github,runner,route,args.target,inspection=inspection)
    if args.environment!=prepared.lifecycle['protectedEnvironment']:
        fail('preview-environment','job protected environment differs from independent policy')
    closed=route['current']['state']=='closed'
    if args.command=='admit':
        values=plan_phases(prepared,handles,root,closed)
        values={k:canonical_bytes(v).decode() if isinstance(v,dict) else v for k,v in values.items()}
        values['phase']='closed' if closed else 'open'
        output(values,os.environ['GITHUB_OUTPUT']);return
    if args.command.startswith('scan-'):
        if closed:fail('preview-phase','closed convergence must not require source scans')
        from scan_entry import outputs,scan,barrier
        if args.command=='scan-inspect':outputs(prepared,'scan-plan.json',os.environ['GITHUB_OUTPUT'],args.component or None)
        elif args.command=='scan-barrier':barrier(prepared,github)
        else:
            credentials={key:os.environ[name] for key,name in {
                'sonarqube_url':'SONARQUBE_URL','sonarqube_token':'SONARQUBE_TOKEN','dtrack_url':'DEPENDENCYTRACK_URL',
                'dtrack_token':'DEPENDENCYTRACK_TOKEN','snyk_token':'SNYK_TOKEN','semgrep_token':'SEMGREP_TOKEN'}.items() if os.environ.get(name)}
            scan(prepared,github,runner,Path('source'),credentials,component_id=args.component or None)
        return
    if not args.phase:fail('preview-phase','fixed execution phase required')
    import re
    if (args.phase in ('root','destroy','absence','readiness') and (args.component or args.handle)) or (
            args.phase in ('component','cleanup') and not re.fullmatch('[a-z][a-z0-9-]{0,47}',args.component)):
        fail('preview-phase','component and phase scope disagree')
    if args.failure_isolation and args.phase not in ('cleanup','destroy'):
        fail('preview-phase','isolation cleanup policy cannot authorize rollout')
    historical=find_handle(handles,args.component,args.handle)
    if args.phase in ('cleanup',) and historical is None:fail('preview-history','cleanup requires selected historical handle digest')
    protected=settings(os.environ);backend=os.environ.get('DEPLOYMENT_STATE_CONF','')
    chosen=selected(prepared,args.target,args.component,backend,protected,actor,historical=historical,root=root)
    if args.command=='configure':output(chosen,os.environ['GITHUB_OUTPUT']);return
    workload=read_context(os.environ['WORKLOAD_CONTEXT'],runner_temp=os.environ['RUNNER_TEMP'])
    backend_capture=copy.deepcopy(workload) if chosen['same-binding']=='true' else read_context(os.environ['BACKEND_CONTEXT'],runner_temp=os.environ['RUNNER_TEMP'])
    root_capture=(copy.deepcopy(workload) if chosen['root-same-workload']=='true' else copy.deepcopy(backend_capture)
        if chosen['root-same-backend']=='true' else read_context(os.environ['ROOT_BACKEND_CONTEXT'],runner_temp=os.environ['RUNNER_TEMP']))
    pair={'workload':workload,'backend':backend_capture};prepared.bind(backend,protected,pair,automation_id=actor)
    with tempfile.TemporaryDirectory(prefix='cloudopsworks-preview-phase-') as directory:
        work=Path(directory);work.chmod(0o700)
        execute_phase(github,runner,route,prepared,args.target,args.phase,args.component,historical,pair,root_capture,work,failure_isolation=args.failure_isolation)


if __name__=='__main__':
    from diagnostics import event,error_category
    try:main()
    except Exception as error:
        event('preview','failed',failed=1,errorCategory=error_category(error));raise SystemExit(1)
