#!/usr/bin/env node
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { FulltextBroker } from './broker.js';
import { loadConfig } from './config.js';
import { OaAdapter } from './providers/oa.js';
import { createServer } from './server.js';
import { FulltextStore } from './store.js';

async function main(): Promise<void> {
  const config = loadConfig();
  const adapter = new OaAdapter({ timeoutMs: config.httpTimeoutMs, maxBytes: config.maxPdfBytes });
  const broker = new FulltextBroker(new FulltextStore(config.dataDir, config.exchangeRoot), adapter);
  await broker.init();
  const server = createServer(broker);
  await server.connect(new StdioServerTransport());
}

main().catch((error) => {
  process.stderr.write(`[literature-fulltext-mcp] FATAL ${error instanceof Error ? error.stack : String(error)}\n`);
  process.exit(1);
});
