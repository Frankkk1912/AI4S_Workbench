---
name: literature-manager
description: >-
  Synchronize recurring literature reports and selected evidence into one Zotero
  collection with low-friction exact-ID updates; prepare compact, reviewable Zotero import plans for high-risk or standalone work; match
  records by DOI/PMID/title-year; provide optional RIS fallback; deduplicate
  candidate records; route explicitly approved plans to a receipt-producing
  Zotero MCP apply step; and generate compact reusable Agent Tags with safe
  automatic cleanup of source tags; and generate explicitly requested one-sentence
  AI Summary metadata from each item's title and abstract. Use when the user asks to connect literature
  evidence to Zotero, safely import a selected evidence batch, organize or
  semantically tag or summarize a project collection, clean automatic tags, or audit duplicates.
---

# Zotero Literature Manager

## First-run API Onboarding

When installed through `ai4s-literature-workbench`, follow the shared
plugin-local onboarding check before the first workbench task:

```text
node <plugin-root>/scripts/onboard.mjs status --output <private-temp>/ai4s-onboarding-status.json
```

If `first_run` is true, explain the optional Zotero Web API, PubMed, and
EasyScholar enhancements using the report's application links. State plainly
that missing credentials do not block the basic literature workflow. Also
prompt the user to install the separate Zotero Desktop XPI manually for AI4S
columns and Priority controls, using the report's `zotero_desktop_xpi`
instructions. Never request a credential in chat or put one in command
arguments; direct the user to the local masked `setup` wizard. Mark the guide
offered after presenting it.
Use `reconfigure --provider ...` only when requested. If the onboarding script
is unavailable, proceed with the skill and report only the capability that is
actually missing.

## Overview
Use this skill to connect saved literature evidence with Frank's Zotero library
without letting Zotero replace source-database retrieval. Zotero is the
management and reuse layer; PubMed, Web of Science, arXiv, and campus sources
remain the evidence discovery layer.

Default to a **low-friction user experience**. Engineering artifacts are safety
mechanisms, not user tasks: do not expose plan files, hashes, receipt paths, or
long JSON during the ordinary exact-ID project-sync path. Surface a compact
risk summary only when ambiguity, ownership conflict, destructive implications,
or a large create batch requires Frank's decision. This policy reduces token
and execution cost without weakening private version checks and receipts.

The hard rule is **No Evidence, No Conclusion**. A Zotero item proves that a
record exists in the library, not that the scientific claim is supported.

For every new import, consume the selected EasyScholar-enriched evidence by
default. The ordinary project-sync path automatically writes available latest
metrics for both creates and exact-ID reuses. It stores IF, 5-Year IF, JCR, and
CAS in versioned `AI4S-Metrics` Extra; all four render as colored metric
columns, while only current `JCR:*` and `CAS:*` values also become native
Zotero tags. Missing metrics and preprint skips are reported but do not block
bibliographic import. Existing-collection backfill runs only when Frank asks
for it explicitly.

## Dependencies
- `literature-research`: use first for search plans, raw retrieval, ranked
  evidence JSON/CSV, and evidence-first reports.
- `literature-writing`: use after Zotero matching when the user wants review,
  proposal, or manuscript prose with traceable citations.
- `web-access`: use only for live Zotero web pages, login-required sources, or
  campus-network database access.

## Quick Start
For a recurring deep-search project, prefer the high-level MCP tool
`zotero_sync_literature_project`. It keeps selected ranked evidence and one
AI4S-owned Current Report Note in the same collection. The first sync binds the
project and requires a collection name; later runs need only the project slug
and reuse the binding to update the same Note. Omit a selection artifact only
when all ranked records are intended for the collection. Read
[project-sync.md](references/project-sync.md) for the risk boundaries.

The lower-level reviewed import-plan path remains available for explicitly
high-risk or standalone batch imports.

Before either new-import path, run the selected-only EasyScholar handoff from
`literature-research`. The display year is derived from the task search date
(`year - 1`; a 2026 task displays `IF(2025)`); the API response itself is
treated as latest and needs no metric-year configuration.

