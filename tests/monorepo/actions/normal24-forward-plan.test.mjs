import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {fixture,invoke,command,cli,hash} from './normal24-forward-plan.integration.mjs';

test('otherwise-valid native blocked-module data reaches the real inspector', async t => {
  const f = fixture(t);
  const result = await invoke(f);
  assert.equal(result.error,undefined,JSON.stringify(result));
  const inspection = JSON.parse(fs.readFileSync(result.outputs['admit:inspection']));
  assert.equal(inspection.activationBlocked,true);
  assert.deepEqual(inspection.counts,{create:0,update:0,delete:0,unchanged:0});
});

import {familyFixture,resourceChange,render,prior} from './normal24-forward-plan.integration.mjs';
const families = ['aws-eks','gcp-gke','azure-aks','aws-beanstalk','aws-lambda','aws-s3-static','aws-apigateway-rest','gcp-cloudrun','gcp-appengine','gcp-functions-gen2','gcp-storage-static','gcp-apigateway','azure-containerapps','azure-appservice','azure-functions','azure-blob-static','azure-apim'];
for (const family of families) {
  test(`actual native ${family} policy permits owned create and withholds late foreign address`, async t => {
    const f = familyFixture(t,family);
    const patterns = f.bound.module.metadata.ownedResourceAddresses;
    const address = family === 'gcp-appengine' ? 'google_app_engine_standard_app_version.component[0]' : patterns[0].replace('[*]','[0]');
    const values = family === 'gcp-appengine' ? {project:f.operation.stateHandle.resourceIdentity.project,service:f.operation.stateHandle.resourceIdentity.service,delete_service_on_destroy:true,noop_on_destroy:false} : {};
    const valid = resourceChange(address,['create'],{after:values});
    render(f,[valid]);
    const positive = await invoke(f);
    assert.equal(positive.error,undefined,JSON.stringify(positive));
    assert.equal(JSON.parse(fs.readFileSync(positive.outputs['admit:inspection'])).counts.create,1);
    const wrongOwner = structuredClone(valid);
    wrongOwner.change.after.tags = {'cloudopsworks-owner':'sha256:'+'0'.repeat(64)};
    render(f,[wrongOwner]);
    await denied(f);
    render(f,[valid,resourceChange('foreign_resource.unowned')]);
    const hostile = await invoke(f);
    assert.equal(hostile.error,'private native plan inspection failed');
    assert.equal(hostile.outputs['admit:inspection'],undefined);
    assert.ok(hostile.calls.filter(call => call.exe === 'tronador').length === 3);
  });
}

