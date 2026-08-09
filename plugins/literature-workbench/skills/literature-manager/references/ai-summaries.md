# AI Summary Metadata Contract

Use this reference only when the user explicitly asks for a one-sentence
summary on one or more Zotero items or a collection.

## Trigger and Scope

- Never run AI Summary during import, recurring project sync, metrics,
  citations, Agent Tags, report updates, or scientific writing.
- A direct natural-language request is sufficient authorization for the
  restricted `AI4S-Summary` namespace; no second hash approval is required.
- Default mode is `missing`, which fills only absent summaries. Use `refresh`
  only after explicit regenerate/refresh/overwrite language from the user.
- Default language is Chinese (`zh-CN`). Change language only when the user
  asks.
- Support item keys or one collection key. Process at most 50 records per page.

## Evidence Boundary

Call `zotero_ai_summary_context`. For every returned candidate:

1. Use only the returned title and abstract.
2. Write exactly one sentence, no Markdown or line breaks, at most 240 Unicode
   characters.
3. Preserve population, model, uncertainty, negation, correlation/causality,
   and other scientific limits stated by the abstract.
4. Prefer research subject/question, method or evidence type, and the main
   abstract-supported finding, but do not force absent dimensions.
5. Do not add PDF, web, tag, metric, citation, or model-memory claims.

The context tool skips a missing title or abstract. Never downgrade to a
title-only guess.

## Apply

Call `zotero_apply_ai_summaries` with:

- `trigger: explicit-user-request`;
- the same `missing` or explicitly requested `refresh` mode;
- item key and version from context;
- the exact title/abstract SHA-256 hashes from context;
- one validated summary and its language.

The apply tool re-reads live items, validates evidence hashes and versions,
and PATCHes only `Extra`. It preserves Abstract, tags, collections, Priority,
Article Type, Agent Tags, metrics, and reports. It saves an internal hashed
plan and receipt and returns only a compact result for ordinary delivery.

## Metadata

The unique managed line is:

```text
AI4S-Summary: {"schema_version":1,"text":"……。","language":"zh-CN","basis":"title-abstract","title_sha256":"…","abstract_sha256":"…","generated_at":"…"}
```

- Duplicate, malformed, or unsupported blocks are conflicts and must not be
  replaced automatically.
- Matching input hashes are current. Changed hashes are stale and require an
  explicit `refresh` request.
- The Zotero add-on displays valid data in a read-only `AI Summary` item-tree
  column; stale summaries show a warning. The sentence is not a native Zotero
  tag.

## User-Facing Result

Report compact counts: created, refreshed, unchanged, stale, skipped,
conflicted, and failed. Surface item details only for missing abstracts,
stale inputs, invalid blocks, or write conflicts that need user action.
