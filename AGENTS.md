# AI4S Workbench Agent Guide

## Source of truth

This public repository is the sole development and release source for the
Molecular Modeling Workbench, the in-development AI4S Literature Workbench,
and its public-safe reusable skills. Work on a branch, open a Draft PR early,
and use GitHub Actions as the relevant verification gate.

## Repository layout

- `skills/` contains standalone public-safe skill sources. Each skill is
  entered through `skills/<name>/SKILL.md`.
- `plugins/` contains repository-local distributable plugin bundles.
- `literature-zotero-mcp/`, `literature-fulltext-mcp/`, and
  `literature-metrics/` are source packages used by the in-development
  literature plugin.
- `forge/`, private memory, credentials, and machine-local artifacts do not
  belong in this public repository.

## Plugin workflow

The editable skill sources are in
`plugins/molecular-modeling-workbench/source-skills/`. The adjacent `skills/`
directory is generated. After changing a source skill, run:

```bash
cd plugins/molecular-modeling-workbench
npm run sync
npm run check
npm test
```

`npm test` intentionally excludes the deferred docking-visualization suite.
Run `npm run test:all` when investigating that suite.

## Literature Workbench workflow (in development)

The literature plugin lives at
`plugins/ai4s-literature-workbench/`; its bundled skills, MCP runtimes, and
Zotero Desktop add-on are retained for development and review. Follow its
README and `v0.1.0-release-plan.md`; do not tag or release it until a separate
acceptance decision promotes the Draft PR.

## Safety

- Do not commit agent-local configuration, credentials, research inputs,
  trajectories, or machine-specific receipts.
- Keep paths platform-neutral and retain the `.gitattributes` line-ending
  rules.
- Before a push or release, run the tracked-file safety scan and Gitleaks.

## Releases

The plugin `package.json` is the release version source. Keep its version equal
to `plugin-meta.json`, update `CHANGELOG.md`, then create `vX.Y.Z-beta.N`
before a final `vX.Y.Z` tag. The release workflow verifies the tag, runs the
Ubuntu contracts, and publishes a plugin archive.
