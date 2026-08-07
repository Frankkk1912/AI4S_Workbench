# Web of Science Database Pattern

## Access Mode
- Use `web-access` for browser readiness and navigation because WoS is dynamic and often depends on campus IP, VPN, institutional redirects, or login state.
- Use the official WoS export path for records; do not replace export with DOM scraping.
- Normalize official CSV/TSV exports with `literature_search.py import-wos-export`.

## Effective Pattern
1. Run or confirm the `web-access` CDP readiness check before browser-assisted WoS work.
2. Open `https://www.webofscience.com/wos/alldb/basic-search` in the campus-authenticated browser.
3. Enter the planned WoS Topic query and apply user-requested filters such as year, document type, collection, research area, or citation sorting.
4. Export records through the official WoS UI. Prefer CSV or tab-delimited text with full record fields.
5. Keep the raw export outside this repository, then run `import-wos-export` to create auditable JSON.
6. Merge/rank WoS JSON with PubMed/arXiv JSON and state WoS limits in the report.

## Evidence Files
- Query plan JSON containing `wos_query` and WoS filters.
- Optional screenshot showing query/result context.
- Official WoS CSV/TSV export kept outside the repository.
- Normalized WoS records JSON.
- Ranked JSON/CSV and final Markdown report.

## Known Traps
- Do not bypass CAPTCHA, institutional login, license limits, or export controls.
- Headless automation is fragile for WoS; visible/local browser workflow is preferred when interaction is required.
- XLSX exports should be converted to CSV/TSV before import unless an explicit parser is available.
- WoS result counts and PubMed result counts are not directly comparable.