async function denied(f, expected = 'private native plan inspection failed', options) {
  const result = await invoke(f,options);
  assert.equal(result.error,expected);
  assert.equal(result.outputs['admit:inspection'],undefined);
  return result;
}
const literalCases = [
  ['missing',undefined,true],['null',null,true],['empty',{},true],
  ['full-owner',owner => ({'cloudopsworks-owner':owner,extra:'value'}),true],
  ['array',[],false],['scalar','bad',false],['unowned', {extra:'value'},false],
  ['null-owner',{'cloudopsworks-owner':null},false],['number-owner',{'cloudopsworks-owner':42},false],
  ['wrong-owner',{'cloudopsworks-owner':'sha256:'+'f'.repeat(64)},false],
  ['truncated-owner',owner => ({'cloudopsworks-owner':owner.slice(7,47)}),false],
];
for (const side of ['before','after']) {
  for (const [name,value,allowed] of literalCases) {
    test(`literal ${side}.tags ${name}: ${allowed ? 'narrow pass only' : 'deny'}`, async t => {
      const f = fixture(t), address = 'aws_lambda_function.component';
      prior(f,[address]);
      const change = resourceChange(address,['update']);
      if (value !== undefined) change.change[side].tags = typeof value === 'function' ? value(f.operation.stateHandleDigest) : value;
      // Unobserved provider identity is deliberately not authenticated here.
      change.change.before.id = 'old'; change.change.after.id = 'changed';
      render(f,[change]);
      if (!allowed) await denied(f);
      else assert.equal((await invoke(f)).error,undefined);
    });
  }
}
const unknownCases = [
  ['missing',undefined,true],['false',false,true],['empty',{},true],
  ['true',true,false],['null',null,false],['scalar',1,false],['array',[],false],
  ['tags-true',{tags:true},false],['tags-null',{tags:null},false],['tags-scalar',{tags:'bad'},false],['tags-array',{tags:[]},false],
  ['tags-empty',{tags:{}},true],['tags-false',{tags:false},true],['owner-true',{tags:{'cloudopsworks-owner':true}},false],
  ['owner-false',{tags:{'cloudopsworks-owner':false,other:true}},true],['malformed-other',{tags:{other:{}}},false],
  ['computed-provider-fields',{id:true,arn:true,nested:{arbitrary:true}},true],
];
for (const [name,value,allowed] of unknownCases) {
  test(`after_unknown ${name}: ${allowed ? 'narrow pass only' : 'deny'}`, async t => {
    const f = fixture(t), change = resourceChange('aws_lambda_function.component');
    if (value !== undefined) change.change.after_unknown = value;
    render(f,[change]);
    if (!allowed) await denied(f);
    else assert.equal((await invoke(f)).error,undefined);
  });
}
for (const family of ['gcp-cloudrun','gcp-functions-gen2']) {
  test(`${family} labels and metadata remain outside literal tags projection`, async t => {
    const f = familyFixture(t,family), address = f.bound.module.metadata.ownedResourceAddresses[0].replace('[*]','[0]');
    const value = {labels:{'cloudopsworks-owner':'foreign'},metadata:{'cloudopsworks-owner':'foreign'}};
    render(f,[resourceChange(address,['create'],{after:value})]);
    assert.equal((await invoke(f)).error,undefined);
    value.tags = {'cloudopsworks-owner':f.operation.stateHandleDigest.slice(7,47)};
    fs.writeFileSync(f.inputs.PLAN_JSON,JSON.stringify(f.rendered));
    await denied(f);
  });
}
for (const family of families) {
  test(`${family} native metadata controls all indexed paths, prior membership and replacements/deletes`, async t => {
    const f = familyFixture(t,family), metadata = f.bound.module.metadata;
    const expected = 'google_app_engine_standard_app_version.component[0]';
    for (const pattern of metadata.ownedResourceAddresses) {
      if (family === 'gcp-appengine' && pattern.includes('flexible')) continue;
      const address = pattern.replace('[*]','["fixture"]');
      const app = resourceChange(expected,['create'],{after:{project:f.operation.stateHandle.resourceIdentity.project,service:f.operation.stateHandle.resourceIdentity.service,delete_service_on_destroy:true,noop_on_destroy:false}});
      const change = resourceChange(address);
      if (family === 'gcp-appengine' && address === expected) change.change.after = app.change.after;
      const changes = family === 'gcp-appengine' && address !== expected ? [app,change] : [change];
      f.inputs.PRIOR_STATE = '';
      render(f,changes);
      assert.equal((await invoke(f)).error,undefined,`${family}/${address}/create`);
      const addresses = changes.map(row => row.address);
      prior(f,addresses);
      for (const row of changes) Object.assign(row.change,{actions:['update'],before:row.change.after});
      render(f,changes);
      assert.equal((await invoke(f)).error,undefined,`${family}/${address}/update`);
      for (const row of changes) row.change.actions = ['no-op'];
      render(f,changes);
      assert.equal((await invoke(f)).error,undefined,`${family}/${address}/no-op`);
      change.change.actions = ['delete','create'];
      render(f,changes);
      const replace = await invoke(f);
      assert.equal(replace.error,metadata.replaceResourceAddresses?.includes(pattern) ? undefined : 'private native plan inspection failed',`${family}/${address}/replacement`);
      change.change.actions = ['delete']; change.change.after = null;
      render(f,changes);
      const deleted = await invoke(f);
      assert.equal(deleted.error,metadata.applyDeleteResourceAddresses?.includes(pattern) ? undefined : 'private native plan inspection failed',`${family}/${address}/delete`);
    }
  });
}

