"""Small LOCAL fixture adapter: native test inputs -> real CLI -> native test plan.

No production runtime import, validation implementation or deployment execution.
Native fixture selection is the explicit test-only YAML inventory.
"""
import copy
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

BP = Path(__file__).resolve().parents[3]
CLI_SOURCE = BP.parent/'tronador-cli-v511/internal/components'
CATALOG = BP/'terraform/monorepo/module-catalog.yaml'
PLUGINS = BP/'terraform/monorepo/capabilities/.terraform/providers'


def command(argv, *, env=None, cwd=None, data=None):
    result = subprocess.run(argv, cwd=cwd, env=env, input=json.dumps(data) if data is not None else None,
                            text=True, capture_output=True, timeout=120, check=False)
    if result.returncode:
        raise AssertionError(f'{argv}: exit {result.returncode}\n{result.stdout[-5000:]}\n{result.stderr[-5000:]}')
    return result.stdout


def yaml_data(path):
    return json.loads(command(['yq', '-o=json', '-I=0', '.', str(path)]))


def blocks(text, pattern):
    """Copy balanced literal HCL test blocks, without evaluating/parsing HCL."""
    result = []
    for match in re.finditer(pattern, text, re.M):
        start = text.index('{', match.start()); depth = 0; quoted = escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if quoted:
                if escaped: escaped = False
                elif char == '\\': escaped = True
                elif char == '"': quoted = False
            elif char == '"': quoted = True
            elif char == '{': depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    result.append(text[match.start():index+1]); break
    return result


