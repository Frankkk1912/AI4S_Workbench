import { createHash } from 'node:crypto';
import { mkdir, rename, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import type { LibraryRef } from '../../api/web-client.js';
import type { ToolContext } from '../../registry/registry.js';
import { semanticTagsDirectory } from './vocabulary.js';

function tagName(entry: any): string { return typeof entry === 'string' ? entry : String(entry?.tag ?? ''); }
function normalize(entry: any): { tag: string; type?: number } {
  return typeof entry === 'string' ? { tag: entry } : entry?.type === undefined ? { tag: entry.tag } : { tag: entry.tag, type: entry.type };
}
function timestampName(): string { return new Date().toISOString().replace(/[:.]/g, '-'); }
async function persist(path: string, value: unknown): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  const temporary = `${path}.tmp-${process.pid}`;
  await writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, 'utf8');
  await rename(temporary, path);
}
function hash(value: unknown): string {
  return `sha256:${createHash('sha256').update(JSON.stringify(value)).digest('hex')}`;
}

export async function cleanupAutomaticTags(
  ctx: ToolContext,
  library: LibraryRef,
  input: { scope_type: 'collection' | 'library'; collection_key?: string; max_items: number; start: number },
): Promise<Record<string, unknown>> {
  const result = await ctx.router.searchItems({
    library, top: true, collectionKey: input.scope_type === 'collection' ? input.collection_key : undefined,
    limit: Math.min(100, input.max_items), start: input.start,
  });
  const candidates = [...result.data];
  let next = input.start + result.data.length;
  while (candidates.length < input.max_items && next < result.totalResults) {
    const page = await ctx.router.searchItems({
      library, top: true, collectionKey: input.scope_type === 'collection' ? input.collection_key : undefined,
      limit: Math.min(100, input.max_items - candidates.length), start: next,
    });
    if (!page.data.length) break;
    candidates.push(...page.data);
    next += page.data.length;
  }
  const actions = [];
  for (const candidate of candidates) {
    const key = candidate?.key ?? candidate?.data?.key;
    if (!key) continue;
    const item = await ctx.web.getItem(library, key);
    const data = item?.data ?? item ?? {};
    if (['attachment', 'note', 'annotation'].includes(String(data.itemType ?? ''))) continue;
    const tags = Array.isArray(data.tags) ? data.tags : [];
    const automatic = tags.filter((entry: any) => typeof entry !== 'string' && entry?.type === 1).map(tagName);
    actions.push({
      item_key: key, expected_version: item?.version ?? data.version, title: data.title ?? '(untitled)',
      automatic_tags: automatic, final_tags: tags.filter((entry: any) => !(typeof entry !== 'string' && entry?.type === 1)).map(normalize),
      decision: automatic.length ? 'update' : 'unchanged',
    });
  }
  const planBase = {
    schema_version: '1.0', plan_type: 'zotero-automatic-tag-cleanup', created_at: new Date().toISOString(),
    target: { library_type: library.type, library_id: library.id },
    scope: { type: input.scope_type, collection_key: input.collection_key, start: input.start, max_items: input.max_items },
    actions,
  };
  const planHash = hash(planBase);
  const stem = `${timestampName()}-${planHash.slice(-12)}`;
  const root = semanticTagsDirectory(ctx.config.dataDir, library);
  const planPath = join(root, 'plans', `cleanup-${stem}.json`);
  const receiptPath = join(root, 'receipts', `cleanup-${stem}.json`);
  await persist(planPath, { ...planBase, plan_hash: planHash });
  const results = [];
  for (const action of actions) {
    if (action.decision === 'unchanged') {
      results.push({ item_key: action.item_key, outcome: 'unchanged', removed_automatic_tags: [], error: null });
      continue;
    }
    try {
      const version = await ctx.web.patchItem(library, action.item_key, { tags: action.final_tags }, action.expected_version);
      results.push({ item_key: action.item_key, outcome: 'updated', zotero_version: version,
        removed_automatic_tags: action.automatic_tags, error: null });
    } catch (error) {
      results.push({ item_key: action.item_key, outcome: 'failed', removed_automatic_tags: [],
        error: (error instanceof Error ? error.message : String(error)).slice(0, 500) });
    }
  }
  const summary = {
    updated: results.filter((entry) => entry.outcome === 'updated').length,
    unchanged: results.filter((entry) => entry.outcome === 'unchanged').length,
    failed: results.filter((entry) => entry.outcome === 'failed').length,
  };
  const truncated = input.start + candidates.length < result.totalResults;
  const receipt = {
    schema_version: '1.0', receipt_type: 'zotero-automatic-tag-cleanup', plan_hash: planHash,
    status: summary.failed ? 'partial' : 'complete', total_results: result.totalResults,
    processed: candidates.length, truncated, next_start: truncated ? input.start + candidates.length : null,
    results, summary,
  };
  await persist(receiptPath, receipt);
  return { status: receipt.status, plan_hash: planHash, plan_path: planPath, receipt_path: receiptPath,
    total_results: result.totalResults, processed: candidates.length, truncated, next_start: receipt.next_start, summary };
}