test('data read/no-op stays separate from managed ownership; mutation and nested addresses deny', async t => {
  const f = fixture(t);
  for (const action of ['read','no-op','update']) {
    const row = {address:'data.aws_caller_identity.external',mode:'data',type:'aws_caller_identity',name:'external',change:{actions:[action],before:action === 'no-op' ? {} : null,after:{},after_unknown:{}}};
    render(f,[row]);
    const result = await invoke(f);
    assert.equal(result.error,action === 'update' ? 'private native plan inspection failed' : undefined);
  }
  render(f,[{address:'module.foreign.data.aws_caller_identity.external',mode:'data',type:'aws_caller_identity',name:'external',change:{actions:['read']}}]);
  await denied(f);
});

const hostileChanges = [
  ['duplicate',rows => rows.push(structuredClone(rows[0]))],
  ['moved',rows => rows[0].previous_address = 'aws_lambda_function.old'],
  ['imported',rows => rows[0].change.importing = {id:'foreign'}],
  ['generated',rows => rows[0].change.generated_config = 'bad'],
  ['malformed-actions',rows => rows[0].change.actions = ['create,delete']],
  ['unknown-action',rows => rows[0].change.actions = ['forget']],
  ['missing-before',rows => delete rows[0].change.before],
  ['array-after',rows => rows[0].change.after = []],
  ['null-after',rows => rows[0].change.after = null],
  ['unknown-mode',rows => rows[0].mode = 'ephemeral'],
  ['prefix-escape',rows => rows[0].address = 'aws_lambda_function.component.foreign'],
  ['unowned-index',rows => rows[0].address = 'aws_lambda_function.component[0]'],
];
for (const [name,mutate] of hostileChanges) {
  test(`otherwise-valid native operation denies ${name} resource shape`, async t => {
    const f = fixture(t), rows = [resourceChange('aws_lambda_function.component')];
    mutate(rows); render(f,rows); await denied(f);
  });
}
for (const [field,value] of [['resource_changes',null],['resource_changes',{}],['errored',true],['deferred_changes',[{}]],['deferred_changes',null]]) {
  test(`plan collection/error representation denies ${field}=${JSON.stringify(value)}`, async t => {
    const f = fixture(t); f.rendered[field] = value;
    fs.writeFileSync(f.inputs.PLAN_JSON,JSON.stringify(f.rendered)); await denied(f);
  });
}
test('resource_changes omission means empty, not readiness', async t => {
  const f = fixture(t); delete f.rendered.resource_changes;
  fs.writeFileSync(f.inputs.PLAN_JSON,JSON.stringify(f.rendered));
  assert.equal((await invoke(f)).error,undefined);
});
const hostileStates = [
  ['version',state => state.version = 3],['lineage',state => state.lineage = ''],['serial',state => state.serial = -1],
  ['nested',state => state.resources[0].module = 'module.foreign'],
  ['duplicate',state => state.resources.push(structuredClone(state.resources[0]))],
  ['index',state => state.resources[0].instances[0].index_key = {}],
];
for (const [name,mutate] of hostileStates) {
  test(`prior-state address-only projection denies ${name}`, async t => {
    const f = fixture(t), address = 'aws_lambda_function.component'; prior(f,[address]);
    const state = JSON.parse(fs.readFileSync(f.inputs.PRIOR_STATE)); mutate(state);
    fs.writeFileSync(f.inputs.PRIOR_STATE,JSON.stringify(state));
    render(f,[resourceChange(address,['update'])]); await denied(f);
  });
}
for (const [name,mutate] of [
  ['wrong-operation',f => f.operation.operation = 'destroy'],
  ['handle-digest',f => f.operation.stateHandleDigest = 'sha256:'+'0'.repeat(64)],
  ['module-revision',f => f.operation.stateHandle.origin.moduleRevision = 'sha256:'+'0'.repeat(64)],
]) {
  test(`native typed/module binding rejects ${name} before show`, async t => {
    const f = fixture(t); mutate(f);
    if (name === 'module-revision') {
      const native = JSON.parse(command(cli,['components','contracts','validate','--kind','StateHandle','--json'],f.operation.stateHandle));
      f.operation.stateHandleDigest = native.digest;
    }
    fs.writeFileSync(f.inputs.OPERATION_PLAN,JSON.stringify(f.operation));
    const result = await denied(f,'private native plan admission failed');
    assert.equal(result.calls.some(call => call.exe === 'tofu'),false);
    assert.deepEqual(result.outputs,{});
    if (name === 'module-revision') assert.equal(result.calls.filter(call => call.exe === 'tronador').length,2);
  });
}
for (const name of ['saved-bytes','companion-bytes','replacement-inode']) {
  test(`late ${name} substitution denies before any final output`, async t => {
    const f = fixture(t);
    const mutate = () => {
      if (name === 'saved-bytes') fs.appendFileSync(f.inputs.SAVED_PLAN,'changed');
      else if (name === 'companion-bytes') fs.appendFileSync(f.inputs.PLAN_JSON,' ');
      else { const bytes = fs.readFileSync(f.inputs.SAVED_PLAN); fs.unlinkSync(f.inputs.SAVED_PLAN); fs.writeFileSync(f.inputs.SAVED_PLAN,bytes,{mode:0o600}); }
    };
    const result = await denied(f,'private native plan admission failed',{mutate});
    assert.deepEqual(result.outputs,{});
  });
}
for (const name of ['wrong-lock','world-readable','symlink','hardlink','bad-utf8','nonbinary']) {
  test(`private input boundary denies ${name} with value-free error`, async t => {
    const f = fixture(t);
    if (name === 'wrong-lock') fs.appendFileSync(f.work+'/.terraform.lock.hcl','\n');
    if (name === 'world-readable') fs.chmodSync(f.inputs.PLAN_JSON,0o644);
    if (name === 'symlink') { fs.renameSync(f.inputs.PLAN_JSON,f.work+'/real.json'); fs.symlinkSync(f.work+'/real.json',f.inputs.PLAN_JSON); }
    if (name === 'hardlink') fs.linkSync(f.inputs.PLAN_JSON,f.work+'/second.json');
    if (name === 'bad-utf8') fs.writeFileSync(f.inputs.PLAN_JSON,Buffer.from([0xff]));
    if (name === 'nonbinary') fs.writeFileSync(f.inputs.SAVED_PLAN,'{"bookmark":"remote"}');
    const result = await denied(f,'private native plan admission failed');
    assert.deepEqual(result.outputs,{});
  });
}

