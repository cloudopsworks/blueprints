// LOCAL test-only platform copy: production flags and historical origins are never changed.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {root,runStep} from './action_test_support.mjs';
export const binary=process.env.TRONADOR_CLI;
assert.ok(binary&&fs.existsSync(binary),'TRONADOR_CLI must name actual fresh-origin CLI');
export function fixture(t,flag=false,rootFlag=flag){
 const work=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'catalog-recovery-real-')));t.after(()=>fs.rmSync(work,{recursive:true,force:true}));
 const env={PATH:process.env.PATH,HOME:work,RUNNER_TEMP:work,GITHUB_WORKSPACE:work,GITHUB_REPOSITORY_ID:'12345',GITHUB_REPOSITORY:'example/mixed-app'};
 const command=(exe,args,input)=>{const r=spawnSync(exe,args,{input:typeof input==='string'?input:JSON.stringify(input),env,encoding:'utf8',timeout:30000,maxBuffer:8*1024*1024});assert.equal(r.status,0,r.stderr);return r.stdout;};
 const catalog=JSON.parse(command('yq',['-o=json','-I=0','.',path.join(root,'terraform/monorepo/module-catalog.yaml')]));
 const row=catalog.modules['aws-lambda'],module=path.join(work,'bp',row.path);fs.mkdirSync(module,{recursive:true,mode:0o700});
 for(const name of row.files){fs.mkdirSync(path.dirname(path.join(module,name)),{recursive:true,mode:0o700});fs.copyFileSync(path.join(root,row.path,name),path.join(module,name));}
 const metadata=JSON.parse(command('yq',['-o=json','-I=0','.',path.join(module,'inputs.yaml')]));metadata.activationBlocked=rootFlag;
 fs.writeFileSync(path.join(module,'inputs.yaml'),command('yq',['-p=json','-o=yaml','.'],metadata));
 row.activationBlocked=flag;
 // Rebinding is confined to an explicit test-only copy. Production/historical bytes never change.
 const hash=createHash('sha256');for(const name of [...row.files].sort())hash.update(name+'\0').update(fs.readFileSync(path.join(module,name))).update('\0');row.revision='sha256:'+hash.digest('hex');
 fs.writeFileSync(path.join(work,'bp/terraform/monorepo/module-catalog.yaml'),command('yq',['-p=json','-o=yaml','.'],catalog));
 const context=JSON.parse(fs.readFileSync(path.join(root,'../tronador-cli-v511/internal/components/testdata/operations/operation-context-frozen.json')));
 const component=context.plan.components[0];component.package={kind:'function',provider:'aws',mode:'aws-zip',runtime:'provided.al2023',entryPoint:'bootstrap',architecture:'amd64',source:'.'};component.workload={kind:'function'};
 component.preview={mode:'container',source:'function',dockerfile:'Dockerfile',context:'.',adapter:'aws-lambda-rie',entryPoint:'bootstrap',port:8080,healthPath:'/health',invokePath:'/invoke',invokeTest:{requestBody:'{}',expectedStatus:200,responseContains:'ok'}};
 context.plan.targets=[{id:'prod-run',environment:'prod',provider:'aws',authRef:'aws-prod',ownership:'managed',configDigest:'sha256:'+'2'.repeat(64),kind:'aws.lambda',region:'us-east-1',functionName:'example',packageMode:'zip',alias:null,runtime:'provided.al2023',iac:{roleArn:'arn:aws:iam::123456789012:role/example',sourceBucket:'external-packages'},readiness:{deadlineSeconds:300,intervalSeconds:5,probe:{kind:'lambda-invoke',requestBody:'{}',responseContains:'ok'}}}];
 context.providerIdentity='123456789012';context.backend.authRef='aws-state';context.backendIdentity={provider:'aws',accountId:'123456789012'};context.authRefs=['aws-prod','aws-state'];delete context.origin.moduleRevision;delete context.origin.providerLockDigest;
 const generated=JSON.parse(command(binary,['components','operations','plan','--module-root',module,'--operation','apply','--environment','prod','--target','prod-run','--component','api','--json'],context));
 const handle=generated.stateHandle;
 const privateFile=(name,record)=>{const file=path.join(work,name);fs.writeFileSync(file,JSON.stringify(record),{mode:0o600});return file;};
 const file=privateFile('handle.json',handle),bindings=Object.fromEntries(['aws-state','aws-prod'].map(name=>[name,{provider:'aws',roleArn:`arn:aws:iam::123456789012:role/${name}`,region:'us-east-1'}]));
 const backend={...handle.backend};delete backend.key;delete backend.prefix;
 return {work,env,handle,file,privateFile,generated,backend,bindings,module,context,command};
}

