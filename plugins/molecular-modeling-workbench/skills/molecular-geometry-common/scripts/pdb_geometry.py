#!/usr/bin/env python3
"""Shared PDB parsing and geometry primitives for molecular-modeling skills.

Single source of truth for the Atom record, residue-classification constants,
and distance/contact geometry used by docking-complex-analysis and
docking-visualization. Import via a sys.path bootstrap relative to __file__
(works both in the repository layout and inside the bundled plugin).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

STANDARD_AA = {
    "ALA",
    "ARG",
    "ASN",
    "ASP",
    "CYS",
    "GLN",
    "GLU",
    "GLY",
    "HIS",
    "ILE",
    "LEU",
    "LYS",
    "MET",
    "PHE",
    "PRO",
    "SER",
    "THR",
    "TRP",
    "TYR",
    "VAL",
}
SOLVENT_IONS = {
    "HOH",
    "WAT",
    "DOD",
    "NA",
    "CL",
    "K",
    "MG",
    "CA",
    "ZN",
    "MN",
    "FE",
    "CU",
    "CO",
    "NI",
    "CD",
    "SO4",
    "PO4",
    "GOL",
    "EDO",
    "PEG",
}
POLAR_ELEMENTS = {"N", "O", "S", "F", "CL", "BR", "I"}


class PdbGeometryError(ValueError):
    """Raised when PDB input cannot be parsed into usable atoms."""


@dataclass(frozen=True)
class Atom:
    serial: int
    record: str
    name: str
    resname: str
    chain: str
    resseq: str
    icode: str
    x: float
    y: float
    z: float
    element: str
    model: int = 1

    @property
    def residue_key(self) -> tuple[str, str, str, str]:
        return (self.chain, self.resseq, self.icode, self.resname)

    @property
    def residue(self) -> tuple[str, str, str]:
        return (self.chain, self.resseq, self.resname)

    @property
    def resid(self) -> str:
        return self.resseq

    @property
    def chimerax_residue_selection(self) -> str:
        chain = f"/{self.chain}" if self.chain else ""
        return f"{chain}:{self.resseq}{self.icode or ''}"

    @property
    def chimerax_atom_selection(self) -> str:
        return f"{self.chimerax_residue_selection}@{self.name}"

    @property
    def chimerax_serial_selection(self) -> str:
        return f"@@serial_number={self.serial}"

    @property
    def chimerax(self) -> str:
        return self.chimerax_atom_selection

    @property
    def pymol(self) -> str:
        chain = f"chain {self.chain} and " if self.chain else ""
        return f"({chain}resi {self.resseq} and name {self.name})"


def _element_from_line(line: str, atom_name: str) -> str:
    element = line[76:78].strip().upper() if len(line) >= 78 else ""
    if element:
        return element
    letters = "".join(ch for ch in atom_name if ch.isalpha()).upper()
    if len(letters) >= 2 and letters[:2] in {"CL", "BR"}:
        return letters[:2]
    return letters[:1]


def _parse_atom_line(line: str, model: int) -> Atom | None:
    try:
        return Atom(
            serial=int(line[6:11]),
            record=line[0:6].strip(),
            name=line[12:16].strip(),
            resname=line[17:20].strip().upper(),
            chain=line[21:22].strip(),
            resseq=line[22:26].strip(),
            icode=line[26:27].strip(),
            x=float(line[30:38]),
            y=float(line[38:46]),
            z=float(line[46:54]),
            element=_element_from_line(line, line[12:16].strip()),
            model=model,
        )
    except ValueError:
        return None


def read_pdb(path: Path, model: int | None = None) -> list[Atom]:
    """Parse ATOM/HETATM records. `model=None` keeps all models; an integer
    selects a single MODEL/ENDMDL block (default PDB behavior when no MODEL
    records exist)."""
    atoms: list[Atom] = []
    current_model = 1
    saw_model = False
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if line.startswith("MODEL"):
                saw_model = True
                parts = line.split()
                current_model = (
                    int(parts[1])
                    if len(parts) > 1 and parts[1].isdigit()
                    else current_model
                )
                continue
            if (
                line.startswith("ENDMDL")
                and saw_model
                and model is not None
                and current_model == model
            ):
                break
            if not line.startswith(("ATOM", "HETATM")):
                continue
            if model is not None and saw_model and current_model != model:
                continue
            atom = _parse_atom_line(line, current_model)
            if atom is not None:
                atoms.append(atom)
    if not atoms:
        scope = f"model {model} of " if model is not None else ""
        raise PdbGeometryError(f"No ATOM/HETATM records found in {scope}{path}")
    return atoms


def read_conect(path: Path) -> list[tuple[int, int]]:
    bonds = set()
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if not line.startswith("CONECT"):
                continue
            fields = line.split()
            if len(fields) < 3:
                continue
            try:
                source = int(fields[1])
            except ValueError:
                continue
            for field in fields[2:]:
                try:
                    target = int(field)
                except ValueError:
                    continue
                if source != target:
                    bonds.add(tuple(sorted((source, target))))
    return sorted(bonds)


def is_hydrogen(atom: Atom) -> bool:
    return atom.element == "H" or atom.name.upper().startswith("H")


def distance(a: Atom, b: Atom) -> float:
    return math.dist((a.x, a.y, a.z), (b.x, b.y, b.z))
