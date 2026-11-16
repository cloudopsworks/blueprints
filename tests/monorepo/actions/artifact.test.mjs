import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {runStep} from './action_test_support.mjs';

const action = 'ci/monorepo/artifact/action.yml', transportAction = 'ci/monorepo/artifact/transport/action.yml';
const cli = process.env.TRONADOR_CLI;
assert.ok(cli && fs.existsSync(cli), 'actual CLI is required for transport extraction');
const host = 'c'.repeat(40), digest = bytes => 'sha256:' + createHash('sha256').update(bytes).digest('hex');
const signed = 'https://artifact-storage.example.invalid/signed?signature=test-only';

function temporary(t) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'artifact-action-test-')));
  t.after(() => fs.rmSync(root, {recursive: true, force: true}));
  return root;
}
function fixture(t, mutate = () => {}) {
  const root = temporary(t);
  fs.writeFileSync(path.join(root, 'plan.json'), '{}');
  const zipped = spawnSync('zip', ['-q', '-X', 'fixture.zip', 'plan.json'], {cwd: root});
  assert.equal(zipped.status, 0);
  const bytes = fs.readFileSync(path.join(root, 'fixture.zip'));
  fs.unlinkSync(path.join(root, 'plan.json')); fs.unlinkSync(path.join(root, 'fixture.zip'));
  const artifact = {id: 300, workflow_run: {id: 200, head_sha: host}, expired: false,
    digest: digest(bytes), size_in_bytes: bytes.length};
  const run = {id: 200, repository: {id: 100}, head_sha: host};
  const repository = {id: 100};
  mutate({artifact, run, repository});
  return {root, bytes, artifact, run, repository,
    env: {ARTIFACT_ID: '300', RUN_ID: '200', GITHUB_REPOSITORY_ID: '100',
      ARCHIVE_DIGEST: digest(bytes), RUNNER_TEMP: root},
    api: [
      {method: 'rest.repos.get', args: {owner: 'example', repo: 'mixed'}, result: {data: repository}},
      {method: 'rest.actions.getWorkflowRun', args: {run_id: '200'}, result: {data: run}},
      {method: 'rest.actions.getArtifact', args: {artifact_id: '300'}, result: {data: artifact}},
      {method: 'request:GET /repos/{owner}/{repo}/actions/artifacts/{artifact_id}/zip',
        args: {artifact_id: '300', request: {redirect: 'manual'}},
        result: {status: 302, headers: {location: signed}}},
    ],
    fetches: [{url: signed, base64: bytes.toString('base64')}],
  };
}
function download(f, overrides = {}) {
  const source = {...f, ...overrides}, routeCount = source.api[0]?.method === 'rest.actions.listWorkflowRunArtifacts' ? 1 : 0;
  const resolved = runStep(transportAction, 'resolve', {env: source.env, api: source.api.slice(0, routeCount)});
  if (resolved.error) return resolved;
  return runStep(transportAction, 'retrieve', {realCli: cli, ...overrides, env: {...source.env, RESOLVED_FILE: resolved.outputs['resolved-file']}, api: source.api.slice(routeCount), fetches: source.fetches});
}

test('raw transport accepts actual metadata with no uploader job or attempt attestation', t => {
  const f = fixture(t), result = download(f);
  assert.equal(result.error, undefined);
  const bundle = JSON.parse(fs.readFileSync(result.outputs['bundles-file']))[0];
  const transport = JSON.parse(fs.readFileSync(bundle.transport));
  assert.deepEqual(transport, {repositoryId: '100', runId: '200', artifactId: '300',
    archiveDigest: digest(f.bytes), sizeInBytes: f.bytes.length, hostHeadSha: host, expired: false});
  assert.equal(fs.statSync(bundle.archive).mode & 0o777, 0o600);
  assert.equal(fs.statSync(path.dirname(bundle.archive)).mode & 0o777, 0o700);
  assert.deepEqual(fs.readFileSync(bundle.archive), f.bytes);
  assert.equal(fs.existsSync(bundle.extract), true, 'cohesive retrieval completes safe extraction');
  assert.equal(result.outputs.payloadVerified, undefined);
  assert.equal(result.outputs.producerJob, undefined);
  const request = result.calls.find(call => call.kind === 'fetch');
  assert.deepEqual(request.headers, {}, 'signed fetch must not inherit GitHub authorization');
  assert.equal(request.credentials, 'omit');
  assert.equal(request.redirect, 'error');
  assert.equal(request.hasSignal, true);
  assert.deepEqual(result.unused, {api: 0, tools: 0, fetches: 0});
});

