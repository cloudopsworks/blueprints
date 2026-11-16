import test from 'node:test';
import assert from 'node:assert/strict';
import {runStep} from './action_test_support.mjs';
const action='cd/tasks/repo/push-tag/action.yml',sha='a'.repeat(40),object='b'.repeat(40);
const env={EXPECTED_SHA:sha,EXPECTED_VERSION:'1.2.3',BOT_USER:'Release Bot',BOT_EMAIL:'release@example.invalid'};
const commit={method:'rest.git.getCommit',args:{commit_sha:sha},result:{data:{sha}}};
const ref=value=>({method:'rest.git.getRef',args:{ref:'tags/v1.2.3'},result:{data:{object:value}}});
const tag=value=>({method:'rest.git.getTag',args:{tag_sha:object},result:{data:{object:value}}});
const missing={method:'rest.git.getRef',args:{ref:'tags/v1.2.3'},error:{status:404}};
const inventory=value=>({method:'rest.repos.listTags',args:{page:1,per_page:100},result:{data:value}});
const createTag={method:'rest.git.createTag',args:{tag:'v1.2.3',message:'chore: Version Tagging: v1.2.3',object:sha,type:'commit',tagger:{name:env.BOT_USER,email:env.BOT_EMAIL}},result:{data:{sha:object}}};
const createRef={method:'rest.git.createRef',args:{ref:'refs/tags/v1.2.3',sha:object},result:{data:{}}};
function run(api,override={}){return runStep(action,'frozen',{env:{...env,...override},api});}
test('frozen existing annotated tag peels exact commit without mutation',()=>{
 const r=run([commit,ref({type:'tag',sha:object}),tag({type:'commit',sha})]);assert.equal(r.error,undefined);assert.deepEqual(r.outputs,{tag:'v1.2.3',version:'1.2.3',sha});assert.equal(r.calls.some(c=>c.method?.includes('create')),false);
});
test('missing frozen tag creates annotated object then ref and verifies independent readback',()=>{
 const r=run([commit,missing,inventory([]),createTag,createRef,ref({type:'tag',sha:object}),tag({type:'commit',sha})]);assert.equal(r.error,undefined);assert.equal(r.unused.api,0);
 assert.deepEqual(r.calls.map(c=>c.method),['rest.git.getCommit','rest.git.getRef','rest.repos.listTags','rest.git.createTag','rest.git.createRef','rest.git.getRef','rest.git.getTag']);
});
test('existing tag at wrong commit denies without force-update or tag output',()=>{
 const r=run([commit,ref({type:'commit',sha:'c'.repeat(40)})]);assert.equal(r.error?.message,'frozen-tag-conflict');assert.deepEqual(r.outputs,{});assert.equal(r.calls.some(c=>c.method?.includes('create')),false);
});
test('different repository version already at exact head denies before tag creation',()=>{
 const r=run([commit,missing,inventory([{name:'v9.9.9',commit:{sha}}])]);assert.equal(r.error?.message,'frozen-tag-other-version-at-head');assert.deepEqual(r.outputs,{});
});
test('deployment qualifier of same repository version is not treated as a new version identity',()=>{
 const r=run([commit,missing,inventory([{name:'v1.2.3+deploy-prod',commit:{sha}}]),createTag,createRef,ref({type:'commit',sha})]);assert.equal(r.error,undefined);
});
test('concurrent createRef conflict still requires exact immutable readback',()=>{
 const r=run([commit,missing,inventory([]),createTag,{...createRef,result:undefined,error:{status:422}},ref({type:'commit',sha:'c'.repeat(40)})]);assert.equal(r.error?.message,'frozen-tag-conflict');assert.deepEqual(r.outputs,{});
});
test('unexpected getRef failure does not masquerade as missing tag',()=>{
 const r=run([commit,{...missing,error:{status:403,message:'forbidden'}}]);assert.equal(r.error?.message,'forbidden');assert.deepEqual(r.outputs,{});
});
for(const override of [{EXPECTED_SHA:'refs/heads/develop'},{EXPECTED_VERSION:'1.2; injected'},{TRONADOR_VERSION:'latest'}])test(`frozen input pin validation rejects ${JSON.stringify(override)}`,()=>{
 const r=runStep(action,'frozen-input',{env:{...env,TRONADOR_VERSION:'v0.6.0',...override}});assert.equal(r.error?.message,'frozen-tag-pins');assert.deepEqual(r.calls,[]);
});
