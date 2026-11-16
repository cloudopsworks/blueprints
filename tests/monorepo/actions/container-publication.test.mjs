import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {root, runStep} from './action_test_support.mjs';
const action='cd/deploy/container/action.yml';
const rawManifest=JSON.stringify({schemaVersion:2,testOnly:true});
const digest='sha256:'+createHash('sha256').update(rawManifest).digest('hex'), repository='ghcr.io/example/api';
function temporary(t){const directory=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'container-action-')));t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));return directory;}
function fixture(t){
 const directory=temporary(t),descriptor=path.join(directory,'artifact.json'),payload=path.join(directory,'image.oci.tar'),authfile=path.join(directory,'auth.json');
 const artifact={kind:'container',format:'oci',digest,sizeBytes:12,location:{kind:'local',path:'.cloudopsworks/out/api/1.2.3/main.oci.tar'},sourceSha:'a'.repeat(40),builtVersion:'1.2.3'};
 fs.writeFileSync(descriptor,JSON.stringify(artifact),{mode:0o600});fs.writeFileSync(payload,'test fixture',{mode:0o600});fs.writeFileSync(authfile,JSON.stringify({auths:{'ghcr.io':{auth:Buffer.from('example:private-test-token').toString('base64')}}}),{mode:0o600});
 return {directory,descriptor,payload,authfile,artifact,env:{RUNNER_TEMP:directory,COMPONENT_MODE:'true',ARTIFACT_PATH:descriptor,PAYLOAD_PATH:payload,DESTINATION:repository,EXPECTED_DIGEST:digest,AUTH_CONTEXT:authfile},tools:[
 {command:'skopeo',args:['--version'],result:{stdout:'skopeo version 1.13.3\n'}},
 {args:['components','contracts','validate','--kind','Artifact'],result:{stdout:JSON.stringify({valid:true,record:artifact})}},
 {prefix:['components','artifacts','verify','--mode','payload'],result:{stdout:JSON.stringify({payloadVerified:true,digest})}},
 {command:'skopeo',prefix:['--command-timeout','5m','copy'],result:{stdout:''}},
 {command:'skopeo',prefix:['--command-timeout','30s','inspect'],result:{stdout:rawManifest}},
 ]};
}
function publish(f){return runStep(action,'publish-component',{env:f.env,tools:f.tools});}
test('legacy Docker transport uses fixed original native argv without rebuilding',()=>{
 const r=runStep(action,'legacy-docker',{env:{STEPS_DOCKER_REGISTRY_RESULT:'registry.example',INPUTS_PROJECT_OWNER:'owner',INPUTS_PROJECT_KEY:'project',DOCKER_CONFIG:'/private/login'},tools:[{command:'docker',args:['image','load','--input','docker-image.tar']},{command:'docker',args:['image','push','--all-tags','registry.example/owner/project']}]});
 assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.calls.length,2);assert.equal(r.calls.some(c=>c.env),false,'legacy credentials remain inherited');
});
for(const text of ['v1\nlatest\nstable\nv1\n','v1\n\tlatest   stable\nlatest\n','v1\r\nlatest\r\n',''])test(`legacy Crane preserves first-line and whitespace tag behavior ${JSON.stringify(text)}`,t=>{
 const directory=temporary(t),tags=path.join(directory,'docker-tags.list');fs.writeFileSync(tags,text);
 const first=text.split('\n')[0],repository='registry.example/owner/project',target=repository+':'+first;
 const tools=[{command:'crane',args:['push','docker-image.tar',target]},...text.split(/[ \t\n]+/).filter(tag=>tag&&tag!==first).map(tag=>({command:'crane',args:['tag',target,tag]}))];
 const r=runStep(action,'legacy-crane',{env:{GITHUB_WORKSPACE:directory,STEPS_DOCKER_REGISTRY_RESULT:'registry.example',INPUTS_PROJECT_OWNER:'owner',INPUTS_PROJECT_KEY:'project'},tools});
 assert.equal(r.error,undefined,JSON.stringify(r));assert.deepEqual(r.unused,{api:0,tools:0,fetches:0});
 assert.deepEqual(r.logs.filter(x=>x.kind==='console').map(x=>x.args[0]),['::group::Push Docker image from tar using Crane','::notice::Pushed Docker image to '+target,...text.split(/[ \t\n]+/).filter(tag=>tag&&tag!==first).map(tag=>'::notice::Tagged Docker image to '+repository+':'+tag),'::endgroup::']);
});
test('component publishes only verified OCI bytes to the exact digest destination and reads it back',t=>{
 const f=fixture(t),r=publish(f);assert.equal(r.error,undefined,JSON.stringify(r));
 assert.deepEqual(r.calls.map(x=>x.command),['skopeo','tronador','tronador','skopeo','skopeo']);
 const copy=r.calls[3],snapshot=copy.env.HOME;assert.deepEqual(copy.args,['--command-timeout','5m','copy','--all','--preserve-digests','--dest-tls-verify=true','--dest-authfile',path.join(snapshot,'auth.json'),'oci-archive:'+path.join(snapshot,'image.oci.tar'),'docker://'+repository+'@'+digest]);
 assert.equal(copy.env.REGISTRY_AUTH_FILE,path.join(snapshot,'auth.json'));assert.equal(fs.existsSync(snapshot),false,'private snapshot and credentials cleaned after readback');assert.equal(copy.env.AWS_ACCESS_KEY_ID,undefined);assert.equal(copy.env.GH_TOKEN,undefined);
 assert.equal(r.outputs.reference,repository+'@'+digest);assert.equal(r.outputs.digest,digest);assert.equal(r.outputs.status,'published');assert.equal(JSON.stringify(r).includes('private-test-token'),false);
});
for(const value of ['ghcr.io/example/api:latest','https://ghcr.io/example/api','ghcr.io/../api','evil.invalid/example/api','ghcr.io/Example/api','ghcr.io/example/api@'+digest])test(`component refuses unsafe or unauthenticated destination ${value}`,t=>{
 const f=fixture(t);f.env.DESTINATION=value;const r=publish(f);assert.ok(r.error,JSON.stringify(r));assert.deepEqual(r.outputs,{});assert.equal(r.calls.length,0);
});
for(const [name,mutate] of [
 ['unknown mode',f=>{f.env.COMPONENT_MODE='yes';}],
 ['mutable digest',f=>{f.env.EXPECTED_DIGEST='latest';}],
 ['public auth file',f=>fs.chmodSync(f.authfile,0o644)],
 ['credential helper',f=>fs.writeFileSync(f.authfile,JSON.stringify({auths:{},credHelpers:{'ghcr.io':'custom'}}))],
 ['payload transport injection',f=>{const p=f.payload+':foreign';fs.renameSync(f.payload,p);f.env.PAYLOAD_PATH=p;}],
 ['symlink payload',f=>{const p=f.payload+'.link';fs.symlinkSync(f.payload,p);f.env.PAYLOAD_PATH=p;}],
 ['symlink descriptor',f=>{const p=f.descriptor+'.link';fs.symlinkSync(f.descriptor,p);f.env.ARTIFACT_PATH=p;}],
])test(`component denies ${name} before native calls`,t=>{const f=fixture(t);mutate(f);const r=publish(f);assert.ok(r.error,JSON.stringify(r));assert.deepEqual(r.outputs,{});assert.equal(r.calls.length,0);});
for(const [name,index,result] of [
 ['wrong tool version',0,{stdout:'skopeo version 1.14.0\n'}],
 ['invalid typed descriptor',1,{exitCode:1,stderr:'private'}],
 ['wrong descriptor digest',1,{stdout:JSON.stringify({valid:true,record:{format:'oci',kind:'container',digest:'sha256:'+'c'.repeat(64),location:{kind:'local'}}})}],
 ['payload verification failure',2,{exitCode:1}],
 ['wrong payload digest',2,{stdout:JSON.stringify({payloadVerified:true,digest:'sha256:'+'c'.repeat(64)})}],
 ['copy failure',3,{exitCode:1,stderr:'secret-token'}],
 ['readback failure',4,{exitCode:1,stderr:'secret-token'}],
 ['rewritten digest',4,{stdout:'sha256:'+'d'.repeat(64)}],
])test(`component never succeeds on ${name}`,t=>{const f=fixture(t);f.tools[index].result=result;const r=publish(f);assert.ok(r.error,JSON.stringify(r));assert.deepEqual(r.outputs,{});if(index<3)assert.equal(r.calls.some(c=>c.args?.includes('copy')),false);assert.equal(JSON.stringify(r.logs).includes('secret-token'),false);});
test('component graph skips all legacy source reads, downloads, login and mutable tool setup',()=>{
 const p=spawnSync('yq',['-o=json','-I=0','.',path.join(root,action)],{encoding:'utf8'});assert.equal(p.status,0,p.stderr);const a=JSON.parse(p.stdout);
 assert.equal(a.inputs['component-mode'].default,'false');
 for(const step of a.runs.steps.filter(s=>s.id!=='publish-component'&&s.id!=='mode'))assert.ok(step.if?.includes("inputs.component-mode != 'true'"),JSON.stringify(step));
 assert.equal(a.runs.steps.some(s=>s.with?.script?.includes('publication.py')),false);
});

