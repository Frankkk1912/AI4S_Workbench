---
name: md-simulation-run
description: >-
  Molecular dynamics simulation guide and standard parameter sets for GROMACS on WSL2 using GPU acceleration (RTX 3080). Contains copy-pasteable standard mdp templates for 100 ns production runs and pdb2gmx multi-chain setup. This is Step 1 of the MD pipeline.
---

# MD Simulation Runner (`md-simulation-run`)

## Overview
This skill provides comprehensive instructions, constraints, and copy-pasteable configuration decks for conducting Molecular Dynamics (MD) simulations in a local **WSL2** environment utilizing **GPU acceleration (NVIDIA RTX 3080)**. 

## Auditable Run Contract

Before preparing MD, create and validate `md_handoff.json` with
`docking-to-md-handoff` for ligand-containing systems. Use the scriptable
manifest so a long run can be resumed without losing provenance:

```bash
uv run scripts/md_run_cli.py plan-duration --profile wsl2-gpu \
  --system-mass-kda 80 --atom-count 120000 --output md/duration_plan.json
uv run scripts/md_run_cli.py prepare --handoff md_handoff.json \
  --environment-receipt environment_receipt.json --duration-plan md/duration_plan.json \
  --work-dir md --output md/md_run_manifest.json
uv run scripts/md_run_cli.py plan-stage --stage em --deffnm em \
  --profile wsl2-gpu --threads 8 --output md/em_stage_plan.json
# The assembly contract already created md/em.tpr.
uv run scripts/md_run_cli.py run --manifest md/md_run_manifest.json \
  --stage-plan md/em_stage_plan.json --output md/md_run_manifest.json

# After EM completes, review a separate, hash-bound NVT preprocessing plan.
uv run scripts/md_run_cli.py plan-stage --stage nvt --deffnm nvt \
  --profile wsl2-gpu --threads 8 --output md/nvt_stage_plan.json
uv run scripts/md_run_cli.py plan-grompp --manifest md/md_run_manifest.json \
  --stage-plan md/nvt_stage_plan.json --mdp md/nvt.mdp --topology md/topol.top \
  --reference md/em.gro --maxwarn 0 --output md/nvt_grompp_plan.json
uv run scripts/md_run_cli.py grompp --plan md/nvt_grompp_plan.json \
  --manifest md/md_run_manifest.json --stage-plan md/nvt_stage_plan.json \
  --mdp md/nvt.mdp --topology md/topol.top --reference md/em.gro \
  --output md/nvt_grompp_receipt.json
uv run scripts/md_run_cli.py run --manifest md/md_run_manifest.json \
  --stage-plan md/nvt_stage_plan.json --output md/md_run_manifest.json
```

`plan-grompp` is the mandatory preprocessing contract for every TPR not already
created by audited system assembly. For `em`, pass `--coordinate` explicitly.
For `nvt`, `npt`, and `md_prod`, do not pass a coordinate: the planner requires
and hash-binds the completed predecessor GRO recorded in the manifest. Pass
`--reference` only when an NVT/NPT MDP explicitly uses position restraints;
other stages reject it. `--maxwarn` must be explicitly selected from 0–2, and a
nonzero value also requires `--warning-rationale`.

The grompp plan hash-binds the manifest, valid mdrun stage plan, MDP, topology,
source/predecessor coordinate, optional restraint reference, environment
receipt, receipt profile and image digest, output prefix, and exact allowlisted
`gmx grompp` argument vector. `grompp` revalidates every binding, mounts only the
manifest work directory, and executes through the receipt's absolute Docker
path with its immutable GPU image digest. It writes a separate grompp receipt,
command, return code, stdout/stderr log, and successful TPR hash. A nonzero
GROMACS return code still produces a failed receipt and causes a nonzero CLI
exit. It never substitutes host `gmx`. Review each plan before executing it;
neither preprocessing nor `mdrun` starts automatically.

`prepare` rejects a ligand handoff without validated parameterization and
topology evidence or a missing duration plan. It also recomputes protected
handoff file hashes and requires a fresh schema-`1.1`, profile-matched,
`ready: true` environment receipt. For GPU profiles that receipt must also
contain the verified immutable digest of
`nvcr.io/nvidia/gromacs:v2023.3`; `run` mounts the work directory into that
digest-pinned container and uses the receipt's absolute Docker path rather
than substituting a host `gmx` or Docker executable found through `PATH`.
`run` captures stage
plans and logs; a plan contains an allowlisted GROMACS argument array rather
than free shell text. Each stage verifies the completed, hash-matched prior
stage output before it starts. Successful production handoff
is `md_prod.tpr` plus `md_prod.xtc` for `md-trajectory-analysis`.

