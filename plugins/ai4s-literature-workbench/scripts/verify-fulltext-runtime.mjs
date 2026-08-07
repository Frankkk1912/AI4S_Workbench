#!/usr/bin/env node
import { existsSync } from 'node:fs';
import { mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const runtimeDir = resolve(scriptDir, '..', 'fulltext-runtime');
const entry = resolve(runtimeDir, 'dist', 'index.js');
if (!existsSync(entry)) throw new Error('Missing fulltext-runtime/dist/index.js. Run its bootstrap step first.');

const { Client } = await import(pathToFileURL(resolve(runtimeDir, 'node_modules/@modelcontextprotocol/sdk/dist/esm/client/index.js')).href);
const { StdioClientTransport } = await import(pathToFileURL(resolve(runtimeDir, 'node_modules/@modelcontextprotocol/sdk/dist/esm/client/stdio.js')).href);
const privateRoot = await mkdtemp(resolve(tmpdir(), 'literature-fulltext-verify-'));
const transport = new StdioClientTransport({
  command: process.execPath, args: [entry], cwd: runtimeDir,
  env: {
    ...process.env,
    LITERATURE_FULLTEXT_DATA_DIR: resolve(privateRoot, 'data'),
    LITERATURE_FULLTEXT_EXCHANGE_ROOT: resolve(privateRoot, 'exchange'),
  },
});
const client = new Client({ name: 'literature-fulltext-runtime-verifier', version: '0.1.0' });
await client.connect(transport);
const listed = await client.listTools();
const expected = [
  'fulltext_access_status',
  'fulltext_capabilities',
  'fulltext_fetch_submit',
  'fulltext_job_cancel',
  'fulltext_job_status',
  'fulltext_session_open',
];
const actual = listed.tools.map((tool) => tool.name).sort();
if (JSON.stringify(actual) !== JSON.stringify(expected)) throw new Error(`Unexpected Fulltext MCP tools: ${actual.join(', ')}`);
for (const name of ['fulltext_capabilities', 'fulltext_access_status']) {
  const result = await client.callTool({ name, arguments: {} });
  if (result.isError) throw new Error(`${name} returned an error.`);
}
await client.close();
process.stdout.write(`Fulltext MCP verified with ${actual.length} tools.\n`);
