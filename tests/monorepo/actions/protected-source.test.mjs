import test from 'node:test';
import assert from 'node:assert/strict';
import {runStep} from './action_test_support.mjs';
const action='cd/tasks/repo/context/protected-source/action.yml',sha='a'.repeat(40),tip='b'.repeat(40);
const empty=()=>({totalCount:0,nodes:[],pageInfo:{hasNextPage:false}});
const policy=(extra={})=>({requiresApprovingReviews:true,requiredApprovingReviewCount:1,requiredStatusCheckContexts:['checkpr / Check Pull Request'],isAdminEnforced:true,dismissesStaleReviews:true,requiresStatusChecks:true,requiresStrictStatusChecks:true,allowsForcePushes:false,bypassPullRequestAllowances:empty(),bypassForcePushAllowances:empty(),...extra});
const api=(method,data,args={})=>({method:'rest.'+method,args,result:{data}});
const rule=p=>({method:'graphql',result:{repository:{ref:{branchProtectionRule:p}}}});
const branch=(name,commit=sha,extra={})=>api('repos.getBranch',{protected:true,commit:{sha:commit},...extra},{branch:name});
const env={EVENT:'push',SOURCE_SHA:sha,SOURCE_REF:'refs/heads/develop',SOURCE_REPOSITORY_ID:'123',GITHUB_REPOSITORY_ID:'123',BASE_REF:'',POLICY_SHA:'',HOST_REF:'',HOST_SHA:'',TAG:'false',DIRECTORY:''};
const context={repo:{owner:'example',repo:'mixed'}};
const facts=e=>({event:e.EVENT,ref:e.EVENT==='pull_request'?'refs/pull/17/merge':'refs/heads/master',hostSha:tip,callerPath:'.github/workflows/main-build.yml',callerSha:tip,blueprintSha:tip,sourceSha:e.SOURCE_SHA,sourceRef:e.SOURCE_REF,sourceRepositoryId:e.SOURCE_REPOSITORY_ID,trustedSource:true,prNumber:e.EVENT==='push'?'0':'17',headRepositoryId:'123',headSha:sha,headRef:'feature/a',baseRef:e.BASE_REF,policySha:e.POLICY_SHA,closed:e.EVENT==='pull_request_target',merged:e.EVENT==='pull_request_target'});
const run=(changes={},api=[],tools=[])=>{const e={...env,...changes};return runStep(action,'verify',{env:{...e,FACTS:JSON.stringify({...facts(e),...changes.facts})},context:{...context,...changes.context},api,tools});};
test('strong source branch and fresh tip ancestry are required, not protected:true alone',()=>{
 const r=run({},[branch('develop',tip),rule(policy()),api('repos.compareCommitsWithBasehead',{status:'ahead',base_commit:{sha},merge_base_commit:{sha}},{basehead:sha+'...'+tip})]);
 assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs['trusted-source'],'true');
});
for(const [key,value]of Object.entries({requiresApprovingReviews:false,requiredApprovingReviewCount:0,requiredStatusCheckContexts:[],isAdminEnforced:false,dismissesStaleReviews:false,requiresStatusChecks:false,requiresStrictStatusChecks:false,allowsForcePushes:true}))test(`required strong policy denies ${key}`,()=>{
 const r=run({},[branch('develop'),rule(policy({[key]:value}))]);assert.equal(r.error?.message,'protected-source-policy');assert.deepEqual(r.outputs,{});assert.equal(r.calls.length,2);
});
for(const connection of ['bypassPullRequestAllowances','bypassForcePushAllowances'])for(const value of [{...empty(),totalCount:1},{...empty(),nodes:[{actor:{__typename:'User'}}]},{...empty(),pageInfo:{hasNextPage:true}},null])test(`deny ${connection} truncation/bypass ${JSON.stringify(value)}`,()=>{
 const r=run({},[branch('develop'),rule(policy({[connection]:value}))]);assert.equal(r.error?.message,'protected-source-bypass');assert.deepEqual(r.outputs,{});
});
test('required source denies nonancestor after otherwise valid strong policy',()=>{
 const r=run({},[branch('develop',tip),rule(policy()),api('repos.compareCommitsWithBasehead',{status:'diverged',base_commit:{sha},merge_base_commit:{sha:tip}})]);assert.equal(r.error?.message,'protected-source-ancestry');
});
for(const [label,sourceRepo,headProtected]of [['fork','456',false],['unprotected same repository','123',false],['protected same repository','123',true]])test(`PR source trust: ${label}, never inherited from protected base`,()=>{
 const calls=[branch('develop'),rule(policy())];if(sourceRepo==='123'){calls.push(branch('feature/a',sha,{protected:headProtected}));if(headProtected)calls.push(rule(policy()));}
 const r=run({EVENT:'pull_request',SOURCE_REF:'refs/heads/feature/a',SOURCE_REPOSITORY_ID:sourceRepo,BASE_REF:'develop',POLICY_SHA:sha},calls);
 assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs['trusted-source'],String(headProtected&&sourceRepo==='123'));
});
test('PR required base failure denies even for otherwise trusted head',()=>{
 const r=run({EVENT:'pull_request',SOURCE_REF:'refs/heads/feature/a',BASE_REF:'develop',POLICY_SHA:sha},[branch('develop'),rule(policy({isAdminEnforced:false}))]);assert.equal(r.error?.message,'protected-source-policy');
});
test('tag uses exact-source configuration for CLI lifecycle and fresh strong eligible lineage',()=>{
 const r=run({SOURCE_REF:'refs/tags/v1.2.3',TAG:'true',DIRECTORY:'/private/source-snapshot'},[
 api('repos.listBranches',[{name:'master'},{name:'support/v1'}],{protected:true,page:1,per_page:100}),branch('support/v1'),rule(policy())],
 [{args:['components','lifecycle','--config-only','--workdir','/private/source-snapshot','--event','push','--ref','refs/heads/master','--base-ref','','--json'],result:{stdout:JSON.stringify({eligible:false})}},
 {args:['components','lifecycle','--config-only','--workdir','/private/source-snapshot','--event','push','--ref','refs/heads/support/v1','--base-ref','','--json'],result:{stdout:JSON.stringify({eligible:true})}}]);
 assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs['trusted-source'],'true');assert.deepEqual(r.unused,{api:0,tools:0,fetches:0});
});
test('tag without configured eligible lineage denies',()=>{
 const r=run({SOURCE_REF:'refs/tags/v1.2.3',TAG:'true',DIRECTORY:'/snapshot'},[api('repos.listBranches',[{name:'master'}])],[{result:{stdout:JSON.stringify({eligible:false})}}]);assert.equal(r.error?.message,'protected-source-tag-lineage');
});
test('tag peeling is independently bound to exact source SHA before snapshot',()=>{
 const r=runStep(action,'identity',{env:{...env,FACTS:JSON.stringify(facts({...env,SOURCE_REF:'refs/tags/v1.2.3'}))},context,api:[api('repos.get',{id:123}),api('git.getRef',{object:{type:'commit',sha:tip}},{ref:'tags/v1.2.3'})]});
 assert.equal(r.error?.message,'protected-source-tag');assert.deepEqual(r.outputs,{});
});

