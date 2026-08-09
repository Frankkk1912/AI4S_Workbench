---
name: literature-research
description: >-
  Retrieve, deduplicate, and rank source-database literature evidence into
  auditable files. Use when the user asks to search PubMed, arXiv, Web of
  Science, or other source databases; rank papers; or prepare evidence files
  before Zotero management or scientific prose. Do not use for Zotero-only
  operations or evidence-traced manuscript writing.
---

# Academic Research

## First-run API Onboarding

When this skill is installed through `literature-workbench`, check the
plugin-local onboarding status before the first workbench task:

```text
node <plugin-root>/scripts/onboard.mjs status --output <private-temp>/ai4s-onboarding-status.json
```

If `first_run` is true, proactively tell the user that Zotero Web API, PubMed,
and EasyScholar credentials are optional enhancements, show the
`application_links` from the redacted status file, and state that retrieval,
ranking, and writing basics remain available without them. Also remind the
user that the separate Zotero Desktop XPI must be installed manually to show
AI4S columns and Priority controls; use the returned `zotero_desktop_xpi`
instructions. Never ask the user to paste a key into chat or pass one in
command arguments. Offer the local masked wizard:

```text
node <plugin-root>/scripts/onboard.mjs setup --output <private-temp>/ai4s-onboarding-result.json
```

After presenting the guide, run `status --mark-offered --output ...` so it is
not repeated on every task. Read only the redacted result. On later requests,
use `reconfigure --provider zotero|pubmed|easyscholar --output ...`. If the
plugin-local script is absent, continue with the base skill and do not block
the literature task.

## Overview

Use this skill for retrieval and ranking only. Its default PubMed-first path
creates four auditable files: `search_plan.json`, `ranked_all.json`,
`ranked_all.csv`, and `report.md`. It also matches journals against the bundled
reviewed 2025 JCR/IF table by ISSN unless the user requests
`--no-journal-metrics`; this enriches evidence but neither filters results nor
writes Zotero. The report is an evidence handoff, not a replacement for
manuscript prose. A project already bound to Zotero may hand `report.md` and
its selected ranked evidence to `literature-manager` so the papers and one
current report Note stay together in the same collection.

During the same evidence-synthesis pass that finalizes `report.md`, write one
compact `priority_recommendations.json` sidecar. This is not a second per-paper
audit: selected papers default to Priority 1, and the agent records only papers
promoted to Priority 2 or 3 with terse reason codes. Priority means personal
reading/use priority for the named project, not evidence quality.

When Frank enables Agent Tags for the retrieved batch, use that same synthesis
pass to write `semantic_tag_candidates.json` following
[semantic-tag-recommendations.md](references/semantic-tag-recommendations.md).
It contains compact English candidates keyed by stable evidence ID; final
reuse/new decisions wait for the current Zotero library vocabulary.

**No Evidence, No Conclusion:** do not make scientific claims until saved
retrieval and ranked evidence support them.

## Route Boundaries

- Retrieval and ranking: `literature-research`.
- Zotero matching, import plans, duplicate review, collections, and tags:
  `literature-manager`.
- Evidence-traced review, proposal, introduction, discussion, or DOCX prose:
  `literature-writing`.

Do not introduce an umbrella coordinator. Hand off the saved files directly to
the next narrow skill when the user's request crosses a boundary.

## Quick Start

For the usual literature search, use the single PubMed-first command:

```bash
uv run literature-research/scripts/literature_search.py review \
  --question "GPLD1 在心血管疾病中的作用" \
  --pubmed-query "(GPLD1) AND (cardiovascular disease OR heart failure)" \
  --limit 50 \
  --top-n 30 \
  --output literature_run
```

On Windows PowerShell, use PowerShell backticks for continuation:

```powershell
uv run literature-research/scripts/literature_search.py review `
  --question "GPLD1 在心血管疾病中的作用" `
  --pubmed-query "(GPLD1) AND (cardiovascular disease OR heart failure)" `
  --limit 50 `
  --top-n 30 `
  --output literature_run