for (const environment of ['standard','flexible']) {
  test(`AppEngine ${environment} exact whole-service fields and same-mode prior version`, async t => {
    const f = familyFixture(t,'gcp-appengine',environment);
    const type = environment === 'standard' ? 'google_app_engine_standard_app_version' : 'google_app_engine_flexible_app_version';
    const address = type+'.component[0]', resource = f.operation.stateHandle.resourceIdentity;
    const values = {project:resource.project,service:resource.service,delete_service_on_destroy:true,noop_on_destroy:false};
    const valid = resourceChange(address,['create'],{after:values});
    render(f,[valid]);
    assert.equal((await invoke(f)).error,undefined);
    for (const [name,mutate] of [
      ['missing-version',rows => rows.length = 0],
      ['wrong-project',rows => rows[0].change.after.project = 'foreign'],
      ['wrong-service',rows => rows[0].change.after.service = 'foreign'],
      ['default-service',rows => rows[0].change.after.service = 'default'],
      ['delete-flag',rows => rows[0].change.after.delete_service_on_destroy = false],
      ['noop-flag',rows => rows[0].change.after.noop_on_destroy = true],
      ...['project','service','delete_service_on_destroy','noop_on_destroy'].map(key => ['unknown-'+key,rows => rows[0].change.after_unknown = {[key]:true}]),
    ]) {
      const rows = [structuredClone(valid)]; mutate(rows); render(f,rows);
      await denied(f);
    }
    prior(f,[address]);
    const replacement = resourceChange(address,['delete','create'],{before:values,after:values});
    render(f,[replacement]);
    assert.equal((await invoke(f)).error,undefined);
    replacement.change.actions = ['create','delete']; render(f,[replacement]); await denied(f);
    prior(f,[(environment === 'standard' ? 'google_app_engine_flexible_app_version' : 'google_app_engine_standard_app_version')+'.component[0]']);
    render(f,[valid]); await denied(f);
    prior(f,[type+'.component[0]',type+'.foreign[0]']); render(f,[replacement]); await denied(f);
  });
}

