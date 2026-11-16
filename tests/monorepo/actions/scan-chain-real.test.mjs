import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import os from 'node:os';import path from 'node:path';import {createHash} from 'node:crypto';import {spawnSync} from 'node:child_process';import {runStep,root as blueprintRoot} from './action_test_support.mjs';
const cli=process.env.TRONADOR_CLI;assert.ok(cli&&fs.existsSync(cli),'actual CLI required');
const fixture=new URL('../../../../tronador-cli-v511/internal/components/testdata/',import.meta.url);
const read=p=>JSON.parse(fs.readFileSync(new URL(p,fixture)));
function run(action,id,options){const r=runStep(action,id,{realCli:cli,...options});return r;}
function zip(root,record){const archive=path.join(root,'scanner.zip');const r=spawnSync('python3',['-c','import zipfile,sys\nwith zipfile.ZipFile(sys.argv[1],"w") as z:z.writestr("scanner-result.json",sys.stdin.read())',archive],{input:JSON.stringify(record),encoding:'utf8'});assert.equal(r.status,0,r.stderr);return fs.readFileSync(archive);}
for(const mutation of ['none','digest','source','status','purpose','attempt','missing-preview'])test(`actual scan writers→two fixed transports→typed purpose coverage ${mutation}`,t=>{
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'real-scan-chain-')));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const plan=read('contracts/valid/build-plan.json'),component=read('contracts/valid/component-result.json');component.previewArtifact.digest='sha256:'+'2'.repeat(64);
 const save=(name,data)=>{const p=path.join(root,name);fs.writeFileSync(p,JSON.stringify(data));return p;};
 const planPath=save('plan.json',plan),resultPath=save('result.json',component),config=save('config.json',{scanners:{trivyEnabled:true}});
 const common={HOME:root,RUNNER_TEMP:root,GITHUB_REPOSITORY_ID:plan.repository.id,GITHUB_RUN_ID:'456',GITHUB_RUN_ATTEMPT:'2',RUN_ID:'456',RUN_ATTEMPT:'2'},items=[],markers=[];
 for(const [index,purpose] of ['main','preview'].entries()){
  const record=read('operations/scanner-result.json');Object.assign(record,{scanner:'trivy',profile:'diagnostic',componentId:'api',sourceSha:plan.headSha,required:true,status:'passed',artifactDigest:component[purpose+'Artifact'].digest});
  if(purpose==='preview'){if(mutation==='digest')record.artifactDigest='sha256:'+'f'.repeat(64);if(mutation==='source')record.sourceSha='f'.repeat(40);if(mutation==='status')record.status='required-gate-failure';}
  const recordPath=save(purpose+'.json',record),bytes=zip(root,record),digest='sha256:'+createHash('sha256').update(bytes).digest('hex'),id=String(789+index),name=`monorepo-scan-456-2-api-${purpose}`;
  const artifact={id:Number(id),name,digest,expired:false,size_in_bytes:bytes.length,workflow_run:{id:456,head_sha:plan.headSha}};
  const emitted=run('ci/scan/trivy/endorsement/action.yml','emit',{env:{...common,COMPUTED_RESULT:recordPath,RETRIEVED_RESULT:recordPath,ARTIFACT_ID:id,ARCHIVE_DIGEST:digest,COMPONENT:'api',ARTIFACT_PURPOSE:purpose},api:[{method:'rest.actions.getArtifact',result:{data:artifact}}]});
  assert.equal(emitted.error,undefined,JSON.stringify(emitted));markers.push(emitted.logs.find(l=>l.kind==='info').message);items.push({record,bytes,digest,id,name,artifact});
 }
 if(mutation==='purpose')markers[1]=markers[1].replace('-preview','-main');
 const locate=run('ci/scan/trivy/endorsement/action.yml','locate',{env:{...common,PLAN_PATH:planPath,CONFIGURATION:config,VERIFIED_RECORDS:JSON.stringify([{recordPath:resultPath}])},api:[
 {method:'rest.actions.getWorkflowRunAttempt',result:{data:{id:456,run_attempt:mutation==='attempt'?1:2,repository:{id:12345}}}},
 {method:'rest.actions.listJobsForWorkflowRunAttempt',result:{data:{jobs:[{id:900,name:'Monorepo delivery slice / scan (api)',run_id:456,run_attempt:2,status:'completed',conclusion:'success'}]}}},
 {method:'rest.actions.listWorkflowRunArtifacts',result:{data:{artifacts:items.map(i=>i.artifact)}}},
 {method:'request:GET /repos/{owner}/{repo}/actions/jobs/{job_id}/logs',result:{status:302,headers:{location:'https://scan.invalid/log'}}}],fetches:[{url:'https://scan.invalid/log',body:markers.join('\n')}]});
 if(['attempt','purpose'].includes(mutation)){assert.ok(locate.error,JSON.stringify(locate));assert.deepEqual(locate.outputs,{});return;}
 assert.equal(locate.error,undefined,JSON.stringify(locate));const records=[];
 // Each purpose follows the actual transport/facade phases independently, matching the two fixed production uses.
 for(const [index,purpose] of ['main','preview'].entries()){
  const item=items[index],route={...common,ARTIFACT_SET_FILE:locate.outputs[purpose+'-artifacts'],MODE:'scanner-file'};
  const resolved=run('ci/monorepo/artifact/transport/action.yml','resolve',{env:route});assert.equal(resolved.error,undefined,JSON.stringify(resolved));
  const download=run('ci/monorepo/artifact/transport/action.yml','retrieve',{env:{...route,RESOLVED_FILE:resolved.outputs['resolved-file']},api:[
   {method:'rest.repos.get',result:{data:{id:12345}}},{method:'rest.actions.getWorkflowRun',result:{data:{id:456,repository:{id:12345},head_sha:plan.headSha}}},
   {method:'rest.actions.getArtifact',result:{data:item.artifact}},{method:'request:GET /repos/{owner}/{repo}/actions/artifacts/{artifact_id}/zip',result:{status:302,headers:{location:'https://scan.invalid/'+purpose}}}],fetches:[{url:'https://scan.invalid/'+purpose,base64:item.bytes.toString('base64')}]});
  assert.equal(download.error,undefined,JSON.stringify(download));
  const typed=run('ci/monorepo/artifact/action.yml','records',{env:{...common,BUNDLES_FILE:download.outputs['bundles-file'],RECORD_KIND:'ScannerResult',FILE_MODE:'true'}});assert.equal(typed.error,undefined,JSON.stringify(typed));
  const payload=run('ci/monorepo/artifact/action.yml','payloads',{env:{...common,VERIFIED_RECORDS_FILE:typed.outputs['verified-records-file'],FILE_MODE:'true'}});assert.equal(payload.error,undefined,JSON.stringify(payload));records.push(payload.outputs['records-file']);
 }
 const coverage=run('ci/scan/trivy/endorsement/action.yml','coverage',{env:{...common,PLAN_PATH:planPath,EXPECTED:locate.outputs.expected,VERIFIED_RECORDS_FILE:records[0],PREVIEW_RECORDS_FILE:mutation==='missing-preview'?'':records[1]}});
 if(mutation==='none'){assert.equal(coverage.error,undefined,JSON.stringify(coverage));assert.equal(coverage.outputs.coverage,'passed-oci-only');}else{assert.ok(coverage.error,JSON.stringify(coverage));assert.deepEqual(coverage.outputs,{});}
});
test('no OCI evidence does not authorize a nonimage main/public gate',t=>{const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'no-image-coverage-')));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));const p=path.join(root,'plan.json');fs.writeFileSync(p,JSON.stringify(read('contracts/valid/build-plan.json')));const dir=fs.mkdtempSync(path.join(root,'scan-coverage-')),expected=path.join(dir,'expected.json');fs.writeFileSync(expected,'[]',{mode:0o600});const r=run('ci/scan/trivy/endorsement/action.yml','coverage',{env:{RUNNER_TEMP:root,RUN_ID:'456',RUN_ATTEMPT:'2',PLAN_PATH:p,EXPECTED:expected,VERIFIED_RECORDS_FILE:'',PREVIEW_RECORDS_FILE:''}});assert.equal(r.error,undefined);assert.equal(r.outputs.coverage,'unsupported-profile');assert.ok(r.logs.some(l=>l.kind==='summary'&&JSON.stringify(l).includes('no nonimage or public main')));});
test('diagnostic coverage retains exactly two fixed existing artifact verifier calls',()=>{const parsed=spawnSync('yq',['-o=json','-I=0','.',path.join(blueprintRoot,'ci/scan/trivy/endorsement/action.yml')],{encoding:'utf8'});assert.equal(parsed.status,0,parsed.stderr);const action=JSON.parse(parsed.stdout),calls=action.runs.steps.filter(s=>s.uses==='./bp/ci/monorepo/artifact'&&s.if?.startsWith("inputs.mode == 'verify-diagnostic'"));assert.deepEqual(calls.map(s=>s.id),['diagnostic-main','diagnostic-preview']);for(const step of calls)assert.equal(step.with['record-kind'],'ScannerResult');assert.equal(calls[0].with['artifact-set-file'],'${{ steps.locate.outputs.main-artifacts }}');assert.equal(calls[1].with['artifact-set-file'],'${{ steps.locate.outputs.preview-artifacts }}');});
