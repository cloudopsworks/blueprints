"""Single-owner Kubernetes previews. No PR source/chart is ever executed here."""
from __future__ import annotations
import copy
import datetime as dt
import hashlib
import io
import json
from pathlib import Path
import re
import socket
import tempfile
import zipfile
from contracts import API_VERSION, canonical_bytes, digest, fail, load_record, safe_path, validate_linked, validate_record
from executor import checked
from diagnostics import event, observed

MANAGED = 'cloudopsworks.io/managed-by'


def namespace(repository_id, pr, target):
    identity = f'{repository_id}:{pr}:{target}'
    return f'pr-{pr}-{target[:20]}-' + hashlib.sha256(identity.encode()).hexdigest()[:12]


def concurrency_key(repository_id, pr, target):
    return f'monorepo-preview-{repository_id}-{pr}-{target}'


def owner(repository, pr, target):
    return {MANAGED: 'blueprints-monorepo', 'cloudopsworks.io/repository-id': repository['id'],
            'cloudopsworks.io/pr': str(pr), 'cloudopsworks.io/target-id': target}


def verify_run(github, run_id, workflow_id, repository):
    run = github.repo('GET', '/actions/runs/' + str(run_id))
    if not run or str(run['id']) != str(run_id) or str(run.get('workflow_id')) != str(workflow_id) or run.get('event') != 'pull_request' or run.get('status') != 'completed' or run.get('conclusion') != 'success':
        fail('preview-run', 'originating CI workflow/run was not an approved successful PR build')
    if str(run.get('repository', {}).get('id')) != repository['id'] or str(run.get('head_repository', {}).get('id')) != repository['id']:
        fail('preview-fork', 'fork or repository-mismatched preview is denied')
    prs = run.get('pull_requests', [])
    if len(prs) != 1:
        fail('preview-pr', 'originating run must identify exactly one PR')
    pr = github.repo('GET', '/pulls/' + str(prs[0]['number']))
    verify_pr(pr, repository, run['head_sha'])
    return run, pr


def verify_pr(pr, repository, head=None, closed=False):
    if not pr or pr.get('state') != ('closed' if closed else 'open') or str(pr.get('base', {}).get('repo', {}).get('id')) != repository['id'] or str(pr.get('head', {}).get('repo', {}).get('id')) != repository['id']:
        fail('preview-pr', 'PR state or repository trust changed')
    if head and pr['head']['sha'] != head:
        fail('preview-stale', 'CI run is stale for the current PR head')


def download_bundle(github, run, root, pr_number=None, *, sources=None,
                    expected_event="pull-request", plan_artifact_id=None, artifact_origins=None, expected_source_sha=None):
    """Download only exact run-bound artifacts into a fresh data-only directory."""
    artifacts = []
    for page in range(1, 101):
        data = github.repo('GET', f'/actions/runs/{run["id"]}/artifacts?per_page=100&page={page}')
        batch = data.get('artifacts', [])
        artifacts.extend(batch)
        if len(batch) < 100:
            break
    else:
        fail('artifact-count', 'CI artifact pagination exceeds bound')
    prefix = f'{run["id"]}-{run["run_attempt"]}'
    expected_plan = 'monorepo-plan-' + prefix
    selected = [a for a in artifacts if a['name'] == expected_plan or a['name'].startswith('components-' + prefix + '-')]
    if sum(a['name'] == expected_plan for a in selected) != 1 or len(selected) > 257:
        fail('artifact-run', 'CI plan artifact is missing or ambiguous')
    if plan_artifact_id is not None and str(next(a for a in selected if a['name']==expected_plan)['id'])!=str(plan_artifact_id):
        fail('artifact-plan-id','exact trusted plan job artifact was deleted or replaced')
    files, total, origins = set(), 0, {}
    for artifact in selected:
        provenance = artifact.get('workflow_run', {})
        if artifact.get('expired') or str(provenance.get('id')) != str(run['id']) or provenance.get('head_sha') != run['head_sha']:
            fail('artifact-run', 'CI artifact does not belong to exact verified run/head')
        data = github.repo('GET', f'/actions/artifacts/{artifact["id"]}/zip', raw=True, limit=1024*1024*1024)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for entry in archive.infolist():
                name = entry.filename.rstrip('/')
                safe_path(name, output=True)
                mode = entry.external_attr >> 16
                if (mode & 0o170000) not in (0, 0o100000, 0o040000) or name in files or len(files) > 10000:
                    fail('artifact-path', 'CI bundle contains links, duplicate or excessive files')
                if entry.is_dir():
                    continue
                if name != 'monorepo-plan.json' and not name.startswith(('results/', '.cloudopsworks/out/')):
                    fail('artifact-path', 'CI bundle contains an unexpected file')
                total += entry.file_size
                if total > 1024*1024*1024:
                    fail('artifact-size', 'CI bundle expansion exceeds bound')
                files.add(name)
                origins[name] = artifact
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(entry))
    plan = validate_record(load_record(root / 'monorepo-plan.json'))
    if plan['event'] != expected_event or plan['prNumber'] != pr_number or plan['headSha'] != (expected_source_sha or run['head_sha']) or plan['repository']['id'] != str(run['repository']['id']):
        fail('artifact-run', 'CI plan identity differs from verified run')
    results = [load_record(p) for p in sorted((root / 'results').glob('*.json'))]
    found = set()
    for result in results:
        validate_linked(result, {'plan': plan})
        if result['status'] != 'succeeded' or result['componentId'] in found:
            fail('artifact-result', 'failed or duplicate CI result')
        found.add(result['componentId'])
    if found != {s['componentId'] for s in plan['buildSelection']}:
        fail('artifact-result', 'selected CI result set is incomplete')
    expected_files = {'monorepo-plan.json'} | {'results/'+r['componentId']+'.json' for r in results}
    from contracts import rooted_path, validate_artifact
    for result in results:
        for key in ('mainArtifact','previewArtifact'):
            artifact = result[key]
            if artifact:
                if artifact['location']['kind'] != 'local':
                    fail('artifact-location','unprivileged CI artifact must use local transport')
                relative = artifact['location']['path']
                expected_files.add(relative)
                validate_artifact(rooted_path(root,relative,output=True),artifact)
    if sources is not None:
        for result in results:
            ident=result['componentId'];descriptor=result['mainArtifact']
            if descriptor['kind'] != 'openapi':continue
            source=origins[descriptor['location']['path']]
            expected_name='components-'+prefix+'-'+ident
            if source['name'] != expected_name:fail('artifact-run','spec bytes must belong to their component bundle')
            sources[ident]={'artifactId':str(source['id']),'runId':str(run['id']),'runAttempt':str(run['run_attempt']),
                'headSha':run['head_sha'],'componentId':ident,'path':descriptor['location']['path'],
                'name':expected_name,'url':'https://github.com/'+plan['repository']['fullName']+'/actions/runs/'+str(run['id'])+'/artifacts/'+str(source['id'])}
    if files != expected_files:
        fail('artifact-extra','CI run bundles contain missing or unreferenced files')
    if artifact_origins is not None:artifact_origins.update(origins)
    return plan, results