def merge(first, second):
    result = copy.deepcopy(first)
    for key, value in second.items():
        result[key] = merge(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else copy.deepcopy(value)
    return result


def nonnull(value):
    if isinstance(value, dict): return {key: nonnull(item) for key, item in value.items() if item is not None}
    if isinstance(value, list): return [nonnull(item) for item in value]
    return value


def remove_private_payloads(root, candidates):
    """Expire real local fixture bytes; nonexistent unused placeholders are not payloads."""
    selected = []
    for value in candidates:
        if not value:
            continue
        path = Path(value)
        path = path if path.is_absolute() else root/path
        if not path.is_relative_to(root) or path.is_symlink() or path.resolve() != path.absolute():
            raise AssertionError('Payload removal must stay within a real private path')
        if not path.exists():
            continue
        if not path.is_file():
            raise AssertionError('Payload removal requires a regular file')
        if path not in selected:
            selected.append(path)
    for path in selected:
        path.unlink()
    return selected


class NativeFixture:
    def __init__(self, root, binary, cases):
        self.root, self.binary, self.cases = root, binary, cases
        self.catalog = yaml_data(CATALOG)['modules']
        self.cache = {}
        home = root/'home'; home.mkdir(mode=0o700)
        self.env = {'PATH': os.environ.get('PATH', ''), 'HOME': str(home), 'CHECKPOINT_DISABLE': '1',
            'HTTPS_PROXY': 'http://127.0.0.1:9', 'HTTP_PROXY': 'http://127.0.0.1:9',
            'ALL_PROXY': 'http://127.0.0.1:9', 'NO_PROXY': '', 'AWS_EC2_METADATA_DISABLED': 'true',
            'AWS_SHARED_CREDENTIALS_FILE': '/dev/null', 'AWS_CONFIG_FILE': '/dev/null',
            'TF_IN_AUTOMATION': 'true', 'AZURE_CONFIG_DIR': str(home/'azure'), 'CLOUDSDK_CONFIG': str(home/'gcloud')}
        self.targets = json.loads((CLI_SOURCE/'schema/monorepo-v1.schema.json').read_text())['$defs']['Target']['oneOf']

    def cli(self, args, data=None):
        return json.loads(command([self.binary, 'components', *args, '--json'], data=data, cwd=self.root, env=self.env))

    def private(self, directory, name, value):
        path = directory/name; path.write_text(json.dumps(value)); path.chmod(0o600); return path

    def harvest(self, root_name):
        if root_name in self.cache: return self.cache[root_name]
        source = BP/'terraform/monorepo/modules'/root_name
        directory = self.root/('native-'+root_name)
        shutil.copytree(source, directory, ignore=shutil.ignore_patterns('.terraform', '*.tfstate*'))
        tests = list((directory/'tests').glob('*.tftest.*'))
        if len(tests) != 1: raise AssertionError(f'{root_name}: expected one native fixture')
        path = tests[0]
        text = path.read_text().replace('../../../../tests/', str(BP/'tests')+'/').replace('"../../../../kubernetes/helm/charts"', json.dumps(str(BP/'kubernetes/helm/charts')))
        selected = [row['case'] for row in self.cases if row['root'] == root_name]
        if path.suffix == '.json':
            original = json.loads(text)
            runs = {name: copy.deepcopy(original['run'][name]) for name in selected}
            for run in runs.values(): run.pop('assert', None); run['command'] = 'plan'
            document = dict(original, run=runs)
            path.write_text(json.dumps(document))
        else:
            prefix = re.split(r'(?m)^run\s', text, maxsplit=1)[0]
            selected_blocks = []
            for name in selected:
                run = blocks(text, '^run "'+re.escape(name)+'"\\s*\\{')[0]
                for assertion in blocks(run, r'^\s*assert\s*\{'): run = run.replace(assertion, '')
                selected_blocks.append(re.sub(r'(command\s*=\s*)apply', r'\1plan', run))
            path.write_text(prefix+'\n'+'\n'.join(selected_blocks))
            original = text
        command(['tofu', 'init', '-backend=false', '-input=false', '-lockfile=readonly', f'-plugin-dir={PLUGINS}'], cwd=directory, env=self.env)
        events = [json.loads(line) for line in command(['tofu', 'test', '-json', '-verbose'], cwd=directory, env=self.env).splitlines()]
        plans = {event['@testrun']: event['test_plan'] for event in events if event.get('type') == 'test_plan'}
        if set(plans) != set(selected): raise AssertionError(f'{root_name}: missing native cases {set(selected)-set(plans)}')
        path.unlink()
        result = (directory, original, plans)
        self.cache[root_name] = result
        return result

    def context(self, variables, row):
        resource = variables['resource']; kind = resource['kind']; provider = kind.split('.')[0]
        # Fixture defaults only. The actual CLI, not this adapter, validates them.
        defaults = dict(id='prod-run', environment='prod', provider=provider, authRef='prod', configDigest='sha256:'+'c'*64,
            kind=kind, region='us-central1', cluster='cluster', namespace='apps', application='app', environmentName='env',
            bucket='bucket', prefix='site', functionName='handler', packageMode='zip', alias=None, restApiId='api', stage='prod',
            project='project', service='api', serviceAccount='runtime@project.iam.gserviceaccount.com', location='us-central1',
            appConfig='app.yaml', trigger={'kind':'http','value':'http'}, api='api', gateway='gateway', backendServiceAccount='backend@project.iam.gserviceaccount.com',
            subscriptionId='00000000-0000-0000-0000-000000000001', resourceGroup='rg', appName='app', containerName='app', slot='production', hostingPlan='premium', workerRuntime='python', account='storage', container='$web', serviceName='gateway', apiId='api', apiPath='api')
        definition = next(item for item in self.targets if item['properties']['kind']['const'] == kind)
        target = {key: defaults[key] for key in definition['required'] if key != 'readiness'}
        target = nonnull(merge(target, merge(resource, variables['configuration'])))
        target.update(id='prod-run', environment='prod', ownership='managed')
        target.pop('architecture', None)
        if kind == 'aws.apigateway-rest' and not resource.get('restApiId'): target.pop('restApiId', None)
        if provider == 'aws': target['region'] = resource.get('region', 'us-east-1')
        probe = dict(kind='http', path='/ready', method='GET', requestBody='', expectedStatus=200, responseContains='ready', auth={'kind':'none'})
        pkg = dict(kind='container', dockerfile='Dockerfile', context='.', platform='linux/amd64')
        workload = dict(kind='http', port=8080, healthPath='/health')
        if kind in ('aws.s3-static', 'gcp.storage-static', 'azure.blob-static'):
            pkg = dict(kind='static', directory='dist', index='index.html'); workload = {'kind':'static'}
            probe = dict(kind='static-http', path='/index.html')
        elif kind in ('aws.apigateway-rest', 'gcp.apigateway', 'azure.apim'):
            pkg = dict(kind='openapi', file='openapi.json', version='3.0'); workload = {'kind':'api'}
            if kind in ('gcp.apigateway', 'azure.apim'): target.setdefault('apiVersion', '1.0')
        elif kind in ('aws.lambda', 'gcp.functions-gen2', 'azure.functions'):
            pkg = dict(kind='function', provider=provider, mode={'aws':'aws-zip','gcp':'gcp-gen2','azure':'azure-zip'}[provider], runtime='python312', entryPoint='handler', architecture='amd64', source='src')
            workload = {'kind':'function'}
            pkg.update(runtime=variables['configuration'].get('runtime') or pkg['runtime'], entryPoint=variables.get('package_handler') or variables['configuration'].get('iac', {}).get('entryPoint') or pkg['entryPoint'])
            if provider != 'gcp': pkg['mode'] = provider+'-'+target['packageMode']
            if provider == 'aws':
                target.setdefault('alias', None)
                pkg['architecture'] = resource.get('architecture', 'amd64')
                probe = dict(kind='lambda-invoke', requestBody='{}', responseContains='ready')
        elif kind in ('aws.beanstalk', 'gcp.appengine', 'azure.appservice'):
            pkg = dict(kind='archive', format='zip', include=['app.yaml'])
        if variables['artifact']['format'] == 'oci' and pkg['kind'] == 'archive':
            pkg = dict(kind='container', dockerfile='Dockerfile', context='.', platform='linux/amd64')
        if kind == 'gcp.appengine':
            config = variables['configuration']['appConfig']; target.update(appConfig='app.yaml', appConfigResolved=copy.deepcopy(config))
            for key in ('entrypoint','instanceClass','runtimeConfig','scaling'): target['appConfigResolved'].setdefault(key, None)
            scaling = target['appConfigResolved']['scaling']
            if scaling:
                keys = {'manual':('instances',), 'basic':('maxInstances','idleTimeout'), 'automatic':('minInstances','maxInstances','minIdleInstances','maxIdleInstances','targetCpuUtilization','targetThroughputUtilization','maxConcurrentRequests','minPendingLatency','maxPendingLatency')}[scaling['kind']]
                for key in keys: scaling.setdefault(key, None)
        if kind == 'gcp.functions-gen2' and 'eventSource' in target:
            event = target.pop('eventSource'); probe = dict(kind='gcp-eventarc', source=event['source'], resource=event['resource'], requestBody='{}', successLogMarker='ready')
        if kind == 'gcp.functions-gen2' and target['trigger']['kind'] == 'http': target['trigger']['value'] = 'http'
        target['readiness'] = dict(deadlineSeconds=30, intervalSeconds=1, probe=probe)
        context = json.loads((CLI_SOURCE/'testdata/operations/operation-context-frozen.json').read_text())
        component = context['plan']['components'][0]
        component.update(package=pkg, workload=workload)
        if workload['kind'] == 'http': workload.update({key: variables.get('workload', {}).get(key, value) for key, value in workload.items()})
        if pkg['kind'] == 'function':
            component['preview'] = dict(mode='container', source='function', dockerfile='Dockerfile', context='.', adapter='handler-http', entryPoint=pkg['entryPoint'], port=8080, healthPath='/health', invokePath='/invoke', invokeTest={'requestBody':'{}','expectedStatus':200,'responseContains':'ready'})
        elif pkg['kind'] == 'archive': component['preview'] = dict(mode='container', source='dockerfile', dockerfile='Dockerfile', context='.', port=8080, healthPath='/health')
        elif pkg['kind'] == 'static': component['preview'] = dict(mode='container', source='static', port=8080, healthPath='/health')
        elif pkg['kind'] == 'openapi': component['preview'] = {'mode':'artifact-only','reason':'openapi'}
        context['plan']['targets'] = [target]
        context['providerIdentity'] = {'aws':'123456789012','gcp':'123456789','azure':defaults['subscriptionId']}[provider]
        context['backend']['authRef'] = 'aws-state'; context['backendIdentity'] = {'provider':'aws','accountId':'999999999999'}
        context['authRefs'] = sorted({target['authRef'], 'aws-state'})
        binding = self.catalog[row['family']]
        context['origin'].update(moduleRevision=binding['revision'], providerLockDigest=binding['providerLockDigest'])
        return context

    def artifact(self, variables, context, directory, source_root):
        specimen = variables['artifact']; component = context['plan']['components'][0]
        artifact = dict(kind=component['package']['kind'], format=specimen['format'], sourceSha=context['plan']['headSha'], builtVersion=context['plan']['version'])
        if specimen['format'] == 'oci':
            known = json.loads((BP/'tests/monorepo/contracts/valid/oci-image-valid.json').read_text())['mainArtifact']
            original = specimen.get('imageReference') or 'registry.example/component@sha256:'+'a'*64
            artifact.update(digest=known['digest'], sizeBytes=known['sizeBytes'], location={'kind':'oci','reference':original.rsplit('@',1)[0]+'@'+known['digest']})
            return artifact, None
        payload = directory/'original-payload.zip'
        if artifact['kind'] == 'static':
            with zipfile.ZipFile(payload, 'w') as archive:
                for item in specimen['files']:
                    source = Path(item['path'])
                    archive.write(source if source.is_absolute() else source_root/source, item['key'])
            artifact['format'] = 'zip'
        else:
            original = Path(specimen['path'])
            shutil.copyfile(original if original.is_absolute() else source_root/original, payload)
            if artifact['kind'] == 'openapi': artifact['format'] = 'openapi-json' if specimen['format'] in ('json','openapi-json') else 'openapi-yaml'
        artifact.update(digest='sha256:'+hashlib.sha256(payload.read_bytes()).hexdigest(), sizeBytes=payload.stat().st_size, location={'kind':'local','path':payload.name})
        return artifact, payload

    def native_run(self, native, original, row, values, *, apply=False):
        test = native/'tests/rendered.tftest.json'
        if isinstance(original, dict):
            run = copy.deepcopy(original['run'][row['case']]); run.pop('variables', None); run.pop('assert', None)
            run['command'] = 'apply' if apply else 'plan'
            test.write_text(json.dumps({'mock_provider':original['mock_provider'], 'variables':values, 'run':{'rendered':run}}))
        else:
            run = blocks(original, '^run "'+re.escape(row['case'])+'"\\s*\\{')[0]
            overrides = '\n'.join(blocks(run, r'^\s*override_(?:data|resource)\s*\{'))
            prefix = re.split(r'(?m)^(?:variables\s*\{|run\s)', original, maxsplit=1)[0]
            test = test.with_suffix('.hcl')
            test.write_text(prefix+'\nvariables {\n'+'\n'.join(key+' = '+json.dumps(value) for key,value in values.items())+'\n}\nrun "rendered" {\n command = '+('apply' if apply else 'plan')+'\n'+overrides+'\n}\n')
        try:
            events = [json.loads(line) for line in command(['tofu','test','-json','-verbose'], cwd=native, env=self.env).splitlines()]
            kind = 'test_state' if apply else 'test_plan'
            return next(event[kind] for event in events if event.get('type') == kind)
        finally:
            test.unlink(missing_ok=True)

    def saved_destroy(self, row, directory, values, state):
        """Pinned REAL provider, no refresh/auth/network; save then inspect the native plan."""
        native = directory/'destroy-native'
        source = BP/'terraform/monorepo/modules'/row['root']
        shutil.copytree(source, native, ignore=shutil.ignore_patterns('.terraform', 'tests', '*.tfstate*'))
        self.private(native, 'terraform.tfstate', state)
        self.private(native, 'recovery.auto.tfvars.json', values)
        provider = row['family'].split('-')[0]
        if provider == 'aws' and row['root'] != 'kubernetes-component':
            override = '''provider "aws" {
 access_key="offline-not-a-credential"
 secret_key="offline-not-a-credential"
 skip_credentials_validation=true
 skip_requesting_account_id=true
 skip_metadata_api_check=true
 skip_region_validation=true
}
'''
        elif provider == 'gcp' and row['root'] != 'kubernetes-component':
            name = 'google-beta' if row['root'] == 'gcp-apigateway' else 'google'
            override = 'provider "'+name+'" { access_token="offline-not-a-credential" }\n'
        elif provider == 'azure' and row['root'] != 'kubernetes-component':
            self.fake_azure_auth()
            override = '''provider "azurerm" {
 tenant_id="22222222-2222-2222-2222-222222222222"
 use_cli=true
 use_oidc=false
}
'''
        else:
            override = ''
        if override:
            (native/'offline_override.tf').write_text(override)
        command(['tofu', 'init', '-backend=false', '-input=false', '-lockfile=readonly', f'-plugin-dir={PLUGINS}'], cwd=native, env=self.env)
        command(['tofu', 'plan', '-destroy', '-refresh=false', '-input=false', '-lock=false', '-out=destroy.plan'], cwd=native, env=self.env)
        view = json.loads(command(['tofu', 'show', '-json', 'destroy.plan'], cwd=native, env=self.env))
        return view, 'sha256:'+hashlib.sha256((native/'destroy.plan').read_bytes()).hexdigest()

    def fake_azure_auth(self):
        """LOCAL pinned-provider credential protocol double, not an ARM/API substitute."""
        binary = self.root/'azure-auth-double'
        if binary.exists():
            return
        binary.mkdir(mode=0o700)
        account = {'id':'00000000-0000-0000-0000-000000000001',
            'tenantId':'22222222-2222-2222-2222-222222222222',
            'user':{'type':'servicePrincipal', 'name':'offline-fixture'}}
        claims = {'tid':account['tenantId'], 'oid':'33333333-3333-3333-3333-333333333333',
            'appid':'11111111-1111-1111-1111-111111111111', 'exp':4102444800}
        encode = lambda value: base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')
        token = encode({'alg':'none'})+'.'+encode(claims)+'.'
        responses = {'version':{'azure-cli':'2.90.0'}, 'account show':account, 'account list':[account],
            'account get-access-token':{'accessToken':token, 'tokenType':'Bearer', 'expiresOn':'2099-01-01 00:00:00.000000'}}
        # Copied from the existing local historical native test, with no runtime imports.
        # Selected v4.66.0 clients/auth.go -> go-azure-sdk Azure CLI authorizer only.
        az = binary/'az'
        az.write_text('#!'+sys.executable+'\nimport json,sys\nr='+repr(responses)+
            '\na=sys.argv[1:]\nkey=a[0] if a and a[0]=="version" else " ".join(a[:2])\n'+
            'if key not in r:sys.exit(91)\nprint(json.dumps(r[key]))\n')
        az.chmod(0o700)
        self.env.update(PATH=str(binary)+os.pathsep+self.env['PATH'], ARM_PROVIDER_ENHANCED_VALIDATION='false')


def native_state(view):
    """Project actual mock-provider state view to native state v4 (test data only)."""
    records = {}
    for resource in view['values']['root_module']['resources']:
        key = (resource['mode'], resource['type'], resource['name'])
        row = records.setdefault(key, {'mode':key[0], 'type':key[1], 'name':key[2],
            'provider':'provider["'+resource['provider_name']+'"]', 'instances':[]})
        instance = {'schema_version':resource['schema_version'], 'attributes':resource['values'], 'sensitive_attributes':[]}
        if '[' in resource['address']: instance['index_key'] = json.loads(resource['address'].split('[',1)[1][:-1])
        row['instances'].append(instance)
    return {'version':4, 'terraform_version':'1.11.4', 'serial':1,
        'lineage':'11111111-1111-1111-1111-111111111111', 'outputs':{}, 'resources':list(records.values())}
