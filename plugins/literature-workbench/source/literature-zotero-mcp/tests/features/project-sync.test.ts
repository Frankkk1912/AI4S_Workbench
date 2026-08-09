import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { renderReportMarkdown } from '../../src/features/project-sync/report-renderer.js';
import { stableEvidenceId, syncLiteratureProject } from '../../src/features/project-sync/sync.js';

function dataOf(value: any): any { return value?.data ?? value; }
class FakeWeb {
  hasKey = true; collections: any[] = []; items: any[] = []; version = 1; next = 1;
  private key(): string { return `K${String(this.next++).padStart(7, '0')}`; }
  async listCollections(_lib: any, query: any = {}) {
    const start = query.start ?? 0; const data = this.collections.slice(start, start + (query.limit ?? 100));
    return { data, totalResults: this.collections.length, lastModifiedVersion: this.version };
  }
  async listItems(_lib: any, query: any = {}) {
    let found = [...this.items];
    if (query.collectionKey) found = found.filter((item) => (dataOf(item).collections ?? []).includes(query.collectionKey));
    if (query.itemType) found = found.filter((item) => dataOf(item).itemType === query.itemType);
    if (query.q) { const needle = String(query.q).toLowerCase(); found = found.filter((item) => JSON.stringify(dataOf(item)).toLowerCase().includes(needle)); }
    const start = query.start ?? 0; const data = found.slice(start, start + (query.limit ?? 100));
    return { data, totalResults: found.length, lastModifiedVersion: this.version };
  }
  async getItem(_lib: any, key: string) {
    const item = this.items.find((candidate) => candidate.key === key); if (!item) throw new Error('not found'); return structuredClone(item);
  }
  async writeCollections(_lib: any, objects: any[]) {
    const successful = objects.map((object, index) => { const key = this.key(); const version = ++this.version; this.collections.push({ key, version, data: { ...object, key, version } }); return { index, key, version }; });
    return { successful, unchanged: [], failed: [], newLibraryVersion: this.version };
  }
  async writeItems(_lib: any, objects: any[]) {
    const successful = objects.map((object, index) => { const key = this.key(); const version = ++this.version; this.items.push({ key, version, data: { ...structuredClone(object), key, version } }); return { index, key, version }; });
    return { successful, unchanged: [], failed: [], newLibraryVersion: this.version };
  }
  async patchItem(_lib: any, key: string, patch: any, _version: number) {
    const item = this.items.find((candidate) => candidate.key === key); if (!item) throw new Error('not found');
    item.version = ++this.version; item.data = { ...item.data, ...structuredClone(patch), version: item.version }; return item.version;
  }
}
async function fixture(records: any[]) {
  const dir = await mkdtemp(join(tmpdir(), 'project-sync-')); const reportPath = join(dir, 'report.md'); const evidencePath = join(dir, 'ranked_all.json');
  await writeFile(reportPath, '# Literature Report\n\n## Answer\nEvidence-based answer.\n', 'utf8');
  await writeFile(evidencePath, JSON.stringify({ records }), 'utf8'); return { dir, reportPath, evidencePath };
}
function context(dataDir: string, web: FakeWeb): any { return { config: { dataDir }, web, schema: { validateItem: async () => ({ valid: true, errors: [] }) } }; }
const record = { source: 'pubmed', id: '123', title: 'A stable-ID study', doi: '10.1000/test.1', pmid: '12345678', authors: ['Smith J'], journal: 'Test Journal', date: '2025', article_types: ['Journal Article'] };

describe('project sync', () => {
  it('renders report tables and escapes raw HTML', () => {
    const html = renderReportMarkdown('# Report\n\n| A | B |\n|---|---|\n| <x> | [link](https://example.com) |');
    expect(html).toContain('<h1>Report</h1>'); expect(html).toContain('<table>'); expect(html).toContain('&lt;x&gt;'); expect(html).toContain('<a href="https://example.com">link</a>');
  });
  it('uses stable identifiers and rejects a conflicting supplied ID', () => {
    expect(stableEvidenceId(record)).toBe('doi:10.1000/test.1'); expect(() => stableEvidenceId({ ...record, evidence_id: 'pmid:12345678' })).toThrow(/mismatch/);
  });
  it('creates once, reuses on rerun, and updates the same report Note', async () => {
    const files = await fixture([record]); const priorityPath = join(files.dir, 'priority_recommendations.json');
    await writeFile(priorityPath, JSON.stringify({ schema_version: '1.0', artifact_type: 'literature-priority-recommendations', scope: 'test-project', review_depth: 'abstract', default_for_selected: 1, recommendations: { 'doi:10.1000/test.1': { priority: 3, reason_codes: ['core-conclusion'] } } }), 'utf8');
    const web = new FakeWeb(); const ctx = context(files.dir, web);
    const input = { projectSlug: 'test-project', collectionName: 'Test Project', searchDate: '2026-07-17', reportPath: files.reportPath, evidencePath: files.evidencePath, priorityRecommendationsPath: priorityPath };
    const first = await syncLiteratureProject(ctx, { type: 'user', id: 1 }, input);
    expect(first).toMatchObject({ status: 'complete', created: 1, report: 'created' }); expect(web.collections).toHaveLength(1);
    expect(dataOf(web.items.find((item) => dataOf(item).itemType === 'journalArticle')).tags).toContainEqual({ tag: 'AI4S:Priority:3' });
    const second = await syncLiteratureProject(ctx, { type: 'user', id: 1 }, { ...input, collectionName: undefined });
    expect(second).toMatchObject({ status: 'complete', created: 0, reused: 1, report: 'unchanged' });
    await writeFile(files.reportPath, '# Literature Report\n\nUpdated synthesis.\n', 'utf8');
    const third = await syncLiteratureProject(ctx, { type: 'user', id: 1 }, input);
    expect(third.report).toBe('updated'); expect(web.items.filter((item) => dataOf(item).itemType === 'note')).toHaveLength(1);
  });
  it('stops when the managed report was edited in Zotero', async () => {
    const files = await fixture([record]); const web = new FakeWeb(); const ctx = context(files.dir, web);
    const input = { projectSlug: 'manual-edit', collectionName: 'Manual Edit', searchDate: '2026-07-17', reportPath: files.reportPath, evidencePath: files.evidencePath };
    await syncLiteratureProject(ctx, { type: 'user', id: 1 }, input); const note = web.items.find((item) => dataOf(item).itemType === 'note'); note.data.note = '<p>Manual change</p>';
    const result = await syncLiteratureProject(ctx, { type: 'user', id: 1 }, input); expect(result.status).toBe('needs_review'); expect(result.risks).toContain('report-note-manually-modified');
  });
  it('requires one review token above fifty creates', async () => {
    const records = Array.from({ length: 51 }, (_, index) => ({ ...record, id: String(index), doi: `10.1000/batch.${index}`, pmid: String(90000000 + index), title: `Study ${index}` }));
    const files = await fixture(records); const web = new FakeWeb();
    const result = await syncLiteratureProject(context(files.dir, web), { type: 'user', id: 1 }, { projectSlug: 'large-batch', collectionName: 'Large Batch', searchDate: '2026-07-17', reportPath: files.reportPath, evidencePath: files.evidencePath });
    expect(result.status).toBe('needs_review'); expect(result.risks).toEqual(['large-create-batch:51']); expect(result.reviewId).toMatch(/^[0-9a-f]{64}$/); expect(web.items).toHaveLength(0);
  });
});
