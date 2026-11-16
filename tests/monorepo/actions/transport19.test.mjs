// LOCAL actual YAML bodies and child processes; no hosted/cloud authority claim.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {runStep, root} from './action_test_support.mjs';

const transport = 'ci/monorepo/artifact/transport/action.yml';
const facade = 'ci/monorepo/artifact/action.yml';
function yaml(file) {
  const r = spawnSync('yq', ['-o=json', '.', path.join(root, file)], {encoding: 'utf8'});
  assert.equal(r.status, 0, r.stderr);
  return JSON.parse(r.stdout);
}
function fixture(t, rows = [{artifactId: '789', archiveDigest: 'sha256:' + 'a'.repeat(64)}]) {
  const directory = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'transport19-')));
  t.after(() => fs.rmSync(directory, {recursive: true, force: true}));
  const ingress = path.join(directory, 'ingress.json');
  fs.writeFileSync(ingress, JSON.stringify(rows), {mode: 0o600});
  return {directory, ingress, env: {RUNNER_TEMP: directory, GITHUB_REPOSITORY_ID: '123',
    RUN_ID: '456', MODE: 'scanner-file', ARTIFACT_SET_FILE: ingress}};
}
test('actual facade-to-transport and retained process mappings use metadata paths', () => {
  const action = yaml(facade), privateAction = yaml(transport);
  const steps = Object.fromEntries(action.runs.steps.map(step => [step.id, step]));
  const phases = Object.fromEntries(privateAction.runs.steps.map(step => [step.id, step]));
  assert.equal(steps.transport.uses, './bp/ci/monorepo/artifact/transport');
  assert.equal(steps.transport.with['artifact-set-file'], '${{ inputs.artifact-set-file }}');
  assert.equal(phases.retrieve.env.RESOLVED_FILE, '${{ steps.resolve.outputs.resolved-file }}');
  assert.equal(privateAction.outputs['bundles-file'].value, '${{ steps.retrieve.outputs.bundles-file }}');
  assert.equal(phases.retrieve.with.script.includes("core.setOutput('downloads'"), false);
  assert.equal(steps.records.env.BUNDLES_FILE, '${{ steps.transport.outputs.bundles-file }}');
  assert.equal(steps.payloads.env.VERIFIED_RECORDS_FILE, '${{ steps.records.outputs.verified-records-file }}');
  assert.equal(action.outputs['records-file'].value, '${{ steps.payloads.outputs.records-file }}');
});
test('file ingress resolves the full1792 collection into a private path without re-expansion', t => {
  const rows = Array.from({length: 1792}, (_, i) => ({artifactId: String(1000 + i), archiveDigest: 'sha256:' + 'a'.repeat(64)}));
  const f = fixture(t, rows), r = runStep(transport, 'resolve', {env: f.env});
  assert.equal(r.error, undefined, JSON.stringify(r));
  assert.deepEqual(Object.keys(r.outputs), ['resolved-file']);
  const file = r.outputs['resolved-file'];
  assert.ok(Buffer.byteLength(file) <= 4096);
  assert.equal(fs.statSync(file).mode & 0o777, 0o600);
  assert.equal(fs.statSync(path.dirname(file)).mode & 0o777, 0o700);
  assert.deepEqual(JSON.parse(fs.readFileSync(file)), rows.map(row => ({...row, runId: '456', artifactName: ''})));
  assert.deepEqual(r.calls, []);
});
for (const [name, mutate, expected] of [
  ['1793 entries', f => fs.writeFileSync(f.ingress, JSON.stringify(Array.from({length: 1793}, (_, i) => ({artifactId: String(i + 1), archiveDigest: 'sha256:' + 'a'.repeat(64)})))), 'artifact-set-count'],
  ['unknown authority', f => fs.writeFileSync(f.ingress, JSON.stringify([{artifactId: '789', archiveDigest: 'sha256:' + 'a'.repeat(64), trustedSource: true}])), 'artifact-set-fields'],
  ['duplicate ID', f => {const rows = JSON.parse(fs.readFileSync(f.ingress)); fs.writeFileSync(f.ingress, JSON.stringify([...rows, ...rows]));}, 'artifact-set-count'],
  ['oversized ingress', f => fs.writeFileSync(f.ingress, ' '.repeat(512 * 1024 + 1)), 'artifact-file-bound'],
  ['malformed ingress', f => fs.writeFileSync(f.ingress, '['), 'artifact-file-json'],
  ['symlink leaf', f => {fs.renameSync(f.ingress, f.ingress + '.real'); fs.symlinkSync(f.ingress + '.real', f.ingress);}, 'artifact-file-path'],
  ['symlink ancestor', f => {const actual = path.join(f.directory, 'actual'); fs.mkdirSync(actual, {mode: 0o700}); fs.renameSync(f.ingress, path.join(actual, 'data.json')); fs.symlinkSync(actual, path.join(f.directory, 'alias')); f.env.ARTIFACT_SET_FILE = path.join(f.directory, 'alias/data.json');}, 'artifact-file-path'],
  ['nonprivate metadata', f => fs.chmodSync(f.ingress, 0o644), 'artifact-file-mode'],
  ['nonregular metadata', f => {fs.unlinkSync(f.ingress); fs.mkdirSync(f.ingress);}, 'artifact-file-path'],
  ['conflicting inline route', f => {f.env.ARTIFACT_SET = '[]';}, 'artifact-file-routing'],
]) test(`file ingress denies ${name} at its intended reader without calls or output`, t => {
  const f = fixture(t); mutate(f);
  const r = runStep(transport, 'resolve', {env: f.env});
  assert.equal(r.error?.message, expected, JSON.stringify(r));
  assert.deepEqual(r.calls, []);
  assert.deepEqual(r.outputs, {});
});

