import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import type { AuthInfo } from '@modelcontextprotocol/sdk/server/auth/types.js';
import type { ZoteusConfig } from './config.js';
import { createLogger, type Logger } from './lib/logger.js';
import { RateLimitedFetcher } from './api/http.js';
import { WebApiClient } from './api/web-client.js';
import { LocalApiClient } from './api/local-client.js';
import { probeCapabilities } from './router/capabilities.js';
import { LibraryRouter } from './router/library-router.js';
import { SchemaService } from './schema/schema-service.js';
import { join } from 'node:path';
import { StyleResolver } from './features/citation/styles.js';
import { TranslationServerClient } from './features/citation/translation-server.js';
import { SearchIndex } from './features/search/index-manager.js';
import { createEmbeddingProvider } from './features/search/embeddings.js';
import { loadIndex, saveIndex } from './features/search/persistence.js';
import { ScholarGraph } from './features/scholar/graph.js';
import { registerAllTools, type ToolContext, type ToolDefinition } from './registry/registry.js';
import { registerResources } from './resources/index.js';
import { registerPrompts } from './prompts/index.js';
import { tools } from './tools/index.js';

const VERSION = '0.1.0';

export interface ContextOverrides {
  /** Per-user Zotero API key (multi-tenant); defaults to config.apiKey. */
  apiKey?: string;
  /** Per-user Zotero userID; scopes the search index file and is the cache key. */
  zoteroUserId?: number;
}

/**
 * Tools exposed for this config: read-only mode hides mutating tools (plus zotero_index,
 * which only touches local index files). Mirrors the M10 selection.
 */
export const WORKBENCH_TOOL_NAMES = new Set([
  'zotero_whoami',
  'zotero_search_items',
  'zotero_get_item',
  'zotero_get_fulltext',
  'zotero_fulltext_context',
  'zotero_apply_fulltext_handoff',
  'zotero_apply_import_plan',
  'zotero_apply_metrics_plan',
  'zotero_apply_citation_plan',
  'zotero_find_duplicates',
  'zotero_semantic_tag_context',
  'zotero_apply_semantic_tags',
  'zotero_cleanup_auto_tags',
  'zotero_semantic_tag_vocabulary',
  'zotero_sync_literature_project',
  'zotero_ai_summary_context',
  'zotero_apply_ai_summaries',
]);

export function selectActiveTools(config: ZoteusConfig): ToolDefinition[] {
  const profiled = config.toolProfile === 'workbench'
    ? tools.filter((tool) => WORKBENCH_TOOL_NAMES.has(tool.name))
    : tools;
  return config.readOnly
    ? profiled.filter((t) => t.annotations?.readOnlyHint === true || t.name === 'zotero_index')
    : profiled;
}

/**
 * Build the (expensive) per-context state: Zotero clients, capability probe, router,
 * schema, search index, etc. With no overrides this is the operator/shared context
 * (identical to M10). With a per-user apiKey it is that tenant's context.
 */
export async function buildContext(config: ZoteusConfig, overrides: ContextOverrides = {}): Promise<ToolContext> {
  const logger = createLogger(config.logLevel, config.logFormat);
  const apiKey = overrides.apiKey ?? config.apiKey;
  const perUser = overrides.apiKey !== undefined;
  const fetcher = new RateLimitedFetcher({ maxConcurrency: 4, logger });
  const web = new WebApiClient({ apiKey, fetcher, contactEmail: config.contactEmail, logger });
  // Per-user (hosted) contexts never touch the operator's desktop local API.
  const local = !perUser && config.local !== 'off' ? new LocalApiClient({ port: config.localPort, fetcher }) : undefined;

  const capabilities = await probeCapabilities(config, { web, local, logger });
  const router = new LibraryRouter({ config, capabilities, web, local });
  const schema = new SchemaService({ web });
  const styles = new StyleResolver();
  const translation = new TranslationServerClient(config.translationServerUrl, fetcher);
  const search = new SearchIndex({ embedder: createEmbeddingProvider(config, logger), logger });

  const searchIndexPath = join(
    config.dataDir,
    overrides.zoteroUserId !== undefined ? `search-index-${overrides.zoteroUserId}.json` : 'search-index.json',
  );
  await loadIndex(search, searchIndexPath).catch(() => false);
  const scholar = new ScholarGraph({ fetcher, mailto: config.contactEmail });

  const ctx: ToolContext = {
    config,
    capabilities,
    router,
    schema,
    web,
    local,
    styles,
    translation,
    search,
    scholar,
    logger,
    searchIndexPath,
  };
  ctx.toolCatalog = selectActiveTools(config).map((t) => ({
    name: t.name,
    title: t.title,
    description: t.description,
    deferLoading: t.deferLoading,
  }));
  return ctx;
}

