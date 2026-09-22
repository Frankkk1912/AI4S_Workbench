# Changelog

All notable AI4S Workbench repository releases are documented here.

## [0.3.0] — 2026-09-19

Molecular Modeling Workbench plugin update; no release workflow is triggered by
this changelog entry.

- Adds a localhost-only FastAPI and React MD workbench with an independent,
  crash-aware task runner, SQLite lifecycle authority, and user-level service
  templates.
- Adds explicit scientific-parameter approval, receipt and artifact hash gates,
  safe checkpoint stop/recovery, audited continuation, live monitoring, and
  reproducible RMSD/RMSF plus thermodynamic diagnostics.
- Adds mock-Docker crash/concurrency/rollback drills, real-GROMACS CPU analysis
  fixtures, frontend/backend/runner suites, and a dedicated CI web-tests job.
- Records the real-GPU restart and checkpoint drill as a pending manual release
  gate; no GPU behavior is claimed until that evidence is completed.
- Keeps Literature Workbench workflows and automated release configuration
  unchanged.

## [0.1.0] — 2026-08-09

First public release of AI4S Workbench.

- Includes the public Molecular Modeling Workbench and Literature Workbench
  plugins, plus public-safe reusable skills.
- Establishes repository-wide release metadata, cross-platform verification,
  and GitHub release archives.
- Root tags represent AI4S Workbench releases only; individual plugin versions
  are maintained in their own manifests and changelogs.