### Duration and throughput contract

- CPU profiles always warn that MD may take a long time and recommend `≤10 ns`.
  A longer CPU duration requires explicit recorded confirmation.
- GPU profiles ask the user to choose duration; the disclosed default is 100 ns.
- Molecular mass is not an ETA. Run a 5–10 minute benchmark on the prepared
  system to obtain observed `ns/day` before estimating production days.
- Use `status` to generate `md_progress.json` and a deterministic progress bar.
  When a scheduling facility is available, invoke it every 1–2 hours; otherwise
  give the user the saved status command. A `watch` process only updates files
  in a supervised terminal and cannot wake an inactive Agent conversation.

It targets **protein monomers** or **protein-protein complexes** under standard physiological conditions (310 K, 1 bar, 150 mM NaCl) using GROMACS inside an NVIDIA Docker container.

## Protein–Ligand System Preparation Admission

For the v0.1 AMBER/GAFF route, create a hash-bound plan before any system
assembly. It accepts only a validated protein–ligand handoff with an individual
selected-pose coordinate file, `amber99sb-ildn`-family protein force field,
GAFF ligand topology, TIP3P, a 1.2 nm dodecahedral box, and an explicit
terminal-state record. It never infers termini or protonation.

```bash
uv run scripts/protein_ligand_system.py plan \
  --handoff md_handoff.json --environment-receipt environment_receipt.json \
  --receptor-pdb receptor.pdb --termini-record termini.json \
  --water-model tip3p --box-shape dodecahedron --box-distance-nm 1.2 \
  --salt-molar 0.15 --output system_preparation_plan.json
```

Run `pdb2gmx` only after reviewing the terminal-state record, then record its
nonempty topology and coordinates instead of claiming the tool selected them:

```bash
uv run scripts/protein_ligand_system.py prepare-protein \
  --plan system_preparation_plan.json --protein-topology topol.top \
  --protein-coordinates protein.gro --output protein_preparation.json
```

After protein preparation is reviewed, use the assembly contract rather than
copying shell fragments. It validates every protected input, writes an
allowlisted command plan, and executes the plan only against the receipt-bound
Docker path and digest-pinned GROMACS image:

```bash
uv run scripts/protein_ligand_assembly.py plan \
  --system-plan system_preparation_plan.json \
  --protein-preparation protein_preparation.json \
  --alignment-report ligand_pose_alignment.json \
  --ligand-topology BNZ_GMX.itp --ions-mdp ions.mdp --em-mdp em.mdp \
  --work-dir composed --profile wsl2-gpu \
  --preion-maxwarn 0 --output system_assembly_plan.json

uv run scripts/protein_ligand_assembly.py assemble \
  --plan system_assembly_plan.json \
  --system-plan system_preparation_plan.json \
  --protein-preparation protein_preparation.json \
  --alignment-report ligand_pose_alignment.json \
  --ligand-topology BNZ_GMX.itp --ions-mdp ions.mdp --em-mdp em.mdp \
  --output system_assembly_receipt.json
```

`assemble` performs topology composition, dodecahedral boxing, solvation,
pre-ionization preprocessing, ionization, and final EM preprocessing. It stops
on a changed hash or a nonzero GROMACS exit. A nonzero `--preion-maxwarn`
requires an explicit reviewed rationale; it is never inserted silently. Do not
use the generic stage runner as a substitute for a prepared system.

---

## Force Field Setup & PDB Preparation

### 1. Force Field Recommendation
*   **Primary Recommendation**: **CHARMM36** (specifically `charmm36-jul2022.ff` or newer). Best suited for complex glycoproteins, membrane systems, and general protein complexes.
*   **Fallback (Built-in)**: **AMBER99SB-ILDN** or **AMBER ff14SB**. Best for clean, standard soluble proteins without custom post-translational modifications (PTMs).
*   **Linking Local Forcefield**: If using a custom folder, always symlink it to your GROMACS working directory so it is visible:
    ```bash
    # Link forcefield directory
    ln -s /path/to/shared/charmm36-jul2022.ff ./charmm36-jul2022.ff
    ```

