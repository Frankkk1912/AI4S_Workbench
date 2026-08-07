import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import { validateRecommendation } from '../../src/features/semantic-tags/contract.js';
import { executeSemanticTags } from '../../src/features/semantic-tags/apply.js';
import { cleanupAutomaticTags } from '../../src/features/semantic-tags/cleanup.js';
import { loadVocabulary, saveVocabulary, vocabularyPath } from '../../src/features/semantic-tags/vocabulary.js';
import semanticTagContext from '../../src/tools/semantic-tag-context.js';
import semanticTagVocabulary from '../../src/tools/semantic-tag-vocabulary.js';

const library = { type: 'user' as const, id: 1 };

function context(dataDir: string, item: any) {
  return {
    config: { dataDir },
    web: {
      getItem: vi.fn(async () => structuredClone(item)),
      patchItem: vi.fn(async () => 5),
    },
  } as any;
}

describe('semantic tag recommendation contract', () => {
  it('enforces metadata-only depth and English labels', () => {
    expect(() => validateRecommendation({
      item_key: 'ITEM0001', expected_version: 4, evidence_depth: 'metadata-only',
      tags: [{ canonical: 'Inflammation', dimension: 'mechanism', decision: 'new', description: 'Inflammatory signaling' }],
    })).toThrow(/may not contain mechanism/);
    expect(() => validateRecommendation({
      item_key: 'ITEM0001', expected_version: 4, evidence_depth: 'title-abstract',
      tags: [{ canonical: '巨噬细胞', dimension: 'entity', decision: 'new', description: 'Cell type' }],
    })).toThrow(/English scientific terminology/);
  });
});

