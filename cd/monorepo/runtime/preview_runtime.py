"""Read-only native preview context. Protected host authorization stays shared.

No source code, YAML parser, cloud SDK, INIT, import, kubectl writer or Helm writer
is used here. The fixed entry supplies an already bound PreparedAuthorization and
private selected workload/backend captures. Closure's prepared context comes from
prepare_preview_closure, not the manual recovery factory or a serialized bundle.
"""
import copy
import json
import hashlib
from pathlib import Path
from urllib.parse import urlsplit
from authorization import PreparedAuthorization
from contracts import digest,fail,load_record,_pairs,_constant
from credential_context import backend_configuration,credential_environment
from executor import checked
from private_state import read_private_state
from protected_runtime import context as protected_context


def _require(condition,code):
    if not condition:fail(code,'verified preview native context is unavailable')


def _command(cloud,argv,*,absent=False):
    text=checked(cloud,argv)
    if not text.strip() and absent:return None
    try:return json.loads(text,object_pairs_hook=_pairs,parse_constant=_constant)
    except (ValueError,TypeError):fail('preview-inventory','native inventory is invalid')


def _resources(state):
    _require(isinstance(state,dict) and state.get('version')==4 and isinstance(state.get('resources'),list),'preview-private-state')
    result={}
    for resource in state['resources']:
        if resource.get('mode')=='data':continue
        _require(resource.get('mode')=='managed' and not resource.get('module'),'preview-private-state')
        for instance in resource.get('instances',[]):
            _require(not instance.get('deposed'),'preview-private-state')
            key=(resource['type'],resource['name'],instance.get('index_key'))
            _require(key not in result,'preview-private-state')
            result[key]=instance.get('attributes',{})
    return result


def owned_environment(handle,state):
    """Bind every exported native ID/UID to actual v4 managed resource state."""
    resources=_resources(state)
    if not resources:return None
    expected={('kubernetes_namespace_v1','environment',None)}
    expected|={('kubernetes_network_policy_v1',p,None) for p in ('default_deny','same_namespace','dns','ingress')}
    expected|={('kubernetes_pod_v1','probe',p) for p in ('canary','control','ingress')}
    _require(set(resources)<=expected,'preview-private-addresses')
    namespace=resources.get(('kubernetes_namespace_v1','environment',None))
    _require(isinstance(namespace,dict),'preview-private-namespace')
    metadata=namespace.get('metadata')
    _require(isinstance(metadata,list) and len(metadata)==1,'preview-private-resource')
    meta=metadata[0];name=handle['resourceIdentity']['namespace'];hd=digest(handle)
    _require(meta.get('name')==name and isinstance(meta.get('uid'),str) and meta['uid']
        and namespace.get('id')==name,'preview-private-uid')
    # A failed native apply/destroy may checkpoint only some managed children
    # and omit/stale its root outputs. Recover exact IDs from actual v4 resource
    # attributes, never invent a UID or require an all-or-nothing successful apply.
    owned={'namespace':name,'uid':meta['uid'],'owner_digest':hd,
        'ownedIds':{'namespace':name,'policies':[],'probes':{}}}
    for key,attributes in resources.items():
        metadata=attributes.get('metadata')
        _require(isinstance(metadata,list) and len(metadata)==1,'preview-private-resource')
        meta=metadata[0]
        _require(meta.get('annotations',{}).get('cloudopsworks.io/owner-digest')==hd,'preview-private-owner')
        if key[0]=='kubernetes_network_policy_v1':
            fixed={'default_deny':'cloudopsworks-default-deny','same_namespace':'cloudopsworks-same-namespace','dns':'cloudopsworks-dns','ingress':'cloudopsworks-ingress'}
            _require(meta.get('name')==fixed[key[1]],'preview-private-policy')
            ident=attributes.get('id')
            _require(meta.get('namespace')==name and ident==name+'/'+meta.get('name',''),'preview-private-policy')
            owned['ownedIds']['policies'].append(ident)
        elif key[0]=='kubernetes_pod_v1':
            probe={field:meta.get(field) for field in ('name','namespace','uid')};probe['id']=attributes.get('id')
            identity=handle['origin']['repository']['id']+':'+str(handle['prNumber'])+':'+handle['targetId']
            suffix=hashlib.sha256(identity.encode()).hexdigest()[:20]
            expected_name='cloudopsworks-canary' if key[2]=='canary' else 'cw-'+key[2]+'-'+suffix
            _require(probe['name']==expected_name and (key[2]!='canary' or probe['namespace']==name),'preview-private-probe')
            _require(all(isinstance(v,str) and v for v in probe.values())
                and probe['id']==probe['namespace']+'/'+probe['name']
                and meta.get('annotations',{}).get('cloudopsworks.io/environment-uid')==owned['uid'],'preview-private-probe')
            owned['ownedIds']['probes'][key[2]]=probe
    _require(len(owned['ownedIds']['policies'])==len(set(owned['ownedIds']['policies'])),'preview-private-policy')
    output=state.get('outputs',{}).get('owned')
    if output is not None:
        _require(isinstance(output,dict) and output.get('sensitive') is False,'preview-private-output')
        value=output.get('value')
        _require(isinstance(value,dict) and set(value)=={'namespace','uid','owner_digest','ownedIds'}
            and all(value.get(k)==owned[k] for k in ('namespace','uid','owner_digest')),'preview-private-output')
        # Child outputs can lag a failed replacement while native resource
        # checkpoints already contain the new UID. Actual managed attributes
        # above, not a stale successful-output envelope, are recovery evidence.
    owned['ownedIds']['policies'].sort()
    return owned


