# Source Policy

## v1 Sources
- PubMed through NCBI E-utilities.
- arXiv through the public arXiv API.
- Web of Science through campus-network browser access plus official CSV/TSV
  export import.
- Versioned bundled `jcr_journals_2025.csv` for ISSN, CAS zone, JCR zone, and
  impact-factor filtering/enrichment. A user-provided reviewed CSV is an
  explicit override, not a prerequisite.

## Optional citation enrichment
- **Crossref** via `/works/{doi}` API. Provides `is-referenced-by-count` and
  `references-count`.
  Rate limit: 50 req/s (polite pool with `mailto` parameter from config or
  `CROSSREF_MAILTO` env). v1 does not depend on Crossref for core search;
  it is enrichment-only.

Citation enrichment does **not** change record scores by default. Scoring
adjustments require explicit `--citation-weight` on `merge-rank`. See
`references/ranking.md` for the formulae.

## Campus-Network Sources
- A generic online search tool is not assumed to have Frank's campus IP,
  institutional login, or library proxy. Use it for public web verification
  only.
- A local browser or local Playwright process running on Frank's machine may use
  campus IP/VPN privileges. Prefer this path for WoS, journal sites, and
  subscription full text.
- For Web of Science, prefer official export files over DOM scraping. Import the
  export with `import-wos-export` so the downstream ranking/report workflow
  remains auditable.
- Use headless browser mode only when the WoS page loads directly under campus
  IP and no login, CAPTCHA, or export dialog needs human interaction. Otherwise
  use a visible browser session and continue from exported records.
- Do not store cookies, browser profiles, private exported records, or full-text
  PDFs inside this repository.

## Deferred Sources
- Zotero import/search is deferred until local API or Better BibTeX behavior is
  specified.
- Google Scholar requires browser automation via web-access CDP; deferred to
  future phase.
- Local n8n transfer bundles are implementation references only. Do not commit
  Docker archives, n8n databases, or private/unlicensed replacement journal
  metric tables into this skill.

## Rate-Limit References
- NCBI E-utilities documentation:
  `https://www.ncbi.nlm.nih.gov/books/NBK25497/`
- arXiv API user manual:
  `https://info.arxiv.org/help/api/user-manual.html`
- Crossref API etiquette:
  `https://github.com/CrossRef/rest-api-doc#etiquette`
