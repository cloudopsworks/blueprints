// Actual installed Go contracts/payload + Git. Remote vendor actions are finite protocol
// fixtures only: no Trivy/setup installation, database download or vulnerability scan.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {root,loadStep} from './action_test_support.mjs';
const cli=process.env.TRONADOR_CLI;
assert.ok(cli&&fs.existsSync(cli),'reviewed installed CLI required');
const action='ci/scan/trivy/source/action.yml',native='ci/scan/trivy/native/action.yml';
const worker=`import fs from 'node:fs';import {createRequire} from 'node:module';import {spawnSync} from 'node:child_process';
const input=JSON.parse(fs.readFileSync(0,'utf8')),outputs={},calls=[],require=createRequire(import.meta.url);
const exec={getExecOutput:async(command,args,options={})=>{calls.push({command,args});if(command==='trivy'){if(JSON.stringify(args)!=='["--version"]')throw Error('unexpected vendor invocation');if(input.trivy){const r=spawnSync(input.trivy,args,{env:options.env,encoding:'utf8',timeout:20000});return {exitCode:r.status,stdout:r.stdout,stderr:r.stderr};}return {exitCode:0,stdout:input.banner||'Version: 0.69.3\\n',stderr:''};}if(!['tronador','git'].includes(command))throw Error('unexpected executable');const r=spawnSync(command==='tronador'?input.cli:'git',args,{cwd:process.cwd(),input:options.input,env:options.env||process.env,encoding:'utf8',timeout:20000,maxBuffer:4194304});if(r.error)throw r.error;return {exitCode:r.status,stdout:r.stdout,stderr:r.stderr};}};
let error;try{await new(Object.getPrototypeOf(async function(){}).constructor)('require','exec','core',input.script)(require,exec,{setOutput:(k,v)=>outputs[k]=v});}catch(e){error={message:e.message};}process.stdout.write(JSON.stringify({outputs,calls,error}));`;
function execute(file,id,env,cwd,banner,trivy) {
  const step=loadStep(file,id);
  const r=spawnSync(process.execPath,['--input-type=module','-e',worker],{cwd,input:JSON.stringify({script:step.script,cli,banner,trivy}),env:{PATH:process.env.PATH,...env},encoding:'utf8',timeout:30000,maxBuffer:4194304});
  assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout);
}
function fixture(t) {
  const temporary=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'trivy-native-protocol-')));
  t.after(()=>fs.rmSync(temporary,{recursive:true,force:true}));
  const workspace=path.join(temporary,'workspace');fs.cpSync(path.join(root,'tests/monorepo/fixtures/composite_first/mixed'),workspace,{recursive:true});
  const git=(...args)=>{const r=spawnSync('git',['-c','core.hooksPath=/dev/null','-c','user.name=Local','-c','user.email=test@example.invalid',...args],{cwd:workspace,encoding:'utf8'});assert.equal(r.status,0,r.stderr);return r.stdout.trim();};
  git('init','-q','-b','develop');git('add','.');git('commit','-qm','source');const head=git('rev-parse','HEAD');
  const p=spawnSync(cli,['components','plan','--workdir',workspace,'--head',head,'--version','1.2.3','--event','push','--repository-id','123','--repository-name','example/mixed','--json'],{encoding:'utf8',timeout:20000});assert.equal(p.status,0,p.stderr);const plan=JSON.parse(p.stdout);
  const descriptor=(name,kind,format)=>{
    const source=path.join(root,'tests/monorepo/contracts/artifacts',name),bytes=fs.readFileSync(source),relative=`.cloudopsworks/out/node/1.2.3/${name}`;
    const file=path.join(workspace,relative);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,bytes);
    return {kind,format,digest:'sha256:'+createHash('sha256').update(bytes).digest('hex'),sizeBytes:bytes.length,location:{kind:'local',path:relative},sourceSha:head,builtVersion:'1.2.3'};
  };
  const result={apiVersion:'cloudopsworks.io/v1',kind:'ComponentResult',repository:plan.repository,componentId:'node',headSha:head,version:plan.version,purpose:'release',status:'succeeded',mainArtifact:descriptor('app.zip','function','zip'),previewArtifact:descriptor('image.oci.tar','container','oci'),error:null};
  const planPath=path.join(temporary,'plan.json'),resultPath=path.join(temporary,'result.json');fs.writeFileSync(planPath,JSON.stringify(plan));fs.writeFileSync(resultPath,JSON.stringify(result));
  fs.writeFileSync(path.join(workspace,'components/node/package-lock.json'),'{}');
  // Source-provided suppressions must not become the scanner configuration.
  for(const name of ['trivy.yaml','trivy-secret.yaml','.trivyignore.yaml'])fs.writeFileSync(path.join(workspace,name),'malicious: source-suppression-canary');
  const env={SOURCE_PATH:workspace,PLAN_PATH:planPath,COMPONENT_RESULT:resultPath,COMPONENT:'node',SOURCE_SHA:head,RUNNER_TEMP:temporary,GITHUB_WORKSPACE:workspace};
  return {temporary,workspace,head,result,env,git};
}
function prepare(f) { const p=execute(action,'prepare',f.env,f.workspace);assert.equal(p.error,undefined,JSON.stringify(p));return p; }
function invocation(f,p,banner) {return execute(native,'filesystem',{RUNNER_TEMP:f.temporary,GITHUB_WORKSPACE:f.workspace,SCAN_TYPE:'fs',SCAN_REF:p.outputs.source,REPORT_PATH:p.outputs.report},f.workspace,banner);}
function vendorFixture(f,p,n,content) {
  const r=spawnSync('yq',['-o=json','-I=0','.',path.join(root,native)],{encoding:'utf8'});assert.equal(r.status,0,r.stderr);
  const step=JSON.parse(r.stdout).runs.steps.find(s=>s.uses==='aquasecurity/trivy-action@v0.36.0'&&s.with['scan-type']==='fs');
  assert.equal(step.with['skip-setup-trivy'],true);assert.equal(step.with['scan-ref'],'${{ inputs.scan-ref }}');assert.equal(step.with.input,undefined);
  for(const key of ['config','secret','ignore']){assert.equal(fs.readFileSync(n.outputs[key],'utf8'),'{}\n');assert.equal(fs.statSync(n.outputs[key]).mode&0o777,0o600);assert.ok(!n.outputs[key].startsWith(f.workspace+path.sep));}
  assert.equal(step.env.TRIVY_CMD,'trivy');assert.equal(step.env.TRIVY_SECRET_CONFIG,'${{ steps.filesystem.outputs.secret }}');
  assert.equal(step.with.scanners,'vuln,misconfig,secret');assert.equal(step.with.severity,'CRITICAL,HIGH,MEDIUM');assert.equal(step.with['exit-code'],'0');assert.equal(step.with.cache,false);
  // This is deliberately a finite remote-action output fixture, NOT a real vendor execution.
  fs.writeFileSync(p.outputs.report,typeof content==='string'?content:JSON.stringify(content));
  return execute(action,'report',{DIRECTORY:p.outputs.directory,TOOL_OUTCOME:'success'},f.workspace);
}
const clean=()=>({SchemaVersion:2,Trivy:{Version:'0.69.3'},ArtifactType:'filesystem',ArtifactName:'runner-hostname-content',Results:[{Target:'package-lock.json',Class:'lang-pkgs',Type:'npm',Packages:[{Name:'dependency',Version:'1.2.3'}]}]});

