"""Read-only native identity and serving checks after exact saved IaC apply.

No resource configuration or workload publication is performed here. Lambda
invoke/HTTP probes exercise the intended immutable workload, not management API
success. Unsupported families fail closed until their own native proof exists.
"""
from __future__ import annotations
import base64
import json
import re
from . import common as c


def verify(r,ex,ctx,outputs,*,image=None,directory=None):
    t=r['target'];kind=t['kind']
    if kind.startswith('azure.') and kind!='azure.aks':
        from .azure_readiness import verify as verify_azure
        return verify_azure(r,ex,ctx,outputs,image=image,directory=directory)
    owned=outputs.get('owned')
    c.require(isinstance(owned,dict),'iac-readiness-output','root has no owned resource outputs')
    if kind in ('aws.eks','gcp.gke','azure.aks'):return kubernetes(r,ex,ctx,outputs,image=image)
    if kind=='aws.lambda':
        from .aws import cli
        version=owned.get('version');arn=owned.get('function_arn')
        c.require(isinstance(version,str) and version.isdigit() and int(version)>0
            and arn=='arn:aws:lambda:'+t['region']+':'+ctx['expectedIdentity']+':function:'+t['functionName'],
            'iac-readiness-output','root Lambda output is not exact')
        def check():
            live=cli(ex,t,'lambda','get-function','--function-name',t['functionName'],'--qualifier',version)
            cfg=live['Configuration']
            correct=cfg.get('Version')==version and cfg.get('State')=='Active' and cfg.get('LastUpdateStatus')=='Successful'
            correct=correct and cfg.get('Architectures',['x86_64'])==['x86_64' if r['package']['architecture']=='amd64' else 'arm64']
            if image: correct=correct and live.get('Code',{}).get('ResolvedImageUri')==image
            else:
                correct=correct and base64.b64decode(cfg.get('CodeSha256','')).hex()==r['artifact']['digest'][7:]
                correct=correct and cfg.get('Handler')==r['package']['entryPoint'] and cfg.get('Runtime')==r['package']['runtime']
            if t['alias']:
                alias=cli(ex,t,'lambda','get-alias','--function-name',t['functionName'],'--name',t['alias'])
                correct=correct and alias.get('FunctionVersion')==version and not alias.get('RoutingConfig',{}).get('AdditionalVersionWeights')
            return correct
        c.poll(r,ctx,check)
        probe=t['readiness']['probe'];payload=ctx['workDir']/'invoke-input.json';payload.write_text(probe['requestBody'])
        output=ctx['workDir']/'invoke-output.json'
        invocation=cli(ex,t,'lambda','invoke','--function-name',t['functionName'],'--qualifier',version,
            '--invocation-type','RequestResponse','--payload','fileb://'+str(payload),str(output))
        c.require(invocation.get('StatusCode')==200 and not invocation.get('FunctionError') and invocation.get('ExecutedVersion')==version,
            'handler-failed','intended Lambda handler invocation failed')
        c.require(output.is_file() and output.stat().st_size<=1024*1024 and probe['responseContains'] in output.read_text(),
            'handler-failed','intended Lambda response failed')
        return None
    if kind=='aws.beanstalk':
        from .aws import cli
        expected_version=r['artifact']['digest'][7:]
        c.require(owned.get('environmentName')==t['environmentName'] and owned.get('version')==expected_version
            and isinstance(owned.get('environmentId'),str), 'iac-readiness-output','root Beanstalk outputs differ')
        def check():
            environments=cli(ex,t,'elasticbeanstalk','describe-environments','--environment-ids',owned['environmentId']).get('Environments',[])
            c.require(len(environments)==1,'intended-environment','intended Beanstalk environment is missing or ambiguous')
            live=environments[0]
            c.require(live.get('EnvironmentName')==t['environmentName'] and live.get('ApplicationName')==t['application'],
                'intended-environment','native Beanstalk identity differs')
            return live if live.get('VersionLabel')==expected_version and live.get('Status')=='Ready' and live.get('Health')=='Green' else False
        live=c.poll(r,ctx,check)
        versions=cli(ex,t,'elasticbeanstalk','describe-application-versions','--application-name',t['application'],
            '--version-labels',expected_version).get('ApplicationVersions',[])
        c.require(len(versions)==1 and versions[0].get('SourceBundle')=={'S3Bucket':t['bucket'],
            'S3Key':t['prefix'].strip('/')+'/'+expected_version+'/application.zip'},
            'intended-package','Beanstalk version does not reference the intended immutable ZIP')
        base=c.origin('http://'+live['CNAME'],host_suffix='.elasticbeanstalk.com',allow_http=True)
        return c.serving(r,ex,ctx,base,allow_http=True)
    if kind=='aws.s3-static':
        c.require(isinstance(owned.get('objects'),list) and bool(owned['objects']),
            'iac-readiness-output','root static objects are missing')
        hyphen=t['region'] in {'us-east-1','us-west-1','us-west-2','eu-west-1','ap-southeast-1','ap-southeast-2','ap-northeast-1','sa-east-1'}
        suffix='.amazonaws.com.cn' if t['region'].startswith('cn-') else '.amazonaws.com'
        base=c.origin('http://'+t['bucket']+'.s3-website'+('-' if hyphen else '.')+t['region']+suffix,
            host_suffix=suffix,allow_http=True)
        return c.verify_static(r,ex,ctx,directory,base,t['prefix'])
    if kind=='aws.apigateway-rest':
        from .aws import cli
        api_id=owned.get('restApiId')
        c.require(isinstance(api_id,str) and re.fullmatch('[a-z0-9]{1,32}',api_id)
            and (not t.get('restApiId') or t['restApiId']==api_id)
            and owned.get('stage')==t['stage'] and isinstance(owned.get('deploymentId'),str),
            'iac-readiness-output','root REST API output identity differs')
        stage=cli(ex,t,'apigateway','get-stage','--rest-api-id',api_id,'--stage-name',t['stage'])
        c.require(stage.get('deploymentId')==owned['deploymentId'],'intended-stage','REST stage has a different immutable deployment')
        suffix='.amazonaws.com.cn' if t['region'].startswith('cn-') else '.amazonaws.com'
        base=c.origin('https://'+api_id+'.execute-api.'+t['region']+suffix,host_suffix=suffix)
        c.require(owned.get('invokeUrl','').rstrip('/')==base+'/'+t['stage'],'iac-readiness-output','root invoke URL differs from canonical API endpoint')
        return c.serving(r,ex,ctx,base,path_prefix=t['stage'])
    if kind=='gcp.cloudrun':
        from .gcp import cli
        c.require(owned.get('service')=='projects/'+t['project']+'/locations/'+t['region']+'/services/'+t['service'],
            'iac-readiness-output','root Cloud Run output is not exact')
        def check():
            live=cli(ex,t,'run','services','describe',t['service'],'--region',t['region'])
            status,spec=live['status'],live['spec'];desired=status.get('latestReadyRevisionName')
            ready=any(v.get('type')=='Ready' and v.get('status')=='True' for v in status.get('conditions',[]))
            ready=ready and desired and desired==status.get('latestCreatedRevisionName')
            ready=ready and str(status.get('observedGeneration'))==str(live['metadata']['generation'])
            ready=ready and spec['template']['spec']['containers'][0]['image']==image
            ready=ready and sum(v.get('percent',0) for v in status.get('traffic',[]) if v.get('revisionName')==desired)==100
            return live if ready else False
        live=c.poll(r,ctx,check)
        return c.serving(r,ex,ctx,c.origin(live['status']['url'],host_suffix='.run.app'))
    if kind=='gcp.functions-gen2':
        from .gcp import cli,event_probe
        expected='projects/'+t['project']+'/locations/'+t['region']+'/functions/'+t['functionName']
        c.require(owned.get('function')==expected,'iac-readiness-output','root Gen2 function identity differs')
        def check():
            live=cli(ex,t,'functions','describe',t['functionName'],'--v2','--region',t['region'])
            c.require(live.get('name')==expected,'intended-function','native Gen2 function identity differs')
            build=live.get('buildConfig',{});service=live.get('serviceConfig',{})
            source=build.get('source',{}).get('storageSource',{})
            object_name='cloudopsworks/'+ctx['iacOwnerDigest'][7:]+'/'+r['artifact']['digest'][7:]+'/main.zip'
            ready=live.get('state')=='ACTIVE' and service.get('allTrafficOnLatestRevision') is True
            ready=ready and service.get('serviceAccountEmail')==t['serviceAccount']
            ready=ready and build.get('runtime')==r['package']['runtime'] and build.get('entryPoint')==r['package']['entryPoint']
            ready=ready and source.get('bucket')==t['iac']['sourceBucket'] and source.get('object')==object_name
            ready=ready and live.get('labels',{}).get('cloudopsworks-owner')==ctx['iacOwnerDigest'][7:47]
            event=live.get('eventTrigger')
            probe=t['readiness']['probe']
            if t['trigger']['kind']=='http':ready=ready and not event
            else:
                expected_event='google.cloud.pubsub.topic.v1.messagePublished' if probe['source']=='pubsub' else 'google.cloud.storage.object.v1.finalized'
                ready=ready and isinstance(event,dict) and event.get('eventType')==expected_event
                if isinstance(event,dict):
                    ready=ready and (event.get('pubsubTopic')==t['trigger']['value'] if probe['source']=='pubsub' else
                        any(item.get('attribute')=='bucket' and item.get('value')==t['trigger']['value'] for item in event.get('eventFilters',[])))
            return live if ready else False
        live=c.poll(r,ctx,check)
        if t['trigger']['kind']=='http':return c.serving(r,ex,ctx,c.origin(live['serviceConfig']['uri'],host_suffix='.run.app'))
        event_probe(r,ex,ctx,live)
        return None
    if kind=='gcp.appengine':
        from .gcp import cli
        prefix='apps/'+t['project']+'/services/'+t['service']+'/versions/'
        value=owned.get('version')
        c.require(isinstance(value,str) and value.startswith(prefix) and re.fullmatch(r'v-[0-9a-f]{16,40}',value[len(prefix):]),
            'iac-readiness-output','root App Engine immutable version differs')
        version=value[len(prefix):]
        def check():
            live=cli(ex,t,'app','versions','describe',version,'--service',t['service'])
            traffic=cli(ex,t,'app','services','describe',t['service'])
            correct=live.get('id')==version and live.get('servingStatus')=='SERVING'
            correct=correct and traffic.get('split',{}).get('allocations')=={version:1}
            if image:correct=correct and live.get('deployment',{}).get('container',{}).get('image')==image and live.get('env')=='flex'
            else:
                source='https://storage.googleapis.com/'+t['iac']['sourceBucket']+'/cloudopsworks/'+ctx['iacOwnerDigest'][7:]+'/'+r['artifact']['digest'][7:]+'/main.zip'
                correct=correct and live.get('deployment',{}).get('zip',{}).get('sourceUrl')==source
            return live if correct else False
        live=c.poll(r,ctx,check)
        return c.serving(r,ex,ctx,c.origin(live['versionUrl'],host_suffix='.appspot.com'))
    if kind=='gcp.storage-static':
        c.require(isinstance(owned.get('objects'),list) and bool(owned['objects']),'iac-readiness-output','root static objects are missing')
        return c.verify_static(r,ex,ctx,directory,c.origin('https://storage.googleapis.com',host_suffix='storage.googleapis.com'),t['bucket']+'/'+t['prefix'])
    if kind=='gcp.apigateway':
        from .gcp import cli
        prefix='projects/'+t['project']+'/locations/'
        c.require(owned.get('gateway')==prefix+t['region']+'/gateways/'+t['gateway']
            and owned.get('api')==prefix+'global/apis/'+t['api']
            and isinstance(owned.get('config'),str) and owned['config'].startswith(owned['api']+'/configs/'),
            'iac-readiness-output','root API Gateway outputs are not exact')
        def check():
            live=cli(ex,t,'api-gateway','gateways','describe',t['gateway'],'--location',t['region'])
            return live if live.get('state')=='ACTIVE' and live.get('apiConfig')==owned['config'] else False
        live=c.poll(r,ctx,check)
        return c.serving(r,ex,ctx,c.origin('https://'+live['defaultHostname'],host_suffix='.gateway.dev'))
    c.require(False,'iac-readiness-capability-blocked','selected family readiness is not implemented')


