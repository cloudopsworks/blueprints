import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {runStep} from './action_test_support.mjs';
const binary=process.env.TRONADOR_CLI;
assert.ok(binary&&fs.existsSync(binary),'TRONADOR_CLI must name the actual freshly built CLI; integration is never silently skipped');
const fixture=fileURLToPath(new URL('../fixtures/composite_first/mixed/',import.meta.url));
function repository(t){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'composite-real-cli-')));
 t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const source=path.join(root,'source');fs.cpSync(fixture,source,{recursive:true});
 const home=path.join(root,'home');fs.mkdirSync(home);
 const env={PATH:'/opt/homebrew/opt/node@24/bin:'+process.env.PATH,HOME:home,RUNNER_TEMP:root,GOTOOLCHAIN:'local',GOPROXY:'off',GOSUMDB:'off',GOCACHE:path.join(root,'gocache'),GOMODCACHE:path.join(root,'gomodcache'),npm_config_offline:'true',npm_config_audit:'false',npm_config_fund:'false',GITHUB_REPOSITORY_ID:'123',GITHUB_REPOSITORY:'example/mixed'};
 function git(...args){const r=spawnSync('git',['-c','core.hooksPath=/dev/null','-c','user.name=Local Test','-c','user.email=test@example.invalid',...args],{cwd:source,env,encoding:'utf8',timeout:10000,maxBuffer:1048576});assert.equal(r.status,0,r.stderr);return r.stdout.trim();}
 git('init','-q');git('add','.');git('commit','-qm','base');const base=git('rev-parse','HEAD');
 function plan(){const head=git('rev-parse','HEAD');const r=runStep('ci/monorepo/plan/action.yml','plan',{realCli:binary,env:{...env,SOURCE_PATH:source,HEAD_SHA:head,BASE_SHA:base,VERSION:'1.2.3',PLAN_EVENT:'push',PR_NUMBER:'0'},timeout:30000});assert.equal(r.error,undefined,JSON.stringify(r));return {r,record:JSON.parse(fs.readFileSync(r.outputs.plan))};}
 return {root,source,env,git,base,plan};
}
for(const [name,change,expected] of [
 ['changed',f=>fs.appendFileSync(path.join(f.source,'components/node/index.js'),'\n// changed\n'),['node']],
 ['deleted',f=>fs.unlinkSync(path.join(f.source,'components/node/index.test.js')),['node']],
 ['renamed',f=>f.git('mv','components/node/index.test.js','components/go/renamed-node-test.js'),['go','node']],
 ['configuration-only',f=>fs.appendFileSync(path.join(f.source,'.cloudopsworks/cloudopsworks-ci.yaml'),'\n# comment only\n'),[]],
 ['shared',f=>{fs.mkdirSync(path.join(f.source,'shared'));fs.writeFileSync(path.join(f.source,'shared/input.txt'),'shared');},['go','node']],
])test(`real Git handoff selects ${name} using production planner and actual CLI`,t=>{
 const f=repository(t);change(f);f.git('add','-A');f.git('commit','-qm',name);
 const {record}=f.plan();assert.deepEqual(record.buildSelection.map(x=>x.componentId).sort(),expected);
 assert.equal(record.buildNoop,expected.length===0);
});
for(const component of ['node','go'])test(`real ${component} native build/test reaches honest Docker-blocked preview package`,t=>{
 const f=repository(t);fs.appendFileSync(path.join(f.source,`components/${component}/${component==='node'?'index.js':'main.go'}`),'\n// native build/test evidence\n');
 f.git('add','-A');f.git('commit','-qm','change');const {r:planned}=f.plan();
 const r=runStep('ci/monorepo/build/action.yml','build',{realCli:binary,env:{...f.env,SOURCE_PATH:f.source,PLAN_PATH:planned.outputs.plan,COMPONENT:component},timeout:180000});
 const operations=r.calls.filter(call=>call.kind==='exec');
 assert.deepEqual(operations.map(call=>call.args[1]),['build','test','package'],JSON.stringify(r));
 assert.equal(operations[0].result.exitCode,0,JSON.stringify(operations[0]));
 assert.equal(operations[1].result.exitCode,0,JSON.stringify(operations[1]));
 assert.notEqual(operations[2].result.exitCode,0,'No fake successful OCI package is permitted in this Docker-less local proof');
 assert.match(operations[2].result.stderr,/docker|container-build-failed/,JSON.stringify(operations[2]));
 assert.ok(r.error);assert.deepEqual(r.outputs,{});
 console.log(`LOCAL GAP ${component}: ${JSON.stringify({command:[operations[2].command,...operations[2].args],stderr:operations[2].result.stderr})}`);
});
function outerArchive(root,files){
 const archive=path.join(root,'outer.zip');
 const script='import json,sys,zipfile\na=json.load(sys.stdin)\nwith zipfile.ZipFile(a["archive"],"w",compression=zipfile.ZIP_STORED) as z:\n for name,body in a["files"]: z.writestr(name,body)\n';
 const r=spawnSync('python3',['-c',script],{input:JSON.stringify({archive,files}),encoding:'utf8',env:{PATH:process.env.PATH},timeout:10000,maxBuffer:1048576});assert.equal(r.status,0,r.stderr);return archive;
}
function bundleMetadata(root,directory,files,owner={}){
 fs.chmodSync(path.dirname(directory),0o700);fs.chmodSync(directory,0o700);
 for(const name of files){const file=path.join(directory,name);if(fs.existsSync(file)){fs.chmodSync(path.dirname(file),0o700);fs.chmodSync(file,0o600);}}
 const parent=path.dirname(directory),metadata=path.join(parent,'bundles.json');
 fs.writeFileSync(metadata,JSON.stringify([{runId:'456',artifactId:'789',archiveDigest:'sha256:'+'a'.repeat(64),artifactName:'',archive:path.join(parent,'archive.zip'),transport:path.join(parent,'transport.json'),extract:directory,directory,files,...owner}]),{mode:0o600});
 return metadata;
}
async function downloadArchive(f,archive,metadata={}){
 const {createHash}=await import('node:crypto');const bytes=fs.readFileSync(archive),digest='sha256:'+createHash('sha256').update(bytes).digest('hex'),head='d'.repeat(40);
 const route={...f.env,ARTIFACT_ID:'789',RUN_ID:'456',ARCHIVE_DIGEST:digest},resolved=runStep('ci/monorepo/artifact/transport/action.yml','resolve',{env:route});assert.equal(resolved.error,undefined,JSON.stringify(resolved));
 const r=runStep('ci/monorepo/artifact/transport/action.yml','retrieve',{realCli:binary,env:{...route,RESOLVED_FILE:resolved.outputs['resolved-file']},api:[
  {method:'rest.repos.get',result:{data:{id:123}}},
  {method:'rest.actions.getWorkflowRun',result:{data:{id:456,repository:{id:123},head_sha:head}}},
  {method:'rest.actions.getArtifact',result:{data:{id:789,workflow_run:{id:456,head_sha:head},expired:false,digest,size_in_bytes:bytes.length,...metadata}}},
  {method:'request:GET /repos/{owner}/{repo}/actions/artifacts/{artifact_id}/zip',result:{status:302,headers:{location:'https://storage.invalid/signed'}}},
 ],fetches:[{url:'https://storage.invalid/signed',base64:bytes.toString('base64')}]});
 return r;
}
test('real Go outer ZIP verification precedes actual embedded BuildPlan validation without any application descriptor',async t=>{
 const f=repository(t);fs.appendFileSync(path.join(f.source,'components/go/main.go'),'\n// changed\n');f.git('add','.');f.git('commit','-qm','changed');
 const {record}=f.plan();const archive=outerArchive(f.root,[['plan.json',JSON.stringify(record)]]),retrieved=await downloadArchive(f,archive);
 assert.equal(retrieved.error,undefined,JSON.stringify(retrieved));assert.equal(retrieved.calls.find(call=>call.kind==='exec').args.includes('--descriptor'),false);
 const records=runStep('ci/monorepo/artifact/action.yml','records',{realCli:binary,env:{...f.env,BUNDLES_FILE:retrieved.outputs['bundles-file'],RECORD_KIND:'BuildPlan'}});
 assert.equal(records.error,undefined,JSON.stringify(records));assert.deepEqual(JSON.parse(fs.readFileSync(records.outputs.record)),record);
});
for(const name of ['../escape','/absolute','safe/../../escape','safe\\escape'])test(`real Go unsafe outer archive ${name} never extracts`,async t=>{
 const f=repository(t),archive=outerArchive(f.root,[['plan.json','{}'],[name,'unsafe']]),r=await downloadArchive(f,archive);
 assert.ok(r.error,JSON.stringify(r));assert.deepEqual(r.outputs,{});
 const native=r.calls.find(call=>call.kind==='exec'),extract=native.args[native.args.indexOf('--extract-to')+1];
 assert.ok(!fs.existsSync(extract)||fs.readdirSync(extract).length===0);

});
for(const mutation of ['none','headSha','version','componentId','sourceSha','builtVersion'])test(`actual embedded typed result ${mutation==='none'?'accepts control only':'rejects wrong '+mutation} before payload verification`,t=>{
 const f=repository(t);fs.appendFileSync(path.join(f.source,'components/go/main.go'),'\n// linked control fixture\n');f.git('add','.');f.git('commit','-qm','changed');
 const {record:plan,r:planned}=f.plan(),directory=path.join(f.root,'artifact-data-control','extracted');fs.mkdirSync(path.join(directory,'results'),{recursive:true,mode:0o700});
 // Explicit descriptor-only unit data: never claimed as a built OCI/ZIP payload.
 const descriptor=(kind,format,p)=>({kind,format,digest:'sha256:'+'e'.repeat(64),sizeBytes:10,location:{kind:'local',path:p},sourceSha:plan.headSha,builtVersion:plan.version});
 const record={apiVersion:'cloudopsworks.io/v1',kind:'ComponentResult',repository:plan.repository,componentId:'go',headSha:plan.headSha,version:plan.version,purpose:'release',status:'succeeded',mainArtifact:descriptor('function','zip','.cloudopsworks/out/go/1.2.3/main.zip'),previewArtifact:descriptor('container','oci','.cloudopsworks/out/go/1.2.3/preview.oci.tar'),error:null};
 if(mutation==='headSha')record.headSha='f'.repeat(40);
 if(mutation==='version')record.version='9.9.9';
 if(mutation==='componentId')record.componentId='unknown';
 if(mutation==='sourceSha')record.mainArtifact.sourceSha='f'.repeat(40);
 if(mutation==='builtVersion')record.mainArtifact.builtVersion='9.9.9';
 fs.writeFileSync(path.join(directory,'results/go.json'),JSON.stringify(record));
 const r=runStep('ci/monorepo/artifact/action.yml','records',{realCli:binary,env:{...f.env,BUNDLES_FILE:bundleMetadata(f.root,directory,['results/go.json',record.mainArtifact.location.path,record.previewArtifact.location.path]),RECORD_KIND:'ComponentResult',PLAN_PATH:planned.outputs.plan}});
 if(mutation==='none')assert.equal(r.error,undefined,JSON.stringify(r));
 else {assert.equal(r.error?.message,'artifact-record-contract',JSON.stringify(r));assert.deepEqual(r.outputs,{});}
 assert.equal(r.calls.length,1);assert.equal(r.calls[0].args.includes('--descriptor'),false);
});