test('cached trustedSource cannot grant an unprotected PR head',()=>{
 const r=run({EVENT:'pull_request',SOURCE_REF:'refs/heads/feature/a',BASE_REF:'develop',POLICY_SHA:sha,facts:{trustedSource:true}},[branch('develop'),rule(policy()),branch('feature/a',sha,{protected:false})]);
 assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs['trusted-source'],'false');
});
test('closure independently checks captured original host and distinct native delivery host',()=>{
 const r=run({EVENT:'pull_request_target',BASE_REF:'develop',POLICY_SHA:sha,HOST_REF:'refs/heads/current',HOST_SHA:sha,GITHUB_REF:'refs/heads/current',GITHUB_SHA:sha,context:{eventName:'workflow_run'}},[branch('develop'),rule(policy()),branch('master',tip),rule(policy()),branch('current'),rule(policy()),branch('develop'),rule(policy())]);
 assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs['trusted-source'],'true');assert.deepEqual(r.unused,{api:0,tools:0,fetches:0});
});
for(const changes of [{HOST_REF:'refs/heads/current'},{HOST_SHA:sha},{HOST_REF:'refs/heads/current',HOST_SHA:sha},{HOST_REF:'refs/heads/current',HOST_SHA:sha,GITHUB_REF:'refs/heads/wrong',GITHUB_SHA:sha,context:{eventName:'workflow_run'}}])test('incomplete or nonnative additional delivery host denies '+JSON.stringify(changes),()=>{
 const r=run(changes);assert.equal(r.error?.message,'protected-source-host');assert.deepEqual(r.outputs,{});
});
for(const [label,value,error]of [['unexpected key',{...facts(env),grant:true},'protected-source-facts-fields'],['missing field',Object.fromEntries(Object.entries(facts(env)).filter(([k])=>k!=='hostSha')),'protected-source-facts-fields'],['oversize',' '.repeat(65537),'protected-source-facts-bound']])test('closed original facts reject '+label,()=>{
 const r=runStep(action,'identity',{env:{FACTS:typeof value==='string'?value:JSON.stringify(value)},context});assert.equal(r.error?.message,error);assert.deepEqual(r.calls,[]);
});
test('eligible tag candidate with weak policy denies even after another valid lineage, preserving existing strong-policy parity',()=>{
 const r=run({SOURCE_REF:'refs/tags/v1.2.3',TAG:'true',DIRECTORY:'/snapshot'},[api('repos.listBranches',[{name:'develop'},{name:'support/v1'}]),branch('develop'),rule(policy()),branch('support/v1'),rule(policy({isAdminEnforced:false}))],[{result:{stdout:JSON.stringify({eligible:true})}},{result:{stdout:JSON.stringify({eligible:true})}}]);
 assert.equal(r.error?.message,'protected-source-policy');assert.deepEqual(r.outputs,{});
});
