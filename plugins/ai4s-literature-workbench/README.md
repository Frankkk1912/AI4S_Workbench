# AI4S Literature Workbench

AI4S Literature Workbench is composed of three coordinated layers:

1. **Skills** — `literature-research`, `literature-manager`, and
   `literature-writing` retrieve evidence, prepare reviewed import plans, and
   draft evidence-traced scientific prose.
2. **MCP** — the workbench-profile Zotero MCP performs read-only library work,
   applies exact reviewed import/metrics/citation plans, performs lightweight
   recurring project sync for reports plus selected papers, and runs the
   constrained automatic Agent Tags workflow plus the explicitly requested
   title-and-abstract AI Summary workflow with internal plans and receipts. A
   separate optional Fulltext MCP owns OA PDF verification and private
   handoffs; it cannot affect Zotero except through the separately controlled
   attachment-write step.
3. **Zotero Desktop plugin** — the separate repository-root
   `literature-metrics` XPI renders AI4S-managed metrics and labels and provides
   an interactive, user-owned Priority star control.

## Installation

- **Claude Code**: `/plugin marketplace add Frankkk1912/AI4S_Workbench`,
  then `/plugin install ai4s-literature-workbench@ai4s-workbench`.
- **Codex**: `codex plugin marketplace add <this repository>`, then
  `codex plugin add ai4s-literature-workbench@personal`.
- **opencode / Antigravity / others**: use the bundled `skills/` directory
  from this plugin with the agent's documented local skill installation flow.
  The private repository's `sync/` installer is not part of this public
  development export.

After installing, run the first-time setup below in the plugin directory.

## First-time setup

The bundled MCP runtime is source-based and intentionally does not include
`node_modules`, build output, credentials, or Zotero data. Bootstrap it after
installing the plugin:

```bash
bash scripts/bootstrap-runtime.sh
```

On Windows PowerShell:

```powershell
.\scripts\bootstrap-runtime.ps1
```

Bootstrap requires Node.js 20.19+ and npm. It runs `npm ci`, builds the bundled
Zotero runtime from its committed lockfile, and verifies its workbench MCP tools
over stdio. It then attempts to build the optional Fulltext runtime; an
optional-runtime dependency failure is reported as a warning and never
prevents Zotero or Skills from installing.
For release validation, make optional runtime failures fatal and save a
machine-readable report:

```powershell
.\scripts\bootstrap-runtime.ps1 -RequireOptional -ReportPath .\bootstrap-report.json
```

Web of Science browser search and official export are deferred from v0.1.0 and
are not registered by this plugin release. Manually obtained official exports
can still be normalized with `import-wos-export`. The confirmed scope,
deferrals, and release gates are recorded in
[`v0.1.0-release-plan.md`](v0.1.0-release-plan.md).

The optional Fulltext MCP currently supports only public OA HTTP routes (PMC
lookup plus reviewed candidate URLs). It verifies PDF bytes with a parser and
requires a strong DOI-and-title match before it writes a private, hashed
handoff. It does not start a browser, connect a VPN, store credentials, or
upload PDFs to Zotero; `zotero_apply_fulltext_handoff` performs the separate,
controlled attachment-write phase. Institutional fallback remains unimplemented.

API credentials are optional. After the first workbench conversation, the
Agent reports which capabilities are available and shows the official
application links for Zotero Web API, PubMed, and EasyScholar. Basic retrieval,
ranking, and writing remain usable when any or all credentials are skipped.

Run the unified local credential wizard:

```bash
node scripts/onboard.mjs setup --output onboarding-result.json
```

On Windows PowerShell:

```powershell
node .\scripts\onboard.mjs setup --output .\onboarding-result.json
```