describe('semantic tag application', () => {
  it('replaces only the semantic namespace, removes automatic tags, and persists vocabulary and receipts', async () => {
    const dataDir = await mkdtemp(join(tmpdir(), 'semantic-tags-'));
    const item = { key: 'ITEM0001', version: 4, data: {
      itemType: 'journalArticle', title: 'Single-cell macrophage states', abstractNote: 'Macrophage states measured by scRNA-seq.',
      tags: [
        { tag: 'manual:keep' }, { tag: 'PubMed keyword', type: 1 },
        { tag: 'AI4S:Semantic:Old label' }, { tag: 'AI4S:Priority:3' }, { tag: 'JCR:Q1' },
      ],
    } };
    const ctx = context(dataDir, item);
    const result = await executeSemanticTags(ctx, library, {
      scope: { type: 'collection', collection_key: 'COLL0001' }, vocabulary_revision: 0,
      cleanup_auto_tags: true,
      items: [{ item_key: 'ITEM0001', expected_version: 4, evidence_depth: 'title-abstract', tags: [{
        canonical: 'Single-cell transcriptomics', dimension: 'method', decision: 'new',
        aliases: ['scRNA-seq', 'Single-cell RNA sequencing'],
        description: 'Transcriptome profiling at single-cell resolution',
      }] }],
    });
    expect(result.status).toBe('complete');
    const patch = ctx.web.patchItem.mock.calls[0][2];
    expect(patch.tags).toEqual([
      { tag: 'manual:keep' }, { tag: 'AI4S:Priority:3' }, { tag: 'JCR:Q1' },
      { tag: 'AI4S:Semantic:Single-cell transcriptomics' },
    ]);
    const vocabulary = await loadVocabulary(dataDir, library);
    expect(vocabulary.revision).toBe(1);
    expect(vocabulary.tags[0]).toMatchObject({ canonical: 'Single-cell transcriptomics', usage_count: 1, collection_keys: ['COLL0001'] });
    const receipt = JSON.parse(await readFile(String(result.receipt_path), 'utf8'));
    expect(receipt.results[0]).toMatchObject({
      outcome: 'updated', removed_automatic_tags: ['PubMed keyword'],
      before_semantic_tags: ['AI4S:Semantic:Old label'],
      after_semantic_tags: ['AI4S:Semantic:Single-cell transcriptomics'],
    });
    expect(JSON.parse(await readFile(String(result.plan_path), 'utf8')).plan_hash).toBe(result.plan_hash);
  });

  it('reuses one new canonical entry across a batch and rejects a stale vocabulary revision before writes', async () => {
    const dataDir = await mkdtemp(join(tmpdir(), 'semantic-tags-batch-'));
    const items: Record<string, any> = {
      ITEM0001: { key: 'ITEM0001', version: 1, data: { itemType: 'journalArticle', title: 'A', tags: [] } },
      ITEM0002: { key: 'ITEM0002', version: 2, data: { itemType: 'journalArticle', title: 'B', tags: [] } },
    };
    const patchItem = vi.fn(async (_lib, key) => key === 'ITEM0001' ? 3 : 4);
    const ctx = { config: { dataDir }, web: { getItem: vi.fn(async (_lib, key) => structuredClone(items[key])), patchItem } } as any;
    const proposal = { canonical: 'Macrophage', dimension: 'entity' as const, decision: 'new' as const,
      aliases: ['Macrophages'], description: 'Macrophages as the principal study subject' };
    await executeSemanticTags(ctx, library, {
      scope: { type: 'items' }, vocabulary_revision: 0, cleanup_auto_tags: true,
      items: [
        { item_key: 'ITEM0001', expected_version: 1, evidence_depth: 'title-abstract', tags: [proposal] },
        { item_key: 'ITEM0002', expected_version: 2, evidence_depth: 'title-abstract', tags: [proposal] },
      ],
    });
    expect((await loadVocabulary(dataDir, library)).tags[0].usage_count).toBe(2);
    await expect(executeSemanticTags(ctx, library, {
      scope: { type: 'items' }, vocabulary_revision: 0, cleanup_auto_tags: true,
      items: [{ item_key: 'ITEM0001', expected_version: 3, evidence_depth: 'title-abstract', tags: [] }],
    })).rejects.toThrow(/revision changed/);
    expect(patchItem).toHaveBeenCalledTimes(2);
  });

  it('does not advance vocabulary revision for a fully unchanged reuse', async () => {
    const dataDir = await mkdtemp(join(tmpdir(), 'semantic-tags-idempotent-'));
    const vocabulary = await loadVocabulary(dataDir, library);
    vocabulary.revision = 2;
    vocabulary.updated_at = '2026-07-17T00:00:00Z';
    vocabulary.tags = [{
      id: 'semantic:macrophage-12345678', canonical: 'Macrophage', dimension: 'entity', aliases: ['Macrophages'],
      description: 'Macrophages as the principal study subject', usage_count: 1, collection_keys: [],
      created_at: '2026-07-17T00:00:00Z', updated_at: '2026-07-17T00:00:00Z',
    }];
    await saveVocabulary(vocabularyPath(dataDir, library), vocabulary);
    const item = { key: 'ITEM0001', version: 4, data: { itemType: 'journalArticle', title: 'Paper', tags: [{ tag: 'AI4S:Semantic:Macrophage' }] } };
    const ctx = context(dataDir, item);
    const result = await executeSemanticTags(ctx, library, {
      scope: { type: 'items' }, vocabulary_revision: 2, cleanup_auto_tags: true,
      items: [{ item_key: 'ITEM0001', expected_version: 4, evidence_depth: 'title-abstract', tags: [{
        canonical: 'Macrophage', dimension: 'entity', decision: 'reuse', matched_alias: 'Macrophages',
      }] }],
    });
    expect(result.summary).toMatchObject({ unchanged: 1 });
    expect((await loadVocabulary(dataDir, library)).revision).toBe(2);
    expect(ctx.web.patchItem).not.toHaveBeenCalled();
  });

  it('persists a newly confirmed alias for a reused canonical tag and covers it in the plan hash', async () => {
    const dataDir = await mkdtemp(join(tmpdir(), 'semantic-tags-alias-'));
    const vocabulary = await loadVocabulary(dataDir, library);
    vocabulary.revision = 1;
    vocabulary.updated_at = '2026-07-17T00:00:00Z';
    vocabulary.tags = [{
      id: 'semantic:macrophage-12345678', canonical: 'Macrophage', dimension: 'entity', aliases: ['Macrophages'],
      description: 'Macrophages as the principal study subject', usage_count: 1, collection_keys: [],
      created_at: '2026-07-17T00:00:00Z', updated_at: '2026-07-17T00:00:00Z',
    }];
    await saveVocabulary(vocabularyPath(dataDir, library), vocabulary);
    const item = { key: 'ITEM0001', version: 4, data: { itemType: 'journalArticle', title: 'Paper', tags: [{ tag: 'AI4S:Semantic:Macrophage' }] } };
    const ctx = context(dataDir, item);
    const result = await executeSemanticTags(ctx, library, {
      scope: { type: 'items' }, vocabulary_revision: 1, cleanup_auto_tags: true,
      items: [{ item_key: 'ITEM0001', expected_version: 4, evidence_depth: 'title-abstract', tags: [{
        canonical: 'Macrophage', dimension: 'entity', decision: 'reuse', vocabulary_id: 'semantic:macrophage-12345678',
        aliases: ['Macrophage cells'],
      }] }],
    });
    const updated = await loadVocabulary(dataDir, library);
    expect(updated.revision).toBe(2);
    expect(updated.tags[0].aliases).toEqual(['Macrophages', 'Macrophage cells']);
    expect(ctx.web.patchItem).not.toHaveBeenCalled();
    const plan = JSON.parse(await readFile(String(result.plan_path), 'utf8'));
    expect(plan.actions[0].desired[0]).toMatchObject({ decision: 'reuse', aliases: ['Macrophage cells'] });
  });
});