const preflight='cd/monorepo/native/preflight/action.yml',writer='cd/monorepo/native/reservation/action.yml',history='cd/monorepo/recovery/history/action.yml';
const canonical=v=>JSON.stringify(v===null||typeof v!=='object'?v:Array.isArray(v)?v.map(x=>JSON.parse(canonical(x))):Object.fromEntries(Object.keys(v).sort().map(k=>[k,JSON.parse(canonical(v[k]))])));
const digest=v=>'sha256:'+createHash('sha256').update(canonical(v)).digest('hex');
const api=(method,data,args)=>({method,args,result:{data}});

export function product(t,options={}){
 const f=fixture(t),repo={owner:'example',repo:'mixed-app'};
 f.env={...f.env,GITHUB_RUN_ID:'100',GITHUB_RUN_ATTEMPT:'1'};f.repo=repo;
 const config=JSON.parse(f.command('yq',['-o=json','-I=0','.',path.join(root,'tests/monorepo/fixtures/composite_first/mixed/.cloudopsworks/cloudopsworks-ci.yaml')]));
 config.components={api:{...config.components.go,targets:['prod-run']}};config.components.api.path='components/api';
 config.cd={targets:{},deployments:{release:{env:'prod',enabled:true}}};
 const policy=path.join(f.work,'policy');fs.mkdirSync(path.join(policy,'.cloudopsworks/vars'),{recursive:true});
 fs.writeFileSync(path.join(policy,'.cloudopsworks/cloudopsworks-ci.yaml'),f.command('yq',['-p=json','-o=yaml','.'],config));
 const target={...f.context.plan.targets[0]};delete target.id;delete target.configDigest;delete target.environment;
 fs.writeFileSync(path.join(policy,'.cloudopsworks/vars/inputs-prod.yaml'),f.command('yq',['-p=json','-o=yaml','.'],{monorepo:{targets:{'prod-run':target}}}));
 const normalized=JSON.parse(f.command(binary,['components','validate','--config-only','--workdir',policy,'--json'])).resolved;
 const plan={...f.context.plan,components:normalized.components,targets:normalized.targets,previewPolicy:normalized.previewPolicy};
 plan.matrix.include=[{componentId:'api',closure:['api'],toolchains:plan.components[0].toolchains}];
 const manifest=JSON.parse(fs.readFileSync(path.join(root,'../tronador-cli-v511/internal/components/testdata/contracts/valid/actions-staged-manifest.json')));
 manifest.package=undefined;manifest.components[0].package=plan.components[0].package;manifest.components[0].workload=plan.components[0].workload;
 manifest.components[0].mainArtifact={...manifest.components[0].mainArtifact,kind:'function',format:'zip'};manifest.targets=plan.targets;
 const stage={repositoryId:'12345',runId:'100',runAttempt:'1',artifactId:'700',artifactName:'monorepo-stage-100-1',archiveDigest:'sha256:'+'7'.repeat(64)};
 const host={id:100,run_attempt:1,repository:{id:12345},event:'workflow_dispatch',head_branch:'main',head_sha:plan.headSha,path:'.github/workflows/composite-first-slice.yml',triggering_actor:{login:'operator'},referenced_workflows:['monorepo-delivery-slice.yml','monorepo-native-reservation.yml'].map(name=>({path:'cloudopsworks/blueprints/.github/workflows/'+name+'@v5.11.0',sha:f.handle.origin.blueprintSha}))};
 if(options.closure){plan.prNumber=7;host.event='pull_request_target';host.path='.github/workflows/composite-first-closure.yml';host.head_sha='e'.repeat(40);}
 f.host=host;f.plan=plan;f.manifest=manifest;f.stage=stage;f.normalized=normalized;
 f.prepare=()=>runStep(preflight,'prepare',{realCli:binary,context:{repo},env:{...f.env,MODE:'data',PLAN:f.privateFile('plan.json',plan),MANIFEST:f.privateFile('manifest.json',manifest),STAGE:JSON.stringify(stage),CONFIGURATION:f.privateFile('configuration.json',normalized),POLICY_DIRECTORY:policy,SOURCE_SHA:plan.headSha,BLUEPRINT_SHA:f.handle.origin.blueprintSha,PROJECTED_SOURCE:f.projectedSource || '',HOST_REF:'refs/heads/main',BASE_REF:options.closure?'support/1.0':'',PR_NUMBER:options.closure?'7':'',AUTH_BINDINGS:JSON.stringify(f.bindings),IDENTITIES:JSON.stringify({'aws-state':'123456789012','aws-prod':'123456789012'}),DEPLOYMENT_STATE_CONF:'s3:\n  bucket: state-example\n  region: us-east-1\n  use_lockfile: true\n  auth_ref: aws-state\n'},api:[api('rest.actions.getWorkflowRunAttempt',host)]});
 const planFile=f.privateFile('stage-plan.json',plan),manifestFile=f.privateFile('stage-manifest.json',manifest);
 const endorsement=runStep('ci/monorepo/stage/endorsement/action.yml','emit',{realCli:binary,context:{repo},env:{...f.env,COMPUTED_PLAN:planFile,RETRIEVED_PLAN:planFile,COMPUTED_MANIFEST:manifestFile,RETRIEVED_MANIFEST:manifestFile,ARTIFACT_ID:stage.artifactId,ARCHIVE_DIGEST:stage.archiveDigest,RUN_ID:'100',RUN_ATTEMPT:'1'},api:[api('rest.actions.getArtifact',{id:700,name:stage.artifactName,digest:stage.archiveDigest,expired:false,workflow_run:{id:100}})]});
 assert.equal(endorsement.error,undefined,JSON.stringify(endorsement));f.stageLog=endorsement.logs.find(l=>l.message?.startsWith('CLOUDOPSWORKS_STAGE_V1 ')).message;
 if(options.closure){
  const projection=runStep('ci/monorepo/stage/source-context/action.yml','project',{realCli:binary,context:{repo},env:{...f.env,PLAN_PATH:planFile,CLOSURE:'true',HOST_REF:'refs/heads/main',BASE_REF:'support/1.0',SOURCE_SHA:plan.headSha,PR_NUMBER:'7'},api:[api('rest.git.getRef',{object:{type:'commit',sha:plan.headSha}})]});
  assert.equal(projection.error,undefined,JSON.stringify(projection));f.projectedSource=projection.outputs['source-context'];
 }
 return f;
}

