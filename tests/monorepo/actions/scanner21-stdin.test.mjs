// LOCAL native transport observations call through real filesystem and the immutable native CLI.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
const cli=process.env.TRONADOR_CLI;
assert.ok(cli&&fs.existsSync(cli),'immutable CLI required, no silent skip');
assert.equal(createHash('sha256').update(fs.readFileSync(cli)).digest('hex'),'2dd1cc04bcda2d26f851cfe61355bae79e57bd48267934df1ed521a9e87538c5');
const worker=new URL('./script_worker.mjs',import.meta.url);
const record=fs.readFileSync(new URL('../../../../tronador-cli-v511/internal/components/testdata/operations/scanner-result.json',import.meta.url));
const observe=`const fs = require('node:fs'), path = require('node:path'), crypto = require('node:crypto');
const observations = [], originalWrite = fs.writeFileSync, originalOpen = fs.openSync, originalClose = fs.closeSync;
fs.writeFileSync = function(file, bytes, options) { observations.push({file,length:Buffer.byteLength(bytes),hash:crypto.createHash('sha256').update(bytes).digest('hex'),options}); const result=originalWrite.call(fs,file,bytes,options); observations.at(-1).mode=fs.statSync(file).mode & 0o777; observations.at(-1).directoryMode=fs.statSync(path.dirname(file)).mode & 0o777; return result; };
const opens = [], closes = [];
fs.openSync = function(file, flags, ...args) { const fd = originalOpen.call(fs,file,flags,...args); opens.push({file,flags,fd}); return fd; };
fs.closeSync = function(fd) { closes.push(fd); return originalClose.call(fs,fd); };
`;
function invoke(t,bytes,{kind='ScannerResult',cwd,runner=true,extra='',before='',asString=false,noInput=false}={}){
 const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'scanner21-stdin-')));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
 const script=observe+before+`const supplied=${asString?JSON.stringify(bytes.toString()):`Buffer.from('${bytes.toString('base64')}','base64')`};
let result, failure;
try { result=await exec.getExecOutput('tronador',${noInput?`['--help']`:`['components','contracts','validate','--kind','${kind}']`},{${noInput?'':'input:supplied,'}${cwd?`cwd:${JSON.stringify(cwd)},`:''}ignoreReturnCode:true}); } catch(error) { failure=error.message; }
${extra}
core.setOutput('observation',JSON.stringify({observations,opens,closes,result,failure,osTemporaryRoot:fs.realpathSync(require('node:os').tmpdir()),remaining:observations.filter(x=>fs.existsSync(x.file)).map(x=>x.file),remainingDirectories:observations.filter(x=>fs.existsSync(path.dirname(x.file))).map(x=>path.dirname(x.file))}));`;
 const r=spawnSync(process.execPath,[worker.pathname],{input:JSON.stringify({script,realCli:cli}),encoding:'utf8',env:{PATH:process.env.PATH,...(runner?{RUNNER_TEMP:root}:{})},timeout:20000,maxBuffer:8388608});
 assert.equal(r.status,0,r.stderr||r.error?.message);const output=JSON.parse(r.stdout);assert.equal(output.error,undefined,JSON.stringify(output));return {root,output,observed:JSON.parse(output.outputs.observation)};
}
test('real native input selects a private readonly FD and cleans resources',t=>{
 const f=invoke(t,record),o=f.observed;assert.equal(o.observations.length,1,'native input must be written at the actual filesystem boundary, not sent through a synchronous pipe');
 assert.equal(o.result.exitCode,0,o.result.stderr);assert.equal(o.observations[0].length,record.length);assert.equal(o.observations[0].hash,createHash('sha256').update(record).digest('hex'));
 assert.equal(o.observations[0].mode,0o600);assert.equal(o.observations[0].directoryMode,0o700);assert.deepEqual(o.observations[0].options,{mode:0o600,flag:'wx'});assert.equal(o.opens.find(x=>x.file===o.observations[0].file&&x.flags==='r').flags,'r');assert.ok(o.closes.includes(o.opens.find(x=>x.file===o.observations[0].file&&x.flags==='r').fd));
 assert.equal(path.dirname(path.dirname(o.observations[0].file)),f.root);assert.deepEqual(o.remaining,[]);assert.deepEqual(o.remainingDirectories,[]);
 assert.deepEqual(f.output.calls[0].args,['components','contracts','validate','--kind','ScannerResult']);assert.equal(f.output.calls[0].result.exitCode,0);
});

