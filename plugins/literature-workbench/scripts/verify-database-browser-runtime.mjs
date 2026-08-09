#!/usr/bin/env node
import { existsSync } from 'node:fs';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const runtimeDir = resolve(scriptDir, '..', 'database-browser-runtime');
const entry = resolve(runtimeDir, 'dist', 'index.js');
if (!existsSync(entry)) {
  throw new Error('Missing database-browser-runtime/dist/index.js. Run its bootstrap step first.');
}

const { Client } = await import(pathToFileURL(resolve(runtimeDir, 'node_modules/@modelcontextprotocol/sdk/dist/esm/client/index.js')).href);
const { StdioClientTransport } = await import(pathToFileURL(resolve(runtimeDir, 'node_modules/@modelcontextprotocol/sdk/dist/esm/client/stdio.js')).href);
const dataDir = await mkdtemp(resolve(tmpdir(), 'literature-database-browser-verify-'));
const transport = new StdioClientTransport({
  command: process.execPath,
  args: [entry],
  cwd: runtimeDir,
  env: { ...process.env, LITERATURE_DATABASE_BROWSER_DATA_DIR: dataDir },
});
const client = new Client({ name: 'database-browser-runtime-verifier', version: '0.1.0' });
await client.connect(transport);
const listed = await client.listTools();

const expected = [
  'database_browser_capabilities',
  'database_export_submit',
  'database_job_cancel',
  'database_search_status',
  'database_search_submit',
  'database_session_open',
  'database_session_status',
];
const actual = listed.tools.map((tool) => tool.name).sort();
if (JSON.stringify(actual) !== JSON.stringify(expected)) {
  throw new Error(`Unexpected database browser MCP tools: ${actual.join(', ')}`);
}
const capabilities = await client.callTool({ name: 'database_browser_capabilities', arguments: {} });
if (capabilities.isError) throw new Error('Database browser capability tool returned an error.');
const session = await client.callTool({ name: 'database_session_status', arguments: {} });
if (session.isError) throw new Error('Database browser session-status tool returned an error.');
await client.close();
process.stdout.write(`Database browser MCP verified with ${actual.length} tools.\n`);
