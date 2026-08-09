# Local deployment

Public deployment is intentionally disabled until upstream provenance is fully
recorded. For local evaluation, build and run the independently named image:

```bash
docker compose build literature-zotero-mcp
docker compose up literature-zotero-mcp
```

The service listens on port 3939 inside the Compose network. Configure secrets
only in a git-ignored `.env` file. The included Caddy service is optional and
requires `LITERATURE_ZOTERO_MCP_DOMAIN`; do not expose the MCP publicly without
OAuth and an explicit security review.

The systemd example expects a locally built `literature-zotero-mcp:local` image
and configuration under `/opt/literature-zotero-mcp`. It never pulls or
publishes the upstream Zoteus image.
