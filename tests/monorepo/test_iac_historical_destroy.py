"""Historical destroy evaluation against concrete pinned roots, without payloads.

Prior states come from native provider-mocked Apply, never cloud Apply. Destroy
plans use the selected REAL provider with refresh disabled, synthetic priorstate,
test-only native credential protocol doubles and blocked network. No production
activation or independently proved historical GitHub provenance claim.
"""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from contracts import digest,validate_record,_check,schema
from iac import verify_saved_plan
from iac_values import recovery_values
from test_providers import request

MODULES=ROOT/'terraform/monorepo/modules'
BINARY=os.environ.get('TRONADOR_TEST_BINARY')
MODES={
 'aws-lambda':['zip_digest_and_optional_alias','image_exact_private_ecr_digest'],
 'aws-beanstalk':['owned_mock_apply','immutable_dockerrun_zip'],
 'aws-s3-static':['owned_mock_apply'],
 'aws-apigateway-rest':['owned_mock_apply','existing_owned_id_preserves_verified_name_description','native_json_openapi_exact_body'],
 'gcp-cloudrun':['oci'],
 'gcp-appengine':['standard_native','flex_native','flex_oci','standard_basic','standard_automatic'],
 'gcp-functions-gen2':['http','pubsub','storage_finalize'],
 'gcp-storage-static':['objectset','static_zip'],
 'gcp-apigateway':['openapi','openapi_json'],
 'azure-containerapps':['digest_revision'],
 'azure-appservice':['linux_production_zip','linux_production_container','linux_staging_zip','linux_staging_container','windows_production_zip','windows_staging_zip'],
 'azure-functions':['linux_production_zip','linux_production_container','linux_staging_zip','linux_staging_container','windows_production_zip','windows_staging_zip','flex_zip','dedicated_linux_production_zip','dedicated_linux_production_container','dedicated_linux_staging_zip','dedicated_linux_staging_container','dedicated_windows_production_zip','dedicated_windows_staging_zip','native_custom_handler'],
 'azure-blob-static':['prefix_bound'],
 'azure-apim':['api_exact_digest'],
 'kubernetes-component':['eks_immutable_release','gke','aks'],
}


def merge(first,second):
    result=copy.deepcopy(first)
    for key,value in second.items():
        result[key]=merge(result[key],value) if isinstance(value,dict) and isinstance(result.get(key),dict) else copy.deepcopy(value)
    return result


def without_nulls(value):
    if isinstance(value,dict):return {key:without_nulls(item) for key,item in value.items() if item is not None}
    if isinstance(value,list):return [without_nulls(item) for item in value]
    return value


def fixture_blocks(text,pattern):
    """Select balanced native fixture blocks without parsing/executing HCL."""
    result=[]
    for match in re.finditer(pattern,text,re.M):
        opening=text.index('{',match.start());depth=0;quoted=False;escaped=False
        for index in range(opening,len(text)):
            char=text[index]
            if quoted:
                if escaped:escaped=False
                elif char=='\\':escaped=True
                elif char=='"':quoted=False
            elif char=='"':quoted=True
            elif char=='{':depth+=1
            elif char=='}':
                depth-=1
                if depth==0:
                    result.append(text[match.start():index+1]);break
    return result


def native_state(view):
    records={}
    for resource in view['values']['root_module']['resources']:
        key=(resource['mode'],resource['type'],resource['name'])
        record=records.setdefault(key,{'mode':key[0],'type':key[1],'name':key[2],
            'provider':'provider["'+resource['provider_name']+'"]','instances':[]})
        instance={'schema_version':resource['schema_version'],'attributes':resource['values'],'sensitive_attributes':[]}
        if '[' in resource['address']:
            instance['index_key']=json.loads(resource['address'].split('[',1)[1][:-1])
        record['instances'].append(instance)
    return {'version':4,'terraform_version':'1.11.4','serial':1,'lineage':'00000000-0000-0000-0000-000000000001',
            'outputs':{},'resources':list(records.values())}


