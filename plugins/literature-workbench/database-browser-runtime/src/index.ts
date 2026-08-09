#!/usr/bin/env node
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { WosPlaywrightAdapter } from './adapters/wos.js';
import { DatabaseBroker } from './broker.js';
import { loadConfig } from './config.js';
import { createServer } from './server.js';
import { JobStore } from './store.js';

async function main(): Promise<void> {
  const config = loadConfig();
  const adapter = new WosPlaywrightAdapter(config);
  const broker = new DatabaseBroker(new JobStore(config.dataDir), adapter);
  await broker.init();
  const server = createServer(broker);
  const transport = new StdioServerTransport();
  await server.connect(transport);

  const close = () => void adapter.close().catch(() => undefined);
  process.once('SIGINT', close);
  process.once('SIGTERM', close);
}

main().catch((error) => {
  process.stderr.write(`[literature-database-browser] FATAL ${error instanceof Error ? error.stack : String(error)}\n`);
  process.exit(1);
});
