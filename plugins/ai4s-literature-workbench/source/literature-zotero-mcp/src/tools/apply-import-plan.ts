import { z } from 'zod';
import type { ToolDefinition, ToolHandlerResult } from '../registry/registry.js';
import { ok, requireCloudLibrary } from '../registry/registry.js';
import { readImportPlan } from '../features/import-plan/contract.js';
import { applyImportPlan, dryRunImportPlan } from '../features/import-plan/apply.js';

function err(text: string): ToolHandlerResult {
  return { content: [{ type: 'text', text }], isError: true };
}

const applyImportPlanTool: ToolDefinition = {
  name: 'zotero_apply_import_plan',
  title: 'Apply an approved Zotero import plan',
  description:
    'Validate and dry-run or apply a file-based zotero_import_plan.json. The tool resolves or creates one exact project collection, creates new items, reuses uniquely matched items, preserves unrelated tags/collections, and saves an idempotent zotero_import_receipt.json. Apply mode requires the exact approved plan hash and a Zotero Web API key. It never writes through the Local API and never merges, trashes, or deletes items.',
  inputSchema: {
    plan_path: z.string().min(1).describe('Absolute path to zotero_import_plan.json.'),
    mode: z.enum(['dry_run', 'apply']),
    receipt_path: z.string().min(1).optional().describe('Required for apply; ignored by dry-run.'),
    confirm_plan_hash: z.string().regex(/^sha256:[0-9a-f]{64}$/).optional().describe('Required for apply and must match the plan.'),
  },
  annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: true },
  handler: async (args, ctx) => {
    const plan = await readImportPlan(args.plan_path);
    const lib = requireCloudLibrary(ctx, {
      library_type: plan.target.library_type,
      library_id: plan.target.library_id,
    });
    if (args.mode === 'dry_run') {
      const summary = await dryRunImportPlan(ctx, plan, lib);
      return ok(summary as unknown as Record<string, unknown>, `Dry-run ${summary.status}: ${plan.plan_hash.slice(0, 19)}.`);
    }
    if (!ctx.web.hasKey) return err('Apply mode requires a Zotero Web API key; the desktop Local API is read-only.');
    if (!args.receipt_path) return err('`receipt_path` is required for apply mode.');
    if (!args.confirm_plan_hash) return err('`confirm_plan_hash` is required for apply mode.');
    if (args.confirm_plan_hash !== plan.plan_hash) return err('Confirmed plan hash does not match the plan file; no writes were attempted.');
    const summary = await applyImportPlan(ctx, plan, lib, args.receipt_path);
    return ok(
      summary as unknown as Record<string, unknown>,
      `Import ${summary.status}: receipt ${args.receipt_path}; created=${summary.summary.created ?? 0}, reused=${summary.summary.reused ?? 0}.`,
    );
  },
};

export default applyImportPlanTool;
