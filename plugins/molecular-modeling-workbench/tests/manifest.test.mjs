import assert from 'node:assert/strict';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import test from 'node:test';
import { checkPluginAssembly, treeHash } from '../scripts/assemble-plugin.mjs';

const root = resolve(import.meta.dirname, '..');
const repoRoot = resolve(root, '../..');

test('plugin-meta.json carries required fields and plain semver version', () => {
  const meta = JSON.parse(readFileSync(resolve(root, 'plugin-meta.json'), 'utf8'));
  for (const key of ['name', 'version', 'description', 'author', 'license', 'codex', 'marketplace']) {
    assert.ok(meta[key], `plugin-meta.json missing ${key}`);
  }
  assert.match(meta.version, /^\d+\.\d+\.\d+$/);
});

test('codex and claude manifests are generated and synchronized', () => {
  assert.match(checkPluginAssembly(), /match all source skills/);
  const codex = JSON.parse(readFileSync(resolve(root, '.codex-plugin/plugin.json'), 'utf8'));
  const claude = JSON.parse(readFileSync(resolve(root, '.claude-plugin/plugin.json'), 'utf8'));
  assert.equal(claude.name, codex.name);
  assert.equal(claude.version, codex.version);
  assert.equal(codex.skills, './skills/');
  assert.ok(codex.interface.displayName);
  assert.equal(claude.interface, undefined);
});

test('tree hashing excludes local caches from reproducible bundle manifests', () => {
  const root = mkdtempSync(resolve(tmpdir(), 'ai4s-bundle-hash-'));
  try {
    writeFileSync(resolve(root, 'tracked.txt'), 'stable content\n');
    const baseline = treeHash(root);
    mkdirSync(resolve(root, '.ruff_cache'));
    writeFileSync(resolve(root, '.ruff_cache', 'state'), 'machine-local state\n');
    mkdirSync(resolve(root, '.venv'));
    writeFileSync(resolve(root, '.venv', 'marker'), 'environment state\n');
    assert.equal(treeHash(root), baseline);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('repository root exposes a claude marketplace listing this plugin', () => {
  const marketplace = JSON.parse(readFileSync(resolve(repoRoot, '.claude-plugin/marketplace.json'), 'utf8'));
  const meta = JSON.parse(readFileSync(resolve(root, 'plugin-meta.json'), 'utf8'));
  assert.equal(typeof marketplace.name, 'string');
  const entry = marketplace.plugins.find((p) => p.name === meta.name);
  assert.ok(entry, 'plugin missing from marketplace');
  assert.equal(entry.source, `./plugins/${meta.name}`);
  assert.ok(existsSync(resolve(repoRoot, entry.source, '.claude-plugin/plugin.json')));
});

test('runtime contract and Python lock are present', () => {
  const contract = JSON.parse(readFileSync(resolve(root, 'runtime-contract.json'), 'utf8'));
  assert.equal(contract.artifact_type, 'molecular_modeling_runtime_contract');
  assert.equal(contract.python.lockfile, 'uv.lock');
  assert.equal(existsSync(resolve(root, 'pyproject.toml')), true);
  assert.equal(existsSync(resolve(root, 'uv.lock')), true);
});

test('repository CI runs the locked CPU-only suite', () => {
  const workflow = readFileSync(resolve(repoRoot, '.github/workflows/molecular-modeling-workbench-ci.yml'), 'utf8');
  const meta = JSON.parse(readFileSync(resolve(root, 'plugin-meta.json'), 'utf8'));
  assert.match(workflow, new RegExp(`working-directory: plugins/${meta.name}`));
  assert.match(workflow, /npm run check/);
  assert.match(workflow, /npm test/);
  assert.match(workflow, /contents: read/);
});

test('test runner is platform-neutral and preserves the locked Python contract', () => {
  const pkg = JSON.parse(readFileSync(resolve(root, 'package.json'), 'utf8'));
  assert.equal(pkg.scripts.test, 'node scripts/run-tests.mjs');
  const runner = readFileSync(resolve(root, 'scripts/run-tests.mjs'), 'utf8');
  assert.match(runner, /--locked/);
  assert.match(runner, /spawnSync/);
  assert.doesNotMatch(runner, /bash -lc|PYTHONPYCACHEPREFIX=.*&&/);
});
