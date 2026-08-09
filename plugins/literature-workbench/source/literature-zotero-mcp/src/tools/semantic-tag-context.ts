import { z } from 'zod';
import type { LibraryRef } from '../api/web-client.js';
import type { ToolDefinition } from '../registry/registry.js';
import { ok } from '../registry/registry.js';
import { semanticLabel } from '../features/semantic-tags/contract.js';
import { loadVocabulary, selectVocabularyEntries, vocabularyPath } from '../features/semantic-tags/vocabulary.js';

function project(item: any): Record<string, unknown> | null {
  const data = item?.data ?? item ?? {};
  if (['attachment', 'note', 'annotation'].includes(String(data.itemType ?? ''))) return null;
  const tags = Array.isArray(data.tags) ? data.tags : [];
  const abstract = typeof data.abstractNote === 'string' ? data.abstractNote.trim() : '';
  return {
    item_key: item?.key ?? data.key,
    version: item?.version ?? data.version,
    item_type: data.itemType,
    title: data.title ?? '(untitled)',
    abstract: abstract.slice(0, 6000),
    abstract_truncated: abstract.length > 6000,
    evidence_depth: abstract ? 'title-abstract' : 'metadata-only',
    collections: Array.isArray(data.collections) ? data.collections : [],
    existing_semantic_tags: tags.map((entry: any) => typeof entry === 'string' ? entry : entry?.tag)
      .filter((tag: unknown): tag is string => typeof tag === 'string' && semanticLabel(tag) !== null),
    automatic_tags: tags.filter((entry: any) => typeof entry !== 'string' && entry?.type === 1)
      .map((entry: any) => entry.tag).filter(Boolean),
  };
}

const semanticTagContext: ToolDefinition = {
  name: 'zotero_semantic_tag_context',
  title: 'Prepare semantic-tag context',
  description:
    'Read one item set or collection for Agent semantic tagging. Returns title/abstract evidence, existing AI4S:Semantic tags, automatic tags, the current vocabulary revision, and a compact reusable English vocabulary subset. Use the returned revision and item versions with zotero_apply_semantic_tags. No writes.',
  inputSchema: {
    item_keys: z.array(z.string().regex(/^[A-Z0-9]{8}$/)).min(1).max(50).optional(),
    collection_key: z.string().regex(/^[A-Z0-9]{8}$/).optional(),
    limit: z.number().int().min(1).max(50).optional().describe('Collection items to return (default 25, max 50).'),
    start: z.number().int().min(0).optional(),
    vocabulary_limit: z.number().int().min(1).max(500).optional().describe('Vocabulary entries to return (default 200).'),
    vocabulary_query: z.string().max(500).optional().describe('Optional domain terms to prioritize vocabulary selection.'),
    library_type: z.enum(['user', 'group']).optional(),
    library_id: z.number().int().optional(),
  },
  annotations: { readOnlyHint: true, openWorldHint: false },
  handler: async (args, ctx) => {
    if (Boolean(args.item_keys) === Boolean(args.collection_key)) {
      throw new Error('Provide exactly one of item_keys or collection_key');
    }
    const library: LibraryRef = args.library_id
      ? { type: args.library_type ?? 'group', id: args.library_id }
      : ctx.router.defaultLibrary();
    const items: Record<string, unknown>[] = [];
    let totalResults: number;
    let libraryVersion: number | undefined;
    if (args.item_keys) {
      for (const key of args.item_keys) {
        const projected = project(await ctx.router.getItem(key, { library }));
        if (projected) items.push(projected);
      }
      totalResults = items.length;
    } else {
      const result = await ctx.router.searchItems({
        library, collectionKey: args.collection_key, top: true,
        limit: args.limit ?? 25, start: args.start ?? 0,
      });
      for (const item of result.data) {
        const projected = project(item);
        if (projected) items.push(projected);
      }
      totalResults = result.totalResults;
      libraryVersion = result.lastModifiedVersion;
    }
    const vocabulary = await loadVocabulary(ctx.config.dataDir, library);
    const searchText = [args.vocabulary_query, ...items.flatMap((item) => [item.title, item.abstract])]
      .filter((value): value is string => typeof value === 'string').join(' ');
    const selected = selectVocabularyEntries(vocabulary, searchText, args.collection_key, args.vocabulary_limit ?? 200);
    return ok({
      library, scope: args.collection_key ? { type: 'collection', collection_key: args.collection_key } : { type: 'items' },
      items, totalResults, libraryVersion, start: args.start ?? 0,
      vocabulary: { revision: vocabulary.revision, language: vocabulary.language, entries: selected.entries,
        total: selected.total, truncated: selected.truncated, path: vocabularyPath(ctx.config.dataDir, library) },
      rules: { max_tags_per_item: 4, metadata_only_max: 2, metadata_only_forbids: ['mechanism'],
        language: 'en', specific_entity_requires_principal_subject: true },
    }, `Prepared ${items.length} item(s) with vocabulary revision ${vocabulary.revision} (${selected.entries.length}/${selected.total} entries).`);
  },
};

export default semanticTagContext;