test('native typed decoder receives original duplicate-key record bytes and denies before output', t => {
  const cli = process.env.TRONADOR_CLI;
  assert.ok(cli && fs.existsSync(cli), 'actual CLI is mandatory; never silently skipped');
  const f = fixture(t), directory = path.join(f.directory, 'artifact-data-duplicate');
  fs.mkdirSync(directory, {mode: 0o700});
  const extracted = path.join(directory, 'extracted'); fs.mkdirSync(extracted, {mode: 0o700});
  const record = JSON.parse(fs.readFileSync(new URL('../../../../tronador-cli-v511/internal/components/testdata/operations/scanner-result.json', import.meta.url)));
  const raw = '{"scanner":"semgrep",' + JSON.stringify(record).slice(1);
  assert.equal(JSON.parse(raw).scanner, record.scanner, 'ordinary JSON.parse would silently erase the duplicate');
  fs.writeFileSync(path.join(extracted, 'scanner-result.json'), raw, {mode: 0o600});
  const metadata = path.join(f.directory, 'bundles.json');
  fs.writeFileSync(metadata, JSON.stringify([{runId: '456', artifactId: '789', archiveDigest: 'sha256:' + 'a'.repeat(64),
    artifactName: '', archive: path.join(directory, 'archive.zip'), transport: path.join(directory, 'transport.json'),
    extract: extracted, directory: extracted, files: ['scanner-result.json']}]), {mode: 0o600});
  const r = runStep(facade, 'records', {realCli: cli, env: {...f.env, FILE_MODE: 'true',
    BUNDLES_FILE: metadata, RECORD_KIND: 'ScannerResult'}});
  assert.equal(r.error?.message, 'artifact-record-contract', JSON.stringify(r));
  assert.equal(r.calls.length, 1, 'intended native typed decoder must be reached');
  assert.notEqual(r.calls[0].result.exitCode, 0);
  assert.deepEqual(r.outputs, {});
});

