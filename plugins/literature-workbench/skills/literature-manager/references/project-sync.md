# Lightweight Zotero Project Sync

Use this route after `literature-research` finalizes `report.md` and ranked
evidence. It keeps one project collection, selected papers, and one current
AI4S report Note together without turning audit mechanics into user work.

## User Contract

The ordinary result is one compact summary: collection name, created count,
reused count, and whether the report was created, updated, or unchanged. Do not
show internal plan paths, hashes, receipts, or per-paper JSON unless diagnosing
a failure. `report.md` remains the auditable source; the Zotero Note is its
synced reading copy. Keep human annotations in a separate Note.

## Low-Risk Automatic Path

- Reuse one unique DOI or PMID match.
- Create a supported record with a DOI or PMID after a complete live query
  finds no identifier match.
- Add, but never remove, project tags and collection membership.
- Create a missing collection with one unambiguous exact name.
- Create or update the one AI4S-owned report Note.
- Resume an internal idempotent receipt after a partial transient failure.
- Write available EasyScholar metrics during the same create/reuse operation:
  merge only the managed `AI4S-Metrics` Extra block, synchronize current
  `JCR:*`/`CAS:*` tags, and preserve all user Extra and unrelated tags.

## High-Risk Escalation

Stop and show a short risk summary for title-only or conflicting matches,
missing stable IDs, truncated queries, ownership/version conflicts, destructive
implications, duplicate collections/notes, manual report edits, or more than 50
new records. Only the large-create case may proceed after one explicit
confirmation using the returned review ID. Identity and ownership conflicts
must be resolved first.

## Inputs and Recovery

Required inputs are the project slug, search date, finalized `report.md`, and
ranked evidence JSON. The evidence should already contain selected-only
EasyScholar enrichment for a new import. The collection name is required only on first sync; later
runs recover it from the private binding. An optional compact selection JSON
restricts the collection; otherwise all ranked records are selected. Never pass
an uncapped raw retrieval dump as ranked evidence.

The sync derives the metric display year from the search date (`year - 1`) and
returns `metrics_updated`, `metrics_missing`, `metrics_preprint_skipped`, and
`display_metric_year`. Missing metrics never block bibliography writes.

Zotero rate limiting uses the existing Web API client. Private receipts are
keyed by internal content hash. Reruns skip completed writes and resume pending
ones, so a report failure after paper import does not duplicate papers.