def validate_spec_source(source, repository, ident, artifact):
    keys={'artifactId','runId','runAttempt','headSha','componentId','path','name','url'}
    if not isinstance(source,dict) or set(source)!=keys or source['componentId']!=ident:
        fail('preview-spec-source','invalid durable spec source')
    if any(not isinstance(source[k],str) or not re.fullmatch(r'[1-9][0-9]{0,19}',source[k]) for k in ('artifactId','runId','runAttempt')):
        fail('preview-spec-source','invalid source API identity')
    if source['headSha'] != artifact['sourceSha'] or not re.fullmatch(r'[0-9a-f]{40}',source['headSha']) or source['path'] != artifact['location'].get('path'):
        fail('preview-spec-source','spec source provenance mismatch')
    safe_path(source['path'],output=True)
    expected='components-'+source['runId']+'-'+source['runAttempt']+'-'+ident
    url='https://github.com/'+repository['fullName']+'/actions/runs/'+source['runId']+'/artifacts/'+source['artifactId']
    if source['name'] != expected or source['url'] != url:
        fail('preview-spec-source','spec source link mismatch')


def verify_spec_source(github, repository, pr, ident, artifact, source):
    """Fetch immutable run-bound bytes on every carry; expiry/deletion fails closed."""
    from contracts import validate_artifact
    validate_spec_source(source,repository,ident,artifact)
    run=github.repo('GET','/actions/runs/'+source['runId'])
    if not run or run.get('event')!='pull_request' or run.get('status')!='completed' or run.get('conclusion')!='success' or str(run.get('repository',{}).get('id'))!=repository['id'] or str(run.get('head_repository',{}).get('id'))!=repository['id'] or run.get('head_sha')!=source['headSha'] or [p.get('number') for p in run.get('pull_requests',[])]!=[pr]:
        fail('preview-spec-source','source run is not verified same-repository PR CI')
    metadata=github.repo('GET','/actions/artifacts/'+source['artifactId'])
    if not metadata or metadata.get('expired') or metadata.get('name')!=source['name'] or str(metadata.get('workflow_run',{}).get('id'))!=source['runId'] or metadata.get('workflow_run',{}).get('head_sha')!=source['headSha']:
        fail('preview-spec-source','durable spec artifact missing, expired or mismatched')
    data=github.repo('GET','/actions/artifacts/'+source['artifactId']+'/zip',raw=True,limit=1024*1024*1024)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        matches=[entry for entry in archive.infolist() if entry.filename==source['path']]
        if len(matches)!=1 or matches[0].file_size>4*1024*1024 or (matches[0].external_attr>>16)&0o170000 not in (0,0o100000):
            fail('preview-spec-source','durable spec ZIP entry is unsafe or ambiguous')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'spec';path.write_bytes(archive.read(matches[0]));validate_artifact(path,artifact)
    return source['url']


def kubectl(executor, args, *, data=None, json_output=False):
    text = checked(executor, ['kubectl', *args], input=canonical_bytes(data).decode() if data is not None else None)
    return load_record(text) if json_output and text.strip() else (None if json_output else text)


def current_namespace(executor, name, labels):
    current = kubectl(executor, ['get', 'namespace', name, '--ignore-not-found', '-o', 'json'], json_output=True)
    if current and any(current['metadata'].get('labels', {}).get(k) != v for k, v in labels.items()):
        fail('namespace-owner', 'existing namespace belongs to another repository/PR/target')
    return current


def ensure_namespace(executor, name, labels):
    """Legacy helper is read-only; namespace creation belongs to native IaC."""
    current = current_namespace(executor, name, labels)
    if not current:
        fail('preview-iac-required', 'namespace must be created by the authorized environment root')
    return current

def network_policy(namespace, isolation):
    return {'apiVersion': 'networking.k8s.io/v1', 'kind': 'NetworkPolicy',
        'metadata': {'name': 'cloudopsworks-sandbox', 'namespace': namespace},
        'spec': {'podSelector': {}, 'policyTypes': ['Ingress', 'Egress'],
            'ingress': [{'from': [{'podSelector': {}}]}, {'from': [{'namespaceSelector': {'matchLabels': isolation['ingressNamespaceSelector']}, 'podSelector': {'matchLabels': isolation['ingressPodSelector']}}]}],
            'egress': [{'to': [{'podSelector': {}}]}, {'to': [{'namespaceSelector': {'matchLabels': isolation['dnsNamespaceSelector']}, 'podSelector': {'matchLabels': isolation['dnsPodSelector']}}], 'ports': [{'protocol': 'UDP', 'port': 53}, {'protocol': 'TCP', 'port': 53}]}]}}


def _pod(name, namespace, image, code, args=(), labels=None, server=False):
    container = {'name': 'probe', 'image': image, 'command': ['python3', '-c', code, *args],
        'securityContext': {'allowPrivilegeEscalation': False, 'readOnlyRootFilesystem': True, 'capabilities': {'drop': ['ALL']}},
        'resources': {'requests': {'cpu': '10m', 'memory': '32Mi'}, 'limits': {'cpu': '100m', 'memory': '64Mi'}}}
    if server:
        container['readinessProbe'] = {'tcpSocket': {'port': 8000}}
    return {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': namespace, 'labels': labels or {}},
            'spec': {'restartPolicy': 'Never', 'automountServiceAccountToken': False,
                'securityContext': {'runAsNonRoot': True, 'runAsUser': 65532, 'seccompProfile': {'type': 'RuntimeDefault'}},
                'containers': [container]}}


