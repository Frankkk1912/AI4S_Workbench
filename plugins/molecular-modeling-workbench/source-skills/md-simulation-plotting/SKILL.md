---
name: md-simulation-plotting
description: Publication-grade Molecular Dynamics simulation plotting workflow. Generates Nature/Science tier plots for Basic QC, Free Energy Landscapes, DCCM Networks, and Geometric analyses. Works seamlessly with output from md-trajectory-analysis.
---

# MD Simulation Plotting (`md-simulation-plotting`)

## Overview

This skill generates publication-grade, multi-panel composite figures from Molecular Dynamics simulation data (`.xvg`, `.xpm`, `.csv`).

It perfectly complements the `md-trajectory-analysis` pipeline by automatically visualizing its output in two regimes: **Basic** (Automated Reporting) and **Advanced** (Hypothesis-Driven).

---

## The Plotting Workflow

### 1. Basic Plotting (Automated QC & Stability)

The `basic` command reads a directory containing the outputs of the `md-trajectory-analysis` basic pipeline and generates up to 3 standard reports in a single run:

- **QC 4-Panel (`*_qc_4panel.pdf`)**: RMSD, RMSF, Rg, SASA.
- **Hydrogen Bonds (`*_hbonds.pdf`)**.
- **Secondary Structure (`*_dssp.pdf`)**.

**Usage (Single System)**:

```bash
uv run /path/to/skills/md-simulation-plotting/scripts/md_plot_cli.py basic \
    --sys1-dir analysis_out/ \
    --sys1-label "Apo WT" \
    --output final_report
```

**Usage (Comparative 2-System)**:

```bash
uv run /path/to/skills/md-simulation-plotting/scripts/md_plot_cli.py basic \
    --sys1-dir wt_analysis_out/ \
    --sys2-dir mut_analysis_out/ \
    --sys1-label "WT" \
    --sys2-label "Mutant" \
    --output final_compare
```

*Note: This command supports ligand/nucleic acid custom labels via `--rmsd-ylabel`, `--rmsf-ylabel`, and `--rmsf-xlabel`.*

---

### 2. Formal Diagnostics Gallery

The `diagnostics` command consumes the session-scoped `energy.xvg`, `rmsd.xvg`,
and `rmsf.xvg` outputs and writes matching PNG, SVG, PDF, and TIFF figures.
Changing the style configuration redraws those figures without changing the
numeric XVG inputs.

```bash
uv run scripts/md_plot_cli.py --style-config style.json diagnostics \
    --analysis-dir analysis/session-id \
    --eq-start-ns 20 \
    --output analysis/session-id/figures/diagnostics
```

### 3. Advanced Plotting (Hypothesis-Driven)

These commands are used to plot the specific analyses requested by the user from the advanced trajectory pipeline.

#### A. Free Energy Landscape & PCA (`advanced-fel`)

Plots a 2D Free Energy Landscape mapping the conformational phase space.

```bash
uv run scripts/md_plot_cli.py advanced-fel \
    --sys1-pca analysis_out/pca_2dproj.xvg \
    --output fel_plot
```

#### B. Dynamic Network Analysis (`advanced-network`)

Plots 2x2 or 1x2 grids comparing Contact Probability Maps and Dynamic Cross-Correlation Matrices (DCCM).

```bash
uv run scripts/md_plot_cli.py advanced-network \
    --sys1-contact analysis_out/contact.csv \
    --sys1-dccm analysis_out/dccm.csv \
    --output network_plot
```

#### C. Targeted Geometry (`advanced-geometry`)

Plots 1D kernel density estimates (KDE) for distances or angles.

```bash
uv run scripts/md_plot_cli.py advanced-geometry \
    --sys1-dist custom_dist.xvg \
    --metric-name "Active Site Distance" \
    --unit "nm" \
    --output geometry_plot
```

#### D. Radial Distribution Function (`advanced-rdf`)

Plots $g(r)$ vs Distance.

```bash
uv run scripts/md_plot_cli.py advanced-rdf \
    --sys1-rdf rdf.xvg \
    --target-name "Water" \
    --output rdf_plot
```

---

## Universal Styling & Customization

The system outputs high-resolution PDFs and PNGs using a constrained, colorblind-friendly aesthetic (`StyleConfig`).

To change colors, font sizes, or figure dimensions without modifying Python,
pass the flat `StyleConfig` key names in a JSON file. `--style-config` is a
global option and therefore precedes the plotting subcommand.

```bash
uv run scripts/md_plot_cli.py --style-config custom_theme.json basic ...
```

```json
{
  "sys1_color": "#1F77B4",
  "sys2_color": "#FF7F0E",
  "font_family": "Arial",
  "font_size": 10,
  "title_size": 12,
  "fig_size_qc_4panel": [8.0, 6.0],
  "fig_size_diagnostics": [8.0, 9.0]
}
```

All omitted values keep the original defaults. Style files control rendering
only; they do not contain or modify scientific analysis parameters.