function assertBytesAndCleanup(observed,bytes){
 assert.equal(observed.observations.length,1);assert.equal(observed.observations[0].length,bytes.length);assert.equal(observed.observations[0].hash,createHash('sha256').update(bytes).digest('hex'));
 assert.deepEqual(observed.remaining,[]);assert.deepEqual(observed.remainingDirectories,[]);
}
function pinnedPlan(){
 const fixture=new URL('../../../../tronador-cli-v511/internal/components/testdata/contracts/valid/build-plan.json',import.meta.url),plan=JSON.parse(fs.readFileSync(fixture)),template=structuredClone(plan.components[0]);
 plan.components=Array.from({length:256},(_,i)=>{const c=structuredClone(template);c.id='component-'+i;c.path='components/'+c.id;c.targetIds=[];for(const tc of c.toolchains)tc.components=[c.id];return c;});plan.targets=[];
 plan.buildSelection=plan.components.map(c=>({componentId:c.id,reasons:['component-path-changed']}));plan.matrix.include=plan.components.map(c=>({componentId:c.id,closure:[c.id],toolchains:c.toolchains}));
 const bytes=Buffer.from(JSON.stringify(plan));assert.equal(bytes.length,183724);assert.equal(createHash('sha256').update(bytes).digest('hex'),'1bb909cc6cf241566d4455858cb5bec7693dcaaa05d9f8a48a5f561b6d65b659');return bytes;
}
test('300 actual native validations preserve exact183724byte input through readonly FD without retries',t=>{
 const bytes=pinnedPlan();for(let i=0;i<300;i++){const f=invoke(t,bytes,{kind:'BuildPlan'});assertBytesAndCleanup(f.observed,bytes);assert.equal(f.observed.result.exitCode,0,`iteration${i}: ${f.observed.result.stderr}`);assert.equal(f.output.calls.length,1);assert.equal(JSON.parse(f.observed.result.stdout).valid,true);}
});
for(const [label,bytes,pattern]of [
 ['malformed JSON',Buffer.from('{'),/contract-invalid-json/],
 ['duplicate key',Buffer.from('{"scanner":"semgrep",'+record.toString().slice(1)),/contract-invalid-json: duplicate key "scanner"/],
 ['invalid UTF8',Buffer.concat([Buffer.from('{"x":"'),Buffer.from([255]),Buffer.from('"}')]),/contract-invalid-utf8/],
])test(`real native FD input preserves ${label} bytes and rejection with cleanup`,t=>{
 const f=invoke(t,bytes);assertBytesAndCleanup(f.observed,bytes);assert.notEqual(f.observed.result.exitCode,0);assert.match(f.observed.result.stderr,pattern);assert.equal(f.output.calls.length,1);assert.equal(f.output.calls[0].result.exitCode,f.observed.result.exitCode);
});
test('real native string input uses canonical OS temporary fallback and cleans it',t=>{
 const f=invoke(t,record,{runner:false,asString:true});assertBytesAndCleanup(f.observed,record);assert.equal(f.observed.result.exitCode,0);assert.equal(path.dirname(path.dirname(f.observed.observations[0].file)),f.observed.osTemporaryRoot);
});
test('real native launch error retains error and cleans readonly input resources',t=>{
 const f=invoke(t,record,{cwd:'/nonexistent-scanner21-working-directory'});assertBytesAndCleanup(f.observed,record);assert.match(f.observed.failure,/ENOENT/);assert.equal(f.observed.result,undefined);assert.equal(f.output.calls.length,1);assert.equal(f.output.calls[0].result,undefined);
});
test('real exclusive creation failure cleans the partially created private directory',t=>{
 const before=`const observeWrite=fs.writeFileSync; fs.writeFileSync=function(file,bytes,options){originalWrite.call(fs,file,bytes,{mode:0o600,flag:'wx'});return observeWrite.call(fs,file,bytes,options);};\n`;
 const f=invoke(t,record,{before});assertBytesAndCleanup(f.observed,record);assert.match(f.observed.failure,/EEXIST/);assert.equal(f.observed.result,undefined);assert.equal(f.output.calls[0].result,undefined);
});
test('native no-input and real tar semantics stay unchanged; timeout cleanup is statically covered, not executed',()=>{
 const source=fs.readFileSync(worker,'utf8');assert.match(source,/command === 'tronador' && options\.input !== undefined && options\.input !== null/);
 assert.match(source,/\.\.\.\(stdio \? \{stdio\} : \{input: options\.input\}\), encoding: 'utf8', env: process\.env/);
 assert.match(source,/cwd: options\.cwd, timeout: 120000, maxBuffer: 4 \* 1024 \* 1024/);
 assert.match(source,/finally \{\s*try \{ if \(descriptor !== undefined\) fs\.closeSync\(descriptor\); \}\s*finally \{ if \(directory\) fs\.rmSync\(directory, \{recursive: true, force: true\}\); \}/);
 assert.match(source,/command === 'tronador' \? input\.realCli : 'tar'/);assert.match(source,/\['--extract', '--file', '--directory', '--no-same-owner', '--no-same-permissions'\]/);
});
test('real native no-input invocation retains ordinary help result and creates no stdin file',t=>{
 const f=invoke(t,record,{noInput:true});assert.equal(f.observed.result.exitCode,0,f.observed.result.stderr);assert.match(f.observed.result.stdout,/Usage:/);assert.deepEqual(f.observed.observations,[]);assert.deepEqual(f.output.calls[0].args,['--help']);assert.equal(f.output.calls[0].input,undefined);
});