CONNECT = "import socket,sys; s=socket.create_connection((sys.argv[1],int(sys.argv[2])),timeout=3); s.close(); print('reachable')"
SERVER = "import http.server; http.server.HTTPServer(('0.0.0.0',8000),http.server.BaseHTTPRequestHandler).serve_forever()"
NETWORK = """import json,socket,sys
p=json.loads(sys.argv[1])
def reachable(e):
 try:
  s=socket.create_connection((e['host'],e['port']),timeout=2);s.close();return True
 except OSError:return False
print(json.dumps({'dns':bool(socket.getaddrinfo('kubernetes.default.svc.cluster.local',443)), 'controlDenied':not reachable(p['controlEndpoint']), 'metadataDenied':all(not reachable(e) for e in p['metadataEndpoints'])}))
"""


def _completed_probe(executor, pod):
    fail('preview-iac-required', 'probe creation and cleanup belong to the native environment root')

def isolation_preflight(executor, name, policy, provider, *, resolution=None):
    """Actual admission + paired control/denial/DNS/ingress tests, before PR pods."""
    isolation = policy['isolation']
    required = {('169.254.169.254', 80)}
    if provider == 'aws':
        required.add(('fd00:ec2::254', 80))
    if provider == 'gcp':
        required.add(('metadata.google.internal', 80))
    supplied = {(e['host'], e['port']) for e in isolation['metadataEndpoints']}
    if not required <= supplied:
        fail('isolation-metadata', 'trusted policy omits a mandatory provider metadata endpoint')
    control = isolation['controlEndpoint']
    if not control['host'].endswith('.' + isolation['controlNamespace'] + '.svc.cluster.local'):
        fail('isolation-control', 'control endpoint must be an operator-owned service in control namespace')
    for key in ('ingressNamespaceSelector','ingressPodSelector','dnsNamespaceSelector','dnsPodSelector'):
        if not isolation[key] or any(not k or not v for k, v in isolation[key].items()):
            fail('isolation-selector', 'isolation selectors cannot match all namespaces/pods')
    # A ready enforcement agent is a prerequisite; the actual paired canary
    # below is still required (agent/policy presence alone is never proof).
    daemon = {'cilium':'cilium','calico':'calico-node','gke-dataplane-v2':'anetd',
              'aws-vpc-network-policy':'aws-node','azure-network-policy':'azure-npm'}[isolation['mode']]
    agent = kubectl(executor, ['get', 'daemonset', daemon, '--namespace', 'kube-system', '-o', 'json'], json_output=True)
    if not agent or agent['status'].get('numberReady', 0) < 1 or agent['status'].get('numberReady') != agent['status'].get('desiredNumberScheduled'):
        fail('isolation-enforcement', 'network-policy enforcement agent is unavailable')
    bad = _pod('cloudopsworks-admission-test', name, isolation['probeImage'], CONNECT)
    bad['spec']['hostNetwork'] = True
    bad['spec']['containers'][0]['securityContext']['privileged'] = True
    rejection = executor.run(['kubectl', 'create', '--dry-run=server', '-f', '-'], input=canonical_bytes(bad).decode())
    if rejection.returncode == 0 or not re.search(r'PodSecurity|restricted|hostNetwork', rejection.stderr):
        fail('isolation-admission', 'restricted Pod Security rejection was not established')
    # Probes and policies were created by the saved environment-root apply.
    # This phase only reads/executes bounded connectivity tests in owned pods.
    if not isinstance(resolution,dict) or resolution.get('namespace') != name:
        fail('isolation-native-state', 'verified environment native outputs are required')
    policy_ids=resolution.get('ownedIds',{}).get('policies',[])
    expected={name+'/'+p for p in ('cloudopsworks-default-deny','cloudopsworks-same-namespace','cloudopsworks-dns','cloudopsworks-ingress')}
    if not isinstance(policy_ids,list) or set(policy_ids)!=expected:
        fail('isolation-native-state','complete fixed native policy identities are required')
    for ident in policy_ids:
        document=kubectl(executor,['get','networkpolicy',ident.split('/')[1],'--namespace',name,'-o','json'],json_output=True)
        if (not document or document.get('metadata',{}).get('namespace') != name
                or document['metadata'].get('annotations',{}).get('cloudopsworks.io/owner-digest') != resolution['owner_digest']):
            fail('isolation-native-state','native policy ownership differs from API')
    probes=resolution.get('ownedIds',{}).get('probes',{})
    if set(probes) != {'canary','control','ingress'}:
        fail('isolation-native-state', 'all native probe identities are required')
    for probe in probes.values():
        if not isinstance(probe,dict) or set(probe)!={'id','name','namespace','uid'} or not all(probe.values()):
            fail('isolation-native-state','probe identity is incomplete')
        pod=kubectl(executor,['get','pod',probe['name'],'--namespace',probe['namespace'],'-o','json'],json_output=True)
        if (not pod or pod['metadata'].get('uid') != probe['uid']
                or pod['metadata'].get('annotations',{}).get('cloudopsworks.io/owner-digest') != resolution['owner_digest']
                or pod['metadata'].get('annotations',{}).get('cloudopsworks.io/environment-uid') != resolution['uid']):
            fail('isolation-native-state','native probe generation differs from API')
        kubectl(executor,['wait','--for=condition=Ready','pod/'+probe['name'],'--namespace',probe['namespace'],'--timeout=60s'])
    def execute(probe,code,args):
        return kubectl(executor,['exec',probe['name'],'--namespace',probe['namespace'],'--','python3','-c',code,*args])
    if 'reachable' not in execute(probes['control'],CONNECT,[control['host'],str(control['port'])]):
        fail('isolation-control','operator control endpoint is unavailable')
    evidence=load_record(execute(probes['canary'],NETWORK,[json.dumps(isolation)]))
    if evidence != {'dns':True,'controlDenied':True,'metadataDenied':True}:
        fail('isolation-network','sandbox connectivity checks failed or were inconclusive')
    pod=kubectl(executor,['get','pod',probes['canary']['name'],'--namespace',name,'-o','json'],json_output=True)
    if 'reachable' not in execute(probes['ingress'],CONNECT,[pod['status']['podIP'],'8000']):
        fail('isolation-ingress','intended ingress traffic is not allowed')
    return {'policyDigest':digest({'isolation':isolation,'ownerDigest':resolution['owner_digest'],'policies':sorted(policy_ids)}), 'probeImageDigest':isolation['probeImage'].rsplit('@',1)[1],
        'verifiedAt':dt.datetime.now(dt.timezone.utc).isoformat().replace('+00:00','Z'),
        'admissionRestricted':True,'ingressDnsAllowed':True,'unintendedEgressDenied':True,'metadataDenied':True}


