"""GCP typed native deployments into preconfigured projects and resources."""
import json
import uuid

import contracts
from . import common as c


def cli(ex, t, *args, json_output=True):
    return c.command(ex, ['gcloud', *args, '--project', t['project'], '--quiet', '--format=json'], json_output=json_output)


def resolve(r, ex):
    c.validate_request(r)
    t = r['target']
    c.require(t['provider'] == 'gcp', 'provider', 'GCP adapter requires GCP target')
    project = cli(ex, t, 'projects', 'describe', t['project'])
    account = str(project['projectNumber'])
    c.require(project['projectId'] == t['project'] and project.get('lifecycleState', 'ACTIVE') == 'ACTIVE', 'account-mismatch', 'GCP project mismatch')
    k = t['kind']
    if k == 'gcp.gke':
        resource = cli(ex, t, 'container', 'clusters', 'describe', t['cluster'], '--location', t['location'])
        claims = [resource['selfLink'] + '/namespace/' + t['namespace'] + '/release/' + r['componentId']]
    elif k == 'gcp.cloudrun':
        resource = cli(ex, t, 'run', 'services', 'describe', t['service'], '--region', t['region'])
        claims = ['//run.googleapis.com/projects/' + account + '/locations/' + t['region'] + '/services/' + resource['metadata']['name']]
    elif k == 'gcp.appengine':
        resource = cli(ex, t, 'app', 'services', 'describe', t['service'])
        claims = ['//appengine.googleapis.com/apps/' + account + '/services/' + t['service']]
    elif k == 'gcp.functions-gen2':
        resource = cli(ex, t, 'functions', 'describe', t['functionName'], '--v2', '--region', t['region'])
        claims = [resource['name'].replace('/' + t['project'] + '/', '/' + account + '/')]
        backing = resource.get('serviceConfig', {}).get('service')
        if backing:
            claims.append('//run.googleapis.com/' + backing.replace('/' + t['project'] + '/', '/' + account + '/'))
    elif k == 'gcp.storage-static':
        resource = cli(ex, t, 'storage', 'buckets', 'describe', 'gs://' + t['bucket'])
        c.require(str(resource.get('project_number', resource.get('projectNumber'))) == account, 'account-mismatch', 'bucket project mismatch')
        c.require(resource.get('website', resource.get('website_config')), 'hosting-disabled', 'static website hosting must be preconfigured')
        claims = ['prefix://storage.googleapis.com/' + t['bucket'] + '/' + t['prefix'].strip('/') + '/']
    else:
        cli(ex, t, 'api-gateway', 'apis', 'describe', t['api'])
        resource = cli(ex, t, 'api-gateway', 'gateways', 'describe', t['gateway'], '--location', t['region'])
        claims = [resource['name'].replace('/' + t['project'] + '/', '/' + account + '/'),
            '//apigateway.googleapis.com/projects/' + account + '/apis/' + t['api']]
    return dict(providerIdentity=account, resourceClaims=sorted(claims), resourceLock=claims[0], resource=resource)


def deploy(request, executor, *, context=None, resolved=None):
    from iac_deploy import apply
    return c.execute(request, executor, resolve, apply, context=context, resolved=resolved)




def event_probe(r, ex, ctx, live):
    t, probe = r['target'], r['target']['readiness']['probe']
    nonce = uuid.uuid4().hex
    envelope = json.dumps({'nonce': nonce, 'artifactDigest': r['artifact']['digest'], 'release': c.version(r), 'sourceResource': probe['resource'], 'payload': probe['requestBody']})
    object_name = '.cloudopsworks-probes/' + nonce + '.json'
    try:
        if probe['source'] == 'pubsub':
            cli(ex, t, 'pubsub', 'topics', 'publish', probe['resource'], '--message', envelope)
        else:
            payload = ctx['workDir'] / 'event.json'
            payload.write_text(envelope)
            cli(ex, t, 'storage', 'cp', str(payload), 'gs://' + probe['resource'] + '/' + object_name, json_output=False)
        # Fixed query; JSON-escaped literals. Handler fixture emits a structured completion.
        fields = {'resource.type': 'cloud_run_revision', 'resource.labels.service_name': live['serviceConfig']['service'].split('/')[-1],
            'resource.labels.revision_name': live['serviceConfig']['revision'].split('/')[-1], 'jsonPayload.nonce': nonce,
            'jsonPayload.artifactDigest': r['artifact']['digest'], 'jsonPayload.release': c.version(r),
            'jsonPayload.marker': probe['successLogMarker'], 'jsonPayload.sourceResource': probe['resource'], 'jsonPayload.status': 'completed'}
        query = ' AND '.join(key + '=' + json.dumps(value) for key, value in fields.items())
        def ready():
            logs = cli(ex, t, 'logging', 'read', query, '--freshness=5m', '--limit=20')
            return any(all(log.get('jsonPayload', {}).get(key) == value for key, value in {
                'nonce': nonce, 'artifactDigest': r['artifact']['digest'], 'release': c.version(r),
                'marker': probe['successLogMarker'], 'status': 'completed', 'sourceResource': probe['resource']}.items()) and
                log.get('resource', {}).get('labels', {}).get('service_name') == live['serviceConfig']['service'].split('/')[-1] and
                log.get('resource', {}).get('labels', {}).get('revision_name') == live['serviceConfig']['revision'].split('/')[-1] for log in logs)
        c.poll(r, ctx, ready)
    finally:
        if probe['source'] == 'storage-finalize':
            cli(c.cleanup_executor(ex), t, 'storage', 'rm', 'gs://' + probe['resource'] + '/' + object_name, json_output=False)
