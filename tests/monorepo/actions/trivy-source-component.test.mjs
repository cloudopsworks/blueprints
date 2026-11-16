import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {root,runStep,loadStep} from './action_test_support.mjs';
const action='ci/scan/trivy/source/action.yml', native='ci/scan/trivy/native/action.yml';
const cli=process.env.TRONADOR_CLI || '/tmp/tronador-v511-python-prep';
const digest='sha256:'+'c'.repeat(64);
function yaml(file) { const r=spawnSync('yq',['-o=json','-I=0','.',path.join(root,file)],{encoding:'utf8'});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout); }
function fixture(t) {
  const temporary=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'trivy-source-')));
  t.after(()=>fs.rmSync(temporary,{recursive:true,force:true}));
  const workspace=path.join(temporary,'workspace'),source=path.join(workspace,'components/api');
  fs.mkdirSync(source,{recursive:true});fs.writeFileSync(path.join(source,'package-lock.json'),'{}');
  const relative='.cloudopsworks/out/api/main.zip';fs.mkdirSync(path.dirname(path.join(workspace,relative)),{recursive:true});fs.writeFileSync(path.join(workspace,relative),'payload');
  const plan={headSha:'a'.repeat(40),components:[{id:'api',path:'components/api',buildProfile:'npm'}],buildSelection:[{componentId:'api'}]};
  const result={componentId:'api',headSha:plan.headSha,status:'succeeded',mainArtifact:{digest,location:{kind:'local',path:relative}}};
  for(const file of ['plan.json','result.json'])fs.writeFileSync(path.join(temporary,file),'{}');
  const env={SOURCE_PATH:workspace,PLAN_PATH:path.join(temporary,'plan.json'),COMPONENT_RESULT:path.join(temporary,'result.json'),COMPONENT:'api',SOURCE_SHA:plan.headSha,RUNNER_TEMP:temporary};
  const tools=[{prefix:['components','contracts','validate','--kind','BuildPlan'],result:{stdout:JSON.stringify({record:plan})}},
    {prefix:['components','contracts','validate','--kind','ComponentResult'],result:{stdout:JSON.stringify({record:result})}},
    {prefix:['components','artifacts','verify'],result:{stdout:JSON.stringify({payloadVerified:true,digest})}},
    {command:'git',result:{stdout:plan.headSha+'\n'}}];
  return {temporary,workspace,source,plan,result,env,tools};
}
function prepare(f) { return runStep(action,'prepare',f); }
function report(f,p,content,outcome='success') {
  if(content!==undefined) fs.writeFileSync(p.outputs.report,typeof content==='string'?content:JSON.stringify(content),{mode:0o600});
  const r=runStep(action,'report',{env:{DIRECTORY:p.outputs.directory,TOOL_OUTCOME:outcome},realCli:cli});
  return {...r,record:r.calls.find(c=>c.command==='tronador')?.input && JSON.parse(r.calls.find(c=>c.command==='tronador').input)};
}
const clean=()=>({SchemaVersion:2,Trivy:{Version:'0.69.3'},ArtifactType:'filesystem',ArtifactName:'runner-hostname',Results:[{Target:'package-lock.json',Class:'lang-pkgs',Packages:[{Name:'dependency',Version:'1.2.3'}]}]});

test('source route adds explicit fs branch without changing default image body',()=>{
  const n=yaml(native),image=n.runs.steps.find(s=>s.uses==='aquasecurity/trivy-action@v0.36.0'&&s.with['scan-type']==='image');
  assert.equal(n.inputs['scan-type'].default,'image');assert.equal(n.inputs['image-input'].required,true);
  assert.deepEqual(image.with,{input:'${{ inputs.image-input }}','scan-type':'image',format:'json',output:'${{ inputs.output }}','skip-setup-trivy':true,'ignore-unfixed':true,severity:'CRITICAL,HIGH,MEDIUM','github-pat':'${{ inputs.token }}',scanners:'vuln','exit-code':'0'});
  const vendor=n.runs.steps.filter(s=>s.uses==='aquasecurity/trivy-action@v0.36.0');assert.equal(vendor.length,2);
  const fsStep=vendor.find(s=>s.with['scan-type']==='fs');assert.ok(fsStep);assert.equal(fsStep.with['scan-ref'],'${{ inputs.scan-ref }}');
  assert.equal(fsStep.with.input,undefined);assert.equal(fsStep.with['image-ref'],undefined);assert.equal(fsStep.with.scanners,'vuln,misconfig,secret');
  assert.equal(fsStep.with['list-all-pkgs'],true);assert.equal(fsStep.with.cache,false);assert.equal(fsStep.with['github-pat'],'');
  assert.equal(fsStep.with['skip-setup-trivy'],true);assert.equal(fsStep.env.TRIVY_CMD,'trivy');
  assert.equal(n.runs.steps.find(s=>s.uses==='aquasecurity/setup-trivy@v0.3.1').if,"inputs.scan-type == 'image'");
  const producer=yaml(action).runs.steps.find(s=>s.id==='scan');assert.equal(producer.uses,'./bp/ci/scan/trivy/native');assert.equal(producer.with['scan-type'],'fs');
  assert.equal(yaml(action).inputs.token,undefined);assert.equal(yaml(action).inputs.required,undefined);
});