for (const [name, mutate] of [
  ['repository', f => { f.repository.id = 101; }],
  ['run repository', f => { f.run.repository.id = 101; }],
  ['run ID', f => { f.run.id = 201; }],
  ['artifact ID', f => { f.artifact.id = 301; }],
  ['artifact run', f => { f.artifact.workflow_run.id = 201; }],
  ['expired metadata', f => { f.artifact.expired = true; }],
  ['missing expiry', f => { delete f.artifact.expired; }],
  ['REST digest', f => { f.artifact.digest = 'sha256:' + 'f'.repeat(64); }],
  ['negative size', f => { f.artifact.size_in_bytes = -1; }],
  ['oversized metadata', f => { f.artifact.size_in_bytes = 512 * 1024 * 1024 + 1; }],
  ['contradictory host metadata', f => { f.artifact.workflow_run.head_sha = 'd'.repeat(40); }],
]) {
  test(`download rejects wrong ${name} before ZIP request or extraction`, t => {
    const result = download(fixture(t, mutate));
    assert.ok(result.error);
    assert.deepEqual(result.outputs, {});
    assert.equal(result.calls.some(call => call.kind === 'fetch'), false);
    assert.equal(result.calls.some(call => call.method?.startsWith('request:')), false);
  });
}

for (const location of ['http://storage.invalid/a', 'https://user:secret@storage.invalid/a',
  'https://storage.invalid/a#fragment', 'not-a-url']) {
  test(`download rejects unsafe signed location ${location}`, t => {
    const f = fixture(t);
    f.api[3].result.headers.location = location;
    const result = download(f);
    assert.ok(result.error);
    assert.equal(result.calls.some(call => call.kind === 'fetch'), false);
    assert.deepEqual(result.outputs, {});
  });
}

for (const [name, response] of [
  ['second redirect', {status: 302, headers: {location: 'https://another.invalid/'}}],
  ['content length lie', {headers: {'content-length': '2'}}],
  ['stream byte overrun', {body: 'this body is longer than the metadata byte count'}],
  ['same-size digest mismatch', {body: 'x'.repeat(Buffer.byteLength('raw zip transport bytes'))}],
  ['aborted transport', {error: 'timed out', errorName: 'AbortError'}],
]) {
  test(`download denies ${name} without exposing transport outputs`, t => {
    const f = fixture(t);
    f.fetches = [{url: signed, ...response,
      ...(response.body || response.error || response.status ? {} : {base64: f.bytes.toString('base64')})}];
    const result = download(f);
    assert.ok(result.error);
    assert.deepEqual(result.outputs, {});
    const extracted = fs.readdirSync(f.root).flatMap(name => fs.readdirSync(path.join(f.root, name)));
    assert.equal(extracted.includes('extracted'), false);
  });
}

test('outer bundle invocation has no fabricated application descriptor', t => {
  const result = download(fixture(t));
  assert.equal(result.error, undefined);
  const native = result.calls.find(call => call.kind === 'exec');
  assert.equal(native.args.includes('--descriptor'), false);
  const bundle = JSON.parse(fs.readFileSync(result.outputs['bundles-file']))[0];
  assert.equal(fs.existsSync(bundle.directory), true);
  assert.equal(result.outputs.payloadVerified, undefined);
});