test('real CLI/Git source binding and finite pinned vendor protocol preserve controlled config and advisory result',t=>{
  const f=fixture(t),p=prepare(f),n=invocation(f,p);assert.equal(n.error,undefined,JSON.stringify(n));
  assert.deepEqual(n.calls,[{command:'trivy',args:['--version']}]);assert.equal(fs.statSync(p.outputs.report).mode&0o777,0o600);
  const body=clean();body.Results[0].Vulnerabilities=[{VulnerabilityID:'CVE-example',Severity:'HIGH'}];const r=vendorFixture(f,p,n,body);
  assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs.status,'findings-advisory');const record=JSON.parse(fs.readFileSync(r.outputs.result));assert.equal(record.required,false);assert.equal(record.profile,'npm');assert.equal(record.artifactDigest,f.result.mainArtifact.digest);
  assert.equal(f.git('rev-parse','HEAD'),f.head);assert.equal(fs.statSync(r.outputs.result).mode&0o777,0o600);
});
test('wrong installed version cannot reach finite vendor protocol',t=>{
  const f=fixture(t),p=prepare(f),n=invocation(f,p,'Version: 0.69.2\n');assert.equal(n.error?.message,'trivy-source-version');assert.equal(fs.existsSync(p.outputs.report),false);
});
test('source-controlled vendor helper is rejected rather than sourced/clobbered',t=>{
  const f=fixture(t),p=prepare(f),helper=path.join(f.workspace,'trivy_envs.txt');fs.writeFileSync(helper,'touch source-execution-canary');const n=invocation(f,p);assert.equal(n.error?.message,'trivy-source-reserved-helper');assert.deepEqual(n.calls,[]);assert.equal(fs.readFileSync(helper,'utf8'),'touch source-execution-canary');
});
test('native vendor has no filesystem write quota: large source files survive while oversized consumed JSON is rejected',t=>{
  const f=fixture(t);fs.writeFileSync(path.join(f.workspace,'components/node/large-source.bin'),Buffer.alloc(20*1024*1024));const p=prepare(f),n=invocation(f,p);assert.equal(n.error,undefined);
  const r=vendorFixture(f,p,n,' '.repeat(17*1024*1024));assert.equal(fs.statSync(p.outputs.report).size,17*1024*1024);assert.equal(fs.statSync(path.join(p.outputs.source,'large-source.bin')).size,20*1024*1024);assert.equal(r.outputs.status,'infrastructure-error');
});
test('real payload corruption and real Git mismatch cannot become a source scanner identity',t=>{
  const f=fixture(t);fs.appendFileSync(path.join(f.workspace,f.result.mainArtifact.location.path),'corruption');const p=execute(action,'prepare',f.env,f.workspace);assert.equal(p.error?.message,'trivy-source-payload-integrity');
  const g=fixture(t);fs.writeFileSync(path.join(g.workspace,'changed.txt'),'change');g.git('add','.');g.git('commit','-qm','different head');const q=execute(action,'prepare',g.env,g.workspace);assert.equal(q.error?.message,'trivy-source-head');
});

