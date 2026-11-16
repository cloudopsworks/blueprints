import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {runStep} from './action_test_support.mjs';
const action='ci/monorepo/toolchains/action.yml';
function fixture(t,change={}){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'typed-toolchains-')));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const plan={matrix:{include:[{componentId:'api',toolchains:[{tool:'node',version:'24.22.3'},{tool:'go',version:'1.27.4'}]}]},components:[{id:'api',dependsOn:['library'],toolchains:[{tool:'node',version:'24.22.3'}]},{id:'library',dependsOn:[],toolchains:[{tool:'go',version:'1.27.4'}]}]};
 if(change.plan)change.plan(plan);const file=path.join(root,'plan.json');fs.writeFileSync(file,JSON.stringify(plan));
 return {env:{PLAN_PATH:file,COMPONENT:'api',SCAN_COMPONENT:'false',...change.env},tools:[{args:['components','contracts','validate','--kind','BuildPlan'],result:{stdout:JSON.stringify({record:plan})}}]};
}
test('build tool setup consumes exact typed matrix toolchain row without second selector',t=>{
 const r=runStep(action,'tools',fixture(t));assert.equal(r.error,undefined);assert.equal(r.outputs.node,'24.22.3');assert.equal(r.outputs.go,'1.27.4');assert.equal(r.outputs.python,'');assert.equal(r.calls.length,1);
});
test('scanner source toolchain closure uses declared component dependencies rather than changed-only matrix',t=>{
 const r=runStep(action,'tools',fixture(t,{env:{SCAN_COMPONENT:'true'}}));assert.equal(r.error,undefined);assert.equal(r.outputs.node,'24.22.3');assert.equal(r.outputs.go,'1.27.4');
});
for(const [name,change] of [
 ['missing selected row',{plan:p=>p.matrix.include.splice(0)}],['duplicate selected row',{plan:p=>p.matrix.include.push(p.matrix.include[0])}],
 ['missing declared dependency',{env:{SCAN_COMPONENT:'true'},plan:p=>p.components[0].dependsOn=['missing']}],
 ['conflicting dependency versions',{env:{SCAN_COMPONENT:'true'},plan:p=>p.components[1].toolchains.push({tool:'node',version:'26.13.1'})}],
 ['undeclared tool',{plan:p=>p.matrix.include[0].toolchains.push({tool:'shell',version:'1.2.3'})}],
 ['injected tool version',{plan:p=>p.matrix.include[0].toolchains[0].version='24;touch marker'}],
])test(`toolchain setup denies ${name} without install outputs`,t=>{
 const r=runStep(action,'tools',fixture(t,change));assert.ok(r.error);assert.deepEqual(r.outputs,{});
});