function recordsFixture(t, kind, record, extra = [], root = temporary(t)) {
  const parent = fs.mkdtempSync(path.join(root, 'artifact-data-')), directory = path.join(parent, 'extracted');
  fs.mkdirSync(directory, {mode: 0o700});
  const name = kind === 'BuildPlan' ? 'plan.json' : `results/${record.componentId}.json`;
  fs.mkdirSync(path.dirname(path.join(directory, name)), {recursive: true, mode: 0o700});
  fs.writeFileSync(path.join(directory, name), JSON.stringify(record), {mode: 0o600});
  const plan = path.join(root, 'endorsed-plan.json');
  fs.writeFileSync(plan, '{}');
  const files = [...new Set([name, ...['mainArtifact', 'previewArtifact'].filter(key => record[key])
    .map(key => record[key].location.path), ...extra])];
  const bundle = {runId:'200', artifactId:String(fs.readdirSync(root).length + 300), archiveDigest:'sha256:'+'a'.repeat(64), artifactName:'', archive:path.join(parent,'archive.zip'), transport:path.join(parent,'transport.json'), extract:directory, directory, files};
  const metadata = path.join(parent,'bundles.json'); fs.writeFileSync(metadata,JSON.stringify([bundle]),{mode:0o600});
  return {bundle, env: {RUNNER_TEMP:root, BUNDLES_FILE:metadata, DIRECTORY: directory, FILES: JSON.stringify(files), RECORD_KIND: kind, PLAN_PATH: plan},
    tools: [{prefix: ['components', 'contracts', 'validate', '--kind', kind],
      result: {stdout: JSON.stringify({record})}}]};
}

test('plan/control record requires no application descriptor or payload', t => {
  const result = runStep(action, 'records', recordsFixture(t, 'BuildPlan', {kind: 'BuildPlan'}));
  assert.equal(result.error, undefined);
  assert.equal(result.calls.length, 1);
  assert.equal(result.calls[0].args.includes('--descriptor'), false);
  assert.equal(result.outputs.payloadVerified, undefined);
});

test('component descriptor is read from the bounded validated embedded result', t => {
  const record = {componentId: 'api', status: 'succeeded', mainArtifact: {
    location: {kind: 'local', path: '.cloudopsworks/out/api/1.2.3/main.zip'},
  }};
  const result = runStep(action, 'records', recordsFixture(t, 'ComponentResult', record));
  assert.equal(result.error, undefined);
  assert.equal(JSON.parse(fs.readFileSync(result.outputs.record)).mainArtifact.location.path,
    record.mainArtifact.location.path);
  assert.equal(result.calls[0].args.includes('--linked-context'), true);
  assert.equal(result.outputs.payloadVerified, undefined);
});

test('identical main and preview descriptors may share one physical payload', t => {
  const artifact = {kind: 'container', format: 'oci', digest: 'sha256:' + 'a'.repeat(64),
    sizeBytes: 1000, location: {kind: 'local', path: '.cloudopsworks/out/api/1.2.3/main.oci.tar'},
    sourceSha: 'b'.repeat(40), builtVersion: '1.2.3'};
  const record = {componentId: 'api', status: 'succeeded', mainArtifact: artifact,
    previewArtifact: structuredClone(artifact)};
  const result = runStep(action, 'records', recordsFixture(t, 'ComponentResult', record));
  assert.equal(result.error, undefined, JSON.stringify(result));
  assert.ok(result.outputs.record);
});

for (const difference of ['digest', 'sizeBytes', 'sourceSha', 'builtVersion', 'format']) {
  test(`contradictory ${difference} descriptors cannot alias a physical payload`, t => {
    const artifact = {kind: 'container', format: 'oci', digest: 'sha256:' + 'a'.repeat(64),
      sizeBytes: 1000, location: {kind: 'local', path: '.cloudopsworks/out/api/1.2.3/main.oci.tar'},
      sourceSha: 'b'.repeat(40), builtVersion: '1.2.3'};
    const preview = structuredClone(artifact);
    preview[difference] = {digest: 'sha256:' + 'c'.repeat(64), sizeBytes: 1001,
      sourceSha: 'c'.repeat(40), builtVersion: '1.2.4', format: 'zip'}[difference];
    const result = runStep(action, 'records', recordsFixture(t, 'ComponentResult',
      {componentId: 'api', status: 'succeeded', mainArtifact: artifact, previewArtifact: preview}));
    assert.ok(result.error, JSON.stringify(result));
    assert.deepEqual(result.outputs, {});
  });
}

