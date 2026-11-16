// LOCAL isolated child process: no inherited credentials and no real API/network.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {spawnSync} from 'node:child_process';

const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const outputs = {}, calls = [], logs = [], failures = [];
const api = [...(input.api || [])], tools = [...(input.tools || [])];
const fetches = [...(input.fetches || [])];
const requireBuiltin = createRequire(import.meta.url);
const allowed = new Set(['fs', 'path', 'os', 'crypto', 'buffer', 'stream', 'url', 'util', 'zlib']);
const safeRequire = name => {
  if (!allowed.has(name.replace(/^node:/, '').split('/')[0]))
    throw new Error(`Unexpected implementation import: ${name}`);
  return requireBuiltin(name);
};
function expectedArguments(actual, expected) {
  for (const [key, value] of Object.entries(expected || {}))
    assert.deepEqual(actual[key], value, `Unexpected argument ${key}`);
}
function endpoint(name) {
  return async args => {
    calls.push({kind: 'api', method: name, args});
    const expected = api.shift();
    assert.ok(expected, `Unexpected API operation: ${name}`);
    assert.equal(name, expected.method);
    expectedArguments(args || {}, expected.args);
    if (expected.error) throw Object.assign(new Error(expected.error.message || 'API denied'), expected.error);
    return expected.result;
  };
}
const rest = new Proxy({}, {get: (_, namespace) => new Proxy({}, {
  get: (_, method) => endpoint(`rest.${String(namespace)}.${String(method)}`),
})});
const github = {
  rest,
  request: (route, args) => endpoint(`request:${route}`)(args),
  graphql: (query, args) => endpoint('graphql')({...args, query}),
  paginate: async (method, args) => {
    const result = await method(args);
    return Array.isArray(result.data) ? result.data : result.data.jobs || result.data.artifacts;
  },
};
const summary = new Proxy({}, {get: (_, name) => (...args) => {
  logs.push({kind: 'summary', method: String(name), args});
  return name === 'write' ? Promise.resolve() : summary;
}});
const core = {
  setOutput: (key, value) => { outputs[key] = value; },
  setFailed: message => { failures.push(String(message)); },
  info: message => logs.push({kind: 'info', message}),
  warning: message => logs.push({kind: 'warning', message}),
  debug: message => logs.push({kind: 'debug', message}),
  error: message => logs.push({kind: 'error', message}),
  setSecret: () => {}, summary,
};
const exec = {
  getExecOutput: async (command, args, options = {}) => {
    calls.push({kind: 'exec', command, args,
      input: options.input ? Buffer.from(options.input).toString() : undefined,
      ...(options.env ? {env: options.env} : {})});
    if (input.realCli && command === 'tronador' || input.realTar && command === 'tar') {
      if (command === 'tar') {
        assert.equal(args.length, 7);
        assert.deepEqual([args[0], args[1], args[3], args[5], args[6]],
          ['--extract', '--file', '--directory', '--no-same-owner', '--no-same-permissions']);
      }
      let directory, descriptor, result;
      try {
        let stdio;
        if (command === 'tronador' && options.input !== undefined && options.input !== null) {
          directory = fs.mkdtempSync(path.join(fs.realpathSync(process.env.RUNNER_TEMP || os.tmpdir()), 'native-stdin-'));
          fs.chmodSync(directory, 0o700);
          const file = path.join(directory, 'input.bin');
          fs.writeFileSync(file, options.input, {mode: 0o600, flag: 'wx'});
          descriptor = fs.openSync(file, 'r');
          stdio = [descriptor, 'pipe', 'pipe'];
        }
        result = spawnSync(command === 'tronador' ? input.realCli : 'tar', args, {
          ...(stdio ? {stdio} : {input: options.input}), encoding: 'utf8', env: process.env,
          cwd: options.cwd, timeout: 120000, maxBuffer: 4 * 1024 * 1024,
        });
      } finally {
        try { if (descriptor !== undefined) fs.closeSync(descriptor); }
        finally { if (directory) fs.rmSync(directory, {recursive: true, force: true}); }
      }
      if (result.error) throw result.error;
      calls[calls.length - 1].result = {exitCode: result.status,
        stdout: result.stdout, stderr: result.stderr};
      return {exitCode: result.status, stdout: result.stdout, stderr: result.stderr};
    }
    const expected = tools.shift();
    assert.ok(expected, `Unexpected executable: ${command}`);
    assert.equal(command, expected.command || 'tronador');
    if (expected.args) assert.deepEqual(args, expected.args);
    if (expected.prefix) assert.deepEqual(args.slice(0, expected.prefix.length), expected.prefix);
    if (expected.error) throw new Error(expected.error);
    if (expected.nativeSavedPlan !== undefined) {
      // Finite LOCAL Terragrunt saved-plan output double; no native provider execution claim.
      assert.equal(command, 'terragrunt');
      assert.equal(args.length, 9);
      assert.deepEqual([args[0],args[1],...args.slice(3)], ['--non-interactive','--working-dir','run','--','plan','-destroy','-input=false','-out=operation.tfplan']);
      const path = requireBuiltin('node:path'), directory=fs.realpathSync(args[2]), temp=fs.realpathSync(process.env.RUNNER_TEMP);
      assert.ok(directory.startsWith(temp+path.sep));
      assert.equal(fs.lstatSync(directory).isDirectory(), true);
      fs.writeFileSync(path.join(directory,'operation.tfplan'), Buffer.from(expected.nativeSavedPlan, 'base64'), {mode:0o600,flag:'wx'});
    }
    if (expected.nativeFile !== undefined) {
      // Finite LOCAL AWS CLI response side effect, never a generic source runner.
      assert.equal(command, 'aws');
      assert.deepEqual(args.slice(0, 2), ['s3api', 'get-object']);
      assert.ok(args.includes('--if-match'), 'Native object read must remain conditional');
      const destination = args.at(-1);
      assert.equal(typeof destination, 'string');
      const body = typeof expected.nativeFile === 'string' ? expected.nativeFile : JSON.stringify(expected.nativeFile);
      if (fs.existsSync(destination)) {
        const stat = fs.lstatSync(destination);
        assert.ok(stat.isFile() && !stat.isSymbolicLink());
        assert.equal(stat.mode & 0o077, 0);
      }
      fs.writeFileSync(destination, body, {mode: 0o600, flag: 'w'});
    }
    return {exitCode: 0, stdout: '', stderr: '', ...expected.result};
  },
};
exec.exec = async (command, args, options) => (await exec.getExecOutput(command, args, options)).exitCode;
const io = {mkdirP: path => fs.promises.mkdir(path, {recursive: true}),
  rmRF: path => fs.promises.rm(path, {recursive: true, force: true}),
  cp: (source, destination) => fs.promises.copyFile(source, destination)};