test('actual offline CLI verifies the real OCI fixture before the recorded native publication',t=>{
 const binary=process.env.TRONADOR_CLI;
 assert.ok(binary&&fs.existsSync(binary),'TRONADOR_CLI must name the compiled local test CLI');
 const f=fixture(t),assetRoot=path.resolve(root,'../tronador-cli-v511/internal/components/testdata/contracts');
 const record=JSON.parse(fs.readFileSync(path.join(assetRoot,'valid/oci-image-valid.json'))),artifact=record.mainArtifact;
 fs.writeFileSync(f.descriptor,JSON.stringify(artifact));fs.copyFileSync(path.join(assetRoot,'artifacts/image.oci.tar'),f.payload);
 const manifest=spawnSync('tar',['-xOf',f.payload,'blobs/sha256/'+artifact.digest.slice(7)],{encoding:'utf8'});assert.equal(manifest.status,0,manifest.stderr);
 f.env.EXPECTED_DIGEST=artifact.digest;
 const r=runStep(action,'publish-component',{env:f.env,realCli:binary,tools:[f.tools[0],f.tools[3],{...f.tools[4],result:{stdout:manifest.stdout}}]});
 assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs.reference,repository+'@'+artifact.digest);
 const checks=r.calls.filter(call=>call.command==='tronador');assert.equal(checks.length,2);assert.equal(checks.every(call=>call.result.exitCode===0),true);
});
test('actual offline CLI rejects corrupt OCI bytes before any registry command',t=>{
 const binary=process.env.TRONADOR_CLI;
 assert.ok(binary&&fs.existsSync(binary),'TRONADOR_CLI must name the compiled local test CLI');
 const f=fixture(t),assetRoot=path.resolve(root,'../tronador-cli-v511/internal/components/testdata/contracts');
 const artifact=JSON.parse(fs.readFileSync(path.join(assetRoot,'valid/oci-image-valid.json'))).mainArtifact;
 fs.writeFileSync(f.descriptor,JSON.stringify(artifact));f.env.EXPECTED_DIGEST=artifact.digest;
 const r=runStep(action,'publish-component',{env:f.env,realCli:binary,tools:[f.tools[0]]});
 assert.equal(r.error?.message,'container-artifact-integrity',JSON.stringify(r));assert.deepEqual(r.outputs,{});assert.equal(r.calls.some(call=>call.command==='skopeo'&&call.args.includes('copy')),false);
});

