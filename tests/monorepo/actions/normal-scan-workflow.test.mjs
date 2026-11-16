import test from 'node:test';import assert from'node:assert/strict';import fs from'node:fs';import path from'node:path';import{spawnSync}from'node:child_process';import{root}from'./action_test_support.mjs';
const filename=path.join(root,'.github/workflows/monorepo-scan.yml');
function workflow(){const r=spawnSync('yq',['-o=json','.',filename],{encoding:'utf8'});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout);}
test('shared scan workers cover all current components before the barrier and have no cloud grants',()=>{
 const w=workflow();assert.equal(w.jobs.component.name,'monorepo-scan-component (${{ matrix.componentId }})');assert.equal(w.jobs.required.name,'monorepo-scan-required');
 assert.deepEqual(w.jobs.required.needs,['prepare','component']);
 for(const job of Object.values(w.jobs)){assert.equal(job.permissions['id-token'],undefined);assert.equal(job.permissions.contents,'read');assert.equal(job.permissions.checks,undefined);}
 const steps=w.jobs.component.steps,uses=steps.map(s=>s.uses);for(const scanner of ['snyk','semgrep','sonarqube/component','trivy/source','dependency-track/component'])assert.ok(uses.includes('./bp/ci/scan/'+scanner));assert.ok(uses.includes('./bp/ci/dotnet/scan/sonarqube/component'));
 const checkout=steps.findIndex(s=>s.uses==='actions/checkout@v4'&&s.with.path==='source');for(const action of ['./bp/ci/monorepo/toolchains','./bp/ci/monorepo/scanners'])assert.ok(uses.indexOf(action)<checkout);
 assert.match(w.jobs.prepare.steps.find(s=>s.id==='matrix').with.script,/plan.components.map/);assert.doesNotMatch(w.jobs.prepare.steps.find(s=>s.id==='matrix').with.script,/buildSelection/);
 assert.equal(steps.find(s=>s.id==='inputs').uses,'./bp/ci/monorepo/stage/inputs');assert.match(steps.find(s=>s.id==='semgrep').with['source-ref'],/inputs.outputs.source-ref/);
 assert.doesNotMatch(fs.readFileSync(filename,'utf8'),/python|id-token:|contents: write|run:|SEMGREP_COMMIT|GITHUB_EVENT_NAME:/);
});

// Execute production workflow bodies with the same bounded harness as composite bodies.
const worker=new URL('./script_worker.mjs',import.meta.url);
function execute(id,options){const step=workflow().jobs.component.steps.find(s=>s.id===id);assert.equal(step.uses,'actions/github-script@v9');const r=spawnSync(process.execPath,[worker.pathname],{input:JSON.stringify({script:step.with.script,realCli:process.env.TRONADOR_CLI,...options}),encoding:'utf8',env:{PATH:process.env.PATH,...options.env},timeout:20000,maxBuffer:8388608});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout);}
import os from'node:os';
const contracts=new URL('../../../../tronador-cli-v511/internal/components/testdata/contracts/valid/',import.meta.url);
function resultFixture(t,scanners={},trusted='false'){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'scan-outcomes-17-')));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const save=(name,data)=>{const file=path.join(root,name);fs.writeFileSync(file,JSON.stringify(data));return file;};
 const plan=JSON.parse(fs.readFileSync(new URL('build-plan.json',contracts))),record=JSON.parse(fs.readFileSync(new URL('component-result.json',contracts)));
 const policy={sonarqubeEnabled:false,sonarqubeQualityGateEnabled:true,sonarqubeFailOnQualityGate:false,snykEnabled:false,semgrepEnabled:false,trivyEnabled:false,dependencyTrackEnabled:false,...scanners};
 const env={RUNNER_TEMP:root,PLAN:save('plan.json',plan),RESULT:save('result.json',record),CONFIGURATION:save('configuration.json',{scanners:policy}),COMPONENT:'api',TRUSTED_SOURCE:trusted};return{root,save,plan,record,policy,env};
}
test('actual workflow emits five typed disabled outcomes, never absent results',t=>{const f=resultFixture(t),r=execute('results',{env:f.env});assert.equal(r.error,undefined,JSON.stringify(r));assert.deepEqual(Object.keys(r.outputs).sort(),['dependency-track','semgrep','snyk','sonarqube','trivy']);for(const file of Object.values(r.outputs)){const record=JSON.parse(fs.readFileSync(file));assert.equal(record.status,'disabled');assert.equal(record.required,false);assert.equal(record.sourceSha,f.plan.headSha);assert.equal(record.artifactDigest,f.record.mainArtifact.digest);}});
test('actual untrusted required Sonar outcome is explicit and non-passed',t=>{const f=resultFixture(t,{sonarqubeEnabled:true,sonarqubeFailOnQualityGate:true}),r=execute('results',{env:f.env});assert.equal(r.error,undefined,JSON.stringify(r));const record=JSON.parse(fs.readFileSync(r.outputs.sonarqube));assert.equal(record.status,'unavailable-untrusted-context');assert.equal(record.required,true);});
test('missing enabled native scanner cannot be manufactured as clean',t=>{const f=resultFixture(t,{semgrepEnabled:true},'true'),r=execute('results',{env:f.env});assert.equal(r.error?.message,'scan-missing-outcome');assert.equal(r.outputs.semgrep,undefined);});
test('disabled scanner with an injected executable result is denied',t=>{const f=resultFixture(t),r=execute('results',{env:{...f.env,SNYK:'/untrusted/injected'}});assert.equal(r.error?.message,'scan-unexpected-execution');assert.deepEqual(r.outputs,{});});
