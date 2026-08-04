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
  --ligand ligand.sdf --force-field amber-gaff --net-charge 0 \
  --charge-method bcc --output-dir ligand_params
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
  `<identity>_GMX.itp` and `<identity>_GMX.gro`. `--charge-method bcc` maps to
  ACPYPE `-c bcc` (AM1-BCC) and is the default for SDF, PDB, and MOL2 inputs.
  `--charge-method user` maps to `-c user` and is accepted only for an
  explicitly reviewed MOL2 that already contains user partial charges. The
  receipt-backed runner never adds, removes, or rewrites `LD_LIBRARY_PATH` for
  the initial ACPYPE process; it passes through the caller's value unchanged.
  Injecting `<prefix>/lib` at process launch can make a pip `openbabel-wheel`
  extension bind to an ABI-incompatible prefix `libopenbabel`, even though a
  clean Python import works. ACPYPE later replaces `LD_LIBRARY_PATH` with its
  bundled AmberTools library directory before starting tools such as SQM and
  teLeap, so an initial prefix prepend is both ineffective for those children
  and unsafe for ACPYPE's own Python imports. The runner instead safely derives
  ACPYPE's bundled `amber_linux/bin` from the prefix-owned Python in
  the ACPYPE launcher's shebang and that interpreter's isolated `purelib`
  location. It runs the system `ldd` only on ELF files directly in that known
  bundled directory, accepts only lines exactly shaped as
  `<soname> => not found`, and preloads a soname only when the same basename is
  a file directly under `<prefix>/lib`. All discovered verified paths are
  prepended to child-only `LD_PRELOAD`, which survives into ACPYPE's child
  processes; inherited values remain after them. If package discovery or
  `ldd` is unavailable, times out, or finds no matching libraries, the runner
  does not override `LD_PRELOAD` and does not fail for that reason. This is a
  runner-specific workaround: use the runner and do not set either variable
  through manual or global exports.

  The action receipt's `runtime_environment.LD_PRELOAD_prepend` is a stable
  ordered list containing the complete set of paths added by discovery. There
  is no runner-added `LD_LIBRARY_PATH` receipt field, and inherited environment
  values are never recorded.
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
chemical knowledge or literature. The plan always records `charge_method` as
`bcc` or `user`, and its hashed ACPYPE argv must match that choice. Omitted
`--charge-method` safely defaults to `bcc`, including for MOL2.

A hash-valid plan created by an older version may contain ACPYPE `-c user` for
an SDF/PDB without an explicit `charge_method`. `run` refuses that plan without
altering its approved command. Regenerate it with `--charge-method bcc`, then
review the new plan and hash. Use `user` only after reviewing a MOL2's stored
partial charges.

`finalize` only writes `validation.status: validated` when
`--charges-verified` is passed after the user inspects the per-atom charges;
otherwise it stays `pending_review` and the handoff rejects it.

## Boundaries

- No engine (acpype, sobtop, CGenFF) is ever downloaded automatically.
- `run` accepts no plan-supplied environment variables. Its narrow ACPYPE
  loader adjustment leaves `LD_LIBRARY_PATH` exactly as inherited, prepends
  only verified prefix-library paths to child-only `LD_PRELOAD`, retains the
  inherited preload value afterward, and records only paths it prepended. It
  never installs, modifies, or links package/system libraries and does not
  support arbitrary shared-library preloads.
- Plans are SHA256-hashed; `run` refuses a modified plan or an unsafe legacy
  SDF/PDB `user`-charge plan rather than rewriting an approved command.
- A local action ending `failed`, `blocked`, or `incomplete` still produces a
  receipt with attempts/stdout/stderr evidence, but `run` exits nonzero and
  does not report success. Manual sobtop/CGenFF handoffs remain successful
  `handoff_required` receipts.
- The `validated` status is bookkeeping evidence (files exist, hashes
  recorded, charges inspected), not a physical accuracy guarantee.
- Docking scores play no role in charge or parameter decisions.

## Common Mistakes

1. **Guessed net charge**: always derive it from protonation analysis, not
   from docking output or intuition.
2. **Using `user` on SDF/PDB**: ACPYPE requires a MOL2 containing reviewed
   partial charges for `-c user`; use the BCC default for SDF/PDB inputs.
3. **Mixing force-field families**: GAFF2 topologies belong with AMBER-family
   protein force fields; CHARMM36 protein systems need the CGenFF route.