export function prove(f,change={}){
 const prepared=f.prepare();assert.equal(prepared.error,undefined,JSON.stringify(prepared));
 const p=JSON.parse(fs.readFileSync(prepared.outputs.prepared));
 const credentials=Object.fromEntries(['BACKEND','WORKLOAD'].flatMap(prefix=>['ACCESS_KEY','SECRET_KEY','SESSION_TOKEN'].map(key=>[prefix+'_'+key,prefix+'-'+key])));
 const outputs=[{Account:'123456789012',Arn:'arn:aws:sts::123456789012:assumed-role/aws-state/session'},{Account:'123456789012',Arn:'arn:aws:sts::123456789012:assumed-role/aws-prod/session'},change.state||{IsTruncated:false,KeyCount:0},{Role:{Arn:'arn:aws:iam::123456789012:role/example'}},{LocationConstraint:null},change.object||{IsTruncated:false,KeyCount:0},change.functions||{Functions:[]}];
 const r=runStep(preflight,'prove',{env:{...f.env,PREPARED:prepared.outputs.prepared,...credentials},tools:[{command:'aws',args:['--version'],result:{stdout:'aws-cli/2.40.1 test'}},...outputs.map(output=>({command:'aws',result:{stdout:JSON.stringify(output)}}))]});
 return {r,p,prepared};
}