def cleanup(executor, github, repository, pr, target, save_state, *, provider=None, context=None):
    controller=(context or {}).get('controller')
    if not isinstance(controller,IaCPreview):
        fail('preview-iac-required','standing closure requires the protected IaC controller')
    changed=controller.close()
    name=namespace(repository['id'],pr,target)
    save_state({'phase':'closed','namespace':name})
    event('preview-cleanup','deleted' if changed else 'noop',namespace=name,provider=provider,target=target,
        reason='native-state-closure-verified' if changed else 'namespace-already-absent')
    return name

def validate_metadata(payload):
    """Actor protection is supplied by PreviewStore, never by this data envelope."""
    from contracts import _check, _artifact
    required = {'apiVersion','kind','state','artifacts'}
    if not isinstance(payload,dict) or not required <= payload.keys() or payload.keys() - required - {'componentConfigs','artifactSources'}:
        fail('preview-state','invalid preview metadata envelope')
    if payload['apiVersion'] != API_VERSION or payload['kind'] != 'PreviewMetadata':
        fail('preview-state','invalid preview metadata version')
    state = validate_record(payload['state'])
    components = {c['componentId']:c for c in state['components'] if c['status'] != 'removed'}
    artifacts, configs = payload['artifacts'], payload.get('componentConfigs',{})
    if not isinstance(artifacts,dict) or not isinstance(configs,dict) or (set(artifacts) != set(components) and not (state['phase']=='failed' and not components)) or not set(configs) <= set(components):
        fail('preview-state','metadata component identity mismatch')
    for ident, artifact in artifacts.items():
        if not isinstance(ident,str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}',ident):
            fail('preview-state','invalid metadata component identifier')
        _check(artifact,{'$ref':'#/$defs/Artifact'},'$.artifacts.'+ident,0)
        _artifact(artifact,repository=state['repository'])
        if ident in components and artifact['digest'] != components[ident]['desiredDigest']:
            fail('preview-state','metadata artifact differs from desired component')
    if any(not isinstance(value,str) or not re.fullmatch(r'sha256:[0-9a-f]{64}',value) for value in configs.values()):
        fail('preview-state','invalid effective preview configuration digest')
    sources=payload.get('artifactSources',{})
    if not isinstance(sources,dict) or not set(sources)<=set(artifacts):fail('preview-state','invalid artifact source identities')
    for ident,source in sources.items():
        if artifacts[ident]['kind']!='openapi':fail('preview-state','durable spec source belongs to non-spec component')
        validate_spec_source(source,state['repository'],ident,artifacts[ident])
    return payload


class PreviewStore:
    def __init__(self, github, repository, pr, target, automation_id):
        if not str(automation_id).isdigit():
            fail('preview-automation', 'protected automation identity is required')
        self.github, self.repository, self.pr, self.target = github, repository, pr, target
        self.automation_id = str(automation_id)
        self.environment = f'cloudopsworks/preview/{target}/pr-{pr}'

    def load(self):
        deployments = self.github.pages('/deployments?environment=' + self.environment)
        for deployment in sorted(deployments, key=lambda d:int(d['id']), reverse=True):
            if str(deployment.get('creator', {}).get('id')) != self.automation_id:
                continue
            payload = deployment.get('payload')
            if not isinstance(payload, dict) or payload.get('kind') != 'PreviewMetadata':
                continue
            validate_metadata(payload)
            state = payload['state']
            if state['repository'] != self.repository or state['prNumber'] != self.pr or state['targetId'] != self.target or state['namespace'] != namespace(self.repository['id'], self.pr, self.target):
                fail('preview-state', 'durable preview identity does not match target group')
            statuses = self.github.pages(f'/deployments/{deployment["id"]}/statuses')
            trusted = sorted((s for s in statuses if str(s.get('creator',{}).get('id')) == self.automation_id),key=lambda s:int(s['id']),reverse=True)
            expected = 'success' if state['phase']=='ready' else 'inactive' if state['phase']=='closed' else 'failure' if state['phase']=='failed' else 'in_progress'
            if not trusted or trusted[0]['state'] != expected:
                fail('preview-state', 'durable preview state lacks trusted API status')
            return payload
        return None

    def save(self, state, artifacts, component_configs=None, artifact_sources=None):
        payload = validate_metadata({'apiVersion':API_VERSION,'kind':'PreviewMetadata','state':state,
            'artifacts':artifacts,'componentConfigs':component_configs or {},'artifactSources':artifact_sources or {}})
        deployment = self.github.repo('POST', '/deployments', {'ref': state['headSha'], 'auto_merge': False,
            'required_contexts': [], 'environment': self.environment, 'transient_environment': True,
            'production_environment': False, 'payload': payload})
        status = 'success' if state['phase'] == 'ready' else 'inactive' if state['phase'] == 'closed' else 'failure' if state['phase'] == 'failed' else 'in_progress'
        result = self.github.repo('POST', f'/deployments/{deployment["id"]}/statuses', {'state':status, 'auto_inactive':False})
        if not result or not result.get('id') or result.get('state') != status or str(result.get('creator',{}).get('id')) != self.automation_id:
            fail('preview-state', 'durable preview state status write failed')
        stored = self.load()
        if stored != payload:
            fail('preview-state','durable preview metadata readback mismatch')