def kubernetes(r,ex,ctx,outputs,*,image):
    """Verify an IaC-owned Helm release; no Helm/Kubernetes mutation calls."""
    from .kubernetes import forward
    t=r['target'];name=r['componentId'];env={'KUBECONFIG':ctx.get('kubeconfigPath','')}
    c.require(env['KUBECONFIG'],'iac-kubeconfig','trusted generated kubeconfig is required')
    owned=outputs.get('owned',{})
    c.require(owned=={'release':name,'namespace':t['namespace'],'owner_digest':ctx.get('iacOwnerDigest')},
        'iac-readiness-output','owned Helm release output differs')
    versions=c.command(ex,['kubectl','version','--output=json'],env=env)
    client,server=versions['clientVersion'],versions['serverVersion']
    c.require(client['major']==server['major'] and abs(int(client['minor'].rstrip('+'))-int(server['minor'].rstrip('+')))<=1,
        'client-skew','kubectl is outside the supported cluster skew')
    status=c.command(ex,['helm','status',name,'--namespace',t['namespace'],'--output','json'],env=env)
    c.require(status.get('name')==name and status.get('namespace')==t['namespace']
        and status.get('info',{}).get('status')=='deployed' and status['info'].get('description')==ctx['iacOwnerDigest'],
        'helm-owner','intended IaC-owned Helm release is not deployed')
    def owned_resource(resource):
        annotations=resource.get('metadata',{}).get('annotations',{})
        return annotations.get('meta.helm.sh/release-name')==name and annotations.get('meta.helm.sh/release-namespace')==t['namespace']
    deployment=c.command(ex,['kubectl','get','deployment',name,'--namespace',t['namespace'],'-o','json'],env=env)
    containers=deployment['spec']['template']['spec']['containers']
    c.require(owned_resource(deployment) and len(containers)==1 and containers[0]['image']==image
        and containers[0]['ports'][0]['containerPort']==r['workload']['port'],'intended-deployment','owned Deployment differs from immutable workload')
    for key in ('startupProbe','readinessProbe','livenessProbe'):
        c.require(containers[0].get(key,{}).get('httpGet',{}).get('path')==r['workload']['healthPath'],
            'intended-deployment','owned workload readiness path differs')
    revision=deployment['metadata']['annotations']['deployment.kubernetes.io/revision']
    c.require(isinstance(revision,str) and revision.isdigit(),'intended-deployment','Deployment revision is missing')
    c.command(ex,['kubectl','rollout','status','deployment/'+name,'--namespace',t['namespace'],
        '--timeout='+str(t['readiness']['deadlineSeconds'])+'s','--revision='+revision],json_output=False,env=env)
    service=c.command(ex,['kubectl','get','service',name,'--namespace',t['namespace'],'-o','json'],env=env)
    c.require(owned_resource(service) and service['metadata']['name']==name and service['spec']['ports'][0]['port']==r['workload']['port']
        and service['spec']['selector']=={'app.kubernetes.io/name':name},'intended-service','owned Service differs')
    with ctx.get('forward',forward)(ex,t['namespace'],name,r['workload']['port'],env) as base:
        c.serving(r,ex,ctx,base,allow_http=True)
    return None