test('256 independent actual native operation checks: invalid final input withholds its inspection, not prior results', async t => {
  const f = fixture(t);
  let validations = 0, inspected = 0;
  for (let index = 0; index < 256; index++) {
    if (index === 255) {
      f.operation.stateHandleDigest = 'sha256:'+'0'.repeat(64);
      fs.writeFileSync(f.inputs.OPERATION_PLAN,JSON.stringify(f.operation));
    }
    const result = await invoke(f);
    validations += result.calls.filter(call => call.exe === 'tronador').length;
    if (index === 255) {
      assert.equal(result.error,'private native plan admission failed');
      assert.equal(result.outputs['admit:inspection'],undefined);
    } else {
      assert.equal(result.error,undefined);
      inspected++;
    }
  }
  assert.equal(inspected,255);
  assert.equal(validations,766); // 256 OperationPlans + 255 module handles + 255 opt-in inspections, overlapping not additive scenarios.
});

test('late prior-state byte change after native consumption withholds final result after otherwise-valid transitions', async t => {
  const f = fixture(t), address = 'aws_lambda_function.component'; prior(f,[address]);
  render(f,[resourceChange(address,['update'])]);
  await denied(f,'private native plan inspection failed',{afterInspection:() => fs.appendFileSync(f.inputs.PRIOR_STATE,' ')});
});
for (const version of ['1.10.0','1.11.3','1.12.0']) {
  test(`native executable version ${version} is not the pinned contract`, async t => {
    const f = fixture(t);
    const result = await denied(f,'private native plan admission failed',{version});
    assert.equal(result.calls.some(call => call.exe === 'tofu' && call.args[0] === 'show'),false);
  });
}
for (const [name,mutate] of [
  ['binary-too-large',f => fs.truncateSync(f.inputs.SAVED_PLAN,16777217)],
  ['json-too-large',f => fs.truncateSync(f.inputs.PLAN_JSON,4194305)],
  ['binary-empty',f => fs.truncateSync(f.inputs.SAVED_PLAN,0)],
  ['unsafe-ancestor',f => fs.chmodSync(f.work,0o755)],
  ['relative-path',f => f.inputs.PLAN_JSON = 'relative.json'],
  ['wrong-json-format',f => { f.rendered.format_version = '1.0'; fs.writeFileSync(f.inputs.PLAN_JSON,JSON.stringify(f.rendered)); }],
]) {
  test(`bounded path/native representation ${name} denies`, async t => {
    const f = fixture(t); mutate(f); await denied(f,'private native plan admission failed');
  });
}

test('last managed literal-owner mismatch withholds the only final inspection output', async t => {
  const f = fixture(t), owner = f.operation.stateHandleDigest;
  const first = resourceChange('aws_lambda_function.component',['create'],{after:{tags:{'cloudopsworks-owner':owner}}});
  const last = resourceChange('aws_s3_object.package[0]',['create'],{after:{tags:{'cloudopsworks-owner':owner}}});
  render(f,[first,last]);
  assert.equal((await invoke(f)).error,undefined);
  last.change.after.tags['cloudopsworks-owner'] = 'sha256:'+'0'.repeat(64);
  render(f,[first,last]);
  await denied(f);
});

