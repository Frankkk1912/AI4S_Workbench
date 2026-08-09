import { z } from 'zod';
import type { ToolDefinition } from '../registry/registry.js';
import { ok, requireCloudLibrary } from '../registry/registry.js';
import { executeSemanticTags } from '../features/semantic-tags/apply.js';

const tagProposal = z.object({
  canonical: z.string().min(1).max(80),
  dimension: z.enum(['topic', 'entity', 'method', 'mechanism']),
  decision: z.enum(['reuse', 'new']),
  vocabulary_id: z.string().optional(),
  matched_alias: z.string().optional(),
  aliases: z.array(z.string()).max(20).optional(),
  description: z.string().max(240).optional(),
});

const applySemanticTags: ToolDefinition = {
  name: 'zotero_apply_semantic_tags',
  title: 'Apply Agent semantic tags',
  description:
    'Automatically apply validated English semantic-tag recommendations. Replaces only AI4S:Semantic:* on each processed bibliographic item, optionally removes Zotero automatic tags (type 1), preserves every manual/Article Type/Priority/JCR/CAS tag, updates the library-scoped vocabulary, and saves an internal hashed plan plus receipt. Requires versions and vocabulary revision from zotero_semantic_tag_context.',
  inputSchema: {
    scope: z.object({ type: z.enum(['items', 'collection']), collection_key: z.string().regex(/^[A-Z0-9]{8}$/).optional() }),
    vocabulary_revision: z.number().int().min(0),
    cleanup_auto_tags: z.boolean().optional().describe('Remove Zotero automatic tags from processed items (default true).'),
    items: z.array(z.object({
      item_key: z.string().regex(/^[A-Z0-9]{8}$/),
      expected_version: z.number().int().min(0),
      evidence_depth: z.enum(['title-abstract', 'metadata-only']),
      tags: z.array(tagProposal).max(4),
    })).min(1).max(50),
    library_type: z.enum(['user', 'group']).optional(),
    library_id: z.number().int().optional(),
  },
  annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true },
  handler: async (args, ctx) => {
    if (args.scope.type === 'collection' && !args.scope.collection_key) {
      throw new Error('scope.collection_key is required for collection scope');
    }
    if (args.scope.type === 'items' && args.scope.collection_key) {
      throw new Error('scope.collection_key is only valid for collection scope');
    }
    const library = requireCloudLibrary(ctx, args);
    const result = await executeSemanticTags(ctx, library, {
      scope: args.scope, vocabulary_revision: args.vocabulary_revision,
      cleanup_auto_tags: args.cleanup_auto_tags ?? true, items: args.items,
    });
    const summary = result.summary as Record<string, number>;
    return ok(result, `Semantic tagging ${result.status}: updated=${summary.updated ?? 0}, unchanged=${summary.unchanged ?? 0}, conflicts=${summary.conflicted ?? 0}, failed=${summary.failed ?? 0}.`);
  },
};

export default applySemanticTags;
