import { describe, expect, it } from 'vitest';
import {
  canonicalFulltextHandoffHash,
  fulltextFetchRequestSchema,
  fulltextJobSchema,
  validateFulltextHandoff,
} from '../../src/features/fulltext/handoff-contract.js';

function handoff() {
  const unsigned = {
    schema_version: 1 as const, handoff_id: 'fth-12345678', job_id: 'ft-12345678', request_id: 'a'.repeat(64),
    created_at: '2026-07-22T00:00:00.000Z',
    records: [{
      evidence_id: 'doi:10.1000/example', zotero_item_key: 'ABCD1234',
      expected_parent: { doi: '10.1000/example', title: 'Example article' },
      retrieval: { status: 'verified' as const, provider: 'pmc', access_mode: 'open_access_http' as const, document_version: 'version_of_record' as const, file_role: 'main_article' as const, retrieved_at: '2026-07-22T00:00:00.000Z' },
      artifact: { artifact_id: `sha256:${'b'.repeat(64)}`, sha256: 'b'.repeat(64), md5: 'c'.repeat(32), bytes: 123456, content_type: 'application/pdf' as const, page_count: 12 },
      verification: { level: 'strong_identifier' as const, doi_match: true as const, title_match: true as const },
    }],
  };
  return { ...unsigned, handoff_hash: canonicalFulltextHandoffHash(unsigned) };
}

describe('Fulltext handoff contract', () => {
  it('requires a canonical verified-main-article handoff', () => {
    expect(validateFulltextHandoff(handoff())).toMatchObject({ handoff_id: 'fth-12345678' });
    const tampered = handoff();
    tampered.records[0]!.artifact.bytes = 1;
    expect(() => validateFulltextHandoff(tampered)).toThrow(/hash mismatch/);
  });

  it('requires a stable identifier and an internally consistent persisted job', () => {
    const request = fulltextFetchRequestSchema.parse({
      request_id: 'd'.repeat(64), route_policy: 'oa_only', records: [{
        evidence_id: 'doi:10.1000/example', zotero_item_key: 'ABCD1234', doi: '10.1000/example',
        title: 'Example article', item_type: 'journalArticle', candidate_urls: ['https://example.org/article'],
      }],
    });
    expect(request.records).toHaveLength(1);
    expect(() => fulltextFetchRequestSchema.parse({
      ...request, records: [{ ...request.records[0], doi: undefined, arxiv_id: undefined, repository_id: undefined }],
    })).toThrow(/requires doi/);
    expect(() => fulltextJobSchema.parse({
      schema_version: 1, job_id: 'ft-12345678', request_id: request.request_id, route_policy: 'oa_only', state: 'complete',
      created_at: '2026-07-22T00:00:00.000Z', updated_at: '2026-07-22T00:00:01.000Z',
      records: [{ evidence_id: request.records[0]!.evidence_id, zotero_item_key: 'ABCD1234', state: 'verified', error_code: null }],
      user_action_required: false, handoff_id: null, handoff_hash: null,
    })).toThrow(/complete job requires a handoff/);
  });
});
