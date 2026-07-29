---
name: molecular-geometry-common
description: Shared PDB parsing and geometry primitives (Atom record, residue classification constants, distance/contact geometry) used by docking-complex-analysis and docking-visualization. Not a standalone workflow; imported by other skills' scripts.
---

# Molecular Geometry Common (`molecular-geometry-common`)

## Overview
This skill hosts `scripts/pdb_geometry.py`, the single source of truth for:
- The `Atom` frozen dataclass with ChimeraX/PyMOL selection properties.
- `STANDARD_AA`, `SOLVENT_IONS`, `POLAR_ELEMENTS` residue-classification constants.
- `read_pdb` / `read_conect` parsers and `is_hydrogen` / `distance` geometry helpers.

It exists to keep `docking-complex-analysis` and `docking-visualization` from
drifting into divergent copies of the same parsing logic.

## Usage
Consumer scripts add this skill's `scripts/` directory to `sys.path` relative
to their own `__file__` (valid both in the repository layout and inside the
bundled plugin):

```python
_SHARED = Path(__file__).resolve().parents[2] / "molecular-geometry-common" / "scripts"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))
from pdb_geometry import Atom, read_pdb, distance  # noqa: E402
```

## Rules
- Keep this module dependency-free (standard library only).
- Behavior changes here affect every consumer skill; run each consumer's
  tests after editing.
