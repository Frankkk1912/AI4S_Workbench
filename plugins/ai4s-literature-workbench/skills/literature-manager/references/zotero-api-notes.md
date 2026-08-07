# Zotero API Notes

Use this reference only when a Zotero task needs API semantics, write behavior,
or rate-limit details.

## API Surface

- Web API base URL: `https://api.zotero.org`.
- Local API base URL: `http://localhost:23119/api`.
- Request API v3 with `Zotero-API-Version: 3`.
- Private Web API access requires an API key in a header. Do not place keys in
  URLs, command history, repository files, or sync artifacts.
- Local API is useful for a user's desktop library and does not use API-key
  authentication, but Zotero must be running and local API access must be
  enabled.

## Read Constraints

- Multi-object Web API reads are paginated. A single Web API response returns no
  more than 100 results.
- For library-wide sync, prefer incremental `since` queries when a previous
  library version is available.
- Search with `q` and `qmode=titleCreatorYear` before using broader
  full-library scans.

## Rate Limits

Official Zotero Web API docs do not publish a fixed request-per-second value.
They require clients to handle:

- `Backoff: <seconds>` headers on any response.
- `429 Too Many Requests`, optionally with `Retry-After: <seconds>`.
- Reduced request rate and no more than four concurrent requests after limits.

The bundled script defaults to one request per second for Web API calls, uses a
file-lock rate limiter, honors `Backoff`/`Retry-After`, retries transient 5xx
responses, and raises `RateLimitError` after repeated 429 responses. The local
API does not currently apply rate limiting, so the script disables the artificial
delay when `--local` is used.

## Write Safety

- Write requests require write-capable credentials for the target library.
- Prefer `plan-import` or `plan-sync` first for ambiguous, destructive, or
  standalone batch writes. Recurring exact-ID project sync is the narrow
  exception: its preflight and receipt remain private and it stops for review
  on ambiguity, ownership conflict, destructive implications, or more than 50
  creates.
- Use MCP import-plan dry-run or `apply-sync --dry-run` by default. Only run a
  non-dry write after the user approves the exact plan hash/actions.
- `apply-sync` uses `PATCH` for existing items and only updates `tags` and
  `collections`. `zotero_apply_import_plan` may create items from the exact
  approved plan and writes a receipt, but never uploads PDFs, merges, trashes,
  deletes, or writes through Local API.
- If an item changed since retrieval, Zotero can reject the write with version
  errors. Re-fetch the item/library and regenerate the sync plan.

## MCP Boundary

A Zotero MCP server may be used as a runtime convenience for browsing and
interactive operations, but the workflow contract stays API-shaped:

1. Fetch/export library records to JSON.
2. Match evidence by DOI, PMID, or title-year.
3. Produce a hashed import or sync plan.
4. Dry-run, then apply only after explicit approval of the exact plan.
5. Persist a receipt for imports and keep final duplicate merging in Zotero
   Desktop.

Do not make an MCP-only workflow that cannot be audited from saved JSON files.