Create one reviewed import plan from explicitly selected stable evidence IDs:

```bash
uv run literature-manager/scripts/zotero_literature_manager.py plan-import \
  --evidence ranked_all.json \
  --selection-json selection.json \
  --project gpld1-cvd \
  --search-date 2026-07-12 \
  --collection-name "GPLD1 cardiovascular disease" \
  --library-type user \
  --library-id 19552201 \
  --candidate-limit 50 \
  --priority-recommendations priority_recommendations.json \
  --output zotero_import_plan.json
```

Windows PowerShell equivalent:

```powershell
uv run literature-manager/scripts/zotero_literature_manager.py plan-import `
  --evidence ranked_all.json `
  --selection-json selection.json `
  --project gpld1-cvd `
  --search-date 2026-07-12 `
  --collection-name "GPLD1 cardiovascular disease" `
  --library-type user `
  --library-id 19552201 `
  --candidate-limit 50 `
  --priority-recommendations priority_recommendations.json `
  --output zotero_import_plan.json
```

Local API matching is the default. Use `--zotero-items zotero_items.json` for
an offline snapshot. Use `--ris-output selected.ris` only when a portable manual
fallback is needed. If Local API is unavailable, stop unless the user explicitly
approves `--allow-unchecked-create`.

After reviewing the exact plan hash, dry-run and then apply it through
`zotero_apply_import_plan`. Apply mode requires the hash, receipt path, and a
write-capable Zotero Web API key.

Create a metrics-only backfill plan from an item snapshot and an audited CSV:

```bash
uv run literature-manager/scripts/zotero_literature_manager.py plan-metrics-backfill \
  --zotero-items zotero_items.json \
  --journal-metrics reviewed_jcr_cas_2026.csv \
  --metrics-year 2026 \
  --source-label reviewed-jcr-cas-2026 \
  --library-type user --library-id 19552201 \
  --output zotero_metrics_plan.json
```

Review the saved plan, call `zotero_apply_metrics_plan` with `mode: dry_run`,
then approve the exact `plan_hash` before calling `mode: apply`. The MCP writes
the year-specific payload into `Extra` and synchronizes only current
`JCR:*`/`CAS:*` tags; it preserves all other tags and user Extra text.

For Agent Tags, read [semantic-tags.md](references/semantic-tags.md). Call
`zotero_semantic_tag_context`, reconcile at most four English tags per item
against the returned library vocabulary, then call
`zotero_apply_semantic_tags`. Frank has enabled automatic application for this
restricted workflow: it replaces only `AI4S:Semantic:*`, removes `type: 1`
automatic tags on the same items, preserves every other tag, and saves an
internal hashed plan plus receipt without a separate approval round.

For AI Summary metadata, read [ai-summaries.md](references/ai-summaries.md).
Run it only after the user explicitly asks for per-paper summaries. Call
`zotero_ai_summary_context`, write exactly one Chinese sentence by default from
only each returned title and abstract, then call `zotero_apply_ai_summaries`.
Ordinary import, project sync, metrics, Agent Tags, and report updates must not
trigger it. Default `missing` mode fills only absent values; use `refresh` only
when the user explicitly asks to regenerate or overwrite existing summaries.

The older match/sync path remains available for records already in Zotero.

Fetch Zotero items from the local desktop API:

```bash
uv run literature-manager/scripts/zotero_literature_manager.py fetch-items \
  --local \
  --library-type user \
  --library-id 123456 \
  --limit 200 \
  --output zotero_items.json
```

Match `literature-research` ranked evidence against Zotero:

```bash
uv run literature-manager/scripts/zotero_literature_manager.py match-evidence \
  --evidence ranked_all.json \
  --zotero-items zotero_items.json \
  --min-score 0.8 \
  --output zotero_match.json
```

Audit likely duplicate Zotero records before collection sync:

```bash
uv run literature-manager/scripts/zotero_literature_manager.py dedupe-library \
  --zotero-items zotero_items.json \
  --min-title-score 0.92 \
  --output zotero_duplicates.json
```

Prepare a collection/tag/note sync plan:

```bash
uv run literature-manager/scripts/zotero_literature_manager.py plan-sync \
  --matches zotero_match.json \
  --project gpld1-cvd \
  --search-date 2026-07-10 \
  --collection-name "GPLD1 cardiovascular disease" \
  --collection-key ABCD1234 \
  --tag domain:cardiovascular-disease \
  --output zotero_sync_plan.json
```

Always inspect `zotero_sync_plan.json` before applying. Use dry-run first:

```bash
uv run literature-manager/scripts/zotero_literature_manager.py apply-sync \
  --sync-plan zotero_sync_plan.json \
  --library-type user \
  --library-id 123456 \
  --dry-run \
  --output zotero_sync_dry_run.json
```

## Utility Scripts
Use `scripts/zotero_literature_manager.py` for repeatable work. All subcommands
write outputs to files and print only short status messages.
Examples using `\` continuation are Bash commands; use a PowerShell backtick
or place the same arguments on one line on Windows.

- `fetch-items`: fetch Web API or Local API library/collection items to JSON.
  Use explicit `--limit`; do not imply that a capped export is complete.
- `match-evidence`: compare ranked evidence to Zotero items by DOI, PMID, and
  title-year similarity. Output matched and unmatched records.
- `dedupe-library`: report likely duplicate Zotero records by DOI, PMID, and
  title-year similarity. It never modifies the library.
- `plan-import`: convert explicitly selected ranked evidence into one hashed
  create/reuse/check/skip plan; normalize source-database publication types
  into per-item `AI4S:ArticleType:*` tags; optionally consume report-stage
  Priority recommendations and export create actions to RIS. Available
  EasyScholar metrics are embedded for both create and reuse actions by
  default, using the search-date-derived display year.
- `plan-sync`: legacy lower-level path that turns a match report into a
  reviewable collection/tag/note plan.
- `apply-sync`: apply an approved plan to existing Zotero items. It updates only
  tags and collections through the Web API. Local API writes are rejected. Use
  `--dry-run` unless the user explicitly approves the exact plan.
- `plan-metrics-backfill`: make a no-write, hashed IF/JCR/CAS patch plan using
  unique ISSN matches first, then a strict unique normalized journal-name or
  standard-abbreviation fallback, from an audited CSV and a versioned Zotero item snapshot.
Read `references/project-sync.md` for recurring report-and-evidence collection
sync. Read `references/sync-schema.md` when interpreting lower-level match/sync JSON. Read
`references/zotero-api-notes.md` before live API writes, local API work, MCP
integration, or rate-limit troubleshooting. Read `references/import-contract.md`
for import-plan and receipt decisions. Read `references/semantic-tags.md` for
Agent vocabulary, cleanup, and automatic-apply boundaries. Read
`references/ai-summaries.md` for explicit triggering, sentence evidence, and
the `AI4S-Summary` Extra contract.

## Workflow
1. Confirm the evidence source. If there is no ranked evidence file, run
   `literature-research` first.
2. For a recurring report project, use `zotero_sync_literature_project` with
   the finalized `report.md`, EasyScholar-enriched ranked evidence, project
   slug, and search date. Exact DOI/PMID operations and available create/reuse
   metrics proceed idempotently and return a compact result.
3. Stop and ask Frank only if project sync reports a high-risk case. A large
   create batch can resume after one explicit confirmation; identity and
   ownership conflicts require resolution.
4. For lower-level work, export or fetch Zotero items to `zotero_items.json`. Prefer local API for a
   desktop library and Web API for synced/group libraries.
5. Run `dedupe-library` if the user asked for library cleanup or if duplicate
   records would affect collection/tag decisions.
6. Run `match-evidence` and inspect unmatched records. DOI or PMID matches are
   strong; title-year fuzzy matches require human review.
7. Run `plan-sync` with project, search date, collection, and tag metadata.
8. Inspect the sync plan. Resolve collection keys and remove bad matches before
   writing.
9. Run `apply-sync --dry-run`; only then run a non-dry write if Frank approved
   the exact plan.
10. Run `plan-metrics-backfill` only for an explicitly requested refresh of
    existing items/collections; inspect skipped matches, then dry-run and
    explicitly approve `zotero_apply_metrics_plan`.
11. When Agent Tags are requested, run the semantic-tag workflow after import or
   directly on existing items/collection. Re-read context on any vocabulary or
   item version conflict.
12. Only when the user explicitly requests AI Summary metadata, run context then
   apply for named items or a collection. Default to Chinese and `missing` mode;
   skip records without abstracts and never infer from the title alone.
13. Hand `zotero_match.json` or `zotero_sync_plan.json` to `literature-writing`
   when drafting prose.

For new imports, use `plan-import`, inspect the plan/hash, run MCP dry-run,
obtain explicit approval, apply to a receipt, then run the read-only duplicate
audit. PubMed `PublicationType` and Web of Science `Document Type` values are
projected into native Zotero tags such as `AI4S:ArticleType:Review`; Zotero's
broad `itemType` remains citation-oriented, so a journal Letter is not converted
to the personal-correspondence `letter` item type. Confirmed duplicate merges
stay in Zotero Desktop.

When `priority_recommendations.json` is present, selected records default to
`AI4S:Priority:1`; explicit Priority 2/3 promotions are carried into the hashed
action with reason codes and sidecar SHA-256. Priority is user-owned after the
first write: an existing valid Priority tag is preserved during planning and
again during live MCP apply unless Frank explicitly requests a separate
re-rating workflow.

When `semantic_tag_candidates.json` is present, apply the import first, map its
stable evidence IDs through the import receipt, and then reconcile candidates
with `zotero_semantic_tag_context`. Do not write run-specific candidates before
checking the persistent vocabulary. Final tags use
`AI4S:Semantic:<canonical English>`; each item receives zero to four, or at
most two without an abstract and never a metadata-only mechanism tag.

## MCP and API Boundary
A Zotero MCP server is optional runtime convenience. Do not make MCP state the
only source of truth. Preserve JSON exports, match reports, and sync plans so a
future agent can audit what was matched and changed.

For lightweight project sync, `report.md` and ranked evidence remain the source
of truth. Private MCP state stores only reconstructible Zotero bindings,
content hashes, and receipts; report ownership tags support recovery without
user-facing plan files.

Do not commit API keys, library export files containing private PDFs/notes,
cookies, local Zotero database files, or unpublished project annotations.

## Rate Limiting
Zotero Web API clients must handle `Backoff` and `429 Too Many Requests`
responses and reduce concurrency. The bundled script defaults to one Web API
request per second with file-lock coordination, honors `Backoff` and
`Retry-After`, retries transient 5xx errors, and raises `RateLimitError` after
repeated 429 responses. Local API mode disables the artificial delay.

## Common Mistakes
- Do not treat Zotero as a substitute for PubMed/WoS/arXiv retrieval.
- Do not import or tag unmatched records without reviewing DOI/PMID/title-year
  evidence.
- Do not run ambiguous, destructive, or broad lower-level library writes
  without a saved plan and dry-run output. Exact-ID recurring project sync is a
  narrow exception: it adds without removing, updates only its AI4S-owned report
  Note, and keeps its plan/receipt internal. Agent semantic tagging is the other
  narrow exception explicitly enabled by Frank;
  its MCP tool creates the plan and receipt internally and can modify only the
  semantic namespace plus Zotero automatic tags on processed items.
- Do not generate AI Summary during import, project sync, metrics, Agent Tags,
  or report updates. An explicit user request is required, and the apply tool
  may modify only the unique `AI4S-Summary` Extra block.
- Do not turn `check` records into creates or reuses without human resolution.
- Do not infer Article Type from a title or abstract when structured source
  metadata is absent; leave it empty or obtain reviewed source metadata first.
- Do not overwrite an existing `AI4S:Priority:1|2|3` tag during ordinary
  imports. Priority is reading/use priority, not evidence quality.
- Do not create a new canonical Agent Tag when an accurate vocabulary alias
  exists, copy source-database keyword lists, or remove manual user tags.
- Do not overwrite Abstract, create a child Note, or turn an AI Summary sentence
  into a native Zotero tag. Without an abstract, skip instead of guessing.