test('actual pinned offline secret+egg ingestion report is accepted without claiming vendor/vulnerability/misconfiguration execution', {skip:!process.env.TRIVY_NATIVE}, t=>{
  const trivy=fs.realpathSync(process.env.TRIVY_NATIVE),sha=createHash('sha256').update(fs.readFileSync(trivy)).digest('hex');
  assert.equal(sha,'bef08bfe2644873257d75585dd62e1409eb5c53403075c4bc83d54279dffd812');
  const f=fixture(t),packages=path.join(f.workspace,'components/node/packages');fs.mkdirSync(packages);
  fs.mkdirSync(path.join(f.temporary,'EGG-INFO'));const info=path.join(f.temporary,'EGG-INFO/PKG-INFO');fs.writeFileSync(info,'Metadata-Version: 2.1\nName: requests\nVersion: 2.0.0\n');
  const zip=spawnSync('zip',['-q',path.join(packages,'demo.egg'),'EGG-INFO/PKG-INFO'],{cwd:f.temporary,encoding:'utf8'});assert.equal(zip.status,0,zip.stderr);
  fs.writeFileSync(path.join(f.workspace,'components/node/config.js'),'const github_token = "ghp_AbCdEf0123456789AbCdEf0123456789AbCdEf";\n');
  const p=prepare(f),n=execute(native,'filesystem',{RUNNER_TEMP:f.temporary,GITHUB_WORKSPACE:f.workspace,SCAN_TYPE:'fs',SCAN_REF:p.outputs.source,REPORT_PATH:p.outputs.report},f.workspace,undefined,trivy);
  assert.equal(n.error,undefined,JSON.stringify(n));
  const args=['fs','--config',n.outputs.config,'--cache-dir',n.outputs.cache,'--secret-config',n.outputs.secret,'--ignorefile',n.outputs.ignore,'--skip-version-check','--disable-telemetry','--scanners','secret','--list-all-pkgs','--format','json','--output',p.outputs.report,p.outputs.source];
  const result=spawnSync(trivy,args,{env:{PATH:process.env.PATH,HOME:n.outputs.home,HTTP_PROXY:'http://127.0.0.1:1',HTTPS_PROXY:'http://127.0.0.1:1',ALL_PROXY:'http://127.0.0.1:1',NO_PROXY:''},encoding:'utf8',timeout:30000,maxBuffer:1048576});
  assert.equal(result.status,0,'actual offline native probe failed');
  const body=JSON.parse(fs.readFileSync(p.outputs.report));assert.equal(body.Trivy.Version,'0.69.3');assert.equal(body.ArtifactType,'filesystem');
  assert.ok(body.Results.some(row=>row.Target==='Python'&&row.Type==='python-pkg'&&row.Packages.some(pkg=>pkg.FilePath==='packages/demo.egg')));
  const classified=execute(action,'report',{DIRECTORY:p.outputs.directory,TOOL_OUTCOME:'success'},f.workspace);assert.equal(classified.error,undefined,JSON.stringify(classified));
  assert.ok(['passed','findings-advisory'].includes(classified.outputs.status));
  console.log(JSON.stringify({nativeSha256:sha,scope:'offline secret+package ingestion only; no vendor/vuln/misconfig/full coverage proof',status:classified.outputs.status,targets:body.Results.map(row=>({target:row.Target,class:row.Class,type:row.Type||null}))}));
});

