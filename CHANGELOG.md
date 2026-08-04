# Changelog

All notable changes are documented here.

## 0.2.0 — 2026-08-04

- Adds a non-destructive Windows 11 preflight and a fail-closed Ubuntu 22.04
  WSL2 initializer for newcomers.
- Guides users to WSL-native Codex CLI or Claude Code while keeping Windows
  desktop clients outside the scientific execution path.
- Adds explicit diagnostics and handoffs for WSL, Docker, NVIDIA, Agent setup,
  Linux-home workspaces, and the existing verified environment receipt.
- Does not automate elevation, reboot, Docker/GPU drivers, proprietary tools,
  credentials, or Agent authentication.

## 0.1.0 — 2026-07-27

- Initial WSL2-first public beta of Molecular Modeling Workbench.
- Adds auditable docking, visualization, ligand parameterization, validated
  docking-to-MD handoff, MD orchestration, analysis, and plotting skills.
- Requires a verified environment receipt before scientific execution.
- PLIP, native Windows execution, HPC scheduling, and multi-GPU workflows are
  not supported in this release.
