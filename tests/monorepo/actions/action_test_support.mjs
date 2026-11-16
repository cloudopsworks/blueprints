// LOCAL test support. Every executable body comes from current production YAML.
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const worker = fileURLToPath(new URL('./script_worker.mjs', import.meta.url));

export function loadStep(actionPath, id) {
  const source = path.join(root, actionPath);
  if (process.env.MONOREPO_ACTION_BUNDLE) {
    const filename = path.join(process.env.MONOREPO_ACTION_BUNDLE, 'actions.json');
    const action = JSON.parse(readFileSync(filename)).actions[actionPath];
    if (!action) throw new Error(`Actual action missing from extracted bundle: ${actionPath}`);
    const digest = createHash('sha256').update(readFileSync(source)).digest('hex');
    if (action.sha256 !== digest) throw new Error(`Stale extracted action: ${actionPath}`);
    const script = action.scripts.find(step => step.id === id);
    if (!script) throw new Error(`Actual v9 step missing: ${actionPath}#${id}`);
    return script;
  }
  const parsed = spawnSync('yq', ['-o=json', '-I=0', '.', source], {
    encoding: 'utf8', timeout: 10000, maxBuffer: 4 * 1024 * 1024,
    env: {PATH: process.env.PATH || ''},
  });
  if (parsed.status !== 0) throw new Error(parsed.stderr || `Cannot read ${source}`);
  const step = JSON.parse(parsed.stdout).runs.steps.find(step => step.id === id);
  if (!step || step.uses !== 'actions/github-script@v9' || !step.with?.script)
    throw new Error(`Actual v9 step missing: ${actionPath}#${id}`);
  return {id, script: step.with.script, env: step.env || {}};
}

export function runStep(actionPath, id, options = {}) {
  const step = loadStep(actionPath, id);
  const result = spawnSync(process.execPath, [worker], {
    input: JSON.stringify({script: step.script, ...options}), encoding: 'utf8',
    env: {PATH: process.env.PATH || '', ...options.env},
    timeout: options.timeout || 20000, maxBuffer: 8 * 1024 * 1024,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(result.stderr || `Script worker exited ${result.status}`);
  return JSON.parse(result.stdout);
}
