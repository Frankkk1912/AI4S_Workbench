#!/usr/bin/env node
import { createHash } from 'node:crypto';
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { basename, dirname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const pluginRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repoRoot = resolve(process.env.AI4S_REPO_ROOT || resolve(pluginRoot, '../..'));
// Private development keeps skills at the repository root.  A public export is
// self-contained and keeps its editable sources alongside this plugin.
const skillSourceRoot = resolve(process.env.AI4S_SKILLS_ROOT || (existsSync(resolve(pluginRoot, 'source-skills')) ? resolve(pluginRoot, 'source-skills') : repoRoot));
const bundles = ['molecular-modeling-environment', 'molecular-geometry-common', 'docking-project-manager', 'docking-simulation-run', 'docking-complex-analysis', 'docking-to-md-handoff', 'docking-visualization', 'ligand-parameterization', 'md-project-manager', 'md-simulation-run', 'md-trajectory-analysis', 'md-simulation-plotting'].map((source) => [source, `skills/${source}`]);

function excluded(path) { const name = path.split(/[\\/]/).at(-1); return ['.git', 'node_modules', 'dist', 'data', 'coverage', '.pytest_cache', '__pycache__', '.ruff_cache', '.venv', '.DS_Store'].includes(name) || name.endsWith('.pyc'); }
export function treeHash(root) {
  if (!existsSync(root)) return null;
  const hash = createHash('sha256');
  function visit(path) { const info = statSync(path); if (info.isDirectory()) { for (const entry of readdirSync(path).sort()) { const child = resolve(path, entry); if (!excluded(child)) visit(child); } return; } hash.update(relative(root, path).replaceAll('\\', '/')); hash.update('\0'); hash.update(readFileSync(path)); hash.update('\0'); }
  visit(root); return hash.digest('hex');
}

const metaPath = resolve(pluginRoot, 'plugin-meta.json');
if (!existsSync(metaPath)) throw new Error('Missing plugin-meta.json.');
const meta = JSON.parse(readFileSync(metaPath, 'utf8'));
for (const key of ['name', 'version', 'description', 'author', 'license', 'codex', 'marketplace']) if (meta[key] === undefined) throw new Error(`plugin-meta.json missing required key: ${key}`);
if (!/^\d+\.\d+\.\d+$/.test(meta.version)) throw new Error(`plugin-meta.json version must be plain semver (got ${meta.version}).`);
if (meta.name !== basename(pluginRoot)) throw new Error(`plugin-meta.json name must match the bundle directory: ${meta.name} != ${basename(pluginRoot)}`);

function baseManifest() { return { name: meta.name, version: meta.version, description: meta.description, author: meta.author, homepage: meta.homepage, repository: meta.repository, license: meta.license, keywords: meta.keywords }; }
const generated = [
  [resolve(pluginRoot, '.codex-plugin/plugin.json'), () => ({ ...baseManifest(), skills: './skills/', interface: meta.codex.interface })],
  [resolve(pluginRoot, '.claude-plugin/plugin.json'), baseManifest],
  [resolve(repoRoot, '.claude-plugin/marketplace.json'), () => ({ name: meta.marketplace.name, owner: meta.marketplace.owner, plugins: [{ name: meta.name, source: `./plugins/${meta.name}`, description: meta.description }] })],
];
function renderManifest(render) { return `${JSON.stringify(render(), null, 2)}\n`; }
function semanticJsonEquals(path, expected) {
  if (!existsSync(path)) return false;
  try { return JSON.stringify(JSON.parse(readFileSync(path, 'utf8'))) === JSON.stringify(JSON.parse(expected)); }
  catch { return false; }
}
function bundleEntries() { return bundles.map(([source, destination]) => ({ source, destination, sha256: treeHash(resolve(skillSourceRoot, source)) })); }
function bundleManifest() {
  const entries = bundleEntries();
  const sourceRoot = relative(pluginRoot, skillSourceRoot) || '.';
  const manifestPath = resolve(pluginRoot, 'bundle-manifest.json');
  let generatedAt = new Date().toISOString();
  if (existsSync(manifestPath)) {
    try {
      const current = JSON.parse(readFileSync(manifestPath, 'utf8'));
      if (current.schema_version === '1.0' && current.source_root === sourceRoot && JSON.stringify(current.bundles) === JSON.stringify(entries) && typeof current.generated_at === 'string') generatedAt = current.generated_at;
    } catch { /* Invalid generated output is replaced during sync. */ }
  }
  return { schema_version: '1.0', generated_at: generatedAt, source_root: sourceRoot, bundles: entries };
}

export function syncPlugin() {
  for (const [source, destination] of bundles) { const from = resolve(skillSourceRoot, source); const to = resolve(pluginRoot, destination); if (!existsSync(from)) throw new Error(`Missing source skill: ${from}`); rmSync(to, { recursive: true, force: true }); cpSync(from, to, { recursive: true, filter: (path) => !excluded(path) }); }
  for (const [path, render] of generated) {
    const content = renderManifest(render);
    if (semanticJsonEquals(path, content)) continue;
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, content);
  }
  writeFileSync(resolve(pluginRoot, 'bundle-manifest.json'), `${JSON.stringify(bundleManifest(), null, 2)}\n`);
  return `Synced ${bundles.length} source skills and ${generated.length} agent manifests.`;
}

export function checkPluginAssembly() {
  const drift = bundles.filter(([source, destination]) => treeHash(resolve(skillSourceRoot, source)) !== treeHash(resolve(pluginRoot, destination))).map(([source, destination]) => `${source} -> ${destination}`);
  for (const [path, render] of generated) if (!semanticJsonEquals(path, renderManifest(render))) drift.push(`manifest:${relative(pluginRoot, path)}`);
  if (drift.length) throw new Error(`Bundled plugin content differs from source-of-truth:\n${drift.join('\n')}`);
  return 'Plugin bundle and agent manifests match all source skills.';
}

const isMain = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  const command = process.argv[2];
  if (!['sync', 'check'].includes(command)) throw new Error('Usage: node scripts/assemble-plugin.mjs <sync|check>');
  process.stdout.write(`${command === 'sync' ? syncPlugin() : checkPluginAssembly()}\n`);
}