```

Inspect `search_plan.json` for the exact query, sources, limits, and filters;
inspect ranking reasons in `ranked_all.json`; then revise the synthesis in the
same `report.md` from saved evidence only. A capped search is never
comprehensive.

## Default Workflow

1. Clarify only ambiguity that changes the biological target or inclusion
   criteria. Otherwise proceed without a planning-only loop.
2. Run `review` with explicit `--limit`, `--top-n`, and output directory.
3. Keep the four script-produced canonical artifacts. Journal metrics are matched by default
   from the bundled reviewed table; use `--journal-metrics` only for an audited
   override, or `--no-journal-metrics` to opt out.
4. Do not create raw copies, renamed result
   files, a second topical report, or ad hoc helper scripts by default.
5. Inspect relevance, score reasons, database coverage, result cap, and
   abstract/full-text status before making a conclusion.
6. While finalizing the report, write `priority_recommendations.json` following
   [priority-recommendations.md](references/priority-recommendations.md). Do not
   start another LLM pass or write prose reasons per paper.
7. If Agent Tags are enabled, write `semantic_tag_candidates.json` in the same
   pass. Use zero to four English tags per paper, or at most two without an
   abstract; never force dimensions or tag a narrow entity that is not a
   principal study subject.
8. Hand `ranked_all.json`, `priority_recommendations.json`, and any enabled
   `semantic_tag_candidates.json` to
   `literature-manager` for Zotero work; hand ranked evidence with `report.md`
   to `literature-writing` for prose. For an existing Zotero-bound project,
   also hand the finalized `report.md` to `literature-manager` for incremental
   project sync. Do not expose plan paths, hashes, or receipts during the
   ordinary exact-ID path.

When the request includes a new Zotero import, EasyScholar enrichment is a
default handoff action after the final selection exists. Run
`enrich-easyscholar --selection-json selection.json` so only selected journal
records are queried; the command skips preprints, deduplicates journal calls,
uses the persistent cache and rate limiter, and never saves the API key. If the
key/API is unavailable, it writes an `unavailable` enrichment summary and
preserves the evidence so bibliographic import can continue with missing
metrics reported. Pass the enriched JSON to `literature-manager`. Do not use
this default to refresh an existing Zotero collection; backfill requires an
explicit user request.

The standalone `review --easyscholar` option remains available for an
explicit all-ranked enrichment, but is not the efficient Zotero import path.
On Windows, the private academic-research configuration and default
EasyScholar cache live below `%LOCALAPPDATA%\frank-ai4s`; an existing
`~\.config\frank-ai4s` configuration remains readable and is migrated on the
next config write.

## Hard Safety Rules

- Source-database retrieval precedes Zotero; Zotero presence never proves
  search completeness.
- Label abstract-level evidence and preprints. Do not imply full-text review,
  peer review, impact factor, or citation counts that were not retrieved.
- Use `web-access` only for authorized logged-in/campus sources, official Web
  of Science exports, full text, or page-level verification. Do not bypass
  CAPTCHAs, access controls, licenses, or export limits.
- Do not commit Web of Science exports, subscription PDFs, cookies, browser
  profiles, private or unlicensed replacement journal-metric tables, or
  unpublished research data.

## Advanced Recipes

Advanced source routing, query expansion, journal filters, citation enrichment,
subagent work, and low-level commands are intentionally outside the default
path. Read [advanced-recipes.md](references/advanced-recipes.md) only when the
user explicitly requests one of them. Use the linked source, query-planning,
ranking, and workflow-contract references for the applicable constraints.
The bundled `references/jcr_journals_2025.csv` is the default IF/JCR lookup
source. It is versioned 2025 data and does not supply CAS zones; do not label
it as 2026 metrics. A newer audited CSV can be supplied explicitly through
`--journal-metrics`.

## Common Mistakes

- Do not claim the capped default search is exhaustive.
- Do not replace evidence retrieval with library search, or evidence writing
  with a retrieval report.
- Do not add arXiv, Web of Science, citation enrichment, or journal metrics
  unless the question requires them.
- Do not equate deterministic search `rank`/`score` with Priority or evidence
  quality. Use report role to promote only core/important papers.
- Do not copy PubMed keywords into Agent Tags or treat semantic tags as claim
  evidence. Reconcile candidates against the persistent Zotero vocabulary.
- Do not query EasyScholar for every raw hit when only a selected subset will
  enter Zotero, and do not fail the bibliographic import solely because journal
  metrics are unavailable.
