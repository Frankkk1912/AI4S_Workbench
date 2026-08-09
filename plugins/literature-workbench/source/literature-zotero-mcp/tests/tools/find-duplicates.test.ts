import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it, vi } from 'vitest';
import findDuplicates from '../../src/tools/find-duplicates.js';

const batch = {
  key: 'BATCH001',
  version: 1,
  data: { itemType: 'journalArticle', title: 'Duplicate paper', DOI: '10.1000/test' },
};
const existing = {
  key: 'LIB00001',
  version: 2,
  data: { itemType: 'journalArticle', title: 'Duplicate paper', DOI: '10.1000/test' },
};

async function context(searchItems: ReturnType<typeof vi.fn>) {
  return {
    config: { dataDir: await mkdtemp(join(tmpdir(), 'literature-zotero-mcp-')) },
    router: {
      defaultLibrary: () => ({ type: 'user', id: 19552201 }),
      searchItems,
    },
  } as any;
}

describe('zotero_find_duplicates', () => {
  it('is explicitly read-only', () => {
    expect(findDuplicates.annotations?.readOnlyHint).toBe(true);
    expect(findDuplicates.annotations?.destructiveHint).toBe(false);
    expect(findDuplicates.annotations?.idempotentHint).toBe(false);
  });

  it('requires exactly one batch selector and an explicit limit', async () => {
    const ctx = await context(vi.fn());

    expect((await findDuplicates.handler({ limit: 100 }, ctx)).isError).toBe(true);
    expect(
      (
        await findDuplicates.handler(
          { collection_key: 'COLL', tag: 'import-run:test', limit: 100 },
          ctx,
        )
      ).isError,
    ).toBe(true);
    expect((await findDuplicates.handler({ collection_key: 'COLL' }, ctx)).isError).toBe(true);
  });

  it('compares a collection batch against the whole library and persists an audit report', async () => {
    const searchItems = vi.fn(async (query: any) => {
      if (query.collectionKey === 'COLL0001') {
        return { data: [batch], totalResults: 1, lastModifiedVersion: 8 };
      }
      return { data: [batch, existing], totalResults: 2, lastModifiedVersion: 8 };
    });
    const ctx = await context(searchItems);

    const result = await findDuplicates.handler({ collection_key: 'COLL0001', limit: 100 }, ctx);

    expect(result.isError).toBeUndefined();
    expect(searchItems).toHaveBeenCalledWith(
      expect.objectContaining({ collectionKey: 'COLL0001', top: true }),
    );
    expect(searchItems).toHaveBeenCalledWith(
      expect.objectContaining({ top: true, includeTrashed: false }),
    );
    expect(result.structuredContent?.clusterCount).toBe(1);
    expect(result.structuredContent?.reportId).toMatch(/^duplicates-/);
    const reportPath = result.structuredContent?.reportPath as string;
    const report = JSON.parse(await readFile(reportPath, 'utf8'));
    expect(report.clusters[0].batch_item_keys).toEqual(['BATCH001']);
    expect(report.clusters[0].native_merge_required).toBe(true);
    expect(JSON.stringify(report)).not.toContain('api-key');
  });

  it('supports a tag-scoped batch', async () => {
    const searchItems = vi.fn(async (query: any) => ({
      data: query.tag ? [batch] : [batch, existing],
      totalResults: query.tag ? 1 : 2,
      lastModifiedVersion: 8,
    }));
    const ctx = await context(searchItems);

    await findDuplicates.handler({ tag: 'import-run:test-20260711', limit: 100 }, ctx);

    expect(searchItems).toHaveBeenCalledWith(
      expect.objectContaining({ tag: 'import-run:test-20260711' }),
    );
  });

  it('fails instead of silently truncating when the selected scope exceeds limit', async () => {
    const searchItems = vi.fn(async () => ({
      data: [batch],
      totalResults: 101,
      lastModifiedVersion: 8,
    }));
    const ctx = await context(searchItems);

    const result = await findDuplicates.handler({ collection_key: 'COLL0001', limit: 100 }, ctx);

    expect(result.isError).toBe(true);
    expect(result.content[0].text).toMatch(/101.*limit.*100/i);
  });

  it('filters child and deleted records before analysis', async () => {
    const attachment = {
      key: 'ATTACH01',
      data: { itemType: 'attachment', title: 'Duplicate paper' },
    };
    const deleted = {
      key: 'DELETED1',
      data: { itemType: 'journalArticle', title: 'Duplicate paper', deleted: 1 },
    };
    const searchItems = vi.fn(async (query: any) => ({
      data: query.collectionKey
        ? [batch, attachment, deleted]
        : [batch, existing, attachment, deleted],
      totalResults: query.collectionKey ? 3 : 4,
      lastModifiedVersion: 8,
    }));
    const ctx = await context(searchItems);

    const result = await findDuplicates.handler({ collection_key: 'COLL0001', limit: 100 }, ctx);
    const report = JSON.parse(
      await readFile(result.structuredContent?.reportPath as string, 'utf8'),
    );

    expect(report.items_scanned).toBe(2);
    expect(report.batch_items_scanned).toBe(1);
  });
});
