import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {runStep} from './action_test_support.mjs';
const source='ci/monorepo/source/action.yml', scan='ci/scan/trivy/action.yml';
const sha='a'.repeat(40), treeSha='b'.repeat(40);
const imageConfig='sha256:71f7bc3fe90c7d87c8ad07d66c7083eef5cfb8c346f434e8825048dbafb3c3b9';
const imageInput='/verified/private-oci-layout';
const imageRoot='sha256:a70823a6d17b91f4211df82cb77c78281329675111c3147d990ee9e442bb59dc';
function temporary(t){const dir=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'actual-source-scan-')));t.after(()=>fs.rmSync(dir,{recursive:true,force:true}));return dir;}
function snapshot(t,change={}){
  const root=temporary(t), bytes=Buffer.from('schemaVersion: 2\n');
  const blobSha=crypto.createHash('sha1').update(`blob ${bytes.length}\0`).update(bytes).digest('hex');
  const entry={path:'.cloudopsworks/cloudopsworks-ci.yaml',type:'blob',mode:'100644',size:bytes.length,sha:blobSha,...change.entry};
  const api=[{method:'rest.git.getCommit',args:{commit_sha:sha},result:{data:{sha,tree:{sha:treeSha},...change.commit}}},
    {method:'rest.git.getTree',args:{tree_sha:treeSha,recursive:'1'},result:{data:{truncated:false,tree:[entry],...change.tree}}},
    {method:'rest.git.getBlob',args:{file_sha:blobSha},result:{data:{sha:blobSha,encoding:'base64',content:bytes.toString('base64'),...change.blob}}}];
  return {root,bytes,api,env:{SOURCE_SHA:sha,RUNNER_TEMP:root}};
}
test('source snapshot reads immutable Git blobs and writes only private YAML configuration',t=>{
  const f=snapshot(t);const r=runStep(source,'snapshot',f);assert.equal(r.error,undefined);
  assert.deepEqual(fs.readFileSync(path.join(r.outputs.directory,'.cloudopsworks/cloudopsworks-ci.yaml')),f.bytes);
  assert.equal(fs.statSync(r.outputs.directory).mode&0o777,0o700);
  assert.equal(fs.statSync(path.join(r.outputs.directory,'.cloudopsworks/cloudopsworks-ci.yaml')).mode&0o777,0o600);
  assert.deepEqual(r.unused,{api:0,tools:0,fetches:0});
});
for(const [name,change] of [
  ['wrong immutable commit',{commit:{sha:'c'.repeat(40)}}],
  ['truncated tree',{tree:{truncated:true}}],
  ['duplicate path',{tree:{tree:[{path:'.cloudopsworks/a.yaml'},{path:'.cloudopsworks/a.yaml'}]}}],
  ['symlink',{entry:{mode:'120000'}}],
  ['traversal',{entry:{path:'.cloudopsworks/../outside.yaml'}}],
  ['oversize blob',{entry:{size:2097153}}],
  ['wrong blob digest',{blob:{content:Buffer.from('counterfeit').toString('base64')}}],
  ['wrong blob encoding',{blob:{encoding:'utf8'}}],
])test(`source snapshot denies ${name} without exposing directory`,t=>{
  const r=runStep(source,'snapshot',snapshot(t,change));assert.ok(r.error);assert.deepEqual(r.outputs,{});
});
test('configuration normalization uses finite config-only CLI without source files',t=>{
  const root=temporary(t), directory=path.join(root,'yaml-only');fs.mkdirSync(directory);
  const resolved={schemaVersion:2,components:{}};
  const r=runStep(source,'normalize',{env:{DIRECTORY:directory},tools:[{args:['components','validate','--workdir',directory,'--config-only','--json'],result:{stdout:JSON.stringify({valid:true,resolved})}}]});
  assert.equal(r.error,undefined);assert.deepEqual(JSON.parse(fs.readFileSync(r.outputs.configuration)),resolved);
  assert.equal(fs.statSync(r.outputs.configuration).mode&0o777,0o600);
});
function scanner(t,{report,outcome='success',required='true'}={}){
  const root=temporary(t), file=path.join(root,'trivy.json');
  if(report!==undefined){
    if(typeof report==='object')report={ArtifactName:imageInput,ArtifactType:'container_image',Metadata:{ImageID:imageConfig},...report,Results:Array.isArray(report.Results)?report.Results.map(result=>({Target:'fixture os (alpine 3.21)',...result})):report.Results};
    fs.writeFileSync(file,typeof report==='string'?report:JSON.stringify(report));
  }
  const env={REPORT_PATH:file,TOOL_OUTCOME:outcome,COMPONENT:'api',SOURCE_SHA:sha,ARTIFACT_DIGEST:imageRoot,PROFILE:'default',REQUIRED:required,IMAGE_INPUT:imageInput,IMAGE_CONFIG_DIGEST:imageConfig};
  // Echo the actual typed record only after the production script classifies it.
  const expected={apiVersion:'cloudopsworks.io/operations/v1',kind:'ScannerResult',scanner:'trivy',profile:'default',componentId:'api',sourceSha:sha,required:required==='true',artifactDigest:env.ARTIFACT_DIGEST,correlationId:'api'};
  return {root,env,expected};
}
const vulnerable={SchemaVersion:2,Results:[{Vulnerabilities:[{VulnerabilityID:'CVE-test',Severity:'HIGH'}]}]};
for(const [name,options,status,errorCode] of [
  ['unrecognized image content',{report:{SchemaVersion:2,Results:[]}},'unsupported-profile','trivy-no-recognized-target'],
  ['absent recognized targets',{report:{SchemaVersion:2}},'unsupported-profile','trivy-no-recognized-target'],
  ['optional no recognized targets',{report:{SchemaVersion:2,Results:[]},required:'false'},'unsupported-profile','trivy-no-recognized-target'],
  ['wrong result container',{report:{SchemaVersion:2,Results:{}}},'infrastructure-error','trivy-report-invalid'],
  ['low finding',{report:{SchemaVersion:2,Results:[{Vulnerabilities:[{VulnerabilityID:'CVE-low',Severity:'LOW'}]}]}},'passed',null],
  ['required findings',{report:vulnerable},'required-gate-failure',null],
  ['advisory findings',{report:vulnerable,required:'false'},'findings-advisory',null],
  ['tool failure',{report:vulnerable,outcome:'failure'},'infrastructure-error','trivy-tool-error'],
  ['missing report',{},'infrastructure-error','trivy-report-invalid'],
  ['invalid JSON',{report:'not JSON'},'infrastructure-error','trivy-report-invalid'],
  ['wrong schema',{report:{SchemaVersion:1,Results:[]}},'infrastructure-error','trivy-report-invalid'],
  ['malformed vulnerability',{report:{SchemaVersion:2,Results:[{Vulnerabilities:[{Severity:'HIGH'}]}]}},'infrastructure-error','trivy-report-invalid'],
])test(`actual Trivy reporter classifies ${name}`,t=>{
  const f=scanner(t,options),record={...f.expected,status,errorCode};
  const r=runStep(scan,'report',{env:f.env,tools:[{args:['components','contracts','validate','--kind','ScannerResult'],result:{stdout:JSON.stringify({record})}}]});
  assert.equal(r.error,undefined);assert.deepEqual(JSON.parse(r.calls[0].input),record);
  assert.equal(r.outputs.status,status);assert.deepEqual(JSON.parse(fs.readFileSync(r.outputs.result)),record);
  assert.deepEqual(r.failures,options.required!=='false'&&status!=='passed'?[status]:[]);
});
test('scanner contract rejection cannot expose a classified success',t=>{
  const f=scanner(t,{report:{SchemaVersion:2,Results:[]}});
  const r=runStep(scan,'report',{env:f.env,tools:[{result:{exitCode:1,stdout:''}}]});
  assert.equal(r.error?.message,'trivy-result-contract');assert.deepEqual(r.outputs,{});
});
