---
name: docking-project-manager
description: >-
  Create persistent, auditable docking project briefs, decision logs, and final
  reports that route protein-ligand and PPI work through reproducible stages.
---

# Docking Project Manager

## Overview

This skill is the persistent project record for docking. Start with a brief,
record deviations in a decision log, and write a final report from saved
artifacts rather than conversation memory.

## Dependencies

- `molecular-modeling-environment` for verified execution capability.
- `docking-simulation-run`, `docking-complex-analysis`, and
  `docking-visualization` for the computational route.
- `docking-to-md-handoff` before ligand-containing MD.

## Quick Start

```bash
uv run scripts/docking_project.py init --project-name EGFR_ligand \
  --system-type protein-ligand --question "Rank poses for a defined pocket" \
  --output-dir project
```

Then append a decision with `decision`, and produce a template-backed final
report with `report` after artifacts exist.

## Guardrails

- State structural sources, protonation assumptions, pocket basis, and limits.
- Do not call docking scores experimental affinities or binding free energies.
- A fallback backend must be recorded as a decision; it cannot change the
  search box or scientific parameters automatically.