test('actual data download→unpack→typed records→inner verification→stage preserves REST name into complete manifest',async t=>{
 const f=repository(t);fs.mkdirSync(path.join(f.source,'shared'));fs.writeFileSync(path.join(f.source,'shared/change.txt'),'all components');f.git('add','.');f.git('commit','-qm','shared');
 const {record:plan,r:planned}=f.plan();const artifacts=fileURLToPath(new URL('../../../../tronador-cli-v511/internal/components/testdata/contracts/artifacts/',import.meta.url));
 const identity=JSON.parse(fs.readFileSync(path.join(artifacts,'identities.json'))),verified=[];
 for(const [index,component] of plan.components.entries()){
  const id=component.id,mainPath=`.cloudopsworks/out/${id}/1.2.3/main.zip`,previewPath=`.cloudopsworks/out/${id}/1.2.3/preview.oci.tar`;
  // Explicit existing archive/OCI UNIT fixtures, not actual packaged mixed apps.
  const descriptor=(kind,format,location,digest,sizeBytes)=>({kind,format,digest,sizeBytes,location:{kind:'local',path:location},sourceSha:plan.headSha,builtVersion:plan.version});
  const record={apiVersion:'cloudopsworks.io/v1',kind:'ComponentResult',repository:plan.repository,componentId:id,headSha:plan.headSha,version:plan.version,purpose:'release',status:'succeeded',mainArtifact:descriptor('function','zip',mainPath,identity.zip.digest,identity.zip.sizeBytes),previewArtifact:descriptor('container','oci',previewPath,identity.oci.rootDigest,identity.oci.rootSizeBytes),error:null};
  const archive=path.join(f.root,`${id}-unit-outer.zip`);
  const contents=[[`results/${id}.json`,Buffer.from(JSON.stringify(record)).toString('base64')],[mainPath,fs.readFileSync(path.join(artifacts,'app.zip')).toString('base64')],[previewPath,fs.readFileSync(path.join(artifacts,'image.oci.tar')).toString('base64')]];
  const zip=spawnSync('python3',['-c','import json,sys,zipfile,base64\na=json.load(sys.stdin)\nwith zipfile.ZipFile(a["path"],"w") as z:\n for n,b in a["files"]: z.writestr(n,base64.b64decode(b))\n'],{env:{PATH:process.env.PATH},input:JSON.stringify({path:archive,files:contents}),encoding:'utf8',timeout:10000,maxBuffer:1048576});assert.equal(zip.status,0,zip.stderr);
  const downloaded=await downloadArchive(f,archive,{name:`components-456-2-${id}`});
  assert.equal(downloaded.error,undefined,JSON.stringify(downloaded));
  const records=runStep('ci/monorepo/artifact/action.yml','records',{realCli:binary,env:{...f.env,BUNDLES_FILE:downloaded.outputs['bundles-file'],RECORD_KIND:'ComponentResult',PLAN_PATH:planned.outputs.plan}});assert.equal(records.error,undefined,JSON.stringify(records));
  const payloads=runStep('ci/monorepo/artifact/action.yml','payloads',{realCli:binary,env:{...f.env,VERIFIED_RECORDS_FILE:records.outputs['verified-records-file']}});assert.equal(payloads.error,undefined,JSON.stringify(payloads));
  const rows=JSON.parse(payloads.outputs.records);assert.equal(rows[0].artifactName,`components-456-2-${id}`,'metadata must flow from actual REST read through real artifact scripts');verified.push(...rows);
  const legacyRows=JSON.parse(fs.readFileSync(records.outputs['verified-records-file'])),mainFile=path.join(legacyRows[0].directory,mainPath),originalPayload=fs.readFileSync(mainFile),publishedBefore=fs.readdirSync(f.root).filter(name=>name.startsWith('artifact-verified-'));
  try {
   fs.writeFileSync(mainFile,'corrupt actual legacy payload');
   const rejected=runStep('ci/monorepo/artifact/action.yml','payloads',{realCli:binary,env:{...f.env,VERIFIED_RECORDS_FILE:records.outputs['verified-records-file']}});
   assert.equal(rejected.error?.message,'artifact-inner-payload',JSON.stringify(rejected));assert.deepEqual(rejected.outputs,{});assert.equal(rejected.logs.some(log=>log.kind==='summary'),false);assert.notEqual(rejected.calls.at(-1).result.exitCode,0);
   assert.deepEqual(fs.readdirSync(f.root).filter(name=>name.startsWith('artifact-verified-')),publishedBefore);
  } finally {fs.writeFileSync(mainFile,originalPayload);}

  const prepared=runStep('ci/scan/trivy/action.yml','prepare',{realCli:binary,realTar:true,env:{...f.env,ARTIFACT_PURPOSE:'preview',DIRECTORY:rows[0].directory,COMPONENT_RESULT:rows[0].recordPath,PLAN_PATH:planned.outputs.plan,COMPONENT:id,SOURCE_SHA:plan.headSha}});
  assert.equal(prepared.error,undefined,JSON.stringify(prepared));assert.equal(prepared.outputs.digest,identity.oci.rootDigest);assert.equal(prepared.outputs['config-digest'],'sha256:71f7bc3fe90c7d87c8ad07d66c7083eef5cfb8c346f434e8825048dbafb3c3b9');
  assert.equal(fs.statSync(prepared.outputs.input).mode&0o777,0o700);assert.ok(fs.existsSync(path.join(prepared.outputs.input,'oci-layout')));assert.ok(fs.existsSync(path.join(prepared.outputs.input,'index.json')));assert.equal(prepared.calls.at(-1).command,'tar');
  // Native OCI preparation only. No installed Trivy/DB or vulnerability-scan success claim.
  const imageFile=path.join(rows[0].directory,previewPath),original=fs.readFileSync(imageFile);
  try {fs.writeFileSync(imageFile,'corrupted OCI fixture');const rejected=runStep('ci/scan/trivy/action.yml','prepare',{realCli:binary,realTar:true,env:{...f.env,ARTIFACT_PURPOSE:'preview',DIRECTORY:rows[0].directory,COMPONENT_RESULT:rows[0].recordPath,PLAN_PATH:planned.outputs.plan,COMPONENT:id,SOURCE_SHA:plan.headSha}});assert.ok(rejected.error);assert.equal(rejected.calls.some(call=>call.command==='tar'),false);assert.deepEqual(rejected.outputs,{});} finally {fs.writeFileSync(imageFile,original);}
 }
 const stage=runStep('ci/monorepo/stage/action.yml','manifest',{realCli:binary,env:{...f.env,PLAN_PATH:planned.outputs.plan,VERIFIED_RECORDS:JSON.stringify(verified),RUN_ID:'456',RUN_ATTEMPT:'2'}});
 assert.equal(stage.error,undefined,JSON.stringify(stage));const manifest=JSON.parse(fs.readFileSync(stage.outputs.manifest));
 assert.equal(manifest.state,'complete');assert.deepEqual(manifest.components.map(c=>c.componentId).sort(),['go','node']);
 for(const component of manifest.components){assert.equal(component.mainArtifact.location.kind,'actions-artifact');assert.equal(component.mainArtifact.location.artifactName,`components-456-2-${component.componentId}`);}
});

