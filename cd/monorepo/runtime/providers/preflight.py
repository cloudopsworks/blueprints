"""Read-only native inventory and exact private-state ownership, before IaC.

Successful complete inventories prove absence. CLI errors (including permission
errors and unclassified 404 text) NEVER become absence. Historical handles and
private state are supplied only after independent host/backend verification.
"""
import re
import json
from pathlib import Path
from urllib.parse import quote
from contracts import digest
from operations import validate_operation
from . import common as c


def _items(value, key=None):
    if isinstance(value,dict) and any(value.get(k) for k in ('nextPageToken','NextToken','nextToken','NextContinuationToken','nextLink')):
        c.require(False,'inventory-incomplete','native inventory is not complete')
    result=value.get(key) if key and isinstance(value,dict) else value
    c.require(isinstance(result,list) and all(isinstance(v,dict) for v in result),
              'inventory-invalid','native inventory is incomplete or malformed')
    return result


def _one(values, predicate, *, field='id'):
    for item in values:
        selected=item
        for part in field.split('.'):
            selected=selected.get(part) if isinstance(selected,dict) else None
        c.require(isinstance(selected,str) and selected,'inventory-invalid','native inventory item has no exact selector')
    found=[value for value in values if predicate(value)]
    c.require(len(found)<=1,'inventory-ambiguous','native workload selector is ambiguous')
    return found[0] if found else None


def _state_ids(state, addresses):
    c.require(isinstance(state,dict) and state.get('version')==4 and isinstance(state.get('resources'),list),
              'inventory-private-state','verified private native state is required')
    ids=set()
    for resource in state['resources']:
        if resource.get('mode')=='data':continue
        c.require(resource.get('mode')=='managed' and not resource.get('module'),
                  'inventory-private-state','private state resource scope is unsupported')
        base=resource.get('type','')+'.'+resource.get('name','')
        if base not in addresses:continue
        for instance in _items(resource.get('instances')):
            attributes=instance.get('attributes',{})
            value=attributes.get('id')
            if resource.get('type')=='helm_release' and isinstance(value,str) and '/' not in value:
                namespace=attributes.get('namespace')
                c.require(isinstance(namespace,str) and namespace,'inventory-private-state','owned Helm namespace is missing')
                value=namespace+'/'+value
            c.require(isinstance(value,str) and value,'inventory-private-state','private owned resource has no native identity')
            ids.add(value.casefold() if value.startswith('/subscriptions/') else value)
            arn=attributes.get('arn')
            if isinstance(arn,str) and arn.startswith('arn:'):
                ids.add(arn)
    return ids


def _contains_identity(identity, target):
    return isinstance(target,dict) and all(
        _contains_identity(value,target.get(key)) if isinstance(value,dict) else target.get(key)==value
        for key,value in identity.items())


def _owned(handle,state,native_ids,addresses,resource):
    validate_operation(handle)
    owner=digest(handle)
    known=_state_ids(state,addresses)
    c.require(native_ids and native_ids<=known,'inventory-unowned','native workload is absent from independently verified private owned state')
    # Truncated cloud labels are compared only alongside the FULL host-verified
    # immutable handle and exact private state IDs, never promoted by themselves.
    for tags in (resource.get('tags'),resource.get('Tags'),resource.get('labels'),resource.get('metadata',{}).get('labels')):
        if isinstance(tags,dict) and 'cloudopsworks-owner' in tags:
            tag=tags['cloudopsworks-owner']
            c.require(tag in (owner,owner[7:47]),'inventory-owner','native ownership metadata differs')
    return owner


def require_external_namespace(namespace,name):
    c.require(namespace.get('metadata',{}).get('name')==name,'inventory-parent','external namespace differs')
    metadata=namespace.get('metadata',{})
    labels=metadata.get('labels',{});annotations=metadata.get('annotations',{})
    c.require(isinstance(labels,dict) and isinstance(annotations,dict)
        and 'cloudopsworks.io/pr' not in labels
        and labels.get('cloudopsworks.io/managed-by')!='blueprints-monorepo'
        and 'cloudopsworks.io/owner-digest' not in annotations,
        'inventory-preview-namespace','normal workloads cannot claim a preview-managed namespace')

