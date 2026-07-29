---
name: docking-complex-analysis
description: >-
  Analyze existing molecular docking complexes before visualization. Supports a
  first protein-ligand geometry workflow that identifies ligand binding-site
  residues, atom contacts, conservative polar/H-bond candidates, clashes, and
  standardized JSON/CSV outputs for docking-visualization.
---

# Docking Complex Analysis

This skill analyzes already-built docking complexes. It does not run docking.
It supports two main workflows:
1. **PLI (Protein-Ligand Interaction)**: Identifies ligand binding-site residues, polar/H-bond candidates, and hydrophobic contacts.
2. **PPI (Protein-Protein Interaction)**: Scans interfaces between two large protein chains (e.g. Chain A vs Chain B) to extract interface hotspots, H-bonds, and topological connections.

The output is a stable analysis bundle for downstream visualization and reports.
Do not rely on ad hoc viewer selections when a formal analysis result is needed.

## Dependencies
- `docking-visualization`: consumes this skill's `complex_analysis.json`.
- `workflow_skill_creator`: use as the meta-process for substantial skill
  changes.

## Quick Start
Analyze an existing protein-ligand complex:

*Note: Both `--ligand-resname` and `--protein-chain` are optional. Omitting `--protein-chain` is highly recommended for multi-chain complexes to auto-detect contacts across all protein chains. When `--ligand-resname` is omitted, auto-detection only considers residues with at least `--min-ligand-atoms` heavy atoms (default: 6) so that solvent additives and buffer fragments are not mistaken for the ligand; rejected candidates are listed in the JSON output and report warnings.*

### PLI (deterministic geometry workflow)
Use the bundled script for the public v0.1 workflow:

```bash
uv run scripts/analyze_docking_complex.py pli \
  --structure complex.pdb \
  --ligand-resname UNL \
  --output-dir docking_analysis
```

PLIP is intentionally not part of v0.1: it will be reconsidered for a later
release only with a locked dependency, a maintained script, and fixtures.

Analyze a protein-protein complex (PPI):

```bash
uv run scripts/analyze_docking_complex.py ppi \
  --structure complex.pdb \
  --chain-a A \
  --chain-b B \
  --output-dir docking_analysis
```

Generated files:
- `complex_analysis.json`: canonical machine-readable result containing the
  selected atoms and interaction candidates.
- `atom_contacts.csv`: ligand-protein heavy-atom contacts.
- `residue_contacts.csv`: residue-level contact summary.
- `interaction_summary.csv`: residue-level candidate interaction classes.
- `analysis_report.md`: concise human-readable report.

## PLI v1 Scope
The v1 geometry workflow intentionally mirrors the practical behavior of common
PyMOL ligand-interaction scripts:
- Binding site: receptor residues within 5.0 A of ligand heavy atoms.
- Polar/H-bond candidates: ligand and receptor N/O/S/F/Cl/Br/I heavy atoms
  within 4.0 A.
- Aromatic-contact candidates: ligand carbon atoms near aromatic receptor
  residues within 4.0 A.
- Hydrophobic contacts: ligand/receptor carbon contacts involving hydrophobic
  residues within 4.5 A.
- Clashes: heavy-atom contacts below 2.0 A.

These are geometry candidates, not definitive energetic conclusions. If the
structure lacks hydrogens, the script still reports polar candidates but records
a warning that strict H-bond assignment was not performed.

## Scientific Wording
- Use `docking_score` for Vina-style scores; do not call them experimental
  binding energies.
- Use `hydrogen_bond_candidates` unless angle and donor/acceptor chemistry have
  been validated.
- Use `binding_site_residues` for ligand-proximal residues, not `hotspots`.
