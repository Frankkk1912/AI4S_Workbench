# AI4S Workbench Agent Guide

## Source of truth

This public repository is the sole development and release source for the
Molecular Modeling Workbench. Work on a branch, open a Draft PR early, and use
GitHub Actions as the Ubuntu 22.04 verification gate.

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