The wizard masks each key, validates it before replacing an existing setting,
and stores it only in the current user's platform-private configuration
directory. Its result file is redacted. Do not paste a key into an Agent chat
or put one in command arguments. See
[`docs/onboarding.md`](docs/onboarding.md) for permissions, skip behavior, and
individual reconfiguration commands. Zotero API onboarding does not install the
separate Zotero Desktop XPI: build it from the repository clone, then install
`literature-metrics/dist/literature-metrics-<version>.xpi` through **Tools →
Add-ons → gear menu → Install Add-on From File…**. The first-run onboarding
status and Agent prompt include this reminder.

## Windows native support and WSL migration

The plugin is installed and bootstrapped separately in each operating-system
environment. On a new machine, or when moving between Windows-native Codex and
WSL-native Codex, clone/pull the repository in that environment, add the local
marketplace, install the plugin, and run its native bootstrap script:

```powershell
# Windows PowerShell
codex plugin marketplace add C:\path\to\AI4S_Workbench
codex plugin add ai4s-literature-workbench@personal
cd C:\path\to\AI4S_Workbench\plugins\ai4s-literature-workbench
.\scripts\bootstrap-runtime.ps1
```

Windows 11 with Windows PowerShell 5.1 or PowerShell 7 is the native support
baseline. Run the repository-level automated acceptance after bootstrap:

```powershell
.\scripts\windows-acceptance.ps1 -ReportPath .\windows-acceptance.json
```

The report contains only tool versions, check results, durations, and artifact
paths. It never records API keys, cookies, Zotero item contents, or browser
profiles. Complete the Zotero/Fulltext/XPI live checklist in
[`docs/windows-acceptance.md`](docs/windows-acceptance.md) before marking a
release as Windows-validated.

```bash
# WSL
codex plugin marketplace add /home/<user>/AI4S_Workbench
codex plugin add ai4s-literature-workbench@personal
cd /home/<user>/AI4S_Workbench/plugins/ai4s-literature-workbench
bash scripts/bootstrap-runtime.sh
```

Do not copy `node_modules`, `dist`, Zotero data, or private environment files
across platforms. Bootstrap recreates runtime artifacts from the committed
lockfile. Put credentials into the destination platform's private environment
only. WSL remains a separately installed compatibility target and is not a
Windows-native release gate.

## Credentials and safety

Do not put Zotero credentials in this repository or plugin manifest. The
wizard stores them at `~/Library/Application Support/...` on macOS,
`%LOCALAPPDATA%\\...` on Windows, and `${XDG_CONFIG_HOME:-~/.config}/...` on
Linux/WSL. `LITERATURE_ZOTERO_MCP_ENV_FILE` remains available for an explicit
private location. `ZOTERO_API_KEY` is required only for approved Web API
writes. Zotero Local API reads remain read-only.

Existing installations using `~/.config/ai4s-literature-workbench/zotero.env`
remain supported; the wizard migrates them to the platform-native location when
it next updates the key.

The MCP workbench profile exposes `zotero_whoami`, `zotero_search_items`,
`zotero_get_item`, `zotero_get_fulltext`, `zotero_fulltext_context`, `zotero_apply_fulltext_handoff`, `zotero_apply_import_plan`,
`zotero_apply_metrics_plan`, `zotero_apply_citation_plan`, `zotero_find_duplicates`,
`zotero_semantic_tag_context`, `zotero_apply_semantic_tags`,
`zotero_cleanup_auto_tags`, `zotero_semantic_tag_vocabulary`,
`zotero_sync_literature_project`, `zotero_ai_summary_context`, and
`zotero_apply_ai_summaries`. Standalone import, existing-collection
metrics backfill, and citation plans require their existing review/hash gates. Agent
tagging is automatically applied only within its restricted namespace and
requires write-capable credentials. Recurring project sync keeps its preflight
and receipts private and surfaces only ambiguous, conflicting, destructive, or
large-create cases. For new imports, it also consumes selected EasyScholar-
enriched evidence and automatically writes available metrics for both creates
and exact-ID reuses; missing metrics do not block bibliography writes.
AI Summary is never automatic: after a direct user request, the Agent uses only
each returned title and abstract, defaults to one Chinese sentence, and writes
only the versioned `AI4S-Summary` Extra block. Default `missing` mode preserves
existing values; `refresh` requires explicit regenerate/overwrite intent.

