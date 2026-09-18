---
name: md-trajectory-analysis
description: Automated Molecular Dynamics trajectory analysis pipeline bridging raw simulation data (xtc/tpr) to the plotting engine. Features a decoupled architecture with a fast "basic" automated reporting module (QC, DSSP) and an "advanced" on-demand hypothesis module (PCA, Network DCCM via MDAnalysis, and a manual MMPBSA handoff).
---

# MD Trajectory Analysis Pipeline (`md-trajectory-analysis`)

## Overview

This skill bridges the critical gap between `md-simulation-run` and
`md-simulation-plotting`.

It is designed with a **Decoupled Architecture**:

1.  **Basic Pipeline (Automated Reporting)**: Executes standard QC metrics automatically, requiring zero biological context. Fast and highly optimized.
2.  **Advanced Pipeline (Hypothesis-Driven)**: Executes computationally heavy or specific structural biology inquiries (PCA, Dynamic Cross-Correlation, Free Energy) strictly on-demand.

---

## Architectural Workflow & When to Use

### 1. The "Basic" Pipeline (Use immediately after Simulation)

**Trigger this module immediately after `md-simulation-run` successfully
produces the final `md_prod.xtc` and `md_prod.tpr`.**

This pipeline runs without pausing for interactive prompts by utilizing an automated index-generation script (`auto_index.py`).
**Outputs:**

- `rmsd.xvg` (Backbone)
- `rmsf.xvg` (C-alpha)
- `rg.xvg` (Protein)
- `sasa.xvg` (Protein)
- `dssp.xpm` (Secondary structure)
- `hbonds.xvg` (Inter-protein hydrogen bonds)

**Command:**

```bash
# Run inside the MD working directory (must contain .tpr and .xtc)
uv run /path/to/skills/md-trajectory-analysis/scripts/md_analyze_cli.py basic --tpr md_prod.tpr --xtc md_prod.xtc --outdir analysis_out
```

*Note: The resulting `analysis_out/` folder should immediately be passed to the `md-simulation-plotting` skill (Tier 1) to generate the baseline report.*

### 2. Formal Diagnostics (Completed Stage or Frozen Snapshot)

Use `diagnostics` for parameterized temperature, pressure, potential-energy,
RMSD, and RMSF results. Time-window values are in ps; atom and fit groups are
limited to the CLI's predefined allowlist. In the local workbench, submit this
through the analysis API so input hashes are checked against a completed
manifest or backend-created frozen snapshot. Do not run formal analysis against
an actively written trajectory.

```bash
uv run /path/to/skills/md-trajectory-analysis/scripts/md_analyze_cli.py diagnostics \
  --tpr md_prod.tpr --xtc md_prod.xtc --edr md_prod.edr \
  --group backbone --fit-group protein --begin 20000 --end 100000 \
  --eq-start 20 --outdir analysis/session-id
```

Each invocation writes `energy.xvg`, `rmsd.xvg`, `rmsf.xvg`, and
`diagnostics_summary.json` to the requested session directory.

### 3. The "Advanced" Pipeline (Use On-Demand)

Use these subcommands *only* when the user asks a specific biological question (e.g., "Why did the loop open?", "What are the key allosteric pathways?").

#### A. Free Energy Landscape (PCA & FEL)

Computes the covariance matrix and projects the first two principal components.

```bash
uv run /path/to/skills/md-trajectory-analysis/scripts/md_analyze_cli.py advanced-fel --tpr md_prod.tpr --xtc md_prod_pbc.xtc --outdir analysis_out
```

#### B. Dynamic Network Analysis (DCCM)

Leverages the Python `MDAnalysis` library to compute the Dynamic Cross-Correlation Matrix (DCCM) and Contact maps.

```bash
uv run /path/to/skills/md-trajectory-analysis/scripts/md_analyze_cli.py advanced-network --tpr md_prod.tpr --xtc md_prod_pbc.xtc --outdir analysis_out
```

#### C. MM/PBSA Binding Free Energy

Prepares a manual `gmx_MMPBSA` handoff because this calculation is extremely slow. It writes `mmpbsa.in` and prints the suggested MPI command; it does **not** run `gmx_MMPBSA`, produce a binding result, or write an execution receipt.

```bash
uv run /path/to/skills/md-trajectory-analysis/scripts/md_analyze_cli.py advanced-mmpbsa --tpr md_prod.tpr --xtc md_prod_pbc.xtc --top topol.top --outdir analysis_out
```

## Prerequisites

- GROMACS (`gmx`) installed and in PATH.
- `uv` installed.
- Dependencies: the configured workbench Python runtime for plotting-related
  downstream work; this trajectory CLI itself invokes GROMACS command-line
  tools and does not import MDAnalysis.