test('valid aliased descriptors cannot hide an unexpected extracted file', t => {
  const artifact = {location: {kind: 'local', path: '.cloudopsworks/out/api/1.2.3/main.oci.tar'}};
  const result = runStep(action, 'records', recordsFixture(t, 'ComponentResult',
    {componentId: 'api', status: 'succeeded', mainArtifact: artifact, previewArtifact: structuredClone(artifact)},
    ['attacker-policy.json']));
  assert.equal(result.error?.message, 'artifact-file-set');
  assert.deepEqual(result.outputs, {});
});

test('unexpected extracted files deny record exposure', t => {
  const result = runStep(action, 'records', recordsFixture(t, 'BuildPlan',
    {kind: 'BuildPlan'}, ['attacker-policy.json']));
  assert.equal(result.error?.message, 'artifact-file-set');
  assert.deepEqual(result.outputs, {});
});

test('typed source/plan mismatch denies before record or payload outputs', t => {
  const f = recordsFixture(t, 'ComponentResult', {componentId: 'api', status: 'succeeded'});
  f.tools[0].result = {exitCode: 1, stdout: ''};
  const result = runStep(action, 'records', f);
  assert.equal(result.error?.message, 'artifact-record-contract');
  assert.deepEqual(result.outputs, {});
});

function payloadFixture(t, artifact, root = temporary(t)) {
  const parent=fs.mkdtempSync(path.join(root,'artifact-data-')), directory=path.join(parent,'extracted');fs.mkdirSync(directory,{mode:0o700});
  const record=path.join(directory,'result.json');
  fs.writeFileSync(record,JSON.stringify({mainArtifact:artifact}),{mode:0o600});
  const bundle={runId:'200', artifactId:String(fs.readdirSync(root).length+300), archiveDigest:'sha256:'+'a'.repeat(64), artifactName:'', archive:path.join(parent,'archive.zip'), transport:path.join(parent,'transport.json'), extract:directory, directory, files:['result.json'],recordPath:record};
  const metadata=path.join(parent,'verified.json');fs.writeFileSync(metadata,JSON.stringify([bundle]),{mode:0o600});
  return {root,bundle,env:{RUNNER_TEMP:root, VERIFIED_RECORDS_FILE:metadata,DIRECTORY:directory,RECORD:record}};
}
test('inner payload verification consumes descriptor from embedded record and deletes temporary descriptor',t=>{
  const artifact={location:{kind:'local',path:'.cloudopsworks/out/api/1.2.3/main.zip'},digest:'sha256:'+'a'.repeat(64)};
  const f=payloadFixture(t,artifact);
  const r=runStep(action,'payloads',{...f,tools:[{prefix:['components','artifacts','verify','--mode','payload'],result:{stdout:'{"payloadVerified":true}'}}]});
  assert.equal(r.error,undefined);const args=r.calls[0].args;
  assert.equal(args[args.indexOf('--payload')+1],path.join(f.env.DIRECTORY,artifact.location.path));
  assert.equal(fs.existsSync(args[args.indexOf('--descriptor')+1]),false);
  assert.ok(r.logs.some(log=>log.kind==='summary'&&JSON.stringify(log).includes('does not attest')));
});
for(const relative of ['../escape','.cloudopsworks/out/../escape','.cloudopsworks/out/api\\escape','.cloudopsworks/out//api'])
  test(`inner payload denies unsafe path ${relative} before invoking CLI`,t=>{
    const f=payloadFixture(t,{location:{kind:'local',path:relative}});
    const r=runStep(action,'payloads',f);assert.equal(r.error?.message,'artifact-payload-path');assert.deepEqual(r.calls,[]);
  });