## Zotero Desktop metrics plugin

`literature-metrics/` is deliberately independent of this Codex plugin: it is
installed into Zotero Desktop as an XPI, while the skills and MCP remain the
agent-side workflow. Its metrics and Article Type columns are read-only and render `IF(YYYY)`,
`5-Year IF(YYYY)`, `JCR(YYYY)`, `CAS(YYYY)`, `Journal Metrics`,
`Article Type`, `Agent Tags`, and `AI Summary`, plus an interactive, user-owned `Priority`
star column. Agent Tags displays canonical English `AI4S:Semantic:*` labels
created by the MCP workflow. Metrics come from versioned AI4S metadata; Article Type reads
native, filterable `AI4S:ArticleType:*` Zotero tags generated from structured
PubMed/WoS publication types or added manually by the user. Priority reads
`AI4S:Priority:1|2|3`, may be initialized from compact report-stage
recommendations, and is never ordinary-import-overwritten once the user has a
rating. Hovering previews a level; clicking atomically replaces only the
Priority namespace, and clicking the saved level again clears it. With focus
in the main item tree, `1/2/3` batch-set selected regular items and `0` clears;
the item context menu exposes the same commands. Build it from a repository clone:

```text
cd literature-metrics
npm ci
npm test
npm run package
```

These commands are identical in Bash and PowerShell.

Install the generated `dist/literature-metrics-<version>.xpi` in Zotero
Desktop's Add-ons Manager. The add-on makes no network requests. Its only
direct item write is a user's explicit Priority rating action.

## Maintaining the bundle

In this repository, the three `skills/literature-*` directories and
`literature-zotero-mcp/` are the source of truth for the Codex bundle. After
changing them, run:

```bash
node scripts/assemble-plugin.mjs sync
node scripts/assemble-plugin.mjs check
```

The plugin bundle is intentionally checked in so a clean checkout can bootstrap
without relying on a private npm publication.

`literature-metrics/` has its own manifest, validation, and XPI packaging; it
is not assembled into the Codex plugin bundle.

## Optional journal metrics / JCR data

The plugin includes the versioned default table at
`skills/literature-research/references/jcr_journals_2025.csv`. Standard
retrieval and ranking match it by ISSN by default, enriching evidence with its
2025 IF/JCR values without filtering records or writing Zotero.

For an explicit CAS/JCR zone or impact-factor filter, use the bundled file;
the user does not need to prepare or upload a CSV:

```bash
uv run skills/literature-research/scripts/literature_search.py review \
  --question "..." --pubmed-query "..." --limit 50 --top-n 30 \
  --output literature_run \
  --journal-metrics skills/literature-research/references/jcr_journals_2025.csv \
  --jcr-zones Q1 --if-min 5 --filter-journals
```

The runtime does not download journal metrics automatically. A newer reviewed
CSV may be supplied with `--journal-metrics` as an explicit override; never
commit private or unlicensed replacement data.

For a new Zotero import, the default live-metrics route is EasyScholar after
the final selection is known:

```bash
uv run skills/literature-research/scripts/literature_search.py enrich-easyscholar \
  --ranked-json literature_run/ranked_all.json \
  --selection-json literature_run/selection.json \
  --output literature_run/ranked_all.json
```

The command queries only selected journal records, skips preprints, reuses the
persistent journal cache, and records an unavailable status instead of failing
the later Zotero import when the key/API is missing. Project sync derives the
display year from the search date (`year - 1`), stores IF/5-Year IF/JCR/CAS in
versioned Extra, and additionally mirrors current JCR/CAS into native tags.
