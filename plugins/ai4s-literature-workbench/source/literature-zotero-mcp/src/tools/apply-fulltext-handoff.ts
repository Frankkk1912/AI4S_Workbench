import { z } from 'zod';
import { executeFulltextHandoff } from '../features/fulltext/apply.js';
import type { ToolDefinition } from '../registry/registry.js';
import { ok, requireCloudLibrary } from '../registry/registry.js';

const applyFulltextHandoff: ToolDefinition = {
  name: 'zotero_apply_fulltext_handoff',
  title: 'Apply a verified Fulltext MCP handoff',
  description:
    'Add only verified main-article PDFs from a private, hashed Fulltext MCP handoff to their exact DOI-matched Zotero parents. This tool accepts no local file path, URL, MIME, password, or arbitrary parent key. It checks the handoff/artifact hashes, live parent DOI, and existing child PDFs; it saves a resumable receipt after attachment creation, bytes upload, registration, and verification. Existing file PDFs are skipped; ambiguity, replacement, deletion, or conflicts stop that record.',
  inputSchema: {
    handoff_id: z.string().regex(/^fth-[A-Za-z0-9-]{8,128}$/),
    handoff_hash: z.string().regex(/^sha256:[a-f0-9]{64}$/i),
    library_type: z.enum(['user', 'group']).optional(),
    library_id: z.number().int().nonnegative().optional(),
  },
  annotations: { readOnlyHint: false, idempotentHint: true, openWorldHint: false },
  handler: async (args, ctx) => {
    const library = requireCloudLibrary(ctx, args);
    const result = await executeFulltextHandoff(ctx, library, { handoffId: args.handoff_id, handoffHash: args.handoff_hash });
    return ok({ handoff_id: result.handoffId, ...result.summary }, `Fulltext handoff applied: attached=${result.summary.attached}, existing=${result.summary.skipped_existing}, conflicts=${result.summary.conflicts}, failed=${result.summary.failed}, pending=${result.summary.pending}.`);
  },
};

export default applyFulltextHandoff;
