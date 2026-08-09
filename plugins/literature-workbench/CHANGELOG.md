# Changelog

All notable changes to the Literature Workbench plugin are documented
here. The format follows Keep a Changelog; versions follow Semantic
Versioning.

## [0.1.0] - 2026-08-09

First release. An auditable literature-workflow plugin for macOS and native
Windows: evidence retrieval and ranking, controlled Zotero operations,
EasyScholar metrics for new imports, and OA-first verified PDF handoffs.

### Support matrix

| Platform | Status |
| --- | --- |
| macOS | Clean-install acceptance passed on Codex CLI and Claude Code (see `macos-acceptance.json`) |
| Windows 11, PowerShell 5.1 and 7 | Native platform and Zotero onboarding acceptance passed |
| WSL | Compatibility target only, not a release gate |
| Codex CLI | Supported agent; installed via the `personal` repository marketplace |
| Claude Code | Supported agent; installed via the `ai4s-workbench` repository marketplace |

### Added

- Three-skill literature workflow bundle: `literature-research`
  (PubMed/arXiv retrieval, evidence ranking, bilingual cited reports,
  bundled JCR 2025 journal metrics, EasyScholar enrichment),
  `literature-manager` (hashed reviewed Zotero import plans, read-only
  duplicate candidate detection, collection/report sync), and
  `literature-writing` (evidence-traced review, proposal, and manuscript
  prose with citation placeholders and bibliography plans).
- `literature-zotero-mcp` workbench runtime (17 MCP tools): reviewed
  imports, metrics backfill, citation plans, fulltext handoff apply,
  semantic tag context/apply/cleanup with a persistent library-scoped
  vocabulary, project sync with receipts, and explicitly requested
  versioned Chinese AI Summary writes.
- `literature-fulltext-mcp` runtime: OA-first (HTTP/PMC and reviewed
  public PDF candidates) verified fulltext handoffs, verified before a
  separate controlled Zotero attachment write.
- `import-wos-export` accepts multiple manually obtained official WoS export
  batches and merges them by WoS UT and then DOI before applying its limit.
- Secure first-run API onboarding wizard (`scripts/onboard.mjs`) with
  masked, validated, platform-private credential storage and a manual Zotero
  Desktop XPI installation reminder for AI4S columns and Priority controls.
- Native macOS and Windows bootstrap scripts with committed lockfiles
  and a repository-level Windows acceptance report script.
- Claude Code plugin manifest (`.claude-plugin/plugin.json`) and
  documented install routes for Claude Code, Codex, and sync-script
  agents.
- `literature-metrics` Zotero Desktop plugin add-on with its own
  manifest, validation, and XPI packaging.

### Deferred (explicitly out of scope for 0.1.0)

- Web of Science browser MCP: live Core Collection search, filtering,
  result-count verification, and official export. It is not registered by the
  v0.1.0 plugin.
- Crossref and all other commercial database adapters.
- VPN/WebVPN automation, credential or cookie handling, CAPTCHA bypass,
  and hidden-browser operation.
- Institutional/SSO full-text fallback (public OA routes only).
- Automatic Zotero duplicate merges/deletions and automatic modification
  of user Priority.

### Release status

Local regression (tests, builds, bundle sync/check, and MCP smoke
verification), macOS clean-install acceptance, Windows native platform and
Zotero onboarding acceptance, and the known-OA Fulltext handoff and attachment
acceptance are complete. Public-release acceptance is complete; macOS and
Windows GitHub Actions verify the merged release commit. See
`v0.1.0-release-plan.md` for the support boundaries.
