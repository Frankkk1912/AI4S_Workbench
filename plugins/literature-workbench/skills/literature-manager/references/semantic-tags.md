# Agent Semantic Tags Workflow

Use this workflow when Frank asks to generate, refresh, display, or clean Agent
Tags for imported papers, selected Zotero items, or a collection.

## Data ownership

- Final tags are native Zotero tags named `AI4S:Semantic:<canonical English>`.
- Re-analysis may replace only `AI4S:Semantic:*` on processed items.
- Ordinary tagging removes Zotero automatic tags (`type: 1`) only from the
  same processed items.
- Preserve user-created tags and all `AI4S:ArticleType:*`,
  `AI4S:Priority:*`, `JCR:*`, and `CAS:*` tags.
- Collection/library cleanup outside the tagging batch requires an explicit
  `zotero_cleanup_auto_tags` request.

## Existing Zotero items or collection

1. Call `zotero_semantic_tag_context` with either item keys or one collection
   key. Page collections in batches of at most 50.
2. Use title plus abstract by default. For `metadata-only`, propose no more
   than two tags and no mechanism tag.
3. Reuse the returned vocabulary entry whenever its canonical label or alias
   accurately represents the concept. Use `decision: reuse` and its vocabulary
   ID or alias.
4. Use `decision: new` only for a genuinely absent reusable concept. Supply a
   concise English canonical label, dimension, definition, and real aliases if
   any. A narrow entity is eligible only when it is a principal study subject.
5. Assign zero to four tags. Do not fill absent dimensions. Returning zero is
   preferable to a vague label.
6. Call `zotero_apply_semantic_tags` with the exact context vocabulary revision
   and item versions. This automatically applies the restricted change and
   saves a hashed plan and receipt; no second confirmation is required because
   Frank enabled automatic Agent tagging.
7. If the vocabulary or item version changed, re-read context. Never bypass a
   revision conflict.

## Newly imported evidence

When `semantic_tag_candidates.json` exists from `literature-research`:

1. Apply the reviewed import plan first and read the import receipt.
2. Map stable evidence IDs in the candidate artifact to resulting Zotero item
   keys from the receipt.
3. Call `zotero_semantic_tag_context` for those item keys to get current item
   versions and vocabulary revision.
4. Reconcile each candidate with the current vocabulary. Candidate canonical
   text is not authority to create a duplicate; an accurate alias match must be
   reused.
5. Call `zotero_apply_semantic_tags`. Preserve the semantic receipt beside the
   import receipt in the run handoff.

Do not insert semantic candidates into the import plan before vocabulary
reconciliation. The library vocabulary, not a single research run, owns the
canonical terminology.

## Vocabulary portability

- `zotero_semantic_tag_vocabulary` with `inspect` reports current revision and
  entries.
- `export` writes a portable JSON snapshot in the MCP data directory unless an
  explicit path is supplied.
- `import` is merge-only, requires the expected current revision, and stops on
  canonical, alias, or dimension conflicts.
- Local vocabulary JSON is user data and must not be committed to this
  repository.

## Failure handling

- Missing abstract: use metadata-only restrictions.
- No defensible label: apply an empty semantic set with `no-confident-tag`.
- More than four proposals or a metadata-only mechanism: correct the
  recommendation; never rely on silent truncation.
- Read-only/non-bibliographic item: accept the reported skip.
- Partial receipt: retry only failed/conflicted items after fresh context.
- Damaged vocabulary: stop writes and surface the path; never recreate an
  empty vocabulary over it.