def cluster_credentials(executor, target, kubeconfig):
    import os
    os.environ['KUBECONFIG'] = str(kubeconfig)
    kind = target['kind']
    if kind == 'aws.eks':
        argv = ['aws','eks','update-kubeconfig','--name',target['cluster'],'--region',target['region'],'--kubeconfig',str(kubeconfig)]
    elif kind == 'gcp.gke':
        argv = ['gcloud','container','clusters','get-credentials',target['cluster'],'--location',target['location'],'--project',target['project']]
    elif kind == 'azure.aks':
        argv = ['az','aks','get-credentials','--name',target['cluster'],'--resource-group',target['resourceGroup'],'--subscription',target['subscriptionId'],'--file',str(kubeconfig)]
    else:
        fail('preview-target', 'previews are Kubernetes-only')
    checked(executor, argv)
    if kind == 'azure.aks':
        checked(executor, ['kubelogin','convert-kubeconfig','-l','azurecli'])
    versions = kubectl(executor, ['version','--output=json'], json_output=True)
    client, server = versions['clientVersion'], versions['serverVersion']
    if client['major'] != server['major'] or abs(int(client['minor'].rstrip('+')) - int(server['minor'].rstrip('+'))) > 1:
        fail('client-skew', 'kubectl minor is outside supported server skew')


def _deploy_component(executor, namespace_name, component, artifact, policy, workdir, *, context=None):
    controller=(context or {}).get('controller')
    if not isinstance(controller,IaCPreview):
        fail('preview-iac-required','component deployment requires the protected IaC controller')
    return controller.component(component,artifact,policy,workdir)

def _verify_component(executor, namespace_name, component, artifact, policy, workdir, *, context=None):
    from providers.kubernetes import forward
    from providers.common import http_request
    context = context or {}
    projection = component['preview']
    deployment = kubectl(executor, ['get','deployment',component['id'],'--namespace',namespace_name,'-o','json'], json_output=True)
    annotations = deployment['metadata'].get('annotations',{})
    if annotations.get('meta.helm.sh/release-name') != component['id'] or annotations.get('meta.helm.sh/release-namespace') != namespace_name:
        fail('preview-workload','live deployment is not owned by the expected Helm release')
    spec = deployment['spec']['template']['spec']
    if len(spec['containers']) != 1 or spec['containers'][0]['image'] != artifact['location']['reference'] or spec['containers'][0]['ports'][0]['containerPort'] != projection['port'] or spec.get('automountServiceAccountToken') is not False:
        fail('preview-workload', 'live workload does not match immutable image/port/token contract')
    revision = deployment['metadata']['annotations']['deployment.kubernetes.io/revision']
    kubectl(executor, ['rollout','status','deployment/'+component['id'],'--namespace',namespace_name,'--timeout=600s','--revision='+revision])
    factory = context.get('forward', forward)
    request_http = context.get('http', http_request)
    with factory(executor, namespace_name, component['id'], projection['port'], {}) as base:
        response = request_http(base + projection['healthPath'], timeout=10)
        status, body = response if isinstance(response, tuple) else (response.status, response.read().decode())
        if status != 200:
            fail('preview-health', 'preview health endpoint did not become ready')
        if projection['source'] == 'function':
            test = projection['invokeTest']
            response = request_http(base + projection['invokePath'], method='POST', body=test['requestBody'], headers={'Content-Type':'application/json'}, timeout=10)
            status, body = response if isinstance(response, tuple) else (response.status, response.read().decode())
            if isinstance(body, bytes):
                body = body.decode('utf-8', errors='replace')
            if status != test['expectedStatus'] or test['responseContains'] not in body:
                fail('preview-handler', 'preview handler invocation failed')


