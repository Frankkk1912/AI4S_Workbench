import { describe, expect, it } from 'vitest';
import { canonicalMetricsPlanHash, validateMetricsPlan } from '../../src/features/metrics-plan.js';

describe('metrics plan zone-only payloads', () => {
  it('accepts a CAS/JCR-only update without inventing an IF', () => {
    const plan: any = {
      schema_version: '1.0', plan_type: 'zotero-metrics', created_at: '2026-07-14T00:00:00Z', plan_hash: '',
      target: { library_type: 'user', library_id: 1 },
      metrics: { metrics_year: 2026, source_label: 'easyscholar-2026', source_sha256: 'a'.repeat(64) },
      actions: [{ item_key: 'ITEM0001', expected_version: 4, title: 'Paper', issns: [], decision: 'update', reason_codes: ['easyscholar-match'], metric: { jcr_zone: 'Q1', cas_zone: '1区', source_label: 'easyscholar-2026', source_sha256: 'a'.repeat(64) } }],
      summary: { selected: 1, update: 1, skip: 0 },
    };
    plan.plan_hash = canonicalMetricsPlanHash(plan);
    expect(validateMetricsPlan(plan).actions[0]?.metric).not.toHaveProperty('impact_factor');
  });

  it('accepts five-year IF and typed publication metrics', () => {
    const plan: any = {
      schema_version: '1.0', plan_type: 'zotero-metrics', created_at: '2026-07-16T00:00:00Z', plan_hash: '',
      target: { library_type: 'user', library_id: 1 },
      metrics: { metrics_year: 2025, remove_years: [2026], source_label: 'easyscholar-2025', source_sha256: 'a'.repeat(64) },
      actions: [{ item_key: 'ITEM0001', expected_version: 4, title: 'Paper', issns: [], decision: 'update', reason_codes: ['easyscholar-match'], metric: { impact_factor: 9.2, impact_factor_5y: 8.5, jcr_zone: 'Q1', cas_zone: '1区', publication_metrics: [{ code: 'cas_major', value: '医学1区' }, { code: 'cas_top', value: true }], retrieved_at: '2026-07-16', source_label: 'easyscholar-2025', source_sha256: 'a'.repeat(64) } }],
      summary: { selected: 1, update: 1, skip: 0 },
    };
    plan.plan_hash = canonicalMetricsPlanHash(plan);
    expect(validateMetricsPlan(plan).actions[0]?.metric).toMatchObject({ impact_factor_5y: 8.5, retrieved_at: '2026-07-16' });
  });

  it('rejects an update with no metric fields', () => {
    const plan: any = {
      schema_version: '1.0', plan_type: 'zotero-metrics', plan_hash: 'sha256:' + '0'.repeat(64),
      target: { library_type: 'user', library_id: 1 },
      metrics: { metrics_year: 2026, source_label: 'x', source_sha256: 'a'.repeat(64) },
      actions: [{ item_key: 'ITEM0001', expected_version: 1, title: 'Paper', issns: [], decision: 'update', reason_codes: [], metric: {} }],
      summary: { selected: 1, update: 1, skip: 0 },
    };
    expect(() => validateMetricsPlan(plan)).toThrow(/needs IF, zone, or publication metrics/);
  });
});
