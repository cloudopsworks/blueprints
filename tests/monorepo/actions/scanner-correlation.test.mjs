import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {runStep} from './action_test_support.mjs';
const action='ci/scan/trivy/action.yml';
const expectedConfig='sha256:71f7bc3fe90c7d87c8ad07d66c7083eef5cfb8c346f434e8825048dbafb3c3b9';
function temporary(t){const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'scanner-correlation-')));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));return root;}
for(const [name,report] of [
 ['empty image result',{SchemaVersion:2,ArtifactName:'/verified/layout',ArtifactType:'container_image',Metadata:{ImageID:expectedConfig},Results:[]}],
 ['wrong target type',{SchemaVersion:2,ArtifactName:'/verified/layout',ArtifactType:'filesystem',Metadata:{ImageID:expectedConfig},Results:[{Target:'unrelated/package-lock.json',Class:'lang-pkgs',Type:'npm',Vulnerabilities:[]}]}],
 ['unrelated image identity',{SchemaVersion:2,ArtifactName:'/verified/layout',ArtifactType:'container_image',Metadata:{ImageID:'sha256:'+'b'.repeat(64),RepoDigests:['unrelated.invalid/app@sha256:'+'d'.repeat(64)]},Results:[{Target:'unrelated (alpine 3.21)',Class:'os-pkgs',Type:'alpine',Vulnerabilities:[]}]}],
])test(`scanner must not green ${name} merely because copied artifactDigest is present`,t=>{
 const root=temporary(t),file=path.join(root,'report.json');fs.writeFileSync(file,JSON.stringify(report));
 const r=runStep(action,'report',{env:{REPORT_PATH:file,TOOL_OUTCOME:'success',IMAGE_INPUT:'/verified/layout',IMAGE_CONFIG_DIGEST:expectedConfig,COMPONENT:'api',SOURCE_SHA:'a'.repeat(40),ARTIFACT_DIGEST:'sha256:'+'c'.repeat(64),PROFILE:'default',REQUIRED:'true'},tools:[{result:{stdout:'{"record":{}}'}}]});
 assert.ok(r.error||['infrastructure-error','unsupported-profile'].includes(r.outputs.status),JSON.stringify(r));
 assert.notEqual(r.outputs.status,'passed');
});
test('scanner prepare rejects an empty outer directory rather than treating it as effective image content',t=>{
 const root=temporary(t),directory=path.join(root,'empty-outer-bundle');fs.mkdirSync(directory);
 const r=runStep(action,'prepare',{env:{DIRECTORY:directory,RUNNER_TEMP:root,COMPONENT:'api',SOURCE_SHA:'a'.repeat(40)}});
 assert.ok(r.error,JSON.stringify(r));
});
test('matching target string cannot bless an unrelated image config identity for actual verified OCI fixture bytes',t=>{
 const root=temporary(t),input=path.join(root,'verified-image.oci.tar');
 const fixtures=new URL('../../../../tronador-cli-v511/internal/components/testdata/contracts/artifacts/',import.meta.url);
 fs.copyFileSync(new URL('image.oci.tar',fixtures),input);
 const identities=JSON.parse(fs.readFileSync(new URL('identities.json',fixtures)));
 const file=path.join(root,'report.json');
 fs.writeFileSync(file,JSON.stringify({SchemaVersion:2,ArtifactName:input,ArtifactType:'container_image',Metadata:{ImageID:'sha256:'+'f'.repeat(64)},Results:[{Target:'unrelated (alpine 3.21)',Class:'os-pkgs',Type:'alpine',Vulnerabilities:[]}]}));
 const r=runStep(action,'report',{env:{REPORT_PATH:file,TOOL_OUTCOME:'success',IMAGE_INPUT:input,IMAGE_CONFIG_DIGEST:'sha256:71f7bc3fe90c7d87c8ad07d66c7083eef5cfb8c346f434e8825048dbafb3c3b9',COMPONENT:'api',SOURCE_SHA:'a'.repeat(40),ARTIFACT_DIGEST:identities.oci.rootDigest,PROFILE:'default',REQUIRED:'true'},tools:[{result:{stdout:'{"record":{}}'}}]});
 assert.ok(r.error||['infrastructure-error','unsupported-profile'].includes(r.outputs.status),JSON.stringify(r));
 assert.notEqual(r.outputs.status,'passed');
});
function preparation(t,verification={}){
 const root=temporary(t),directory=path.join(root,'bundle'),relative='.cloudopsworks/out/api/1.2.3/preview.oci.tar';fs.mkdirSync(path.dirname(path.join(directory,relative)),{recursive:true});
 fs.copyFileSync(new URL('../../../../tronador-cli-v511/internal/components/testdata/contracts/artifacts/image.oci.tar',import.meta.url),path.join(directory,relative));
 const plan=path.join(root,'plan.json'),recordPath=path.join(root,'result.json');fs.writeFileSync(plan,'{}');fs.writeFileSync(recordPath,'{}');
 const rootDigest='sha256:a70823a6d17b91f4211df82cb77c78281329675111c3147d990ee9e442bb59dc',configDigest='sha256:71f7bc3fe90c7d87c8ad07d66c7083eef5cfb8c346f434e8825048dbafb3c3b9';
 const record={componentId:'api',headSha:'a'.repeat(40),status:'succeeded',previewArtifact:{format:'oci',digest:rootDigest,location:{kind:'local',path:relative}}};
 return {root,directory,relative,configDigest,rootDigest,env:{ARTIFACT_PURPOSE:'preview',DIRECTORY:directory,COMPONENT_RESULT:recordPath,PLAN_PATH:plan,COMPONENT:'api',SOURCE_SHA:'a'.repeat(40),RUNNER_TEMP:root},tools:[
 {prefix:['components','contracts','validate','--kind','BuildPlan'],result:{stdout:'{"record":{}}'}},
 {prefix:['components','contracts','validate','--kind','ComponentResult'],result:{stdout:JSON.stringify({record})}},
 {prefix:['components','artifacts','verify','--mode','payload'],result:{stdout:JSON.stringify({payloadVerified:true,digest:rootDigest,imageConfigDigests:[configDigest],...verification})}},
 {command:'tar',prefix:['--extract','--file'],result:{exitCode:0}},
 ]};
}
test('scanner prepares exact OCI directory using fixed native tar only after payload and unique config verification',t=>{
 const f=preparation(t),r=runStep(action,'prepare',f);assert.equal(r.error,undefined,JSON.stringify(r));
 assert.deepEqual(r.calls.map(c=>c.command),['tronador','tronador','tronador','tar']);
 assert.deepEqual(r.calls[3].args,['--extract','--file',path.join(f.directory,f.relative),'--directory',r.outputs.input,'--no-same-owner','--no-same-permissions']);
 assert.equal(fs.statSync(r.outputs.input).mode&0o777,0o700);assert.equal(r.outputs.digest,f.rootDigest);assert.equal(r.outputs['config-digest'],f.configDigest);
});
for(const [name,verification] of [['rejected payload',{payloadVerified:false}],['wrong root digest',{digest:'sha256:'+'f'.repeat(64)}],['absent config',{imageConfigDigests:[]}],['ambiguous configs',{imageConfigDigests:['sha256:'+'d'.repeat(64),'sha256:'+'e'.repeat(64)]}]])test(`scanner never invokes native tar for ${name}`,t=>{
 const r=runStep(action,'prepare',preparation(t,verification));assert.ok(r.error);assert.equal(r.calls.some(c=>c.command==='tar'),false);assert.deepEqual(r.outputs,{});
});

