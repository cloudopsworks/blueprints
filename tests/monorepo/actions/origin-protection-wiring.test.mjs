import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import path from 'node:path';
import {root,loadStep} from './action_test_support.mjs';
const paths=['cd/tasks/repo/context/action.yml','cd/tasks/repo/context/protected-source/action.yml','ci/monorepo/plan/endorsement/action.yml'];
const yaml=file=>{const r=spawnSync('yq',['-o=json','-I=0','.',path.join(root,file)],{encoding:'utf8'});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout);};
test('private protection interface is precisely the existing 18 facts, not a cache authority or new record',()=>{
 const identity=loadStep(paths[1],'identity').script;
 const fields=identity.match(/fields = \[([^\]]+)\]/)[1].match(/'[^']+'/g).map(x=>x.slice(1,-1));
 assert.deepEqual(fields,['event','ref','hostSha','callerPath','callerSha','blueprintSha','sourceSha','sourceRef','sourceRepositoryId','trustedSource','prNumber','headRepositoryId','headSha','headRef','baseRef','policySha','closed','merged']);
 const helper=yaml(paths[1]);assert.deepEqual(Object.keys(helper.inputs),['origin-facts','host-ref','host-sha']);assert.match(identity,/65536/);assert.doesNotMatch(loadStep(paths[1],'verify').script,/facts\.trustedSource/);
});
test('normal public outputs wait for independent protection and retained-origin comparison',()=>{
 const d=yaml(paths[0]),steps=d.runs.steps;
 assert.ok(steps.findIndex(x=>x.id==='normal')<steps.findIndex(x=>x.id==='protected'));
 assert.ok(steps.findIndex(x=>x.id==='protected')<steps.findIndex(x=>x.id==='projection'));
 assert.equal(steps.find(x=>x.id==='protected').with['origin-facts'],'${{ steps.normal.outputs.origin-facts }}');
 assert.equal(steps.find(x=>x.id==='projection').env.TRUSTED,'${{ steps.protected.outputs.trusted-source }}');
 for(const name of ['source-ref','source-repository-id','trusted-source','origin-facts'])assert.match(d.outputs[name].value,/steps\.projection\.outputs/);
 assert.match(loadStep(paths[0],'projection').script,/normal-context-origin-binding/);
});
test('source-free writer independently reuses protection without a context endorsement cycle',()=>{
 const d=yaml(paths[2]),steps=d.runs.steps,proof=steps.find(x=>x.id==='protected'),writer=steps.find(x=>x.id==='origin');
 assert.equal(proof.uses,'./bp/cd/tasks/repo/context/protected-source');assert.equal(proof.with['origin-facts'],'${{ inputs.origin-facts }}');
 assert.equal(writer.env.SOURCE_TRUSTED,'${{ steps.protected.outputs.trusted-source }}');assert.ok(steps.indexOf(proof)<steps.indexOf(writer));
 assert.equal(d.outputs.origin.value,'${{ steps.identity.outputs.origin }}');
 assert.equal(steps.some(x=>x.uses==='./bp/cd/tasks/repo/context'),false);
});
for(const file of paths)test('bounded whole action and inline steps: '+file,()=>{
 const source=readFileSync(path.join(root,file),'utf8'),d=yaml(file);
 assert.ok(source.split('\n').filter(x=>x.trim()&&!x.trimStart().startsWith('#')).length<=300);
 for(const step of d.runs.steps.filter(x=>x.uses==='actions/github-script@v9'))assert.ok(step.with.script.split('\n').filter(x=>x.trim()).length<=120,step.id);
});
