// Actual YAML final readers in real child processes; finite metadata, native immutable typed CLI.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {runStep} from './action_test_support.mjs';
const cli=process.env.TRONADOR_CLI;
assert.ok(cli&&fs.existsSync(cli),'immutable CLI required, no silent skip');
const successor=process.env.SCANNER19_ATTEMPT2==='1';
const actions=successor?{diagnostic:'../.omx/evidence/scanner19-attempt2-endorsement.yml',normal:'../.omx/evidence/scanner19-attempt2-scans.yml'}:{diagnostic:'ci/scan/trivy/endorsement/action.yml',normal:'ci/monorepo/stage/scans/action.yml'};
const digest='sha256:'+'a'.repeat(64),source='b'.repeat(40);
function fixture(t,mode,count=1){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'scanner19-readers-')));
 t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const privateDirectory=prefix=>fs.mkdtempSync(path.join(root,prefix));
 const write=(file,value)=>{fs.writeFileSync(file,JSON.stringify(value),{mode:0o600});return file;};
 const expectedDirectory=privateDirectory(mode==='normal'?'barrier-expected-':'scan-coverage-');
 const verifiedDirectory=privateDirectory('artifact-verified-'),expected=[],records=[];
 const configuration=write(path.join(root,'configuration.json'),{scanners:{sonarqubeEnabled:false,sonarqubeQualityGateEnabled:false,sonarqubeFailOnQualityGate:false,snykEnabled:false,semgrepEnabled:false,trivyEnabled:false,dependencyTrackEnabled:false}});
 const plan=write(path.join(root,'plan.json'),{headSha:source});
 for(let i=0;i<count;i++){
  const component='api'+(i||''),id=String(800+i),data=privateDirectory('artifact-data-'),directory=path.join(data,'extracted');fs.mkdirSync(directory,{mode:0o700});
  const value={apiVersion:'cloudopsworks.io/operations/v1',kind:'ScannerResult',scanner:'trivy',profile:mode==='normal'?'go':'diagnostic',componentId:component,sourceSha:source,status:mode==='normal'?'disabled':'passed',required:mode!=='normal',artifactDigest:digest,correlationId:'test-'+component,errorCode:null};
  const recordPath=write(path.join(directory,'scanner-result.json'),value),typed=spawnSync(cli,['components','contracts','validate','--kind','ScannerResult'],{input:JSON.stringify(value),encoding:'utf8'});assert.equal(typed.status,0,typed.stderr);
  const name=`monorepo-scan-456-2-${component}-${mode==='normal'?'trivy':'main'}`;
  records.push({runId:'456',artifactId:id,archiveDigest:digest,artifactName:name,archive:path.join(data,'archive.zip'),transport:path.join(data,'transport.json'),extract:directory,directory,files:['scanner-result.json'],recordPath});
  expected.push(mode==='normal'?{key:'trivy',artifactId:id,artifactName:name,archiveDigest:digest,digest:JSON.parse(typed.stdout).digest,componentId:component,sourceSha:source,artifactDigest:digest,profile:'go'}:{component,purpose:'main',digest,name});
 }
 const env={RUNNER_TEMP:root,RUN_ID:'456',RUN_ATTEMPT:'2',PLAN_PATH:plan,CONFIGURATION:configuration,EXPECTED:path.join(expectedDirectory,'expected.json'),...(mode==='normal'?{RECORDS_FILE:path.join(verifiedDirectory,'records.json')}:{VERIFIED_RECORDS_FILE:path.join(verifiedDirectory,'records.json'),PREVIEW_RECORDS_FILE:''})};
 const save=()=>{write(env.EXPECTED,expected);write(env.RECORDS_FILE||env.VERIFIED_RECORDS_FILE,records);};
 const run=()=>runStep(actions[mode],mode==='normal'?'normal-coverage':'coverage',{realCli:cli,env});
 save();return{root,mode,records,expected,env,save,run,write};
}
for(const mode of ['diagnostic','normal']){
 test(`actual ${mode} final reader accepts valid private typed data`,t=>{const f=fixture(t,mode),r=f.run();assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs.coverage,mode==='normal'?'passed-current-policy':'passed-oci-only');assert.equal(r.calls.filter(c=>c.kind==='exec').length,1);});
 test(`actual ${mode} final reader rejects wrong run before native validation`,t=>{const f=fixture(t,mode);f.records[0].runId='455';f.save();const r=f.run();assert.equal(r.error?.message,'scan-record-run');assert.deepEqual(r.outputs,{});assert.deepEqual(r.calls,[]);});
 for(const [label,change] of [['unknown field',e=>e.arbitrary=true],['missing field',e=>delete e.digest],['wrong digest type',e=>e.digest=17],['array digest',e=>e.digest=[digest]],['array component',e=>e[mode==='normal'?'componentId':'component']=['api']],['wrong name attempt',e=>e[mode==='normal'?'artifactName':'name']=e[mode==='normal'?'artifactName':'name'].replace('-456-2-','-456-1-')],['invalid component',e=>e[mode==='normal'?'componentId':'component']='../outside']])test(`actual ${mode} expected metadata rejects ${label} at intended reader`,t=>{
  const f=fixture(t,mode);change(f.expected[0]);f.save();const r=f.run();assert.equal(r.error?.message,mode==='normal'?'barrier-expected':'coverage-expected');assert.deepEqual(r.outputs,{});assert.deepEqual(r.calls,[]);
 });
 test(`actual ${mode} expected metadata rejects duplicate identity before any CLI`,t=>{const f=fixture(t,mode,2);f.expected[1]={...f.expected[0]};f.save();const r=f.run();assert.equal(r.error?.message,mode==='normal'?'barrier-expected':'coverage-expected');assert.deepEqual(r.outputs,{});assert.deepEqual(r.calls,[]);});
 test(`actual ${mode} rejects symlink record file without following it`,t=>{const f=fixture(t,mode),record=f.records[0].recordPath,target=path.join(f.root,'substituted.json');fs.renameSync(record,target);fs.symlinkSync(target,record);const r=f.run();assert.equal(r.error?.message,'scan-file-path');assert.deepEqual(r.outputs,{});assert.deepEqual(r.calls,[]);});
 test(`actual ${mode} rejects nonprivate final metadata at intended reader`,t=>{const f=fixture(t,mode);fs.chmodSync(f.env.RECORDS_FILE||f.env.VERIFIED_RECORDS_FILE,0o644);const r=f.run();assert.equal(r.error?.message,'scan-file-path');assert.deepEqual(r.outputs,{});assert.deepEqual(r.calls,[]);});
 test(`actual ${mode} late typed source mismatch withholds all coverage output`,t=>{
  const f=fixture(t,mode,2),value=JSON.parse(fs.readFileSync(f.records[1].recordPath));value.sourceSha='c'.repeat(40);f.write(f.records[1].recordPath,value);
  if(mode==='normal'){const typed=spawnSync(cli,['components','contracts','validate','--kind','ScannerResult'],{input:JSON.stringify(value),encoding:'utf8'});assert.equal(typed.status,0,typed.stderr);f.expected[1].digest=JSON.parse(typed.stdout).digest;f.save();}
  const r=f.run();assert.equal(r.error?.message,mode==='normal'?'barrier-result-mismatch':'coverage-result-mismatch');assert.deepEqual(r.outputs,{});assert.equal(r.calls.filter(c=>c.kind==='exec').length,2);assert.equal(r.logs.some(l=>l.kind==='summary'),false);
 });
}

