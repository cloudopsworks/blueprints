import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {runStep} from './action_test_support.mjs';
const action='ci/scan/trivy/endorsement/action.yml',digest='sha256:'+'a'.repeat(64);
function emitter(t,change={}){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'scan-endorsement-')));
 t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const computed=path.join(root,'computed.json'),retrieved=path.join(root,'retrieved.json');
 const record={kind:'ScannerResult',componentId:'api',sourceSha:'b'.repeat(40),artifactDigest:'sha256:'+'c'.repeat(64),profile:'diagnostic',required:true,status:'passed'};
 fs.writeFileSync(computed,JSON.stringify(record));fs.writeFileSync(retrieved,JSON.stringify(record));
 return {env:{COMPUTED_RESULT:computed,RETRIEVED_RESULT:retrieved,ARTIFACT_ID:'789',ARCHIVE_DIGEST:digest,RUN_ID:'456',RUN_ATTEMPT:'2',GITHUB_RUN_ID:'456',GITHUB_RUN_ATTEMPT:'2',GITHUB_REPOSITORY_ID:'123',COMPONENT:'api',ARTIFACT_PURPOSE:'main',...change.env},
 tools:[digest,change.retrievedDigest||digest].map(d=>({prefix:['components','contracts','validate','--kind','ScannerResult'],result:{stdout:JSON.stringify({digest:d,record})}})),
 api:[{method:'rest.actions.getArtifact',result:{data:{id:789,name:'monorepo-scan-456-2-api-main',digest,expired:false,workflow_run:{id:456},...change.artifact}}}]};
}
test('fixed scanner writer emits closed binding only after exact computed/uploaded typed bytes match',t=>{
 const r=runStep(action,'emit',emitter(t));assert.equal(r.error,undefined,JSON.stringify(r));
 const messages=r.logs.filter(l=>l.kind==='info').map(l=>l.message);
 assert.equal(messages.length,1);assert.ok(messages[0].startsWith('CLOUDOPSWORKS_STAGE_V1 '));
 const binding=JSON.parse(messages[0].slice('CLOUDOPSWORKS_STAGE_V1 '.length));
 assert.deepEqual(binding,{repositoryId:'123',runId:'456',runAttempt:'2',artifactId:'789',artifactName:'monorepo-scan-456-2-api-main',archiveDigest:digest});
});
for(const [name,change] of [
 ['different retrieved bytes',{retrievedDigest:'sha256:'+'f'.repeat(64)}],
 ['old attempt',{env:{GITHUB_RUN_ATTEMPT:'3'}}],
 ['wrong purpose',{artifact:{name:'monorepo-scan-456-2-api-preview'}}],
 ['expired uploaded record',{artifact:{expired:true}}],
 ['wrong artifact run',{artifact:{workflow_run:{id:455}}}],
])test(`scanner writer denies ${name} without an endorsement`,t=>{
 const r=runStep(action,'emit',emitter(t,change));assert.ok(r.error);assert.equal(r.logs.some(l=>l.kind==='info'&&l.message.startsWith('CLOUDOPSWORKS_STAGE_V1 ')),false);
});
