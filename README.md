# AI4S Workbench v0.1.0

[AI4S Workbench v0.1.0](https://github.com/Frankkk1912/AI4S_Workbench/releases/tag/v0.1.0)
is the first public repository release of reproducible AI-for-science agent
workbenches and reusable skills. It contains only distributable, public-safe
artifacts; private research data, credentials, personal memory, experimental
staging, and machine-specific configuration are deliberately excluded.

## Included workbenches

### Molecular Modeling Workbench

[`plugins/molecular-modeling-workbench/`](plugins/molecular-modeling-workbench/)
provides auditable WSL2-first docking-to-MD workflows. It guides Windows users
through non-destructive preflight and hands scientific execution to Ubuntu WSL.

### Literature Workbench

[`plugins/literature-workbench/`](plugins/literature-workbench/) provides
retrieval, controlled Zotero workflows, verified public-OA fulltext handoffs,
and evidence-traced scientific writing. It supports native macOS and Windows;
its bundled Zotero Desktop add-on is installed separately.

Each workbench has its own README, installation instructions, scope boundaries,
and verification commands. Choose the narrow workbench that matches the task.

## Getting started

```bash
git clone https://github.com/Frankkk1912/AI4S_Workbench.git
cd AI4S_Workbench
```

Then follow the selected workbench's README:

- [Molecular Modeling Workbench](plugins/molecular-modeling-workbench/README.md)
- [Literature Workbench](plugins/literature-workbench/README.md)

Do not copy `node_modules`, generated `dist` files, credentials, or local
configuration between machines or operating systems. Bootstrap each workbench
natively and retain its documented verification receipt.

## Reusable skills

Standalone public-safe skill sources are in [`skills/`](skills/). Every
`skills/<name>/SKILL.md` is an entry point. Private-only skills and local Agent
state are not part of this repository.

## Verification and releases

The root version (`package.json` and `release-meta.json`) describes the **AI4S
Workbench repository**. Its `vX.Y.Z` tags and GitHub Releases cover the entire
repository archive, not individual plugins. Plugin versions remain in their
own manifests and changelogs.

GitHub Actions are the release gate:

- Molecular Modeling Workbench uses the Ubuntu CPU contract.
- Literature Workbench uses macOS and Windows release contracts.
- Root tags run repository release contracts and publish a repository archive.

See [CHANGELOG.md](CHANGELOG.md) for repository releases and the individual
workbench documentation for component-specific changes.

## Safety boundaries

Scientific tools and privileged system changes are never installed
implicitly. WSL enablement, Docker, GPU drivers, proprietary software,
credentials, browser logins, and Agent authentication remain explicit user
handoffs. Before sharing research results, retain the relevant verified
receipts and avoid placing private inputs or credentials in the repository.