### 1b. CRITICAL: Ligand Topology Verification
*   **Missing Hydrogens Bug**: PDBs generated from docking software or online databases often strip non-polar (or even polar) hydrogens from ligands. If you run `acpype` or `sobtop` on a ligand missing hydrogens, the generated `.itp` topology will be completely invalid (missing critical steric clash parameters and dihedrals). This will cause the ligand to **collapse and crumple** into a tiny ball during the NVT/NPT/Production simulation.
*   **Fix**: **ALWAYS** verify that the ligand has a chemically correct number of hydrogens added before generating `.itp` forcefield files. (e.g., use `obabel`, `ChimeraX addh`, or `Avogadro`). You MUST manually inspect the `[ atoms ]` block of the generated `.itp` to ensure hydrogens are present.

### 2. PDB Structure Cleaning
*   **Signal Peptide Slicing**: When applicable, mature proteins must be stripped of signal peptides so that residue indices map to their biological mature states.
*   **Explicit Terminal Selection (`-ter`)**: When running GROMACS `pdb2gmx` on multi-chain complexes, **always** specify `-ter` to explicitly configure the protonation state of each chain.
    - **Why**: Prevents GROMACS's known `MET1` N-terminal patch bug (`atom C1 not found in building block 1MET`).
    - **Command Pattern**:
      ```bash
      # Provide selections to interactive prompts (e.g., NH3+ and COO-)
      echo -e "0\n0\n1\n0" | gmx pdb2gmx -f complex_mature.pdb -o complex.gro -water tip3p -ff charmm36-jul2022 -ignh -ter
      ```

---

## Standard GROMACS Parameters (.mdp files)

These are the reference configurations to write into the `params/` directory prior to running simulations.

### 1. Energy Minimization (`em.mdp`)
```mdp
; Energy minimization parameter file
integrator  = steep
emtol       = 1000.0
emstep      = 0.01
nsteps      = 50000
nstlist     = 1
cutoff-scheme = Verlet
ns_type     = grid
coulombtype = PME
rcoulomb    = 1.2
rvdw        = 1.2
pbc         = xyz
```

### 2. NVT Equilibration (`nvt.mdp` - 100 ps)
```mdp
; NVT equilibration at 310 K
define      = -DPOSRES ; Position restraints for heavy atoms
integrator  = md
nsteps      = 50000    ; 100 ps
dt          = 0.002
nstxout     = 5000     ; save coords every 10 ps
nstlog      = 5000
nstenergy   = 5000
continuation = no
constraint_algorithm = lincs
constraints = h-bonds
lincs_iter  = 1
lincs_order = 4
nstlist     = 20
cutoff-scheme = Verlet
ns_type     = grid
coulombtype = PME
rcoulomb    = 1.2
rvdw        = 1.2
pbc         = xyz
tcoupl      = V-rescale
tc-grps     = Protein Non-Protein
tau_t       = 0.1   0.1
ref_t       = 310   310
gen_vel     = yes
gen_temp    = 310
gen_seed    = -1
```

### 3. NPT Equilibration (`npt.mdp` - 100 ps)
```mdp
; NPT equilibration at 310 K, 1 bar
define      = -DPOSRES ; Position restraints
integrator  = md
nsteps      = 50000    ; 100 ps
dt          = 0.002
nstxout     = 5000
nstlog      = 5000
nstenergy   = 5000
continuation = yes
constraint_algorithm = lincs
constraints = h-bonds
lincs_iter  = 1
lincs_order = 4
nstlist     = 20
cutoff-scheme = Verlet
ns_type     = grid
coulombtype = PME
rcoulomb    = 1.2
rvdw        = 1.2
pbc         = xyz
tcoupl      = V-rescale
tc-grps     = Protein Non-Protein
tau_t       = 0.1   0.1
ref_t       = 310   310
pcoupl      = C-rescale
pcoupltype  = isotropic
tau_p       = 2.0
ref_p       = 1.0
compressibility = 4.5e-5
refcoord_scaling = com
```

### 4. Production MD (`md_prod_100ns.mdp` - Default 100 ns)
```mdp
; Production MD — 100 ns at 310 K, 1 bar
integrator  = md
nsteps      = 50000000 ; 100 ns (50,000,000 steps * 0.002 ps)
dt          = 0.002

nstxout-compressed = 25000  ; save every 50 ps (2000 frames total for 100 ns)
nstlog      = 25000
nstenergy   = 25000

continuation    = yes
constraint_algorithm = lincs
constraints     = h-bonds
lincs_iter      = 1
lincs_order     = 4

nstlist     = 20
cutoff-scheme = Verlet
ns_type     = grid
coulombtype = PME
rcoulomb    = 1.2
rvdw        = 1.2
pbc         = xyz
DispCorr    = EnerPres

tcoupl      = V-rescale
tc-grps     = Protein Non-Protein
tau_t       = 0.1   0.1
ref_t       = 310   310

pcoupl          = C-rescale
pcoupltype      = isotropic
tau_p           = 2.0
ref_p           = 1.0
compressibility = 4.5e-5
```

