# AI4S Workbench v0.1.0

[中文文档](README_CN.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-0F766E.svg)](LICENSE) [![Release: v0.1.0](https://img.shields.io/badge/Release-v0.1.0-2563EB.svg)](https://github.com/Frankkk1912/AI4S_Workbench/releases/tag/v0.1.0)

> Give your harness an auditable path from scientific intent to evidence, especially for biomedical researchers.

## Overview

AI4S Workbench is a public collection of plugins and reusable Agent Skills for harness including Codex CLI and Claude Code. It brings two evidence-first workflows into one repository: a Literature Workbench for retrieval, controlled Zotero operations, public-open-access (OA) fulltext handoffs, and evidence-traced writing; and a Molecular Modeling Workbench for WSL2-native docking-to-molecular-dynamics (MD) work.

The workbenches turn long-running research into file-based, reviewable handoffs. Literature searches preserve plans, ranked evidence, and reports before anything is written to Zotero or synthesized into prose. Molecular workflows preserve environment receipts, project briefs, manifests, hashes, stage records, and analysis data from onboarding through docking, GROMACS, and plotting.

Safety boundaries are explicit. Optional literature credentials stay in masked local configuration, higher-risk Zotero writes use review gates, and fulltext automation is limited to verified public OA routes. Molecular onboarding fails closed, makes no silent privileged changes, and requires scientific projects to run under the WSL Linux home filesystem rather than `/mnt/*`.

## Features

### Literature Workbench

- Retrieve, deduplicate, cap, and rank PubMed and arXiv evidence into `search_plan.json`, `ranked_all.json`, `ranked_all.csv`, and `report.md`.
- Synchronize reviewed records and reports to Zotero, audit duplicates without automatic deletion, manage controlled Agent Tags, and generate an AI Summary only after an explicit request.
- Verify legal public-OA PDF candidates before a separate hash-bound Zotero attachment handoff.
- Draft reviews, proposal backgrounds, introductions, and discussions under the strict **No Evidence, No Conclusion** rule.
- Optionally install the separate Zotero Desktop metrics add-on for evidence/metadata columns and an interactive personal Priority rating.

<!-- Screenshot: Zotero Desktop showing the AI4S Priority and AI Summary columns. -->

<!-- ![Zotero Desktop AI4S Priority and AI Summary columns](assets/zotero-ai4s-priority-ai-summary.png) -->

### Molecular Modeling Workbench

- Audit Windows 11, the exact `Ubuntu-22.04` WSL2 distribution, native ext4 paths, locked Python, scientific CLIs, Docker, and NVIDIA GPU evidence without silent elevation.
- Run GNINA-preferred or explicit AutoDock Vina fallback docking with normalized poses, engine-specific scores, manifests, and reports.
- Analyze protein–ligand or protein–protein contacts and generate editable ChimeraX-first or PyMOL-fallback scenes.
- Parameterize ligands, bind protected inputs into `md_handoff.json`, and fail closed when topology, force-field, or hashes do not match.
- Run staged GROMACS energy minimization, NVT, NPT, and production; then analyze RMSD, RMSF, Rg, SASA, DSSP, PCA, or DCCM and create traceable figures.

<!-- Screenshot: ChimeraX or PyMOL 3D render of a docked complex. -->

<!-- ![ChimeraX or PyMOL docked-complex 3D render](assets/docked-complex-3d-render.png) -->

## Quick Start

```text
Fetch and install my selected AI4S Workbench plugin from https://github.com/Frankkk1912/AI4S_Workbench for Codex CLI or Claude Code, and keep the two workbenches separate: for Literature Workbench, confirm a supported native macOS or Windows setup, run the native runtime bootstrap and `node scripts/onboard.mjs status --output onboarding-status.json`; for Molecular Modeling Workbench, confirm Windows 11 with the exact Ubuntu-22.04 WSL2 distribution and a workspace under the WSL Linux home rather than `/mnt/*`, run the read-only Windows preflight when applicable, initialize the WSL workbench, and use `molecular-modeling-environment` to audit and verify a current `environment_receipt.json`. Report every missing requirement, make no privileged or destructive change without my review, never ask me to paste credentials into chat, and guide me through first-use configuration before starting research work.
```

Choose one workbench for the task. Literature Workbench supports native macOS and Windows bootstrap and needs Node.js 20.19+ with npm; its skill scripts also use Python 3 and `uv`. Molecular Modeling Workbench scientific execution is locked to Windows 11 with `Ubuntu-22.04` on WSL2, Python `>=3.10,<3.13`, `uv`, and a native ext4 workspace. Its external scientific tools remain explicit user-managed prerequisites.

## Manual installation & configuration

Clone the repository on the operating system where the selected workbench will run:

```bash
git clone https://github.com/Frankkk1912/AI4S_Workbench.git
cd AI4S_Workbench
```

### Literature Workbench

From `plugins/literature-workbench`, use the native bootstrap for the current OS and inspect the redacted onboarding status:

```bash
cd plugins/literature-workbench
bash scripts/bootstrap-runtime.sh
node scripts/onboard.mjs status --output onboarding-status.json
```

Windows PowerShell:

```powershell
cd plugins\literature-workbench
.\scripts\bootstrap-runtime.ps1
node .\scripts\onboard.mjs status --output .\onboarding-status.json
```

### Molecular Modeling Workbench

From Windows PowerShell, the preflight is read-only and creates a new diagnostics directory:

```powershell
cd plugins\molecular-modeling-workbench
.\scripts\Start-AI4S-Workbench.ps1
```

Clone or move the checkout under the WSL Linux home filesystem—not `/mnt/*`—then initialize from `Ubuntu-22.04`:

```bash
cd "$HOME/AI4S_Workbench/plugins/molecular-modeling-workbench"
node scripts/assemble-plugin.mjs check
node scripts/verify-plugin.mjs
bash scripts/setup-wsl-workbench.sh \
  --agent codex \
  --workspace "$HOME/AI4S-Workbench-Projects"
```

Use `--agent claude` for Claude Code. Review the generated checklist, configure only approved missing tools, and have the Agent run `molecular-modeling-environment` until the current `environment_receipt.json` reports `ready: true`; docking and MD stay blocked otherwise.

## Installation

After plugin installation, still run the workbench-specific native bootstrap or WSL initialization above.

### Codex CLI

Install Codex CLI, add a local checkout as a marketplace, then use the marketplace alias printed by `codex plugin marketplace add` in place of `<marketplace-alias>`:

```bash
npm install -g @openai/codex
codex plugin marketplace add <repo-path>
codex plugin add literature-workbench@<marketplace-alias>
# or
codex plugin add molecular-modeling-workbench@<marketplace-alias>
```

Do not assume that a machine-local alias such as `personal` will exist on another installation.

### Claude Code

Run these as Claude Code plugin commands, not shell commands:

```text
/plugin marketplace add Frankkk1912/AI4S_Workbench
/plugin install literature-workbench@ai4s-workbench
```

Or install the molecular plugin after adding the same marketplace:

```text
/plugin install molecular-modeling-workbench@ai4s-workbench
```

## Configuration

### Literature Workbench

Core PubMed/arXiv retrieval, deduplication, ranking, and writing from saved evidence work without API keys. Zotero Desktop Local API can provide key-free reads; approved Zotero cloud writes require a write-capable Zotero Web API key, and file upload also requires file permission.

All optional credentials are local enhancements:

| Variable                | Purpose                                                          |
| ----------------------- | ---------------------------------------------------------------- |
| `ZOTERO_API_KEY`      | Zotero Web API identity and approved cloud library writes        |
| `NCBI_API_KEY`        | Higher PubMed E-utilities allowance and steadier batch retrieval |
| `EASYSCHOLAR_API_KEY` | Selected-journal rank and metric enrichment                      |

Never paste a key into Agent chat or pass one as a command argument. Use the masked local wizard from `plugins/literature-workbench`:

```bash
node scripts/onboard.mjs setup --output onboarding-result.json
```

Reconfigure one provider with `node scripts/onboard.mjs reconfigure --provider zotero|pubmed|easyscholar --output onboarding-result.json`. The wizard validates before replacement and writes only redacted status. The optional Zotero Desktop XPI is built and installed separately; the onboarding result provides its reminder.

### Molecular Modeling Workbench

No API key or project `.env` is required. Authenticate the Coding Agent only through its provider's official flow. Scientific commands and large calculation files must remain under the WSL Linux `$HOME`; `/mnt/c` and every other `/mnt/*` path are forbidden for scientific execution.

The supported onboarding target is Windows 11 with the exact `Ubuntu-22.04` WSL2 distribution. The locked runtime uses Python `>=3.10,<3.13`, `pyproject.toml`, `uv.lock`, and `uv`. The environment receipt records absolute paths and versions for GNINA, Vina, GROMACS (`gmx`), acpype, Open Babel (`obabel`), ChimeraX, and PyMOL. Missing tools are failed capability checks, not permission to silently change a backend or scientific parameter.

## Prompt Examples

### 1. Audit a molecular environment

```text
Use molecular-modeling-environment to audit this Ubuntu-22.04 WSL2 workspace before docking. Check the native ext4 path, locked Python and uv runtime, GNINA/Vina, GROMACS, acpype, Open Babel, ChimeraX/PyMOL, Docker, and NVIDIA GPU evidence. Do not install anything or use sudo. Write the checklist and environment receipt, report every missing capability, and propose a reviewable configuration plan.
```

**Involved:** `molecular-modeling-environment`.

### 2. Dock, analyze, and prepare a 3D scene

```text
Create an auditable docking project for receptor [receptor.pdb] and ligand [ligand.sdf]. Validate the ready environment receipt, ask me to confirm protonation, ligand charge, binding-site center, and box size, then run GNINA when its GPU capability is verified or record an explicit Vina fallback. Rank individual poses, analyze contacts, and prepare a ChimeraX-first visualization without turning docking scores into binding-energy claims.
```

**Involved:** `docking-project-manager`, `docking-simulation-run`, `docking-complex-analysis`, `docking-visualization`.

### 3. Retrieve evidence and synchronize a reviewed selection

```text
Search PubMed for the role of NLRP3 in cardiovascular disease. Cap retrieval at 50, rank the top 30, and preserve search_plan.json, ranked_all.json, ranked_all.csv, and report.md. After I review the selection, sync project `nlrp3-cvd` to the Zotero collection `NLRP3 cardiovascular disease`; show ambiguity or large-create review before proceeding and do not overwrite existing Priority.
```

**Involved:** `literature-research`, `literature-manager`, and `ai4s-literature-zotero` tools such as `zotero_sync_literature_project`.

### 4. Fetch public OA evidence and write from it

```text
For the exact Zotero parent items I selected, use only legal public-OA routes, poll the Fulltext MCP job, and apply only a verified hashed handoff. Do not use institutional login, VPN, cookies, or access-control bypass. Then draft a review section from saved ranked_all.json and report.md, put an [EV:<index>] placeholder on every scientific claim, disclose search caps and fulltext status, and include a reference-audit table.
```

**Involved:** `literature-manager`, `literature-writing`, `ai4s-literature-fulltext`, and `ai4s-literature-zotero`.

## Available Skills

The plugin skill directories are bundled for their workbench; matching public-safe sources also live under [`skills/`](skills/). The internal `molecular-geometry-common` helper is intentionally not offered as a standalone user workflow.

### Literature Workbench

| Skill                   | Use it for                                                                                        |
| ----------------------- | ------------------------------------------------------------------------------------------------- |
| `literature-research` | Source retrieval, deduplication, ranking, and auditable evidence files                            |
| `literature-manager`  | Reviewed Zotero imports/sync, metrics, duplicate audit, tags, and explicitly requested AI Summary |
| `literature-writing`  | Evidence-traced reviews, manuscript sections, bilingual prose, and citation audits                |

### Molecular Modeling Workbench

| Skill                              | Use it for                                                              |
| ---------------------------------- | ----------------------------------------------------------------------- |
| `molecular-modeling-environment` | Environment audit, onboarding, planning, bootstrap, and verification    |
| `docking-project-manager`        | Persistent docking briefs, decisions, routing, and final reports        |
| `docking-simulation-run`         | GNINA-preferred or Vina-fallback protein–ligand docking                |
| `docking-complex-analysis`       | Deterministic protein–ligand or protein–protein contact geometry      |
| `docking-visualization`          | ChimeraX-first or PyMOL-fallback offline 3D scenes                      |
| `ligand-parameterization`        | Auditable small-molecule parameterization and`ligand_parameters.json` |
| `docking-to-md-handoff`          | Hash-bound selected-pose admission to ligand MD                         |
| `md-project-manager`             | Pre-simulation brief and final evidence-based report                    |
| `md-simulation-run`              | Staged GROMACS preparation, execution, and resumption                   |
| `md-trajectory-analysis`         | Basic QC and hypothesis-driven advanced trajectory analysis             |
| `md-simulation-plotting`         | Publication-grade QC, FEL, DCCM/network, and geometry plots             |

### Standalone reusable skills

| Skill                               | Use it for                                                                                |
| ----------------------------------- | ----------------------------------------------------------------------------------------- |
| `scientific-infographic-onepager` | Editable HTML plus PNG science-popularization onepagers                                   |
| `western-blot-processor`          | Western Blot auto-cropping and Gamma contrast adjustment                                  |
| `workflow-skill-creator`          | Distilling a completed workflow into a reusable Agent Skill after mandatory brainstorming |

## MCP Tools

The Literature Workbench registers exactly two active servers in [`plugins/literature-workbench/.mcp.json`](plugins/literature-workbench/.mcp.json). The Molecular Modeling Workbench does not register an MCP server.

### `ai4s-literature-zotero`

The workbench profile exposes controlled Zotero identity, search/read, reviewed writes, organization, and project synchronization. Representative real tools and key inputs include:

| Capability            | Tool                                                           | Key inputs                                                                                            |
| --------------------- | -------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| Identity              | `zotero_whoami`                                              | none                                                                                                  |
| Search                | `zotero_search_items`                                        | `q`, `itemType`, `tag`, `collectionKey`, `limit`; optional `library_type`, `library_id` |
| Item/fulltext read    | `zotero_get_item`, `zotero_get_fulltext`                   | `item_key`; fulltext can add `query`, `page_range`, `max_passages`                            |
| Reviewed import       | `zotero_apply_import_plan`                                   | `plan_path`, `mode`; apply requires `receipt_path`, `confirm_plan_hash`                       |
| Duplicate audit       | `zotero_find_duplicates`                                     | one of`collection_key`/`tag`, plus `limit`                                                      |
| Project sync          | `zotero_sync_literature_project`                             | `project_slug`, `search_date`, `report_path`, `evidence_path`                                 |
| AI Summary            | `zotero_ai_summary_context`, `zotero_apply_ai_summaries`   | selected items/collection; apply requires`trigger="explicit-user-request"` and `items`            |
| OA attachment handoff | `zotero_fulltext_context`, `zotero_apply_fulltext_handoff` | `item_keys`; then `handoff_id`, `handoff_hash`                                                  |

Duplicate detection is read-only, confirmed merges remain manual in Zotero Desktop, and higher-risk apply operations require reviewed plans and matching hashes.

### `ai4s-literature-fulltext`

This OA-only server provides `fulltext_capabilities`, `fulltext_access_status`, `fulltext_fetch_submit`, `fulltext_job_status`, and `fulltext_job_cancel`. Submit uses `request_id`, `route_policy="oa_only"`, and `records[]`; each record identifies its evidence and Zotero parent and supplies a title plus a DOI, arXiv ID, or repository ID. Poll and cancel use `job_id`.

Fulltext support is **public OA only**. It does not automate institutional or SSO access, accept institutional credentials, connect a VPN, bypass access controls, return PDF bytes/full text in chat, or directly upload to Zotero. `fulltext_session_open` is a deferred interface that returns `INSTITUTION_ACCESS_UNAVAILABLE` in this runtime.

## Project Structure

```text
AI4S_Workbench/
├── .claude-plugin/                    # Claude Code marketplace manifest
├── .github/workflows/                 # CI and release contracts
├── plugins/
│   ├── literature-workbench/
│   │   ├── .mcp.json                  # Two active MCP servers
│   │   ├── skills/                    # Three bundled literature skills
│   │   ├── runtime/                   # Assembled Zotero MCP
│   │   ├── fulltext-runtime/          # Assembled OA Fulltext MCP
│   │   └── source/                    # Editable MCP and Zotero add-on source
│   └── molecular-modeling-workbench/
│       ├── source-skills/             # Editable molecular skill source
│       ├── skills/                    # Generated bundled skills
│       ├── scripts/                   # Assembly, checks, tests, onboarding
│       └── runtime-contract.json       # WSL/Python/tool evidence policy
├── skills/                             # Standalone public-safe skill sources
├── AGENTS.md                           # Development source of truth
├── CITATION.cff
├── LICENSE
├── package.json                        # Root v0.1.0 version source
├── README.md
└── README_CN.md
```

## Development

Follow [`AGENTS.md`](AGENTS.md), keep private data and local Agent state out of Git, and edit generated areas only through their source workflows.

For Molecular Modeling Workbench, edit `source-skills/`, then regenerate and verify:

```bash
cd plugins/molecular-modeling-workbench
npm run sync
npm run check
npm test
```

For Literature Workbench MCP code, edit only `source/`, then assemble and check the runtime bundles:

```bash
cd plugins/literature-workbench
node scripts/assemble-plugin.mjs sync
node scripts/assemble-plugin.mjs check
```

The Molecular Ubuntu CPU contract and Literature macOS/Windows release contracts are the required CI gates. Root tags represent the entire repository; plugin versions remain in their own manifests and changelogs.

## License & Citation

AI4S Workbench is released under the [MIT License](LICENSE). If you use the Molecular Modeling Workbench, follow the message and metadata in [`CITATION.cff`](CITATION.cff) and also cite the underlying scientific software used in your workflow. Root repository releases are versioned by `package.json` and `release-meta.json`.