function nativeArchives(t, count) {
  const cli = process.env.TRONADOR_CLI;
  assert.ok(cli && fs.existsSync(cli), 'actual CLI is mandatory; no silent skip');
  const f = fixture(t, []), longRoot=path.join(f.directory,'long-'+ 'x'.repeat(120),'y'.repeat(120),'z'.repeat(120));
  fs.mkdirSync(longRoot,{recursive:true,mode:0o700});
  const longIngress=path.join(longRoot,'ingress.json');fs.renameSync(f.ingress,longIngress);
  Object.assign(f,{directory:longRoot,ingress:longIngress});Object.assign(f.env,{RUNNER_TEMP:longRoot,ARTIFACT_SET_FILE:longIngress});
  const source = path.join(f.directory, 'source'); fs.mkdirSync(source, {mode: 0o700});
  const record = fs.readFileSync(new URL('../../../../tronador-cli-v511/internal/components/testdata/operations/scanner-result.json', import.meta.url));
  fs.writeFileSync(path.join(source, 'scanner-result.json'), record, {mode: 0o600});
  const zipped = spawnSync('zip', ['-q', '-X', path.join(f.directory, 'scanner.zip'), 'scanner-result.json'], {cwd: source});
  assert.equal(zipped.status, 0, zipped.stderr?.toString());
  const bytes = fs.readFileSync(path.join(f.directory, 'scanner.zip'));
  const digestResult = spawnSync('shasum', ['-a', '256', path.join(f.directory, 'scanner.zip')], {encoding: 'utf8'});
  assert.equal(digestResult.status, 0);
  const digest = 'sha256:' + digestResult.stdout.split(' ')[0];
  const rows = Array.from({length: count}, (_, i) => ({artifactId: String(i + 1000), archiveDigest: digest}));
  fs.writeFileSync(f.ingress, JSON.stringify(rows));
  const api = [], fetches = [];
  for (const row of rows) {
    api.push({method:'rest.repos.get',result:{data:{id:123}}},
      {method:'rest.actions.getWorkflowRun',result:{data:{id:456,repository:{id:123},head_sha:'a'.repeat(40)}}},
      {method:'rest.actions.getArtifact',result:{data:{id:Number(row.artifactId),workflow_run:{id:456},expired:false,digest,size_in_bytes:bytes.length}}},
      {method:'request:GET /repos/{owner}/{repo}/actions/artifacts/{artifact_id}/zip',result:{status:302,headers:{location:'https://transport.invalid/'+row.artifactId}}});
    fetches.push({url:'https://transport.invalid/'+row.artifactId,base64:bytes.toString('base64')});
  }
  return {...f, cli, rows, api, fetches};
}
test('all1792 real ZIPs and native typed ScannerResults traverse actual path-only child-process phases', t => {
  const f = nativeArchives(t, 1792);
  const resolved = runStep(transport, 'resolve', {env:f.env});
  assert.equal(resolved.error, undefined, JSON.stringify(resolved));
  const retrieved = runStep(transport, 'retrieve', {realCli:f.cli,env:{...f.env,RESOLVED_FILE:resolved.outputs['resolved-file']},api:f.api,fetches:f.fetches,timeout:180000});
  assert.equal(retrieved.error, undefined, JSON.stringify(retrieved));
  assert.deepEqual(Object.keys(retrieved.outputs), ['bundles-file']);
  assert.equal(retrieved.calls.filter(call=>call.kind==='exec').length,1792);
  const typed = runStep(facade, 'records', {realCli:f.cli,env:{...f.env,FILE_MODE:'true',RECORD_KIND:'ScannerResult',BUNDLES_FILE:retrieved.outputs['bundles-file']},timeout:180000});
  assert.equal(typed.error, undefined, JSON.stringify(typed));
  assert.deepEqual(Object.keys(typed.outputs), ['verified-records-file']);
  assert.equal(typed.calls.length,1792);
  const payloads = runStep(facade, 'payloads', {realCli:f.cli,env:{...f.env,FILE_MODE:'true',VERIFIED_RECORDS_FILE:typed.outputs['verified-records-file']},timeout:180000});
  assert.equal(payloads.error, undefined, JSON.stringify(payloads));
  assert.deepEqual(Object.keys(payloads.outputs), ['records-file']);
  const records = JSON.parse(fs.readFileSync(payloads.outputs['records-file']));
  assert.equal(records.length,1792);
  assert.ok(Buffer.byteLength(JSON.stringify(records))>131072,'expanded descriptor collection cannot fit a single environment string');
  assert.ok(f.directory.length>400,'capacity proof uses ordinary long private runner paths');
  assert.deepEqual(records.map(record=>record.artifactId),f.rows.map(row=>row.artifactId));
  const last=records.at(-1),original=fs.readFileSync(last.recordPath),bad=JSON.parse(original);bad.status='fabricated-success';fs.writeFileSync(last.recordPath,JSON.stringify(bad));
  try {
    const rejected=runStep(facade,'records',{realCli:f.cli,env:{...f.env,FILE_MODE:'true',RECORD_KIND:'ScannerResult',BUNDLES_FILE:retrieved.outputs['bundles-file']},timeout:180000});
    assert.equal(rejected.error?.message,'artifact-record-contract',JSON.stringify(rejected));assert.equal(rejected.calls.length,1792);assert.notEqual(rejected.calls.at(-1).result.exitCode,0);assert.deepEqual(rejected.outputs,{});
  } finally {fs.writeFileSync(last.recordPath,original);}

  for (const result of [resolved,retrieved,typed,payloads]) {
    for (const value of Object.values(result.outputs)) assert.ok(Buffer.byteLength(value)<=4096);
    assert.deepEqual(result.unused,{api:0,tools:0,fetches:0});
  }
});

