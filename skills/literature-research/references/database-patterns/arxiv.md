# arXiv Database Pattern

## Access Mode
- Use `literature_search.py search-arxiv` through the public arXiv API first.
- Use browser access only when verifying a specific arXiv page, PDF availability, author version, or cross-link.

## Effective Pattern
1. Keep arXiv queries compact; avoid PubMed-style synonym-heavy Boolean strings.
2. Run `search-arxiv` with an explicit `--limit` and save JSON output.
3. Merge arXiv records with peer-reviewed databases only after labeling them as preprints.
4. Verify peer-review status separately before using arXiv evidence as established biomedical evidence.

## Evidence Files
- Query plan JSON.
- arXiv records JSON.
- Ranked JSON/CSV and final Markdown report.

## Known Traps
- arXiv metadata is not a peer-review signal.
- Biomedical search recall is weaker than PubMed for synonym-rich disease queries.
- Preprints should not be mixed with clinical or mechanistic claims without clear labeling.
