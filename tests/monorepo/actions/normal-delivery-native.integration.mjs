// LOCAL native Git + unchanged installed CLI + actual production YAML bodies.
// Finite API replies prove local protocol behavior, not a hosted run or uploaded archive.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {root,runStep} from './action_test_support.mjs';
const cli=process.env.TRONADOR_CLI;
assert.ok(cli&&fs.existsSync(cli),'TRONADOR_CLI must identify the unchanged installed binary; no skipped native proof');
const action='ci/monorepo/plan/endorsement/action.yml',archive='sha256:'+'a'.repeat(64);
function fixture(t){
 const temp=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'origin-native-')));t.after(()=>fs.rmSync(temp,{recursive:true,force:true}));
 const source=path.join(temp,'source');fs.cpSync(path.join(root,'tests/monorepo/fixtures/composite_first/mixed'),source,{recursive:true});
 const git=(...args)=>{const r=spawnSync('git',['-c','core.hooksPath=/dev/null','-c','user.name=Local','-c','user.email=local@example.invalid',...args],{cwd:source,encoding:'utf8'});assert.equal(r.status,0,r.stderr);return r.stdout.trim();};
 git('init','-q','-b','develop');git('add','.');git('commit','-qm','original');
 const env={RUNNER_TEMP:temp,HOME:temp,GITHUB_REPOSITORY_ID:'123',GITHUB_REPOSITORY:'example/mixed',GITHUB_RUN_ID:'456',GITHUB_RUN_ATTEMPT:'2'};
 const invoke=(id,options={})=>runStep(action,id,{realCli:cli,...options,env:{...env,...options.env}});
 const planned=runStep('ci/monorepo/plan/action.yml','plan',{realCli:cli,env:{...env,SOURCE_PATH:source,HEAD_SHA:git('rev-parse','HEAD'),BASE_SHA:'',VERSION:'1.2.3',PLAN_EVENT:'push',PR_NUMBER:'0'}});
 assert.equal(planned.error,undefined,JSON.stringify(planned));
 const computed=planned.outputs.plan,plan=JSON.parse(fs.readFileSync(computed));
 const validated=spawnSync(cli,['components','contracts','validate','--kind','BuildPlan'],{input:fs.readFileSync(computed),encoding:'utf8',env:{PATH:process.env.PATH}});
 assert.equal(validated.status,0,validated.stderr);const digest=JSON.parse(validated.stdout).digest;
 const retrieved=path.join(temp,'retrieved.json');fs.copyFileSync(computed,retrieved);
 const jobs=plan.buildSelection.map(({componentId},i)=>({id:700+i,name:`lifecycle / ci / monorepo-ci-build (${componentId})`,run_id:456,run_attempt:2,status:'completed',conclusion:'success'}));
 assert.ok(jobs.length>=2,'mixed real Git planner fixture must select multiple actual components');
 return {temp,computed,retrieved,plan,digest,jobs,invoke};
}
test('real Git planner computed bytes and independently retrieved copy retain original inline writer edge',t=>{
 const f=fixture(t);const r=f.invoke('emit',{env:{COMPUTED_PLAN:f.computed,RETRIEVED_PLAN:f.retrieved,ARTIFACT_ID:'789',ARCHIVE_DIGEST:archive,RUN_ID:'456',RUN_ATTEMPT:'2'},api:[{method:'rest.actions.getArtifact',result:{data:{id:789,name:'monorepo-plan-456-2',digest:archive,expired:false,workflow_run:{id:456}}}}]});
 assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.logs.filter(x=>x.kind==='info').length,1);assert.deepEqual(r.unused,{api:0,tools:0,fetches:0});
});
test('another valid version plan cannot replace original computed planner selection bytes',t=>{
 const f=fixture(t);fs.writeFileSync(f.retrieved,JSON.stringify({...f.plan,version:'9.9.9'}));
 const r=f.invoke('emit',{env:{COMPUTED_PLAN:f.computed,RETRIEVED_PLAN:f.retrieved,ARTIFACT_ID:'789',ARCHIVE_DIGEST:archive,RUN_ID:'456',RUN_ATTEMPT:'2'}});
 assert.equal(r.error?.message,'planner-writer-bytes');assert.deepEqual(r.logs,[]);assert.equal(r.calls.some(x=>x.kind==='api'),false);
});
for(const variant of ['current','retained selected build','missing selected build','changed typed digest','changed source'])test(`real typed origin plan admission: ${variant}`,t=>{
 const f=fixture(t),origin={repositoryId:'123',runId:'456',runAttempt:'2',event:'push',ref:'refs/heads/develop',sourceRef:'refs/heads/develop',sourceRepositoryId:'123',trustedSource:true,prNumber:'0',headRepositoryId:'',headSha:'',headRef:'',baseRef:'',policySha:'',closed:false,merged:false,checkId:'91',checkAppId:'15368',checkName:'monorepo-delivery/456/2',checkExternalId:'cloudopsworks:123:456:2',sourceSha:f.plan.headSha,planDigest:f.digest};
 let jobs=f.jobs;
 if(variant==='retained selected build')jobs=[{...jobs[0],run_attempt:1},...jobs.slice(1)];
 if(variant==='missing selected build')jobs=jobs.slice(1);
 if(variant==='changed typed digest')origin.planDigest='sha256:'+'b'.repeat(64);
 if(variant==='changed source')origin.sourceSha='c'.repeat(40);
 const r=f.invoke('identity',{env:{PLAN_PATH:f.retrieved,MODE:'origin-verify',ORIGIN:JSON.stringify(origin),JOBS:JSON.stringify(jobs)}});
 assert.equal(!r.error,variant==='current',JSON.stringify(r));
 if(variant!=='current'){assert.equal(r.error.message,['retained selected build','missing selected build'].includes(variant)?'origin-selected-build-attempt':'origin-plan-binding');assert.deepEqual(r.outputs,{});}
});
for(const name of ['develop','support/1.x','release/1.2','master','main'])test(`actual unchanged CLI tag-lineage eligibility: ${name}`,t=>{
 const temp=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'tag-source-')));t.after(()=>fs.rmSync(temp,{recursive:true,force:true}));
 const config=path.join(temp,'.cloudopsworks');fs.mkdirSync(config);
 const bytes=fs.readFileSync(path.join(root,'tests/monorepo/fixtures/composite_first/mixed/.cloudopsworks/cloudopsworks-ci.yaml'),'utf8').replace('cd: {targets: {}, deployments: {}}','cd: {targets: {}, deployments: {develop: {env: dev}, test: {env: uat}, release: {env: prod}, support: [{match: ".*", env: maint}]}}');
 fs.writeFileSync(path.join(config,'cloudopsworks-ci.yaml'),bytes);
 const sha='a'.repeat(40),empty=()=>({totalCount:0,nodes:[],pageInfo:{hasNextPage:false}}),policy={requiresApprovingReviews:true,requiredApprovingReviewCount:1,requiredStatusCheckContexts:['checkpr / Check Pull Request'],isAdminEnforced:true,dismissesStaleReviews:true,requiresStatusChecks:true,requiresStrictStatusChecks:true,allowsForcePushes:false,bypassPullRequestAllowances:empty(),bypassForcePushAllowances:empty()};
 const facts={event:'push',ref:'refs/tags/v1.2.3',hostSha:sha,callerPath:'.github/workflows/main-build.yml',callerSha:sha,blueprintSha:'b'.repeat(40),sourceSha:sha,sourceRef:'refs/tags/v1.2.3',sourceRepositoryId:'123',trustedSource:true,prNumber:'0',headRepositoryId:'',headSha:'',headRef:'',baseRef:'',policySha:'',closed:false,merged:false};
 const eligible=!['master','main'].includes(name),api=[{method:'rest.repos.listBranches',result:{data:[{name}]}}];
 if(eligible)api.push({method:'rest.repos.getBranch',args:{branch:name},result:{data:{protected:true,commit:{sha}}}},{method:'graphql',result:{repository:{ref:{branchProtectionRule:policy}}}});
 const r=runStep('cd/tasks/repo/context/protected-source/action.yml','verify',{realCli:cli,env:{GITHUB_REPOSITORY_ID:'123',FACTS:JSON.stringify(facts),TAG:'true',DIRECTORY:temp},context:{repo:{owner:'example',repo:'mixed'}},api});
 assert.equal(r.error?.message,eligible?undefined:'protected-source-tag-lineage',JSON.stringify(r));assert.deepEqual(r.unused,{api:0,tools:0,fetches:0});
 const command=r.calls.find(c=>c.kind==='exec');assert.equal(command.args[command.args.indexOf('--workdir')+1],temp);assert.equal(command.result.exitCode,0);assert.equal(JSON.parse(command.result.stdout).eligible,eligible);
});
