# PubMed Database Pattern

## Access Mode
- Use `literature_search.py search-pubmed` through NCBI E-utilities first.
- Use browser access only for page-level verification, related-link inspection, or manual checks that the API output cannot answer.

## Effective Pattern
1. Build a query plan and review synonyms, MeSH-style terms, organism constraints, article types, and exclusions.
2. Run `search-pubmed` with an explicit `--limit` and save JSON output.
3. If journal-quality filters matter, generate an ISSN filter audit from a local metrics CSV, but keep the broad PubMed records as the primary retrieval output.
4. Merge and rank saved JSON records, then use `enrich-journal-metrics --filter-to-matches` for local CAS/JCR/IF filtering by ISSN.
5. Use a PubMed ISSN second pass only when the broad result set is too large to download and the ISSN query is short enough for NCBI.
6. Inspect `score_reasons` and `journal_metrics_filter` before writing conclusions.

## Evidence Files
- Query plan JSON.
- PubMed records JSON.
- Optional ISSN filter audit JSON/Markdown.
- Optional local journal-filtered ranked JSON/CSV.
- Ranked JSON/CSV and final Markdown report.

## Known Traps
- A capped `--limit` result is not exhaustive.
- Very long ISSN filters can trigger NCBI request failures; prefer local filtering for large Q/IF journal sets.
- PubMed queries may miss publisher-ahead-of-print or non-indexed records.
- Do not infer full-text findings from abstract metadata without saying so.
