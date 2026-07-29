# Molecular Modeling Workbench

An auditable, file-based workbench for docking, complex analysis,
visualization, ligand parameterization, docking-to-MD handoff, GROMACS stage
orchestration, trajectory analysis, and plots.

`environment audit → docking brief → GNINA/Vina → complex analysis →
ChimeraX/PyMOL scene → validated MD handoff → GROMACS → analysis → plots`

## Support contract

v0.1.0 is a **WSL2-first public beta**. Its release target is Ubuntu 22.04
inside WSL2 on an NVIDIA GPU (first acceptance hardware: RTX 3080), with the
agent, project files, and scientific tools all running under the Linux home
directory. Native Windows execution, HPC schedulers, multi-GPU runs, and
automatic proprietary-tool installation are out of scope. CPU-only runs are
useful for small demonstrations and contract tests, not release-equivalent MD.

Run the environment audit before an expensive calculation; downstream docking,
parameterization, handoff, and MD commands reject a stale, mismatched, or
not-ready receipt.

## Scientific boundaries

Docking scores are not experimental affinities or binding free energies.
Geometry-derived hydrogen-bond and contact results are candidate interactions,
not a complete energetic judgment. Review receptor/ligand preparation,
protonation, force-field family, charge, selected pose, and production length
before proceeding. PLIP integration is deferred beyond v0.1.

## Install and onboard

Clone the public repository inside the Linux home directory of the supported
WSL2 distribution. Do not run trajectories from a Windows-mounted path such as
`/mnt/c`.

```bash
git clone https://github.com/Frankkk1912/AI4S_Workbench.git
cd AI4S_Workbench/plugins/molecular-modeling-workbench
npm run check
npm test
```

Add the plugin through the agent's marketplace flow, then restart or reload
the agent. The Claude marketplace file is at the repository root; Codex users
can add the same repository as a marketplace and select
`molecular-modeling-workbench`.

Before installing or running scientific tools, create an onboarding checklist
and review its handoffs. The commands below are read-only; `verify` writes the
receipt that later stages require.

```bash
uv run skills/molecular-modeling-environment/scripts/molecular_modeling_environment.py onboard \
  --profile wsl2-gpu --output-dir environment
uv run skills/molecular-modeling-environment/scripts/molecular_modeling_environment.py verify \
  --profile wsl2-gpu --output-dir environment
```

If the receipt is not ready, inspect `environment/onboarding_checklist.md` and
use the generated, reviewable install plan. The workbench never enables WSL,
modifies Docker Desktop, installs GPU drivers, accepts proprietary licenses, or
uses administrator privileges automatically.

GPU MD uses the verified GROMACS container. Trajectory analysis uses the
version-pinned `gmx-mmpbsa` environment (GROMACS 2023.4 plus gmx_MMPBSA 1.6.5)
and its paired native `gmx`; request that component in the reviewed environment
plan. It installs in the project environment directory and never modifies a
shared Conda base.

## Outputs and troubleshooting

Each stage writes JSON artifacts with input hashes, command plans, tool
versions, and output references. Preserve the environment receipt, docking
manifest, ranked poses, ligand-parameterization record, MD handoff, MD run
manifest, and analysis outputs together in the project directory.

- A stale, profile-mismatched, or `ready: false` receipt stops the run; repeat
  the audit/verify process after fixing the reported capability.
- A changed pose or parameter file invalidates the handoff intentionally;
  regenerate and revalidate the handoff instead of editing its hashes.
- A missing prior-stage artifact stops MD rather than allowing an implicit
  restart. Generate a controlled resume stage plan after reviewing the failure.
- GPU or Docker checks may be isolated from a healthy WSL host. Use the
  read-only host recheck recommended by the environment report before changing
  system configuration.

The plugin does not transmit structures or trajectories. Do not put
unpublished inputs, credentials, or identifying research data into issues,
logs, screenshots, or public acceptance artifacts.

## Upgrade and removal

Pull a new release, rerun `npm run sync`, `npm run check`, and `npm test`, then
reload the agent plugin. Keep old project receipts and manifests with their
projects; do not reuse them across materially changed environments. Remove the
plugin through the agent's normal plugin manager, then delete its cloned
repository only after preserving the scientific project outputs you need.

`environment audit → docking brief → GNINA/Vina → complex analysis →
ChimeraX/PyMOL scene → validated MD handoff → GROMACS → analysis → plots`

Docking scores, GNINA CNN outputs, confidence fields, and post-MD free-energy
estimates remain separate quantities throughout schemas and reports.

The visualization route is also independently usable: provide a PDB complex,
an approximate style request, and optionally a reference image. The Agent saves
the normalized intent and produces editable ChimeraX-first/PyMOL-fallback
scripts without requiring a preceding docking or MD job.

## Development and public export

```bash
npm run sync
npm run check
npm test
```

In private development, `skills/` and `bundle-manifest.json` are generated from
the source skill directories and committed for plugin installation; do not
hand-edit the bundled copies. A public export is self-contained and stores the
same editable sources in `source-skills/`.
`.codex-plugin/plugin.json`, `.claude-plugin/plugin.json`, and the
repository-root `.claude-plugin/marketplace.json` are generated from
`plugin-meta.json` by `npm run sync`; edit only `plugin-meta.json`.

## Runtime contract

`pyproject.toml` and `uv.lock` pin the plotting runtime. External scientific
tools remain explicit environment dependencies: their resolved absolute paths
and versions must appear in a verified environment receipt. The release
contract, including the GROMACS GPU container-reference policy, is in
`runtime-contract.json`.
