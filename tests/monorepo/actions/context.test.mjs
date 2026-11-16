import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {runStep} from './action_test_support.mjs';
const action='cd/tasks/repo/context/action.yml';
function fixture(change={}){
 const bytes=fs.readFileSync(fileURLToPath(new URL('../../../../monorepo-app-template/.github/workflows/composite-first-slice.yml',import.meta.url)));
 const head='a'.repeat(40),bp='b'.repeat(40),blob=createHash('sha1').update(`blob ${bytes.length}\0`).update(bytes).digest('hex');
 const run={id:456,run_attempt:2,repository:{id:123},event:'workflow_dispatch',path:'.github/workflows/composite-first-slice.yml',head_sha:head,head_branch:'develop',referenced_workflows:[{path:'cloudopsworks/blueprints/.github/workflows/monorepo-delivery-slice.yml@v5.11.0',sha:bp}],...change.run};
 const ref={object:change.ref||{type:'commit',sha:bp}};
 const api=[{method:'rest.repos.get',result:{data:{id:123}}},{method:'rest.actions.getWorkflowRunAttempt',result:{data:run}},
 {method:'rest.repos.getBranch',args:{branch:'develop'},result:{data:{protected:true,commit:{sha:head},...change.branch}}},
 {method:'rest.repos.getContent',args:{ref:head,path:'.github/workflows/composite-first-slice.yml'},result:{data:{type:'file',encoding:'base64',content:bytes.toString('base64'),sha:blob,...change.file}}},
 {method:'rest.git.getRef',args:{owner:'cloudopsworks',repo:'blueprints',ref:'tags/v5.11.0'},result:{data:ref}}];
 if(change.comparison)api.splice(3,0,{method:'rest.repos.compareCommitsWithBasehead',args:{basehead:head+'...'+'e'.repeat(40)},result:{data:change.comparison}});
 if(change.tag)api.push({method:'rest.git.getTag',args:{tag_sha:change.ref.sha},result:{data:{object:change.tag}}});
 return {env:{GITHUB_REPOSITORY_ID:'123',GITHUB_RUN_ID:'456',GITHUB_RUN_ATTEMPT:'2'},api};
}
test('actual diagnostic caller bytes bind protected immutable source and exact reusable Blueprint commit',()=>{
 const r=runStep(action,'verify',fixture());assert.equal(r.error,undefined);
 assert.deepEqual(r.outputs,{'source-sha':'a'.repeat(40),'blueprint-sha':'b'.repeat(40),'caller-mode':'reusable','run-id':'456','run-attempt':'2'});
});
test('annotated Blueprint tag resolves to exact referenced reusable commit',()=>{
 const r=runStep(action,'verify',fixture({ref:{type:'tag',sha:'c'.repeat(40)},tag:{type:'commit',sha:'b'.repeat(40)}}));assert.equal(r.error,undefined);assert.equal(r.unused.api,0);
});
for(const [name,change] of [
 ['wrong host repository',{run:{repository:{id:124}}}],['old host attempt',{run:{run_attempt:1}}],
 ['non-diagnostic event',{run:{event:'pull_request'}}],['wrong caller path',{run:{path:'.github/workflows/other.yml'}}],
 ['unprotected source branch',{branch:{protected:false}}],['moved branch',{branch:{commit:{sha:'e'.repeat(40)}}}],
 ['counterfeit caller bytes',{file:{content:Buffer.from('counterfeit').toString('base64')}}],['wrong Git blob',{file:{sha:'e'.repeat(40)}}],
 ['wrong reusable commit',{run:{referenced_workflows:[{path:'cloudopsworks/blueprints/.github/workflows/monorepo-delivery-slice.yml@v5.11.0',sha:'e'.repeat(40)}]}}],
 ['duplicate called workflow',{run:{referenced_workflows:Array(2).fill({path:'cloudopsworks/blueprints/.github/workflows/monorepo-delivery-slice.yml@v5.11.0',sha:'b'.repeat(40)})}}],
])test(`context denies ${name} without source or blueprint authority`,()=>{
 const r=runStep(action,'verify',fixture(change));assert.ok(r.error);assert.deepEqual(r.outputs,{});
});
test('rerun after protected branch advances retains captured run commit after exact ancestry corroboration',()=>{
 const captured='a'.repeat(40),tip='e'.repeat(40);
 const r=runStep(action,'verify',fixture({branch:{commit:{sha:tip}},comparison:{status:'ahead',base_commit:{sha:captured},merge_base_commit:{sha:captured}}}));
 assert.equal(r.error,undefined);assert.equal(r.outputs['source-sha'],captured);assert.equal(r.calls.find(c=>c.method==='rest.repos.getContent').args.ref,captured);
});
for(const [name,comparison] of [
 ['diverged',{status:'diverged',base_commit:{sha:'a'.repeat(40)},merge_base_commit:{sha:'c'.repeat(40)}}],
 ['behind',{status:'behind',base_commit:{sha:'a'.repeat(40)},merge_base_commit:{sha:'a'.repeat(40)}}],
 ['wrong base',{status:'ahead',base_commit:{sha:'c'.repeat(40)},merge_base_commit:{sha:'a'.repeat(40)}}],
 ['wrong merge base',{status:'ahead',base_commit:{sha:'a'.repeat(40)},merge_base_commit:{sha:'c'.repeat(40)}}],
])test(`advanced branch denies ${name} ancestry instead of switching source`,()=>{
 const r=runStep(action,'verify',fixture({branch:{commit:{sha:'e'.repeat(40)}},comparison}));assert.equal(r.error?.message,'context-captured-host-ancestry');assert.deepEqual(r.outputs,{});
});
test('historical context verifies the requested exact host attempt rather than current invocation',()=>{
 const f=fixture({run:{id:455,run_attempt:1}});f.env.CONTEXT_RUN_ID='455';f.env.CONTEXT_RUN_ATTEMPT='1';
 const r=runStep(action,'verify',f);assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs['run-id'],'455');assert.equal(r.outputs['run-attempt'],'1');
});
for(const value of [{malformed:true},null,[{number:17}]])test(`manual canonical publisher denies a nonempty/malformed PR association ${JSON.stringify(value)}`,()=>{const f=fixture();f.api[1].result.data.pull_requests=value;const r=runStep(action,'verify',f);assert.equal(r.error?.message,'context-run-pull-association',JSON.stringify(r));assert.deepEqual(r.outputs,{});});

