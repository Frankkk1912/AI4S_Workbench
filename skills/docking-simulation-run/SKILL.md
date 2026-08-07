---
name: docking-simulation-run
description: >-
  Prepare and execute reproducible GNINA-preferred or AutoDock Vina docking,
  writing normalized poses, engine-specific scores, manifests, and reports.
---

# Docking Simulation Run

## Overview

Run protein-ligand docking with one normalized output contract. GNINA is used
when an environment receipt supports it; Vina is the fallback only if GNINA
fails before a valid result. The fallback preserves the supplied inputs and
search box exactly.

## Dependencies

- `molecular-modeling-environment` for an environment receipt.
- `docking-project-manager` for the project brief and decisions.
- `docking-to-md-handoff` for selected-pose MD admission.

## Quick Start

```bash
uv run scripts/docking_run.py run --backend auto --profile wsl2-gpu --receptor receptor.pdbqt \
  --ligand ligand.pdbqt --center 10,12,8 --size 20,20,20 --seed 7 \
  --environment-receipt environment_receipt.json --output-dir docking
```

Outputs are `docking_manifest.json`, `ranked_poses.json`, raw engine output,
`individual-poses/pose_###.pdbqt`, `docking_report.md`, and a command log.
Each normalized pose has a `coordinate_file` path and SHA256 for one individual
PDBQT model; use that file, rather than the shared multi-model raw output, for
any downstream MD handoff. Scores remain explicitly named by engine and are
never described as experimental affinities.

## Boundaries

- v1 executes protein-small-molecule docking only. PPI must use an explicitly
  selected specialized backend and records a no-run route here.
- A backend fallback never regenerates the search box or scientific inputs.
- The receipt must be schema `1.1`, `ready: true`, profile-matched, no older
  than seven days, and prove the selected engine is available at an existing
  absolute executable path. The runner uses that receipt-bound path instead of
  re-resolving the engine through `PATH`.
- If both engines fail, execution stops with saved diagnostics.
- A run whose MODEL count cannot be matched one-to-one with ranked poses fails
  instead of emitting ambiguous MD starting coordinates.
