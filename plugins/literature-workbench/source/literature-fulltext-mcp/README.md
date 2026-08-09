# Literature Fulltext MCP

An independent, OA-first MCP runtime for the Literature Workbench. Its
first release supports only public HTTP/HTTPS OA routes (PMC lookup plus
explicit candidate URLs), validates an actual main-article PDF before creating
a compact hashed handoff, and never handles Zotero credentials or institutional
login state.

It does not use Sci-Hub, LibGen, proxies, VPN automation, hidden browsers,
credential imports, or access-control workarounds. Institutional-browser
fallback is intentionally separate. A separate controlled Zotero MCP tool
consumes only the resulting private handoff; this runtime never holds a Zotero
credential or uploads bytes itself.

Use `npm ci && npm run build`. Runtime state and artifacts live in private
application-data directories; no PDFs or receipts are stored in this source
repository.
