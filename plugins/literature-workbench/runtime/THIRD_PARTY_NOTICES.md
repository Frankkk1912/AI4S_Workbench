# Third-Party Notices

## Zoteus

`literature-zotero-mcp` is derived from Zoteus:

- Upstream project: <https://github.com/oscardvs/zoteus>
- Upstream package: `@oscardvs/zoteus`
- Upstream release tag: `v1.0.2`
- Annotated tag object: `fd2f9486869f173e93d53fd80b87cfa35ebef3d2`
- Peeled source commit: `6b2f5333b2d075cbc78100aef0d46db03ce92330`
- Original author and copyright holder: Oscar Devos
- License: MIT

On 2026-07-11, the staged `forge/zoteus-source` tree was compared recursively
against an official checkout of `v1.0.2` with `.git` excluded; no content
differences were found. The derivative remains marked `private` because public
distribution has not yet been explicitly reviewed or requested.

Material changes in this derivative include:

- independent project, package, MCP server, log, and data-directory naming;
- the read-only `zotero_find_duplicates` MCP tool;
- persistent duplicate-candidate audit reports;
- batch-versus-library duplicate detection and master-record recommendations;
- documentation that requires final merges to use Zotero Desktop.

The complete original MIT license is preserved in `licenses/ZOTEUS-LICENSE`.
This derivative is independently maintained and is not affiliated with or
endorsed by Zoteus or Zotero.