export function reserve(f,change={}){
 const proof=prove(f);assert.equal(proof.r.error,undefined,JSON.stringify(proof.r));
 const p=proof.p,h=p.operation.stateHandle;
 const payload={apiVersion:'cloudopsworks.io/operations/v1',kind:'StateHandleReservation',stateHandle:h,stateHandleDigest:p.operation.stateHandleDigest,resourceClaims:p.preflight.resourceClaims};
 const receipt={id:900,creator:{id:41898282},ref:h.origin.sourceSha,task:'cloudopsworks-state',environment:'cloudopsworks-state/'+digest(h.native).slice(7),payload};
 const job={id:801,run_id:100,run_attempt:1,name:'Monorepo delivery slice / native-reservation / preflight',status:'completed',conclusion:'success',...change.job};
 const log=proof.r.logs.find(x=>x.message?.startsWith('CLOUDOPSWORKS_PREFLIGHT_V1 ')).message;
 const r=runStep(writer,'reserve',{realCli:binary,context:{repo:f.repo},env:{...f.env,PREPARED:proof.prepared.outputs.prepared},api:[api('rest.actions.getWorkflowRunAttempt',f.host),api('rest.actions.listJobsForWorkflowRunAttempt',{jobs:[job]}),{method:'request:GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs',result:{status:302,headers:{location:'https://logs.example/preflight'}}},api('rest.repos.listDeployments',typeof change.entries==='function'?change.entries(receipt):change.entries||[]),api('rest.repos.createDeployment',receipt),api('rest.repos.getDeployment',{...receipt,...change.readback}),api('rest.repos.listDeployments',[receipt])],fetches:[{body:typeof change.log==='function'?change.log(log):change.log??log}]});
 return {...proof,r,receipt,log};
}