for (const replacement of ['extra-field','array-like-object']) test(`original ingress reread denies ${replacement} after a real resolve before API calls`,t=>{
  const f=nativeArchives(t,1),resolved=runStep(transport,'resolve',{env:f.env});
  assert.equal(resolved.error,undefined,JSON.stringify(resolved));
  fs.writeFileSync(f.ingress,JSON.stringify(replacement==='extra-field'?[{...f.rows[0],grant:true}]:{length:1,0:f.rows[0]}));
  const result=runStep(transport,'retrieve',{realCli:f.cli,env:{...f.env,RESOLVED_FILE:resolved.outputs['resolved-file']},api:f.api,fetches:f.fetches});
  assert.equal(result.error?.message,'artifact-set-fields',JSON.stringify(result));
  assert.deepEqual(result.calls,[]);
  assert.deepEqual(result.outputs,{});
});


test('exact ID/digest plus component/attempt hints completes actual legacy facade chain',t=>{
 const f=nativeArchives(t,1),env={...f.env,MODE:'legacy',ARTIFACT_SET_FILE:'',ARTIFACT_ID:f.rows[0].artifactId,ARCHIVE_DIGEST:f.rows[0].archiveDigest,COMPONENT:'api',RUN_ATTEMPT:'2',RECORD_KIND:'ScannerResult'};
 const route=runStep(facade,'route',{env});assert.equal(route.error,undefined,JSON.stringify(route));assert.equal(route.outputs.mode,'legacy');
 const resolved=runStep(transport,'resolve',{env:{...env,MODE:route.outputs.mode}});assert.equal(resolved.error,undefined,JSON.stringify(resolved));
 const retrieved=runStep(transport,'retrieve',{realCli:f.cli,env:{...env,RESOLVED_FILE:resolved.outputs['resolved-file']},api:f.api,fetches:f.fetches});assert.equal(retrieved.error,undefined,JSON.stringify(retrieved));
 const typed=runStep(facade,'records',{realCli:f.cli,env:{...env,FILE_MODE:route.outputs['file-mode'],BUNDLES_FILE:retrieved.outputs['bundles-file']}});assert.equal(typed.error,undefined,JSON.stringify(typed));
 const payloads=runStep(facade,'payloads',{realCli:f.cli,env:{...env,FILE_MODE:route.outputs['file-mode'],VERIFIED_RECORDS_FILE:typed.outputs['verified-records-file']}});assert.equal(payloads.error,undefined,JSON.stringify(payloads));
 assert.equal(JSON.parse(payloads.outputs.records).length,1);assert.ok(fs.existsSync(payloads.outputs.record));assert.ok(fs.statSync(payloads.outputs.directory).isDirectory());
 assert.equal(retrieved.calls.some(call=>call.method==='rest.actions.listWorkflowRunArtifacts'),false);
});

