---
name: docking-visualization
description: >-
  Create auditable, ChimeraX-first or PyMOL-fallback visualizations directly
  from PDB complexes or standardized docking-complex analysis outputs.
---

# Docking Visualization

## Overview

Use this skill independently of docking and MD to turn a PDB complex plus an
approximate visual request into a backend-neutral scene, editable renderer
scripts, and a disclosure report. The Agent translates fuzzy terms and optional
reference images into `visualization_request.json`; the local CLI performs only
explicit geometry inference and rendering.

## Dependencies

- `docking-complex-analysis`: preferred formal protein–ligand geometry route;
  direct PDB inference uses conservative equivalent distance criteria when no
  analysis file exists.
- `molecular-modeling-environment`: detects a verified renderer.
- `nature-figure`: apply its visual conventions only when the rendered image is
  part of a manuscript figure; it does not replace 3D rendering.

## Quick Start

Create a request template, then let the Agent fill its intent fields from the
user's words and optional reference image:

```bash
uv run scripts/generate_visualization_scene.py template \
  --kind protein-ligand --output visualization_request.json
uv run scripts/generate_visualization_scene.py infer \
  --structure complex.pdb --request visualization_request.json --output-dir viz
uv run scripts/generate_visualization_scene.py generate \
  --structure complex.pdb --request visualization_request.json --output-dir viz
```

The default renderer route is ChimeraX, then PyMOL. `generate` always writes
`visualization_scene.json`, `render_chimerax.cxc`, `render_pymol.pml`, and
`visualization_report.md`; `render` is optional.

## Utility Scripts

- `generate_visualization_scene.py`: primary route described above; turns a
  PDB plus `visualization_request.json` into a backend-neutral scene with
  ChimeraX/PyMOL adapters and a disclosure report.
- `generate_docking_viz.py`: analysis-driven report views (global, pocket, and
  a 2D SVG interaction diagram) from `complex_analysis.json`, plus offscreen
  ChimeraX rendering of generated scripts.
- `generate_ppi_viz.py`: explicit-config protein–protein route (merged from
  the retired `docking-visualization-assistant` skill). Use
  `template --output ppi_viz_config.json`, edit domains/interface
  groups/distances/labels, then `script --config … --output-dir …` and
  optionally `render --script … --chimerax /usr/bin/chimerax`. Selections
  stay fully explicit; nothing infers interfaces automatically.
- `generate_viz_legacy.py`: legacy auto-detect protein–ligand ChimeraX helper
  kept only for compatibility with old notes; prefer
  `generate_visualization_scene.py` for new work.

## Default Templates

- `pocket-glass`: transparent local surface (“glass/bubble”), internal cartoon,
  ligand/pocket sticks, and conservative H-bond-candidate lines.
- `pocket-global`: whole-protein context and ligand location.
- `ppi-interface`: domain/interface emphasis with local transparent surfaces.
- `protein-context`: a safe basic protein-only view.

## Intent and Reference Images

The Agent may map terms such as “glass”, “soft lighting”, “clean paper figure”,
or a supplied example image to background, palette family, transparency,
framing, and label density. It records that mapping, assumptions, and
uncertainty in the request artifact. A reference image is never used to infer
residue identities, interactions, or biological conclusions. See
`references/intent-contract.md`.

## Boundaries

- Automatic direct inference currently accepts PDB. For mmCIF, convert to PDB
  or provide a formal analysis/configuration route.
- H-bond lines are distance-based geometry candidates, not validated H-bonds.
- If no ligand or interface can be defensibly inferred, the tool writes a
  `protein-context` fallback with warnings rather than inventing a focus.
- The utility never downloads ChimeraX or PyMOL.