test('flat native data identifiers permit HCL hyphens and Unicode without managed ownership', async t => {
  const f = fixture(t);
  render(f,[{address:'data.aws_caller_identity.external-name',mode:'data',type:'aws_caller_identity',name:'external-name',change:{actions:['read'],before:null,after:{},after_unknown:{}}},{address:'data.example.équipe',mode:'data',type:'example',name:'équipe',change:{actions:['no-op'],before:{},after:{}}}]);
  assert.equal((await invoke(f)).error,undefined);
});
test('wildcard ownership does not accept noncanonical numeric instance syntax', async t => {
  const f = fixture(t);
  render(f,[resourceChange('aws_s3_object.package[1e3]')]);
  await denied(f);
});

// Source-backed representation cases; read/no-op are not managed ownership observations.
const dataShapes = [
  ['known-read',{actions:['read'],before:null,after:{},after_unknown:{}},true],
  ['root-unknown-source',{actions:['read'],before:null,after_unknown:true},true],
  ['recursive-mask',{actions:['read'],before:null,after:{},after_unknown:{x:[true,{y:false}]}},true],
  ['equal-noop-source',{actions:['no-op'],before:{x:[1]},after:{x:[1]},after_unknown:{x:[false]}},true],
  ['actions-only',{actions:['read']},false],
  ['missing-before',{actions:['read'],after:{},after_unknown:{}},false],
  ['null-after',{actions:['read'],before:null,after:null,after_unknown:true},false],
  ['contradictory-mask',{actions:['read'],before:null,after:{},after_unknown:true},false],
  ['missing-mask',{actions:['read'],before:null,after:{}},false],
  ['null-mask-leaf',{actions:['read'],before:null,after:{},after_unknown:{x:[null]}},false],
  ['string-mask-leaf',{actions:['read'],before:null,after:{},after_unknown:{x:'secret'}},false],
  ['number-mask-leaf',{actions:['read'],before:null,after:{},after_unknown:{x:1}},false],
  ['null-noop',{actions:['no-op'],before:null,after:{}},false],
  ['different-noop',{actions:['no-op'],before:{x:1},after:{x:2}},false],
  ['unknown-noop',{actions:['no-op'],before:{},after:{},after_unknown:{x:[true]}},false],
];
for (const [name,change,valid] of dataShapes) {
  test(`native data structure ${name}: ${valid ? 'pass' : 'deny'}`,async t => {
    const f=fixture(t);
    render(f,[{address:'data.example.external',mode:'data',type:'example',name:'external',change}]);
    const result=await invoke(f);
    assert.equal(result.error,valid ? undefined : 'private native plan inspection failed');
    if (!valid) assert.deepEqual(result.outputs,{});
  });
}

