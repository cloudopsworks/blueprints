// LOCAL real Git/ZIP/native CLI; APIs/storage are finite doubles, not hosted attestations.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {root,runStep} from './action_test_support.mjs';
const cli=process.env.TRONADOR_CLI, binding='ci/monorepo/plan/binding/action.yml',endorsement='ci/monorepo/plan/endorsement/action.yml';
assert.equal(createHash('sha256').update(fs.readFileSync(cli)).digest('hex'),'2dd1cc04bcda2d26f851cfe61355bae79e57bd48267934df1ed521a9e87538c5');
const hash=bytes=>'sha256:'+createHash('sha256').update(bytes).digest('hex');
const nativeCalls=result=>result.calls.filter(call=>call.kind==='exec'&&call.command==='tronador'&&call.result?.exitCode===0).length;
function fixture(t,history=false,count=2){
 const temp=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'normal23-native-')));t.after(()=>fs.rmSync(temp,{recursive:true,force:true}));
 const source=path.join(temp,'source');fs.cpSync(path.join(root,'tests/monorepo/fixtures/composite_first/mixed'),source,{recursive:true});
 if(count===256){const config=path.join(source,'.cloudopsworks/cloudopsworks-ci.yaml'),original=fs.readFileSync(config,'utf8');const start=original.indexOf('  go:\n'),end=original.indexOf('cd:');const component=original.slice(start,end);const first=original.slice(0,original.indexOf('components:\n'))+'components:\n';let rows='';for(let i=0;i<256;i++){const id='c'+String(i).padStart(3,'0');fs.cpSync(path.join(source,'components/go'),path.join(source,'components',id),{recursive:true});rows+=component.replace('  go:\n','  '+id+':\n').replace('path: components/go','path: components/'+id);}fs.writeFileSync(config,first+rows+'cd: {targets: {}, deployments: {}}\n');}
 const git=(...args)=>{const r=spawnSync('git',['-c','core.hooksPath=/dev/null','-c','user.name=Local','-c','user.email=local@example.invalid',...args],{cwd:source,encoding:'utf8'});assert.equal(r.status,0,r.stderr);return r.stdout.trim();};
 git('init','-q','-b','develop');git('add','.');git('commit','-qm','initial');const base=git('rev-parse','HEAD');
 if(history){fs.appendFileSync(path.join(source,'components/node/index.js'),'\n// changed\n');git('add','.');git('commit','-qm','node changed');}
 const head=git('rev-parse','HEAD'),env={RUNNER_TEMP:temp,GITHUB_REPOSITORY_ID:'123',GITHUB_REPOSITORY:'example/mixed',GITHUB_RUN_ID:'456',GITHUB_RUN_ATTEMPT:'2',EXPECTED_REPOSITORY_ID:'123',EXPECTED_REPOSITORY:'example/mixed',EXPECTED_RUN_ID:'456',EXPECTED_RUN_ATTEMPT:'2',EXPECTED_HEAD_SHA:head};
 const dir=fs.mkdtempSync(path.join(temp,'download-'));fs.chmodSync(dir,0o755);
 const receipt={repositoryId:'123',runId:'456',runAttempt:'2',headSha:head,found:history,baseSha:history?base:'',reason:history?'normal-stage-available':'normal-stage-unavailable',stage:history?{runId:'100',runAttempt:'1',artifactId:'200',archiveDigest:'sha256:'+'c'.repeat(64)}:null};
 const file=path.join(dir,'baseline.json');fs.writeFileSync(file,JSON.stringify(receipt),{mode:0o644});
 return {temp,source,base,head,env,receipt,file,git};
}
function ingress(f){
 const parsed=spawnSync('yq',['-o=json','.',path.join(root,'.github/workflows/monorepo-ci.yml')],{encoding:'utf8'});assert.equal(parsed.status,0);
 const script=JSON.parse(parsed.stdout).jobs.plan.steps.find(s=>s.id==='baseline').with.script;
 const actualCheckout=spawnSync('git',['rev-parse','HEAD'],{cwd:f.source,encoding:'utf8'});assert.equal(actualCheckout.status,0);
 const result=spawnSync(process.execPath,[path.join(root,'tests/monorepo/actions/script_worker.mjs')],{input:JSON.stringify({script,env:{...f.env,HEAD_SHA:f.head,BASELINE_PATH:f.file},tools:[{command:'git',args:['rev-parse','HEAD'],result:{stdout:actualCheckout.stdout}}]}),encoding:'utf8',env:{PATH:process.env.PATH,...f.env,HEAD_SHA:f.head,BASELINE_PATH:f.file},timeout:20000});assert.equal(result.status,0,result.stderr);return JSON.parse(result.stdout);
}
function plan(f,base){const r=runStep('ci/monorepo/plan/action.yml','plan',{realCli:cli,env:{...f.env,SOURCE_PATH:f.source,HEAD_SHA:f.head,BASE_SHA:base,VERSION:'1.2.3',PLAN_EVENT:'push',PR_NUMBER:'0',PLAN_ALL:'false'}});assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.calls[0].args[r.calls[0].args.indexOf('--base')+1],base);assert.equal(r.calls[0].args.includes('--all'),false);return r;}
function invoke(f,extra){return runStep(binding,'bind',{realCli:cli,env:{...f.env,...extra}});}
function prepare(f,p,receipt,digest){return invoke(f,{MODE:'prepare',VERIFICATION_ROLE:'',PLAN:p,CONSUMED_RECEIPT:receipt,CONSUMED_DIGEST:digest});}
function archive(f,dir){const zip=path.join(f.temp,'plan.zip');const zipped=spawnSync('zip',['-q','-X',zip,'plan.json','baseline.json'],{cwd:dir});assert.equal(zipped.status,0);const bytes=fs.readFileSync(zip);return {bytes,digest:hash(bytes),artifact:{id:789,name:'monorepo-plan-456-2',workflow_run:{id:456,head_sha:f.head},expired:false,digest:hash(bytes),size_in_bytes:bytes.length}};}
function retrieve(f,a,missingArtifact=false){
 const transport='ci/monorepo/artifact/transport/action.yml',facade='ci/monorepo/artifact/action.yml',env={...f.env,ARTIFACT_ID:'789',RUN_ID:'456',ARCHIVE_DIGEST:a.digest,RECORD_KIND:'BuildPlan'};
 const route=runStep(transport,'resolve',{env});assert.equal(route.error,undefined,JSON.stringify(route));
 const download=runStep(transport,'retrieve',{realCli:cli,env:{...env,RESOLVED_FILE:route.outputs['resolved-file']},api:[
 {method:'rest.repos.get',result:{data:{id:123}}},{method:'rest.actions.getWorkflowRun',result:{data:{id:456,repository:{id:123},head_sha:f.head}}},{method:'rest.actions.getArtifact',...(missingArtifact?{error:{status:404,message:'original-plan-missing'}}:{result:{data:a.artifact}})},{method:'request:GET /repos/{owner}/{repo}/actions/artifacts/{artifact_id}/zip',result:{status:302,headers:{location:'https://storage.invalid/plan'}}}],fetches:[{url:'https://storage.invalid/plan',base64:a.bytes.toString('base64')}]});if(download.error)return download;
 const records=runStep(facade,'records',{realCli:cli,env:{...env,BUNDLES_FILE:download.outputs['bundles-file']}});assert.equal(records.error,undefined,JSON.stringify(records));
 const payloads=runStep(facade,'payloads',{realCli:cli,env:{...env,VERIFIED_RECORDS_FILE:records.outputs['verified-records-file']}});assert.equal(payloads.error,undefined,JSON.stringify(payloads));
 const nativePhases={transport:nativeCalls(download),records:nativeCalls(records),payloads:nativeCalls(payloads)};
 return {plan:payloads.outputs.record,counts:{api:4,redirects:1,downloads:1,archiveBytes:a.bytes.length,nativePhases,native:Object.values(nativePhases).reduce((sum,count)=>sum+count,0)}};
}
function readerProof(f,a,planPath,marker,mutate=()=>{},variant={}){
 const bp='c'.repeat(40),job=(name,id)=>({id,name,run_id:456,run_attempt:2,status:'completed',conclusion:'success'});
 const p=JSON.parse(fs.readFileSync(planPath)),typed=spawnSync(cli,['components','contracts','validate','--kind','BuildPlan'],{input:fs.readFileSync(planPath),encoding:'utf8'});assert.equal(typed.status,0);
 const origin={repositoryId:'123',runId:'456',runAttempt:'2',event:'push',ref:'refs/heads/develop',hostSha:f.head,callerPath:'.github/workflows/main-build.yml',callerSha:f.head,blueprintSha:bp,sourceSha:f.head,sourceRef:'refs/heads/develop',sourceRepositoryId:'123',trustedSource:true,plannerJobId:'999',artifactId:'789',artifactName:a.artifact.name,archiveDigest:a.digest,planDigest:JSON.parse(typed.stdout).digest,checkId:'91',checkName:'monorepo-delivery/456/2',checkAppId:'15368',checkExternalId:'cloudopsworks:123:456:2',prNumber:'0',headRepositoryId:'',headSha:'',headRef:'',baseRef:'',policySha:'',closed:false,merged:false};
 const jobs=[job('lifecycle / ci / monorepo-ci-origin',998),job('lifecycle / ci / monorepo-ci-plan',999),job('lifecycle / ci / monorepo-ci-required',996),job('lifecycle / monorepo-ci-origin-init',997),...p.buildSelection.map((c,i)=>job('lifecycle / ci / monorepo-ci-build ('+c.componentId+')',700+i))];mutate(jobs);
 const proof=runStep(endorsement,'verify',{env:{...f.env,MODE:'origin-verify',CALLER_MODE:'normal-main',RUN_ID:'456',RUN_ATTEMPT:'2'},api:[{method:'rest.actions.getWorkflowRunAttempt',result:{data:{id:456,run_attempt:2,repository:{id:123},event:'push',path:origin.callerPath,referenced_workflows:['monorepo-main-build.yml','monorepo-ci.yml'].map(name=>({path:'cloudopsworks/blueprints/.github/workflows/'+name+'@v5.11.0',sha:variant.code?'d'.repeat(40):bp})),...(variant.attempt?{run_attempt:1}:{}),...(variant.caller?{path:'.github/workflows/unknown.yml'}:{})}}},{method:'rest.actions.listJobsForWorkflowRunAttempt',result:{data:{jobs}}},{method:'rest.git.getRef',result:{data:{object:{type:'commit',sha:bp}}}},...[998,999].map(id=>({method:'request:GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs',args:{job_id:id},result:{status:302,headers:{location:'https://logs.invalid/'+id}}}))],fetches:[{url:'https://logs.invalid/998',...(variant.originMissing?{status:404}:{body:'CLOUDOPSWORKS_ORIGIN_V1 '+JSON.stringify(origin)})},{url:'https://logs.invalid/999',...(variant.plannerMissing?{status:404}:{body:variant.digest?marker.replace(a.digest,'sha256:'+'f'.repeat(64)):marker})}]});
 if(proof.error)return proof;
 // This is the unchanged endorsement's actual internal data route, not a successful facade mock.
 const endorsed=retrieve(f,a,variant.artifactMissing);
 if(endorsed.error)return endorsed;
 const identity=runStep(endorsement,'identity',{realCli:cli,env:{...f.env,MODE:'origin-verify',PLAN_PATH:endorsed.plan,ORIGIN:proof.outputs.origin,JOBS:proof.outputs.jobs}});
 if(identity.error)return identity;
 const projected=completeContext(f,identity.outputs.origin,variant);
 if(projected.error)return projected;
 const facts=JSON.parse(identity.outputs.origin),typedPlan=JSON.parse(fs.readFileSync(endorsed.plan));
 return {proof,identity,context:projected,readback:endorsed,fixtureOnlyNative:{originPlanValidation:Number(typed.status===0)},bindingEnv:{MODE:'verify',VERIFICATION_ROLE:'reader',PLAN:endorsed.plan,EXPECTED_REPOSITORY_ID:facts.repositoryId,EXPECTED_REPOSITORY:typedPlan.repository.fullName,EXPECTED_RUN_ID:projected.outputs['run-id'],EXPECTED_RUN_ATTEMPT:projected.outputs['run-attempt'],EXPECTED_HEAD_SHA:projected.outputs['source-sha']}};
}
function completeContext(f,origin,variant={}){
 const contextAction='cd/tasks/repo/context/action.yml',protectedAction='cd/tasks/repo/context/protected-source/action.yml',facts=JSON.parse(origin),bp=facts.blueprintSha;
 const bytes=variant.callerBytes?Buffer.from('wrong caller'):fs.readFileSync(path.join(root,'../monorepo-app-template/.github/workflows/main-build.yml'));
 const env={...f.env,GITHUB_RUN_ID:'900',GITHUB_RUN_ATTEMPT:'1',CONTEXT_MODE:'normal',CONTEXT_RUN_ID:facts.runId,CONTEXT_RUN_ATTEMPT:facts.runAttempt,ORIGIN:origin};
 const run={id:456,run_attempt:2,repository:{id:123},event:'push',path:facts.callerPath,head_sha:variant.source?'d'.repeat(40):facts.hostSha,head_branch:'develop',status:'completed',conclusion:'success',referenced_workflows:['monorepo-main-build.yml','monorepo-ci.yml'].map(name=>({path:'cloudopsworks/blueprints/.github/workflows/'+name+'@v5.11.0',sha:bp}))};
 const normal=runStep(contextAction,'normal',{env,api:[{method:'rest.repos.get',result:{data:{id:123,default_branch:'master'}}},{method:'rest.actions.getWorkflowRunAttempt',result:{data:run}},{method:'rest.git.getRef',result:{data:{object:{type:'commit',sha:bp}}}},{method:'rest.repos.getContent',args:{path:facts.callerPath,ref:facts.callerSha},result:{data:{type:'file',encoding:'base64',content:bytes.toString('base64'),sha:createHash('sha1').update('blob '+bytes.length+'\0').update(bytes).digest('hex')}}}]});
 if(normal.error)return normal;
 assert.deepEqual(normal.unused,{api:0,tools:0,fetches:0});
 const checkedFacts=normal.outputs['origin-facts'];
 const checked=runStep(protectedAction,'identity',{env:{...env,FACTS:checkedFacts},api:[{method:'rest.repos.get',result:{data:{id:123}}}]});if(checked.error)return checked;
 assert.equal(checked.outputs.tag,'false'); // Branch route correctly skips source-configuration/tag-only action.
 const empty={totalCount:0,nodes:[],pageInfo:{hasNextPage:false}},policy={requiresApprovingReviews:true,requiredApprovingReviewCount:1,requiredStatusCheckContexts:['checkpr / Check Pull Request'],isAdminEnforced:true,dismissesStaleReviews:true,requiresStatusChecks:true,requiresStrictStatusChecks:true,allowsForcePushes:false,bypassPullRequestAllowances:empty,bypassForcePushAllowances:empty};
 const protection=runStep(protectedAction,'verify',{env:{...env,FACTS:checkedFacts,TAG:checked.outputs.tag},api:[{method:'rest.repos.getBranch',args:{branch:'develop'},result:{data:{protected:!variant.protection,commit:{sha:facts.sourceSha}}}},{method:'graphql',result:{repository:{ref:{branchProtectionRule:policy}}}},...(variant.source?[{method:'rest.repos.compareCommitsWithBasehead',args:{basehead:'d'.repeat(40)+'...'+facts.sourceSha},result:{data:{status:'ahead',base_commit:{sha:'d'.repeat(40)},merge_base_commit:{sha:'d'.repeat(40)}}}}]:[])]});if(protection.error)return protection;
 assert.deepEqual(protection.unused,{api:0,tools:0,fetches:0});
 return runStep(contextAction,'projection',{env:{IDENTITY:JSON.stringify(normal.outputs),ORIGIN:origin,TRUSTED:protection.outputs['trusted-source']}});
}
for(const history of [false,true])test(`real native ${history?'incremental exact-D local premise':'empty-base materialization'} seals and rereads companion`,t=>{
 const f=fixture(t,history);let consumed=f.file,digest=hash(fs.readFileSync(f.file));
 if(!history){const r=ingress(f);assert.equal(r.error,undefined,JSON.stringify(r));consumed=r.outputs.receipt;digest=r.outputs['receipt-digest'];assert.equal(fs.statSync(path.dirname(consumed)).mode&0o777,0o700);assert.equal(fs.statSync(consumed).mode&0o777,0o600);}else{fs.chmodSync(path.dirname(consumed),0o700);fs.chmodSync(consumed,0o600);/* Explicit D authority fixture only: production ingress rejects found=true. */assert.ok(ingress(f).error);}
 const planned=plan(f,f.receipt.baseSha),native=JSON.parse(fs.readFileSync(planned.outputs.plan));assert.deepEqual(native.buildSelection.map(x=>x.componentId),history?['node']:['go','node']);
 const sealed=prepare(f,planned.outputs.plan,consumed,digest);assert.equal(sealed.error,undefined,JSON.stringify(sealed));const a=archive(f,sealed.outputs.directory),readback=retrieve(f,a);
 const emit=runStep(endorsement,'emit',{realCli:cli,env:{...f.env,COMPUTED_PLAN:planned.outputs.plan,RETRIEVED_PLAN:readback.plan,ARTIFACT_ID:'789',ARCHIVE_DIGEST:a.digest,RUN_ID:'456',RUN_ATTEMPT:'2'},api:[{method:'rest.actions.getArtifact',result:{data:a.artifact}}]});assert.equal(emit.error,undefined,JSON.stringify(emit));
 const verified=invoke(f,{MODE:'verify',VERIFICATION_ROLE:'writer',PLAN:readback.plan,CONSUMED_RECEIPT:consumed,CONSUMED_DIGEST:digest});assert.equal(verified.error,undefined,JSON.stringify(verified));assert.deepEqual(fs.readFileSync(verified.outputs.receipt),fs.readFileSync(consumed));
 const marker=emit.logs.find(l=>l.kind==='info').message,authenticated=readerProof(f,a,readback.plan,marker);assert.equal(authenticated.error,undefined,JSON.stringify(authenticated));
 const reader=invoke(f,authenticated.bindingEnv);assert.equal(reader.error,undefined,JSON.stringify(reader));assert.equal(reader.outputs.stage,history?JSON.stringify(f.receipt.stage):'');
 const positiveProductionNativePhases={planner:nativeCalls(planned),prepare:nativeCalls(sealed),writerReadback:readback.counts.native,endorsementEmit:nativeCalls(emit),writerVerify:nativeCalls(verified),readerReadback:authenticated.readback.counts.native,readerIdentity:nativeCalls(authenticated.identity),readerBinding:nativeCalls(reader)};
 t.diagnostic(JSON.stringify({localOnly:true,scope:'this positive production path only; excludes fixture-only calls, negative cases, other tests and history admission',historyAuthority:history?'fixture premise':'none',productionNative:{phases:positiveProductionNativePhases,subtotal:Object.values(positiveProductionNativePhases).reduce((sum,count)=>sum+count,0)},fixtureOnlyNative:authenticated.fixtureOnlyNative,transportReadbacks:{writer:readback.counts,reader:authenticated.readback.counts},mutations:0}));
 for(const conclusion of ['failure','cancelled','skipped']){const bad=readerProof(f,a,readback.plan,marker,jobs=>{jobs.find(j=>j.id===999).conclusion=conclusion;});assert.equal(bad.error?.message,'planner-job-status');assert.equal(bad.outputs?.origin,undefined);}
 // A same-base D2 companion cannot replace consumed D bytes after an otherwise valid seal.
 const other={...f.receipt,...(history?{stage:{...f.receipt.stage,artifactId:'201'}}:{reason:'preview-receipt-absent'})};fs.writeFileSync(verified.outputs.receipt,JSON.stringify(other));
 const changed=invoke(f,{MODE:'verify',VERIFICATION_ROLE:'writer',PLAN:readback.plan,CONSUMED_RECEIPT:consumed,CONSUMED_DIGEST:digest});assert.equal(changed.error?.message,'binding-consumed-bytes');assert.deepEqual(changed.outputs,{});
});
test('real valid nonempty base cannot replace empty-input C2 materialization',t=>{const f=fixture(t,true);f.receipt.found=false;f.receipt.baseSha='';f.receipt.stage=null;f.receipt.reason='normal-stage-unavailable';fs.chmodSync(path.dirname(f.file),0o700);fs.chmodSync(f.file,0o600);fs.writeFileSync(f.file,JSON.stringify(f.receipt));const p=plan(f,f.base),r=prepare(f,p.outputs.plan,f.file,hash(fs.readFileSync(f.file)));assert.equal(r.error?.message,'binding-native-base');assert.deepEqual(r.outputs,{});});
test('real256 native components bind, and late invalid selection withholds all outputs',t=>{const f=fixture(t,false,256),ingressed=ingress(f);assert.equal(ingressed.error,undefined,JSON.stringify(ingressed));const p=plan(f,''),record=JSON.parse(fs.readFileSync(p.outputs.plan));assert.equal(record.components.length,256);const good=prepare(f,p.outputs.plan,ingressed.outputs.receipt,ingressed.outputs['receipt-digest']);assert.equal(good.error,undefined,JSON.stringify(good));record.buildSelection[255].componentId='not-a-component';fs.writeFileSync(p.outputs.plan,JSON.stringify(record));const bad=prepare(f,p.outputs.plan,ingressed.outputs.receipt,ingressed.outputs['receipt-digest']);assert.equal(bad.error?.message,'binding-native-plan');assert.deepEqual(bad.outputs,{});});