for(const result of [{exitCode:1,stdout:''},{stdout:'{"payloadVerified":false}'}])
  test(`unverified inner payload cannot emit success summary (${JSON.stringify(result)})`,t=>{
    const f=payloadFixture(t,{location:{kind:'local',path:'.cloudopsworks/out/api/1.2.3/main.zip'}});
    const r=runStep(action,'payloads',{...f,tools:[{result}]});
    assert.equal(r.error?.message,'artifact-inner-payload');assert.equal(r.logs.some(log=>log.kind==='summary'),false);
    assert.equal(fs.existsSync(path.join(f.root,'mainArtifact.json')),false);
  });

const pair=(artifactId='300')=>({artifactId,archiveDigest:'sha256:'+'a'.repeat(64)});
for(const [name,value] of [
 ['empty',[]],['not an array',{}],['duplicate IDs',[pair(),pair()]],
 ['unknown authority field',[{...pair(),producerJob:'build'}]],
 ['missing digest',[{artifactId:'300'}]],['zero ID',[pair('0')]],
 ['nondecimal ID',[pair('artifact-three-hundred')]],['wrong digest',[{...pair(),archiveDigest:'sha256:bad'}]],
 ['too many',Array.from({length:257},(_,i)=>pair(String(i+1)))],
])test(`artifact batch denies ${name} before external calls or outputs`,t=>{
 const f=fixture(t);f.env.ARTIFACT_SET=JSON.stringify(value);const r=download(f);
 assert.ok(r.error);assert.deepEqual(r.calls,[]);assert.deepEqual(r.outputs,{});
});
test('artifact batch enforces its serialized byte bound before parsing',t=>{
 const f=fixture(t);f.env.ARTIFACT_SET=' '.repeat(65537);const r=download(f);assert.equal(r.error?.message,'artifact-set-bound');assert.deepEqual(r.calls,[]);
});
function batch(t,failSecond=false){
 const f=fixture(t),second=fixture(t,({artifact})=>{artifact.id=301;if(failSecond)artifact.expired=true;});
 for(const api of second.api)if(api.args.artifact_id)api.args.artifact_id='301';
 f.env.ARTIFACT_SET=JSON.stringify([{...pair(),archiveDigest:digest(f.bytes)},{...pair('301'),archiveDigest:digest(second.bytes)}]);f.api.push(...second.api);f.fetches.push(...second.fetches);return f;
}
test('artifact batch uses each exact immutable ID and emits complete routing only after all transfers',t=>{
 const r=download(batch(t));assert.equal(r.error,undefined);
 const all=JSON.parse(fs.readFileSync(r.outputs['bundles-file']));assert.deepEqual(all.map(x=>x.artifactId),['300','301']);assert.equal(r.outputs.archive,undefined);
 assert.deepEqual(r.calls.filter(x=>x.method==='rest.actions.getArtifact').map(x=>x.args.artifact_id),['300','301']);
 assert.equal(new Set(all.map(x=>x.archive)).size,2);assert.deepEqual(r.unused,{api:0,tools:0,fetches:0});
});
test('late artifact batch metadata failure withholds the whole set despite first transfer success',t=>{
 const r=download(batch(t,true));assert.ok(r.error);assert.deepEqual(r.outputs,{});assert.equal(r.calls.filter(x=>x.kind==='fetch').length,1);
});
test('batch inner payload failure withholds every final record output',t=>{
 const artifact={location:{kind:'local',path:'.cloudopsworks/out/api/1.2.3/main.zip'}};
 const root=temporary(t),one=payloadFixture(t,artifact,root),two=payloadFixture(t,artifact,root);
 const verified=[one.bundle,two.bundle], metadata=path.join(root,'verified.json');fs.writeFileSync(metadata,JSON.stringify(verified),{mode:0o600});
 const r=runStep(action,'payloads',{env:{RUNNER_TEMP:root,VERIFIED_RECORDS_FILE:metadata},tools:[{result:{stdout:'{"payloadVerified":true}'}},{result:{stdout:'{"payloadVerified":false}'}}]});
 assert.equal(r.error?.message,'artifact-inner-payload');assert.deepEqual(r.outputs,{});assert.equal(r.logs.some(l=>l.kind==='summary'),false);
});
test('batch verified records are exposed together only after every inner payload succeeds',t=>{
 const artifact={location:{kind:'local',path:'.cloudopsworks/out/api/1.2.3/main.zip'}};
 const root=temporary(t),verified=[payloadFixture(t,artifact,root),payloadFixture(t,artifact,root)].map(f=>f.bundle),metadata=path.join(root,'verified.json');fs.writeFileSync(metadata,JSON.stringify(verified),{mode:0o600});
 const r=runStep(action,'payloads',{env:{RUNNER_TEMP:root,VERIFIED_RECORDS_FILE:metadata},tools:verified.map(()=>({result:{stdout:'{"payloadVerified":true}'}}))});
 assert.equal(r.error,undefined);assert.deepEqual(JSON.parse(r.outputs.records),verified);assert.equal(r.outputs.record,undefined);
});
test('aggregate batch metadata cap denies the later transfer without allocating huge fixtures',t=>{
 const f=batch(t);f.api[6].result.data.size_in_bytes=512*1024*1024;
 const r=download(f);assert.equal(r.error?.message,'artifact-set-size');assert.deepEqual(r.outputs,{});assert.equal(r.calls.filter(c=>c.kind==='fetch').length,1);
});
test('late outer archive failure withholds all unpacked bundle outputs',t=>{
 const f=batch(t),bad=Buffer.from('invalid second ZIP');f.api[6].result.data.digest=digest(bad);f.api[6].result.data.size_in_bytes=bad.length;f.fetches[1].base64=bad.toString('base64');
 const route=JSON.parse(f.env.ARTIFACT_SET);route[1].archiveDigest=digest(bad);f.env.ARTIFACT_SET=JSON.stringify(route);const r=download(f);
 assert.equal(r.calls.filter(call=>call.kind==='exec').length,2);assert.equal(r.calls.filter(call=>call.kind==='exec')[0].result.exitCode,0);
 assert.equal(r.error?.message,'artifact-archive');assert.deepEqual(r.outputs,{});
});
test('late typed-record failure withholds every records-set output',t=>{
 const root=temporary(t),one=recordsFixture(t,'BuildPlan',{kind:'BuildPlan'},[],root),two=recordsFixture(t,'BuildPlan',{kind:'BuildPlan'},[],root);
 const bundles=[one.bundle,two.bundle],metadata=path.join(root,'bundles.json');fs.writeFileSync(metadata,JSON.stringify(bundles),{mode:0o600});
 const r=runStep(action,'records',{env:{RUNNER_TEMP:root,BUNDLES_FILE:metadata,RECORD_KIND:'BuildPlan'},tools:[one.tools[0],{result:{exitCode:1,stdout:''}}]});
 assert.equal(r.error?.message,'artifact-record-contract');assert.deepEqual(r.outputs,{});
});
function discovered(t,artifacts){
 const f=fixture(t);f.artifact.name='components-200-2-api';Object.assign(f.env,{ARTIFACT_ID:'',ARCHIVE_DIGEST:'',COMPONENT:'api',RUN_ATTEMPT:'2'});
 f.api.unshift({method:'rest.actions.listWorkflowRunArtifacts',args:{run_id:'200',page:1},result:{data:{artifacts:artifacts||[{id:300,name:'components-200-2-api',digest:digest(f.bytes)}]}}});return f;
}
test('component artifact discovery is fixed-name routing followed by the same exact immutable-ID verifier',t=>{
 const r=download(discovered(t));assert.equal(r.error,undefined);assert.equal(JSON.parse(fs.readFileSync(r.outputs['bundles-file']))[0].artifactId,'300');
 assert.ok(r.calls.some(c=>c.method==='rest.actions.getArtifact'&&c.args.artifact_id==='300'));
});
for(const [name,artifacts] of [
 ['missing',[]],['wrong attempt',[{id:300,name:'components-200-1-api'}]],['wrong component',[{id:300,name:'components-200-2-other'}]],
 ['duplicate fixed name',[{id:300,name:'components-200-2-api'},{id:301,name:'components-200-2-api'}]],
])test(`component routing denies ${name} instead of choosing first/last artifact`,t=>{
 const r=download(discovered(t,artifacts));assert.equal(r.error?.message,'artifact-route-identity');assert.deepEqual(r.outputs,{});assert.equal(r.calls.length,1);
});