def _cluster(target,cloud,kubeconfig,expected,*,tenant=None):
    """Fresh native account/cluster + private kubeconfig endpoint binding."""
    if target['provider']=='aws':
        from providers.aws import cli
        account=cli(cloud,target,'sts','get-caller-identity')['Account']
        cluster=cli(cloud,target,'eks','describe-cluster','--name',target['cluster'])['cluster']
        ident='arn:aws:eks:'+target['region']+':'+account+':cluster/'+target['cluster']
        _require(cluster.get('arn')==ident,'preview-cluster')
        endpoint=cluster.get('endpoint');ca=cluster.get('certificateAuthority',{}).get('data')
    elif target['provider']=='gcp':
        from providers.gcp import cli
        project=cli(cloud,target,'projects','describe',target['project'])
        account=str(project['projectNumber'])
        _require(project.get('projectId')==target['project'] and project.get('lifecycleState','ACTIVE')=='ACTIVE','preview-cluster')
        cluster=cli(cloud,target,'container','clusters','describe',target['cluster'],'--location',target['location'])
        expected_link='https://container.googleapis.com/v1/projects/'+target['project']+'/locations/'+target['location']+'/clusters/'+target['cluster']
        _require(cluster.get('name')==target['cluster'] and cluster.get('selfLink') in
            (expected_link,expected_link.replace('/locations/','/zones/')),'preview-cluster')
        ident=expected_link.replace('/projects/'+target['project']+'/', '/projects/'+account+'/')
        endpoint='https://'+str(cluster.get('endpoint',''));ca=cluster.get('masterAuth',{}).get('clusterCaCertificate')
    elif target['provider']=='azure':
        from providers.azure import cli
        from providers.common import resource_id
        current=cli(cloud,target,'account','show');account=current['id'].casefold()
        _require(current.get('state')=='Enabled' and account==target['subscriptionId'].casefold()
            and (tenant is None or current.get('tenantId','').casefold()==tenant.casefold()),'preview-cluster')
        cluster=cli(cloud,target,'aks','show','--resource-group',target['resourceGroup'],'--name',target['cluster'])
        ident='/subscriptions/'+account+'/resourcegroups/'+target['resourceGroup'].casefold()+'/providers/microsoft.containerservice/managedclusters/'+target['cluster'].casefold()
        _require(resource_id(cluster.get('id',''))==ident,'preview-cluster')
        endpoint=None;ca=None
    else:fail('preview-cluster','Kubernetes preview provider is unsupported')
    _require(account==expected,'preview-account')
    config=load_record(checked(cloud,['kubectl','config','view','--raw','--output=json'],env={'KUBECONFIG':str(kubeconfig)}))
    contexts=[c for c in config.get('contexts',[]) if c.get('name')==config.get('current-context')]
    _require(len(contexts)==1,'preview-kubeconfig')
    clusters=[c['cluster'] for c in config.get('clusters',[]) if c.get('name')==contexts[0].get('context',{}).get('cluster')]
    _require(len(clusters)==1 and not clusters[0].get('insecure-skip-tls-verify'),'preview-kubeconfig')
    if endpoint:
        _require(clusters[0].get('server')==endpoint and isinstance(ca,str) and ca
            and clusters[0].get('certificate-authority-data')==ca,'preview-kubeconfig')
    else:
        host=urlsplit(clusters[0].get('server','')).hostname
        _require(host and host in {cluster.get('fqdn'),cluster.get('privateFqdn')}
            and clusters[0].get('certificate-authority-data'),'preview-kubeconfig')
    return account,ident


