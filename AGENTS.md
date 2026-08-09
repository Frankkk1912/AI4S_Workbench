# AI4S Workbench Agent Guide

## Scope and source of truth

This public repository is the sole development and release source for AI4S
Workbench v0.1.0: Molecular Modeling Workbench, Literature Workbench, and
public-safe reusable skills. Keep private research data, credentials, personal
memory, experimental staging, and machine-local receipts out of Git.

Work on a branch, open a Draft PR early, and use the applicable GitHub Actions
contracts as the merge gate. Squash merge approved PRs into `main`.

## Repository layout

- `skills/` — standalone public-safe skills; each `SKILL.md` is its entry point.
- `plugins/molecular-modeling-workbench/` — WSL2-first molecular workflows.
  `source-skills/` is editable and `skills/` is generated.
- `plugins/literature-workbench/` — literature skills, bundled MCP runtimes,
  and the separately packaged Zotero Desktop metrics add-on. Its editable MCP
  source is under `source/`.
- `.github/workflows/` — repository and workbench CI/release contracts.
- `forge/`, private notes, credentials, and local Agent state — never commit.

## Development workflow

1. Start from current `main` and create a focused `feature/`, `fix/`,
   `docs/`, or `chore/` branch.
2. Make the smallest reviewable change and open a Draft PR.
3. Run the workbench-specific checks below and inspect the relevant CI result.
4. Before push or release, run the tracked-file safety scan and Gitleaks.
5. Squash merge only after required CI is green.

### Molecular Modeling Workbench

Edit `source-skills/`, then regenerate and verify the bundled skills:

```bash
cd plugins/molecular-modeling-workbench
npm run sync
npm run check
npm test
```

`npm test` intentionally omits the deferred docking-visualization suite. Use
`npm run test:all` only when investigating that suite. The Ubuntu CPU contract
is its required CI gate.

### Literature Workbench

Edit MCP code only in `plugins/literature-workbench/source/`, then regenerate
runtime bundles before committing generated changes:

```bash
cd plugins/literature-workbench
node scripts/assemble-plugin.mjs sync
node scripts/assemble-plugin.mjs check
```

Follow the workbench README for its runtime, skill, and Zotero add-on tests.
macOS and Windows release contracts are its required CI gate. Keep stable MCP
server identifiers unchanged unless an explicit compatibility change is
intended.

## Documentation

Keep the root README focused on the repository and its two workbenches. Put
component installation steps, supported platforms, and detailed contracts in
the relevant plugin README. Update the root `CHANGELOG.md` only for AI4S
Workbench repository releases; plugin release notes belong in their own
changelogs.

## Safety

- Never commit local Agent configuration, credentials, research inputs,
  trajectories, browser profiles, or generated private receipts.
- Preserve `.gitattributes` line-ending rules and use platform-neutral paths.
- Run this tracked-file scan before every release and config/documentation push:

  ```bash
  git ls-files | grep -iE '^\.(claude|codex|cursor)/|^\.env|\.(pem|key)$|secrets|credentials' \
    && echo "WARNING: sensitive files tracked" || echo "clean"
  ```

- Run `gitleaks git .` before releases; treat historical secret findings as
  leaked credentials that require rotation and history remediation.

## Releases

The root `package.json` is the AI4S Workbench version source and must equal
`release-meta.json`. Update the root `CHANGELOG.md`, merge the release PR, and
create `vX.Y.Z-beta.N` before a final `vX.Y.Z` tag when a prerelease is needed.

Root tags and GitHub Releases represent the entire AI4S Workbench repository.
Do **not** create root tags for individual plugins: their versions remain in
their own manifests and changelogs. The release workflow verifies the root
version, runs repository release contracts, and publishes a repository archive.