def resolve(request,executor,*,historical_handle=None,private_state=None,kubeconfig=None):
    """Resolve all accepted normal families without interpreting stderr as 404.

    `historical_handle` MUST already be independently host-origin verified; this
    function checks canonical target/component/account and private native IDs.
    No import, adoption, parent provisioning or state write is performed.
    """
    c.validate_request(request)
    t=request['target'];kind=t['kind'];component=request['componentId'];resource=None
    native_ids=set();addresses=set();claims=[]
    if t['provider']=='aws':
        from .aws import cli
        account=cli(executor,t,'sts','get-caller-identity')['Account']
        c.require(isinstance(account,str) and re.fullmatch(r'[0-9]{12}',account),'account-mismatch','AWS account is invalid')
        if kind=='aws.lambda':
            resource=_one(_items(cli(executor,t,'lambda','list-functions'),'Functions'),lambda v:v.get('FunctionName')==t['functionName'],field='FunctionName')
            claim='arn:aws:lambda:'+t['region']+':'+account+':function:'+t['functionName'];claims=[claim]
            if resource:
                c.require(resource.get('FunctionArn')==claim,'account-mismatch','function identity differs')
                native_ids={claim};addresses={'aws_lambda_function.component'}
                resource=cli(executor,t,'lambda','get-function','--function-name',t['functionName'])
        elif kind=='aws.beanstalk':
            apps=_items(cli(executor,t,'elasticbeanstalk','describe-applications','--application-names',t['application']),'Applications')
            c.require(len(apps)==1 and apps[0].get('ApplicationName')==t['application'],'inventory-parent','external application is missing')
            resource=_one(_items(cli(executor,t,'elasticbeanstalk','describe-environments','--environment-names',t['environmentName']),'Environments'),lambda v:v.get('EnvironmentName')==t['environmentName'],field='EnvironmentName')
            claims=['arn:aws:elasticbeanstalk:'+t['region']+':'+account+':environment/'+t['application']+'/'+t['environmentName']]
            if resource:
                c.require(resource.get('ApplicationName')==t['application'] and resource.get('EnvironmentArn')==claims[0],'inventory-parent','environment application differs')
                native_ids={resource['EnvironmentId']};addresses={'aws_elastic_beanstalk_environment.component'}
        elif kind=='aws.apigateway-rest':
            values=_items(cli(executor,t,'apigateway','get-rest-apis'),'items')
            resource=_one(values,lambda v:v.get('id')==t['restApiId']) if t.get('restApiId') else _one(values,lambda v:v.get('name')==t['apiName'],field='name')
            claims=['arn:aws:apigateway:'+t['region']+':'+account+':/restapis/'+t['restApiId']] if t.get('restApiId') else ['aws:'+account+':'+t['region']+':rest-api:new-name:'+t['apiName']]
            if resource:
                native_ids={resource['id']};addresses={'aws_api_gateway_rest_api.component'}
                claims.append('arn:aws:apigateway:'+t['region']+':'+account+':/restapis/'+resource['id'])
        elif kind=='aws.s3-static':
            cli(executor,t,'s3api','head-bucket','--bucket',t['bucket'],'--expected-bucket-owner',account,json_output=False)
            resource=cli(executor,t,'s3api','get-bucket-website','--bucket',t['bucket'],'--expected-bucket-owner',account)
            listing=cli(executor,t,'s3api','list-objects-v2','--bucket',t['bucket'],'--prefix',t['prefix'].strip('/')+'/','--expected-bucket-owner',account)
            c.require(isinstance(listing,dict) and listing.get('IsTruncated') is False and not listing.get('NextContinuationToken'), 'inventory-incomplete','object inventory was truncated')
            if 'Contents' not in listing:
                c.require(listing.get('KeyCount')==0,'inventory-invalid','empty object inventory is not explicit')
                listing=dict(listing,Contents=[])
            objects=_items(listing,'Contents')
            native_ids={v['Key'] for v in objects};addresses={'aws_s3_object.files'}
            claims=['prefix:arn:aws:s3:::'+t['bucket']+'/'+t['prefix'].strip('/')+'/'];resource=dict(resource,inventoryObjects=objects)
        else:
            resource=cli(executor,t,'eks','describe-cluster','--name',t['cluster'])['cluster']
            c.require(resource['arn']=='arn:aws:eks:'+t['region']+':'+account+':cluster/'+t['cluster'],'inventory-parent','cluster identity differs')
            claims=[resource['arn']+'/namespace/'+t['namespace']+'/release/'+component]
    elif t['provider']=='gcp':
        from .gcp import cli
        project=cli(executor,t,'projects','describe',t['project']);account=str(project['projectNumber'])
        c.require(project.get('projectId')==t['project'] and project.get('lifecycleState','ACTIVE')=='ACTIVE','account-mismatch','project identity differs')
        prefix='projects/'+t['project']+'/locations/'+t.get('region',t.get('location',''))
        if kind=='gcp.cloudrun':
            resource=_one(_items(cli(executor,t,'run','services','list','--region',t['region'])),lambda v:v.get('metadata',{}).get('name')==t['service'],field='metadata.name')
            name=prefix+'/services/'+t['service'];claims=['//run.googleapis.com/'+name.replace('/'+t['project']+'/', '/'+account+'/')]
            if resource:native_ids={name};addresses={'google_cloud_run_v2_service.component'}
        elif kind=='gcp.appengine':
            c.require(t.get('ownership','external')=='managed' and t['service']!='default',
                'inventory-appengine-exclusive','App Engine requires an explicitly managed exclusive nondefault service')
            resource=_one(_items(cli(executor,t,'app','services','list')),lambda v:v.get('id')==t['service'])
            # Global application/service identity, never partitioned by region
            # or authentication alias. External project/application remain unowned.
            claims=['//appengine.googleapis.com/apps/'+account+'/services/'+t['service']]
            if resource:
                versions=_items(cli(executor,t,'app','versions','list','--service',t['service']))
                c.require(bool(versions) and all(isinstance(v.get('id'),str) and v['id'] for v in versions),
                    'inventory-appengine-history','existing service version inventory is incomplete')
                c.require(historical_handle is not None and isinstance(private_state,dict),
                    'inventory-appengine-history','preexisting service has no independently verified exclusive history')
                expected_type='google_app_engine_'+('flexible' if historical_handle['resourceIdentity'].get('appEnvironment','standard')=='flexible' else 'standard')+'_app_version'
                owned_versions=[v for v in private_state.get('resources',[]) if v.get('mode')=='managed' and v.get('type') in
                    ('google_app_engine_standard_app_version','google_app_engine_flexible_app_version')]
                c.require(len(owned_versions)==1 and owned_versions[0]['type']==expected_type,
                    'inventory-appengine-mode','historical service hosting mode is ambiguous or changed')
                instances=owned_versions[0].get('instances',[])
                c.require(len(instances)==1,'inventory-appengine-history','exclusive service has ambiguous version history')
                old=instances[0].get('attributes',{})
                c.require(old.get('delete_service_on_destroy') is True and old.get('noop_on_destroy') is False
                    and old.get('project')==t['project'] and old.get('service')==t['service'],
                    'inventory-appengine-history','legacy or unknown service deletion history is not adoptable')
                resource=dict(resource,inventoryVersions=versions)
                native_ids={'apps/'+t['project']+'/services/'+t['service']+'/versions/'+v['id'] for v in versions}
                addresses={'google_app_engine_standard_app_version.component','google_app_engine_flexible_app_version.component'}
        elif kind=='gcp.functions-gen2':
            name=prefix+'/functions/'+t['functionName']
            resource=_one(_items(cli(executor,t,'functions','list','--v2','--regions',t['region'])),lambda v:v.get('name')==name,field='name')
            claims=['//cloudfunctions.googleapis.com/'+name.replace('/'+t['project']+'/', '/'+account+'/')]
            if resource:
                native_ids={name};addresses={'google_cloudfunctions2_function.component'}
                backing=resource.get('serviceConfig',{}).get('service')
                if backing:claims.append('//run.googleapis.com/'+backing.replace('/'+t['project']+'/', '/'+account+'/'))
        elif kind=='gcp.storage-static':
            resource=cli(executor,t,'storage','buckets','describe','gs://'+t['bucket'])
            c.require(str(resource.get('project_number',resource.get('projectNumber')))==account and resource.get('website',resource.get('website_config')),'inventory-parent','external static bucket differs')
            objects=_items(cli(executor,t,'storage','objects','list','gs://'+t['bucket']+'/**'))
            objects=[v for v in objects if v.get('name','').startswith(t['prefix'].strip('/')+'/')]
            native_ids={t['bucket']+'/'+v['name'] for v in objects};addresses={'google_storage_bucket_object.files'}
            claims=['prefix://storage.googleapis.com/'+t['bucket']+'/'+t['prefix'].strip('/')+'/'];resource=dict(resource,inventoryObjects=objects)
        elif kind=='gcp.apigateway':
            resource=_one(_items(cli(executor,t,'api-gateway','gateways','list','--location',t['region'])),lambda v:v.get('name')==prefix+'/gateways/'+t['gateway'],field='name')
            apis=_items(cli(executor,t,'api-gateway','apis','list'))
            api=_one(apis,lambda v:v.get('name')=='projects/'+t['project']+'/locations/global/apis/'+t['api'],field='name')
            c.require((resource is None)==(api is None),'inventory-partial','partial API workload requires reviewed recovery')
            claims=['//apigateway.googleapis.com/projects/'+account+'/apis/'+t['api'],'//apigateway.googleapis.com/'+prefix.replace('/'+t['project']+'/', '/'+account+'/')+'/gateways/'+t['gateway']]
            if resource:native_ids={resource['name'],api['name']};addresses={'google_api_gateway_gateway.component','google_api_gateway_api.component'}
        else:
            resource=cli(executor,t,'container','clusters','describe',t['cluster'],'--location',t['location'])
            claims=[resource['selfLink']+'/namespace/'+t['namespace']+'/release/'+component]
    else:
        from .azure import cli
        account_record=cli(executor,t,'account','show');account=account_record['id'].casefold()
        c.require(account==t['subscriptionId'].casefold() and account_record.get('state')=='Enabled','account-mismatch','subscription identity differs')
        base='/subscriptions/'+account+'/resourcegroups/'+t['resourceGroup'].casefold()+'/providers/'
        rg=['--resource-group',t['resourceGroup']]
        if kind=='azure.containerapps':
            name=base+'microsoft.app/containerapps/'+t['appName'].casefold()
            resource=_one(_items(cli(executor,t,'containerapp','list',*rg)),lambda v:str(v.get('id','')).casefold()==name)
            claims=[name];addresses={'azurerm_container_app.component'}
        elif kind in ('azure.appservice','azure.functions'):
            name=base+'microsoft.web/sites/'+t['appName'].casefold();slot=t['slot'].casefold()
            if slot=='production':
                group='functionapp' if kind=='azure.functions' else 'webapp'
                values=_items(cli(executor,t,group,'list',*rg))
            else:
                parent=cli(executor,t,'webapp','show',*rg,'--name',t['appName'])
                c.require(str(parent.get('id','')).casefold()==name,'inventory-parent','external slot parent differs')
                values=_items(cli(executor,t,'webapp','deployment','slot','list',*rg,'--name',t['appName']));name+='/slots/'+slot
            resource=_one(values,lambda v:str(v.get('id','')).casefold()==name)
            claims=['prefix:'+name+'/']
            addresses={('azurerm_'+os+'_function_app'+suffix+'.component') for os in ('linux','windows') for suffix in ('','_slot')}
            addresses|={('azurerm_'+os+'_web_app'+suffix+'.component') for os in ('linux','windows') for suffix in ('','_slot')}
            addresses.add('azurerm_function_app_flex_consumption.component')
        elif kind=='azure.apim':
            name=base+'microsoft.apimanagement/service/'+t['serviceName'].casefold()+'/apis/'+t['apiId'].casefold()
            resource=_one(_items(cli(executor,t,'apim','api','list',*rg,'--service-name',t['serviceName'])),lambda v:str(v.get('id','')).casefold().split(';rev=')[0]==name)
            claims=[name];addresses={'azurerm_api_management_api.component'}
        elif kind=='azure.blob-static':
            resource=cli(executor,t,'storage','account','show',*rg,'--name',t['account'])
            name=base+'microsoft.storage/storageaccounts/'+t['account'].casefold()
            c.require(str(resource.get('id','')).casefold()==name,'inventory-parent','storage account differs')
            website=cli(executor,t,'storage','blob','service-properties','show','--account-name',t['account'],'--auth-mode','login')
            c.require(website.get('staticWebsite',{}).get('enabled') is True,'inventory-parent','static website is disabled')
            objects=_items(cli(executor,t,'storage','blob','list','--account-name',t['account'],'--container-name','$web','--prefix',t['prefix'].strip('/')+'/','--auth-mode','login'))
            native_ids={'https://'+t['account']+'.blob.core.windows.net/$web/'+quote(v['name'],safe='/') for v in objects};addresses={'azurerm_storage_blob.files'}
            claims=['prefix:'+name+'/$web/'+t['prefix'].strip('/')+'/'];resource=dict(resource,inventoryObjects=objects)
        else:
            resource=cli(executor,t,'aks','show',*rg,'--name',t['cluster']);claims=[c.resource_id(resource['id'])+'/namespace/'+t['namespace']+'/release/'+component]
        if resource and kind not in ('azure.blob-static','azure.aks'):native_ids={c.resource_id(resource['id'])}
    if kind in ('aws.eks','gcp.gke','azure.aks'):
        c.require(kubeconfig,'inventory-kubeconfig','verified cluster kubeconfig is required')
        env={'KUBECONFIG':str(kubeconfig)}
        namespace=c.command(executor,['kubectl','get','namespace',t['namespace'],'-o','json'],env=env)
        c.require(namespace.get('metadata',{}).get('name')==t['namespace'],'inventory-parent','external namespace differs')
        require_external_namespace(namespace,t['namespace'])
        release=_one(_items(c.command(executor,['helm','list','--namespace',t['namespace'],'--all','--output','json'],env=env)),lambda v:v.get('name')==component,field='name')
        resource=release
        if release:
            c.require(release.get('namespace')==t['namespace'],'inventory-parent','owned Helm namespace differs')
            native_ids={t['namespace']+'/'+component};addresses={'helm_release.component'}
    exists=bool(native_ids)
    if resource is not None and kind not in ('aws.s3-static','gcp.storage-static','azure.blob-static') and not exists:
        c.require(False,'inventory-invalid','native resource has no exact identity')
    owner=None
    if exists:
        c.require(historical_handle is not None,'inventory-unowned','preexisting workload requires separate adoption prerequisite')
        c.require(historical_handle['componentId']==component and historical_handle['targetId']==t['id']
            and historical_handle['providerIdentity']==account and historical_handle['origin']['repository']==request['repository']
            and historical_handle['moduleId']==kind.replace('.','-')
            and _contains_identity(historical_handle['resourceIdentity'],t),
            'inventory-owner','historical owner identity differs')
        # Use exact selected root address inventory, not a guessed family name.
        blueprint=Path(__file__).resolve().parents[4]
        catalog=json.loads((blueprint/'terraform/monorepo/module-catalog.json').read_text())
        row=catalog['modules'][historical_handle['moduleId']]
        metadata=blueprint/row['path']/'inputs.json'
        c.require(metadata.resolve().is_relative_to(blueprint) and 'inputs.json' in row['files'],'inventory-root','fixed ownership root metadata is invalid')
        root_metadata=json.loads(metadata.read_text())
        addresses={re.sub(r'\[.*$', '', value) for value in root_metadata['ownedResourceAddresses']}
        owner=_owned(historical_handle,private_state,native_ids,addresses,resource)
    elif historical_handle is None:
        c.require(t.get('ownership','external')=='managed','inventory-adoption-required','fresh creation requires explicit managed ownership')
    return {'providerIdentity':account,'resourceClaims':sorted(set(claims)),'resourceLock':sorted(set(claims))[0],
            'resource':resource or {},'existing':{'providerIdentity':account,'exists':exists,'ownerDigest':owner}}