export function historical(f,produced,change={}){
 assert.equal(produced.r.error,undefined,JSON.stringify(produced.r));
 const created=produced.r.calls.find(c=>c.method==='rest.repos.createDeployment');
 const receipt={...produced.receipt,payload:created.args.payload}; // Captured actual request, never a fixture ownership marker.
 const located=runStep(history,'locate',{realCli:binary,context:{repo:f.repo},env:{...f.env,RECEIPT_ID:'900'},api:[api('rest.repos.getDeployment',receipt)]});assert.equal(located.error,undefined,JSON.stringify(located));
 const caller=fs.readFileSync(path.join(root,'../monorepo-app-template/.github/workflows/'+(f.host.event==='pull_request_target'?'composite-first-closure.yml':'composite-first-slice.yml')));
 const remote=bytes=>({type:'file',encoding:'base64',content:bytes.toString('base64'),sha:createHash('sha1').update(`blob ${bytes.length}\0`).update(bytes).digest('hex')});
 const pull={number:7,state:'closed',merged:true,merge_commit_sha:f.plan.headSha,base:{ref:'support/1.0',sha:'d'.repeat(40),repo:{id:12345}},head:{ref:'feature',sha:'f'.repeat(40),repo:{id:12345}},...change.pull};
 const host=runStep('cd/tasks/repo/context/action.yml','verify',{context:{repo:f.repo},env:{...f.env,CONTEXT_RUN_ID:'100',CONTEXT_RUN_ATTEMPT:'1'},api:[api('rest.repos.get',{id:12345,default_branch:'main'}),api('rest.actions.getWorkflowRunAttempt',f.host),api('rest.repos.getBranch',{protected:true,commit:{sha:f.host.head_sha}}),api('rest.repos.getContent',remote(caller)),api('rest.git.getRef',{object:{type:'commit',sha:f.handle.origin.blueprintSha}}),...(f.host.event==='pull_request_target'&&f.host.pull_requests?.length?[api('rest.pulls.get',pull)]:[])]});assert.equal(host.error,undefined,JSON.stringify(host));
 const definitions=['monorepo-delivery-slice.yml','monorepo-native-reservation.yml'].map(name=>{
   const relative='.github/workflows/'+name,bytes=fs.readFileSync(path.join(root,relative)),destination=path.join(f.work,'bp',relative);fs.mkdirSync(path.dirname(destination),{recursive:true});fs.writeFileSync(destination,bytes);return api('rest.repos.getContent',remote(bytes));
 });
 const stateLog=produced.r.logs.find(l=>l.message?.startsWith('CLOUDOPSWORKS_STATE_V1 ')).message;
 const stageLog=f.stageLog;
 const jobs=[{id:802,run_id:100,run_attempt:1,name:'Monorepo delivery slice / stage',status:'completed',conclusion:'success'},{id:803,run_id:100,run_attempt:1,name:'Monorepo delivery slice / native-reservation / reserve',status:'completed',conclusion:change.writerConclusion||'success',steps:[{name:'Reserve exact native state claims',status:'completed',conclusion:'success'}]}];
 if(change.jobs)change.jobs(jobs);
 const r=runStep(history,'verify',{context:{repo:f.repo},env:{...f.env,RECEIPT:located.outputs.receipt,BLUEPRINT_SHA:host.outputs['blueprint-sha'],SOURCE_SHA:host.outputs['source-sha']},api:[api('rest.actions.getWorkflowRunAttempt',{...f.host,...change.host}),...definitions,api('rest.actions.listJobsForWorkflowRunAttempt',{jobs}),...[802,803].map(id=>({method:'request:GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs',args:{job_id:id},result:{status:302,headers:{location:'https://logs.example/'+id}}})),...(f.host.event==='pull_request_target'?[api('rest.pulls.get',pull),api('rest.repos.getBranch',{protected:true,commit:{sha:f.plan.headSha}}),api('rest.repos.compareCommitsWithBasehead',{status:'identical',base_commit:{sha:f.plan.headSha},merge_base_commit:{sha:f.plan.headSha}}),api('rest.git.getRef',{object:{type:'commit',sha:change.tagSha||f.plan.headSha}})]:[])],fetches:[{body:change.stageLog??stageLog},{body:change.stateLog??stateLog}]});
 return {r,receipt,host,located,stateLog};
}
export function unlock(f,retained,change={}) {
 const handle=retained.receipt.payload.stateHandle,handleDigest=retained.receipt.payload.stateHandleDigest,lockId='native-lock';
 const calls=[],run=(action,id,options)=>{const r=runStep(action,id,options);calls.push(...r.calls);assert.equal(r.error,undefined,JSON.stringify(r));return r;};
 const selected=run('cd/monorepo/recovery/backend/action.yml','select',{realCli:binary,context:{repo:f.repo},env:{...f.env,STATE_HANDLE:retained.r.outputs['state-handle'],RESERVATION_MARKER:retained.r.outputs['reservation-marker'],DEPLOYMENT_STATE_CONF:'s3:\n  bucket: state-example\n  region: us-east-1\n  use_lockfile: true\n  auth_ref: aws-state\n',AUTH_BINDINGS:JSON.stringify(f.bindings),OPERATION:'unlock',LOCK_ID:lockId}});
 const credentials=Object.fromEntries(['BACKEND','WORKLOAD'].flatMap(prefix=>['ACCESS_KEY','SECRET_KEY','SESSION_TOKEN'].map(key=>[prefix+'_'+key,prefix+'-'+key])));
 const identities=['aws-state','aws-prod'].map(role=>({Account:'123456789012',Arn:'arn:aws:sts::123456789012:assumed-role/'+role+'/session'}));
 const captured=run('cd/monorepo/recovery/backend/action.yml','capture',{env:{...f.env,SELECTION:selected.outputs.selection,...credentials},tools:[{command:'aws',args:['--version'],result:{stdout:'aws-cli/2.40.1 test'}},...identities.map(identity=>({command:'aws',prefix:['sts','get-caller-identity'],result:{stdout:JSON.stringify(identity)}}))]});
 const arn='arn:aws:lambda:us-east-1:123456789012:function:example';
 const state={version:4,serial:1,lineage:'frozen',resources:[{mode:'managed',type:'aws_lambda_function',name:'component',instances:[{attributes:{arn,function_name:'example',tags:{'cloudopsworks-owner':handleDigest}}}]}]};
 const lock={ID:lockId,Path:handle.backend.bucket+'/'+handle.backend.key};
 const read=(previous='',mutate=false)=>{
   const bytes=JSON.stringify(state),lockBytes=JSON.stringify(lock),etag=mutate?'"changed-state"':'"native-state"';
   const read=run('cd/monorepo/recovery/backend/read/action.yml','state',{realCli:binary,env:{...f.env,SELECTION:selected.outputs.selection,WORKLOAD_CONTEXT:captured.outputs['workload-context'],BACKEND_CONTEXT:captured.outputs['backend-context']},tools:[{command:'aws',args:['--version'],result:{stdout:'aws-cli/2.40.1 test'}},...identities.map(identity=>({command:'aws',prefix:['sts','get-caller-identity'],result:{stdout:JSON.stringify(identity)}})),{command:'aws',prefix:['s3api','head-object'],result:{stdout:JSON.stringify({ContentLength:Buffer.byteLength(bytes),ETag:etag})}},{command:'aws',prefix:['s3api','get-object'],nativeFile:bytes,result:{stdout:JSON.stringify({ETag:etag})}},{command:'aws',prefix:['s3api','list-objects-v2'],result:{stdout:JSON.stringify({IsTruncated:false,Contents:[{Key:handle.backend.key+'.tflock'}]})}},{command:'aws',prefix:['s3api','head-object'],result:{stdout:JSON.stringify({ContentLength:Buffer.byteLength(lockBytes),ETag:'"native-lock"'})}},{command:'aws',prefix:['s3api','get-object'],nativeFile:lockBytes,result:{stdout:JSON.stringify({ETag:'"native-lock"'})}}]});
   const owned=run('cd/monorepo/recovery/backend/read/action.yml','ownership',{env:{...f.env,STATE_PROOF:read.outputs['state-proof']},tools:[{command:'aws',prefix:['lambda','get-function'],result:{stdout:JSON.stringify({Configuration:{FunctionArn:arn,FunctionName:'example'},Tags:{'cloudopsworks-owner':handleDigest}})}}]});
   const inspected=runStep('cd/monorepo/recovery/backend/read/action.yml','inspect',{env:{...f.env,OWNERSHIP_PROOF:owned.outputs['ownership-proof'],PREVIOUS_PROOF:previous}});calls.push(...inspected.calls);return inspected;
 };
 const baseline=read();assert.equal(baseline.error,undefined,JSON.stringify(baseline));
 const planned=run('cd/monorepo/recovery/execute/action.yml','plan',{realCli:binary,context:{repo:f.repo},env:{...f.env,GITHUB_RUN_ID:'456',GITHUB_RUN_ATTEMPT:'2',STATE_HANDLE:retained.r.outputs['state-handle'],RESERVATION_MARKER:retained.r.outputs['reservation-marker'],PROOF:baseline.outputs.proof,OPERATION:'unlock',LOCK_ID:lockId,CONFIRMATION:'unlock release/prod/prod-run/api '+lockId,HISTORICAL_CONTEXT:'',SOURCE_SHA:f.host.head_sha,BLUEPRINT_SHA:handle.origin.blueprintSha},api:[api('rest.actions.getWorkflowRunAttempt',{id:456,run_attempt:2,repository:{id:12345},head_sha:f.host.head_sha,triggering_actor:{login:'operator'}})]});
 const beforeInit=read(baseline.outputs.proof,change.beforeInit);if(beforeInit.error)return {calls,error:beforeInit.error};
 const init=run('cd/monorepo/recovery/execute/action.yml','unlock-init',{env:{...f.env,OPERATION_PLAN:planned.outputs['operation-plan'],DIRECTORY:planned.outputs.directory,BACKEND_CONTEXT:captured.outputs['backend-context'],WORKLOAD_CONTEXT:captured.outputs['workload-context']},tools:[{command:'tofu',args:['version','-json'],result:{stdout:'{"terraform_version":"1.11.4"}'}},{command:'terragrunt',args:['--version'],result:{stdout:'terragrunt version v0.99.4'}},{command:'terragrunt',args:['--non-interactive','--working-dir',path.join(planned.outputs.directory,'unlock'),'run','--','init','-input=false','-get=false']}]});
 const beforeUnlock=read(baseline.outputs.proof,change.beforeUnlock);if(beforeUnlock.error)return {calls,error:beforeUnlock.error};
 const released=run('cd/monorepo/recovery/execute/action.yml','unlock',{env:{...f.env,OPERATION_PLAN:planned.outputs['operation-plan'],ROOT:init.outputs.root,PROOF:beforeUnlock.outputs.proof,WORKLOAD_CONTEXT:captured.outputs['workload-context']},tools:[{command:'terragrunt',args:['--non-interactive','--working-dir',init.outputs.root,'run','--','force-unlock','-force',lockId]}]});
 return {calls,released};
}