---

## Execution Strategy & Progress Tracking

Because Molecular Dynamics simulations (especially `npt` and `md_prod`) are long-running tasks, the agent MUST follow these tracking and feedback protocols to avoid silent waiting and to keep the user informed.

### 1. Sequential Execution and Reactive Wakeup
Do NOT combine all four MD steps (EM, NVT, NPT, Prod) into a single monolithic background command. If you do, it will be impossible to track intermediate failures. 
*   Launch each step individually using the `run_command` tool.
*   Once launched, allow the command to run in the background. The system will automatically wake you up when the step completes. You do NOT need to poll the `status` continuously.
*   Check the completion status. Only proceed to the next step if the previous one succeeded.

### 2. User Progress Reporting (The Progress Bar)
After launching production MD, parse the GROMACS log rather than assuming it is
still healthy:

```bash
uv run scripts/md_run_cli.py status --manifest md_run_manifest.json \
  --log md_prod.log --total-steps 50000000 --output md_progress.json
```

The resulting `md_progress.json` and `md_progress.md` include a bar such as
`[██████░░░░] 60% | Step: 30,000,000 / 50,000,000 | 4.8 ns/day | ETA: ~8 h`.
Set a 1–2 hour Agent timer only if the current surface supports it; otherwise
tell the user how to rerun the status command. A stale log or missing step is a
warning, not evidence that simulation is progressing.

---

## Command Execution Pipeline (WSL2 + NVIDIA Docker)

### 1. Defining the Box, Solvating, and Adding Ions
```bash
# Define box (dodecahedron, 1.2 nm buffer distance)
gmx editconf -f complex.gro -o complex_box.gro -c -d 1.2 -bt dodecahedron

# Solvate with TIP3P water
gmx solvate -cp complex_box.gro -cs spc216.gro -o complex_solv.gro -p topol.top

# Generate TPR for adding ions
gmx grompp -f params/em.mdp -c complex_solv.gro -p topol.top -o ions.tpr -maxwarn 2

# Add ions (150 mM NaCl, neutralise system)
echo "SOL" | gmx genion -s ions.tpr -o complex_ions.gro -p topol.top \
    -pname NA -nname CL -neutral -conc 0.15
```

### 2. Running Simulations with GPU Acceleration
Use only the audited `plan-grompp` → `grompp` → `run` sequence shown in the
Auditable Run Contract. Do not join preprocessing and simulation into shell
text and do not invoke a mutable image tag directly. The environment receipt
must identify the absolute Docker executable and immutable digest for
`nvcr.io/nvidia/gromacs:v2023.3`; the CLI reconstructs the argument-vector
command without a shell.

Repeat the reviewed sequence independently for NVT, NPT, and production. The
successor grompp plan takes its coordinate from the prior completed manifest
stage, while the subsequent `run` retains the existing mdrun stage-plan and
artifact behavior. Production completion still requires the planned `.tpr`,
`.gro`, `.log`, `.edr`, and `.xtc`. Adjust `--threads` in each mdrun stage plan
to the reviewed physical-core allocation; the structured plan keeps one MPI
rank and selects GPU nonbonded work for GPU profiles.

---

## Next Step: Handoff to Analysis Engine (CRITICAL)

**STOP HERE.** The `md-simulation-run` skill concludes the moment `md_prod.xtc` and `md_prod.tpr` are successfully generated. 

You must **NEVER** run manual `gmx rms` or `gmx trjconv` commands or attempt to fix Periodic Boundary Conditions (PBC) manually. The downstream pipeline handles all of this automatically.

### Pipeline Handoff
1. **Pass the Baton**: Immediately invoke the **`md-trajectory-analysis`** skill.
2. Provide it with the raw trajectory files:
   - `--tpr md_prod.tpr`
   - `--xtc md_prod.xtc`
3. The `md-trajectory-analysis` skill will automatically execute PBC corrections and extract all standard QC metrics for plotting.
