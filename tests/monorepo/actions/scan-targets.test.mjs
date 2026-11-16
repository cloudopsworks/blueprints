import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {runStep} from './action_test_support.mjs';
const action='ci/scan/trivy/targets/action.yml';
function fixture(t,{main='oci',preview='oci',enabled=true,same=false}={}){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'scan-targets-')));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const plan={repository:{id:'123',fullName:'example/mixed'},headSha:'a'.repeat(40),components:[{id:'api'}]};
 const descriptor=(format,digit)=>({format,digest:'sha256:'+digit.repeat(64)});
 const record={componentId:'api',headSha:plan.headSha,status:'succeeded',mainArtifact:descriptor(main,'b'),previewArtifact:preview?descriptor(preview,same?'b':'c'):null};
 const files={PLAN_PATH:plan,COMPONENT_RESULT:record,CONFIGURATION:{scanners:{trivyEnabled:enabled}}};
 const env={COMPONENT:'api',SOURCE_SHA:plan.headSha};
 for(const [key,value]of Object.entries(files)){env[key]=path.join(root,key+'.json');fs.writeFileSync(env[key],JSON.stringify(value));}
 return {env,record,tools:[plan,record].map(record=>({prefix:['components','contracts','validate'],result:{stdout:JSON.stringify({record})}}))};
}
for(const [name,options,main,preview] of [
 ['distinct main and preview images',{},true,true],
 ['identical main and preview bytes',{same:true},true,true],
 ['function main with image preview',{main:'zip'},false,true],
 ['image main without preview',{preview:null},true,false],
 ['disabled policy',{enabled:false},false,false],
])test(`finite image purpose targets reflect ${name}`,t=>{
 const f=fixture(t,options),r=runStep(action,'targets',f);assert.equal(r.error,undefined,JSON.stringify(r));
 assert.equal(String(r.outputs.main),String(main));assert.equal(String(r.outputs.preview),String(preview));
 if(main)assert.equal(r.outputs['main-digest'],f.record.mainArtifact.digest);
 if(preview)assert.equal(r.outputs['preview-digest'],f.record.previewArtifact.digest);
 assert.equal(r.calls.some(call=>call.kind==='api'),false);
});