test('complete fresh original reader chain rejects authority contradictions before binding',t=>{
 const f=fixture(t),ingressed=ingress(f);assert.equal(ingressed.error,undefined);const planned=plan(f,''),sealed=prepare(f,planned.outputs.plan,ingressed.outputs.receipt,ingressed.outputs['receipt-digest']);assert.equal(sealed.error,undefined);
 const a=archive(f,sealed.outputs.directory),readback=retrieve(f,a),emitted=runStep(endorsement,'emit',{realCli:cli,env:{...f.env,COMPUTED_PLAN:planned.outputs.plan,RETRIEVED_PLAN:readback.plan,ARTIFACT_ID:'789',ARCHIVE_DIGEST:a.digest,RUN_ID:'456',RUN_ATTEMPT:'2'},api:[{method:'rest.actions.getArtifact',result:{data:a.artifact}}]});assert.equal(emitted.error,undefined);const marker=emitted.logs.find(l=>l.kind==='info').message;
 for(const [name,variant,expected]of [['caller',{caller:true},'origin-producer-api'],['code',{code:true},'origin-producer-code'],['attempt',{attempt:true},'planner-run-attempt'],['digest',{digest:true},'planner-marker-binding'],['origin log',{originMissing:true},'planner-log-transfer'],['planner log',{plannerMissing:true},'planner-log-transfer'],['caller bytes',{callerBytes:true},'normal-context-caller-definition'],['source',{source:true},'normal-context-origin-binding'],['protection',{protection:true},'protected-source-policy'],['original plan',{artifactMissing:true},'original-plan-missing']]){
  const r=readerProof(f,a,readback.plan,marker,()=>{},variant);assert.equal(r.error?.message,expected,name+':'+JSON.stringify(r));assert.equal(r.bindingEnv,undefined);assert.equal(r.outputs?.stage,undefined);
 }
});