@unittest.skipUnless(BINARY,'set TRONADOR_TEST_BINARY to the reviewed Go CLI')
class HistoricalDestroyTests(unittest.TestCase):
    def command(self,directory,*args):
        result=subprocess.run(['tofu',*args],cwd=directory,env=self.env,text=True,capture_output=True,timeout=120)
        self.assertEqual(result.returncode,0,str(directory.name)+' '+str(args)+'\n'+result.stdout+'\n'+result.stderr)
        return result.stdout
    def go_inputs(self,variables,module):
        resource=variables['resource'];kind=resource['kind']
        r=request(kind);target=merge(r['target'],merge(resource,variables['configuration']))
        target.update(id='prod-run',ownership='managed')
        target.pop('architecture',None)
        if kind=='gcp.appengine':
            target['appConfig']='app.yaml'
            target['appConfigResolved']=variables['configuration']['appConfig']
        if kind=='gcp.functions-gen2' and 'eventSource' in target:
            event=target.pop('eventSource')
            target['readiness']['probe']=dict(kind='gcp-eventarc',source=event['source'],resource=event['resource'],requestBody='{}',successLogMarker='ready')
        if kind in ('gcp.apigateway','azure.apim'):target.setdefault('apiVersion','1.0')
        context=json.loads((Path(__file__).with_name('fixtures')/'operations/operation-context-frozen.json').read_text())
        target=without_nulls(target)
        if kind=='aws.lambda':target.setdefault('alias',None)
        if kind=='gcp.functions-gen2' and target['trigger']['kind']=='http':target['trigger']['value']='http'
        if kind=='gcp.appengine':
            config=target['appConfigResolved']
            for key in ('entrypoint','instanceClass','runtimeConfig','scaling'):config.setdefault(key,None)
            scaling=config['scaling']
            if scaling:
                required={'manual':('instances',),'basic':('maxInstances','idleTimeout'),
                    'automatic':('minInstances','maxInstances','minIdleInstances','maxIdleInstances','targetCpuUtilization','targetThroughputUtilization','maxConcurrentRequests','minPendingLatency','maxPendingLatency')}
                for key in required[scaling['kind']]:scaling.setdefault(key,None)
        context['plan']['targets']=[target]
        component=context['plan']['components'][0]
        component.update(package=r['package'],workload=r['workload'])
        if component['workload']['kind']=='http':component['workload'].update({k:v for k,v in variables.get('workload',{}).items() if k in ('port','healthPath')})
        if kind=='aws.lambda':component['package'].update(architecture=resource.get('architecture','amd64'),runtime=variables['configuration'].get('runtime') or component['package']['runtime'],entryPoint=variables.get('package_handler') or component['package']['entryPoint'])
        package=component['package']
        if ((kind=='azure.appservice' and target.get('packageMode')=='container')
                or (kind=='gcp.appengine' and variables['artifact']['format']=='oci')):
            component['package']=dict(kind='container',dockerfile='Dockerfile',context='.',platform='linux/amd64');package=component['package']
        if package['kind']=='function':
            if variables['configuration'].get('runtime'):package['runtime']=variables['configuration']['runtime']
            if variables['configuration'].get('iac',{}).get('entryPoint'):package['entryPoint']=variables['configuration']['iac']['entryPoint']
            if kind=='gcp.functions-gen2':package['mode']='gcp-gen2'
            else:package['mode']={'aws.lambda':'aws-','azure.functions':'azure-'}[kind]+target['packageMode']
            component['preview']=dict(mode='container',source='function',dockerfile='Dockerfile',context='.',adapter='handler-http',entryPoint=package['entryPoint'],port=8080,healthPath='/health',invokePath='/invoke',invokeTest={'requestBody':'{}','expectedStatus':200,'responseContains':'ready'})
        elif package['kind']=='archive':component['preview']=dict(mode='container',source='dockerfile',dockerfile='Dockerfile',context='.',port=8080,healthPath='/health')
        elif package['kind']=='static':component['preview']=dict(mode='container',source='static',port=8080,healthPath='/health')
        elif package['kind']=='openapi':component['preview']={'mode':'artifact-only','reason':'openapi'}
        context['plan']['components']=[component]
        context['providerIdentity']={'aws':'123456789012','gcp':'123456789','azure':resource.get('subscriptionId','00000000-0000-0000-0000-000000000001')}[target['provider']]
        context['backend']['authRef']='aws-state';context['backendIdentity']={'provider':'aws','accountId':'999999999999'}
        context['authRefs']=sorted({target['authRef'],'aws-state'})
        catalog=json.loads((ROOT/'terraform/monorepo/module-catalog.json').read_text())
        row=catalog['modules'][{'aws.eks':'aws-eks','gcp.gke':'gcp-gke','azure.aks':'azure-aks'}.get(kind,module)]
        context['origin'].update(moduleRevision=row['revision'],providerLockDigest=row['providerLockDigest'])
        definition=next(item for item in schema()['$defs']['Target']['oneOf'] if item['properties']['kind']['const']==kind)
        _check(target,definition,'$.target')
        _check(component,schema()['$defs']['Component'],'$.component')
        _check(context['plan'],{'$ref':'#/$defs/BuildPlan'},'$')
        validate_record(context['plan'])
        output=subprocess.run([BINARY,'components','operations','plan','--operation','apply','--environment','prod','--target','prod-run','--component','api','--json'],input=json.dumps(context),capture_output=True,text=True,timeout=30)
        self.assertEqual(output.returncode,0,kind+' sole-Go historical inputs: '+output.stderr)
        operation=json.loads(output.stdout)
        context['historicalHandle']=operation['stateHandle']
        historical=subprocess.run([BINARY,'components','operations','plan','--operation','apply','--environment','prod','--target','prod-run','--component','api','--json'],input=json.dumps(context),capture_output=True,text=True,timeout=30)
        self.assertEqual(historical.returncode,0,kind+' sole-Go historical regeneration: '+historical.stderr)
        regenerated=json.loads(historical.stdout)
        self.assertEqual(regenerated['stateHandle'],operation['stateHandle'])
        self.assertEqual(regenerated['inputs'],operation['inputs'])
        self.assertEqual(operation['inputs']['resource'],operation['stateHandle']['resourceIdentity'])
        return operation['inputs'],operation['stateHandle'],component['package'].get('entryPoint')
    def offline_provider(self,module):
        if module.startswith('aws-'):
            return 'provider "aws" {\n access_key="offline-not-a-credential"\n secret_key="offline-not-a-credential"\n skip_credentials_validation=true\n skip_requesting_account_id=true\n skip_metadata_api_check=true\n skip_region_validation=true\n}\n'
        if module.startswith('gcp-'):return 'provider "'+('google-beta' if module=='gcp-apigateway' else 'google')+'" { access_token="offline-not-a-credential" }\n'
        if module.startswith('azure-'):
            return 'provider "azurerm" {\n tenant_id="22222222-2222-2222-2222-222222222222"\n use_cli=true\n use_oidc=false\n}\n'
        return ''
    def fake_azure_auth(self,home):
        # Selected v4.66.0 sources: internal/clients/auth.go and vendored
        # go-azure-sdk/sdk/{auth/azure_cli_authorizer.go,internal/azurecli/azcli.go}.
        # ONLY the native provider's credential acquisition is doubled. No ARM
        # operations, SDK, provider replacement or production auth fallback.
        account={'id':'00000000-0000-0000-0000-000000000001',
            'tenantId':'22222222-2222-2222-2222-222222222222',
            'user':{'type':'servicePrincipal','name':'offline-fixture'}}
        claims={'tid':account['tenantId'],'oid':'33333333-3333-3333-3333-333333333333',
            'appid':'11111111-1111-1111-1111-111111111111','exp':4102444800}
        encode=lambda value:base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')
        token=encode({'alg':'none'})+'.'+encode(claims)+'.'
        responses={'version':{'azure-cli':'2.90.0'},'account show':account,'account list':[account],
            'account get-access-token':{'accessToken':token,'tokenType':'Bearer','expiresOn':'2099-01-01 00:00:00.000000'}}
        binary=home/'bin';binary.mkdir(mode=0o700);az=binary/'az'
        az.write_text('#!'+sys.executable+'\nimport json,sys\nr='+repr(responses)+
            '\na=sys.argv[1:]\nkey=a[0] if a and a[0]=="version" else " ".join(a[:2])\n'+
            'if key not in r:sys.exit(91)\nprint(json.dumps(r[key]))\n')
        az.chmod(0o700)
        self.env.update(PATH=str(binary)+os.pathsep+self.env['PATH'],ARM_PROVIDER_ENHANCED_VALIDATION='false')

    def test_all_seventeen_families_and_historical_modes_have_pure_native_destroy_plans(self):
        self.assertEqual(json.loads(subprocess.check_output(['tofu','version','-json']))['terraform_version'],'1.11.4')
        plugins=(ROOT/'terraform/monorepo/capabilities/.terraform/providers').resolve()
        self.assertTrue(plugins.is_dir())
        self.env={k:v for k,v in os.environ.items() if not k.startswith(('AWS_','GOOGLE_','CLOUDSDK_','ARM_','AZURE_','TF_VAR_','TF_CLI_','TF_LOG'))}
        self.env={k:v for k,v in self.env.items() if k.lower() not in ('http_proxy','https_proxy','all_proxy','no_proxy') and k not in ('KUBECONFIG','DOCKER_CONFIG')}
        self.env.update(HTTPS_PROXY='http://127.0.0.1:9',HTTP_PROXY='http://127.0.0.1:9',ALL_PROXY='http://127.0.0.1:9',NO_PROXY='',AWS_EC2_METADATA_DISABLED='true',AWS_SHARED_CREDENTIALS_FILE='/dev/null',AWS_CONFIG_FILE='/dev/null')
        families=set();modes=0
        with tempfile.TemporaryDirectory(prefix='historical-native-destroy-') as temporary:
            home=Path(temporary)/'private-home';home.mkdir(mode=0o700)
            self.env.update(HOME=str(home),CLOUDSDK_CONFIG=str(home/'gcloud'),AZURE_CONFIG_DIR=str(home/'azure'))
            self.fake_azure_auth(home)
            for module,selected in MODES.items():
                directory=Path(temporary)/module
                shutil.copytree(MODULES/module,directory,ignore=shutil.ignore_patterns('.terraform','*.tfstate*'))
                tests=list((directory/'tests').glob('*.tftest.*'));self.assertEqual(len(tests),1)
                test=tests[0]
                text=test.read_text().replace('../../../../tests/',str(ROOT/'tests')+'/').replace('"../../../../kubernetes/helm/charts"',json.dumps(str(ROOT/'kubernetes/helm/charts')))
                test.write_text(text)
                self.command(directory,'init','-backend=false','-input=false','-lockfile=readonly',f'-plugin-dir={plugins}')
                events=[json.loads(line) for line in self.command(directory,'test','-json','-verbose').splitlines()]
                cases={event['@testrun']:{key:item['value'] for key,item in event['test_plan']['variables'].items()} for event in events if event.get('type')=='test_plan'}
                if test.suffix=='.json':
                    doc=json.loads(text);mock={'mock_provider':doc['mock_provider']}
                    for name in selected:
                        if name not in cases:cases[name]=merge(doc['variables'],doc['run'][name].get('variables',{}))
                else:mock=re.split(r'(?m)^(?:variables\s*\{|run\s)',text,maxsplit=1)[0]
                test.unlink()
                for mode in selected:
                    with self.subTest(module=module,mode=mode):
                        try:
                            variables=copy.deepcopy(cases[mode])
                            inputs,handle,handler=self.go_inputs(variables,module)
                            variables['owner_digest']=digest(handle)
                            payloads=directory/'prior-payloads';payloads.mkdir(mode=0o700)
                            artifact=variables['artifact']
                            for index,item in enumerate(artifact.get('files',[]) if inputs['workload']['kind']=='static' else [artifact]):
                                old=item.get('path')
                                if old:
                                    source=Path(old) if Path(old).is_absolute() else directory/old
                                    destination=payloads/str(index);shutil.copyfile(source,destination)
                                    item['path']=str(destination)
                            if inputs['workload']['kind']=='static':
                                archive=payloads/'static.zip'
                                with zipfile.ZipFile(archive,'w') as bundle:
                                    for item in artifact['files']:bundle.write(item['path'],item['key'])
                                artifact.update(path=str(archive),format='zip',digest='sha256:'+hashlib.sha256(archive.read_bytes()).hexdigest())
                            if isinstance(mock,dict):
                                prior={**mock,'variables':variables,'run':{'historical_prior':dict(doc['run'][mode],command='apply')}}
                                prior['run']['historical_prior'].pop('variables',None)
                                prior['run']['historical_prior'].pop('assert',None)
                                native_test=directory/'tests/historical.tftest.json';native_test.write_text(json.dumps(prior))
                            else:
                                native_test=directory/'tests/historical.tftest.hcl'
                                run=fixture_blocks(text,r'^run "'+re.escape(mode)+r'"\s*\{')[0]
                                overrides='\n'.join(fixture_blocks(run,r'^\s*override_(?:data|resource)\s*\{'))
                                native_test.write_text(mock+'\nvariables {\n'+'\n'.join(key+' = '+json.dumps(value) for key,value in variables.items())+'\n}\nrun "historical_prior" {\n command = apply\n'+overrides+'\n}\n')
                            events=[json.loads(line) for line in self.command(directory,'test','-json','-verbose').splitlines()]
                            view=next(event['test_state'] for event in events if event.get('type')=='test_state')
                            state=native_state(view)
                            shutil.rmtree(payloads)  # original artifact is expired/unavailable before rendering
                            previous={resource['address'] for resource in view['values']['root_module']['resources'] if resource['mode']=='managed'}
                            self.assertTrue(previous)
                            scaffold=directory/'evaluation';scaffold.mkdir(mode=0o700)
                            kube=directory/'offline-kubeconfig'
                            kube.write_text('apiVersion: v1\nkind: Config\nclusters:\n- name: offline\n  cluster:\n    server: https://127.0.0.1:9\n    insecure-skip-tls-verify: true\ncontexts:\n- name: offline\n  context:\n    cluster: offline\n    user: offline\ncurrent-context: offline\nusers:\n- name: offline\n  user:\n    token: offline-not-a-credential\n')
                            metadata=json.loads((directory/'inputs.json').read_text())
                            values=recovery_values(inputs,metadata,handle,state,work=scaffold,package_handler=handler,
                                chart_path=ROOT/'kubernetes/helm/charts',kubeconfig_path=kube,
                                resolved_api=variables.get('resolved_api'))
                            self.assertEqual(values['artifact'].get('files',[]),[])
                            self.assertEqual(values['owner_digest'],digest(handle))
                            if values['artifact'].get('path'):
                                self.assertTrue(Path(values['artifact']['path']).is_relative_to(scaffold.resolve()))
                            self.assertFalse(payloads.exists())
                            (directory/'recovery.auto.tfvars.json').write_text(json.dumps(values))
                            (directory/'terraform.tfstate').write_text(json.dumps(state))
                            (directory/'offline_override.tf').write_text(self.offline_provider(module))
                            self.command(directory,'plan','-destroy','-refresh=false','-input=false','-lock=false','-out=destroy.plan')
                            plan=json.loads(self.command(directory,'show','-json','destroy.plan'))
                            changes={item['address']:item['change']['actions'] for item in plan.get('resource_changes',[]) if item['mode']=='managed'}
                            self.assertEqual(changes,{address:['delete'] for address in previous})
                            verify_saved_plan(plan,operation='destroy',addresses=metadata['ownedResourceAddresses'],owner_digest=digest(handle),previously_owned=previous)
                            families.add(inputs['resource']['kind']);modes+=1
                        finally:
                            for path in (directory/'recovery.auto.tfvars.json',directory/'terraform.tfstate',directory/'terraform.tfstate.backup',directory/'offline_override.tf',directory/'destroy.plan',directory/'tests/historical.tftest.json',directory/'tests/historical.tftest.hcl'):
                                path.unlink(missing_ok=True)
                            shutil.rmtree(directory/'evaluation',ignore_errors=True)
                            shutil.rmtree(directory/'prior-payloads',ignore_errors=True)
            self.assertEqual(len(families),17)
            self.assertEqual(modes,sum(map(len,MODES.values())))


if __name__=='__main__':unittest.main()
