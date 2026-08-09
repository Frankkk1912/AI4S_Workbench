import { mkdtemp, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { FulltextBroker } from '../src/broker.js';
import { sha256 } from '../src/lib/canonical.js';
import { FulltextStore } from '../src/store.js';
import type { Candidate, FetchRecord, FulltextAdapter } from '../src/domain.js';
import { validateFulltextHandoff } from '../../literature-zotero-mcp/src/features/fulltext/handoff-contract.js';

const directories: string[] = [];

async function temporaryDirectory(): Promise<string> {
  const path = await mkdtemp(join(tmpdir(), 'literature-fulltext-test-'));
  directories.push(path);
  return path;
}

afterEach(() => { directories.length = 0; });

class FakeAdapter implements FulltextAdapter {
  constructor(private readonly available: Set<string>) {}
  providerNames(): string[] { return ['fixture-oa']; }
  async resolveCandidates(record: FetchRecord): Promise<Candidate[]> {
    return this.available.has(record.evidenceId)
      ? [{ provider: 'candidate-oa-url', url: 'https://oa.example.org/article.pdf', accessMode: 'open_access_http', documentVersion: 'version_of_record', fileRole: 'main_article' }]
      : [];
  }
  async download(): Promise<{ bytes: Uint8Array; contentType: string }> {
    return { bytes: new TextEncoder().encode('%PDF-1.4\nfixture bytes for a verified PDF\n'), contentType: 'application/pdf' };
  }
}

async function waitFor(broker: FulltextBroker, jobId: string, state: string): Promise<Record<string, any>> {
  // Windows CI can take longer than a half second to flush the asynchronous
  // filesystem-backed state transition after a PDF parser import.
  for (let attempt = 0; attempt < 300; attempt += 1) {
    const status = await broker.status(jobId);
    if (status.state === state) return status as Record<string, any>;
    await new Promise((resolve) => setTimeout(resolve, 10));
  }
  throw new Error(`Timed out waiting for ${jobId} to reach ${state}.`);
}

function request(records: Array<Partial<FetchRecord>> = []): any {
  return {
    requestId: 'a'.repeat(64), routePolicy: 'oa_only', records: records.length ? records.map((record, index) => ({
      evidenceId: record.evidenceId ?? `doi:10.1000/example-${index}`,
      zoteroItemKey: record.zoteroItemKey ?? `ABCD123${index}`,
      doi: record.doi ?? `10.1000/example-${index}`,
      title: record.title ?? `Example article ${index}`,
      itemType: record.itemType ?? 'journalArticle', candidateUrls: record.candidateUrls ?? [],
    })) : [{ evidenceId: 'doi:10.1000/example', zoteroItemKey: 'ABCD1234', doi: '10.1000/example', title: 'Example article', itemType: 'journalArticle', candidateUrls: [] }],
  };
}

describe('FulltextBroker OA-only jobs', () => {
  it('writes a compact hashed handoff only for strongly verified OA PDFs', async () => {
    const root = await temporaryDirectory();
    const bytes = new TextEncoder().encode('%PDF-1.4\nfixture bytes for a verified PDF\n');
    const broker = new FulltextBroker(
      new FulltextStore(join(root, 'data'), join(root, 'exchange')),
      new FakeAdapter(new Set(['doi:10.1000/example-0'])),
      async () => ({ sha256: sha256(bytes), md5: 'b'.repeat(32), bytes: bytes.byteLength, pageCount: 1, level: 'strong_identifier', doiMatch: true, titleMatch: true }),
    );
    const submitted = await broker.submit(request([{}, { evidenceId: 'doi:10.1000/missing', zoteroItemKey: 'EFGH5678' }]));
    const retry = await broker.submit(request([{}, { evidenceId: 'doi:10.1000/missing', zoteroItemKey: 'EFGH5678' }]));
    expect(retry).toEqual({ jobId: submitted.jobId, reused: true });
    const status = await waitFor(broker, submitted.jobId, 'partial');
    expect(status.counts).toMatchObject({ requested: 2, verified: 1, unavailable: 1 });
    expect(status.handoff_id).toMatch(/^fth-/);
    const handoff = JSON.parse(await readFile(join(root, 'exchange', 'handoffs', `${status.handoff_id}.json`), 'utf8'));
    expect(validateFulltextHandoff(handoff)).toMatchObject({ handoff_id: status.handoff_id, handoff_hash: status.handoff_hash });
    expect(handoff.records).toHaveLength(1);
    expect(handoff.records[0]).toMatchObject({ evidence_id: 'doi:10.1000/example-0', retrieval: { file_role: 'main_article' }, verification: { level: 'strong_identifier' } });
    expect(handoff).not.toHaveProperty('artifact_path');
    expect(await readFile(join(root, 'exchange', 'artifacts', `${sha256(bytes)}.pdf`))).toEqual(Buffer.from(bytes));
  });

  it('rejects request-id reuse for a different canonical request', async () => {
    const root = await temporaryDirectory();
    const broker = new FulltextBroker(new FulltextStore(join(root, 'data'), join(root, 'exchange')), new FakeAdapter(new Set()), async () => ({ sha256: 'a'.repeat(64), md5: 'b'.repeat(32), bytes: 500, pageCount: 1, level: 'strong_identifier', doiMatch: true, titleMatch: true }));
    await broker.submit(request());
    await expect(broker.submit({ ...request(), records: [{ ...request().records[0], title: 'Different article' }] }))
      .rejects.toEqual(expect.objectContaining({ code: 'REQUEST_ID_CONFLICT' }));
  });
});
