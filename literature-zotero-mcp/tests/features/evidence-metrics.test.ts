import { describe, expect, it } from 'vitest';
import {
  displayMetricYear,
  isPreprintEvidence,
  mergeMetricIntoExtra,
  mergePlannedMetricsExtra,
  metricFromEvidence,
  synchronizeCurrentMetricTags,
} from '../../src/features/evidence-metrics.js';

describe('default EasyScholar metrics on new imports', () => {
  it('uses the task year minus one only for the display label', () => {
    expect(displayMetricYear('2026-07-17')).toBe(2025);
    expect(() => displayMetricYear('2026-02-30')).toThrow(/valid calendar date/);
  });

  it('maps EasyScholar latest fields and does not substitute bundled metrics', () => {
    expect(metricFromEvidence({ source: 'pubmed', journal_metrics: { impact_factor: 10 } }, 'a'.repeat(64))).toBeNull();
    expect(metricFromEvidence({
      source: 'pubmed',
      easyscholar: {
        official_rank: { all: { sciif: '5.8', sciif5: '6.3', sci: 'Q1', sciUp: '生物学1区' } },
        fetched_at: '2026-07-17T00:00:00Z',
      },
    }, 'a'.repeat(64))).toMatchObject({
      impact_factor: 5.8, impact_factor_5y: 6.3, jcr_zone: 'Q1', cas_zone: '1区',
      source_label: 'easyscholar-latest', retrieved_at: '2026-07-17',
    });
  });

  it('merges reuse Extra and replaces only current JCR/CAS tags', () => {
    const current = 'PMID: 42\nUser note: keep\nAI4S-Metrics: {"schema_version":2,"by_year":{"2024":{"impact_factor":4}}}';
    const planned = mergeMetricIntoExtra('', 2025, {
      impact_factor: 5.8, jcr_zone: 'Q1', cas_zone: '1区', source_label: 'easyscholar-latest', source_sha256: 'b'.repeat(64),
    })!;
    const merged = mergePlannedMetricsExtra(current, planned)!;
    expect(merged).toContain('User note: keep');
    expect(merged).toContain('"2024"');
    expect(merged).toContain('"2025"');
    expect(synchronizeCurrentMetricTags([{ tag: 'manual' }, { tag: 'JCR:Q2' }], merged)).toEqual(expect.arrayContaining([
      { tag: 'manual' }, { tag: 'JCR:Q1' }, { tag: 'CAS:1区' },
    ]));
  });

  it('skips preprints even when metric-shaped data is present', () => {
    const record = { source: 'arxiv', article_types: ['Preprint'], easyscholar: { official_rank: { all: { sciif: 99 } } } };
    expect(isPreprintEvidence(record)).toBe(true);
    expect(metricFromEvidence(record, 'c'.repeat(64))).toBeNull();
  });
});
