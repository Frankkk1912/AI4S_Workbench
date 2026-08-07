# Environment Diagnostic and Bootstrap Upgrade

## Goal

Make `molecular-modeling-environment` distinguish a missing or broken local
scientific environment from an agent/container execution boundary.  Retain the
current file-based audit and approved-plan bootstrap model.

## Confirmed Workflow

1. Run the ordinary, read-only `audit` or `verify` in the active execution
   context.
2. If the WSL2 GPU or Docker probe fails and isolation evidence is present,
   write a structured diagnosis rather than reporting only a generic failed
   probe.
3. Offer one host-level, read-only recheck.  It is executed only after one
   explicit user command authorization.
4. Build a hashed, reviewable installation plan for missing components.
5. After explicit approval of that plan, execute every safe, non-privileged
   action automatically.  Leave Windows driver/WSL configuration, Docker
   Desktop, sudo-managed packages, reboots, BIOS changes, and ChimeraX download
   as explicit handoffs.

## Inputs and Outputs

Inputs are the existing profile and output directory, plus an optional
host-recheck authorization and a reviewed installation plan.  Outputs remain
JSON receipts and add machine-readable diagnostics, evidence, actions, and
handoffs.  No network API is used.

## Proposed CLI Changes

- `audit` and `verify`: collect command paths, WSL GPU bridge state
  (`/dev/dxg`), home writability, Docker socket ownership, effective groups,
  Conda executable candidates, and classified probe errors.
- `host-recheck`: read-only WSL host probe for GPU and Docker.  It requires an
  explicit command authorization from the agent execution layer and never
  changes state.
- `plan`: permit selected missing scientific components and record each
  proposed user-space or manual action with its privilege boundary.
- `bootstrap`: retain plan-hash validation and perform only approved
  non-privileged actions.  It emits a per-component receipt and actionable
  manual handoffs for anything requiring elevated/system access.

## Diagnostic Classes

| Class | Evidence | Result |
| --- | --- | --- |
| `available` | command succeeds | ready component |
| `not_installed_or_not_on_path` | no command or Conda candidate | plan an install/activation action |
| `execution_isolation` | WSL2 expected but `/dev/dxg` absent, home not writable, or Docker socket is namespace-mapped | request host recheck; do not diagnose host failure |
| `host_configuration_failure` | host recheck also fails | manual Windows/WSL/Docker handoff |
| `manual_only` | installation requires privileged or vendor-managed action | record instructions; never automate |

## Installation Boundaries

The bootstrapper may automate approved user-scoped Conda/micromamba or
downloaded binary installation actions, with smoke tests.  It must not use
`sudo`, change Windows settings, restart WSL, modify drivers, alter Docker
Desktop, or download ChimeraX.

## Validation

- Unit-test the diagnostic classifier with successful GPU, absent command,
  NVML failure, absent `/dev/dxg`, and Docker permission fixtures.
- Test host-recheck receipt construction without invoking a real host in unit
  tests.
- Test plan hashing and refusal of an altered plan.
- Run the plugin `sync`, `check`, and complete `test` suite to ensure the
  bundled skill matches the source skill.

