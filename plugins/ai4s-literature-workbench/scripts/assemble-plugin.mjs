#!/usr/bin/env node
import { createHash } from 'node:crypto';
import {
  cpSync,
  existsSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { execFileSync } from 'node:child_process';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const command = process.argv[2];
if (!['sync', 'check'].includes(command)) {
  throw new Error('Usage: node scripts/assemble-plugin.mjs <sync|check>');
}

const scriptDir = dirname(fileURLToPath(import.meta.url));
const pluginRoot = resolve(scriptDir, '..');
const repoRoot = resolve(process.env.AI4S_REPO_ROOT || resolve(pluginRoot, '../..'));
const bundles = [
  ['skills/literature-research', 'skills/literature-research'],
  ['skills/literature-manager', 'skills/literature-manager'],
  ['skills/literature-writing', 'skills/literature-writing'],
  ['literature-zotero-mcp', 'runtime'],
  ['literature-fulltext-mcp', 'fulltext-runtime'],
];

function excluded(path) {
  const name = path.split(/[\\/]/).at(-1);
  return (
    name === '.git' ||
    name === 'node_modules' ||
    name === 'dist' ||
    name === 'data' ||
    name === 'coverage' ||
    name === '.pytest_cache' ||
    name === '__pycache__' ||
    name === '.DS_Store' ||
    name === 'original-draft.md' ||
    name.endsWith('.pyc') ||
    (name.startsWith('.env') && name !== '.env.example')
  );
}

const runtimeSource = resolve(repoRoot, 'literature-zotero-mcp');
const fulltextRuntimeSource = resolve(repoRoot, 'literature-fulltext-mcp');
const runtimeTopLevel = new Set([
  '.env.example',
  'LICENSE',
  'THIRD_PARTY_NOTICES.md',
  'licenses',
  'package-lock.json',
  'package.json',
  'scripts',
  'src',
  'tsconfig.json',
]);

function bundleRuntime() {
  const esbuildCandidates = [
    resolve(runtimeSource, 'node_modules', 'esbuild', 'bin', 'esbuild'),
    resolve(runtimeSource, 'node_modules', 'esbuild', 'bin', 'esbuild.exe'),
  ];
  const esbuild = esbuildCandidates.find((candidate) => existsSync(candidate));
  if (!esbuild) {
    throw new Error('Missing literature-zotero-mcp esbuild dependency; run npm install in literature-zotero-mcp first.');
  }
  const output = resolve(pluginRoot, 'runtime', 'dist', 'index.js');
  const esbuildArgs = [
    resolve(runtimeSource, 'src', 'index.ts'),
    '--bundle',
    '--platform=node',
    '--format=esm',
    '--target=node20',
    // Express and a few transitive dependencies retain CommonJS dynamic
    // requires when bundled. Keep ESM so import.meta.url continues to work
    // for private env-file discovery, while providing Node's real require.
    '--banner:js=import { createRequire } from "node:module"; const require = createRequire(import.meta.url);',
    `--outfile=${output}`,
  ];
  // esbuild's postinstall normally replaces bin/esbuild with the platform
  // binary. Execute it directly in that case; only route through Node when
  // the entry point is still the JavaScript shim.
  const isNativeBinary = readFileSync(esbuild).subarray(0, 256).includes(0);
  if (isNativeBinary) {
    execFileSync(esbuild, esbuildArgs, { stdio: 'inherit' });
  } else {
    execFileSync(process.execPath, [esbuild, ...esbuildArgs], { stdio: 'inherit' });
  }
}

function shouldCopy(source) {
  if (excluded(source)) return false;
  for (const sourceRoot of [runtimeSource, fulltextRuntimeSource]) {
    const runtimeRelative = relative(sourceRoot, source);
    if (!runtimeRelative) return true;
    if (!runtimeRelative.startsWith('..')) {
      const topLevel = runtimeRelative.split(/[\\/]/)[0];
      return runtimeTopLevel.has(topLevel);
    }
  }
  return true;
}

function treeHash(root) {
  if (!existsSync(root)) return null;
  const hash = createHash('sha256');
  function visit(path) {
    const info = statSync(path);
    if (info.isDirectory()) {
      for (const entry of readdirSync(path).sort()) {
        const child = resolve(path, entry);
        // runtime/dist is a generated, self-contained MCP entry point. Its
        // source equivalence is verified through the surrounding runtime tree;
        // keeping it out of this hash avoids comparing generated output with
        // the source package's ignored dist directory.
        if (relative(root, child).replaceAll('\\', '/') === 'dist') continue;
        if (shouldCopy(child)) visit(child);
      }
      return;
    }
    hash.update(relative(root, path).replaceAll('\\', '/'));
    hash.update('\0');
    hash.update(readFileSync(path));
    hash.update('\0');
  }
  visit(root);
  return hash.digest('hex');
}

function sourcePath(source) {
  return resolve(repoRoot, source);
}

function bundlePath(destination) {
  return resolve(pluginRoot, destination);
}

if (command === 'sync') {
  for (const [source, destination] of bundles) {
    const from = sourcePath(source);
    const to = bundlePath(destination);
    if (!existsSync(from)) throw new Error(`Missing source directory: ${from}`);
    rmSync(to, { recursive: true, force: true });
    cpSync(from, to, { recursive: true, filter: shouldCopy });
    if (source === 'literature-zotero-mcp') bundleRuntime();
  }
  const manifest = {
    generated_at: new Date().toISOString(),
    source_root: (relative(pluginRoot, repoRoot) || '.').replaceAll('\\', '/'),
    bundles: bundles.map(([source, destination]) => ({
      source,
      destination,
      sha256: treeHash(sourcePath(source)),
    })),
  };
  writeFileSync(resolve(pluginRoot, 'bundle-manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
  process.stdout.write(`Synced ${bundles.length} plugin bundles from ${repoRoot}\n`);
} else {
  const drift = [];
  for (const [source, destination] of bundles) {
    const expected = treeHash(sourcePath(source));
    const actual = treeHash(bundlePath(destination));
    if (expected !== actual) drift.push(`${source} -> ${destination}`);
  }
  if (!existsSync(resolve(pluginRoot, 'runtime', 'dist', 'index.js'))) {
    drift.push('literature-zotero-mcp bundled runtime entry point is missing');
  }
  if (drift.length) {
    throw new Error(`Bundled plugin content differs from source-of-truth:\n${drift.join('\n')}`);
  }
  process.stdout.write('Plugin bundle matches all source directories.\n');
}