test('exact ID/digest route accepts component and attempt hints without switching to discovery', t => {
 const f=fixture(t);Object.assign(f.env,{COMPONENT:'api',RUN_ATTEMPT:'2'});
 const r=download(f);assert.equal(r.error,undefined,JSON.stringify(r));
 assert.equal(r.calls.some(call=>call.method==='rest.actions.listWorkflowRunArtifacts'),false);
 assert.equal(JSON.parse(fs.readFileSync(r.outputs['bundles-file']))[0].artifactId,'300');
});

test('normal23 BuildPlan permits exactly one raw bounded baseline companion', t => {
  const f=recordsFixture(t,'BuildPlan',normal23Plan(),['baseline.json']);
  const file=path.join(f.bundle.directory,'baseline.json');fs.writeFileSync(file,'{"raw":true}',{mode:0o600});
  const r=runStep(action,'records',{...f,tools:[],realCli:cli});assert.equal(r.error,undefined,JSON.stringify(r));
  assert.equal(fs.readFileSync(file,'utf8'),'{"raw":true}');
});
for(const [name,change,error] of [
 ['oversize',file=>fs.writeFileSync(file,Buffer.alloc(65537)),'artifact-file-bound'],
 ['public',file=>fs.chmodSync(file,0o644),'artifact-file-mode'],
 ['symlink',file=>{fs.renameSync(file,file+'.real');fs.symlinkSync(file+'.real',file);},'artifact-file-path'],
])test(`normal23 companion rejects ${name} with no output`,t=>{
 const f=recordsFixture(t,'BuildPlan',normal23Plan(),['baseline.json']);const file=path.join(f.bundle.directory,'baseline.json');
 fs.writeFileSync(file,'{}',{mode:0o600});
 const control=runStep(action,'records',{...f,tools:[],realCli:cli});assert.equal(control.error,undefined,JSON.stringify(control));
 assert.equal(control.calls.length,1);assert.equal(control.calls[0].command,'tronador');assert.equal(control.calls[0].result.exitCode,0);
 change(file);
 const r=runStep(action,'records',{...f,tools:[],realCli:cli});assert.equal(r.error?.message,error,JSON.stringify(r));assert.deepEqual(r.outputs,{});
 assert.equal(r.calls.length,1);assert.equal(r.calls[0].command,'tronador');assert.deepEqual(r.calls[0].args,['components','contracts','validate','--kind','BuildPlan']);assert.equal(r.calls[0].result.exitCode,0);
});

