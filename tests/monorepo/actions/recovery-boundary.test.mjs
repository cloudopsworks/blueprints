import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {root} from './action_test_support.mjs';
function yaml(relative){
 const file=path.join(root,relative);assert.ok(fs.existsSync(file),`Required named recovery composite missing: ${relative}`);
 const r=spawnSync('yq',['-o=json','-I=0','.',file],{encoding:'utf8',env:{PATH:process.env.PATH},timeout:10000,maxBuffer:4194304});
 assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout);
}
for(const [name,relative,ids] of [
 ['historical authority','cd/monorepo/recovery/history/action.yml',['locate','verify']],
 ['backend','cd/monorepo/recovery/backend/action.yml',['select','capture']],
 ['conditional state reader','cd/monorepo/recovery/backend/read/action.yml',['state','ownership','inspect']],
 ['native recovery executor','cd/monorepo/recovery/execute/action.yml',['plan','unlock-init','unlock','destroy-prepare','destroy']],
])test(`recovery has a fixed maintained ${name} action, not a custom runtime`,()=>{
 const action=yaml(relative);assert.equal(action.runs.using,'composite');
 for(const id of ids)assert.ok(action.runs.steps.some(step=>step.id===id),`Missing ${relative}#${id}`);
 assert.equal(action.runs.steps.some(s=>s.run),false,'control glue must use github-script v9 composites');
});
