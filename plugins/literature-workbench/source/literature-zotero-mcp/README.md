# Literature Zotero MCP

`literature-zotero-mcp` is an independently maintained Zotero MCP server for
auditable literature and evidence workflows. It is derived from the
MIT-licensed [Zoteus](https://github.com/oscardvs/zoteus) project and adds
read-only duplicate candidate detection for import batches.

It also provides an Agent semantic-tag workflow with a persistent,
library-scoped English vocabulary, constrained Zotero tag writes, automatic
source-tag cleanup, and hashed plans/receipts.

The explicitly triggered AI Summary workflow reads only each item's title and
abstract, defaults to one Chinese sentence, and persists a versioned
`AI4S-Summary` block in `Extra` without modifying the original Abstract.

This derivative is not affiliated with or endorsed by Zoteus, Zotero, or the
Corporation for Digital Scholarship.

## V1 duplicate workflow

The `zotero_find_duplicates` tool:

- accepts exactly one batch selector: `collection_key` or `tag`;
- requires an explicit `limit` and refuses silent truncation;
- compares the selected batch with all top-level bibliographic items in the
  same Zotero library;
- detects exact DOI, PMID, and ISBN matches;
- reviews normalized title, creator, year, and item-type evidence;
- recommends a master record using a deterministic metadata-completeness score;
- saves a JSON audit report under the MCP data directory; and
- never merges, trashes, deletes, or modifies Zotero records.

Confirm candidates and complete merges in Zotero Desktop. Zotero's native merge
preserves collection, tag, and citation relationships that cannot be reproduced
through the public Local or Web APIs.

## Evidence import-plan workflow

`zotero_apply_import_plan` consumes the file-based plan produced by
`literature-manager plan-import`.

- Dry-run validates the contract/hash, collection state, live create checks,
  existing-item versions, and every proposed new item without writing.
- Apply requires the exact approved plan hash and a Web API key.
- The tool creates or uniquely reuses the project collection, creates new
  records, updates collection/tag membership for uniquely reused records, and
  persists `zotero_import_receipt.json` after each batch.
- Repeating a completed plan is a no-op; a partial receipt resumes pending work.
- New live matches become `check`; the tool never silently chooses a duplicate.
- It never merges, trashes, deletes, or writes through Zotero Local API.

## Journal-metrics plan workflow

`literature-manager plan-metrics-backfill` creates a hashed plan from a
versioned, reviewed journal-metrics CSV and a Zotero item snapshot. The plan
matches only a unique normalized ISSN; missing or ambiguous matches are recorded
as `skip` and are never guessed from journal names.

`zotero_apply_metrics_plan` first dry-runs the exact plan against live item
versions. After explicit hash confirmation, apply replaces only the managed
`AI4S-Metrics:` line in `Extra`, retains all other Extra text and tags, and
updates only the current `JCR:*` / `CAS:*` tags. Those tags are derived from
the highest metric year, so backfilling an older year cannot downgrade them.
Each apply writes a receipt; no Local API write is permitted.

### EasyScholar backfill

After enriching `ranked_all.json` with EasyScholar, create a conservative
metrics plan for existing Zotero items:

```bash
uv run literature-manager/scripts/zotero_literature_manager.py plan-easyscholar-metrics-backfill \
  --ranked-json output/ranked_all.json \
  --zotero-items output/zotero_items.json \
  --metrics-year 2026 \
  --source-label easyscholar-2026 \
  --library-type user --library-id 1234567 \
  --output output/zotero_metrics_plan.json
```

Review the hash and run `zotero_apply_metrics_plan` in `dry_run` mode before
explicitly approving the exact plan for `apply`. DOI/PMID matches are preferred;
ambiguous or unmatched records remain `skip`.

## Agent semantic-tag workflow

`zotero_semantic_tag_context` returns title/abstract evidence, current item
versions, existing semantic/automatic tags, the vocabulary revision, and a
compact reusable vocabulary subset. The Agent proposes zero to four canonical
English labels per item, reusing aliases whenever accurate; metadata-only items
are limited to two labels and may not receive a mechanism tag.

`zotero_apply_semantic_tags` is an explicitly enabled automatic workflow. It:

- replaces only `AI4S:Semantic:*` on processed bibliographic items;
- removes Zotero automatic tags (`type: 1`) from those same items by default;
- preserves all manual, Article Type, Priority, JCR, and CAS tags;
- checks item versions and the vocabulary revision before writing;
- persists the vocabulary with a lock and atomic rename; and
- saves a hashed internal plan and per-item before/after receipt.

`zotero_cleanup_auto_tags` provides a separate explicit, bounded
collection/library cleanup. `zotero_semantic_tag_vocabulary` inspects and
exports the JSON vocabulary or merge-imports a compatible snapshot using an
expected revision. Runtime vocabulary and receipts are user data and must not
be committed.

## Explicit AI Summary workflow

AI Summary never runs as part of import, project sync, metrics, Agent Tags, or
report updates. After a direct user request, call `zotero_ai_summary_context`
for item keys or one collection. It returns title/abstract evidence, item
versions, stable input hashes, and current/missing/stale state; the default
language is `zh-CN` and records without abstracts are skipped.

The Agent writes one sentence per returned candidate using no external
knowledge, then calls `zotero_apply_ai_summaries` with
`trigger: "explicit-user-request"`. The apply tool validates the live version,
input hashes, sentence length/shape, and the existing managed block; it PATCHes
only `Extra` and saves an internal hashed plan and receipt. `missing` mode never
overwrites a current or stale Summary. `refresh` is accepted only for a user-
requested regeneration. The Zotero Desktop add-on displays valid values in its
read-only `AI Summary` column and marks changed title/abstract inputs stale.

## Development

Requirements: Node.js 20.19 or newer.

```bash
npm install
npm test
npm run typecheck
npm run build
```

The package is intentionally marked `private`. The staged source has been
verified against the upstream Zoteus `v1.0.2` tag, but public distribution still
requires an explicit release and security review. Exact provenance is recorded
in `THIRD_PARTY_NOTICES.md`.

## Runtime configuration

The server supports the upstream Zoteus configuration variables for backward
compatibility, including `ZOTERO_API_KEY`, `ZOTEUS_LOCAL`, and the other
`ZOTEUS_*` settings documented in `.env.example`.

For the literature workbench, set:

```text
LITERATURE_ZOTERO_MCP_TOOL_PROFILE=workbench
```

This exposes only `zotero_whoami`, `zotero_search_items`, `zotero_get_item`,
`zotero_get_fulltext`, `zotero_fulltext_context`, `zotero_apply_fulltext_handoff`, `zotero_apply_import_plan`,
`zotero_apply_metrics_plan`, `zotero_apply_citation_plan`, `zotero_find_duplicates`,
`zotero_semantic_tag_context`, `zotero_apply_semantic_tags`,
`zotero_cleanup_auto_tags`, `zotero_semantic_tag_vocabulary`,
`zotero_sync_literature_project`, `zotero_ai_summary_context`, and
`zotero_apply_ai_summaries`. Schema validation, collection creation, batch item
creation, and tag/membership updates remain internal to the import-plan tool.
Use `full` only when developing or explicitly using inherited low-level tools.
Combining `workbench` with `ZOTEUS_READ_ONLY=true` removes write-capable tools
and leaves eight read-only tools, including fulltext, semantic-tag, and AI
Summary context preparation.

For an explicitly requested fulltext workflow, first use
`zotero_fulltext_context` to preflight exact parents and local file PDFs. Send
only eligible records to the independent OA Fulltext MCP, then pass its returned
`handoff_id` and `handoff_hash` to `zotero_apply_fulltext_handoff`. The apply
tool reads only the owner-private exchange root, revalidates every artifact hash
and live parent DOI, skips an existing file PDF, and resumes interrupted uploads
with the same attachment key. It accepts no caller-provided file path or URL.

For a first-time local setup, run the interactive command from the runtime
directory after building it:

```bash
npm run zotero:configure -- setup
```

It reads the key through a masked terminal prompt, verifies it against Zotero,
and stores it outside the repository and plugin bundle. Do not paste the key
into an agent chat, a command argument, `.mcp.json`, or a tracked `.env` file.

At startup the server reads a per-user private file if it exists:

- macOS: `~/Library/Application Support/literature-workbench/zotero.env`
- Windows: `%LOCALAPPDATA%\\literature-workbench\\zotero.env`
- Linux/WSL: `${XDG_CONFIG_HOME:-~/.config}/literature-workbench/zotero.env`

Set `LITERATURE_ZOTERO_MCP_ENV_FILE` to point at a different private env file
if required. Existing process environment variables still win over file values.
The legacy `~/.config/literature-workbench/zotero.env` path remains
readable during migration; the setup command copies its settings to the native
location when it creates or updates a key.

The preferred data-directory override for this derivative is:

```text
LITERATURE_ZOTERO_MCP_DATA_DIR=/path/to/runtime-data
```

`ZOTEUS_DATA_DIR` remains accepted as a migration alias. The default directory
name is `literature-zotero-mcp` on macOS, Linux, and Windows.

Web API credentials are required for writes and group libraries. The Zotero
desktop Local API is read-only. Never commit API keys, runtime reports, Zotero
databases, private attachments, or unpublished annotations.

## License and attribution

The project is distributed under the MIT License. Zoteus attribution and the
unaltered upstream license are preserved in `THIRD_PARTY_NOTICES.md` and
`licenses/ZOTEUS-LICENSE`.
