import { z } from 'zod';
import type { LibraryRef } from '../api/web-client.js';
import type { ToolDefinition } from '../registry/registry.js';
import { ok } from '../registry/registry.js';
import {
  evidenceHash, normalizeEvidenceText, normalizeLanguage, parseAiSummaryExtra, type SummaryMode,
} from '../features/ai-summaries/contract.js';

function dataOf(item: any): any { return item?.data ?? item ?? {}; }
function keyOf(item: any): string { const data = dataOf(item); return String(item?.key ?? data.key ?? ''); }
function versionOf(item: any): number | null {
  const value = item?.version ?? item?.data?.version;
  return Number.isInteger(value) ? value : null;
}
function regularItem(data: any): boolean {
  return !['attachment', 'note', 'annotation'].includes(String(data.itemType ?? ''));
}

function project(item: any, mode: SummaryMode, language: string): {
  candidate?: Record<string, unknown>;
  result?: Record<string, unknown>;
  outcome: 'candidate' | 'unchanged' | 'stale' | 'skipped' | 'conflicted';
} {
  const data = dataOf(item);
  const itemKey = keyOf(item);
  const version = versionOf(item);
  const title = normalizeEvidenceText(data.title);
  const abstract = normalizeEvidenceText(data.abstractNote);
  const base = { item_key: itemKey, version, title: title || '(untitled)' };
  if (!regularItem(data)) {
    return { outcome: 'skipped', result: { ...base, outcome: 'skipped', reason: 'unsupported-item-type' } };
  }
  if (!title) return { outcome: 'skipped', result: { ...base, outcome: 'skipped', reason: 'missing-title' } };
  if (!abstract) return { outcome: 'skipped', result: { ...base, outcome: 'skipped', reason: 'missing-abstract' } };
  if (version === null) return { outcome: 'conflicted', result: { ...base, outcome: 'conflicted', reason: 'missing-version' } };
  const parsed = parseAiSummaryExtra(data.extra);
  if (parsed.status === 'invalid') {
    return { outcome: 'conflicted', result: { ...base, outcome: 'conflicted', reason: parsed.error } };
  }
  const titleSha256 = evidenceHash(title);
  const abstractSha256 = evidenceHash(abstract);
  const summaryState = parsed.status === 'missing' ? 'missing'
    : parsed.payload.title_sha256 === titleSha256 && parsed.payload.abstract_sha256 === abstractSha256 ? 'current' : 'stale';
  if (mode === 'missing' && summaryState === 'current') {
    return { outcome: 'unchanged', result: { ...base, outcome: 'unchanged', reason: 'summary-current' } };
  }
  if (mode === 'missing' && summaryState === 'stale') {
    return { outcome: 'stale', result: { ...base, outcome: 'stale', reason: 'explicit-refresh-required' } };
  }
  return {
    outcome: 'candidate',
    candidate: {
      ...base, item_type: data.itemType, title, abstract, title_sha256: titleSha256,
      abstract_sha256: abstractSha256, language, existing_summary_state: summaryState,
    },
  };
}

const aiSummaryContext: ToolDefinition = {
  name: 'zotero_ai_summary_context',
  title: 'Prepare AI Summary context',
  description:
    'Read one item set or collection for explicitly requested one-sentence AI summaries. Returns only title-and-abstract evidence, stable input hashes, item versions, and existing AI4S-Summary state. Default language is Chinese (zh-CN). In missing mode, current or stale summaries are not regenerated; use refresh only when the user explicitly asks to refresh or overwrite. No writes.',
  inputSchema: {
    item_keys: z.array(z.string().regex(/^[A-Z0-9]{8}$/)).min(1).max(50).optional(),
    collection_key: z.string().regex(/^[A-Z0-9]{8}$/).optional(),
    mode: z.enum(['missing', 'refresh']).optional().describe('Default missing; refresh requires explicit user overwrite intent.'),
    language: z.string().max(35).optional().describe('BCP 47 output language; defaults to zh-CN.'),
    limit: z.number().int().min(1).max(50).optional().describe('Collection records per page (default 25, max 50).'),
    start: z.number().int().min(0).optional(),
    library_type: z.enum(['user', 'group']).optional(),
    library_id: z.number().int().optional(),
  },
  annotations: { readOnlyHint: true, openWorldHint: false },
  handler: async (args, ctx) => {
    if (Boolean(args.item_keys) === Boolean(args.collection_key)) {
      throw new Error('Provide exactly one of item_keys or collection_key');
    }
    const mode: SummaryMode = args.mode ?? 'missing';
    const language = normalizeLanguage(args.language ?? 'zh-CN');
    const library: LibraryRef = args.library_id
      ? { type: args.library_type ?? 'group', id: args.library_id }
      : ctx.router.defaultLibrary();
    const rawItems: any[] = [];
    let totalResults = 0;
    let libraryVersion: number | undefined;
    const start = args.start ?? 0;
    if (args.item_keys) {
      for (const key of args.item_keys) rawItems.push(await ctx.router.getItem(key, { library }));
      totalResults = rawItems.length;
    } else {
      const result = await ctx.router.searchItems({
        library, collectionKey: args.collection_key, top: true, limit: args.limit ?? 25, start,
      });
      rawItems.push(...result.data);
      totalResults = result.totalResults;
      libraryVersion = result.lastModifiedVersion;
    }
    const candidates: Record<string, unknown>[] = [];
    const results: Record<string, unknown>[] = [];
    const counts = { candidate: 0, unchanged: 0, stale: 0, skipped: 0, conflicted: 0 };
    for (const item of rawItems) {
      const projected = project(item, mode, language);
      counts[projected.outcome] += 1;
      if (projected.candidate) candidates.push(projected.candidate);
      if (projected.result) results.push(projected.result);
    }
    const nextStart = args.collection_key && start + rawItems.length < totalResults ? start + rawItems.length : null;
    return ok({
      library, scope: args.collection_key ? { type: 'collection', collection_key: args.collection_key } : { type: 'items' },
      mode, language, items: candidates, results, summary: counts, totalResults, libraryVersion,
      start, next_start: nextStart,
      rules: { basis: 'title-abstract', one_sentence: true, max_characters: 240, markdown: false,
        default_language: 'zh-CN', no_external_knowledge: true },
    }, `Prepared ${candidates.length} AI Summary candidate(s); unchanged=${counts.unchanged}, stale=${counts.stale}, skipped=${counts.skipped}, conflicts=${counts.conflicted}.`);
  },
};

export default aiSummaryContext;