const normal23Fixtures=new URL('../../../../tronador-cli-v511/internal/components/testdata/contracts/valid/',import.meta.url);
const nativeFixture=name=>JSON.parse(fs.readFileSync(new URL(name+'.json',normal23Fixtures)));
function normal23Plan(){return nativeFixture('build-plan');}
for(const extra of ['third.json','nested/baseline.json','duplicate'])test(`normal23 closed BuildPlan layout rejects ${extra}`,t=>{
 const f=recordsFixture(t,'BuildPlan',normal23Plan(),['baseline.json',...(extra==='duplicate'?[]:[extra])]);fs.writeFileSync(path.join(f.bundle.directory,'baseline.json'),'{}',{mode:0o600});
 if(extra==='duplicate'){f.bundle.files.push('baseline.json');fs.writeFileSync(f.env.BUNDLES_FILE,JSON.stringify([f.bundle]));}
 const r=runStep(action,'records',{...f,tools:[],realCli:cli});assert.equal(r.error?.message,extra==='duplicate'?'artifact-bundle-files':'artifact-file-set');assert.deepEqual(r.outputs,{});
});
function normal23Other(t,kind,companion){
 const record=kind==='ScannerResult'?{apiVersion:'cloudopsworks.io/operations/v1',kind,scanner:'trivy',profile:'diagnostic',componentId:'api',sourceSha:'a'.repeat(40),status:'passed',required:true,artifactDigest:'sha256:'+'a'.repeat(64),correlationId:'normal23',errorCode:null}:nativeFixture(kind==='ComponentResult'?'component-result':'release-manifest');
 const f=recordsFixture(t,kind,record,companion?['baseline.json']:[]),directory=f.bundle.directory;
 const previous=kind==='BuildPlan'?'plan.json':'results/'+record.componentId+'.json',correct=kind==='ScannerResult'?'scanner-result.json':kind==='ReleaseManifest'?'manifest.json':previous;
 if(previous!==correct){fs.renameSync(path.join(directory,previous),path.join(directory,correct));f.bundle.files=f.bundle.files.map(x=>x===previous?correct:x);}
 fs.writeFileSync(f.env.PLAN_PATH,JSON.stringify(normal23Plan()),{mode:0o600});fs.chmodSync(f.env.PLAN_PATH,0o600);
 if(kind==='ReleaseManifest'){fs.writeFileSync(path.join(directory,'plan.json'),JSON.stringify(normal23Plan()),{mode:0o600});f.bundle.files.push('plan.json');}
 if(companion)fs.writeFileSync(path.join(directory,'baseline.json'),'{}',{mode:0o600});
 fs.writeFileSync(f.env.BUNDLES_FILE,JSON.stringify([f.bundle]));return f;
}
for(const kind of ['ScannerResult','ComponentResult','ReleaseManifest'])test(`normal23 companion rejected on otherwise native-valid ${kind}`,t=>{
 const control=normal23Other(t,kind,false),positive=runStep(action,'records',{...control,tools:[],realCli:cli});assert.equal(positive.error,undefined,JSON.stringify(positive));
 const bad=normal23Other(t,kind,true),r=runStep(action,'records',{...bad,tools:[],realCli:cli});assert.equal(r.error?.message,'artifact-file-set',JSON.stringify(r));assert.deepEqual(r.outputs,{});
});
test('normal23 late second native plan companion failure withholds complete set',t=>{
 const first=recordsFixture(t,'BuildPlan',normal23Plan(),['baseline.json']),second=recordsFixture(t,'BuildPlan',normal23Plan(),['baseline.json'],first.env.RUNNER_TEMP);
 fs.writeFileSync(path.join(first.bundle.directory,'baseline.json'),'{}',{mode:0o600});fs.writeFileSync(path.join(second.bundle.directory,'baseline.json'),Buffer.alloc(65537),{mode:0o600});
 fs.writeFileSync(first.env.BUNDLES_FILE,JSON.stringify([first.bundle,second.bundle]));const r=runStep(action,'records',{...first,tools:[],realCli:cli});
 assert.equal(r.error?.message,'artifact-file-bound');assert.equal(r.calls.filter(x=>x.command==='tronador').length,2);assert.deepEqual(r.outputs,{});
});
test('normal23 actual outer ZIP duplicate companion member rejects before facade outputs',t=>{
 const f=fixture(t);const zip=path.join(f.root,'duplicate.zip');const r=spawnSync('python3',['-c',"import zipfile,sys; z=zipfile.ZipFile(sys.argv[1],'w'); z.writestr('plan.json','{}'); z.writestr('baseline.json','{}'); z.writestr('baseline.json','{}'); z.close()",zip]);assert.equal(r.status,0);
 f.bytes=fs.readFileSync(zip);f.artifact.size_in_bytes=f.bytes.length;f.artifact.digest=digest(f.bytes);f.env.ARCHIVE_DIGEST=f.artifact.digest;f.fetches=[{url:signed,base64:f.bytes.toString('base64')}];
 const result=download(f);assert.equal(result.error?.message,'artifact-archive');assert.deepEqual(result.outputs,{});
});