for (const mutation of ['none', 'digest', 'unexpected-file']) test(`real CLI shared main/preview payload alias ${mutation}`, t => {
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'real-cli-shared-payload-')));
 t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const contracts=fileURLToPath(new URL('../../../../tronador-cli-v511/internal/components/testdata/contracts/valid/',import.meta.url));
 const plan=JSON.parse(fs.readFileSync(path.join(contracts,'build-plan.json'))),record=JSON.parse(fs.readFileSync(path.join(contracts,'component-result.json')));
 const planPath=path.join(root,'plan.json'),linked=path.join(root,'independent-linked.json'),directory=path.join(root,'artifact-data-control','extracted');
 fs.mkdirSync(path.join(directory,'results'),{recursive:true});
 if(mutation==='digest')record.previewArtifact.digest='sha256:'+'2'.repeat(64);
 fs.writeFileSync(planPath,JSON.stringify(plan));fs.writeFileSync(linked,JSON.stringify({plan}));
 const validation=spawnSync(binary,['components','contracts','validate','--kind','ComponentResult','--linked-context',linked],{input:JSON.stringify(record),encoding:'utf8',env:{PATH:process.env.PATH,HOME:root},timeout:10000,maxBuffer:4194304});
 assert.equal(validation.status,0,validation.stderr); // File-set/alias denial belongs to the actual records body, not a mocked contract rejection.
 fs.writeFileSync(path.join(directory,'results/api.json'),JSON.stringify(record));
 const files=['results/api.json',record.mainArtifact.location.path];
 // The descriptor-only fixture proves records/file-set acceptance, not native OCI packaging.
 fs.mkdirSync(path.dirname(path.join(directory,record.mainArtifact.location.path)),{recursive:true});
 fs.writeFileSync(path.join(directory,record.mainArtifact.location.path),'descriptor-only fixture');
 if(mutation==='unexpected-file'){files.push('unexpected.json');fs.writeFileSync(path.join(directory,'unexpected.json'),'{}');}
 const result=runStep('ci/monorepo/artifact/action.yml','records',{realCli:binary,env:{RUNNER_TEMP:root,BUNDLES_FILE:bundleMetadata(root,directory,files),RECORD_KIND:'ComponentResult',PLAN_PATH:planPath,HOME:root}});
 if(mutation==='none'){
  assert.equal(result.error,undefined,JSON.stringify(result));
  assert.deepEqual(JSON.parse(fs.readFileSync(result.outputs.record)),record);
 }else{assert.ok(result.error,JSON.stringify(result));assert.deepEqual(result.outputs,{});}
});