test('explicit main purpose scans main OCI even when a distinct preview OCI exists', t => {
 const f=preparation(t),record=JSON.parse(f.tools[1].result.stdout).record;
 const main={...structuredClone(record.previewArtifact),digest:'sha256:'+'b'.repeat(64),location:{kind:'local',path:'.cloudopsworks/out/api/1.2.3/main.oci.tar'}};
 fs.copyFileSync(path.join(f.directory,f.relative),path.join(f.directory,main.location.path));
 record.mainArtifact=main;f.tools[1].result.stdout=JSON.stringify({record});
 f.tools[2].result.stdout=JSON.stringify({payloadVerified:true,digest:main.digest,imageConfigDigests:[f.configDigest]});
 f.env.ARTIFACT_PURPOSE='main';
 const r=runStep(action,'prepare',f);
 assert.equal(r.error,undefined,JSON.stringify(r));
 assert.equal(r.outputs.digest,main.digest);
 assert.equal(r.calls[2].args[r.calls[2].args.indexOf('--payload')+1],path.join(f.directory,main.location.path));
});
for(const purpose of ['', 'arbitrary', 'mainArtifact', 'MAIN'])test(`scanner denies absent or unknown artifact purpose ${JSON.stringify(purpose)}`,t=>{
 const f=preparation(t);f.env.ARTIFACT_PURPOSE=purpose;
 const r=runStep(action,'prepare',f);
 assert.ok(r.error,JSON.stringify(r));assert.deepEqual(r.outputs,{});
 assert.equal(r.calls.some(call=>call.command==='tar'),false);
});
test('requested main image cannot be substituted by preview when main is not OCI',t=>{
 const f=preparation(t),record=JSON.parse(f.tools[1].result.stdout).record;
 record.mainArtifact={format:'zip',location:{kind:'local',path:'.cloudopsworks/out/api/1.2.3/main.zip'}};
 f.tools[1].result.stdout=JSON.stringify({record});f.env.ARTIFACT_PURPOSE='main';
 const r=runStep(action,'prepare',f);
 assert.ok(r.error,JSON.stringify(r));assert.deepEqual(r.outputs,{});
 assert.equal(r.calls.some(call=>call.command==='tar'),false);
});
