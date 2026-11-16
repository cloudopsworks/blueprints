// LOCAL adversarial recovery proof. Positive authority is captured from actual producer/history bodies.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {destroyPreparation,ownership,product,reserve,historical,binary} from './native_recovery_fixture.mjs';
import {runStep} from './action_test_support.mjs';
const reader='cd/monorepo/recovery/backend/read/action.yml';
for(const [name,change]of [['foreign bucket',{bucket:'foreign-packages'}],['foreign prefix',{key:'foreign/'+'1'.repeat(64)+'/main.zip'}],['different digest under frozen prefix',{key:'components/'+'e'.repeat(64)+'/main.zip'}]])test(`matching owner tags/linkage cannot authorize ${name}`,t=>{
 const {r}=ownership(t,change);assert.ok(r.error,JSON.stringify(r));assert.deepEqual(r.outputs,{});assert.equal(r.calls.some(c=>c.command==='terragrunt'||c.command==='tofu'||c.args?.includes?.('get-object-tagging')),false);
});
test('exact authenticated object claim retains native ownership proof',t=>{const {r}=ownership(t);assert.equal(r.error,undefined,JSON.stringify(r));assert.ok(r.outputs['ownership-proof']);});

function association(f){return {number:7,base:{ref:'support/1.0',sha:'d'.repeat(40),repo:{id:12345}},head:{ref:'feature',sha:'f'.repeat(40),repo:{id:12345}}};}
test('historical closure corroborates nonempty association with retained marker PR and actual PR API',t=>{
 const f=product(t,{closure:true}),producer=reserve(f);f.host.pull_requests=[association(f)];const retained=historical(f,producer);assert.equal(retained.r.error,undefined,JSON.stringify(retained.r));assert.ok(retained.r.outputs['reservation-marker']);
});
for(const [name,mutate]of [['different PR',a=>a.number=8],['different head SHA',a=>a.head.sha='9'.repeat(40)],['different head ref',a=>a.head.ref='unrelated'],['multiple associations',a=>{}]])test(`historical retained marker denies ${name} association`,t=>{
 const f=product(t,{closure:true}),producer=reserve(f),a=association(f);mutate(a);const host={pull_requests:name==='multiple associations'?[a,a]:[a]};const retained=historical(f,producer,{host});assert.ok(retained.r.error,JSON.stringify(retained.r));assert.deepEqual(retained.r.outputs,{});
});

test('actual authenticated producer through native ownership executes destroy preparation without original artifacts',t=>{
 const frame=destroyPreparation(t),r=frame.prepared;assert.equal(r.error,undefined,JSON.stringify(r));assert.ok(r.outputs['saved-plan']);const saved=JSON.parse(fs.readFileSync(r.outputs['saved-plan']));assert.ok(saved.resourceIdentities['aws_s3_object.package[0]']);assert.equal(frame.calls.some(c=>c.args?.includes?.('apply')),false);assert.equal(frame.calls.some(c=>c.args?.includes?.('render')),true);
 for(const call of frame.calls.filter(c=>c.command==='aws'&&['head-object','get-object','list-objects-v2','get-object-tagging'].includes(c.args[1])))assert.equal(call.args[call.args.indexOf('--expected-bucket-owner')+1],'123456789012');
});
for(const [name,mutate]of [['bucket',c=>c.change.before.bucket='foreign-packages'],['prefix',c=>c.change.before.key='foreign/'+'1'.repeat(64)+'/main.zip'],['digest',c=>c.change.before.key='components/'+'e'.repeat(64)+'/main.zip'],['version',c=>c.change.before.version_id='foreign-version']])test(`saved delete-only plan rejects changed remote ${name} despite owned address and owner tag`,t=>{
 const frame=destroyPreparation(t,{before:changes=>mutate(changes.find(c=>c.type==='aws_s3_object'))}),r=frame.prepared;assert.equal(r.error?.message,'recovery-saved-before-identity',JSON.stringify(r));assert.deepEqual(r.outputs,{});assert.equal(frame.calls.some(c=>c.args?.includes?.('apply')),false);
});
test('historical retained marker rejects malformed association base SHA even when PR identity agrees',t=>{
 const f=product(t,{closure:true}),producer=reserve(f),a=association(f);a.base.sha=['d'.repeat(40)];const retained=historical(f,producer,{host:{pull_requests:[a]}});assert.equal(retained.r.error?.message,'history-pr-association-binding',JSON.stringify(retained.r));assert.deepEqual(retained.r.outputs,{});
});
for(const side of ['base','head'])test(`historical retained marker rejects ${side} repository ID array coercion`,t=>{
 const f=product(t,{closure:true}),producer=reserve(f),a=association(f);a[side].repo.id=[12345];const retained=historical(f,producer,{host:{pull_requests:[a]}});assert.equal(retained.r.error?.message,'history-pr-association-binding',JSON.stringify(retained.r));assert.deepEqual(retained.r.outputs,{});
});
