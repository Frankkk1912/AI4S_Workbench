import { z } from 'zod';
import type { ToolDefinition } from '../registry/registry.js';
import { ok, requireCloudLibrary } from '../registry/registry.js';
import { cleanupAutomaticTags } from '../features/semantic-tags/cleanup.js';

const cleanupAutoTags: ToolDefinition = {
  name: 'zotero_cleanup_auto_tags',
  title: 'Clean Zotero automatic tags',
  description:
    'Explicitly remove only Zotero automatic tags (tag type 1) from a collection or library page. Manual tags and every AI4S namespace are preserved unless Zotero itself marked that tag automatic. Saves a hashed plan and receipt. Use max_items and next_start to process large scopes in bounded pages.',
  inputSchema: {
    scope_type: z.enum(['collection', 'library']),
    collection_key: z.string().regex(/^[A-Z0-9]{8}$/).optional(),
    max_items: z.number().int().min(1).max(1000).describe('Maximum items to process in this call.'),
    start: z.number().int().min(0).optional(),
    library_type: z.enum(['user', 'group']).optional(),
    library_id: z.number().int().optional(),
  },
  annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: true },
  handler: async (args, ctx) => {
    if (args.scope_type === 'collection' && !args.collection_key) throw new Error('collection_key is required for collection cleanup');
    if (args.scope_type === 'library' && args.collection_key) throw new Error('collection_key is only valid for collection cleanup');
    const library = requireCloudLibrary(ctx, args);
    const result = await cleanupAutomaticTags(ctx, library, {
      scope_type: args.scope_type, collection_key: args.collection_key,
      max_items: args.max_items, start: args.start ?? 0,
    });
    const summary = result.summary as Record<string, number>;
    return ok(result, `Automatic-tag cleanup ${result.status}: updated=${summary.updated ?? 0}, unchanged=${summary.unchanged ?? 0}, failed=${summary.failed ?? 0}.`);
  },
};

export default cleanupAutoTags;