test('prepare binds selected-current typed result, payload, real head and component directory',t=>{
  const f=fixture(t),p=prepare(f);assert.equal(p.error,undefined,JSON.stringify(p));assert.equal(p.outputs.source,f.source);
  const calls=p.calls.filter(c=>c.kind==='exec');assert.deepEqual(calls.map(c=>c.command),['tronador','tronador','tronador','git']);
  assert.equal(fs.statSync(p.outputs.directory).mode&0o777,0o700);
  const r=report(f,p,clean());assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs.status,'passed');
  assert.equal(r.record.required,false);assert.equal(r.record.scanner,'trivy');assert.equal(r.record.profile,'npm');assert.equal(r.record.artifactDigest,digest);
  assert.match(r.record.correlationId,/^scan-[a-f0-9]{32}$/);assert.equal(fs.statSync(r.outputs.result).mode&0o777,0o600);
});
for(const [field,finding] of [['Vulnerabilities',{VulnerabilityID:'CVE-example',Severity:'HIGH'}],['Misconfigurations',{ID:'AVD-example',Severity:'MEDIUM',Status:'FAIL'}],['Secrets',{RuleID:'generic',Severity:'HIGH'}]]) test(`reported ${field} are advisory`,t=>{
  const f=fixture(t),p=prepare(f),body=clean();if(field!=='Vulnerabilities'){body.Results[0].Class=field==='Secrets'?'secret':'config';delete body.Results[0].Packages;}body.Results[0][field]=[finding];const r=report(f,p,body);
  assert.equal(r.outputs.status,'findings-advisory');assert.equal(r.record.required,false);
});
for(const results of [undefined,[],[{Target:'package-lock.json',Class:'unknown'}],[{Target:'package-lock.json',Class:'lang-pkgs',Packages:[]}]]) test(`no recognized scope ${JSON.stringify(results)}`,t=>{
  const f=fixture(t),p=prepare(f),body=clean();body.Results=results;const r=report(f,p,body);
  assert.equal(r.outputs.status,'unsupported-profile');assert.equal(r.record.errorCode,'trivy-source-coverage-unconfirmed');
});
for(const [name,change] of [['version',r=>r.Trivy.Version='0.0.0'],['schema',r=>r.SchemaVersion=1],['type',r=>r.ArtifactType='container_image'],['scope escape',r=>r.Results[0].Target='../outside'],['null result',r=>r.Results=[null]],['false clean inventory',r=>r.Results[0].Packages=[{}]]]) test(`invalid report never clean: ${name}`,t=>{
  const f=fixture(t),p=prepare(f),body=clean();change(body);assert.equal(report(f,p,body).outputs.status,'infrastructure-error');
});
for(const [name,body,outcome] of [['missing',undefined,'success'],['malformed','{','success'],['tool failed',clean(),'failure'],['large',' '.repeat(16777217),'success']]) test(`consumed report failure: ${name}`,t=>{
  const f=fixture(t),p=prepare(f);assert.equal(report(f,p,body,outcome).outputs.status,'infrastructure-error');
});
for(const [name,change] of [['not selected',f=>f.plan.buildSelection=[]],['wrong head',f=>f.result.headSha='b'.repeat(40)],['wrong owner',f=>f.result.componentId='other'],['failed result',f=>f.result.status='failed'],['component escape',f=>f.plan.components[0].path='../outside'],['payload escape',f=>f.result.mainArtifact.location.path='.cloudopsworks/out/../outside'],['payload symlink',f=>{const file=path.join(f.workspace,f.result.mainArtifact.location.path);fs.unlinkSync(file);fs.symlinkSync('/etc/hostname',file);}],['dependency escape',f=>fs.symlinkSync('/etc',path.join(f.source,'external'))]]) test(`prepare rejects ${name}`,t=>{
  const f=fixture(t);change(f);f.tools[0].result.stdout=JSON.stringify({record:f.plan});f.tools[1].result.stdout=JSON.stringify({record:f.result});assert.ok(prepare(f).error);
});
test('normal generated dependency internal symlinks are contained without being rejected as arbitrary source escape',t=>{
  const f=fixture(t);fs.mkdirSync(path.join(f.source,'node_modules/.bin'),{recursive:true});fs.mkdirSync(path.join(f.source,'node_modules/tool'));
  fs.writeFileSync(path.join(f.source,'node_modules/tool/cli.js'),'');fs.symlinkSync('../tool/cli.js',path.join(f.source,'node_modules/.bin/tool'));
  assert.equal(prepare(f).error,undefined);
});
for(const name of ['TRIVY_CMD','TRIVY_SKIP_FILES','TRIVY_CONFIG','TRIVY_SEVERITY','AWS_ACCESS_KEY_ID','ACTIONS_ID_TOKEN_REQUEST_TOKEN']) test(`native fs denies ambient ${name} before binary/vendor execution`,t=>{
  const f=fixture(t),p=prepare(f);const r=runStep(native,'filesystem',{env:{SCAN_REF:f.source,REPORT_PATH:p.outputs.report,RUNNER_TEMP:f.temporary,[name]:'false-clean-canary'}});
  assert.equal(r.error?.message,'trivy-source-environment');assert.deepEqual(r.calls,[]);assert.ok(!JSON.stringify(r).includes('false-clean-canary'));
});
for(const id of ['prepare','report']) test(`bounded actual ${id} body`,()=>assert.ok(loadStep(action,id).script.split('\n').filter(l=>l.trim()).length<=120));
for(const [target,type] of [['Python','python-pkg'],['Conda','conda-pkg'],['Ruby','gemspec'],['Node.js','node-pkg'],['Java','jar'],['Kubernetes','kubernetes']]) test(`bounded synthetic ${target}/${type} binds actual package paths, not hostname identity`,t=>{
  const f=fixture(t),p=prepare(f),body=clean();body.Results[0]={Target:target,Class:'lang-pkgs',Type:type,Packages:[{Name:'dependency',Version:'1.2.3',FilePath:'package-lock.json'}]};
  assert.equal(report(f,p,body).outputs.status,'passed');
});
for(const [name,change,status] of [
  ['wrong native type',r=>r.Results[0].Type='npm','unsupported-profile'],
  ['missing source path',r=>delete r.Results[0].Packages[0].FilePath,'unsupported-profile'],
  ['package path escapes',r=>r.Results[0].Packages[0].FilePath='/etc/hostname','infrastructure-error'],
  ['class contradiction',r=>r.Results[0].Class='secret','unsupported-profile'],
]) test(`synthetic scope rejects ${name}`,t=>{
  const f=fixture(t),p=prepare(f),body=clean();body.Results[0]={Target:'Python',Class:'lang-pkgs',Type:'python-pkg',Packages:[{Name:'dep',Version:'1',FilePath:'package-lock.json'}]};change(body);
  assert.equal(report(f,p,body).outputs.status,status);
});
test('a package array cannot turn a secret-only empty scope into false clean',t=>{
  const f=fixture(t),p=prepare(f),body=clean();body.Results[0].Class='secret';assert.equal(report(f,p,body).outputs.status,'infrastructure-error');
});
test('physical lockfile target does not require optional virtual package metadata to be a real filesystem path',t=>{
  const f=fixture(t),p=prepare(f),body=clean();body.Results[0].Packages[0].FilePath='nested.jar!/virtual/package';assert.equal(report(f,p,body).outputs.status,'passed');
});
test('synthetic archive-internal package path without physical source proof remains coverage-unconfirmed',t=>{
  const f=fixture(t),p=prepare(f),body=clean();body.Results[0]={Target:'Python',Class:'lang-pkgs',Type:'python-pkg',Packages:[{Name:'dep',Version:'1',FilePath:'archive.egg!/nested/package'}]};assert.equal(report(f,p,body).outputs.status,'unsupported-profile');
});
