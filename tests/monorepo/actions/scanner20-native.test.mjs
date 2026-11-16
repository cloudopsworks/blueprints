// LOCAL fixed production-YAML/native-CLI chains. Finite GitHub/storage doubles, not hosted authority.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {runStep,root as blueprintRoot} from './action_test_support.mjs';
const cli=process.env.TRONADOR_CLI;
assert.ok(cli&&fs.existsSync(cli),'immutable CLI required; no silent skip');
const scanner='ci/scan/trivy/endorsement/action.yml',barrier='ci/monorepo/stage/scans/action.yml';
const facade='ci/monorepo/artifact/action.yml',transport='ci/monorepo/artifact/transport/action.yml';
const fixtures=new URL('../../../../tronador-cli-v511/internal/components/testdata/contracts/valid/',import.meta.url);
const read=name=>JSON.parse(fs.readFileSync(new URL(name+'.json',fixtures)));
const sha=bytes=>'sha256:'+createHash('sha256').update(bytes).digest('hex');
function setup(t,long=false){
 const temporary=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'scanner20-native-')));
 t.after(()=>fs.rmSync(temporary,{recursive:true,force:true}));
 const root=long?path.join(temporary,'long-'+ 'x'.repeat(120),'y'.repeat(120),'z'.repeat(120)):temporary;
 fs.mkdirSync(root,{recursive:true,mode:0o700});
 const save=(name,value)=>{const file=path.join(root,name);fs.writeFileSync(file,JSON.stringify(value),{mode:0o600});return file;};
 const env={HOME:root,RUNNER_TEMP:root,GITHUB_REPOSITORY_ID:'12345',GITHUB_RUN_ID:'456',GITHUB_RUN_ATTEMPT:'2',RUN_ID:'456',RUN_ATTEMPT:'2'};
 return {root,save,env};
}
function zipped(f,record,id){
 const source=path.join(f.root,'zip-source');fs.mkdirSync(source,{recursive:true,mode:0o700});
 const file=path.join(source,'scanner-result.json');fs.writeFileSync(file,JSON.stringify(record),{mode:0o600});
 const archive=path.join(f.root,`fixture-${id}.zip`),r=spawnSync('zip',['-q','-X',archive,'scanner-result.json'],{cwd:source});
 assert.equal(r.status,0,r.stderr?.toString());const bytes=fs.readFileSync(archive);
 return {bytes,digest:sha(bytes),recordPath:f.save('record-'+id+'.json',record)};
}
function fixedFacade(env,ingress,items){
 const route=runStep(facade,'route',{env:{...env,RECORD_KIND:'ScannerResult',ARTIFACT_SET_FILE:ingress}});
 assert.equal(route.error,undefined,JSON.stringify(route));
 const transportEnv={...env,MODE:route.outputs.mode,ARTIFACT_SET_FILE:ingress};
 const resolved=runStep(transport,'resolve',{env:transportEnv});assert.equal(resolved.error,undefined,JSON.stringify(resolved));
 const api=[],fetches=[];
 for(const item of items){
  api.push({method:'rest.repos.get',result:{data:{id:12345}}},
   {method:'rest.actions.getWorkflowRun',result:{data:{id:456,repository:{id:12345},head_sha:'a'.repeat(40)}}},
   {method:'rest.actions.getArtifact',result:{data:item.artifact}},
   {method:'request:GET /repos/{owner}/{repo}/actions/artifacts/{artifact_id}/zip',result:{status:302,headers:{location:'https://scanner20.invalid/archive/'+item.id}}});
  fetches.push({url:'https://scanner20.invalid/archive/'+item.id,base64:item.bytes.toString('base64')});
 }
 const retrieved=runStep(transport,'retrieve',{realCli:cli,env:{...transportEnv,RESOLVED_FILE:resolved.outputs['resolved-file']},api,fetches,timeout:180000});
 assert.equal(retrieved.error,undefined,JSON.stringify(retrieved));assert.equal(retrieved.calls.filter(c=>c.kind==='exec').length,items.length);
 const typedEnv={...env,FILE_MODE:route.outputs['file-mode'],RECORD_KIND:'ScannerResult',BUNDLES_FILE:retrieved.outputs['bundles-file']};
 const typed=runStep(facade,'records',{realCli:cli,env:typedEnv,timeout:180000});
 assert.equal(typed.error,undefined,JSON.stringify(typed));assert.equal(typed.calls.length,items.length);
 const payloads=runStep(facade,'payloads',{realCli:cli,env:{...env,FILE_MODE:route.outputs['file-mode'],VERIFIED_RECORDS_FILE:typed.outputs['verified-records-file']},timeout:180000});
 assert.equal(payloads.error,undefined,JSON.stringify(payloads));
 for(const result of [route,resolved,retrieved,typed,payloads]){
  assert.deepEqual(result.unused,{api:0,tools:0,fetches:0});
  for(const value of Object.values(result.outputs))assert.ok(Buffer.byteLength(value)<=4096);
 }
 return {route,resolved,retrieved,typed,payloads,typedEnv};
}
function scannerRecord(component,source,profile,scanner,status,artifactDigest){
 return {apiVersion:'cloudopsworks.io/operations/v1',kind:'ScannerResult',scanner,profile,componentId:component,sourceSha:source,status,required:profile==='diagnostic',artifactDigest,correlationId:'native-'+component,errorCode:null};
}
for(const purposes of [[],['main'],['preview'],['main','preview']])test(purposes.join()==='main'?'actual diagnostic main-only native rejection preserves mandatory preview':`actual diagnostic reachable ${purposes.join('+')||'zero'} follows nonempty fixed facade buckets`,t=>{
 const f=setup(t),plan=read('build-plan'),component=read('component-result');
 if(purposes.join()==='main')component.previewArtifact=null;
 if(purposes.join()==='preview'){
  plan.components[0].package={kind:'archive',format:'zip',include:['dist']};plan.components[0].targetIds=[];plan.targets=[];
  plan.components[0].preview={mode:'container',source:'dockerfile',dockerfile:'Dockerfile.preview',context:'.',port:8080,healthPath:'/health'};
  component.mainArtifact.kind='archive';component.mainArtifact.format='zip';
 }
 const planPath=f.save('plan.json',plan),resultPath=f.save('component.json',component),configuration=f.save('configuration.json',{scanners:{trivyEnabled:purposes.length>0}}),items=[],markers=[];
 for(const [index,purpose]of purposes.entries()){
  const record=scannerRecord('api',plan.headSha,'diagnostic','trivy','passed',component[purpose+'Artifact'].digest),id=String(800+index),bundle=zipped(f,record,id),name=`monorepo-scan-456-2-api-${purpose}`;
  const artifact={id:Number(id),name,digest:bundle.digest,expired:false,size_in_bytes:bundle.bytes.length,workflow_run:{id:456,head_sha:plan.headSha}};
  const emitted=runStep(scanner,'emit',{realCli:cli,env:{...f.env,COMPUTED_RESULT:bundle.recordPath,RETRIEVED_RESULT:bundle.recordPath,ARTIFACT_ID:id,ARCHIVE_DIGEST:bundle.digest,COMPONENT:'api',ARTIFACT_PURPOSE:purpose},api:[{method:'rest.actions.getArtifact',result:{data:artifact}}]});
  assert.equal(emitted.error,undefined,JSON.stringify(emitted));markers.push(emitted.logs.find(l=>l.kind==='info').message);items.push({id,...bundle,artifact,purpose});
 }
 const jobs=purposes.length?[{id:900,name:'Monorepo delivery slice / scan (api)',run_id:456,run_attempt:2,status:'completed',conclusion:'success'}]:[];
 const api=[{method:'rest.actions.getWorkflowRunAttempt',result:{data:{id:456,run_attempt:2,repository:{id:12345}}}},{method:'rest.actions.listJobsForWorkflowRunAttempt',result:{data:{jobs}}},{method:'rest.actions.listWorkflowRunArtifacts',result:{data:{artifacts:items.map(i=>i.artifact)}}}];
 if(purposes.length)api.push({method:'request:GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs',result:{status:302,headers:{location:'https://scanner20.invalid/diagnostic'}}});
 const located=runStep(scanner,'locate',{realCli:cli,env:{...f.env,PLAN_PATH:planPath,CONFIGURATION:configuration,VERIFIED_RECORDS:JSON.stringify([{recordPath:resultPath}])},api,fetches:purposes.length?[{url:'https://scanner20.invalid/diagnostic',body:markers.join('\n')}]:[]});
 if(purposes.join()==='main'){assert.equal(located.error?.message,'coverage-component');assert.match(located.calls.at(-1).result.stderr,/preview-artifact-required/);assert.deepEqual(located.outputs,{});return;}
 assert.equal(located.error,undefined,JSON.stringify(located));let facadeCount=0;const paths={};
 for(const purpose of ['main','preview'])if(located.outputs[purpose+'-artifacts']){facadeCount++;const chain=fixedFacade(f.env,located.outputs[purpose+'-artifacts'],items.filter(i=>i.purpose===purpose));paths[purpose]=chain.payloads.outputs['records-file'];}
 assert.equal(facadeCount,purposes.length);
 const covered=runStep(scanner,'coverage',{realCli:cli,env:{...f.env,PLAN_PATH:planPath,EXPECTED:located.outputs.expected,VERIFIED_RECORDS_FILE:paths.main||'',PREVIEW_RECORDS_FILE:paths.preview||''}});
 assert.equal(covered.error,undefined,JSON.stringify(covered));assert.equal(covered.outputs.coverage,purposes.length?'passed-oci-only':'unsupported-profile');
 assert.equal(covered.calls.length,purposes.length);assert.equal([...located.logs,...covered.logs].some(l=>l.message?.startsWith('CLOUDOPSWORKS_STAGE_V1 ')),false);
 assert.notEqual(covered.outputs.coverage,'passed-current-policy');
});