describe('automatic tag cleanup', () => {
  it('removes only type-1 tags and leaves manual tags untouched', async () => {
    const dataDir = await mkdtemp(join(tmpdir(), 'auto-tag-cleanup-'));
    const item = { key: 'ITEM0001', version: 7, data: { itemType: 'journalArticle', title: 'Paper',
      tags: [{ tag: 'manual:keep' }, { tag: 'automatic:remove', type: 1 }, { tag: 'AI4S:Priority:2' }] } };
    const patchItem = vi.fn(async () => 8);
    const ctx = {
      config: { dataDir },
      router: { searchItems: vi.fn(async () => ({ data: [item], totalResults: 1, lastModifiedVersion: 7 })) },
      web: { getItem: vi.fn(async () => item), patchItem },
    } as any;
    const result = await cleanupAutomaticTags(ctx, library, { scope_type: 'library', max_items: 10, start: 0 });
    expect(result.summary).toMatchObject({ updated: 1, failed: 0 });
    expect(patchItem.mock.calls[0][2].tags).toEqual([{ tag: 'manual:keep' }, { tag: 'AI4S:Priority:2' }]);
  });
});

describe('semantic tag context and vocabulary portability tools', () => {
  it('returns title/abstract evidence with the current reusable vocabulary revision', async () => {
    const dataDir = await mkdtemp(join(tmpdir(), 'semantic-context-'));
    const vocabulary = await loadVocabulary(dataDir, library);
    vocabulary.revision = 3;
    vocabulary.updated_at = '2026-07-17T00:00:00Z';
    vocabulary.tags = [{
      id: 'semantic:single-cell-12345678', canonical: 'Single-cell transcriptomics', dimension: 'method',
      aliases: ['scRNA-seq'], description: 'Transcriptome profiling at single-cell resolution', usage_count: 2,
      collection_keys: ['COLL0001'], created_at: '2026-07-17T00:00:00Z', updated_at: '2026-07-17T00:00:00Z',
    }];
    await saveVocabulary(vocabularyPath(dataDir, library), vocabulary);
    const ctx = {
      config: { dataDir },
      router: {
        defaultLibrary: () => library,
        getItem: vi.fn(async () => ({ key: 'ITEM0001', version: 4, data: {
          itemType: 'journalArticle', title: 'Macrophage scRNA-seq', abstractNote: 'Single-cell analysis.',
          tags: [{ tag: 'old keyword', type: 1 }, { tag: 'AI4S:Semantic:Macrophage' }], collections: ['COLL0001'],
        } })),
      },
    } as any;
    const result = await semanticTagContext.handler({ item_keys: ['ITEM0001'] }, ctx);
    expect(result.structuredContent?.vocabulary).toMatchObject({ revision: 3, total: 1, truncated: false });
    expect((result.structuredContent?.items as any[])[0]).toMatchObject({
      evidence_depth: 'title-abstract', automatic_tags: ['old keyword'],
      existing_semantic_tags: ['AI4S:Semantic:Macrophage'],
    });
  });

  it('exports and merge-imports a vocabulary with expected-revision protection', async () => {
    const dataDir = await mkdtemp(join(tmpdir(), 'semantic-portability-'));
    const ctx = { config: { dataDir }, router: { defaultLibrary: () => library } } as any;
    const incoming = await loadVocabulary(dataDir, library);
    incoming.tags = [{
      id: 'semantic:macrophage-12345678', canonical: 'Macrophage', dimension: 'entity', aliases: ['Macrophages'],
      description: 'Macrophages as the principal study subject', usage_count: 4, collection_keys: ['COLL0001'],
      created_at: '2026-07-17T00:00:00Z', updated_at: '2026-07-17T00:00:00Z',
    }];
    const source = join(dataDir, 'incoming.json');
    await saveVocabulary(source, incoming);
    const imported = await semanticTagVocabulary.handler({ action: 'import', path: source, expected_revision: 0 }, ctx);
    expect(imported.structuredContent).toMatchObject({ added: 1, merged: 0, revision: 1 });
    const destination = join(dataDir, 'exported.json');
    const exported = await semanticTagVocabulary.handler({ action: 'export', path: destination }, ctx);
    expect(exported.structuredContent).toMatchObject({ path: destination, revision: 1, entries: 1 });
    expect(JSON.parse(await readFile(destination, 'utf8')).tags[0].canonical).toBe('Macrophage');
    await expect(semanticTagVocabulary.handler({ action: 'import', path: source, expected_revision: 0 }, ctx))
      .rejects.toThrow(/revision changed/);
  });
});
