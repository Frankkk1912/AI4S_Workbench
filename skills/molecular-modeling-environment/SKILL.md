---
name: molecular-modeling-environment
description: >-
  Audit, plan, bootstrap, and verify reproducible molecular-modeling
  environments across WSL2 GPU, Linux GPU, Linux SSH, and CPU fallback profiles.
---

# Molecular Modeling Environment

## Overview

Create file-based evidence of the available molecular-modeling environment
before docking or MD. The utility never changes a valid installation during
`audit` or `verify`; administrator-controlled actions remain explicit handoffs.

## Dependencies

- `docking-simulation-run`: consumes a verified environment receipt.
- `md-simulation-run`: consumes a verified environment receipt.

## Quick Start

```bash
uv run scripts/molecular_modeling_environment.py audit \
  --profile wsl2-gpu --output-dir environment
uv run scripts/molecular_modeling_environment.py onboard \
  --profile wsl2-gpu --output-dir environment
uv run scripts/molecular_modeling_environment.py plan \
  --profile wsl2-gpu --components vina,gromacs,gmx-mmpbsa,acpype --output-dir environment
uv run scripts/molecular_modeling_environment.py bootstrap \
  --plan environment/install_plan.json --output-dir environment
uv run scripts/molecular_modeling_environment.py verify \
  --profile wsl2-gpu --output-dir environment
uv run scripts/molecular_modeling_environment.py host-recheck \
  --profile wsl2-gpu --output-dir environment
```

## Utility Scripts

`molecular_modeling_environment.py` writes JSON artifacts and short status
messages only. Profiles are `wsl2-gpu`, `linux-gpu`, `linux-ssh`, and
`cpu-fallback`.

- `audit --profile PROFILE --output-dir DIR`: inventory host, GPU, containers,
  command paths, WSL GPU bridge visibility, Docker socket context, and relevant
  executables without changing state.  It detects `conda`/`mamba`/`micromamba`
  executables and the currently activated Conda environment, and it classifies
  unavailable GPU/Docker probes as host failure, missing tool, permission
  failure, or execution isolation.
- `plan --profile PROFILE --components CSV --output-dir DIR`: make a scoped,
  reviewable user-space installation plan. On GPU profiles `gromacs` resolves
  to the pinned `nvcr.io/nvidia/gromacs:v2023.3` Docker image; on
  `cpu-fallback` it resolves to its own conda-forge prefix. On every profile,
  `gmx-mmpbsa` installs the version-pinned native analysis environment
  (GROMACS 2023.4 and gmx_MMPBSA 1.6.5); its paired `gmx` is the only GROMACS
  executable accepted for trajectory analysis. It resolves from conda-forge,
  as do Vina, Open Babel, DSSP, PyMOL, and the dedicated `acpype` + AmberTools
  ligand-parameterization prefix.
- `bootstrap --plan PLAN.json --output-dir DIR`: execute only permitted
  user-space actions from a hash-checked plan. It uses `micromamba`, then
  compatible `mamba` or `conda`, for package prefixes and performs the reviewed
  Docker image pull for GROMACS. ChimeraX is never downloaded. Legacy DSSP
  plans that request `mkdssp` as the package must be regenerated and reviewed;
  bootstrap rejects them rather than changing an approved action.
- `verify --profile PROFILE --output-dir DIR`: write a readiness receipt. GPU
  profiles require a verified immutable digest for the pinned GROMACS image.
- `onboard --profile PROFILE --output-dir DIR`: write a beginner-facing,
  step-ordered `onboarding_checklist.json` and `.md` from a read-only audit.
  Each step is marked satisfied, run-it-yourself (with the exact command), or
  manual handoff. It never installs or changes anything; use it as the first
  command for students new to the command line.
- `host-recheck --profile PROFILE --output-dir DIR`: repeat the WSL GPU and
  Docker inventory in a host-authorized execution context.  An agent must
  request one explicit command authorization before this read-only command.
- `remote --host SSH_TARGET --profile linux-ssh --output-dir DIR`: make a
  read-only SSH inventory; it never uses sudo or submits jobs.

## Environment Strategy

`plan`/`bootstrap` install each scientific component into its own
user-scoped micromamba prefix (`environments/<component>`), never into a
shared or activated Conda environment.  This is a deliberate trade-off:

- **Per-component prefix (chosen).** Components such as `gmx_MMPBSA` pin
  specific Python/GROMACS versions that can conflict with
  `pymol-open-source` or `openbabel`.  Separate prefixes keep each
  component's receipt reproducible, let one component be deleted or
  reinstalled without breaking the others, and avoid compromise versions
  chosen by a shared solver.  The cost is extra disk (each prefix carries
  its own base Python) and per-prefix binaries instead of one activation.
- **Unified conda env (rejected as the default).** A single environment
  saves disk and gives one activation point, but merges dependency
  constraints across unrelated tools, blurs per-component provenance in
  the audit trail, and makes one failed solver transaction block the whole
  workbench.

`audit` still detects `conda`, `mamba`, and `micromamba` executables plus
the currently activated environment (`CONDA_PREFIX`, `CONDA_DEFAULT_ENV`,
`CONDA_EXE`, `MAMBA_ROOT_PREFIX`) so that tools already on `PATH` from an
existing Conda installation are found.  Detection is read-only: bootstrap
never activates, installs into, or mutates a shared Conda environment.

After bootstrap, audit/verify also inspect the matching output directory's
`environments/<component>/bin` paths. The receipt records that absolute path,
and docking consumes that exact recorded executable rather than doing a later
`PATH` lookup. Always use the same `--output-dir` for plan, bootstrap, and
verify.

GPU MD uses the pinned NVIDIA GROMACS container rather than a native CUDA and
GROMACS installation. A completed `docker pull` is not sufficient evidence:
run `verify` afterwards so the receipt captures the resolved `@sha256:` digest
that MD execution will use. CPU fallback instead requires the managed native
`gmx` prefix and its receipt-bound absolute executable path.

Trajectory analysis is a separate MMPBSA-native capability in v0.1: `audit`
and `verify` record its paired `gmx` as `trajectory_analysis.gromacs`. On a
GPU profile, request `gmx-mmpbsa` when the bundled trajectory CLI is needed;
it installs `environments/gmx-mmpbsa/bin/gmx` together with
`gmx_MMPBSA`, without changing the shared Conda base or the GPU MD container
policy. Do not substitute the GPU MD container or an unrelated `gmx` binary.

## Safety Boundaries

- Native Windows scientific execution is unsupported; use WSL2.
- WSL enablement, reboots, BIOS changes, Docker Desktop, GPU drivers, sudo,
  and cluster modules are reported as user actions, never automated.
- Open-Source PyMOL is installed only into the plan's user-scoped micromamba
  prefix. ChimeraX is detected only and its official-download handoff is saved.
- A missing GPU is a failed GPU verification, not permission to silently change
  scientific execution parameters.
- An active agent/container context without `/dev/dxg` or a writable home may
  be isolated from a healthy WSL2 host.  Request the authorized `host-recheck`
  before telling a user their GPU configuration is broken.

## Common Mistakes

- Treating a docking score or CNN score as experimental affinity.
- Running `bootstrap` without first reviewing the generated install plan.
- Assuming a remote SSH login permits sudo or Slurm submission.