const parsed=spawnSync('yq',['-o=json','.',path.join(blueprintRoot,'.github/workflows/monorepo-scan.yml')],{encoding:'utf8'});
assert.equal(parsed.status,0,parsed.stderr);const receiptScript=JSON.parse(parsed.stdout).jobs.component.steps.find(s=>s.id==='receipt').with.script;
function receipt(env){
 const worker=new URL('./script_worker.mjs',import.meta.url),r=spawnSync(process.execPath,[worker.pathname],{input:JSON.stringify({script:receiptScript,realCli:cli,env}),encoding:'utf8',env:{PATH:process.env.PATH,...env},timeout:180000,maxBuffer:8388608});
 assert.equal(r.status,0,JSON.stringify({error:r.error?.message,signal:r.signal,stderr:r.stderr}));const result=JSON.parse(r.stdout);assert.equal(result.error,undefined,JSON.stringify(result));return result.logs.find(l=>l.message?.startsWith('CLOUDOPSWORKS_SCAN_V1 ')).message;
}
test('actual256component seven-purpose1792 native archives reach final normal coverage; late failures withhold completion',t=>{
 const f=setup(t,true),plan=read('build-plan'),template=structuredClone(plan.components[0]),componentTemplate=read('component-result');
 plan.components=Array.from({length:256},(_,i)=>{const c=structuredClone(template);c.id='component-'+i;c.path='components/'+c.id;c.targetIds=[];for(const tc of c.toolchains)tc.components=[c.id];return c;});plan.targets=[];
 plan.buildSelection=plan.components.map(c=>({componentId:c.id,reasons:['component-path-changed']}));plan.matrix.include=plan.components.map(c=>({componentId:c.id,closure:[c.id],toolchains:c.toolchains}));
 const planPath=f.save('current-plan.json',plan),sourceConfiguration=f.save('source-configuration.json',{scanners:{snykEnabled:false,semgrepEnabled:false,sonarqubeEnabled:false,sonarqubeQualityGateEnabled:false,sonarqubeFailOnQualityGate:false,trivyEnabled:true,dependencyTrackEnabled:false}});
 const common={...f.env,ORIGIN_RUN_ID:'450',ORIGIN_RUN_ATTEMPT:'1',HOST_ORIGIN_RUN_ID:'450',HOST_ORIGIN_RUN_ATTEMPT:'1',CALLER_MODE:'normal-main',HOST_CALLER_MODE:'normal-main',HOST_SOURCE_SHA:plan.headSha,PLAN_ARTIFACT_ID:'700',PLAN_ARCHIVE_DIGEST:'sha256:'+'7'.repeat(64)};
 const projection=runStep(barrier,'policy',{env:{...common,CONFIGURATION:sourceConfiguration,POLICY_CONFIGURATION:sourceConfiguration}});assert.equal(projection.error,undefined,JSON.stringify(projection));
 const items=[],messages=[],jobs=[];let nextId=1000;
 for(const [index,c]of plan.components.entries()){
  const component=structuredClone(componentTemplate);component.componentId=c.id;
  const resultPath=f.save(c.id+'-result.json',component),scans=[],computed={};
  for(const key of ['snyk','semgrep','sonarqube','dependency-track','trivy','oci-main','oci-preview']){
   const scanner=key.startsWith('oci-')?'trivy':key==='sonarqube'?'sonar':key,record=scannerRecord(c.id,plan.headSha,'go',scanner,scanner==='trivy'?'passed':'disabled',component.mainArtifact.digest);record.required=false;
   const id=String(nextId++),bundle=zipped(f,record,id),name=`monorepo-scan-456-2-${c.id}-${key}`,artifact={id:Number(id),name,digest:bundle.digest,expired:false,size_in_bytes:bundle.bytes.length,workflow_run:{id:456,head_sha:plan.headSha}};
   items.push({id,...bundle,artifact});scans.push({artifactId:id,artifactName:name,archiveDigest:bundle.digest,recordPath:bundle.recordPath});computed['COMPUTED_'+key.replaceAll('-','_').toUpperCase()]=bundle.recordPath;
  }
  messages.push(receipt({...common,...computed,CURRENT_PLAN:planPath,ORIGINAL_PLAN:planPath,COMPONENT_RESULT:resultPath,CONFIGURATION:projection.outputs.configuration,POLICY_DIGESTS:projection.outputs['policy-digests'],COMPONENT:c.id,OWNER_RECORDS:JSON.stringify([{runId:'450',artifactId:String(9000+index),artifactName:`components-450-1-${c.id}`,archiveDigest:'sha256:'+'8'.repeat(64)}]),SCAN_RECORDS:JSON.stringify(scans)}));
  jobs.push({id:900+index,name:`delivery / scan / monorepo-scan-component (${c.id})`,run_id:456,run_attempt:2,status:'completed',conclusion:'success'});
 }
 const api=[{method:'rest.actions.getWorkflowRunAttempt',result:{data:{id:456,run_attempt:2,event:'workflow_run',repository:{id:12345}}}}];
 for(let offset=0;offset<jobs.length;offset+=100)api.push({method:'rest.actions.listJobsForWorkflowRunAttempt',result:{data:{jobs:jobs.slice(offset,offset+100)}}});
 for(const job of jobs)api.push({method:'request:GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs',result:{status:302,headers:{location:'https://scanner20.invalid/worker/'+job.id}}});
 const located=runStep(barrier,'normal-locate',{realCli:cli,env:{...common,PLAN_PATH:planPath,CONFIGURATION:sourceConfiguration,EFFECTIVE_CONFIGURATION:projection.outputs.configuration,POLICY_DIGEST:projection.outputs['policy-digest'],POLICY_DIGESTS:projection.outputs['policy-digests']},api,fetches:messages.map((body,i)=>({url:'https://scanner20.invalid/worker/'+jobs[i].id,body})),timeout:180000});
 assert.equal(located.error,undefined,JSON.stringify(located));assert.equal(JSON.parse(fs.readFileSync(located.outputs.expected)).length,1792);
 const chain=fixedFacade(f.env,located.outputs['artifacts-file'],items),recordsFile=chain.payloads.outputs['records-file'],records=JSON.parse(fs.readFileSync(recordsFile));
 assert.equal(records.length,1792);assert.ok(fs.statSync(recordsFile).size>131072);assert.ok(f.root.length>400);
 const coverageEnv={...f.env,CONFIGURATION:projection.outputs.configuration,EXPECTED:located.outputs.expected,RECORDS_FILE:recordsFile};
 const covered=runStep(barrier,'normal-coverage',{realCli:cli,env:coverageEnv,timeout:180000});assert.equal(covered.error,undefined,JSON.stringify(covered));assert.equal(covered.calls.length,1792);assert.equal(covered.outputs.coverage,'passed-current-policy');
 const last=records.at(-1),original=fs.readFileSync(last.recordPath),value=JSON.parse(original);value.status='fabricated-success';fs.writeFileSync(last.recordPath,JSON.stringify(value));
 const badTyped=runStep(facade,'records',{realCli:cli,env:chain.typedEnv,timeout:180000});assert.equal(badTyped.error?.message,'artifact-record-contract',JSON.stringify(badTyped));assert.equal(badTyped.calls.length,1792);assert.notEqual(badTyped.calls.at(-1).result.exitCode,0);assert.deepEqual(badTyped.outputs,{});
 value.status='passed';value.sourceSha='f'.repeat(40);fs.writeFileSync(last.recordPath,JSON.stringify(value));
 // Update only final expected typed digest to isolate the independent source comparison, not an earlier digest failure.
 const native=spawnSync(cli,['components','contracts','validate','--kind','ScannerResult'],{input:JSON.stringify(value),encoding:'utf8'});assert.equal(native.status,0,native.stderr);
 const expected=JSON.parse(fs.readFileSync(located.outputs.expected));expected.at(-1).digest=JSON.parse(native.stdout).digest;fs.writeFileSync(located.outputs.expected,JSON.stringify(expected));
 const late=runStep(barrier,'normal-coverage',{realCli:cli,env:coverageEnv,timeout:180000});assert.equal(late.error?.message,'barrier-result-mismatch',JSON.stringify(late));assert.equal(late.calls.length,1792);assert.deepEqual(late.outputs,{});assert.equal(late.logs.some(l=>l.kind==='summary'),false);
 for(const result of [located,covered,late])for(const output of Object.values(result.outputs))assert.ok(Buffer.byteLength(output)<=4096);
});
