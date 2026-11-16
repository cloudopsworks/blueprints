// LOCAL native integration. Recorded show documents are explicitly not provider execution.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import test from 'node:test';
import {root, loadStep} from './action_test_support.mjs';

export const action = 'cd/monorepo/native/forward-plan/action.yml';
export const cli = process.env.TRONADOR_CLI || '/tmp/tronador-v511-python-prep';
export const hash = bytes => 'sha256:' + createHash('sha256').update(bytes).digest('hex');
export function command(exe, args, input, env = {PATH: process.env.PATH}, cwd) {
  const result = spawnSync(exe, args, {input: typeof input === 'string' ? input : JSON.stringify(input), env, cwd, encoding: 'utf8', timeout: 30000, maxBuffer: 8 * 1024 * 1024});
  assert.equal(result.status, 0, result.stderr);
  return result.stdout;
}
export function fixture(t) {
  const expected = cli === '/tmp/tronador-v511-python-prep' ? 'sha256:2dd1cc04bcda2d26f851cfe61355bae79e57bd48267934df1ed521a9e87538c5' : process.env.TRONADOR_CLI_SHA256;
  assert.match(expected || '',/^sha256:[a-f0-9]{64}$/,'independently supplied binary SHA is required');
  assert.equal(hash(fs.readFileSync(cli)), expected);
  const work = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'normal24-')));
  fs.chmodSync(work, 0o700);
  t.after(() => fs.rmSync(work, {recursive: true, force: true}));
  const catalog = JSON.parse(command('yq', ['-o=json', '-I=0', '.', path.join(root, 'terraform/monorepo/module-catalog.yaml')]));
  const row = catalog.modules['aws-lambda'];
  const module = path.join(root, row.path);
  const context = JSON.parse(fs.readFileSync(path.join(root, '../tronador-cli-v511/internal/components/testdata/operations/operation-context-frozen.json')));
  Object.assign(context.plan.components[0], {
    package: {kind:'function',provider:'aws',mode:'aws-zip',runtime:'provided.al2023',entryPoint:'bootstrap',architecture:'amd64',source:'.'},
    workload: {kind:'function'},
    preview: {mode:'container',source:'function',dockerfile:'Dockerfile',context:'.',adapter:'aws-lambda-rie',entryPoint:'bootstrap',port:8080,healthPath:'/health',invokePath:'/invoke',invokeTest:{requestBody:'{}',expectedStatus:200,responseContains:'ok'}},
  });
  context.plan.targets = [{id:'prod-run',environment:'prod',provider:'aws',authRef:'aws-prod',ownership:'managed',configDigest:'sha256:'+'2'.repeat(64),kind:'aws.lambda',region:'us-east-1',functionName:'example',packageMode:'zip',alias:null,runtime:'provided.al2023',iac:{roleArn:'arn:aws:iam::123456789012:role/example',sourceBucket:'external-packages'},readiness:{deadlineSeconds:300,intervalSeconds:5,probe:{kind:'lambda-invoke',requestBody:'{}',responseContains:'ok'}}}];
  context.providerIdentity = '123456789012';
  context.backend.authRef = 'aws-state';
  context.backendIdentity = {provider:'aws',accountId:'123456789012'};
  context.authRefs = ['aws-prod','aws-state'];
  Object.assign(context.origin, {moduleRevision:row.revision,providerLockDigest:row.providerLockDigest});
  // No module-root here: this constructs inspectable data, not an activated operation.
  const operation = JSON.parse(command(cli, ['components','operations','plan','--operation','apply','--environment','prod','--target','prod-run','--component','api','--json'], context));
  const bound = JSON.parse(command(cli, ['components','contracts','validate','--kind','StateHandle','--module-root',module,'--json'], operation.stateHandle));
  assert.equal(bound.module.activationBlocked, true);
  assert.equal(bound.digest, operation.stateHandleDigest);
  const privateFile = (name, value) => {
    const filename = path.join(work, name);
    fs.writeFileSync(filename, Buffer.isBuffer(value) ? value : JSON.stringify(value), {mode:0o600});
    return filename;
  };
  const saved = privateFile('saved.plan', Buffer.from('504b030400000000', 'hex'));
  const rendered = {format_version:'1.2',terraform_version:'1.11.4',resource_changes:[]};
  const inputs = {OPERATION_PLAN:privateFile('operation.json',operation),SAVED_PLAN:saved,PLAN_JSON:privateFile('plan.json',rendered),PRIOR_STATE:''};
  fs.copyFileSync(path.join(module,'.terraform.lock.hcl'),path.join(work,'.terraform.lock.hcl'));
  fs.chmodSync(path.join(work,'.terraform.lock.hcl'),0o600);
  const cache = path.join(root,'terraform/monorepo/capabilities/.terraform');
  assert.ok(fs.existsSync(path.join(cache,'providers')),'recorded-shape tests also retain an installed cache, never an empty replacement');
  fs.cpSync(cache,path.join(work,'.terraform'),{recursive:true,mode:fs.constants.COPYFILE_FICLONE});
  const privateCache = directory => {
    fs.chmodSync(directory,0o700);
    for (const entry of fs.readdirSync(directory,{withFileTypes:true})) {
      assert.equal(entry.isSymbolicLink(),false);
      if (entry.isDirectory()) privateCache(path.join(directory,entry.name));
    }
  };
  privateCache(path.join(work,'.terraform'));
  return {work,module,operation,bound,rendered,inputs,privateFile,catalog,context};
}