/** Create a fresh McpServer bound to a (possibly per-user) ToolContext. */
export function createServer(ctx: ToolContext): McpServer {
  const server = new McpServer(
    { name: 'literature-zotero-mcp', version: VERSION },
    {
      capabilities: {
        tools: { listChanged: true },
        resources: { listChanged: true },
        prompts: { listChanged: true },
      },
      instructions:
        'Literature Zotero MCP exposes your Zotero library for auditable evidence workflows. Call zotero_whoami first to resolve identity. Prefer zotero_search_items for discovery, zotero_get_item for full records, and zotero_find_duplicates for read-only batch duplicate detection. Apply standalone import and existing-collection metrics plans only after their explicit review gates. The low-risk project-sync path may automatically apply available EasyScholar metrics for new create/reuse actions while preserving user Extra and unrelated tags. For Agent tags, call zotero_semantic_tag_context before zotero_apply_semantic_tags; the latter is an explicitly user-enabled automatic workflow that writes only AI4S:Semantic tags and optionally removes Zotero automatic tags while saving a plan and receipt. Generate AI Summary metadata only after an explicit user request: call zotero_ai_summary_context, write one Chinese sentence by default using only each returned title and abstract, then call zotero_apply_ai_summaries; never run this during import, project sync, metrics, tags, or report updates. Call tools sequentially rather than in large parallel batches — Zotero rate-limits, and parallel or very long calls can time out.',
    },
  );
  registerAllTools(server, selectActiveTools(ctx.config), ctx);
  registerResources(server, ctx);
  registerPrompts(server);
  return server;
}

export interface BuiltServer {
  server: McpServer;
  ctx: ToolContext;
  /**
   * Create a fresh McpServer sharing the same (expensive) ToolContext. Used by the
   * HTTP transport to give each MCP session its own server/transport pair — a single
   * McpServer/transport cannot be reused across sessions (it rejects a second
   * `initialize` with "Server already initialized").
   */
  createServer: () => McpServer;
}

/** Operator/shared server (stdio + the no-auth HTTP path). Preserves the M10 signature. */
export async function buildServer(config: ZoteusConfig): Promise<BuiltServer> {
  const ctx = await buildContext(config);
  if (config.readOnly || config.toolProfile !== 'full') {
    ctx.logger.info(
      `Tool profile ${config.toolProfile}${config.readOnly ? ' (read-only)' : ''}: exposing ${selectActiveTools(config).length}/${tools.length} tools.`,
    );
  }
  return { server: createServer(ctx), ctx, createServer: () => createServer(ctx) };
}

/**
 * Resolves a ToolContext per authenticated user (keyed by zoteroUserId), caching the
 * expensive build. Sessions without a per-user Zotero key (passcode/stdio/no-auth) fall
 * back to the operator context. Eviction only drops the cache entry; live sessions keep
 * the ctx they already closed over.
 */
export class ContextCache {
  private readonly entries = new Map<number, { ctx: ToolContext; lastUsed: number }>();
  private order = 0;

  constructor(
    private readonly config: ZoteusConfig,
    private readonly operatorCtx: ToolContext,
    private readonly maxEntries = 50,
  ) {}

  async resolve(authInfo?: AuthInfo): Promise<ToolContext> {
    const extra = authInfo?.extra as { zoteroKey?: string; zoteroUserId?: number; username?: string } | undefined;
    const zoteroKey = extra?.zoteroKey;
    const zoteroUserId = extra?.zoteroUserId;
    if (!zoteroKey || zoteroUserId === undefined) return this.operatorCtx;

    const hit = this.entries.get(zoteroUserId);
    if (hit) {
      hit.lastUsed = ++this.order;
      return hit.ctx;
    }
    const ctx = await buildContext(this.config, { apiKey: zoteroKey, zoteroUserId });
    this.entries.set(zoteroUserId, { ctx, lastUsed: ++this.order });
    this.evictIfNeeded();
    return ctx;
  }

  /** Persist every live context's search index (operator + per-user). Best-effort. */
  async flushIndexes(): Promise<void> {
    const ctxs = [this.operatorCtx, ...[...this.entries.values()].map((e) => e.ctx)];
    await Promise.allSettled(ctxs.map((c) => saveIndex(c.search, c.searchIndexPath)));
  }

  private evictIfNeeded(): void {
    while (this.entries.size > this.maxEntries) {
      let oldestKey: number | undefined;
      let oldest = Infinity;
      for (const [k, v] of this.entries) {
        if (v.lastUsed < oldest) {
          oldest = v.lastUsed;
          oldestKey = k;
        }
      }
      if (oldestKey === undefined) break;
      this.entries.delete(oldestKey);
    }
  }
}

export type { Logger };