@observed('preview')
def reconcile_preview(executor, github, repository, pr, run, trusted_plan, plan, results,
                      target_id, publisher, root, store, *, context=None):
    validate_record(trusted_plan)
    validate_record(plan)
    trusted_targets = {t['id']:t for t in trusted_plan['targets']}
    policy = next((p for p in trusted_plan['previewPolicy']['targets'] if p['targetId'] == target_id), None)
    if not trusted_plan['previewPolicy']['enabled'] or policy is None or target_id not in trusted_targets:
        fail('preview-policy', 'target is not enabled in trusted default-branch policy')
    target = trusted_targets[target_id]
    if target['kind'] not in ('aws.eks','gcp.gke','azure.aks'):
        fail('preview-target', 'previews are Kubernetes-only')
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', policy['baseDomain']) or not re.fullmatch(r'[a-z0-9][a-z0-9-]*', policy['ingressClass']):
        fail('preview-policy', 'trusted ingress domain/class is invalid')
    # Never consume PR target auth/cluster/policy overrides, even if well-shaped.
    offered = next((t for t in plan['targets'] if t['id'] == target_id), None)
    if offered != target:
        fail('preview-target-override', 'PR plan attempted to override the trusted deployment target')
    verify_pr(github.repo('GET','/pulls/'+str(pr)), repository, run['head_sha'])
    if plan['repository'] != repository or plan['headSha'] != run['head_sha'] or plan['prNumber'] != pr:
        fail('preview-identity', 'PR build plan is not bound to verified run')
    previous = store.load()
    previous_state = previous['state'] if previous else None
    previous_artifacts = previous.get('artifacts', {}) if previous else {}
    previous_components = {c['componentId']:c for c in previous_state['components']} if previous_state else {}
    result_map = {}
    for result in results:
        validate_linked(result, {'plan':plan})
        if result['componentId'] in result_map or result['status'] != 'succeeded':
            fail('preview-result', 'duplicate or failed build result')
        result_map[result['componentId']] = result
    if set(result_map) != {s['componentId'] for s in plan['buildSelection']}:
        fail('preview-result', 'selected result set is incomplete')
    # Enabled trusted preview groups account for every active component, independently
    # of its normal provider/package bindings. Normal target validation is unchanged.
    active = plan['components']
    name = namespace(repository['id'],pr,target_id)
    state = {'apiVersion':API_VERSION,'kind':'PreviewState','repository':repository,'prNumber':pr,
        'targetId':target_id,'namespace':name,'headSha':plan['headSha'],'runId':str(run['id']),
        'phase':'preparing','isolation':None,'components':[]}
    artifacts = {}
    component_configs = {}
    artifact_sources = {}
    counts = {'updated':0,'verified':0,'failed':0,'artifactOnly':0,'removed':0}
    # Publish/verify every image as data before namespace/PR workload mutation.
    for component in active:
        ident = component['id']
        if component['preview']['mode'] == 'artifact-only':
            if ident not in result_map and (not previous_state or previous_state['headSha'] not in (plan['baseSha'], plan['headSha'])):
                fail('preview-artifact', 'artifact-only carry requires continuous verified source history')
            source = result_map.get(ident, {}).get('mainArtifact') or previous_artifacts.get(ident)
            if not source:
                fail('preview-artifact', 'artifact-only component has no verified current spec')
            if ident in result_map:
                from contracts import rooted_path, validate_artifact
                validate_artifact(rooted_path(root,source['location']['path'],output=True),source)
            provenance = (context or {}).get('artifact_sources',{}).get(ident) if ident in result_map else (previous or {}).get('artifactSources',{}).get(ident)
            verified_link=verify_spec_source(github,repository,pr,ident,source,provenance)
            artifact_sources[ident]=provenance
            event('preview-spec','reused' if ident not in result_map else 'published',component=ident,target=target_id,namespace=name,provider=target['provider'],source=source['sourceSha'],version=source['builtVersion'],digest=source['digest'],artifactLink={'repository':repository['fullName'],'runId':provenance['runId'],'artifactId':provenance['artifactId'],'url':verified_link})
            artifacts[ident] = source
            continue
        if ident in result_map:
            artifact = result_map[ident]['previewArtifact']
            if artifact is None:
                fail('preview-artifact', 'container preview image is missing')
            artifacts[ident] = publisher.publish(artifact,ident,'preview',root,None,None,repository)
        else:
            if not previous_state or previous_state['phase'] == 'closed' or previous_state['headSha'] not in (plan['baseSha'],plan['headSha']) or ident not in previous_artifacts:
                fail('preview-artifact', 'initial/missing-state preview requires an unprivileged all-components build')
            artifact = previous_artifacts[ident]
            if artifact['kind'] != 'container':
                fail('preview-artifact', 'carried preview is not an immutable container')
            publisher.verify(artifact)
            artifacts[ident] = artifact
    labels = owner(repository,pr,target_id)
    controller=(context or {}).get('controller')
    if not isinstance(controller,IaCPreview):
        fail('preview-iac-required','protected IaC preview controller is required')
    verify_pr(github.repo('GET','/pulls/'+str(pr)),repository,plan['headSha'])
    # Environment resources consume no application payload/image. An authentic
    # existing descriptor suffices for the generic renderer, including OpenAPI.
    if not artifacts:
        fail('preview-empty','preview has no component descriptors')
    owned=controller.environment(next(iter(artifacts.values())),policy,root)
    if owned['namespace']!=name:
        fail('preview-namespace','canonical namespace differs from durable group')
    event('preview-namespace','owned',namespace=name,provider=target['provider'],target=target_id)
    readiness_actions={}
    try:
        controller._guard()
        state['isolation'] = isolation_preflight(executor,name,policy,target['provider'],resolution=owned)
        # Admission and actual network evidence is fresh on every apply.
        validate_record({**state,'components':[]})
        for old_id, old in previous_components.items():
            if old_id not in {c['id'] for c in active} and old['releaseName']:
                if old['releaseName'] != old_id:
                    fail('preview-state', 'durable release identity is not canonical component ID')
                verify_pr(github.repo('GET','/pulls/'+str(pr)),repository,plan['headSha'])
                controller.remove(old_id)
                counts['removed'] += 1
                event('preview-component','removed',component=old_id,target=target_id,reason='component-removed')
        for component in active:
            ident, artifact = component['id'], artifacts[component['id']]
            config_digest = digest({'domain':'effective-preview/v1','projection':component['preview'],
                'policy':policy,'target':target,'chart':'blueprints@v5.11.0/kubernetes/helm/charts','runtime':(context or {}).get('preview_config',{})})
            if component['preview']['mode'] == 'artifact-only':
                component_configs[ident] = config_digest
                counts['artifactOnly'] += 1
                state['components'].append({'componentId':ident,'status':'artifact-only','releaseName':None,
                    'desiredDigest':artifact['digest'],'successfulDigest':artifact['digest'],'error':None})
                continue
            entry = {'componentId':ident,'status':'failed','releaseName':ident,'desiredDigest':artifact['digest'],
                'successfulDigest':previous_components.get(ident,{}).get('successfulDigest'),'error':None}
            try:
                verify_pr(github.repo('GET','/pulls/'+str(pr)),repository,plan['headSha'])
                old = previous_components.get(ident,{})
                unchanged = old.get('status') == 'ready' and old.get('successfulDigest') == artifact['digest'] and previous.get('componentConfigs',{}).get(ident) == config_digest
                if unchanged:
                    effective = (context or {}).get('materialize_artifact',lambda artifact,component:artifact)(artifact,component)
                    (context or {}).get('verify_component',_verify_component)(executor,name,component,effective,policy,root,context=context)
                    counts['verified'] += 1
                else:
                    (context or {}).get('deploy_component',_deploy_component)(executor,name,component,artifact,policy,root,context=context)
                    counts['updated'] += 1
                controller._guard()
                component_configs[ident] = config_digest
                readiness_actions[ident]='unchanged-verified' if unchanged else 'deployed-verified'
                entry.update(status='ready',successfulDigest=artifact['digest'])
            except Exception:
                counts['failed'] += 1
                entry['error'] = {'code':'preview-workload','message':'Preview deployment or serving verification failed','retryable':True}
                state['components'].append(entry)
                state['phase']='failed'
                known={c['componentId'] for c in state['components']}
                for remaining in active:
                    rid=remaining['id']
                    if rid in known:continue
                    old=copy.deepcopy(previous_components.get(rid))
                    if old and old['desiredDigest']==artifacts[rid]['digest']:
                        state['components'].append(old)
                        if rid in previous.get('componentConfigs',{}):component_configs[rid]=previous['componentConfigs'][rid]
                    else:
                        state['components'].append({'componentId':rid,'status':'failed','releaseName':rid,
                            'desiredDigest':artifacts[rid]['digest'],'successfulDigest':(old or {}).get('successfulDigest'),
                            'error':{'code':'preview-not-attempted','message':'Earlier operation uncertain; not attempted','retryable':True}})
                store.save(validate_record(state),artifacts,component_configs,artifact_sources)
                # Uncertain provider/readiness outcomes stop every later write.
                raise
            state['components'].append(entry)
        state['phase'] = 'failed' if any(c['status']=='failed' for c in state['components']) else 'ready'
        controller._guard()
        validate_record(state)
        store.save(state,artifacts,component_configs,artifact_sources)
        for entry in state['components']:
            event('preview-readiness',entry['status'],component=entry['componentId'],target=target_id,namespace=name,provider=target['provider'],digest=entry['desiredDigest'],reason=readiness_actions.get(entry['componentId'],'artifact-only' if entry['status']=='artifact-only' else 'readiness-failed'),errorCategory=(entry.get('error') or {}).get('code','none'))
        event('preview-components',state['phase'],namespace=name,provider=target['provider'],target=target_id,source=plan['headSha'],version=plan['version'],selected=counts['updated'],reused=counts['verified'],failed=counts['failed'],skipped=counts['artifactOnly'])
        if state['phase'] != 'ready':
            fail('preview-failed','one or more preview components failed; namespace retained for retry')
        return state
    except Exception:
        if state['phase']!='failed':
            state['phase']='failed'
            store.save(validate_record(state),artifacts,{},artifact_sources)
            print('preview target='+target_id+' phase=failed isolation=failed updated=0 verified=0')
        raise