export async function invoke(f, options = {}) {
  const calls = [], outputs = {}, nativeRequire = createRequire(import.meta.url);
  const old = process.env;
  process.env = {PATH: old.PATH, RUNNER_TEMP:f.work, GITHUB_ACTION_PATH:path.join(root,path.dirname(action)), ...f.inputs, ...options.env};
  const require = name => name === 'node:child_process' ? {spawnSync(exe,args,settings) {
    calls.push({exe,args,env:{...settings.env},cwd:settings.cwd});
    if (exe === 'tronador') {
      const linked = args.indexOf('--linked-context');
      const contextPath = linked < 0 ? null : args[linked+1];
      if (contextPath && options.beforeInspection) options.beforeInspection(contextPath);
      const result = spawnSync(options.cli || cli,args,settings);
      if (contextPath && options.afterInspection) options.afterInspection(contextPath);
      if (contextPath && options.nativeResult) return options.nativeResult(result);
      return result;
    }
    if (exe === 'tofu' && !options.realTofu) {
      const stdout = args[0] === 'version' ? Buffer.from(JSON.stringify({terraform_version:options.version || '1.11.4'})) : fs.readFileSync(f.inputs.PLAN_JSON);
      if (options.mutate && args[0] === 'show') options.mutate();
      return {status:0,stdout,stderr:Buffer.alloc(0)};
    }
    if (exe === 'tofu' && options.denyNetwork) return spawnSync('/usr/bin/sandbox-exec',['-p','(version 1)(allow default)(deny network*)','tofu',...args],settings);
    return spawnSync(exe,args,settings);
  }} : nativeRequire(name);
  try {
    for (const id of ['admit']) {
      const step = loadStep(action,id);
      const core = {setOutput(name,value) { outputs[id+':'+name] = value; }, setFailed(message) {throw new Error(message);}};
      const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
      await new AsyncFunction('require','core',step.script)(require,core);
    }
    return {outputs,calls};
  } catch (error) {
    return {error:error.message,outputs,calls};
  } finally {
    process.env = old;
  }
}

if (path.resolve(process.argv[1] || '') === fileURLToPath(import.meta.url)) {
  test('actual pinned CLI validates blocked authoritative module without activation', t => {
    const f = fixture(t);
    assert.equal(f.bound.module.activationBlocked,true);
  });
}

