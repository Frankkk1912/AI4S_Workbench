#!/usr/bin/env node
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const runtimeDir = resolve(scriptDir, '..', 'runtime');
const entry = resolve(runtimeDir, 'dist', 'index.js');
if (!existsSync(entry)) {
  throw new Error('Missing runtime/dist/index.js. Run the bootstrap script first.');
}

const { Client } = await import(pathToFileURL(resolve(runtimeDir, 'node_modules/@modelcontextprotocol/sdk/dist/esm/client/index.js')).href);
const { StdioClientTransport } = await import(pathToFileURL(resolve(runtimeDir, 'node_modules/@modelcontextprotocol/sdk/dist/esm/client/stdio.js')).href);
const transport = new StdioClientTransport({
  command: process.execPath,
  args: [entry],
  cwd: runtimeDir,
  env: {
    ...process.env,
    LITERATURE_ZOTERO_MCP_TOOL_PROFILE: 'workbench',
    ZOTEUS_LOCAL: 'off',
    ZOTEUS_EMBEDDINGS: 'off',
  },
});
const client = new Client({ name: 'ai4s-literature-workbench-verify', version: '0.1.0' });
await client.connect(transport);
const { tools } = await client.listTools();
await client.close();

const expected = [
  'zotero_ai_summary_context',
  'zotero_apply_ai_summaries',
  'zotero_apply_citation_plan',
  'zotero_apply_fulltext_handoff',
  'zotero_apply_import_plan',
  'zotero_apply_metrics_plan',
  'zotero_apply_semantic_tags',
  'zotero_cleanup_auto_tags',
  'zotero_find_duplicates',
  'zotero_fulltext_context',
  'zotero_get_fulltext',
  'zotero_get_item',
  'zotero_search_items',
  'zotero_semantic_tag_context',
  'zotero_semantic_tag_vocabulary',
  'zotero_sync_literature_project',
  'zotero_whoami',
];
const actual = tools.map((tool) => tool.name).sort();
if (JSON.stringify(actual) !== JSON.stringify(expected)) {
  throw new Error(`Unexpected workbench MCP tools: ${actual.join(', ')}`);
}
process.stdout.write(`Runtime MCP verified with ${actual.length} workbench tools.\n`);
