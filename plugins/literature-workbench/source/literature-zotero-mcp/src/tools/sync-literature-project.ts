import { z } from 'zod';
import type { ToolDefinition } from '../registry/registry.js';
import { ok, requireCloudLibrary } from '../registry/registry.js';
import { syncLiteratureProject } from '../features/project-sync/sync.js';

const syncLiteratureProjectTool: ToolDefinition = {
  name: 'zotero_sync_literature_project',
  title: 'Sync a literature project to Zotero',
  description: 'Synchronize one literature-research report and its selected ranked evidence into a persistent Zotero collection. Normal exact-ID creates/reuses, EasyScholar-enriched metrics, and an AI4S-owned Current Report Note are applied idempotently without user-facing plan files. IF/5-Year IF/JCR/CAS render from versioned Extra; current JCR/CAS also synchronize as native tags. Missing metrics do not block bibliographic import.',
  inputSchema: {
    project_slug: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/),
    collection_name: z.string().min(1).optional().describe('Required on first sync; later runs reuse the private project binding.'),
    search_date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
    report_path: z.string().min(1).describe('Absolute path to the finalized report.md.'),
    evidence_path: z.string().min(1).describe('Absolute path to ranked_all.json.'),
    selection_path: z.string().min(1).optional().describe('Optional compact selection JSON; otherwise all ranked records are selected.'),
    priority_recommendations_path: z.string().min(1).optional().describe('Optional report-stage priority_recommendations.json sidecar.'),
    confirm_review_id: z.string().regex(/^[0-9a-f]{64}$/).optional().describe('Only used after explicit approval of a reported large-create review.'),
    library_type: z.enum(['user', 'group']).optional(), library_id: z.number().int().optional(),
  },
  annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: true },
  handler: async (args, ctx) => {
    const result = await syncLiteratureProject(ctx, requireCloudLibrary(ctx, args), {
      projectSlug: args.project_slug, collectionName: args.collection_name, searchDate: args.search_date,
      reportPath: args.report_path, evidencePath: args.evidence_path, selectionPath: args.selection_path,
      priorityRecommendationsPath: args.priority_recommendations_path, confirmReviewId: args.confirm_review_id,
    });
    const compact: Record<string, unknown> = {
      status: result.status, collection: result.collectionName, created: result.created, reused: result.reused,
      report: result.report, risks: result.risks, metrics_updated: result.metrics.updated,
      metrics_missing: result.metrics.missing, metrics_preprint_skipped: result.metrics.preprintsSkipped,
      display_metric_year: result.metrics.displayYear, metrics_status: result.metrics.status,
      ...(result.reviewId ? { review_id: result.reviewId } : {}),
    };
    const summary = result.status === 'complete'
      ? `Synced "${result.collectionName}": created=${result.created}, reused=${result.reused}, report=${result.report}, metrics=${result.metrics.updated}, missing=${result.metrics.missing}, preprints=${result.metrics.preprintsSkipped}, display_year=${result.metrics.displayYear}.`
      : `Sync needs review: ${result.risks.join(', ')}. Metrics available=${result.metrics.updated}, missing=${result.metrics.missing}, preprints=${result.metrics.preprintsSkipped}.`;
    return ok(compact, summary);
  },
};
export default syncLiteratureProjectTool;
