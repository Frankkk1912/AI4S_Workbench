# Distribution status

`literature-zotero-mcp` 0.1.0 is a private, locally built derivative package.
Public npm, MCP Registry, GHCR, DXT release, and hosted deployment are disabled.

Before enabling public distribution:

1. Re-run the full license and dependency audit.
2. Choose and verify an available package/registry identifier.
3. Remove `private: true` only through an explicitly reviewed release change.
4. Create new release workflows that publish only the independently named
   derivative; never reuse `@oscardvs/zoteus` or upstream container names.

The staged source provenance has been verified against upstream `v1.0.2`; see
`THIRD_PARTY_NOTICES.md` for the tag object, peeled commit, and comparison record.

Local validation remains:

```bash
npm install
npm test
npm run typecheck
npm run build
npm pack --dry-run
```