export function nativePlan(f, builtin = false, configuration) {
  const source = path.join(f.module,'.terraform');
  assert.ok(fs.existsSync(path.join(source,'providers')),'preinstalled authoritative provider cache is required; no install/green skip');
  const packageRoot = path.join(source,'providers/registry.opentofu.org/hashicorp/aws/6.35.0/darwin_arm64');
  const packageLines = fs.readdirSync(packageRoot).sort().map(name => {
    const fd = fs.openSync(path.join(packageRoot,name),'r'), digest = createHash('sha256'), buffer = Buffer.alloc(1048576);
    try {
      let length;
      while ((length = fs.readSync(fd,buffer,0,buffer.length,null))) digest.update(buffer.subarray(0,length));
    } finally { fs.closeSync(fd); }
    return digest.digest('hex')+'  '+name+'\n';
  }).join('');
  const packageHash = 'h1:'+createHash('sha256').update(packageLines).digest('base64');
  assert.ok(fs.readFileSync(path.join(f.module,'.terraform.lock.hcl'),'utf8').includes('"'+packageHash+'"'),'installed package must match authoritative lock; presence is insufficient');
  fs.cpSync(source,path.join(f.work,'.terraform'),{recursive:true,mode:fs.constants.COPYFILE_FICLONE});
  const privateDirectories = directory => {
    fs.chmodSync(directory,0o700);
    for (const entry of fs.readdirSync(directory,{withFileTypes:true})) {
      assert.equal(entry.isSymbolicLink(),false,'cache fixture must not escape through a symlink');
      if (entry.isDirectory()) privateDirectories(path.join(directory,entry.name));
    }
  };
  privateDirectories(path.join(f.work,'.terraform'));
  fs.writeFileSync(path.join(f.work,'main.tf'),configuration ?? (builtin ? 'resource "terraform_data" "unowned" { input = "local-native-test" }\n' : 'terraform {}\n'),{mode:0o600});
  const config = path.join(f.work,'test.tofurc');
  fs.writeFileSync(config,'disable_checkpoint = true\n',{mode:0o600});
  const env = {PATH:process.env.PATH,HOME:f.work,TMPDIR:f.work,TF_DATA_DIR:path.join(f.work,'.terraform'),TF_CLI_CONFIG_FILE:config,TF_IN_AUTOMATION:'true',CHECKPOINT_DISABLE:'1'};
  const lockBefore = hash(fs.readFileSync(path.join(f.work,'.terraform.lock.hcl')));
  command('tofu',['plan','-input=false','-refresh=false','-out='+f.inputs.SAVED_PLAN],undefined,env,f.work);
  fs.chmodSync(f.inputs.SAVED_PLAN,0o600);
  const shown = command('tofu',['show','-json','-plan='+f.inputs.SAVED_PLAN],undefined,env,f.work);
  fs.writeFileSync(f.inputs.PLAN_JSON,shown,{mode:0o600});
  assert.equal(hash(fs.readFileSync(path.join(f.work,'.terraform.lock.hcl'))),lockBefore);
  assert.equal(lockBefore,f.operation.stateHandle.origin.providerLockDigest);
  assert.equal(JSON.parse(shown).format_version,'1.2');
  return {lockBefore,env};
}