test('captured actual full-profile native JSON decodes against copied inert source data, not hosted/vendor source authority', {skip:!process.env.TRIVY_FULL_CAPTURE}, t=>{
  const metadata=JSON.parse(fs.readFileSync(process.env.TRIVY_FULL_CAPTURE));
  const raw=fs.readFileSync(path.join(metadata.private_fixture_root,'report.json'));
  assert.equal(createHash('sha256').update(raw).digest('hex'),metadata.report_sha256);
  assert.equal(metadata.exit_code,0);assert.equal(metadata.binary_sha256,'bef08bfe2644873257d75585dd62e1409eb5c53403075c4bc83d54279dffd812');
  const f=fixture(t);fs.cpSync(path.join(metadata.private_fixture_root,'component source'),path.join(f.workspace,'components/node'),{recursive:true});
  const p=prepare(f),n=invocation(f,p);assert.equal(n.error,undefined);
  const r=vendorFixture(f,p,n,raw.toString());assert.equal(r.error,undefined,JSON.stringify(r));assert.equal(r.outputs.status,'findings-advisory');
  const rows=JSON.parse(raw).Results;assert.ok(rows.some(row=>row.Vulnerabilities?.length));assert.ok(rows.some(row=>row.Misconfigurations?.length));assert.ok(rows.some(row=>row.Secrets?.length));
  console.log(JSON.stringify({actualCaptureSha256:metadata.report_sha256,decodedStatus:r.outputs.status,scope:'actual captured vuln/misconfig/secret JSON; this reuse has finite fixture source binding, not fresh vendor execution or full coverage'}));
});

test('application checkout under source/ leaves native reserved workspace helper separate from legitimate source data',t=>{
  const f=fixture(t),host=path.join(f.temporary,'host');fs.mkdirSync(host);const sourceRoot=path.join(host,'source');fs.renameSync(f.workspace,sourceRoot);
  f.workspace=host;f.env.SOURCE_PATH=sourceRoot;f.env.GITHUB_WORKSPACE=host;
  const legitimate=path.join(sourceRoot,'trivy_envs.txt');fs.writeFileSync(legitimate,'legitimate nested source data');
  const p=prepare(f),n=invocation(f,p);assert.equal(n.error,undefined,JSON.stringify(n));
  assert.ok(p.outputs.source.startsWith(sourceRoot+path.sep));assert.equal(vendorFixture(f,p,n,clean()).outputs.status,'passed');assert.equal(fs.readFileSync(legitimate,'utf8'),'legitimate nested source data');
});
