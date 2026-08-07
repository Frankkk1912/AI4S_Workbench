#!/usr/bin/env python3
"""Rigidly align complete ligand GRO coordinates to a named-atom docking pose."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path


class AlignmentError(ValueError):
    pass


def dot(a, b): return sum(x * y for x, y in zip(a, b))
def sub(a, b): return [x - y for x, y in zip(a, b)]
def add(a, b): return [x + y for x, y in zip(a, b)]
def scale(a, s): return [x * s for x in a]
def cross(a, b): return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
def norm(a): return math.sqrt(dot(a, a))
def unit(a):
    length = norm(a)
    if length < 1e-10: raise AlignmentError("Mapped heavy atoms are collinear or duplicated.")
    return scale(a, 1 / length)
def sha(path: Path): return hashlib.sha256(path.read_bytes()).hexdigest()


def pdbqt_atoms(path: Path):
    atoms = {}
    for line in path.read_text(errors="replace").splitlines():
        if not line.startswith(("ATOM", "HETATM")): continue
        try: name, xyz = line[12:16].strip(), [float(line[30:38]), float(line[38:46]), float(line[46:54])]
        except ValueError:
            fields = line.split(); name, xyz = fields[2], list(map(float, fields[6:9]))
        if name in atoms: raise AlignmentError(f"Duplicate docking atom name: {name}")
        atoms[name] = scale(xyz, 0.1)  # Angstrom to nm
    return atoms


def gro_atoms(path: Path):
    lines = path.read_text().splitlines()
    if len(lines) < 3: raise AlignmentError("GRO file is incomplete.")
    try: count = int(lines[1].strip())
    except ValueError as exc: raise AlignmentError("GRO atom count is invalid.") from exc
    if len(lines) < count + 3: raise AlignmentError("GRO atom records are incomplete.")
    atoms = []
    for line in lines[2:2+count]:
        try: atom = {"resnr": int(line[:5]), "resid": line[5:10].strip(), "name": line[10:15].strip(), "nr": int(line[15:20]), "xyz": [float(line[20:28]), float(line[28:36]), float(line[36:44])]}
        except ValueError as exc: raise AlignmentError(f"Invalid GRO atom record: {line}") from exc
        atoms.append(atom)
    return lines[0], atoms, lines[2+count]


def basis(origin, p1, p2):
    e0 = unit(sub(p1, origin)); e2 = unit(cross(e0, sub(p2, origin))); e1 = cross(e2, e0)
    return (e0, e1, e2)


def transform(point, source_origin, source_basis, target_origin, target_basis):
    delta = sub(point, source_origin)
    return add(target_origin, add(scale(target_basis[0], dot(delta, source_basis[0])), add(scale(target_basis[1], dot(delta, source_basis[1])), scale(target_basis[2], dot(delta, source_basis[2])))))


def align_pose_to_gro(pose: Path, ligand_gro: Path, output: Path):
    dock = pdbqt_atoms(pose); title, atoms, box = gro_atoms(ligand_gro)
    gro = {atom["name"]: atom["xyz"] for atom in atoms}
    shared = [name for name in gro if name in dock and not name.upper().startswith("H")]
    if len(shared) < 3: raise AlignmentError("At least three shared non-hydrogen atom names are required.")
    names = shared[:3]
    source_basis = basis(gro[names[0]], gro[names[1]], gro[names[2]])
    target_basis = basis(dock[names[0]], dock[names[1]], dock[names[2]])
    for atom in atoms: atom["xyz"] = transform(atom["xyz"], gro[names[0]], source_basis, dock[names[0]], target_basis)
    squared = [dot(sub(next(atom["xyz"] for atom in atoms if atom["name"] == name), dock[name]), sub(next(atom["xyz"] for atom in atoms if atom["name"] == name), dock[name])) for name in shared]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(title + "\n" + str(len(atoms)) + "\n" + "".join(f"{a['resnr']:5d}{a['resid']:<5}{a['name']:>5}{a['nr']:5d}{a['xyz'][0]:8.3f}{a['xyz'][1]:8.3f}{a['xyz'][2]:8.3f}\n" for a in atoms) + box + "\n")
    return {"mapped_heavy_atoms": shared, "heavy_atom_rmsd_nm": math.sqrt(sum(squared)/len(squared)), "pose": {"path": str(pose.resolve()), "sha256": sha(pose)}, "source": {"path": str(ligand_gro.resolve()), "sha256": sha(ligand_gro)}, "coordinates": {"path": str(output.resolve()), "sha256": sha(output)}}


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--pose", type=Path, required=True); parser.add_argument("--ligand-gro", type=Path, required=True); parser.add_argument("--output", type=Path, required=True); parser.add_argument("--report", type=Path, required=True); args = parser.parse_args()
    try: data = align_pose_to_gro(args.pose, args.ligand_gro, args.output)
    except AlignmentError as exc: print(f"Error: {exc}", file=sys.stderr); raise SystemExit(1)
    args.report.parent.mkdir(parents=True, exist_ok=True); args.report.write_text(json.dumps(data, indent=2)+"\n"); print(f"Success! Data written to: {args.report}")


if __name__ == "__main__": main()
