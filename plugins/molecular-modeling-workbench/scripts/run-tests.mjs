#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const cacheRoot = resolve(process.env.AI4S_TEST_CACHE_DIR || root, '.test-cache');
mkdirSync(cacheRoot, { recursive: true });
const env = {
  ...process.env,
  UV_CACHE_DIR: process.env.UV_CACHE_DIR || resolve(cacheRoot, 'uv'),
  PYTHONPYCACHEPREFIX: process.env.PYTHONPYCACHEPREFIX || resolve(cacheRoot, 'pycache'),
};
const deferredPythonSuites = ['docking-visualization'];
const m5PythonSuites = ['md-simulation-plotting', 'md-trajectory-analysis'];
const includeDeferred = process.argv.includes('--include-deferred');
const includeWeb = process.argv.includes('--include-web');
const webOnly = process.argv.includes('--web-only');
const pythonSuites = [
  'molecular-modeling-environment',
  'docking-to-md-handoff',
  'docking-simulation-run',
  'docking-complex-analysis',
  ...(includeDeferred ? deferredPythonSuites : []),
  'ligand-parameterization',
  'md-simulation-run',
  ...(includeWeb ? m5PythonSuites : []),
];
if (!includeDeferred && !webOnly) {
  process.stderr.write(
    `Skipping deferred Python suites: ${deferredPythonSuites.join(', ')}. Run npm run test:all to include them.\n`,
  );
}
const coreCommands = [
  [process.execPath, ['--test', 'tests/*.test.mjs']],
  ...pythonSuites.map((skill) => ['uv', ['run', '--locked', 'python', '-m', 'unittest', 'discover', '-s', `skills/${skill}/tests`]]),
];
const webCommands = [
  ['uv', ['run', '--project', 'web', '--locked', 'python', '-m', 'unittest', 'discover', '-s', 'web/runner/tests', '-t', '.']],
  ['uv', ['run', '--project', 'web', '--locked', 'python', '-m', 'unittest', 'discover', '-s', 'web/backend/tests', '-t', '.']],
  ['npm', ['--prefix', 'web/frontend', 'run', 'build']],
  ['npm', ['--prefix', 'web/frontend', 'run', 'lint']],
  ['npm', ['--prefix', 'web/frontend', 'test', '--', '--run']],
];
const commands = webOnly ? webCommands : [...coreCommands, ...(includeWeb ? webCommands : [])];
for (const [command, args] of commands) {
  const result = spawnSync(command, args, { cwd: root, env, stdio: 'inherit', shell: false });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
