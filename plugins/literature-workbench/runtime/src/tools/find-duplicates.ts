import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { z } from 'zod';
import type { LibraryRef } from '../api/web-client.js';
import { findDuplicateClusters } from '../features/duplicates/detector.js';
import type { ToolContext, ToolDefinition, ToolHandlerResult } from '../registry/registry.js';
import { ok } from '../registry/registry.js';

const PAGE_SIZE = 100;
const ALGORITHM_VERSION = '1.0.0';
const EXCLUDED_TYPES = new Set(['attachment', 'note', 'annotation']);

function err(text: string): ToolHandlerResult {
  return { content: [{ type: 'text', text }], isError: true };
}

function isBibliographic(item: any): boolean {
  const data = item?.data ?? item ?? {};
  return !EXCLUDED_TYPES.has(data.itemType) && !data.deleted;
}

async function listScope(
  ctx: ToolContext,
  query: { library?: LibraryRef; collectionKey?: string; tag?: string },
  cap: number,
): Promise<{ items: any[]; totalResults: number; libraryVersion?: number }> {
  const items: any[] = [];
  let start = 0;
  let totalResults = 0;
  let libraryVersion: number | undefined;
  do {
    const result = await ctx.router.searchItems({
      ...query,
      top: true,
      includeTrashed: false,
      limit: Math.min(PAGE_SIZE, cap),
      start,
    });
    totalResults = result.totalResults;
    libraryVersion = result.lastModifiedVersion;
    if (totalResults > cap) {
      throw new Error(
        `Selected scope contains ${totalResults} items, which exceeds the explicit limit of ${cap}. Narrow the batch or raise limit.`,
      );
    }
    items.push(...result.data.filter(isBibliographic));
    start += result.data.length;
    if (!result.data.length) break;
  } while (start < totalResults);
  return { items, totalResults, libraryVersion };
}

const findDuplicates: ToolDefinition = {
  name: 'zotero_find_duplicates',
  title: 'Find duplicate candidates in a Zotero import batch',
  description:
    'Read-only duplicate candidate detection for a collection or import-run tag. Compares the selected batch against all top-level bibliographic items in the same Zotero library using DOI, PMID, ISBN, normalized title, creators, and year. Saves an auditable JSON report and recommends a master record, but never merges, trashes, deletes, or otherwise modifies Zotero. Review every candidate and perform the final merge in Zotero Desktop so collections, tags, and citation relations are preserved.',
  inputSchema: {
    collection_key: z
      .string()
      .min(1)
      .optional()
      .describe('Batch collection key. Provide exactly one batch selector.'),
    tag: z
      .string()
      .min(1)
      .optional()
      .describe('Batch/import-run tag. Provide exactly one batch selector.'),
    limit: z
      .number()
      .int()
      .min(1)
      .describe('Explicit maximum item count for both batch and library scans.'),
    title_threshold: z
      .number()
      .min(0.8)
      .max(1)
      .optional()
      .describe('Review-candidate title similarity threshold; default 0.85.'),
    library_type: z.enum(['user', 'group']).optional(),
    library_id: z.number().int().optional(),
  },
  annotations: {
    readOnlyHint: true,
    destructiveHint: false,
    idempotentHint: false,
    openWorldHint: true,
  },
  handler: async (args, ctx) => {
    if (Boolean(args.collection_key) === Boolean(args.tag)) {
      return err('Provide exactly one of `collection_key` or `tag`.');
    }
    if (!Number.isInteger(args.limit) || args.limit < 1) {
      return err(
        'Provide an explicit positive integer `limit`; duplicate scans never use a silent cap.',
      );
    }
    const library: LibraryRef | undefined = args.library_id
      ? { type: (args.library_type ?? 'group') as 'user' | 'group', id: args.library_id }
      : undefined;
    const resolvedLibrary = library ?? ctx.router.defaultLibrary();

    let batch;
    let fullLibrary;
    try {
      batch = await listScope(
        ctx,
        { library, collectionKey: args.collection_key, tag: args.tag },
        args.limit,
      );
      fullLibrary = await listScope(ctx, { library }, args.limit);
    } catch (error) {
      return err(error instanceof Error ? error.message : String(error));
    }

    const clusters = findDuplicateClusters(batch.items, fullLibrary.items, {
      titleThreshold: args.title_threshold,
    });
    const createdAt = new Date().toISOString();
    const reportId = `duplicates-${createdAt.replace(/[:.]/g, '-')}-${randomUUID().slice(0, 8)}`;
    const reportDirectory = join(ctx.config.dataDir, 'duplicate-reports');
    const reportPath = join(reportDirectory, `${reportId}.json`);
    const report = {
      report_id: reportId,
      created_at: createdAt,
      algorithm_version: ALGORITHM_VERSION,
      library: resolvedLibrary,
      batch_selector: args.collection_key
        ? { collection_key: args.collection_key }
        : { tag: args.tag },
      explicit_limit: args.limit,
      truncated: false,
      source_total_results: fullLibrary.totalResults,
      batch_total_results: batch.totalResults,
      items_scanned: fullLibrary.items.length,
      batch_items_scanned: batch.items.length,
      library_version: fullLibrary.libraryVersion,
      cluster_count: clusters.length,
      confidence_counts: {
        high: clusters.filter((cluster) => cluster.confidence === 'high').length,
        medium: clusters.filter((cluster) => cluster.confidence === 'medium').length,
        review: clusters.filter((cluster) => cluster.confidence === 'review').length,
      },
      policy: {
        read_only: true,
        native_merge_required: true,
        instruction: 'Review candidates and merge confirmed duplicates in Zotero Desktop.',
      },
      clusters,
    };

    try {
      await mkdir(reportDirectory, { recursive: true });
      await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`, {
        encoding: 'utf8',
        flag: 'wx',
      });
    } catch (error) {
      return err(
        `Could not persist duplicate audit report: ${error instanceof Error ? error.message : String(error)}`,
      );
    }

    return ok(
      {
        reportId,
        reportPath,
        clusterCount: clusters.length,
        confidenceCounts: report.confidence_counts,
        itemsScanned: report.items_scanned,
        batchItemsScanned: report.batch_items_scanned,
        nativeMergeRequired: true,
      },
      `Found ${clusters.length} duplicate candidate cluster(s) across ${batch.items.length} batch item(s); audit report saved to ${reportPath}. Final merges must be completed in Zotero Desktop.`,
    );
  },
};

export default findDuplicates;