if (path.resolve(process.argv[1] || '') === fileURLToPath(import.meta.url)) {
  test('actual OpenTofu1.11.4 empty binary plan is byte-bound with retained exact lock and installed cache', async t => {
    const f = fixture(t), native = nativePlan(f);
    const before = hash(fs.readFileSync(f.inputs.SAVED_PLAN));
    const result = await invoke(f,{realTofu:true,env:{AWS_SECRET_ACCESS_KEY:'must-not-inherit',GITHUB_TOKEN:'must-not-inherit',TF_CLI_ARGS_show:'--bad',TF_ENCRYPTION:'bad',TF_REATTACH_PROVIDERS:'bad',OTEL_TRACES_EXPORTER:'otlp'}});
    assert.equal(result.error,undefined,JSON.stringify(result));
    const record = JSON.parse(fs.readFileSync(result.outputs['admit:inspection']));
    assert.deepEqual(record.counts,{create:0,update:0,delete:0,unchanged:0});
    assert.equal(record.savedPlanDigest,before);
    assert.equal(hash(fs.readFileSync(f.inputs.SAVED_PLAN)),before);
    assert.equal(hash(fs.readFileSync(path.join(f.work,'.terraform.lock.hcl'))),native.lockBefore);
    const shows = result.calls.filter(call => call.exe === 'tofu' && call.args[0] === 'show');
    assert.equal(shows.length,1);
    assert.deepEqual(shows[0].args,['show','-json','-plan='+f.inputs.SAVED_PLAN]);
    assert.equal(shows[0].cwd,f.work);
    assert.deepEqual(Object.keys(shows[0].env).sort(),['CHECKPOINT_DISABLE','HOME','PATH','TF_CLI_CONFIG_FILE','TF_DATA_DIR','TF_IN_AUTOMATION','TMPDIR']);
    assert.equal(fs.statSync(result.outputs['admit:inspection']).mode & 0o777,0o600);
  });
  test('actual builtin native plan reaches unowned-address denial rather than a recorded show', async t => {
    const f = fixture(t);
    nativePlan(f,true);
    const result = await invoke(f,{realTofu:true});
    assert.equal(result.error,'private native plan inspection failed');
    assert.equal(result.outputs['admit:inspection'],undefined);
    assert.ok(result.calls.some(call => call.exe === 'tofu' && call.args[0] === 'show'));
  });
  test('ZIP signature without valid native binary contents fails actual native decoding', async t => {
    const f = fixture(t);
    nativePlan(f);
    fs.writeFileSync(f.inputs.SAVED_PLAN,Buffer.from('504b030400000000','hex'));
    const result = await invoke(f,{realTofu:true});
    assert.equal(result.error,'private native plan admission failed');
    assert.deepEqual(result.outputs,{});
  });
}