for(const boundary of ['resolved','bundles','verified']) for(const mutation of ['unknown-field','duplicate-identity','symlink','ancestor-symlink','nonregular','nonprivate','oversized','count-overflow','truncated','outside-root']) test(`${boundary} private handoff denies ${mutation} at its intended reader`,t=>{
 const f=nativeArchives(t,1),resolved=runStep(transport,'resolve',{env:f.env});assert.equal(resolved.error,undefined,JSON.stringify(resolved));
 let file=resolved.outputs['resolved-file'],action=transport,phase='retrieve',env={...f.env,RESOLVED_FILE:file};
 if(boundary!=='resolved'){
  const retrieved=runStep(transport,'retrieve',{realCli:f.cli,env,api:f.api,fetches:f.fetches});assert.equal(retrieved.error,undefined,JSON.stringify(retrieved));
  file=retrieved.outputs['bundles-file'];action=facade;phase='records';env={...f.env,FILE_MODE:'true',RECORD_KIND:'ScannerResult',BUNDLES_FILE:file};
  if(boundary==='verified'){
   const typed=runStep(facade,'records',{realCli:f.cli,env});assert.equal(typed.error,undefined,JSON.stringify(typed));
   file=typed.outputs['verified-records-file'];phase='payloads';env={...f.env,FILE_MODE:'true',VERIFIED_RECORDS_FILE:file};
  }
 }
 let expected=boundary==='resolved'?'artifact-set-fields':'artifact-bundle-fields';
 if(mutation==='unknown-field'){const rows=JSON.parse(fs.readFileSync(file));rows[0].grant=true;fs.writeFileSync(file,JSON.stringify(rows));}
 if(mutation==='duplicate-identity'){const rows=JSON.parse(fs.readFileSync(file));fs.writeFileSync(file,JSON.stringify([...rows,...rows]));expected='artifact-set-count';}
 if(mutation==='count-overflow'){const row=JSON.parse(fs.readFileSync(file))[0];fs.writeFileSync(file,JSON.stringify(Array.from({length:1793},(_,i)=>({...row,artifactId:String(1000+i)}))));expected='artifact-set-count';}
 if(mutation==='truncated'){fs.writeFileSync(file,'[');expected='artifact-file-json';}
 if(mutation==='ancestor-symlink'){const parent=path.dirname(file);fs.renameSync(parent,parent+'.real');fs.symlinkSync(parent+'.real',parent);expected='artifact-file-path';}
 if(mutation==='nonregular'){fs.unlinkSync(file);fs.mkdirSync(file,{mode:0o700});expected='artifact-file-path';}
 if(mutation==='outside-root'){const outside=path.join(path.dirname(f.directory),'outside.json');fs.copyFileSync(file,outside);env[boundary==='resolved'?'RESOLVED_FILE':boundary==='bundles'?'BUNDLES_FILE':'VERIFIED_RECORDS_FILE']=outside;expected='artifact-file-path';}
 if(mutation==='symlink'){fs.renameSync(file,file+'.real');fs.symlinkSync(file+'.real',file);expected='artifact-file-path';}
 if(mutation==='nonprivate'){fs.chmodSync(file,0o644);expected='artifact-file-mode';}
 if(mutation==='oversized'){fs.writeFileSync(file,' '.repeat(16*1024*1024+1));expected='artifact-file-bound';}
 const result=runStep(action,phase,{realCli:f.cli,env});
 assert.equal(result.error?.message,expected,JSON.stringify(result));assert.deepEqual(result.calls,[]);assert.deepEqual(result.outputs,{});
});

test('native typed decoder rejects original invalid UTF-8 bytes rather than normalized replacement text',t=>{
 const f=nativeArchives(t,1),resolved=runStep(transport,'resolve',{env:f.env}),retrieved=runStep(transport,'retrieve',{realCli:f.cli,env:{...f.env,RESOLVED_FILE:resolved.outputs['resolved-file']},api:f.api,fetches:f.fetches});assert.equal(retrieved.error,undefined,JSON.stringify(retrieved));
 const bundle=JSON.parse(fs.readFileSync(retrieved.outputs['bundles-file']))[0],file=path.join(bundle.directory,'scanner-result.json'),bytes=fs.readFileSync(file),offset=bytes.indexOf('api');assert.ok(offset>=0);bytes[offset]=255;fs.writeFileSync(file,bytes);
 const result=runStep(facade,'records',{realCli:f.cli,env:{...f.env,FILE_MODE:'true',RECORD_KIND:'ScannerResult',BUNDLES_FILE:retrieved.outputs['bundles-file']}});
 assert.equal(result.error?.message,'artifact-record-contract',JSON.stringify(result));assert.equal(result.calls.length,1);assert.notEqual(result.calls[0].result.exitCode,0);assert.match(result.calls[0].result.stderr,/contract-invalid-utf8/);assert.deepEqual(result.outputs,{});
});

test('last of1792 corrupt real archives withholds the entire collection after1791 native extractions',t=>{
 const f=nativeArchives(t,1792),bad=Buffer.from('not a zip archive');
 const digestResult=spawnSync('shasum',['-a','256'],{input:bad,encoding:'utf8'});assert.equal(digestResult.status,0);const digest='sha256:'+digestResult.stdout.split(' ')[0];
 f.rows.at(-1).archiveDigest=digest;fs.writeFileSync(f.ingress,JSON.stringify(f.rows));f.api.at(-2).result.data.digest=digest;f.api.at(-2).result.data.size_in_bytes=bad.length;f.fetches.at(-1).base64=bad.toString('base64');
 const resolved=runStep(transport,'resolve',{env:f.env});assert.equal(resolved.error,undefined,JSON.stringify(resolved));
 const retrieved=runStep(transport,'retrieve',{realCli:f.cli,env:{...f.env,RESOLVED_FILE:resolved.outputs['resolved-file']},api:f.api,fetches:f.fetches,timeout:180000});
 assert.equal(retrieved.error?.message,'artifact-archive',JSON.stringify(retrieved));assert.deepEqual(retrieved.outputs,{});assert.equal(retrieved.calls.filter(call=>call.kind==='exec').length,1792);assert.notEqual(retrieved.calls.at(-1).result.exitCode,0);assert.deepEqual(retrieved.unused,{api:0,tools:0,fetches:0});
});