for(const reason of ['stage-artifact-unavailable','original-artifact-unavailable'])test(`real unavailable materialization retains ${reason} as diagnostic only`,t=>{
 const f=fixture(t);f.receipt.reason=reason;fs.writeFileSync(f.file,JSON.stringify(f.receipt));const ingressed=ingress(f);assert.equal(ingressed.error,undefined);const p=plan(f,''),sealed=prepare(f,p.outputs.plan,ingressed.outputs.receipt,ingressed.outputs['receipt-digest']);assert.equal(sealed.error,undefined,JSON.stringify(sealed));assert.equal(JSON.parse(fs.readFileSync(sealed.outputs.receipt)).reason,reason);assert.equal(sealed.outputs.stage,'');
 // No authority is inferred from the literal: missing original planner log still denies earlier.
 const a=archive(f,sealed.outputs.directory),readback=retrieve(f,a),marker='CLOUDOPSWORKS_STAGE_V1 '+JSON.stringify({repositoryId:'123',runId:'456',runAttempt:'2',artifactId:'789',artifactName:a.artifact.name,archiveDigest:a.digest});
 for(const [variant,error]of [[{plannerMissing:true},'planner-log-transfer'],[{artifactMissing:true},'original-plan-missing']]){const denied=readerProof(f,a,readback.plan,marker,()=>{},variant);assert.equal(denied.error?.message,error);assert.equal(denied.bindingEnv,undefined);assert.equal(denied.outputs?.origin,undefined);assert.equal(denied.outputs?.stage,undefined);assert.equal(denied.outputs?.record,undefined);}
});