function normalFixture(change={}) {
 const mode=change.kind||'main',caller={main:'main-build.yml',pr:'pr-build.yml',closure:'pr-close.yaml'}[mode];
 const bytes=fs.readFileSync(fileURLToPath(new URL('../../../../'+(change.template||'monorepo-app-template')+'/.github/workflows/'+caller,import.meta.url)));
 const head='a'.repeat(40),bp='b'.repeat(40),base='c'.repeat(40),merge='d'.repeat(40);
 const file='.github/workflows/'+caller,events={main:'push',pr:'pull_request',closure:'pull_request_target'};
 const workflows={main:['monorepo-main-build.yml','monorepo-ci.yml'],pr:['monorepo-pr-build.yml','monorepo-ci.yml'],closure:['monorepo-pr-close.yml','monorepo-closure.yml','monorepo-ci.yml']}[mode];
 const pull={number:17,state:mode==='closure'?'closed':'open',merged:mode==='closure',merge_commit_sha:merge,head:{sha:head,ref:'feature/topic',repo:{id:123}},base:{sha:base,ref:'develop',repo:{id:123}},...change.pull};
 const association={number:17,head:pull.head,base:pull.base};
 const run={id:456,run_attempt:2,repository:{id:123},event:events[mode],path:file,head_sha:head,head_branch:mode==='closure'?'master':mode==='pr'?'feature/topic':'develop',pull_requests:mode==='main'?[]:[association],referenced_workflows:workflows.map(name=>({path:'cloudopsworks/blueprints/.github/workflows/'+name+'@v5.11.0',sha:bp})),...change.run};
 const api=[{method:'rest.repos.get',result:{data:{id:123,default_branch:'master'}}},{method:'rest.actions.getWorkflowRunAttempt',result:{data:run}},
  {method:'rest.repos.getContent',args:{path:file,ref:head},result:{data:{type:'file',encoding:'base64',content:bytes.toString('base64'),sha:createHash('sha1').update(`blob ${bytes.length}\0`).update(bytes).digest('hex'),...change.file}}},
  {method:'rest.git.getRef',result:{data:{object:{type:'commit',sha:bp}}}}];
 [api[2],api[3]]=[api[3],api[2]];
 if(mode!=='main')api.push({method:'rest.pulls.get',args:{pull_number:17},result:{data:pull}});
 return {env:{CONTEXT_MODE:'normal',GITHUB_REPOSITORY_ID:'123',GITHUB_RUN_ID:'456',GITHUB_RUN_ATTEMPT:'2',GITHUB_SHA:head,GITHUB_WORKFLOW_SHA:head,GITHUB_REF:mode==='pr'?'refs/pull/17/merge':'refs/heads/'+run.head_branch,...change.env},context:{eventName:events[mode],repo:{owner:'example',repo:'mixed'},payload:{action:mode==='closure'?'closed':'opened',pull_request:mode==='closure'?{...pull,base:{...pull.base,sha:'e'.repeat(40)}}:pull}},api};
}
for(const [kind,source,mode] of [['main','a','normal-main'],['pr','a','normal-pr'],['closure','d','normal-closure']])test(`normal ${kind} caller binds actual immutable lineage and source`,()=>{
 const r=runStep(action,'normal',normalFixture({kind}));assert.equal(r.error,undefined,JSON.stringify(r));
 assert.equal(r.outputs['source-sha'],source.repeat(40));assert.equal(r.outputs['caller-mode'],mode);assert.equal(r.outputs['blueprint-sha'],'b'.repeat(40));assert.deepEqual(r.unused,{api:0,tools:0,fetches:0});
});
for(const [name,change] of [
 ['counterfeit caller',{file:{content:Buffer.from('evil').toString('base64')}}],
 ['wrong nested lineage',{run:{referenced_workflows:[]}}],
 ['wrong run attempt',{run:{run_attempt:1}}],
 ['manual wrong caller path',{run:{path:'.github/workflows/random.yml'}}],
 ['ordinary PR missing association',{kind:'pr',run:{pull_requests:[]}}],
 ['PR API head changed',{kind:'pr',pull:{head:{sha:'f'.repeat(40),ref:'feature/topic',repo:{id:123}}}}],
 ['historical closure lacks retained pull proof',{kind:'closure',env:{CONTEXT_RUN_ID:'455',CONTEXT_RUN_ATTEMPT:'1'},run:{id:455,run_attempt:1,pull_requests:[]}}],
 ])test(`normal context rejects ${name}`,()=>{const r=runStep(action,'normal',normalFixture(change));assert.ok(r.error,JSON.stringify(r));assert.deepEqual(r.outputs,{});});