for(const [kind,mutation] of [
 ['ScannerResult','none'],['ScannerResult','invalid-status'],
 ['ReleaseManifest','none'],['ReleaseManifest','headSha'],['ReleaseManifest','version'],['ReleaseManifest','componentId'],
])test(`real CLI ${kind} control bundle ${mutation}`,t=>{
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'real-control-bundle-')));
 t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const contracts=fileURLToPath(new URL('../../../../tronador-cli-v511/internal/components/testdata/',import.meta.url));
 const directory=path.join(root,'artifact-data-control','extracted');fs.mkdirSync(directory,{recursive:true,mode:0o700});
 const filename=kind==='ScannerResult'?'scanner-result.json':'manifest.json';
 const record=JSON.parse(fs.readFileSync(path.join(contracts,kind==='ScannerResult'?'operations/scanner-result.json':'contracts/valid/release-manifest.json')));
 const files=[filename];
 if(kind==='ReleaseManifest'){
  const plan=JSON.parse(fs.readFileSync(path.join(contracts,'contracts/valid/build-plan.json')));
  fs.writeFileSync(path.join(directory,'plan.json'),JSON.stringify(plan));files.push('plan.json');
  if(mutation==='headSha')record.headSha='f'.repeat(40);
  if(mutation==='version'){record.version='9.9.9';record.tag='v9.9.9';}
  if(mutation==='componentId')record.components[0].componentId='foreign';
 }else if(mutation==='invalid-status')record.status='invented-success';
 fs.writeFileSync(path.join(directory,filename),JSON.stringify(record));
 const r=runStep('ci/monorepo/artifact/action.yml','records',{realCli:binary,env:{RUNNER_TEMP:root,BUNDLES_FILE:bundleMetadata(root,directory,files),RECORD_KIND:kind,HOME:root}});
 if(mutation==='none'){
  assert.equal(r.error,undefined,JSON.stringify(r));
  assert.deepEqual(JSON.parse(fs.readFileSync(r.outputs.record)),record);
  assert.ok(r.calls.some(call=>call.result?.exitCode===0));
  assert.equal(r.outputs.payloadVerified,undefined);
 }else{
  assert.ok(r.error,JSON.stringify(r));assert.deepEqual(r.outputs,{});
  assert.ok(r.calls.some(call=>call.result?.exitCode!==0),'actual Go linked/schema validator must reject false control semantics');
 }
 assert.equal(r.calls.some(call=>call.args.includes('--descriptor')),false);
});

