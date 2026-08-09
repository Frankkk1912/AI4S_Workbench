import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { mkdtemp } from 'node:fs/promises';
import { describe, expect, it, vi } from 'vitest';
import { executeFulltextHandoff } from '../../src/features/fulltext/apply.js';
import { canonicalFulltextHandoffHash } from '../../src/features/fulltext/handoff-contract.js';

const library = { type: 'user' as const, id: 1 };

async function fixture(root: string) {
  const bytes = Buffer.concat([Buffer.from('%PDF-1.4\n'), Buffer.alloc(300, 0x20)]);
  const sha = createHash('sha256').update(bytes).digest('hex');
  const unsigned = {
    schema_version: 1 as const, handoff_id: 'fth-12345678', job_id: 'ft-12345678', request_id: 'a'.repeat(64), created_at: '2026-07-22T00:00:00.000Z',
    records: [{
      evidence_id: 'doi:10.1000/example', zotero_item_key: 'ABCD1234', expected_parent: { doi: '10.1000/example', title: 'Example article' },
      retrieval: { status: 'verified' as const, provider: 'pmc', access_mode: 'open_access_http' as const, document_version: 'version_of_record' as const, file_role: 'main_article' as const, retrieved_at: '2026-07-22T00:00:00.000Z' },
      artifact: { artifact_id: `sha256:${sha}`, sha256: sha, md5: 'b'.repeat(32), bytes: bytes.byteLength, content_type: 'application/pdf' as const, page_count: 1 },
      verification: { level: 'strong_identifier' as const, doi_match: true as const, title_match: true as const },
    }],
  };
  const handoff = { ...unsigned, handoff_hash: canonicalFulltextHandoffHash(unsigned) };
  await mkdir(join(root, 'handoffs'), { recursive: true });
  await mkdir(join(root, 'artifacts'), { recursive: true });
  await writeFile(join(root, 'handoffs', `${handoff.handoff_id}.json`), JSON.stringify(handoff));
  await writeFile(join(root, 'artifacts', `${sha}.pdf`), bytes);
  return handoff;
}

describe('verified Fulltext handoff application', () => {
  it('persists one attachment key across retry and never accepts a caller file path', async () => {
    const exchange = await mkdtemp(join(tmpdir(), 'fulltext-apply-'));
    const handoff = await fixture(exchange);
    const writeItems = vi.fn(async () => ({ successful: [{ index: 0, key: 'IJKL9012' }], unchanged: [], failed: [], newLibraryVersion: 2 }));
    const ctx = {
      config: { fulltextExchangeRoot: exchange },
      web: {
        getItem: vi.fn(async (_library: any, key: string) => key === 'ABCD1234'
          ? { key, data: { itemType: 'journalArticle', DOI: '10.1000/example', title: 'Example article' } }
          : { key, data: { itemType: 'attachment', parentItem: 'ABCD1234' } }),
        getItemChildren: vi.fn(async () => ({ data: [], totalResults: 0, lastModifiedVersion: 1 })),
        writeItems,
        requestUpload: vi.fn(async () => ({ url: 'https://storage.example/upload', contentType: 'application/octet-stream', prefix: '', suffix: '', uploadKey: 'upload-key' })),
        uploadBytes: vi.fn(async () => undefined),
        registerUpload: vi.fn(async () => undefined),
      },
    } as any;
    const first = await executeFulltextHandoff(ctx, library, { handoffId: handoff.handoff_id, handoffHash: handoff.handoff_hash });
    expect(first.summary).toMatchObject({ attached: 1, failed: 0 });
    expect(writeItems).toHaveBeenCalledTimes(1);
    const receipt = JSON.parse(await readFile(join(exchange, 'receipts', `${handoff.handoff_id}.json`), 'utf8'));
    expect(receipt.results[0]).toMatchObject({ attachment_item_key: 'IJKL9012', phase: 'verified', status: 'complete' });
    await executeFulltextHandoff(ctx, library, { handoffId: handoff.handoff_id, handoffHash: handoff.handoff_hash });
    expect(writeItems).toHaveBeenCalledTimes(1);
  });

  it('skips a live imported PDF rather than adding another attachment', async () => {
    const exchange = await mkdtemp(join(tmpdir(), 'fulltext-existing-'));
    const handoff = await fixture(exchange);
    const writeItems = vi.fn();
    const ctx = { config: { fulltextExchangeRoot: exchange }, web: {
      getItem: vi.fn(async () => ({ key: 'ABCD1234', data: { itemType: 'journalArticle', DOI: '10.1000/example' } })),
      getItemChildren: vi.fn(async () => ({ data: [{ key: 'OLDPDF01', data: { itemType: 'attachment', linkMode: 'imported_file', contentType: 'application/pdf' } }], totalResults: 1, lastModifiedVersion: 1 })),
      writeItems,
    } } as any;
    const result = await executeFulltextHandoff(ctx, library, { handoffId: handoff.handoff_id, handoffHash: handoff.handoff_hash });
    expect(result.summary).toMatchObject({ skipped_existing: 1, attached: 0 });
    expect(writeItems).not.toHaveBeenCalled();
  });
});