for(const [name,replace] of [
 ['non-container descriptor',{kind:'archive'}],
 ['non-OCI descriptor',{format:'zip'}],
 ['remote descriptor',{location:{kind:'registry',reference:'ghcr.io/example/api@'+digest}}],
])test(`component denies ${name} before native publication`,t=>{
 const f=fixture(t);f.tools[1].result.stdout=JSON.stringify({record:{...f.artifact,...replace}});
 const r=publish(f);assert.equal(r.error?.message,'container-artifact-link',JSON.stringify(r));assert.equal(r.calls.some(c=>c.args?.includes('copy')),false);assert.deepEqual(r.outputs,{});
 assert.equal(fs.readdirSync(f.directory).some(name=>name.startsWith('container-publication-')),false,'private snapshot is removed on validation denial');
});
test('component failure removes its private credential and payload snapshot',t=>{
 const f=fixture(t);f.tools[3].result={exitCode:1,stderr:'secret-token'};const r=publish(f);
 assert.equal(r.error?.message,'container-publication-denied');assert.deepEqual(r.outputs,{});
 assert.equal(fs.readdirSync(f.directory).some(name=>name.startsWith('container-publication-')),false);
});
test('component root readback hashes exact raw bytes including formatting, not a normalized JSON equivalent',t=>{
 const f=fixture(t);f.tools[4].result={stdout:JSON.stringify(JSON.parse(rawManifest),null,2)};
 const r=publish(f);assert.equal(r.error?.message,'container-digest-readback');assert.deepEqual(r.outputs,{});
});
test('legacy failed load never pushes; failed Crane push never tags',t=>{
 const r=runStep(action,'legacy-docker',{env:{STEPS_DOCKER_REGISTRY_RESULT:'registry.example',INPUTS_PROJECT_OWNER:'owner',INPUTS_PROJECT_KEY:'project'},tools:[{command:'docker',result:{exitCode:1}}]});
 assert.equal(r.error?.message,'container-legacy-load');assert.equal(r.calls.length,1);
 const directory=temporary(t);fs.writeFileSync(path.join(directory,'docker-tags.list'),'v1\nlatest\n');
 const c=runStep(action,'legacy-crane',{env:{GITHUB_WORKSPACE:directory,STEPS_DOCKER_REGISTRY_RESULT:'registry.example',INPUTS_PROJECT_OWNER:'owner',INPUTS_PROJECT_KEY:'project'},tools:[{command:'crane',result:{exitCode:1}}]});
 assert.equal(c.error?.message,'container-legacy-push');assert.equal(c.calls.length,1);
});


test('malformed private credential JSON produces only a safe error code',t=>{
 const f=fixture(t);fs.writeFileSync(f.authfile,'private-test-token');const r=publish(f);
 assert.equal(r.error?.message,'container-auth-shape');assert.equal(r.calls.length,0);
 assert.equal(JSON.stringify(r).includes('private-test-token'),false);
});