export function familyFixture(t, family, mode = 'standard') {
  const f = fixture(t), row = f.catalog.modules[family], module = path.join(root,row.path);
  const kind = family.replace('-','.'), provider = kind.split('.')[0];
  const tests = fs.readdirSync(path.join(module,'tests')).filter(name => /\.tftest\.(json|hcl)$/.test(name));
  assert.equal(tests.length,1);
  const text = fs.readFileSync(path.join(module,'tests',tests[0]),'utf8');
  const variables = tests[0].endsWith('.json') ? JSON.parse(text).variables : Object.fromEntries(['resource','configuration','workload'].map(key => {
    const match = text.match(new RegExp('^\\s*'+key+'\\s*=\\s*(\\{.*\\})\\s*$','m'));
    return [key,match && match[1].includes('"') && !['aws-eks','gcp-gke','azure-aks'].includes(family) ? JSON.parse(match[1]) : {kind}];
  }));
  if (family === 'gcp-appengine' && mode === 'flexible') {
    const configurations = [...text.matchAll(/^\s*configuration\s*=\s*(\{.*\})\s*$/gm)];
    variables.configuration = JSON.parse(configurations[1][1]);
  }
  const defaults = {id:'prod-run',environment:'prod',provider,authRef:'prod',configDigest:'sha256:'+'c'.repeat(64),kind,region:'us-central1',cluster:'cluster',namespace:'apps',application:'app',environmentName:'env',bucket:'bucket',prefix:'site',functionName:'handler',packageMode:'zip',alias:null,restApiId:'api',stage:'prod',project:'project',service:'api',serviceAccount:'runtime@project.iam.gserviceaccount.com',location:'us-central1',appConfig:'app.yaml',trigger:{kind:'http',value:'http'},api:'api',gateway:'gateway',backendServiceAccount:'backend@project.iam.gserviceaccount.com',subscriptionId:'00000000-0000-0000-0000-000000000001',resourceGroup:'rg',appName:'app',containerName:'app',slot:'production',hostingPlan:'premium',workerRuntime:'python',account:'storage',container:'$web',serviceName:'gateway',apiId:'api',apiPath:'api'};
  const definitions = JSON.parse(fs.readFileSync(path.join(root,'../tronador-cli-v511/internal/components/schema/monorepo-v1.schema.json'))).$defs.Target.oneOf;
  const definition = definitions.find(item => item.properties.kind.const === kind);
  const merge = (a,b) => {
    const value = {...a};
    for (const [key,entry] of Object.entries(b)) value[key] = entry && typeof entry === 'object' && !Array.isArray(entry) ? merge(value[key] || {},entry) : entry;
    return value;
  };
  const target = merge(Object.fromEntries(definition.required.filter(key => key !== 'readiness').map(key => [key,defaults[key]])),merge(variables.resource,variables.configuration));
  Object.assign(target,{kind,id:'prod-run',environment:'prod',ownership:'managed'});
  delete target.architecture;
  if (provider === 'aws') target.region = variables.resource.region || 'us-east-1';
  let pkg = {kind:'container',dockerfile:'Dockerfile',context:'.',platform:'linux/amd64'}, workload = {kind:'http',port:8080,healthPath:'/health'};
  let probe = {kind:'http',path:'/ready',method:'GET',requestBody:'',expectedStatus:200,responseContains:'ready',auth:{kind:'none'}};
  if (['aws.s3-static','gcp.storage-static','azure.blob-static'].includes(kind)) {
    pkg = {kind:'static',directory:'dist',index:'index.html'}; workload = {kind:'static'}; probe = {kind:'static-http',path:'/index.html'};
  } else if (['aws.apigateway-rest','gcp.apigateway','azure.apim'].includes(kind)) {
    pkg = {kind:'openapi',file:'openapi.json',version:'3.0'}; workload = {kind:'api'};
    if (provider !== 'aws') target.apiVersion ??= '1.0';
  } else if (['aws.lambda','gcp.functions-gen2','azure.functions'].includes(kind)) {
    pkg = {kind:'function',provider,mode:{aws:'aws-zip',gcp:'gcp-gen2',azure:'azure-zip'}[provider],runtime:variables.configuration.runtime || 'python312',entryPoint:variables.package_handler || variables.configuration.iac?.entryPoint || 'handler',architecture:'amd64',source:'src'};
    workload = {kind:'function'};
    if (provider === 'aws') { target.alias ??= null; probe = {kind:'lambda-invoke',requestBody:'{}',responseContains:'ready'}; }
  } else if (['aws.beanstalk','gcp.appengine','azure.appservice'].includes(kind)) pkg = {kind:'archive',format:'zip',include:['app.yaml']};
  if (kind === 'gcp.appengine') {
    target.appConfigResolved = structuredClone(variables.configuration.appConfig);
    target.appConfig = 'app.yaml';
    target.appEnvironment = target.appConfigResolved.environment;
    for (const key of ['entrypoint','instanceClass','runtimeConfig','scaling']) target.appConfigResolved[key] ??= null;
    const scaling = target.appConfigResolved.scaling;
    const keys = scaling.kind === 'manual' ? ['instances'] : ['minInstances','maxInstances','minIdleInstances','maxIdleInstances','targetCpuUtilization','targetThroughputUtilization','maxConcurrentRequests','minPendingLatency','maxPendingLatency'];
    for (const key of keys) scaling[key] ??= null;
  }
  if (kind === 'gcp.functions-gen2') target.trigger = {kind:'http',value:'http'};
  target.readiness = {deadlineSeconds:30,intervalSeconds:1,probe};
  const context = f.context, component = context.plan.components[0];
  Object.assign(component,{package:pkg,workload,preview:{mode:'container',source:'main',port:8080,healthPath:'/health'}});
  if (pkg.kind === 'function') component.preview = {mode:'container',source:'function',dockerfile:'Dockerfile',context:'.',adapter:'handler-http',entryPoint:pkg.entryPoint,port:8080,healthPath:'/health',invokePath:'/invoke',invokeTest:{requestBody:'{}',expectedStatus:200,responseContains:'ready'}};
  else if (pkg.kind === 'archive') component.preview = {mode:'container',source:'dockerfile',dockerfile:'Dockerfile',context:'.',port:8080,healthPath:'/health'};
  else if (pkg.kind === 'static') component.preview = {mode:'container',source:'static',port:8080,healthPath:'/health'};
  else if (pkg.kind === 'openapi') component.preview = {mode:'artifact-only',reason:'openapi'};
  context.plan.targets = [target];
  context.providerIdentity = {aws:'123456789012',gcp:'123456789',azure:defaults.subscriptionId}[provider];
  context.authRefs = ['aws-state','prod'];
  Object.assign(context.origin,{moduleRevision:row.revision,providerLockDigest:row.providerLockDigest});
  const operation = JSON.parse(command(cli,['components','operations','plan','--operation','apply','--environment','prod','--target','prod-run','--component','api','--json'],context));
  const bound = JSON.parse(command(cli,['components','contracts','validate','--kind','StateHandle','--module-root',module,'--json'],operation.stateHandle));
  assert.equal(bound.module.activationBlocked,true);
  assert.equal(bound.digest,operation.stateHandleDigest);
  f.operation = operation; f.bound = bound; f.module = module;
  fs.writeFileSync(f.inputs.OPERATION_PLAN,JSON.stringify(operation));
  fs.copyFileSync(path.join(module,'.terraform.lock.hcl'),path.join(f.work,'.terraform.lock.hcl'));
  fs.chmodSync(path.join(f.work,'.terraform.lock.hcl'),0o600);
  return f;
}

