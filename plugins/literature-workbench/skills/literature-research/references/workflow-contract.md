# Workflow Contract: n8n, Scripts, Agent, and Subagents

Use this reference when optimizing or executing the academic research workflow.
The goal is to keep repeatable work in scripts and reserve agent reasoning for
scientific judgment.

## Core Principle

- A **script command** is a deterministic node: API calls, XML/CSV/JSON parsing,
  ISSN filtering, deduplication, ranking, citation enrichment, report rendering.
- The **main agent** is a quality gate: query semantics, ambiguity resolution,
  evidence inspection, retry decisions, final synthesis.
- A **subagent** is an independent evidence worker: one database, one source, or
  one separable research branch. It is not a replacement for every n8n node.

## n8n Review Workflow Mapping

| n8n node class | literature-research equivalent | Owner |
|---|---|---|
| Chat trigger | user request | main agent |
| LLM PubMed query generator | `plan` / `expand-query` plus agent review | main agent + script |
| ESearch / EFetch HTTP nodes | `search-pubmed` | script |
| XML parse, article split, ISSN extraction | internal parser in `search-pubmed` outputs | script |
| Prepare CSV / save files | script `--output` paths | script |
| IF/CAS/JCR filter scripts | `journal-filter-query` for audit, `enrich-journal-metrics --filter-to-matches` for local filtering | script |
| Generate second PubMed query | explicit fallback with `compose-pubmed-query`, then `search-pubmed` only when local-first retrieval is impractical | script, agent reviews semantics |
| Review outline agent | evidence-based outline from ranked JSON/report | main agent |
| Review writing agent | final synthesis from saved evidence, written back into `report.md` or routed to `literature-writing` for manuscript prose | main agent / literature-writing |
| Zotero collection/report/paper management | `literature-manager` lightweight project sync after ranked evidence and `report.md` exist | downstream Zotero skill |
| Reference renumber / docx export | downstream writing/document workflow, not core retrieval | literature-writing / document tooling |

## Agent Intervention Points

The agent should intervene before:

1. First retrieval, to ensure the biological target and search scope are right.
2. Query expansion, to add synonyms, MeSH terms, species, exclusions, and disease
   families in an auditable scaffold.
3. Local journal-quality filtering, to confirm the journal-quality constraint is
   intended and not accidentally narrowing the biology; use PubMed second-pass
   ISSN filtering only as an explicit fallback for oversized broad searches.
4. Final synthesis, after inspecting ranked JSON, score reasons, abstracts,
   limitations, and links. The synthesis must be merged into `report.md` with
   the search strategy and evidence table, not written as a separate topical
   Markdown report.

The agent should not intervene for:

- Low-level XML/CSV/JSON parsing.
- ISSN normalization or de-duplication.
- Joining PubMed query fragments for an approved second-pass fallback.
- Ranking arithmetic.
- File naming and saved evidence manifests.
- Creating duplicate report files to separate "search strategy" from "research
  findings"; the canonical report is `report.md`.
- Writing ad hoc helper scripts such as `filter_q1_if.py`; reusable script
  commands must own deterministic filtering and enrichment.
- Renaming canonical outputs into target-specific duplicate files such as
  `<target>_*_records.json`, `<target>_*_records.csv`, `*_metrics.json`, or
  `*_metrics.csv`.
- Searching Zotero instead of source databases when the user requested current,
  auditable literature retrieval. Zotero can confirm library reuse only after
  evidence ranking.

## Subagent Boundary

Use subagents only when the work can return a complete evidence handoff:

- PubMed source retrieval.
- arXiv source retrieval.
- Web of Science browser search plus official export import.
- Separate research questions or target/disease branches.

Do not create subagents for:

- `search-pubmed` ESearch vs EFetch internals.
- ISSN filtering.
- CSV conversion.
- Citation formatting.
- Markdown rendering.

Required subagent handoff fields: exact query, filters/limits, count, output
paths, top records with IDs/DOIs/URLs, and limitations. The main agent owns the
final merge/rank and scientific conclusion.

## Downstream Literature Workbench Boundary

The production literature workflow is split into three skills:

1. `literature-research`: source search, retrieval, filtering, ranking, and
   evidence report drafting.
2. `literature-manager`: Zotero library matching, deduplication,
   collection/tag/note sync planning, and approved API updates.
3. `literature-writing`: review/proposal/manuscript prose from ranked evidence
   and optional Zotero metadata.

The interface is file-based:

- `literature-research` writes ranked evidence JSON/CSV and `report.md`.
- A Zotero-bound project hands selected ranked evidence plus the finalized
  report to `literature-manager`; exact-ID incremental sync is quiet and
  idempotent, while ambiguous or conflicting cases are surfaced for review.
- `literature-manager` reads ranked evidence and `report.md`. Recurring exact-ID
  project sync updates Zotero with private runtime state; lower-level or
  high-risk workflows still write `zotero_match.json` / `zotero_sync_plan.json`.
- For a new Zotero import, the finalized selection is enriched through
  EasyScholar before this handoff. Only selected journal records are queried;
  preprints are skipped and an unavailable API is recorded without blocking
  bibliographic import.
- `literature-writing` reads evidence reports plus optional Zotero metadata and
  writes citation-traced Markdown sections.

Future plugins may package these skills together, but plugin packaging must not
move search, Zotero management, or writing logic out of the production skills.