for(const duplicate of [false,true])test(`actual diagnostic main/preview descriptor IDs ${duplicate?'reject duplicates before native validation':'remain distinct and pass native coverage'}`,t=>{
 const f=fixture(t,'diagnostic',2);
 f.expected[1].purpose='preview';f.expected[1].name=f.expected[1].name.replace(/-main$/,'-preview');f.records[1].artifactName=f.expected[1].name;
 if(duplicate)f.records[1].artifactId=f.records[0].artifactId;
 f.save();const r=f.run();
 if(duplicate){assert.equal(r.error?.message,'coverage-record-identity');assert.deepEqual(r.outputs,{});assert.deepEqual(r.calls,[]);assert.equal(r.logs.some(l=>l.kind==='summary'),false);}
 else{assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs.coverage,'passed-oci-only');assert.equal(r.calls.filter(c=>c.kind==='exec').length,2);}
});

test('actual diagnostic rejects a nonarray per-facade collection before flattening',t=>{
 const f=fixture(t,'diagnostic',0);f.write(f.env.VERIFIED_RECORDS_FILE,'');const r=f.run();
 assert.equal(r.error?.message,'coverage-record-set');assert.deepEqual(r.outputs,{});assert.deepEqual(r.calls,[]);assert.equal(r.logs.some(l=>l.kind==='summary'),false);
});

for(const bucket of ['VERIFIED_RECORDS_FILE','PREVIEW_RECORDS_FILE']){
 for(const [label,value]of [['empty string',''],['nonempty string','bad'],['object',{}],['null',null],['number',1],['boolean',false],['513 entries',Array(513).fill({})]])test(`actual diagnostic ${bucket} rejects ${label} before collection flattening`,t=>{
  const f=fixture(t,'diagnostic',0);const file=f.env.VERIFIED_RECORDS_FILE;f.env.VERIFIED_RECORDS_FILE='';f.env.PREVIEW_RECORDS_FILE='';f.env[bucket]=file;f.write(file,value);const r=f.run();
  assert.equal(r.error?.message,'coverage-record-set');assert.deepEqual(r.outputs,{});assert.deepEqual(r.calls,[]);assert.equal(r.logs.some(l=>l.kind==='summary'),false);
 });
 test(`actual diagnostic legitimate empty ${bucket} retains unsupported-profile`,t=>{const f=fixture(t,'diagnostic',0),file=f.env.VERIFIED_RECORDS_FILE;f.env.VERIFIED_RECORDS_FILE='';f.env.PREVIEW_RECORDS_FILE='';f.env[bucket]=file;const r=f.run();assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs.coverage,'unsupported-profile');assert.deepEqual(r.calls,[]);});
}
test('actual diagnostic absent buckets retain unsupported-profile',t=>{const f=fixture(t,'diagnostic',0);f.env.VERIFIED_RECORDS_FILE='';f.env.PREVIEW_RECORDS_FILE='';const r=f.run();assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs.coverage,'unsupported-profile');assert.deepEqual(r.calls,[]);});