for(const mutation of ['run','name']) test(`genuine discovery reread denies substituted ${mutation} before API calls`,t=>{
 const f=nativeArchives(t,1),name='components-456-2-api',env={...f.env,MODE:'legacy',ARTIFACT_SET_FILE:'',COMPONENT:'api',RUN_ATTEMPT:'2'};
 const resolved=runStep(transport,'resolve',{env,api:[{method:'rest.actions.listWorkflowRunArtifacts',result:{data:{artifacts:[{id:1000,name,digest:f.rows[0].archiveDigest}]}}}]});assert.equal(resolved.error,undefined,JSON.stringify(resolved));
 const rows=JSON.parse(fs.readFileSync(resolved.outputs['resolved-file']));if(mutation==='run')rows[0].runId='455';else rows[0].artifactName='components-456-1-api';fs.writeFileSync(resolved.outputs['resolved-file'],JSON.stringify(rows));
 const result=runStep(transport,'retrieve',{realCli:f.cli,env:{...env,RESOLVED_FILE:resolved.outputs['resolved-file']}});assert.equal(result.error?.message,'artifact-route-binding',JSON.stringify(result));assert.deepEqual(result.calls,[]);assert.deepEqual(result.outputs,{});
});


for(const boundary of ['bundles','verified'])test(`${boundary} reader denies extraction-root escape before invoking downstream CLI`,t=>{
 const f=nativeArchives(t,1),resolved=runStep(transport,'resolve',{env:f.env}),retrieved=runStep(transport,'retrieve',{realCli:f.cli,env:{...f.env,RESOLVED_FILE:resolved.outputs['resolved-file']},api:f.api,fetches:f.fetches});assert.equal(retrieved.error,undefined,JSON.stringify(retrieved));
 let file=retrieved.outputs['bundles-file'],phase='records',env={...f.env,FILE_MODE:'true',RECORD_KIND:'ScannerResult',BUNDLES_FILE:file};
 if(boundary==='verified'){const typed=runStep(facade,'records',{realCli:f.cli,env});assert.equal(typed.error,undefined,JSON.stringify(typed));file=typed.outputs['verified-records-file'];phase='payloads';env={...f.env,FILE_MODE:'true',VERIFIED_RECORDS_FILE:file};}
 const rows=JSON.parse(fs.readFileSync(file));rows[0].directory=path.dirname(rows[0].directory);fs.writeFileSync(file,JSON.stringify(rows));
 const result=runStep(facade,phase,{realCli:f.cli,env});assert.equal(result.error?.message,'artifact-descriptor-path',JSON.stringify(result));assert.deepEqual(result.calls,[]);assert.deepEqual(result.outputs,{});
});


test('final typed handoff denies an escaped recordPath before payload invocation',t=>{
 const f=nativeArchives(t,1),resolved=runStep(transport,'resolve',{env:f.env}),retrieved=runStep(transport,'retrieve',{realCli:f.cli,env:{...f.env,RESOLVED_FILE:resolved.outputs['resolved-file']},api:f.api,fetches:f.fetches});assert.equal(retrieved.error,undefined,JSON.stringify(retrieved));
 const typed=runStep(facade,'records',{realCli:f.cli,env:{...f.env,FILE_MODE:'true',RECORD_KIND:'ScannerResult',BUNDLES_FILE:retrieved.outputs['bundles-file']}});assert.equal(typed.error,undefined,JSON.stringify(typed));
 const rows=JSON.parse(fs.readFileSync(typed.outputs['verified-records-file']));rows[0].recordPath=path.join(path.dirname(rows[0].directory),'scanner-result.json');fs.writeFileSync(typed.outputs['verified-records-file'],JSON.stringify(rows));
 const result=runStep(facade,'payloads',{realCli:f.cli,env:{...f.env,FILE_MODE:'true',VERIFIED_RECORDS_FILE:typed.outputs['verified-records-file']}});assert.equal(result.error?.message,'artifact-record-path',JSON.stringify(result));assert.deepEqual(result.calls,[]);assert.deepEqual(result.outputs,{});
});
