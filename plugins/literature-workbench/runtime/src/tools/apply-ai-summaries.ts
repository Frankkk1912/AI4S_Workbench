import { z } from 'zod';
import type { ToolDefinition } from '../registry/registry.js';
import { ok, requireCloudLibrary } from '../registry/registry.js';
import { executeAiSummaries } from '../features/ai-summaries/apply.js';

const applyAiSummaries: ToolDefinition = {
  name: 'zotero_apply_ai_summaries',
  title: 'Apply one-sentence AI summaries',
  description:
    'Persist explicitly requested one-sentence summaries based only on title and abstract. Writes only a versioned AI4S-Summary block in Zotero Extra, preserves Abstract and every other field/tag/collection/Extra block, validates live input hashes and item versions, and saves an internal hashed plan plus receipt. Default language is Chinese. Use refresh only when the user explicitly asks to overwrite existing summaries.',
  inputSchema: {
    trigger: z.literal('explicit-user-request'),
    mode: z.enum(['missing', 'refresh']).optional(),
    items: z.array(z.object({
      item_key: z.string().regex(/^[A-Z0-9]{8}$/),
      expected_version: z.number().int().min(0),
      title_sha256: z.string().regex(/^[a-f0-9]{64}$/),
      abstract_sha256: z.string().regex(/^[a-f0-9]{64}$/),
      text: z.string().min(1).max(240),
      language: z.string().max(35).optional(),
    })).min(1).max(50),
    library_type: z.enum(['user', 'group']).optional(),
    library_id: z.number().int().optional(),
  },
  annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: true },
  handler: async (args, ctx) => {
    const library = requireCloudLibrary(ctx, args);
    const result = await executeAiSummaries(ctx, library, {
      trigger: args.trigger, mode: args.mode ?? 'missing',
      items: args.items.map((item: any) => ({ ...item, language: item.language ?? 'zh-CN' })),
    });
    const summary = result.summary as Record<string, number>;
    return ok(result, `AI Summary ${result.status}: created=${summary.created ?? 0}, refreshed=${summary.refreshed ?? 0}, unchanged=${summary.unchanged ?? 0}, stale=${summary.stale ?? 0}, skipped=${summary.skipped ?? 0}, conflicts=${summary.conflicted ?? 0}, failed=${summary.failed ?? 0}.`);
  },
};

export default applyAiSummaries;