export function resourceChange(address, actions = ['create'], values = {}) {
  const [type,name] = address.replace(/\[.*$/,'').split('.');
  return {address,mode:'managed',type,name,change:{actions,before:actions.join(',') === 'create' ? null : {},after:actions.join(',') === 'delete' ? null : {},...values}};
}
export function render(f,changes) {
  f.rendered.resource_changes = changes;
  fs.writeFileSync(f.inputs.PLAN_JSON,JSON.stringify(f.rendered));
}
export function prior(f,addresses) {
  const resources = addresses.map(address => {
    const [type,name] = address.replace(/\[.*$/,'').split('.');
    const match = address.match(/\[(.*)\]$/);
    return {mode:'managed',type,name,instances:[match ? {index_key:JSON.parse(match[1]),attributes:{arbitraryPriorIdentity:'not projected'}} : {attributes:{}}]};
  });
  f.inputs.PRIOR_STATE = f.privateFile('prior.json',{version:4,serial:1,lineage:'local-fixture',resources});
}

if (path.resolve(process.argv[1] || '') === fileURLToPath(import.meta.url)) {
  test('actual native show stdout does not accept a different JSON companion', async t => {
    const f = fixture(t);
    nativePlan(f);
    fs.appendFileSync(f.inputs.PLAN_JSON,' ');
    const result = await invoke(f,{realTofu:true});
    assert.equal(result.error,'private native plan admission failed');
    assert.deepEqual(result.outputs,{});
    assert.ok(result.calls.some(call => call.exe === 'tofu' && call.args[0] === 'show'));
  });
}

if (path.resolve(process.argv[1] || '') === fileURLToPath(import.meta.url)) {
  for (const kind of ['known','nested-check','deferred-dependency','unknown-config','seeded-known','seeded-deferred']) {
    test(`actual native builtin data ${kind} preserves observed representation`,async t=>{
      const f=fixture(t);
      const state={version:4,terraform_version:'1.11.4',serial:1,lineage:'normal25-local-fixture',outputs:{example:{value:'ok',type:'string'}},resources:[]};
      const local=f.privateFile('remote.tfstate',state);
      const data=`data "terraform_remote_state" "external" {\n backend = "local"\n config = { path = ${JSON.stringify(local)} }\n}\n`;
      const managed='resource "terraform_data" "unowned" { input = "local-native-fixture" }\n';
      let configuration=data;
      if (kind==='nested-check') configuration=`check "local" {\n ${data} assert {\n condition = data.terraform_remote_state.external.outputs.example == "ok"\n error_message = "unexpected local value"\n }\n}\n`;
      if (kind==='deferred-dependency' || kind==='seeded-deferred') configuration=managed+data.replace(' config =',' depends_on = [terraform_data.unowned]\n config =');
      if (kind==='unknown-config') configuration=managed+data.replace(JSON.stringify(local),'terraform_data.unowned.output');
      if (kind.startsWith('seeded-')) {
        const seeded={...state,outputs:{},resources:[{mode:'data',type:'terraform_remote_state',name:'external',provider:'provider["terraform.io/builtin/terraform"]',instances:[{schema_version:0,attributes:{backend:'local',config:{path:local},outputs:{example:'ok'},workspace:null},sensitive_attributes:[]}]}]};
        fs.writeFileSync(path.join(f.work,'terraform.tfstate'),JSON.stringify(seeded),{mode:0o600});
      }
      nativePlan(f,false,configuration);
      const shown=JSON.parse(fs.readFileSync(f.inputs.PLAN_JSON)), rows=shown.resource_changes || [];
      const reads=rows.filter(row=>row.mode==='data');
      if (['known','seeded-known'].includes(kind)) assert.equal(reads.length,0,'known reads are not fabricated native no-op records');
      else {
        assert.equal(reads.length,1);
        assert.deepEqual(reads[0].change.actions,['read']);assert.equal(reads[0].change.before,null);
        assert.equal(typeof reads[0].change.after,'object');assert.notEqual(reads[0].change.after,null);
        assert.equal(typeof reads[0].change.after_unknown,'object');
        if (kind==='nested-check') assert.deepEqual(reads[0].change.after_unknown,{});
      }
      const result=await invoke(f,{realTofu:true});
      const managedChange=rows.some(row=>row.mode==='managed');
      assert.equal(result.error,managedChange?'private native plan inspection failed':undefined,JSON.stringify(result));
      if (managedChange) assert.deepEqual(result.outputs,{});
      else assert.deepEqual(JSON.parse(fs.readFileSync(result.outputs['admit:inspection'])).counts,{create:0,update:0,delete:0,unchanged:0});
    });
  }
}

if (path.resolve(process.argv[1] || '') === fileURLToPath(import.meta.url)) {
  for (const attack of ['alternate-context','companion-after-show','context-after-consumption']) {
    test(`actual native show + CLI rejects exercised ${attack}`,async t=>{
      const f=fixture(t);nativePlan(f);let fired=0;
      const mutate=filename=>{
        fired++;
        if(attack==='alternate-context') {
          const context=JSON.parse(fs.readFileSync(filename));
          const alternate=f.privateFile('alternate-native.json',fs.readFileSync(f.inputs.PLAN_JSON));
          context.forwardPlan.plan={path:alternate,digest:hash(fs.readFileSync(alternate))};
          fs.writeFileSync(filename,JSON.stringify(context));
        } else if(attack==='companion-after-show')fs.appendFileSync(f.inputs.PLAN_JSON,' ');
        else fs.appendFileSync(filename,' ');
      };
      const result=await invoke(f,{realTofu:true,...(attack==='context-after-consumption'?{afterInspection:mutate}:{beforeInspection:mutate})});
      assert.equal(fired,1);assert.equal(result.error,'private native plan inspection failed');assert.deepEqual(result.outputs,{});
      assert.equal(result.calls.filter(call=>call.exe==='tofu'&&call.args[0]==='show').length,1);
    });
  }
}

if (path.resolve(process.argv[1] || '') === fileURLToPath(import.meta.url)) {
 test('actual builtin show succeeds with host network-denial facility, not universal provider isolation',async t=>{
  assert.ok(fs.existsSync('/usr/bin/sandbox-exec'),'available host network-denial facility is required for this local proof');
  const f=fixture(t);nativePlan(f);
  const result=await invoke(f,{realTofu:true,denyNetwork:true});
  assert.equal(result.error,undefined,JSON.stringify(result));
  assert.equal(JSON.parse(fs.readFileSync(result.outputs['admit:inspection'])).activationBlocked,true);
 });
}