export function ownership(t,change={}){
 const f=product(t),producer=reserve(f),retained=historical(f,producer);assert.equal(retained.r.error,undefined,JSON.stringify(retained.r));
 const markerFile=retained.r.outputs['reservation-marker'];
 const selected=runStep('cd/monorepo/recovery/backend/action.yml','select',{realCli:binary,context:{repo:f.repo},env:{...f.env,STATE_HANDLE:retained.r.outputs['state-handle'],RESERVATION_MARKER:markerFile,DEPLOYMENT_STATE_CONF:'s3:\n  bucket: state-example\n  region: us-east-1\n  use_lockfile: true\n  auth_ref: aws-state\n',AUTH_BINDINGS:JSON.stringify(f.bindings),OPERATION:'destroy',LOCK_ID:''}});assert.equal(selected.error,undefined,JSON.stringify(selected));
 const selection=JSON.parse(fs.readFileSync(selected.outputs.selection)),h=selection.handle,d=selection.digest;
 const bucket=change.bucket||h.resourceIdentity.iac.sourceBucket,key=change.key||producer.p.objectKey,version='v1';
 const arn='arn:aws:lambda:us-east-1:123456789012:function:example';
 const resources=[{mode:'managed',type:'aws_lambda_function',name:'component',instances:[{attributes:{arn,function_name:'example',s3_bucket:bucket,s3_key:key,s3_object_version:version,tags:{'cloudopsworks-owner':d}}}]},{mode:'managed',type:'aws_s3_object',name:'package',instances:[{index_key:0,attributes:{bucket,key,version_id:version,tags:{'cloudopsworks-owner':d}}}]}];
 const proof={selection:selected.outputs.selection,handleDigest:d,operation:'destroy',lockId:null,statePath:f.privateFile('owned-state.json',{version:4,resources}),workloadContext:f.privateFile('workload-read.json',{env:{PATH:process.env.PATH}})};
 const r=runStep('cd/monorepo/recovery/backend/read/action.yml','ownership',{env:{...f.env,STATE_PROOF:f.privateFile('state-proof.json',proof)},tools:[{command:'aws',prefix:['lambda','get-function'],result:{stdout:JSON.stringify({Configuration:{FunctionArn:arn,FunctionName:'example'},Tags:{'cloudopsworks-owner':d}})}},{command:'aws',prefix:['s3api','get-object-tagging'],result:{stdout:JSON.stringify({TagSet:[{Key:'cloudopsworks-owner',Value:d}]})}}]});
 return {f,r,selected,producer,retained,state:{version:4,resources}};
}