def context(prepared,runner,*,target_id,pr,workdir,credentials,kubeconfig,root_backend_capture=None):
    """Construct controller callbacks after shared host and pair authorization.

    Central fixed entry acquires/captures the selected pair and calls bind first;
    no principal is inferred from backend buckets or ambient process credentials.
    """
    _require(isinstance(prepared,PreparedAuthorization) and getattr(prepared,'store',None) is not None,'preview-authority')
    _require(isinstance(credentials,dict) and set(credentials)=={'workload','backend'},'preview-credentials')
    path=Path(kubeconfig)
    _require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(Path(workdir).resolve())
        and not path.stat().st_mode&0o077,'preview-kubeconfig')
    pair=copy.deepcopy(credentials);pair['workload']['environment']['KUBECONFIG']=str(path)
    local,cloud=protected_context(prepared,runner,workdir=workdir,credentials=pair,kubeconfig=path)
    repository=prepared.repository
    def handles(selected_target):
        _require(selected_target==target_id,'preview-scope')
        result={}
        for entry in prepared.store.entries():
            h=entry['payload']['stateHandle']
            if h['targetId']==target_id and h['prNumber']==pr:
                _require(h['origin']['repository']==repository and h['scope'] in ('preview-component','preview-environment')
                    and h['ownership']=='managed','preview-history')
                result[digest(h)]=copy.deepcopy(h)
        return list(result.values())
    def verified(h):
        _require(any(old==h for old in handles(target_id)),'preview-history')
    def state(h):
        verified(h)
        if h['scope']=='preview-environment' and root_backend_capture is not None:
            env=prepared.backend_read_credentials(h,root_backend_capture)
        else:
            backend_configuration(h,pair['backend'])
            env=credential_environment(pair['backend'])
        return read_private_state(h,runner,workdir=workdir,env={'PATH':cloud.environment['PATH'],**env})
    def native_owned(h):
        known=handles(target_id)
        if not any(old==h for old in known):
            # The sole fresh exception is the exact locally generated canonical
            # operation already authorized by PreparedAuthorization, not a wire
            # boolean or a claimed current-run origin.
            pending=prepared._pending.get(digest(h))
            _require(pending and pending['handle']==h and not any(old['native']==h['native'] for old in known),'preview-history')
            return None
        target=h['resourceIdentity']
        _cluster(target,cloud,path,h['providerIdentity'],tenant=pair['workload']['identity'].get('tenantId'))
        return owned_environment(h,state(h))
    def resolve_preview(selected_target,component):
        _require(selected_target==target_id,'preview-scope')
        target=next((t for t in prepared.plan['targets'] if t['id']==target_id),None)
        _require(target and prepared.plan['prNumber']==pr,'preview-target')
        expected=credentials['workload']['identity'][{'aws':'accountId','gcp':'projectNumber','azure':'subscriptionId'}[target['provider']]]
        account,cluster=_cluster(target,cloud,path,expected,tenant=pair['workload']['identity'].get('tenantId'))
        previous=[h for h in handles(target_id) if h['componentId']==(component or None)]
        _require(len(previous)<=1,'preview-history')
        historical=previous[0] if previous else None
        backend=({k:v for k,v in historical['backend'].items() if k not in ('key','prefix')}
            if historical else prepared._backend)
        operation=prepared._operation(target=target,component=component,operation='preview',provider_identity=account,
            backend=backend,auth_refs=historical['authRefs'] if historical else [target['authRef']],historical=historical)
        handle=operation['stateHandle'];name=handle['resourceIdentity']['namespace']
        ns=_command(cloud,['kubectl','get','namespace',name,'--ignore-not-found','--output=json'],absent=True)
        # Empty stdout is an explicitly successful absent inventory, never a
        # CLI error or an exception interpreted as an absent namespace.
        if component:
            releases=_command(cloud,['helm','list','--namespace',name,'--all','--max','257','--output','json']) if ns else []
            _require(isinstance(releases,list) and len(releases)<257,'preview-inventory')
            matches=[r for r in releases if r.get('name')==component]
            _require(len(matches)<=1,'preview-inventory')
            exists=bool(matches)
            if exists:
                _require(historical is not None,'preview-adoption')
                resources=_resources(state(historical));native=resources.get(('helm_release','component',None),{})
                status=load_record(checked(cloud,['helm','status',component,'--namespace',name,'--output','json']))
                _require(native.get('id')==component and native.get('namespace')==name
                    and native.get('description')==digest(historical)
                    and status.get('name')==component and status.get('namespace')==name
                    and status.get('info',{}).get('description')==digest(historical),'preview-native-release')
            claims=[cluster+'/namespace/'+name+'/release/'+component]
        else:
            exists=bool(ns)
            if exists:
                _require(historical is not None,'preview-adoption')
                owned=native_owned(historical)
                _require(owned and ns.get('metadata',{}).get('uid')==owned['uid']
                    and ns['metadata'].get('annotations',{}).get('cloudopsworks.io/owner-digest')==digest(historical),'preview-native-namespace')
            if historical:
                _require(native_owned(historical) is not None,'preview-native-namespace')
            policy=next(p for p in prepared.plan['previewPolicy']['targets'] if p['targetId']==target_id)['isolation']
            selector=','.join(k+'='+v for k,v in sorted(policy['ingressNamespaceSelector'].items()))
            parents=_command(cloud,['kubectl','get','namespaces','--selector',selector,'--output=json'])
            _require(isinstance(parents,dict) and len(parents.get('items',[]))==1,'preview-ingress-parent')
            ingress=parents['items'][0]['metadata']['name']
            # Fixed native root child naming, NOT namespace/target selection.
            # The namespace itself above always comes from the sole Go plan.
            key=hashlib.sha256((repository['id']+':'+str(pr)+':'+target_id).encode()).hexdigest()[:20]
            external=[{'namespace':policy['controlNamespace'],'name':'cw-control-'+key},
                      {'namespace':ingress,'name':'cw-ingress-'+key}]
            if not historical:
                for probe in external:
                    current=_command(cloud,['kubectl','get','pod',probe['name'],'--namespace',probe['namespace'],
                        '--ignore-not-found','--output=json'],absent=True)
                    _require(current is None,'preview-probe-adoption')
            claims=sorted([cluster+'/namespace/'+name]+[cluster+'/namespace/'+p['namespace']+'/pod/'+p['name'] for p in external])
            if historical:
                recorded=[e['payload']['resourceClaims'] for e in prepared.store.entries() if e['payload']['stateHandle']==historical]
                _require(recorded and all(set(claims)<=set(old) for old in recorded),'preview-claim-drift')
                # Never drop a reservation after partial cleanup/uncertainty.
                claims=sorted(set().union(*map(set,recorded)))

        return {'providerIdentity':account,'resourceClaims':claims,'resource':ns,
            'existing':{'providerIdentity':account,'exists':exists,'ownerDigest':digest(historical) if exists else None}}
    def recover_preview(h):
        verified(h)
        _require(callable(getattr(prepared,'recover_preview',None)),'preview-closure-authority')
        if hasattr(prepared,'_preview_closure'):return prepared.recover_preview(h)
        _require(callable(getattr(prepared,'retire_preview',None)),'preview-retirement-authority')
        return prepared.retire_preview(h)
    return {'prepared':prepared,'credentials':pair,'cloud':cloud,'kubeconfigPath':path,'engine':prepared.engine,
        'resolve_preview':resolve_preview,'preview_handles':handles,'native_owned':native_owned,'recover_preview':recover_preview,
        'private_state':state}
