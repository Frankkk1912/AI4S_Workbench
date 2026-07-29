import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { relative, resolve } from 'node:path';
import test from 'node:test';
import { checkPluginAssembly } from '../scripts/assemble-plugin.mjs';
import { verifyPlugin } from '../scripts/verify-plugin.mjs';
const root = resolve(import.meta.dirname, '..');
test('plugin manifest is valid and bundle source is synchronized', () => {
  assert.equal(existsSync(resolve(root, '.codex-plugin/plugin.json')), true);
  assert.match(checkPluginAssembly(), /match all source skills/);
  assert.match(verifyPlugin(), /bundled skills verified/);
});

test('generated plugin logs are ignored before staging', () => {
  const repoRoot = resolve(root, '../..');
  const pluginPath = relative(repoRoot, root);
  const result = spawnSync('git', ['check-ignore', '-q', '--no-index', `${pluginPath}/example.log`], {
    cwd: repoRoot,
  });
  assert.equal(result.status, 0, result.stderr?.toString());
});

test('tracked plugin artifacts do not disclose the maintainer home path', () => {
  const repoRoot = resolve(root, '../..');
  const pluginPath = relative(repoRoot, root);
  const maintainerHomePath = '/home/' + 'frank/';
  const result = spawnSync('git', ['grep', '-n', maintainerHomePath, '--', pluginPath], {
    cwd: repoRoot,
    encoding: 'utf8',
  });
  assert.equal(result.status, 1, result.stdout || result.stderr);
});

test('governance, analysis, plotting, and geometry skills keep their public contracts', () => {
  const contracts = {
    'md-project-manager': [],
    'docking-project-manager': ['scripts/docking_project.py'],
    'md-trajectory-analysis': ['scripts/md_analyze_cli.py'],
    'md-simulation-plotting': ['scripts/md_plot_cli.py'],
    'molecular-geometry-common': ['scripts/pdb_geometry.py'],
  };
  for (const [skill, files] of Object.entries(contracts)) {
    const skillPath = resolve(root, 'skills', skill, 'SKILL.md');
    assert.equal(existsSync(skillPath), true, `${skill} SKILL.md is missing`);
    assert.match(readFileSync(skillPath, 'utf8'), /^---\nname: /, `${skill} needs skill metadata`);
    for (const file of files) assert.equal(existsSync(resolve(root, 'skills', skill, file)), true, `${skill}/${file} is missing`);
  }
});
