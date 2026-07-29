---
name: ligand-parameterization
description: >-
  Detect, plan, and run auditable small-molecule ligand parameterization
  (GAFF2 via acpype, with sobtop/CGenFF handoffs) that produces the
  ligand_parameters.json evidence required by the docking-to-MD handoff.
---

# Ligand Parameterization

## Overview

Prepare small-molecule ligand topology and coordinate files for MD before the
docking-to-MD handoff. The Agent helps the user pick a force-field route and
net charge; the local CLI detects available engines, writes a reviewable plan,
executes only permitted local commands, and finalizes a handoff-compatible
`ligand_parameters.json`.

## Dependencies

- `molecular-modeling-environment`: verifies the base tooling (`obabel`,
  `gmx`) and per-component micromamba prefixes.
- `docking-to-md-handoff`: consumes the finalized `ligand_parameters.json`;
  it requires `ligand_identity`, `net_charge`, existing `topology` and
  `coordinates` paths, and `validation.status` equal to `validated`.
- `md-simulation-run`: CHARMM36 workflows pair with the `charmm-cgenff` route;
  AMBER-family workflows pair with `amber-gaff`.

## Quick Start

```bash
uv run scripts/ligand_parameterization.py detect --output-dir ligand_params
uv run scripts/ligand_parameterization.py plan \
  --ligand ligand.mol2 --force-field amber-gaff --net-charge 0 \
  --output-dir ligand_params
uv run scripts/ligand_parameterization.py run \
  --plan ligand_params/ligand_parameterization_plan.json \
  --environment-receipt environment_receipt.json --output-dir ligand_params
uv run scripts/ligand_parameterization.py finalize \
  --receipt ligand_params/parameterization_receipt.json \
  --topology ligand_params/ligand.acpype/ligand_GMX.itp \
  --coordinates ligand_params/ligand.acpype/ligand_GMX.gro \
  --charges-verified --output ligand_params/ligand_parameters.json
```

## Routes

- `amber-gaff` (engine `acpype`, auto-runnable): GAFF2 parameters through the
  acpype wrapper of Antechamber/parmchk2/tleap, emitted as GROMACS
  `<identity>_GMX.itp` and `<identity>_GMX.gro`. The plan pins `-c user` so
  the explicit net charge is used verbatim.
- `amber-gaff` (engine `sobtop`, handoff): sobtop is a manual download from
  the author's site; the plan records the handoff and expected outputs.
- `charmm-cgenff` (engine `cgenff`, handoff): CGenFF requires the licensed
  program or the official web service. Generate the `.str` stream manually,
  convert it with the cgenff_charmm2gmx script, then run `finalize` against
  the receipt.

## Charge and Protonation

`--net-charge` is mandatory and never inferred. Determine it before planning:
inspect the ligand's ionizable groups at the intended pH, check the input
structure's protonation (for example `obabel -p 7.4`), and confirm against
chemical knowledge or literature. `finalize` only writes
`validation.status: validated` when `--charges-verified` is passed after the
user inspects the per-atom charges; otherwise it stays `pending_review` and
the handoff rejects it.

## Boundaries

- No engine (acpype, sobtop, CGenFF) is ever downloaded automatically.
- Plans are SHA256-hashed; `run` refuses a modified plan.
- The `validated` status is bookkeeping evidence (files exist, hashes
  recorded, charges inspected), not a physical accuracy guarantee.
- Docking scores play no role in charge or parameter decisions.

## Common Mistakes

1. **Guessed net charge**: always derive it from protonation analysis, not
   from docking output or intuition.
2. **Skipping charge inspection**: acpype with `-c user` keeps input per-atom
   charges; uninspected charges leave the handoff blocked at `pending_review`.
3. **Mixing force-field families**: GAFF2 topologies belong with AMBER-family
   protein force fields; CHARMM36 protein systems need the CGenFF route.
