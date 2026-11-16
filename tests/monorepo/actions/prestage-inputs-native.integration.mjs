// LOCAL actual YAML + real Tronador validators + native ZIP, with finite GitHub API/log/storage doubles.
// Payloads are existing ZIP/OCI unit archives, not packaged applications or completed scans.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {runStep} from './action_test_support.mjs';
const cli=process.env.TRONADOR_CLI;
assert.ok(cli&&fs.existsSync(cli),'TRONADOR_CLI must name the actual CLI; never silently skipped');
const inputAction='ci/monorepo/stage/inputs/action.yml',artifactAction='ci/monorepo/artifact/action.yml',transportAction='ci/monorepo/artifact/transport/action.yml';
const fixtures=fileURLToPath(new URL('../fixtures/composite_first/mixed/',import.meta.url));
const archives=fileURLToPath(new URL('../../../../tronador-cli-v511/internal/components/testdata/contracts/artifacts/',import.meta.url));
const identities=JSON.parse(fs.readFileSync(path.join(archives,'identities.json')));
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
const blob=bytes=>createHash('sha1').update(`blob ${bytes.length}\0`).update(bytes).digest('hex');
function fixture(t){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'prestage-native-')));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const source=path.join(root,'source');fs.cpSync(fixtures,source,{recursive:true});
 const env={RUNNER_TEMP:root,HOME:root,GITHUB_REPOSITORY_ID:'123',GITHUB_REPOSITORY:'example/mixed',GITHUB_RUN_ID:'456',GITHUB_RUN_ATTEMPT:'2'};
 const invoke=(action,id,options={})=>runStep(action,id,{realCli:cli,...options,env:{...env,...options.env}});
 const passed=result=>{assert.equal(result.error,undefined,JSON.stringify(result));assert.deepEqual(result.unused,{api:0,tools:0,fetches:0});return result.outputs;};
 const save=(name,record)=>{const p=path.join(root,name+'.json');fs.writeFileSync(p,JSON.stringify(record));return p;};
 const git=(...args)=>{const r=spawnSync('git',['-c','core.hooksPath=/dev/null','-c','user.name=Local','-c','user.email=local@example.invalid',...args],{cwd:source,encoding:'utf8'});assert.equal(r.status,0,r.stderr);return r.stdout.trim();};
 git('init','-q','-b','develop');git('add','.');git('commit','-qm','initial');
 function plan(base,version){const head=git('rev-parse','HEAD'),o=passed(invoke('ci/monorepo/plan/action.yml','plan',{env:{SOURCE_PATH:source,HEAD_SHA:head,BASE_SHA:base,VERSION:version,PLAN_EVENT:'push',PR_NUMBER:'0'}}));return {file:o.plan,record:JSON.parse(fs.readFileSync(o.plan)),head};}
 const original=plan('','1.2.3');
 fs.appendFileSync(path.join(source,'components/node/index.js'),'\n// baseline node edit\n');git('add','.');git('commit','-qm','baseline');const baseline=plan(original.head,'1.2.4');
 fs.appendFileSync(path.join(source,'components/node/index.js'),'\n// current node edit\n');git('add','.');git('commit','-qm','current');const current=plan(baseline.head,'1.2.5');
 assert.deepEqual(current.record.buildSelection.map(x=>x.componentId),['node']);assert.deepEqual(baseline.record.buildSelection.map(x=>x.componentId),['node']);
 function bundle(name,run,attempt,id,head,files){
  const directory=path.join(root,'zip-'+name);fs.mkdirSync(directory);
  for(const [relative,body]of Object.entries(files)){const p=path.join(directory,relative);fs.mkdirSync(path.dirname(p),{recursive:true});fs.writeFileSync(p,body);}
  const zip=path.join(root,name+'.zip'),r=spawnSync('zip',['-q',zip,...Object.keys(files)],{cwd:directory,encoding:'utf8'});assert.equal(r.status,0,r.stderr);
  const bytes=fs.readFileSync(zip),artifact={id:Number(id),name,digest:'sha256:'+hash(bytes),expired:false,size_in_bytes:bytes.length,workflow_run:{id:Number(run),head_sha:head}};
  return {run:String(run),attempt:String(attempt),id:String(id),head,bytes,artifact};
 }
 function data(item,kind,planFile){
  const route={ARTIFACT_ID:item.id,RUN_ID:item.run,ARCHIVE_DIGEST:item.artifact.digest};
  const resolved=passed(invoke(transportAction,'resolve',{env:route}));
  const downloaded=passed(invoke(transportAction,'retrieve',{env:{...route,RESOLVED_FILE:resolved['resolved-file']},api:[
   {method:'rest.repos.get',result:{data:{id:123}}},{method:'rest.actions.getWorkflowRun',result:{data:{id:Number(item.run),repository:{id:123},head_sha:item.head}}},
   {method:'rest.actions.getArtifact',result:{data:item.artifact}},{method:'request:GET /repos/{owner}/{repo}/actions/artifacts/{artifact_id}/zip',result:{status:302,headers:{location:'https://storage.invalid/'+item.id}}}],fetches:[{url:'https://storage.invalid/'+item.id,base64:item.bytes.toString('base64')}]}));
  const typed=invoke(artifactAction,'records',{env:{BUNDLES_FILE:downloaded['bundles-file'],RECORD_KIND:kind,PLAN_PATH:planFile||''}});
  if(typed.error)return typed;
  const payload=invoke(artifactAction,'payloads',{env:{VERIFIED_RECORDS_FILE:typed.outputs['verified-records-file']}});
  return payload;
 }
 function protectedSource(facts,context){
  const action='cd/tasks/repo/context/protected-source/action.yml',empty=()=>({totalCount:0,nodes:[],pageInfo:{hasNextPage:false}});
  const policy={requiresApprovingReviews:true,requiredApprovingReviewCount:1,requiredStatusCheckContexts:['checkpr / Check Pull Request'],isAdminEnforced:true,dismissesStaleReviews:true,requiresStatusChecks:true,requiresStrictStatusChecks:true,allowsForcePushes:false,bypassPullRequestAllowances:empty(),bypassForcePushAllowances:empty()};
  const env={FACTS:JSON.stringify(facts),TAG:'false',HOST_REF:'',HOST_SHA:''};
  passed(invoke(action,'identity',{env,context,api:[{method:'rest.repos.get',result:{data:{id:123}}}]}));
  return passed(invoke(action,'verify',{env,context,api:[{method:'rest.repos.getBranch',args:{branch:'develop'},result:{data:{protected:true,commit:{sha:facts.sourceSha}}}},{method:'graphql',args:{ref:'refs/heads/develop'},result:{repository:{ref:{branchProtectionRule:policy}}}}]}))['trusted-source'];
 }
 function caller(run,attempt,head,diagnostic=false){
  const filename=diagnostic?'composite-first-slice.yml':'main-build.yml';
  const bytes=fs.readFileSync(fileURLToPath(new URL('../../../../monorepo-app-template/.github/workflows/'+filename,import.meta.url)));
  const context={repo:{owner:'example',repo:'mixed'},eventName:diagnostic?'workflow_dispatch':'push'};
  const origin=!diagnostic&&String(run)!==env.GITHUB_RUN_ID?authenticatedOrigin(originalPlan,originalMarker,original.file):'';
  const file={method:'rest.repos.getContent',args:{ref:head},result:{data:{type:'file',encoding:'base64',sha:blob(bytes),content:bytes.toString('base64')}}};
  const release={method:'rest.git.getRef',result:{data:{object:{type:'commit',sha:'b'.repeat(40)}}}};
  const raw=invoke('cd/tasks/repo/context/action.yml',diagnostic?'verify':'normal',{env:{CONTEXT_MODE:diagnostic?'diagnostic':'normal',CONTEXT_RUN_ID:String(run),CONTEXT_RUN_ATTEMPT:String(attempt),GITHUB_SHA:head,GITHUB_WORKFLOW_SHA:head,GITHUB_REF:'refs/heads/develop',ORIGIN:origin},context,api:[
   {method:'rest.repos.get',result:{data:{id:123,default_branch:'develop'}}},
   {method:'rest.actions.getWorkflowRunAttempt',args:{run_id:String(run),attempt_number:String(attempt)},result:{data:{id:Number(run),run_attempt:Number(attempt),repository:{id:123},event:diagnostic?'workflow_dispatch':'push',path:'.github/workflows/'+filename,head_sha:head,head_branch:'develop',pull_requests:[],referenced_workflows:(diagnostic?['monorepo-delivery-slice.yml']:['monorepo-main-build.yml','monorepo-ci.yml']).map(name=>({path:'cloudopsworks/blueprints/.github/workflows/'+name+'@v5.11.0',sha:'b'.repeat(40)}))}}},
   ...(diagnostic?[{method:'rest.repos.getBranch',result:{data:{protected:true,commit:{sha:head}}}},file,release]:[release,file])]});
  if(diagnostic||raw.error)return raw;
  const identity=passed(raw),trusted=protectedSource(JSON.parse(identity['origin-facts']),context);
  return invoke('cd/tasks/repo/context/action.yml','projection',{env:{IDENTITY:JSON.stringify(identity),ORIGIN:origin,TRUSTED:trusted}});
 }
 const originalPlan=bundle('monorepo-plan-450-1',450,1,1450,original.head,{'plan.json':fs.readFileSync(original.file)});
 const currentPlan=bundle('monorepo-plan-456-2',456,2,1456,current.head,{'plan.json':fs.readFileSync(current.file)});
 function receipt(item,kind,computedFile,computedManifest){
  const downloaded=passed(data(item,kind));
  const common={RUN_ID:item.run,RUN_ATTEMPT:item.attempt,ARTIFACT_ID:item.id,ARCHIVE_DIGEST:item.artifact.digest};
  const action=kind==='BuildPlan'?'ci/monorepo/plan/endorsement/action.yml':'ci/monorepo/stage/endorsement/action.yml';
  const emitted=invoke(action,'emit',{env:{...common,GITHUB_RUN_ID:item.run,GITHUB_RUN_ATTEMPT:item.attempt,...(kind==='BuildPlan'?{COMPUTED_PLAN:computedFile,RETRIEVED_PLAN:downloaded.record}:{COMPUTED_PLAN:computedFile,RETRIEVED_PLAN:path.join(downloaded.directory,'plan.json'),COMPUTED_MANIFEST:computedManifest,RETRIEVED_MANIFEST:downloaded.record})},api:[{method:'rest.actions.getArtifact',result:{data:item.artifact}}]});
  passed(emitted);return emitted.logs.find(x=>x.kind==='info').message;
 }
 const currentMarker=receipt(currentPlan,'BuildPlan',current.file),originalMarker=receipt(originalPlan,'BuildPlan',original.file);

 // Execute the actual two independent log edges and typed transport before historical context admission.
 // API/storage doubles model native original production separately from current-host verification.
 function authenticatedOrigin(item,plannerMarker,planFile){
  const action='ci/monorepo/plan/endorsement/action.yml',run={id:Number(item.run),run_attempt:Number(item.attempt),repository:{id:123},head_sha:item.head,event:'push',path:'.github/workflows/main-build.yml',head_branch:'develop',referenced_workflows:['monorepo-main-build.yml','monorepo-ci.yml'].map(name=>({path:'cloudopsworks/blueprints/.github/workflows/'+name+'@v5.11.0',sha:'b'.repeat(40)}))};
  const common={RUN_ID:item.run,RUN_ATTEMPT:item.attempt,ARTIFACT_ID:item.id,ARCHIVE_DIGEST:item.artifact.digest,CALLER_MODE:'normal-main'};
  const native={GITHUB_RUN_ID:item.run,GITHUB_RUN_ATTEMPT:item.attempt,GITHUB_SHA:item.head,GITHUB_WORKFLOW_SHA:item.head,GITHUB_REF:'refs/heads/develop'};
  const context={eventName:'push',repo:{owner:'example',repo:'mixed'},payload:{}};
  const job=(name,id)=>({id,name,run_id:Number(item.run),run_attempt:Number(item.attempt),status:'completed',conclusion:'success'});
  const plan=JSON.parse(fs.readFileSync(planFile)),jobs=[job('lifecycle / ci / monorepo-ci-plan',900),job('lifecycle / ci / monorepo-ci-origin',902),job('lifecycle / ci / monorepo-ci-required',903),job('lifecycle / monorepo-ci-origin-init',904),...plan.buildSelection.map(({componentId},index)=>job('lifecycle / ci / monorepo-ci-build ('+componentId+')',910+index))];
  const check={id:91,name:'monorepo-delivery/'+item.run+'/'+item.attempt,external_id:'cloudopsworks:123:'+item.run+':'+item.attempt,head_sha:item.head,status:'queued',conclusion:null,app:{id:15368,slug:'github-actions'},details_url:'https://github.com/example/mixed/actions/runs/'+item.run+'/attempts/'+item.attempt};
  const initialized=invoke('ci/monorepo/delivery-check/action.yml','check',{env:{...native,PHASE:'initialize',CALLER_MODE:'normal-main',ORIGIN_RUN_ID:item.run,ORIGIN_RUN_ATTEMPT:item.attempt,SOURCE_SHA:item.head,CHECK_ID:'',ENDORSED_CHECK_NAME:'',GITHUB_SERVER_URL:'https://github.com'},context,api:[{method:'rest.checks.create',result:{data:check}},{method:'rest.checks.get',result:{data:check}}]});
  passed(initialized);const acknowledgement=initialized.logs.find(x=>x.kind==='info').message;
  const release={method:'rest.git.getRef',result:{data:{object:{type:'commit',sha:'b'.repeat(40)}}}};
  const endpoints=[{method:'rest.actions.getWorkflowRunAttempt',result:{data:run}},{method:'rest.actions.listJobsForWorkflowRunAttempt',result:{data:{jobs}}}];
  const log=(id)=>({method:'request:GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs',args:{job_id:id},result:{status:302,headers:{location:'https://logs.invalid/'+item.run+'/'+id}}});
  const fetch=(id,body)=>({url:'https://logs.invalid/'+item.run+'/'+id,body});
  const first=passed(invoke(action,'verify',{env:{...common,MODE:'origin-emit',CHECK_ID:initialized.outputs['check-id']},context,api:[...endpoints,release,log(900),log(904),{method:'rest.checks.get',result:{data:check}}],fetches:[fetch(900,plannerMarker),fetch(904,acknowledgement)]}));
  const downloaded=passed(data(item,'BuildPlan'));
  const typed=passed(invoke(action,'identity',{env:{MODE:'origin-emit',PLAN_PATH:downloaded.record}}));
  const facts={event:'push',ref:'refs/heads/develop',hostSha:item.head,callerPath:'.github/workflows/main-build.yml',callerSha:item.head,blueprintSha:'b'.repeat(40),sourceSha:item.head,sourceRef:'refs/heads/develop',sourceRepositoryId:'123',trustedSource:true,prNumber:'0',headRepositoryId:'',headSha:'',headRef:'',baseRef:'',policySha:'',closed:false,merged:false};
  const trusted=protectedSource(facts,context);
  const emitted=invoke(action,'origin',{env:{...common,...native,BLUEPRINT_SHA:first['blueprint-sha'],SOURCE_TRUSTED:trusted,ORIGIN_FACTS:JSON.stringify(facts),PLAN_SOURCE:typed['source-sha'],PLAN_DIGEST:typed['plan-digest'],PLAN_JOB_ID:first['planner-job-id'],CHECK:first.check},context,api:[endpoints[0]]});
  passed(emitted);const originMarker=emitted.logs.find(x=>x.kind==='info').message;
  const verified=passed(invoke(action,'verify',{env:{...common,MODE:'origin-verify'},context,api:[...endpoints,release,log(902),log(900)],fetches:[fetch(902,originMarker),fetch(900,plannerMarker)]}));
  const retrieved=passed(data(item,'BuildPlan'));
  const admitted=passed(invoke(action,'identity',{env:{MODE:'origin-verify',PLAN_PATH:retrieved.record,ORIGIN:verified.origin,JOBS:verified.jobs}}));
  return admitted.origin;
 }
 function endorsement(item,marker,diagnostic=false,change={}){
  const action=diagnostic?'ci/monorepo/stage/endorsement/action.yml':'ci/monorepo/plan/endorsement/action.yml';
  return invoke(action,'verify',{env:{MODE:'verify',CALLER_MODE:diagnostic?'reusable':'normal-main',ARTIFACT_ID:item.id,ARCHIVE_DIGEST:item.artifact.digest,RUN_ID:item.run,RUN_ATTEMPT:item.attempt},api:[
   {method:'rest.actions.getWorkflowRunAttempt',result:{data:{id:Number(item.run),run_attempt:Number(item.attempt),repository:{id:123}}}},
   {method:'rest.actions.listJobsForWorkflowRunAttempt',result:{data:{jobs:[{id:900,name:diagnostic?'Monorepo delivery slice / stage':'lifecycle / ci / monorepo-ci-plan',run_id:Number(item.run),run_attempt:Number(item.attempt),status:'completed',conclusion:'success',...change.job}]}}},
   {method:'request:GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs',result:{status:302,headers:{location:'https://logs.invalid/'+item.id}}}],fetches:[{url:'https://logs.invalid/'+item.id,body:marker}]});
 }
 function component(plan,id,run,attempt,artifactId){
  const descriptor=(kind,format,file,digest,sizeBytes)=>({kind,format,digest,sizeBytes,location:{kind:'local',path:`.cloudopsworks/out/${id}/${plan.record.version}/${file}`},sourceSha:plan.head,builtVersion:plan.record.version});
  const result={apiVersion:'cloudopsworks.io/v1',kind:'ComponentResult',repository:plan.record.repository,componentId:id,headSha:plan.head,version:plan.record.version,purpose:'release',status:'succeeded',mainArtifact:descriptor('function','zip','main.zip',identities.zip.digest,identities.zip.sizeBytes),previewArtifact:descriptor('container','oci','preview.oci.tar',identities.oci.rootDigest,identities.oci.rootSizeBytes),error:null};
  const item=bundle(`components-${run}-${attempt}-${id}`,run,attempt,artifactId,plan.head,{[`results/${id}.json`]:JSON.stringify(result),[result.mainArtifact.location.path]:fs.readFileSync(path.join(archives,'app.zip')),[result.previewArtifact.location.path]:fs.readFileSync(path.join(archives,'image.oci.tar'))});
  return {...item,result};
 }
 const oldGo=component(original,'go',450,1,700),baselineNode=component(baseline,'node',455,1,701),currentNode=component(current,'node',456,2,702);
 const entry=(id,item)=>{const component=baseline.record.components.find(c=>c.id===id),entry={componentId:id,package:component.package,workload:component.workload,targetIds:component.targetIds};for(const key of ['mainArtifact','previewArtifact'])entry[key]={...item.result[key],location:{kind:'actions-artifact',repositoryId:'123',runId:item.run,runAttempt:item.attempt,artifactId:item.id,artifactName:item.artifact.name,path:item.result[key].location.path}};return entry;};
 const manifest={apiVersion:'cloudopsworks.io/v1',kind:'ReleaseManifest',repository:baseline.record.repository,version:baseline.record.version,tag:'v'+baseline.record.version,headSha:baseline.head,previousTag:'v1.2.3',state:'complete',components:baseline.record.components.map(c=>entry(c.id,c.id==='go'?oldGo:baselineNode)),targets:baseline.record.targets};
 const manifestFile=save('baseline-manifest',manifest),stage=bundle('monorepo-stage-455-1',455,1,800,baseline.head,{'plan.json':fs.readFileSync(baseline.file),'manifest.json':fs.readFileSync(manifestFile)}),stageMarker=receipt(stage,'ReleaseManifest',baseline.file,manifestFile);
 const currentContext=passed(caller(456,2,current.head));passed(endorsement(currentPlan,currentMarker));const downloadedPlan=passed(data(currentPlan,'BuildPlan')).record;
 const config=path.join(source,'.cloudopsworks/cloudopsworks-ci.yaml'),bytes=fs.readFileSync(config),tree='f'.repeat(40),configBlob=blob(bytes);
 const snapshot=passed(invoke('ci/monorepo/source/action.yml','snapshot',{env:{SOURCE_SHA:current.head},api:[{method:'rest.git.getCommit',result:{data:{sha:current.head,tree:{sha:tree}}}},{method:'rest.git.getTree',result:{data:{truncated:false,tree:[{path:'.cloudopsworks/cloudopsworks-ci.yaml',mode:'100644',type:'blob',sha:configBlob,size:bytes.length}]}}},{method:'rest.git.getBlob',result:{data:{sha:configBlob,encoding:'base64',content:bytes.toString('base64')}}}]}));
 const configuration=passed(invoke('ci/monorepo/source/action.yml','normalize',{env:{DIRECTORY:snapshot.directory}})).configuration;
 function resolve(id,change={}){
  const carried=id==='go',owner=carried?oldGo:currentNode;
  const route=invoke(inputAction,'route',{env:{PLAN:downloadedPlan,CONFIGURATION:configuration,SOURCE_SHA:currentContext['source-sha'],COMPONENT:id,...(carried?{BASELINE_RUN_ID:'455',BASELINE_RUN_ATTEMPT:'1',BASELINE_ARTIFACT_ID:'800',BASELINE_ARCHIVE_DIGEST:stage.artifact.digest}:{}),...change.route}});
  if(route.error)return route;assert.equal(route.outputs.carried,String(carried));
  let baselineDirectory='',baselineManifest='';
  if(carried){passed(caller(455,1,baseline.head,true));passed(endorsement(stage,stageMarker,true));const baselineData=passed(data(stage,'ReleaseManifest'));baselineDirectory=baselineData.directory;baselineManifest=baselineData.record;}
  const origin=invoke(inputAction,'origin',{env:{PLAN:downloadedPlan,COMPONENT:id,CARRIED:String(carried),RUN_ID:'456',RUN_ATTEMPT:'2',BASELINE_PLAN:path.join(baselineDirectory,'plan.json'),BASELINE_MANIFEST:baselineManifest,BASELINE_SOURCE:baseline.head,...change.origin}});
  if(origin.error)return origin;
  let originalFile=downloadedPlan,ownerContext=currentContext;
  if(carried){ownerContext=passed(caller(origin.outputs['run-id'],origin.outputs['run-attempt'],original.head));}
  const job={id:901,name:`lifecycle / ci / monorepo-ci-build (${id})`,run_id:Number(owner.run),run_attempt:Number(owner.attempt),status:'completed',conclusion:'success',...change.job};
  const located=invoke(inputAction,'locate',{env:{COMPONENT:id,CARRIED:String(carried),CALLER_MODE:ownerContext['caller-mode'],RUN_ID:origin.outputs['run-id'],RUN_ATTEMPT:origin.outputs['run-attempt'],BASELINE_MANIFEST:baselineManifest},api:[{method:'rest.actions.listJobsForWorkflowRunAttempt',result:{data:{jobs:[job]}}},{method:'rest.actions.listWorkflowRunArtifacts',result:{data:{artifacts:change.artifacts||[owner.artifact,...(carried?[originalPlan.artifact]:[])]}}}]});
  if(located.error)return located;
  if(carried){passed(endorsement(originalPlan,originalMarker));originalFile=passed(data(originalPlan,'BuildPlan')).record;}
  const payload=data(owner,'ComponentResult',originalFile);if(payload.error)return payload;
  if(change.records){const rows=JSON.parse(payload.outputs.records);change.records(rows);payload.outputs.records=JSON.stringify(rows);}
  const result=invoke(inputAction,'result',{env:{PLAN:downloadedPlan,ORIGINAL_PLAN:originalFile,ORIGINAL_SOURCE:ownerContext['source-sha'],RECORDS:payload.outputs.records,OWNER_RUN_ID:origin.outputs['run-id'],OWNER_RUN_ATTEMPT:origin.outputs['run-attempt'],ARTIFACT_ID:located.outputs['component-id'],ARCHIVE_DIGEST:located.outputs['component-digest'],COMPONENT:id,CARRIED:String(carried),BASELINE_MANIFEST:baselineManifest,...change.result}});
  return {...result,owner,originalFile,currentFile:downloadedPlan,baselineFile:baseline.file};
 }
 return {root,env,invoke,passed,resolve,oldGo,originalPlan,currentNode,current,baseline,original,save,endorsement,originalMarker,configuration};
}
for(const id of ['node','go'])test(`pre-stage actual plan receipt→${id==='go'?'transitive original carry':'selected current'}→native verified payloads`,t=>{
 const f=fixture(t),r=f.resolve(id);f.passed(r);
 const routing=JSON.parse(r.outputs.records);assert.equal(routing.length,1);assert.equal(routing[0].artifactId,id==='go'?'700':'702');assert.equal(routing[0].artifactName,id==='go'?'components-450-1-go':'components-456-2-node');
 const result=JSON.parse(fs.readFileSync(r.outputs.result));assert.equal(r.outputs['source-sha'],id==='go'?f.original.head:f.current.head);assert.equal(r.outputs.version,id==='go'?'1.2.3':'1.2.5');
 assert.equal(result.mainArtifact.sourceSha,r.outputs['source-sha']);assert.equal(result.previewArtifact.builtVersion,r.outputs.version);
 assert.equal(hash(fs.readFileSync(path.join(r.outputs.directory,result.mainArtifact.location.path))),identities.zip.digest.slice(7));
 if(id==='go'){assert.notEqual(f.original.head,f.baseline.head);assert.notEqual(r.originalFile,r.baselineFile);assert.equal(result.mainArtifact.location.path.includes('/1.2.3/'),true);}
});
for(const [name,change]of [
 ['missing baseline',{route:{BASELINE_ARTIFACT_ID:''}}],['wrong baseline source',{origin:{BASELINE_SOURCE:'e'.repeat(40)}}],
 ['wrong original job',{job:{name:'Monorepo delivery slice / build (go)'}}],['wrong attempt',{job:{run_attempt:2}}],
 ['missing original plan',{artifacts:'missing-plan'}],['expired original plan',{artifacts:'expired'}],['swapped component',{artifacts:'swapped'}],
 ['duplicate result',{records:rows=>rows.push(rows[0])}],['wrong original source',{result:{ORIGINAL_SOURCE:'e'.repeat(40)}}],
])test(`pre-stage denies ${name} before result outputs`,t=>{
 const f=fixture(t);let mutation=change;
 if(change.artifacts==='missing-plan')mutation={artifacts:[f.oldGo.artifact]};
 if(change.artifacts==='expired')mutation={artifacts:[f.oldGo.artifact,{...f.originalPlan.artifact,expired:true}]};
 if(change.artifacts==='swapped')mutation={artifacts:[{...f.oldGo.artifact,id:799},f.originalPlan.artifact]};
 const r=f.resolve('go',mutation),expected={'missing baseline':'inputs-baseline-required','wrong baseline source':'inputs-baseline-source','wrong original job':'inputs-build-job','wrong attempt':'inputs-build-job','missing original plan':'inputs-artifact-identity','expired original plan':'inputs-artifact-identity','swapped component':'inputs-carry-artifact','duplicate result':'inputs-original-source','wrong original source':'inputs-original-source'}[name];
 assert.equal(r.error?.message,expected,JSON.stringify(r));assert.deepEqual(r.outputs,{});t.diagnostic(JSON.stringify({boundary:name,error:r.error.message,last:r.calls.at(-1)?.method||r.calls.at(-1)?.kind||'local validation',mutationCalls:r.calls.filter(c=>/create|update|delete|dispatch/.test(c.method||'')).length}));
});
test('pre-stage rejects swapped current policy even with current membership',t=>{
 const f=fixture(t),configuration=JSON.parse(fs.readFileSync(f.configuration));configuration.components[0].preview.healthPath='/changed';
 const r=f.resolve('node',{route:{CONFIGURATION:f.save('swapped-config',configuration)}});assert.equal(r.error?.message,'inputs-current-membership');assert.deepEqual(r.outputs,{});
});
test('normal original plan receipt rejects diagnostic job and duplicate marker',t=>{
 const f=fixture(t);
 for(const [marker,job]of [[f.originalMarker,{name:'Monorepo delivery slice / plan'}],[f.originalMarker+'\n'+f.originalMarker,{}]]){
  const r=f.endorsement(f.originalPlan,marker,false,{job});assert.equal(r.error?.message,job.name?'planner-job-identity':'planner-marker-count');assert.deepEqual(r.outputs,{});t.diagnostic(JSON.stringify({boundary:'original planner',error:r.error.message,last:r.calls.at(-1)?.method}));
 }
});
for(const [name,mutate]of [
 ['artifact name',rows=>rows[0].artifactName='components-456-1-node'],
 ['owner run',rows=>rows[0].runId='450'],
 ['archive digest',rows=>rows[0].archiveDigest='sha256:'+'e'.repeat(64)],
])test(`selected download denies contradictory verified ${name}`,t=>{const f=fixture(t),r=f.resolve('node',{records:mutate});assert.equal(r.error?.message,'inputs-verified-routing',JSON.stringify(r));assert.deepEqual(r.outputs,{});t.diagnostic(JSON.stringify({boundary:name,error:r.error.message,last:r.calls.at(-1)?.method||'local validation'}));});
