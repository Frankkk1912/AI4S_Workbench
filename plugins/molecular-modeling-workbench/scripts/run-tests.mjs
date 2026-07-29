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
const pythonSuites = [
  'molecular-modeling-environment',
  'docking-to-md-handoff',
  'docking-simulation-run',
  'docking-complex-analysis',
  'docking-visualization',
  'ligand-parameterization',
  'md-simulation-run',
];
const commands = [
  [process.execPath, ['--test', 'tests/*.test.mjs']],
  ...pythonSuites.map((skill) => ['uv', ['run', '--locked', 'python', '-m', 'unittest', 'discover', '-s', `skills/${skill}/tests`]]),
];
for (const [command, args] of commands) {
  const result = spawnSync(command, args, { cwd: root, env, stdio: 'inherit', shell: false });
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status ?? 1);
}
