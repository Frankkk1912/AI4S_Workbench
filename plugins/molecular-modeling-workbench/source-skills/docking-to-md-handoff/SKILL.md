---
name: docking-to-md-handoff
description: >-
  Validate selected docking poses and create a hash-linked, parameterization-aware
  handoff that molecular-dynamics preparation must accept before simulation.
---

# Docking-to-MD Handoff

## Overview

Validate a selected docking pose before MD preparation. It creates
`md_handoff.json`; ligand-containing systems are rejected unless topology and
parameterization evidence is present and internally consistent.

## Dependencies

- `docking-simulation-run`: produces `docking_manifest.json` and `ranked_poses.json`.
- `md-simulation-run`: accepts only a valid handoff for ligand MD.

## Quick Start

```bash
uv run scripts/docking_to_md_handoff.py create \
  --docking-manifest docking/docking_manifest.json \
  --ranked-poses docking/ranked_poses.json \
  --pose-id pose_001 --system-type protein-ligand \
  --parameterization ligand_parameters.json \
  --environment-receipt environment_receipt.json \
  --protein-force-field amber99sb-ildn --rationale "pose reviewed" \
  --output md_handoff.json
```

Use `validate --handoff md_handoff.json` immediately before MD preparation.

## Boundaries

- Docking scores and CNN values are retained as docking outputs; neither is a
  binding free energy or an experimental affinity.
- Protein-only and PPI workflows retain the same schema but mark ligand fields
  as not applicable.
- Selection rationale, source hashes, charge, topology paths, and unresolved
  warnings are mandatory audit fields. The selected docking pose must supply a
  hash-bound individual `coordinate_file`; a shared multi-model PDBQT is not
  admitted as an MD coordinate reference.
- When an MD handoff is intended, generate the ligand PDBQT with unique, stable
  atom names **before docking** and verify the docking engine preserves them.
  Protein-ligand admission rejects duplicate pose atom names and requires at
  least three shared non-hydrogen atom names between the selected pose PDBQT and
  the validated ligand GRO. The checked names and count are recorded under
  `ligand.alignment_admission`; do not infer mappings or reorder symmetric
  ligands.
- Validation recomputes the hashes of docking inputs, selected pose, topology,
  and coordinates and rechecks the named-atom alignment admission. Any changed,
  missing, or malformed protected file stops MD admission.
- `amber-gaff` requires an AMBER-family protein force field; `charmm-cgenff`
  requires a CHARMM-family protein force field.
- The environment receipt is schema-checked, must be `ready: true`, and is
  hash-linked into the handoff; a changed, stale, or unready receipt blocks MD.
