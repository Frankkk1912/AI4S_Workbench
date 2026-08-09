# Zotero Import Handoff Contract

Use this reference when generating or applying a ranked-evidence import plan.
The full design and JSON Schemas live under `docs/literature/` in the source
repository.

## Default Artifacts

- `zotero_import_plan.json`: selected evidence, exact create/reuse/check/skip
  decisions, target collection/tags, per-item Article Type tags, compact match
  evidence, and plan hash.
- `zotero_import_receipt.json`: evidence-to-Zotero key mapping, collection key,
  library versions, failures, and completion state.
- `selected.ris`: optional manual fallback containing create actions only.

Do not create a separate `import_manifest.json`; provenance belongs in the plan
and receipt.

## Decisions

- `reuse`: exactly one DOI or PMID match.
- `create`: no match, supported item type, and sufficient metadata.
- `check`: ambiguous identifiers, title-only candidate, candidate truncation,
  unsupported type, or insufficient metadata.
- `skip`: duplicate selected evidence or explicit exclusion.

Title/fuzzy similarity never produces automatic reuse. `check` and `skip` are
never written.

## Article Type Tags

- Structured source fields (`article_types` or `publication_types`) are
  normalized to native Zotero tags with the prefix `AI4S:ArticleType:`.
- `Journal Article` becomes `AI4S:ArticleType:Article` only when no more
  specific type is present. `Systematic Review` suppresses redundant `Review`.
- Source publication type never changes Zotero's broad citation-oriented
  `itemType`; for example, PubMed `Letter` remains a `journalArticle` item with
  `AI4S:ArticleType:Letter`.
- Create actions write their per-item tags directly. Reuse actions merge their
  hashed per-item tags while preserving all existing Zotero tags.
- Unknown source vocabulary is preserved as a bounded namespaced tag for
  review; the original evidence record remains the lossless source of truth.

## Priority Recommendations

- `--priority-recommendations` accepts the compact report-stage sidecar from
  `literature-research` and verifies schema, project scope, stable evidence IDs,
  review depth, levels, and lower-kebab-case reason codes.
- Selected evidence defaults to `AI4S:Priority:1`; only Priority 2/3 overrides
  are listed in the sidecar.
- The sidecar SHA-256 and each action recommendation are included in the
  canonical import-plan hash.
- Priority means personal reading/use priority, not evidence quality.
- New items receive the planned tag. Reused items receive it only when no valid
  `AI4S:Priority:1|2|3` tag already exists.
- The MCP repeats the existing-tag check against the live item, protecting a
  user rating added after plan generation.
- Multiple existing Priority tags are never silently resolved; the read-only
  Zotero column displays a conflict warning for manual cleanup.

## Default Metrics on New Imports

- Selected journal evidence is enriched through EasyScholar before planning;
  preprints are never assigned journal metrics.
- The display year is `search_date.year - 1`; EasyScholar is treated as the
  latest source and requires no separate metric-year configuration.
- Create and reuse action intent includes the versioned `AI4S-Metrics` Extra
  block. Reuse apply merges only that managed block into live Extra.
- IF/5-Year IF remain continuous values in Extra. Current JCR/CAS are also
  synchronized to native `JCR:*`/`CAS:*` tags for filtering.
- Missing metrics do not change a create/reuse decision. Existing-collection
  backfill is a separate explicitly requested, hash-gated workflow.

## Safety

- Local API is read-only.
- Apply requires the exact approved plan hash and a Web API key.
- A complete receipt makes repeated application a no-op.
- A partial receipt resumes pending work only.
- A live match appearing for a planned create becomes `check`; it is not
  silently reused or duplicated.
- Multiple exact collection names and stale reuse versions block writes.
- The workflow never merges, trashes, or deletes records.