test('context rejects unknown family rather than successful empty routing',()=>{const r=runStep(action,'verify',{env:{CONTEXT_MODE:'unreviewed'}});assert.equal(r.error?.message,'context-mode');assert.deepEqual(r.outputs,{});});
test('normal source version tag keeps actual tag ref, not a fictitious branch',()=>{
 const f=normalFixture({run:{head_branch:'v1.2.3'},env:{GITHUB_REF:'refs/tags/v1.2.3'}});f.api.push({method:'rest.git.getRef',args:{ref:'tags/v1.2.3'},result:{data:{object:{type:'commit',sha:'a'.repeat(40)}}}});
 const r=runStep(action,'normal',f);assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs['host-ref'],'refs/tags/v1.2.3');
});
test('normal source version tag cannot point to another source',()=>{
 const f=normalFixture({run:{head_branch:'v1.2.3'},env:{GITHUB_REF:'refs/tags/v1.2.3'}});f.api.push({method:'rest.git.getRef',result:{data:{object:{type:'commit',sha:'e'.repeat(40)}}}});
 const r=runStep(action,'normal',f);assert.equal(r.error?.message,'normal-context-source-tag');assert.deepEqual(r.outputs,{});
});
for(const event of ['create','workflow_dispatch'])test(`normal ${event} source version tag is verified without a branch fiction`,()=>{
 const f=normalFixture({run:{head_branch:'v1.2.3',event},env:{GITHUB_REF:'refs/tags/v1.2.3'}});f.context.eventName=event;f.api.push({method:'rest.git.getRef',args:{ref:'tags/v1.2.3'},result:{data:{object:{type:'commit',sha:'a'.repeat(40)}}}});
 const r=runStep(action,'normal',f);assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs['host-ref'],'refs/tags/v1.2.3');
});

