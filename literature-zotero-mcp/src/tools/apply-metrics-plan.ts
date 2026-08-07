import { z } from 'zod';
import { ok, requireCloudLibrary, type ToolDefinition } from '../registry/registry.js';
import { executeMetricsPlan, readMetricsPlan } from '../features/metrics-plan.js';

const applyMetricsPlan: ToolDefinition = {
  name: 'zotero_apply_metrics_plan', title: 'Dry-run or apply an approved Zotero metrics plan',
  description: 'Apply a reviewed IF/JCR/CAS metrics plan. It preserves non-AI4S Extra text and unrelated tags, replaces only the same metric year, and derives current JCR:/CAS: tags from the highest available metric year. Dry-run never writes; apply requires the exact plan hash, a receipt path, and Web API credentials.',
  inputSchema: { plan_path:z.string().min(1), mode:z.enum(['dry_run','apply']), confirm_plan_hash:z.string().optional(), receipt_path:z.string().optional(), library_type:z.enum(['user','group']).optional(), library_id:z.number().int().optional() },
  annotations: { readOnlyHint:false, idempotentHint:true, openWorldHint:true },
  handler: async (args, ctx) => {
    const plan = await readMetricsPlan(args.plan_path); const lib = requireCloudLibrary(ctx, args);
    if (lib.type !== plan.target.library_type || lib.id !== plan.target.library_id) throw new Error('Plan target does not match selected Zotero library');
    if (args.mode === 'apply') { if (!ctx.web.hasKey) throw new Error('A Zotero Web API key is required for apply'); if (args.confirm_plan_hash !== plan.plan_hash) throw new Error('Apply requires confirm_plan_hash exactly matching plan_hash'); if (!args.receipt_path) throw new Error('Apply requires receipt_path'); }
    const result = await executeMetricsPlan(ctx, plan, lib, args.mode, args.receipt_path);
    return ok(result, args.mode === 'dry_run' ? `Metrics dry run ${result.status}.` : `Metrics apply ${result.status}.`);
  },
};
export default applyMetricsPlan;
