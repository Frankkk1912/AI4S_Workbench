# AI4S Workbench

Public, release-ready AI4S agent plugins and reusable skills maintained by
[Frankkk1912](https://github.com/Frankkk1912). This repository intentionally
contains only distributable workbenches and public-safe skills; private research
data, personal memory, experimental staging content, and machine-specific
configuration are not included.

## Plugins

- [`molecular-modeling-workbench`](plugins/molecular-modeling-workbench/) —
  auditable docking-to-MD workflows for a WSL2-first public beta.

## Reusable skills

Standalone, public-safe skill sources live in [`skills/`](skills/). Each
`skills/<name>/SKILL.md` is the entry point for that skill. The private
`frank_global_memory/` skill, repository-local plugins, and `forge/` staging
area are intentionally not included here.

## Quick start

Windows 11 newcomers can download a reviewed local copy and run the plugin's
non-destructive PowerShell preflight. Scientific work then moves to a fresh
Linux-side clone under Ubuntu 22.04 WSL2, where the WSL initializer creates the
onboarding checklist and a Codex CLI or Claude Code handoff. Follow the plugin's
detailed README; Windows desktop clients are not scientific command executors.

The public plugin includes both `source-skills/` and its generated `skills/`
bundle, so `npm run sync`, `npm run check`, and `npm test` can run from a clean
checkout.

Scientific tools such as GNINA, Vina, GROMACS, ACPYPE, ChimeraX, and PyMOL are
not downloaded automatically. WSL enablement, Docker, GPU drivers, privileged
changes, and Agent login remain explicit user handoffs. Run the environment
audit and retain its verified receipt before starting a scientific workflow.
