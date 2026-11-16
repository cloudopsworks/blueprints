"""Azure existing-resource adapters. Never provisions landing zones or uses admin AKS credentials."""
import json
import uuid
import re
import urllib.parse

import contracts
from . import common as c


def cli(ex, t, *args, json_output=True):
    return c.command(ex, ['az', *args, '--subscription', t['subscriptionId'], '--only-show-errors', '--output', 'json'], json_output=json_output)


def app_args(t):
    args = ['--resource-group', t['resourceGroup'], '--name', t['appName']]
    if t['slot'] != 'production':
        args += ['--slot', t['slot']]
    return args


def resolve(r, ex):
    c.validate_request(r)
    t = r['target']; k = t['kind']
    c.require(t['provider'] == 'azure', 'provider', 'Azure adapter requires Azure target')
    account = cli(ex, t, 'account', 'show')
    c.require(account['id'].casefold() == t['subscriptionId'].casefold() and account.get('state') == 'Enabled', 'account-mismatch', 'Azure subscription mismatch')
    identity = account['id'].casefold()
    base = ['--resource-group', t['resourceGroup']]
    if k == 'azure.aks':
        resource = cli(ex, t, 'aks', 'show', *base, '--name', t['cluster'])
        claims = [c.resource_id(resource['id']) + '/namespace/' + t['namespace'] + '/release/' + r['componentId']]
    elif k == 'azure.containerapps':
        resource = cli(ex, t, 'containerapp', 'show', *base, '--name', t['appName'])
        claims = [c.resource_id(resource['id'])]
    elif k in ('azure.appservice','azure.functions'):
        group = 'functionapp' if k == 'azure.functions' else 'webapp'
        resource = cli(ex, t, group, 'show', *app_args(t))
        actual=c.resource_id(resource['id']);parent=actual.split('/slots/')[0]
        expected=parent if t['slot'].casefold()=='production' else parent+'/slots/'+t['slot'].casefold()
        c.require(actual==expected,'resource-identity','resolved app/slot differs from exact target scope')
        # Production owns the parent deletion radius; independently owned slots
        # share an EXTERNAL parent but cannot overlap each other's child scopes.
        slot=t['slot'].casefold()
        claims = ['prefix:'+parent+'/' if slot=='production' else 'prefix:'+parent+'/slots/'+slot+'/']
    elif k == 'azure.blob-static':
        resource = cli(ex, t, 'storage', 'account', 'show', *base, '--name', t['account'])
        properties = cli(ex, t, 'storage', 'blob', 'service-properties', 'show', '--account-name', t['account'], '--auth-mode', 'login')
        c.require(properties.get('staticWebsite', {}).get('enabled') is True, 'hosting-disabled', 'static hosting must be preconfigured')
        claims = ['prefix:' + c.resource_id(resource['id']) + '/$web/' + t['prefix'].strip('/') + '/']
    else:
        resource = cli(ex, t, 'apim', 'api', 'show', *base, '--service-name', t['serviceName'], '--api-id', t['apiId'])
        claims = [c.resource_id(resource['id']).split(';rev=')[0]]
        # Instance identity/origin is read independently, not copied from OpenAPI servers.
        resource = dict(resource, instance=cli(ex, t, 'apim', 'show', *base, '--name', t['serviceName']))
    for claim in claims:
        c.require(claim.removeprefix('prefix:').startswith('/subscriptions/' + identity + '/'), 'account-mismatch', 'resolved ARM resource belongs to another subscription')
    return dict(providerIdentity=identity, resourceClaims=sorted(claims), resourceLock=claims[0], resource=resource)


def deploy(request, executor, *, context=None, resolved=None):
    from iac_deploy import apply
    return c.execute(request, executor, resolve, apply, context=context, resolved=resolved)




def admin_probe(r, ex, ctx, live, base):
    t, probe = r['target'], r['target']['readiness']['probe']
    key = ctx.get('hostKeys', {}).get(probe['hostKeyRef'], {})
    c.require(key.get('resourceId','').casefold() == live['id'].casefold() and key.get('keyName') == '_master' and key.get('hostname') == live['defaultHostName'], 'probe-auth', 'administrative key must belong to this exact app/slot')
    secret = key.get('value')
    c.require(isinstance(secret,str) and secret and '\n' not in secret and '\r' not in secret, 'probe-auth', 'administrative key is unavailable')
    nonce = uuid.uuid4().hex
    envelope = dict(nonce=nonce, artifactDigest=r['artifact']['digest'], release=c.version(r), functionName=probe['functionName'], resourceId=live['id'], payload=probe['requestBody'])
    body = json.dumps({'input': json.dumps(envelope)})
    transport = ctx.get('http', c.http_request)
    code, _ = transport(base + '/admin/functions/' + probe['functionName'], method='POST', body=body,
        headers={'x-functions-key': secret, 'Content-Type':'application/json'}, timeout=c.remaining(ctx))
    c.require(code == 202, 'handler-failed', 'admin invocation was not accepted')
    # Only structured handler completion can prove execution. Arbitrary raw query is not accepted.
    fields = {'nonce':nonce,'artifactDigest':r['artifact']['digest'],'release':c.version(r),'marker':probe['successLogMarker'],
              'functionName':probe['functionName'],'resourceId':live['id'],'status':'completed',
              **{'build_' + key:value for key,value in c.build_identity(r).items()}}
    query = 'traces | where timestamp > ago(5m)'
    for key,value in fields.items():
        query += ' | where tostring(customDimensions.' + key + ') == ' + json.dumps(value)
    query += ' | project ' + ', '.join(key + '=tostring(customDimensions.' + key + ')' for key in fields) + ' | take 20'
    def completed():
        data = cli(ex, t, 'monitor', 'app-insights', 'query', '--app', probe['appInsightsAppId'], '--analytics-query', query)
        for table in data.get('tables',[]):
            columns = [x['name'] for x in table['columns']]
            for row in table['rows']:
                if all(dict(zip(columns,row)).get(key) == value for key,value in fields.items()):
                    return True
        return False
    c.poll(r, ctx, completed)