for(const kind of ['main','pr','closure'])test(`normal ${kind} also authenticates unchanged reviewed Ruby caller bytes`,()=>{const r=runStep(action,'normal',normalFixture({kind,template:'ruby-app-template'}));assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs['caller-mode'],'normal-'+kind);});
test('protected main source exposes independently derived scanner identity, not continuation host guesses',()=>{
 const r=runStep(action,'normal',normalFixture()); assert.equal(r.error,undefined);
 assert.equal(r.outputs['source-ref'],'refs/heads/develop');assert.equal(r.outputs['source-repository-id'],'123');assert.equal(r.outputs['trusted-source'],'true');
 const facts=JSON.parse(r.outputs['origin-facts']);assert.equal(facts.callerPath,'.github/workflows/main-build.yml');assert.equal(facts.hostSha,'a'.repeat(40));
});
for(const [label,repo,protectedHead,trusted] of [['protected same-repo',123,true,'true'],['unprotected same-repo',123,false,'false'],['fork',456,true,'false']])
 test(`PR ${label} facts never grant source trust before protected-source action`,()=>{
  const f=normalFixture({kind:'pr',pull:{head:{sha:'a'.repeat(40),ref:'feature/topic',repo:{id:repo}}}});

  const r=runStep(action,'normal',f);assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs['trusted-source'],'false');
  assert.equal(r.outputs['source-ref'],'refs/heads/feature/topic');assert.equal(r.outputs['source-repository-id'],String(repo));
 });

test('PR retains captured protected-base policy independently of its source-head trust',()=>{
 const r=runStep(action,'normal',normalFixture({kind:'pr'}));assert.equal(r.error,undefined,JSON.stringify(r));
 assert.equal(r.outputs['policy-sha'],'c'.repeat(40));assert.equal(JSON.parse(r.outputs['origin-facts']).policySha,'c'.repeat(40));
});
test('native PR API head, merge host, and workflow caller SHA remain distinct',()=>{
 const f=normalFixture({kind:'pr'}),host='d'.repeat(40),caller='e'.repeat(40);
 f.env.GITHUB_SHA=host;f.env.GITHUB_REF='refs/pull/17/merge';f.env.GITHUB_WORKFLOW_SHA=caller;
 f.api[3].args.ref=caller;
 const r=runStep(action,'normal',f);assert.equal(r.error,undefined,JSON.stringify(r));
 const facts=JSON.parse(r.outputs['origin-facts']);assert.equal(facts.sourceSha,'a'.repeat(40));assert.equal(facts.hostSha,host);assert.equal(facts.callerSha,caller);assert.equal(facts.ref,'refs/pull/17/merge');
});
