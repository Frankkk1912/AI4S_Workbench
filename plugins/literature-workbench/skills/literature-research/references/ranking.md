# Ranking Algorithm / 排序算法

All ranking is deterministic, transparent, and non-LLM. Every score increment is recorded in `score_reasons` for audit.

## Base Score (default, always applied)

| Signal | Points | Condition |
|---|---|---|
| Title keyword match | +6 per term | Term (case-insensitive) found in title |
| Abstract keyword match | +3 per term | Term (case-insensitive) found in abstract |
| MeSH term match | +2 per term | Term (case-insensitive) found in MeSH descriptors |
| Recency ≤ 5 years | +2 | Published within 5 years of search date |
| Recency ≤ 10 years | +1 | Published within 10 years (but > 5) |
| DOI available | +0.5 | Record has a DOI |
| Review article | +1 | Article type contains "Review" |

Terms come from the query plan's `core_terms` and `expanded_terms`. The same term can match title, abstract, and MeSH independently (no deduplication of term-level bonuses).

## Citation Weighting (opt-in via `--citation-weight`)

Citation weighting is **off by default** (`--citation-weight none`) to preserve backward compatibility. When enabled, citation data must first be fetched via `enrich-citations`.

### `--citation-weight log` (log-scaled)

```
bonus = min(5.0, log10(citation_count + 1))
```

- Caps at 5.0 points (≈ 100,000 citations).
- Log scale prevents a highly-cited review from drowning out a directly-on-topic paper with fewer citations.
- Example: 9 citations → +1.0; 99 → +2.0; 999 → +3.0; 9,999 → +4.0; 99,999 → +5.0.

### `--citation-weight bucket` (threshold-based)

| Threshold | Points | Condition |
|---|---|---|
| Total citations ≥ 50 | +2 | `citation_count ≥ 50` |
| Total citations ≥ 10 | +1 | `citation_count ≥ 10` (but < 50) |

### Informational mode (`none`)

When `--citation-weight none` (default), citation counts are still recorded in `score_reasons` as informational text (e.g., "citation count: 42 (not weighted)") but contribute 0 points to the score.

## Citation Data Sources

| Provider | Fields | Rate Limit | Notes |
|---|---|---|---|
| Crossref | is-referenced-by-count, references-count | Polite pool with mailto | DOI-based point-in-time snapshot |

Citation counts are point-in-time snapshots from the enrichment date. Different providers may report different counts for the same paper. The report always labels which provider contributed each count.

## Journal Metrics Bonus

When `enrich-journal-metrics` is used, records with matching ISSN get:

| Signal | Points | Condition |
|---|---|---|
| Journal metrics matched | +1.0 | Record's ISSN found in journal metrics CSV |

This bonus is applied by `enrich-journal-metrics`, not by `merge-rank`.

## Audit Trail

Every score modification is recorded in `score_reasons` (list of strings). The ranked JSON preserves all reasons for each record. The CSV includes a `score_reasons` column.

No LLM-generated scores are used at any point in the ranking pipeline.