class IaCPreview:
    """Trusted, process-local preview controller; no callback comes from a bundle.

    The fixed host supplies independently verified historical handles and private
    native-state outputs. API labels alone are never adoption evidence. Terraform
    locks supplement, rather than replace, the common GitHub concurrency group.
    The provider cannot make namespace deletion UID-conditional: a privileged OOB
    replacement or PR reopen after submission remains an explicit boundary.
    """
    def __init__(self, github, repository, pr, target, head, context):
        from authorization import PreparedAuthorization
        if not isinstance(context.get('prepared'), PreparedAuthorization):
            fail('preview-authority', 'fixed protected authorization context is required')
        for key in ('resolve_preview', 'preview_handles', 'recover_preview', 'native_owned'):
            if not callable(context.get(key)):
                fail('preview-authority', 'verified preview runtime is incomplete')
        self.github, self.repository, self.pr, self.target, self.head = github, repository, pr, target, head
        self.context = context
        self.prepared = context['prepared']
        self.executor = context['cloud']
        self.root_handle = None
        self.owned = None

    def _pr(self, closed=False):
        verify_pr(self.github.repo('GET', '/pulls/'+str(self.pr)), self.repository,
                  None if closed else self.head, closed=closed)

    def _handles(self):
        handles = self.context['preview_handles'](self.target)
        if not isinstance(handles, list):
            fail('preview-history', 'complete verified native history is required')
        found = set()
        for handle in handles:
            if (handle['origin']['repository'] != self.repository or handle['prNumber'] != self.pr
                    or handle['targetId'] != self.target or handle['scope'] not in ('preview-environment','preview-component')
                    or digest(handle) in found):
                fail('preview-history', 'historical handle differs from admitted preview group')
            found.add(digest(handle))
        return handles

    def _generation(self, handle, *, absent=False):
        owned = self.context['native_owned'](handle)
        name = handle['resourceIdentity']['namespace']
        current = current_namespace(self.executor, name, owner(self.repository,self.pr,self.target))
        # External control/ingress namespaces are not ours; only exact native
        # probe generations may be destroyed there by the environment root.
        for probe in (owned or {}).get('ownedIds',{}).get('probes',{}).values():
            pod=kubectl(self.executor,['get','pod',probe['name'],'--namespace',probe['namespace'],
                '--ignore-not-found','-o','json'],json_output=True)
            if pod is None:
                if absent:continue
                fail('preview-generation','owned probe unexpectedly absent')
            if (pod.get('metadata',{}).get('uid') != probe['uid']
                    or pod['metadata'].get('annotations',{}).get('cloudopsworks.io/owner-digest') != digest(handle)
                    or pod['metadata'].get('annotations',{}).get('cloudopsworks.io/environment-uid') != owned['uid']):
                fail('preview-generation','external probe UID or owner changed')
        if current is None:
            if absent:
                return owned
            fail('preview-generation', 'owned namespace unexpectedly absent')
        if (not isinstance(owned,dict) or owned.get('namespace') != name or not owned.get('uid')
                or owned.get('owner_digest') != digest(handle)
                or current['metadata'].get('uid') != owned['uid']
                or current['metadata'].get('annotations',{}).get('cloudopsworks.io/owner-digest') != digest(handle)):
            fail('preview-generation', 'native state and API namespace generation differ')
        return owned

    def _guard(self, *, closed=False, creating=False):
        self._pr(closed)
        if self.root_handle:
            if creating and self.owned is None:
                # Creation may proceed only when BOTH native state and API deny
                # an existing namespace, never by adopting matching labels.
                old = self.context['native_owned'](self.root_handle)
                current = current_namespace(self.executor,self.root_handle['resourceIdentity']['namespace'],
                                            owner(self.repository,self.pr,self.target))
                if old is not None or current is not None:
                    fail('preview-adoption','namespace appeared before create submission')
            else:
                actual = self._generation(self.root_handle,absent=closed)
                if self.owned is not None and actual != self.owned:
                    fail('preview-generation','historical namespace generation changed')

    def _execute(self, bound, values, *, closed=False, ready=None, creating=False):
        plan=bound['plan']
        if (plan['stateHandle']['origin']['repository'] != self.repository
                or plan['stateHandle']['targetId'] != self.target or plan['stateHandle']['prNumber'] != self.pr):
            fail('preview-operation','canonical operation differs from admitted group')
        def guard():
            predecessor=self.context.get('before_apply')
            if predecessor is not None:
                predecessor(plan)
            self._guard(closed=closed,creating=creating)
        guard()
        completed=bound['engine'].execute(plan,canonical=bound['canonical'],store=bound['store'],
            resource_claims=bound['resourceClaims'],existing=bound['existing'],values=values,
            credentials=bound['credentials'],verify_ready=ready,before_apply=guard)
        # A successful provider exit is not proof the PR stayed open/closed or
        # the namespace stayed unchanged during submission. Stop later writes.
        if creating or (plan['operation']=='destroy' and plan['stateHandle']['scope']=='preview-environment'):
            self._pr(closed)
        else:
            self._guard(closed=closed)
        return completed

    def environment(self, artifact, policy, workdir):
        resolved=self.context['resolve_preview'](self.target,'')
        bound=self.prepared.authorize_preview(self.target,'',resolved)
        self.root_handle=bound['plan']['stateHandle']
        if self.root_handle['scope'] != 'preview-environment':
            fail('preview-operation','environment requires canonical root handle')
        self.owned=self.context['native_owned'](self.root_handle)
        creating=self.owned is None
        values=self._values(bound,artifact,policy,workdir)
        def ready(outputs):
            owned=outputs.get('owned')
            if not isinstance(owned,dict) or owned.get('owner_digest') != digest(self.root_handle):
                fail('preview-generation','environment native output is incomplete')
            self.owned=copy.deepcopy(owned)
            self.owned['ownedIds']['policies'].sort()
            if self._generation(self.root_handle) != self.owned:
                fail('preview-generation','native output and independently read state differ')
            return owned['namespace']
        self._execute(bound,values,ready=ready,creating=creating)
        self.owned=self._generation(self.root_handle)
        return self.owned

    def _values(self,bound,artifact,policy,workdir):
        from iac_values import render_values
        engine=bound['engine'];handle=bound['plan']['stateHandle']
        row=engine.catalog['modules'][handle['moduleId']]
        metadata=load_record(engine.root/row['path']/'inputs.json')
        with tempfile.TemporaryDirectory(prefix='preview-values-',dir=workdir) as directory:
            Path(directory).chmod(0o700)
            isolation=copy.deepcopy(policy['isolation'])
            selector=','.join(k+'='+v for k,v in sorted(isolation['ingressNamespaceSelector'].items()))
            namespaces=kubectl(self.executor,['get','namespaces','--selector',selector,'-o','json'],json_output=True)
            if not namespaces or len(namespaces.get('items',[])) != 1:
                fail('isolation-ingress','protected ingress namespace is ambiguous')
            isolation['ingressNamespace']=namespaces['items'][0]['metadata']['name']
            if handle['scope']=='preview-environment' and self.owned:
                probes=self.owned['ownedIds']['probes']
                if (('control' in probes and isolation['controlNamespace']!=probes['control']['namespace'])
                        or ('ingress' in probes and isolation['ingressNamespace']!=probes['ingress']['namespace'])):
                    fail('preview-claim-drift','external probe parents changed; historical cleanup is required')
            isolation={k:isolation[k] for k in ('probeImage','controlNamespace','ingressNamespace','ingressNamespaceSelector','ingressPodSelector','dnsNamespaceSelector','dnsPodSelector')}
            return render_values(bound['plan'],metadata,artifact,work=Path(directory),
                chart_path=engine.root/row['chartPath'] if row.get('chartPath') else None,
                kubeconfig_path=self.context['kubeconfigPath'],
                readiness_seconds=next(t for t in self.prepared.plan['targets'] if t['id']==self.target)['readiness']['deadlineSeconds'],
                preview_isolation=isolation if handle['scope']=='preview-environment' else None,
                preview_options={'host':handle['componentId']+'.'+handle['resourceIdentity']['namespace']+'.'+policy['baseDomain'],
                    'ingressClass':policy['ingressClass']} if handle['scope']=='preview-component' else None)

    def component(self, component, artifact, policy, workdir):
        resolved=self.context['resolve_preview'](self.target,component['id'])
        bound=self.prepared.authorize_preview(self.target,component['id'],resolved)
        values=self._values(bound,artifact,policy,workdir)
        def ready(outputs):
            _verify_component(self.executor,self.owned['namespace'],component,artifact,policy,workdir,
                              context=self.context)
            return self.owned['namespace']
        self._execute(bound,values,ready=ready)

    def remove(self, component_id):
        handles=[h for h in self._handles() if h['componentId']==component_id]
        for handle in handles:
            bound=self.context['recover_preview'](handle)
            if bound['plan']['operation'] != 'destroy' or bound['plan']['stateHandle'] != handle:
                fail('preview-operation','cleanup must preserve exact historical handle')
            self._execute(bound,{},closed=False)

    def close(self):
        self._pr(True)
        handles=self._handles()
        roots=[h for h in handles if h['scope']=='preview-environment']
        if handles and len(roots)!=1:
            fail('preview-history','exact namespace-generation root is required')
        if not roots:
            current=current_namespace(self.executor,namespace(self.repository['id'],self.pr,self.target),owner(self.repository,self.pr,self.target))
            if current:fail('preview-history','namespace exists without verified generation history')
            return False
        self.root_handle=roots[0]
        self.owned=self._generation(self.root_handle,absent=True)
        # All workload releases first. Probe resources are root dependencies;
        # the saved native destroy plan destroys them before their namespace.
        for handle in [h for h in handles if h['scope']=='preview-component']+roots:
            bound=self.context['recover_preview'](handle)
            if bound['plan']['operation']!='destroy' or bound['plan']['stateHandle']!=handle:
                fail('preview-operation','standing closure cannot widen a historical operation')
            self._execute(bound,{},closed=True)
        if current_namespace(self.executor,self.root_handle['resourceIdentity']['namespace'],owner(self.repository,self.pr,self.target)):
            fail('preview-cleanup','namespace deletion remains uncertain; recovery handles retained')
        return True
