// LOCAL metadata/native-leaf evidence, not writer authority or production activation.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {root,runStep} from './action_test_support.mjs';
const binary=process.env.TRONADOR_CLI;
assert.ok(binary&&fs.existsSync(binary),'TRONADOR_CLI must name the actual newly built CLI; no silent skip');
function fixture(t,flag=false,rootFlag=flag){
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
 context.providerIdentity='123456789012';context.backend.authRef='aws-state';context.backendIdentity={provider:'aws',accountId:'123456789012'};context.authRefs=['aws-prod','aws-state'];context.origin.moduleRevision=row.revision;context.origin.providerLockDigest=row.providerLockDigest;
 const generated=JSON.parse(command(binary,['components','operations','plan','--operation','apply','--environment','prod','--target','prod-run','--component','api','--json'],context));
 const handle=generated.stateHandle;
 const privateFile=(name,record)=>{const file=path.join(work,name);fs.writeFileSync(file,JSON.stringify(record),{mode:0o600});return file;};
 const file=privateFile('handle.json',handle),bindings=Object.fromEntries(['aws-state','aws-prod'].map(name=>[name,{provider:'aws',roleArn:`arn:aws:iam::123456789012:role/${name}`,region:'us-east-1'}]));
 const backend={...handle.backend};delete backend.key;delete backend.prefix;
 const marker=privateFile('marker.json',{receiptId:'900',repositoryId:handle.origin.repository.id,runId:handle.origin.runId,runAttempt:handle.origin.runAttempt,sourceContext:{sourceSha:handle.origin.sourceSha},sourceStage:{},stateHandleDigest:generated.stateHandleDigest,workflowRef:'retained',workflowSha:handle.origin.blueprintSha,resourceClaims:['arn:aws:lambda:us-east-1:123456789012:function:example','object:arn:aws:s3:::external-packages/components/'+'1'.repeat(64)+'/main.zip']});
 // Fixture-only marker data: these tests prove metadata prerequisites, not writer authority.
 return {work,env,handle,file,marker,privateFile,generated,backend,bindings,module};
}
for(const [name,flag,rootFlag,accepted]of [['false pair',false,false,true],['real blocked pair',true,true,false],['mismatch',false,true,false],['string false','false','false',false]])test(`actual CLI metadata guard ${accepted?'permits only prerequisite':'denies'} ${name} before cloud auth`,t=>{
 const f=fixture(t,flag,rootFlag),r=runStep('cd/monorepo/recovery/backend/action.yml','select',{realCli:binary,env:{...f.env,STATE_HANDLE:f.file,RESERVATION_MARKER:f.marker,DEPLOYMENT_STATE_CONF:`s3:\n  bucket: ${f.backend.bucket}\n  region: ${f.backend.region}\n  workspace: default\n  use_lockfile: true\n  auth_ref: aws-state\n`,AUTH_BINDINGS:JSON.stringify(f.bindings),OPERATION:'unlock',LOCK_ID:'exact-native-lock'}});
 if(accepted){assert.equal(r.error,undefined,JSON.stringify(r));assert.ok(r.outputs.selection);}else{assert.ok(r.error,JSON.stringify(r));assert.deepEqual(r.outputs,{});}
 assert.equal(r.calls.some(c=>c.command!=='tronador'||c.kind==='api'),false);assert.equal(r.calls.some(c=>c.args?.includes('render')||c.args?.includes('artifacts')),false);
 if(name==='real blocked pair'){const checked=JSON.parse(r.calls[1].result.stdout);assert.equal(checked.valid,true);assert.equal(checked.module.activationBlocked,true);assert.equal(r.error.message,'recovery-module-blocked');}
});
for(const blocked of [false,true])test(`actual CLI direct execute guard ${blocked?'denies real standing block':'passes false fixture without renderer/artifacts/source'}`,t=>{
 const f=fixture(t,blocked),checked=spawnSync(binary,['components','contracts','validate','--kind','StateHandle'],{input:JSON.stringify(f.handle),env:f.env,encoding:'utf8'});assert.equal(checked.status,0,checked.stderr);const digest=JSON.parse(checked.stdout).digest;
 const selection={handle:f.handle,digest,operation:'unlock',lockId:'exact-native-lock'},proof={selection:f.privateFile('selection.json',selection),workloadContext:'/not-read-by-data-guard',backendContext:'/not-read-by-data-guard',handleDigest:digest,operation:'unlock',lockId:'exact-native-lock'};
 const r=runStep('cd/monorepo/recovery/execute/action.yml','plan',{realCli:binary,context:{repo:{owner:'example',repo:'mixed-app'}},env:{...f.env,STATE_HANDLE:f.file,PROOF:f.privateFile('proof.json',proof),OPERATION:'unlock',LOCK_ID:'exact-native-lock',CONFIRMATION:`unlock ${f.handle.protectedEnvironment}/${f.handle.targetId}/${f.handle.componentId} exact-native-lock`,HISTORICAL_CONTEXT:'',SOURCE_SHA:f.handle.origin.sourceSha,BLUEPRINT_SHA:f.handle.origin.blueprintSha,GITHUB_RUN_ID:'456',GITHUB_RUN_ATTEMPT:'2'},api:[{method:'rest.actions.getWorkflowRunAttempt',result:{data:{id:456,run_attempt:2,repository:{id:12345},head_sha:f.handle.origin.sourceSha,triggering_actor:{login:'operator'}}}}]});
 if(blocked){assert.equal(r.error?.message,'recovery-module-blocked',JSON.stringify(r));assert.deepEqual(r.outputs,{});}else{assert.equal(r.error,undefined,JSON.stringify(r));assert.ok(r.outputs['operation-plan']);}
 assert.equal(r.calls.some(c=>c.command==='aws'||c.command==='terragrunt'||c.args?.includes?.('render')||c.args?.includes?.('artifacts')),false);
});