// Connected actual product bodies; fixed local native saved-plan output double, no provider execution.
export function destroyPreparation(t,change={}) {
 const frame=ownership(t),{f,producer,retained,selected,state}=frame;assert.equal(frame.r.error,undefined,JSON.stringify(frame.r));
 const calls=[],run=(action,id,options)=>{const r=runStep(action,id,options);calls.push(...r.calls);assert.equal(r.error,undefined,JSON.stringify(r));return r;};
 const action='cd/monorepo/recovery/execute/action.yml',reader='cd/monorepo/recovery/backend/read/action.yml';
 const credentials=Object.fromEntries(['BACKEND','WORKLOAD'].flatMap(prefix=>['ACCESS_KEY','SECRET_KEY','SESSION_TOKEN'].map(key=>[prefix+'_'+key,prefix+'-'+key])));
 const identities=['aws-state','aws-prod'].map(role=>({Account:'123456789012',Arn:'arn:aws:sts::123456789012:assumed-role/'+role+'/session'}));
 const captured=run('cd/monorepo/recovery/backend/action.yml','capture',{env:{...f.env,SELECTION:selected.outputs.selection,...credentials},tools:[{command:'aws',args:['--version'],result:{stdout:'aws-cli/2.40.1 test'}},...identities.map(identity=>({command:'aws',prefix:['sts','get-caller-identity'],result:{stdout:JSON.stringify(identity)}}))]});
 const bytes=JSON.stringify(state),digest=retained.receipt.payload.stateHandleDigest,handle=retained.receipt.payload.stateHandle;
 const read=run(reader,'state',{realCli:binary,env:{...f.env,SELECTION:selected.outputs.selection,WORKLOAD_CONTEXT:captured.outputs['workload-context'],BACKEND_CONTEXT:captured.outputs['backend-context']},tools:[{command:'aws',args:['--version'],result:{stdout:'aws-cli/2.40.1 test'}},...identities.map(identity=>({command:'aws',prefix:['sts','get-caller-identity'],result:{stdout:JSON.stringify(identity)}})),{command:'aws',prefix:['s3api','head-object'],result:{stdout:JSON.stringify({ContentLength:Buffer.byteLength(bytes),ETag:'"state"'})}},{command:'aws',prefix:['s3api','get-object'],nativeFile:bytes,result:{stdout:'{"ETag":"\\"state\\""}'}},{command:'aws',prefix:['s3api','list-objects-v2'],result:{stdout:'{"IsTruncated":false,"Contents":[]}'}}]});
 const owned=run(reader,'ownership',{env:{...f.env,STATE_PROOF:read.outputs['state-proof']},tools:[{command:'aws',prefix:['lambda','get-function'],result:{stdout:JSON.stringify({Configuration:{FunctionArn:state.resources[0].instances[0].attributes.arn,FunctionName:'example'},Tags:{'cloudopsworks-owner':digest}})}},{command:'aws',prefix:['s3api','get-object-tagging'],result:{stdout:JSON.stringify({TagSet:[{Key:'cloudopsworks-owner',Value:digest}]})}}]});
 const inspected=run(reader,'inspect',{env:{...f.env,OWNERSHIP_PROOF:owned.outputs['ownership-proof'],PREVIOUS_PROOF:''}});
 const historicalContext={...f.context,plan:f.plan,origin:handle.origin,historicalHandle:handle,releaseName:handle.releaseName,authRefs:handle.authRefs,prNumber:f.plan.prNumber};
 const config=f.privateFile('historical-context.json',historicalContext);
 const planned=run(action,'plan',{realCli:binary,context:{repo:f.repo},env:{...f.env,GITHUB_RUN_ID:'456',GITHUB_RUN_ATTEMPT:'2',STATE_HANDLE:retained.r.outputs['state-handle'],PROOF:inspected.outputs.proof,OPERATION:'destroy',LOCK_ID:'',CONFIRMATION:'destroy release/prod/prod-run/api',HISTORICAL_CONTEXT:config,SOURCE_SHA:f.host.head_sha,BLUEPRINT_SHA:handle.origin.blueprintSha},api:[api('rest.actions.getWorkflowRunAttempt',{id:456,run_attempt:2,repository:{id:12345},head_sha:f.host.head_sha,triggering_actor:{login:'operator'}})]});
 // Original stage/application payloads are absent; only retained validated config/native state remain.
 for(const name of ['policy','plan.json','manifest.json','stage-plan.json','stage-manifest.json'])fs.rmSync(path.join(f.work,name),{recursive:true,force:true});
 const rootPath=path.join(planned.outputs.directory,'destroy');
 const changes=state.resources.map(resource=>({address:resource.type+'.'+resource.name+(resource.type==='aws_s3_object'?'[0]':''),mode:'managed',type:resource.type,change:{actions:['delete'],before:structuredClone(resource.instances[0].attributes),after:null}}));
 if(change.before)change.before(changes);
 const native=args=>['--non-interactive','--working-dir',rootPath,'run','--',...args];
 const prepared=runStep(action,'destroy-prepare',{realCli:binary,env:{...f.env,OPERATION_PLAN:planned.outputs['operation-plan'],DIRECTORY:planned.outputs.directory,HISTORICAL_CONTEXT:config,PROOF:inspected.outputs.proof,BACKEND_CONTEXT:captured.outputs['backend-context'],WORKLOAD_CONTEXT:captured.outputs['workload-context']},tools:[{command:'tofu',args:['version','-json'],result:{stdout:'{"terraform_version":"1.11.4"}'}},{command:'terragrunt',args:['--version'],result:{stdout:'terragrunt version v0.99.4'}},{command:'terragrunt',args:native(['init','-input=false','-lockfile=readonly'])},{command:'terragrunt',args:native(['plan','-destroy','-input=false','-out=operation.tfplan']),nativeSavedPlan:Buffer.from('local native saved delete-only plan bytes').toString('base64')},{command:'terragrunt',args:native(['show','-json','operation.tfplan']),result:{stdout:JSON.stringify({resource_changes:changes})}}]});calls.push(...prepared.calls);
 return {...frame,prepared,calls,planned,inspected,changes,captured};
}
