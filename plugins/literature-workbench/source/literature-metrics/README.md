# Literature Metrics for Zotero

`literature-metrics` is a Zotero Desktop add-on for the AI4S literature
workflow. It is the presentation layer only: it never downloads journal
metrics, edits a Zotero item, or accesses an API key.

The companion `literature-manager` and `literature-zotero-mcp` workflow will
write audited `AI4S-Metrics` data into the Zotero `Extra` field. This add-on
reads that data and adds year-specific columns to Zotero's main item tree:

- `Priority` — an interactive one-to-three-star rating backed by user-owned
  native tags `AI4S:Priority:1` through `AI4S:Priority:3`.
- `Article Type` — sortable semantic chips read from native namespaced tags
  such as `AI4S:ArticleType:Review` and `AI4S:ArticleType:Clinical Trial`.
- `Agent Tags` — compact English semantic chips read from reusable,
  Agent-managed `AI4S:Semantic:*` tags. The add-on only displays them; the
  companion MCP owns vocabulary validation, automatic-tag cleanup, plans, and
  receipts.
- `AI Summary` — one Chinese sentence by default, read from the versioned
  `AI4S-Summary` Extra block. The cell stays on one line, the tooltip shows the
  full sentence, and changed title/abstract inputs receive a stale warning.
- `IF(YYYY)` — numeric sorting with five visual bands: `<5`, `5–<10`,
  `10–<20`, `20–<40`, and `≥40`.
- `5-Year IF(YYYY)` — the same numeric sorting and visual bands for five-year IF.
- `JCR(YYYY)` — colored Q1–Q4 labels with explicit ordinal sorting.
- `CAS(YYYY)` — colored 1区–4区 labels with explicit ordinal sorting.
- `Journal Metrics` — compact, single-line semantic chips such as `医学1区`,
  `TOP`, `ESI 临床医学`, and `EI`, using the latest verified metric year.
- `Citations` — the latest explicitly requested Semantic Scholar citation snapshot.

Columns for years present in managed payloads coexist. Zotero's normal column
picker controls which years are visible; when the final managed payload for a
year is removed, the add-on removes that obsolete year's columns without
overwriting item metadata.

## Current scope

The add-on registers only years found in managed `AI4S-Metrics:` payloads. A
calendar/retrieval year never creates an IF/JCR/CAS column by itself. New years
are discovered as items are added or modified. `Citations` appears after an explicitly requested Semantic Scholar
citation refresh; it never refreshes in the background. The metrics plan/apply path in
`literature-manager` and `literature-zotero-mcp` is the only supported write
path; until a reviewed plan has been applied, the add-on correctly displays
only manually or test-populated `AI4S-Metrics` blocks.

The required `Extra` block is a single line:

```text
AI4S-Metrics: {"schema_version":2,"by_year":{"2025":{"impact_factor":12.4,"impact_factor_5y":13.1,"jcr_zone":"Q1","cas_zone":"1区","publication_metrics":[{"code":"cas_major","value":"医学1区"},{"code":"cas_top","value":true}],"retrieved_at":"2026-07-16","source_label":"easyscholar-2025","source_sha256":"..."}}}
```

Other `Extra` text is outside the managed block and is ignored by this add-on.

AI Summary uses a separate managed line:

```text
AI4S-Summary: {"schema_version":1,"text":"该研究……。","language":"zh-CN","basis":"title-abstract","title_sha256":"…","abstract_sha256":"…","generated_at":"2026-07-21T00:00:00Z"}
```

The add-on computes the same normalized title/abstract SHA-256 hashes as the
MCP. A mismatch displays `⚠` and a stale tooltip but never triggers generation
or a write. The sentence remains metadata and is not copied into Zotero's
native tag system.

Article types deliberately use Zotero's native tags rather than the metrics
payload. This makes them editable and filterable in Zotero's tag selector. The
add-on strips the managed prefix in the item-tree column, shows at most two
chips plus an overflow count, and keeps the full list in the cell tooltip:

```text
AI4S:ArticleType:Systematic Review
AI4S:ArticleType:Meta-Analysis
```

Agent Tags also use native Zotero tags so they remain filterable and manually
removable. The visible column hides the namespace and shows at most four
canonical English labels:

```text
AI4S:Semantic:Macrophage
AI4S:Semantic:Single-cell transcriptomics
```

The add-on never generates or writes these tags and never reads the local
semantic vocabulary JSON. Re-analysis and source automatic-tag cleanup are
restricted to the audited MCP workflow.

Priority uses the same native-tag approach:

```text
AI4S:Priority:1  # background/supporting
AI4S:Priority:2  # important
AI4S:Priority:3  # core/must-read
```

Priority means personal reading and use priority, not evidence quality. Keep
exactly one Priority tag per item. If conflicting values exist, the column
shows `⚠` and asks the user to choose a star instead of silently choosing one.
The agent may initialize a missing value from a reviewed report-stage
recommendation, but later imports preserve an existing user value.

Hovering over a star previews the prospective rating; clicking commits it in
one Zotero transaction. Clicking the saved level again clears Priority. The
control supports arrow-key preview, Enter/Space to commit, Escape to cancel the
preview, and Delete/Backspace to clear. This is the add-on's only item-write
path: it atomically replaces only `AI4S:Priority:1|2|3` and preserves every
other tag and field. Star presses stop Zotero's row-selection mouse event, so
the first click changes the rating; clicking elsewhere in the cell still
selects the item normally.

For batch rating, select one or more regular items in Zotero's main item tree
and press `1`, `2`, or `3`; press `0` to clear Priority. Bare-number shortcuts
are active only while focus is inside the item tree. They are ignored in search
boxes, editors, the PDF reader, during key repeat, or when a modifier key is
held. The item context menu provides the same commands under **Set Priority**.
After each batch, a progress popup reports updated, unchanged, read-only
skipped, and failed counts.

## Build and test

Node.js 20.19+ is required for local validation. The build uses one locked,
pure-JavaScript ZIP dependency; the installed XPI has no runtime npm
dependencies and invokes no operating-system archive command.

```bash
npm ci
npm test
npm run check
npm run package
```

The same commands run unchanged in Windows PowerShell. Packaging is implemented
entirely in Node and does not require `zip`, WSL, Git Bash, or 7-Zip.

Colors are a redundant visual cue only: every value remains visible as text,
IF/5-Year IF retain continuous numeric sort keys, and JCR/CAS retain explicit
ordinal sort keys. Descending JCR/CAS sorting places Q1/1区 before Q4/4区.

`npm run package` creates `dist/literature-metrics-0.1.13.xpi`. The add-on
declares Zotero 7.0 through 10.9 compatibility.

## Install in Zotero

1. Build the XPI package.
2. In Zotero, open **Tools → Add-ons**.
3. Click the gear menu and choose **Install Add-on From File…**.
4. Select the generated `.xpi`, then restart Zotero if prompted.
5. In the main item list, use the column picker to show `IF(2025)`,
   `5-Year IF(2025)`, `JCR(2025)`, `CAS(2025)`, `Journal Metrics`,
   `Article Type`, `Agent Tags`, `AI Summary`, `Priority`, `Citations`, or other verified years. Use Zotero's native
   tag selector to filter by a specific `AI4S:ArticleType:*` value.

This add-on is distinct from the repository-local Codex plugin. Install the
Codex plugin for the skills and MCP; install this XPI in Zotero Desktop for
metric columns.

## Safety

- Do not use this add-on as evidence that an IF/JCR/CAS value is current or
  correctly matched. The audited research workflow remains the evidence source.
- Corrupt or duplicate `AI4S-Metrics` blocks render as empty cells; they do not
  trigger writes.
- Corrupt or duplicate `AI4S-Summary` blocks also render empty; stale blocks
  remain visible with a warning and require an explicit Agent refresh request.
- No API keys, journal-metrics CSV files, PDFs, private notes, or Zotero
  database files belong in this directory.