for(const mutation of ['none','sourceSha','builtVersion','digest','path','original-run','selected'])test(`real CLI historical carried result ${mutation}`,t=>{
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'real-carried-result-')));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const contracts=fileURLToPath(new URL('../../../../tronador-cli-v511/internal/components/testdata/contracts/valid/',import.meta.url));
 const current=JSON.parse(fs.readFileSync(path.join(contracts,'build-plan.json')));
 const old=JSON.parse(fs.readFileSync(path.join(contracts,'component-result.json')));
 const manifest=JSON.parse(fs.readFileSync(path.join(contracts,'release-manifest.json')));
 const originalHead=old.headSha,originalVersion=old.version;
 current.baseSha=originalHead;current.headSha='c'.repeat(40);current.version='1.2.4';
 if(mutation!=='selected'){current.buildSelection=[];current.buildNoop=true;current.matrix.include=[];}
 const original={kind:'actions-artifact',repositoryId:current.repository.id,runId:'456',runAttempt:'2',artifactId:'789',artifactName:'components-456-2-api',path:old.mainArtifact.location.path};
 manifest.components[0].mainArtifact={...structuredClone(old.mainArtifact),location:original};
 manifest.components[0].previewArtifact={...structuredClone(old.previewArtifact),location:structuredClone(original)};
 if(mutation==='sourceSha')old.mainArtifact.sourceSha='d'.repeat(40);
 if(mutation==='builtVersion')old.mainArtifact.builtVersion='1.2.2';
 if(mutation==='digest')old.mainArtifact.digest='sha256:'+'d'.repeat(64);
 if(mutation==='path')old.mainArtifact.location.path='.cloudopsworks/out/api/1.2.3/other.oci.tar';
 const planPath=path.join(root,'current-plan.json'),carryPath=path.join(root,'authenticated-prior-manifest.json'),directory=path.join(root,'artifact-data-control','extracted');
 fs.writeFileSync(planPath,JSON.stringify(current));fs.writeFileSync(carryPath,JSON.stringify(manifest));fs.mkdirSync(path.join(directory,'results'),{recursive:true});
 fs.writeFileSync(path.join(directory,'results/api.json'),JSON.stringify(old));
 const files=[...new Set(['results/api.json',old.mainArtifact.location.path,old.previewArtifact.location.path])];
 const r=runStep('ci/monorepo/artifact/action.yml','records',{realCli:binary,env:{CARRY_MANIFEST:carryPath,PLAN_PATH:planPath,RECORD_KIND:'ComponentResult',HOME:root,RUNNER_TEMP:root,BUNDLES_FILE:bundleMetadata(root,directory,files,{artifactId:'789',artifactName:'components-456-2-api',runId:mutation==='original-run'?'455':'456'})}});
 if(mutation==='none'){
  assert.equal(r.error,undefined,JSON.stringify(r));const rows=JSON.parse(fs.readFileSync(r.outputs['verified-records-file']));
  assert.equal(rows[0].runId,'456');assert.equal(rows[0].artifactId,'789');
  const accepted=JSON.parse(fs.readFileSync(rows[0].recordPath));
  assert.equal(accepted.headSha,originalHead);assert.equal(accepted.version,originalVersion);
  assert.equal(accepted.mainArtifact.sourceSha,originalHead);assert.equal(accepted.mainArtifact.builtVersion,originalVersion);
 }else{assert.ok(r.error,JSON.stringify(r));assert.deepEqual(r.outputs,{});}
 assert.equal(r.calls.some(call=>call.args.includes('build')||call.args.includes('package')),false);
});
