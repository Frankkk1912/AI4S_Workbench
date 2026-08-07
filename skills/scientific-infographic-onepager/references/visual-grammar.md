# Visual Grammar

## Provenance
- `schematic-only`: visual explains logic, not measured data.
- `data-backed`: visual comes from real data or upstream analysis.
- Every visual supporting a claim must carry provenance in the spec.

## Schematic Rules
- Use labels that explain relationships, not fake numeric precision.
- Avoid invented p-values, fold changes, docking scores, RMSD values, or confidence percentages.
- Keep arrows meaningful: direction, activation, inhibition, input/output, or transformation.

## Scientific Image Priority
- Molecular structure, microscopy, blot, screenshot, and plot panels need enough space to inspect.
- Use `object-fit:contain` for dense screenshots, blots, code, charts, and microscopy plates.
- Use `object-fit:cover` only when cropping is scientifically irrelevant.
