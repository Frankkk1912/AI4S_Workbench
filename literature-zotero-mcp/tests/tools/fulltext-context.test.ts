import { describe, expect, it, vi } from 'vitest';
import fulltextContext from '../../src/tools/fulltext-context.js';

const library = { type: 'user' as const, id: 1 };
const item = (key: string, data: Record<string, unknown>) => ({ key, version: 1, data });

describe('zotero_fulltext_context', () => {
  it('distinguishes stored file PDFs from linked URLs and blocks ambiguous ownership', async () => {
    const parents: Record<string, any> = {
      ITEM0001: item('ITEM0001', { itemType: 'journalArticle', DOI: 'https://doi.org/10.1000/one.', title: 'Stored' }),
      ITEM0002: item('ITEM0002', { itemType: 'journalArticle', DOI: '10.1000/two', title: 'Linked' }),
      ITEM0003: item('ITEM0003', { itemType: 'journalArticle', DOI: '10.1000/two', title: 'Duplicate' }),
      ITEM0004: item('ITEM0004', { itemType: 'journalArticle', title: 'No DOI' }),
    };
    const children: Record<string, any[]> = {
      ITEM0001: [item('FILE0001', { itemType: 'attachment', linkMode: 'imported_file', contentType: 'application/pdf' })],
      ITEM0002: [item('URL00001', { itemType: 'attachment', linkMode: 'linked_url', contentType: 'application/pdf' })],
      ITEM0003: [],
      ITEM0004: [],
    };
    const ctx = { router: {
      defaultLibrary: () => library,
      getItem: vi.fn(async (key: string) => structuredClone(parents[key])),
      getItemChildren: vi.fn(async (key: string) => ({ data: structuredClone(children[key] ?? []), totalResults: 0, lastModifiedVersion: 1 })),
    } } as any;

    const result = await fulltextContext.handler({ item_keys: Object.keys(parents) }, ctx);
    const rows = result.structuredContent?.items as any[];
    expect(rows.find((row) => row.item_key === 'ITEM0001')).toMatchObject({ doi: '10.1000/one', attachment_state: 'existing_file_pdf', ownership_state: 'ready' });
    expect(rows.find((row) => row.item_key === 'ITEM0002')).toMatchObject({ attachment_state: 'linked_pdf_url_only', ownership_state: 'review_required', reason: 'duplicate-doi-in-request' });
    expect(rows.find((row) => row.item_key === 'ITEM0003')).toMatchObject({ attachment_state: 'missing_pdf', ownership_state: 'review_required', reason: 'duplicate-doi-in-request' });
    expect(rows.find((row) => row.item_key === 'ITEM0004')).toMatchObject({ ownership_state: 'review_required', reason: 'missing-doi' });
  });
});