const fetch = async (url, options = {}) => {
  calls.push({kind: 'fetch', url: String(url), method: options.method || 'GET',
    headers: options.headers || {}, redirect: options.redirect,
    credentials: options.credentials, hasSignal: !!options.signal});
  const expected = fetches.shift();
  assert.ok(expected, `Unexpected network request: ${url}`);
  if (expected.url) assert.equal(String(url), expected.url);
  if (expected.error) throw Object.assign(new Error(expected.error), {name: expected.errorName || 'Error'});
  const body = expected.base64 ? Buffer.from(expected.base64, 'base64') : expected.body || '';
  return new Response(body, {status: expected.status || 200, headers: expected.headers || {}});
};
// Both lexical and global fetch are denied unless a finite response is queued.
globalThis.fetch = fetch;
const NativeDate = Date;
const fixedTime = NativeDate.parse(input.now || '2026-11-13T12:00:00Z');
assert.ok(Number.isFinite(fixedTime), 'Invalid isolated test clock');
class FixedDate extends NativeDate {
  constructor(...args) { super(...(args.length ? args : [fixedTime])); }
  static now() { return fixedTime; }
}
globalThis.Date = FixedDate;
const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
let result, error;
try {
  result = await new AsyncFunction('github', 'context', 'core', 'exec', 'io', 'require',
    'console', 'fetch', 'getOctokit', input.script)(github, input.context || {
      repo: {owner: 'example', repo: 'mixed'},
    }, core, exec, io, safeRequire, {log: (...args) => logs.push({kind: 'console', args})}, fetch, () => github);
} catch (caught) {
  error = {name: caught.name, message: caught.message};
}
process.stdout.write(JSON.stringify({outputs, calls, logs, failures, result, error,
  unused: {api: api.length, tools: tools.length, fetches: fetches.length}}));
