"""Actual Go -> private artifact renderer -> native provider-mocked fresh plans.

All 47 hosting/artifact variants use unchanged pinned roots. Provider responses
are native OpenTofu test doubles, not cloud execution or creation authorization.
The separate historical destroy matrix uses actual selected providers offline.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

import test_iac_historical_destroy as historical
from test_providers import request

ROOT=historical.ROOT
MODULES=historical.MODULES
BINARY=historical.BINARY
MODES=historical.MODES
merge=historical.merge
without_nulls=historical.without_nulls
sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from contracts import ContractError,_check,digest,schema,validate_artifact,validate_record
from iac import verify_saved_plan
from iac_values import ValuesError,render_values


@unittest.skipUnless(BINARY,'set TRONADOR_TEST_BINARY to the reviewed Go CLI')
class GoRootModeTests(unittest.TestCase):
    command=historical.HistoricalDestroyTests.command
    def operation(self,variables,module):
        resource=variables['resource'];kind=resource['kind']
        r=request(kind);target=merge(r['target'],merge(resource,variables['configuration']))
        target.update(id='prod-run',ownership='managed')
        if kind=='aws.apigateway-rest' and not resource.get('restApiId'):target.pop('restApiId',None)
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
        definition={'oneOf':[item for item in schema()['$defs']['Target']['oneOf'] if item['properties']['kind']['const']==kind]}
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
        return operation,context
    def artifact(self,variables,context,directory):
        specimen=variables['artifact'];component=context['plan']['components'][0]
        artifact={'kind':component['package']['kind'],'format':specimen['format'],
            'sourceSha':context['plan']['headSha'],'builtVersion':context['plan']['version'],
            'location':{'kind':'local','path':'.cloudopsworks/out/api/1.2.3/main.zip'}}
        payload=directory/'private-artifact';payload.mkdir(mode=0o700)
        reference=None
        if specimen['format']=='oci':
            corpus=Path(__file__).with_name('contracts')
            known=json.loads((corpus/'valid/oci-image-valid.json').read_text())['mainArtifact']
            artifact.update(digest=known['digest'],sizeBytes=known['sizeBytes'])
            path=payload/'main.oci.tar';shutil.copyfile(corpus/'artifacts/image.oci.tar',path)
            original=specimen.get('imageReference') or 'registry.example/component@sha256:'+'a'*64
            reference=original.rsplit('@',1)[0]+'@'+artifact['digest']
            artifact['location']={'kind':'oci','reference':reference}
        else:
            path=payload/'main.zip'
            if artifact['kind']=='static':
                if specimen['format']=='tar.gz':
                    path=payload/'main.tar.gz'
                    with tarfile.open(path,'w:gz') as archive:
                        for item in specimen['files']:
                            source=Path(item['path']);archive.add(source if source.is_absolute() else directory/source,arcname=item['key'])
                else:
                    with zipfile.ZipFile(path,'w') as archive:
                        for item in specimen['files']:
                            source=Path(item['path']);archive.write(source if source.is_absolute() else directory/source,item['key'])
                    artifact['format']='zip'
            else:
                source=Path(specimen['path'])
                shutil.copyfile(source if source.is_absolute() else directory/source,path)
                if artifact['kind']=='openapi':
                    artifact['format']='openapi-json' if specimen['format'] in ('json','openapi-json') else 'openapi-yaml'
            artifact.update(digest='sha256:'+hashlib.sha256(path.read_bytes()).hexdigest(),sizeBytes=path.stat().st_size)
        validate_artifact(path,artifact)
        return artifact,path,reference

    def native_plan(self,directory,text,mock,mode,values,*,failure=None):
        if isinstance(mock,dict):
            run=copy.deepcopy(mock['run'][mode]);run.pop('variables',None);run.pop('assert',None)
            run['command']='plan'
            document={'mock_provider':mock['mock_provider'],'variables':values,'run':{'go_rendered':run}}
            test=directory/'tests/rendered.tftest.json';test.write_text(json.dumps(document))
        else:
            run=historical.fixture_blocks(text,r'^run "'+re.escape(mode)+r'"\s*\{')[0]
            overrides='\n'.join(historical.fixture_blocks(run,r'^\s*override_(?:data|resource)\s*\{'))
            test=directory/'tests/rendered.tftest.hcl'
            test.write_text(mock+'\nvariables {\n'+'\n'.join(key+' = '+json.dumps(value) for key,value in values.items())+
                '\n}\nrun "go_rendered" {\n command = plan\n'+overrides+'\n}\n')
        result=subprocess.run(['tofu','test','-json','-verbose'],cwd=directory,env=self.env,capture_output=True,text=True,timeout=120)
        events=[json.loads(line) for line in result.stdout.splitlines()]
        if failure:
            self.assertNotEqual(result.returncode,0)
            diagnostics=[event.get('diagnostic',{}) for event in events]
            self.assertTrue(any(failure in item.get('detail','') for item in diagnostics),result.stdout+result.stderr)
            return None
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertFalse(any(event.get('diagnostic',{}).get('severity')=='error' for event in events))
        return next(event['test_plan'] for event in events if event.get('type')=='test_plan')

    def test_actual_go_rendered_fresh_plans_all_seventeen_families_and_forty_seven_modes(self):
        self.assertEqual(json.loads(subprocess.check_output(['tofu','version','-json']))['terraform_version'],'1.11.4')
        plugins=(ROOT/'terraform/monorepo/capabilities/.terraform/providers').resolve()
        self.assertTrue(plugins.is_dir())
        self.env={k:v for k,v in os.environ.items() if not k.startswith(('AWS_','GOOGLE_','CLOUDSDK_','ARM_','AZURE_','TF_VAR_','TF_CLI_','TF_LOG'))
            and k.lower() not in ('http_proxy','https_proxy','all_proxy','no_proxy') and k not in ('KUBECONFIG','DOCKER_CONFIG')}
        self.env.update(HTTPS_PROXY='http://127.0.0.1:9',HTTP_PROXY='http://127.0.0.1:9',ALL_PROXY='http://127.0.0.1:9',NO_PROXY='',AWS_EC2_METADATA_DISABLED='true',AWS_SHARED_CREDENTIALS_FILE='/dev/null',AWS_CONFIG_FILE='/dev/null')
        families=set();covered=set();negative=set()
        with tempfile.TemporaryDirectory(prefix='go-root-fresh-plans-') as temporary:
            home=Path(temporary)/'home';home.mkdir(mode=0o700)
            self.env.update(HOME=str(home),AZURE_CONFIG_DIR=str(home/'azure'),CLOUDSDK_CONFIG=str(home/'gcloud'))
            for module,selected in MODES.items():
                directory=Path(temporary)/module
                shutil.copytree(MODULES/module,directory,ignore=shutil.ignore_patterns('.terraform','*.tfstate*'))
                tests=list((directory/'tests').glob('*.tftest.*'));self.assertEqual(len(tests),1)
                test=tests[0]
                text=test.read_text().replace('../../../../tests/',str(ROOT/'tests')+'/').replace('"../../../../kubernetes/helm/charts"',json.dumps(str(ROOT/'kubernetes/helm/charts')))
                if test.suffix=='.json':
                    mock=json.loads(text)
                    for run in mock['run'].values():run.pop('assert',None);run['command']='plan'
                    harvest=json.dumps(mock)
                else:
                    mock=re.split(r'(?m)^(?:variables\s*\{|run\s)',text,maxsplit=1)[0]
                    harvest=text
                    for block in historical.fixture_blocks(text,r'^\s*assert\s*\{'):harvest=harvest.replace(block,'')
                    harvest=re.sub(r'(command\s*=\s*)apply',r'\1plan',harvest)
                test.write_text(harvest)
                self.command(directory,'init','-backend=false','-input=false','-lockfile=readonly',f'-plugin-dir={plugins}')
                events=[json.loads(line) for line in self.command(directory,'test','-json','-verbose').splitlines()]
                baselines={event['@testrun']:{item['address'] for item in event['test_plan'].get('resource_changes',[]) if item['mode']=='managed'} for event in events if event.get('type')=='test_plan'}
                cases={event['@testrun']:{key:item['value'] for key,item in event['test_plan']['variables'].items()} for event in events if event.get('type')=='test_plan'}
                test.unlink()
                metadata=json.loads((directory/'inputs.json').read_text())
                for mode in selected:
                    with self.subTest(module=module,mode=mode):
                        try:
                            variables=copy.deepcopy(cases[mode]);operation,context=self.operation(variables,module)
                            artifact,path,reference=self.artifact(variables,context,directory)
                            self.assertEqual(artifact['format'],{'json':'openapi-json','yaml':'openapi-yaml'}.get(variables['artifact']['format'],variables['artifact']['format']))
                            workspace=directory/'rendered';workspace.mkdir(mode=0o700)
                            kube=directory/'offline-kubeconfig'
                            kube.write_text('apiVersion: v1\nkind: Config\nclusters:\n- name: offline\n  cluster:\n    server: https://127.0.0.1:9\n    insecure-skip-tls-verify: true\ncontexts:\n- name: offline\n  context:\n    cluster: offline\n    user: offline\ncurrent-context: offline\nusers:\n- name: offline\n  user:\n    token: offline-test\n')
                            marker={'artifactDigest':artifact['digest'],'releaseVersion':artifact['builtVersion'],'idempotencyKey':digest({'componentId':'api','sourceSha':artifact['sourceSha'],'builtVersion':artifact['builtVersion']})}
                            values=render_values(operation,metadata,artifact,work=workspace,artifact_path=path,image_reference=reference,
                                package_handler=context['plan']['components'][0]['package'].get('entryPoint'),static_marker=marker,
                                chart_path=ROOT/'kubernetes/helm/charts',kubeconfig_path=kube,readiness_seconds=60,resolved_api=variables.get('resolved_api'))
                            self.assertEqual(values['owner_digest'],digest(operation['stateHandle']))
                            self.assertEqual(operation['stateHandle']['ownership'],'managed')
                            self.assertEqual(values['artifact']['digest'],artifact['digest'])
                            if reference:self.assertEqual(values['artifact']['imageReference'],reference)
                            if 'package_read_sas' in variables:values['package_read_sas']=variables['package_read_sas']  # protected credential boundary double only
                            plan=self.native_plan(directory,text,mock,mode,values)
                            self.assertEqual(plan['variables']['artifact']['value'],values['artifact'])
                            managed=[item for item in plan['resource_changes'] if item['mode']=='managed']
                            self.assertTrue(managed)
                            expected=baselines[mode]
                            if artifact['kind']=='static':
                                pattern=next(item for item in metadata['ownedResourceAddresses'] if item.endswith('[*]'))
                                expected={pattern[:-3]+'['+json.dumps(item['key'])+']' for item in values['artifact']['files']}
                            self.assertEqual({item['address'] for item in managed},expected)
                            for item in managed:
                                after=item['change']['after']
                                for field in ('tags','metadata','labels'):
                                    owner=(after.get(field) or {}).get('cloudopsworks-owner')
                                    if owner is not None:
                                        self.assertEqual(owner,digest(operation['stateHandle'])[7:47] if field=='labels' else digest(operation['stateHandle']))
                                if item['type']=='helm_release':self.assertEqual(after['description'],digest(operation['stateHandle']))
                            self.assertTrue(all(item['change']['actions']==['create'] for item in managed))
                            verify_saved_plan(plan,operation='apply',addresses=metadata['ownedResourceAddresses'],owner_digest=digest(operation['stateHandle']),previously_owned=set())
                            self.assertFalse(any(item['change'].get('importing') for item in managed))
                            families.add(operation['inputs']['resource']['kind']);covered.add((module,mode))
                            if module=='gcp-cloudrun':
                                bad=copy.deepcopy(context);bad.pop('historicalHandle',None);bad['plan']['components'][0]['workload']={'kind':'function'}
                                result=subprocess.run([BINARY,'components','operations','plan','--operation','apply','--environment','prod','--target','prod-run','--component','api','--json'],input=json.dumps(bad),capture_output=True,text=True,timeout=30)
                                self.assertNotEqual(result.returncode,0);negative.add('go-workload')
                                bad_values=copy.deepcopy(values);bad_values['artifact']['format']='zip'
                                self.native_plan(directory,text,mock,mode,bad_values,failure='Cloud Run requires the exact verified OCI digest.')
                                negative.add('native-artifact-precondition')
                                wrong_reference=workspace/'negative-image';wrong_reference.mkdir(mode=0o700)
                                with self.assertRaises(ValuesError):
                                    render_values(operation,metadata,artifact,work=wrong_reference,image_reference=reference.rsplit('@',1)[0]+'@sha256:'+'0'*64)
                                negative.add('immutable-reference')
                            if module=='azure-appservice' and mode=='linux_production_zip':
                                bad_variables=copy.deepcopy(variables);bad_variables['configuration']['runtime']='COBOL|999'
                                bad_operation,_=self.operation(bad_variables,module)
                                bad_workspace=workspace/'negative-runtime';bad_workspace.mkdir(mode=0o700)
                                bad_values=render_values(bad_operation,metadata,artifact,work=bad_workspace,artifact_path=path,package_handler=context['plan']['components'][0]['package'].get('entryPoint'))
                                bad_values['package_read_sas']=variables['package_read_sas']
                                self.native_plan(directory,text,mock,mode,bad_values,failure='Package mode/OS or immutable artifact mismatch.')
                                negative.add('go-runtime-native-precondition')
                                corrupt=directory/'private-artifact/corrupt.zip';corrupt.write_bytes(path.read_bytes()+b'tamper')
                                bad_workspace=workspace/'negative-bytes';bad_workspace.mkdir(mode=0o700)
                                with self.assertRaises((ContractError,ValuesError)):
                                    render_values(operation,metadata,artifact,work=bad_workspace,artifact_path=corrupt)
                                negative.add('immutable-payload')
                        finally:
                            for name in ('rendered','private-artifact'):shutil.rmtree(directory/name,ignore_errors=True)
                            for name in ('rendered.tftest.json','rendered.tftest.hcl'):(directory/'tests'/name).unlink(missing_ok=True)
            self.assertEqual(len(families),17)
            self.assertEqual(covered,{(module,mode) for module,modes in MODES.items() for mode in modes})
            self.assertEqual(len(covered),47)
            self.assertEqual(negative,{'go-workload','native-artifact-precondition','go-runtime-native-precondition','immutable-reference','immutable-payload'})


if __name__=='__main__':unittest.main()