for (const attack of ['alternate-document','alternate-module','null-state','extra-policy','extra-home','raw-context-after','plan-after','operation-after','lock-after']) {
  test(`producer binding rejects exercised ${attack} replacement`,async t => {
    const f=fixture(t); prior(f,[]);
    let fired=0;
    const mutate=filename => {
      fired++;
      const context=JSON.parse(fs.readFileSync(filename));
      if (attack==='alternate-document') {
        const alternate=f.privateFile('alternate.json',{format_version:'1.2',terraform_version:'1.11.4',resource_changes:[]});
        context.forwardPlan.plan={path:alternate,digest:hash(fs.readFileSync(alternate))};
      } else if (attack==='alternate-module') context.forwardPlan.moduleRoot=f.module.replace('aws-lambda','gcp-cloudrun');
      else if (attack==='null-state') context.forwardPlan.priorState=null;
      else if (attack==='extra-policy') context.forwardPlan.metadata={ownedResourceAddresses:['terraform_data.unowned'],activationBlocked:false};
      else if (attack==='extra-home') context.home=f.work;
      else if (attack==='raw-context-after') {fs.appendFileSync(filename,' ');return;}
      else if (attack==='plan-after') {fs.appendFileSync(f.inputs.PLAN_JSON,' ');return;}
      else if (attack==='operation-after') {fs.appendFileSync(f.inputs.OPERATION_PLAN,' ');return;}
      else if (attack==='lock-after') {fs.appendFileSync(f.work+'/.terraform.lock.hcl',' ');return;}
      fs.writeFileSync(filename,JSON.stringify(context));
    };
    const after=attack.endsWith('-after');
    const result=await invoke(f,after ? {afterInspection:mutate} : {beforeInspection:mutate});
    assert.equal(fired,1,'attack hook must execute on real native context boundary');
    assert.equal(result.error,'private native plan inspection failed');
    assert.deepEqual(result.outputs,{});
  });
}
for (const field of ['missing','valid','record','digest','contextDigest','activationBlocked','moduleId','counts','extra']) {
  test(`recorded hostile native result ${field} denies`,async t => {
    const f=fixture(t);let fired=0;
    const result=await invoke(f,{nativeResult:process => {
      fired++; assert.equal(process.status,0);
      const value=JSON.parse(process.stdout);
      if (field==='missing') delete value.inspection;
      else if (field==='valid') value.valid=false;
      else if (field==='record') value.record.lockId='wrong';
      else if (field==='digest') value.digest='sha256:'+'0'.repeat(64);
      else if (field==='extra') value.inspection.home=f.work;
      else if (field==='counts') value.inspection.counts.create=-1;
      else value.inspection[field]=field==='activationBlocked' ? false : 'wrong';
      return {...process,stdout:Buffer.from(JSON.stringify(value))};
    }});
    assert.equal(fired,1);assert.equal(result.error,'private native plan inspection failed');assert.deepEqual(result.outputs,{});
  });
}
test('old independently frozen binary cannot silently ignore new inspection semantics',async t=>{
 const f=fixture(t);let fired=0;
 const result=await invoke(f,{cli:'/tmp/tronador-v511-python-prep',beforeInspection:()=>fired++});
 assert.equal(fired,1);assert.equal(result.error,'private native plan inspection failed');assert.deepEqual(result.outputs,{});
});
test('production action is one phase and has no mutable admission transport',t=>{
 const filename=new URL('../../../cd/monorepo/native/forward-plan/action.yml',import.meta.url);
 const source=fs.readFileSync(filename,'utf8');
 assert.equal((source.match(/uses: actions\/github-script@v9/g)||[]).length,1);
 assert.ok(source.includes('steps.admit.outputs.inspection'));
 assert.doesNotMatch(source,/admission\.json|ADMISSION:|id: inspect/);
});

for (const late of ['mask','read','noop','owner']) {
 test(`256 valid rows with late ${late} failure withholds all output`,async t=>{
  const f=fixture(t);
  const rows=Array.from({length:256},(_,index)=>({address:`data.example.item[${index}]`,mode:'data',type:'example',name:'item',index,change:{actions:['read'],before:null,after:{},after_unknown:{}}}));
  render(f,rows);assert.equal((await invoke(f)).error,undefined);
  const last={address:'data.example.invalid',mode:'data',type:'example',name:'invalid',change:{actions:['read'],before:null,after:{},after_unknown:{}}};
  if(late==='mask')last.change.after_unknown={nested:[null]};
  if(late==='read')delete last.change.before;
  if(late==='noop')last.change={actions:['no-op'],before:{x:1},after:{x:2}};
  if(late==='owner')Object.assign(last,resourceChange('aws_lambda_function.component',['create'],{after:{tags:{'cloudopsworks-owner':'sha256:'+'0'.repeat(64)}}}));
  render(f,[...rows,last]);const result=await denied(f);assert.deepEqual(result.outputs,{});
 });
}

test('native string instance keys preserve literal HTML characters and prior membership',async t=>{
 const f=fixture(t),address='aws_s3_object.package["a<b&c>"]';
 prior(f,[address]);render(f,[resourceChange(address,['update'])]);
 assert.equal((await invoke(f)).error,undefined);
 render(f,[{address:'data.example.item["a<b&c>"]',mode:'data',type:'example',name:'item',index:'a<b&c>',change:{actions:['read'],before:null,after:{},after_unknown:{}}}]);
 assert.equal((await invoke(f)).error,undefined);
});
