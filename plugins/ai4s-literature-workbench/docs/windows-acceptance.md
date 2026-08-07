# Windows Native Acceptance

Use this checklist on Windows 11 twice: once in Windows PowerShell 5.1 and once
in PowerShell 7. Keep credentials and Zotero data outside the repository.

## Prerequisites

- Native Codex CLI with the public `ai4s-workbench` marketplace configured.
- Node.js 20.19 or newer, npm, and `uv` on `PATH`.
- Zotero Desktop 7 or newer with Local API access enabled.
- A user-designated non-production Zotero test library with Web API write
  permission.

## Automated acceptance

Use a clean clone in a path containing a space or non-ASCII character. Install
the plugin, restart Codex, and run:

```powershell
cd "C:\path with spaces\AI4S_Workbench\plugins\ai4s-literature-workbench"
.\scripts\windows-acceptance.ps1 -ReportPath "$env:TEMP\ai4s-literature-windows.json"
```

Pass requires `overall_status: "passed"` and successful checks for the Zotero
and Fulltext runtimes, both Python skills, bundle drift, and the XPI. Retain
the redacted JSON report as release evidence.

### Recorded automated result — 2026-08-03

The automated acceptance was rerun after installing the Playwright Chromium
runtime required by the then-isolated WoS page-contract tests. Both Windows
PowerShell flavors passed with zero failed checks:

| Shell | Version | Generated (UTC) | Result |
| --- | --- | --- | --- |
| Windows PowerShell | 5.1.26100.8875 | 2026-08-03T13:24:01Z | passed |
| PowerShell | 7.6.3 | 2026-08-03T13:25:11Z | passed |

That historical run included `codex-plugin-visible`, `bootstrap-all-runtimes`,
`zotero-runtime-tests`, `fulltext-runtime-tests`,
`database-browser-runtime-tests`, `python-skill-tests`, `bundle-drift-check`,
and `literature-metrics-xpi`. The generated XPI and two redacted JSON reports
remain local release evidence; no credentials, browser profiles, or Web of
Science exports were written to the repository. The database-browser check was
removed from the v0.1.0 scope when WoS was deferred.

## Zotero and Fulltext MCP live acceptance

1. Run `node .\runtime\scripts\zotero-configure.mjs setup` locally. Confirm the
   key is stored under `%LOCALAPPDATA%\ai4s-literature-workbench` and is absent
   from the repository and acceptance report.
2. Restart Codex. Call `zotero_whoami`, search the designated test library, and
   read one known item. The reported identity and library must match the
   intended test target.
3. Use ranked fixture evidence to create a reviewed import plan targeting a
   collection named `AI4S Windows Acceptance <date>`. Dry-run it, approve its
   exact hash, and apply it. Do not use a production library.
4. Apply one reviewed metrics update, one Agent Tags update, and one explicitly
   requested AI Summary to the acceptance item. Confirm receipts exist and
   `zotero_find_duplicates` remains read-only.
5. Select a known OA item in the test collection. Complete
   `fulltext_fetch_submit`/status and the separately reviewed
   `zotero_apply_fulltext_handoff`; verify exactly one child attachment is
   present. Record a compact redacted result in the acceptance report: the
   Fulltext tool status, verified-handoff count, attachment count, and any
   actionable failure code. Do not record a DOI, item key, PDF path, URL, or
   Zotero content.

## Zotero XPI acceptance

1. Install the XPI path recorded in the acceptance report through Zotero's
   Add-ons Manager.
2. Show the IF, 5-Year IF, JCR, CAS, Journal Metrics, Article Type, Agent Tags,
   AI Summary, Priority, and Citations columns that have fixture data.
3. Verify the acceptance item displays the applied metadata. Change Priority
   with a star, clear it by clicking the saved level again, then repeat with
   the `1` and `0` keyboard shortcuts.
4. Confirm unrelated tags and Extra text remain unchanged.

Do not automatically delete acceptance entries or attachments. Retain them for
manual comparison and remove them later through Zotero Desktop only if desired.

## Deferred Web of Science browser workflow

Web of Science browser search and official export are not part of the v0.1.0
plugin registration or Windows acceptance. Keep official export files outside
the repository; the existing `import-wos-export` command remains available for
user-obtained exports. A future release will restore the campus-network browser
acceptance gates after the backend is ready.
