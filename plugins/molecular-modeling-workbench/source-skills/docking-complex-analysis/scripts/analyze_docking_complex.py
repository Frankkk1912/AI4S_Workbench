#!/usr/bin/env python3
"""Analyze docking complexes and write standardized geometry outputs."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_SHARED = Path(__file__).resolve().parents[2] / "molecular-geometry-common" / "scripts"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))
from pdb_geometry import (
    POLAR_ELEMENTS,
    SOLVENT_IONS,
    STANDARD_AA,
    Atom,
    PdbGeometryError,
    distance,
    is_hydrogen,
    read_conect,
    read_pdb,
)

AROMATIC_RESIDUES = {"PHE", "TYR", "TRP", "HIS"}
HYDROPHOBIC_RESIDUES = {"ALA", "VAL", "LEU", "ILE", "MET", "PHE", "TRP", "TYR", "PRO"}


class AnalysisError(PdbGeometryError):
    """Raised when analysis inputs are invalid."""


def parse_vina_score(path: Path) -> dict[str, Any]:
    score: dict[str, Any] = {}
    pattern = re.compile(r"REMARK\s+VINA RESULT:\s+([-+]?\d+(?:\.\d+)?)")
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            match = pattern.search(line)
            if match:
                score["docking_score"] = float(match.group(1))
                score["score_type"] = "vina_result"
                score["units"] = "kcal/mol scoring-function value"
                break
    return score


DEFAULT_MIN_LIGAND_HEAVY_ATOMS = 6


def detect_ligand(
    atoms: list[Atom], min_heavy_atoms: int = DEFAULT_MIN_LIGAND_HEAVY_ATOMS
) -> tuple[str, list[dict[str, Any]]]:
    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for atom in atoms:
        if (
            is_hydrogen(atom)
            or atom.resname in STANDARD_AA
            or atom.resname in SOLVENT_IONS
        ):
            continue
        counts[(atom.resname, atom.chain, atom.resseq)] += 1
    candidates = [
        {
            "resname": resname,
            "chain": chain,
            "resseq": resseq,
            "heavy_atom_count": count,
        }
        for (resname, chain, resseq), count in counts.items()
    ]
    candidates.sort(key=lambda item: item["heavy_atom_count"], reverse=True)
    rejected = [c for c in candidates if c["heavy_atom_count"] < min_heavy_atoms]
    for candidate in rejected:
        candidate["rejected_reason"] = (
            f"heavy_atom_count {candidate['heavy_atom_count']} < min_ligand_atoms "
            f"{min_heavy_atoms} (likely solvent/additive fragment)"
        )
    candidates = [c for c in candidates if c["heavy_atom_count"] >= min_heavy_atoms]
    if not candidates:
        detail = ""
        if rejected:
            detail = (
                " Rejected small candidates: "
                + ", ".join(
                    f"{c['resname']}({c['heavy_atom_count']} atoms)" for c in rejected
                )
                + ". Lower --min-ligand-atoms if one of these is the intended ligand."
            )
        raise AnalysisError(
            f"Could not auto-detect ligand. Provide --ligand-resname.{detail}"
        )
    return candidates[0]["resname"], candidates + rejected


def chimerax_residue_set(residue_keys: list[tuple[str, str, str, str]]) -> str:
    parts = []
    for chain, resseq, icode, _resname in residue_keys:
        prefix = f"/{chain}" if chain else ""
        parts.append(f"{prefix}:{resseq}{icode or ''}")
    return " | ".join(parts)


def residue_selection_from_contact(contact: dict[str, Any]) -> str:
    chain = str(contact.get("protein_chain", ""))
    resseq = str(contact.get("protein_resseq", ""))
    icode = str(contact.get("protein_icode", ""))
    return (f"/{chain}" if chain else "") + f":{resseq}{icode}"


def summarize_interactions(
    contacts: list[dict[str, Any]],
    polar_contacts: list[dict[str, Any]],
    aromatic_candidates: list[dict[str, Any]],
    hydrophobic_contacts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}

    def add_rows(rows: list[dict[str, Any]], interaction_type: str) -> None:
        for row in rows:
            key = (
                interaction_type,
                str(row["protein_chain"]),
                str(row["protein_resseq"]),
                str(row["protein_icode"]),
                str(row["protein_resname"]),
            )
            current = grouped.get(key)
            if (
                current is None
                or row["distance_angstrom"] < current["min_distance_angstrom"]
            ):
                grouped[key] = {
                    "interaction_type": interaction_type,
                    "protein_chain": row["protein_chain"],
                    "protein_resseq": row["protein_resseq"],
                    "protein_icode": row["protein_icode"],
                    "protein_resname": row["protein_resname"],
                    "residue_selection": residue_selection_from_contact(row),
                    "min_distance_angstrom": row["distance_angstrom"],
                    "ligand_atom": row["ligand_atom"],
                    "ligand_element": row["ligand_element"],
                    "ligand_serial": row["ligand_serial"],
                    "protein_atom": row["protein_atom"],
                    "protein_element": row["protein_element"],
                    "protein_serial": row["protein_serial"],
                    "ligand_selection": row["ligand_selection"],
                    "protein_selection": row["protein_selection"],
                    "classification": "geometry_candidate",
                }

    add_rows(polar_contacts, "hydrogen_bond_candidate")
    add_rows(aromatic_candidates, "aromatic_contact_candidate")
    add_rows(hydrophobic_contacts, "hydrophobic_contact")

    priority = {
        "hydrogen_bond_candidate": 0,
        "aromatic_contact_candidate": 1,
        "hydrophobic_contact": 2,
    }
    return sorted(
        grouped.values(),
        key=lambda item: (
            priority.get(item["interaction_type"], 99),
            item["min_distance_angstrom"],
            item["protein_chain"],
            item["protein_resseq"],
        ),
    )


def residue_sort_key(
    key: tuple[str, str, str, str], min_distance: dict[tuple[str, str, str, str], float]
) -> tuple[Any, ...]:
    chain, resseq, icode, resname = key
    resseq_key: int | str = int(resseq) if resseq.isdigit() else resseq
    return (min_distance[key], chain, resseq_key, icode, resname)


def analyze_pli(args: argparse.Namespace) -> int:
    structure = Path(args.structure).expanduser().resolve()
    if not structure.exists():
        raise AnalysisError(f"Structure not found: {structure}")

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    atoms = read_pdb(structure, args.model)
    ligand_resname = args.ligand_resname.upper() if args.ligand_resname else None
    detected_candidates: list[dict[str, Any]] = []
    if ligand_resname is None:
        ligand_resname, detected_candidates = detect_ligand(
            atoms, args.min_ligand_atoms
        )

    ligand_atoms = [
        atom
        for atom in atoms
        if atom.resname == ligand_resname
        and (args.ligand_chain is None or atom.chain == args.ligand_chain)
        and not is_hydrogen(atom)
    ]
    if not ligand_atoms:
        raise AnalysisError(
            f"No ligand heavy atoms found for resname {ligand_resname}."
        )

    receptor_atoms = [
        atom
        for atom in atoms
        if atom.resname != ligand_resname
        and atom.resname not in SOLVENT_IONS
        and (args.protein_chain is None or atom.chain == args.protein_chain)
        and not is_hydrogen(atom)
    ]
    if not receptor_atoms:
        raise AnalysisError("No receptor heavy atoms found. Check --protein-chain.")

    contacts: list[dict[str, Any]] = []
    residue_min_distance: dict[tuple[str, str, str, str], float] = {}
    residue_contact_counts: dict[tuple[str, str, str, str], int] = defaultdict(int)
    polar_contacts: list[dict[str, Any]] = []
    aromatic_candidates: list[dict[str, Any]] = []
    hydrophobic_contacts: list[dict[str, Any]] = []
    clashes: list[dict[str, Any]] = []

    for lig_atom in ligand_atoms:
        for rec_atom in receptor_atoms:
            dist = distance(lig_atom, rec_atom)
            if dist > args.contact_cutoff:
                continue
            residue_key = rec_atom.residue_key
            residue_min_distance[residue_key] = min(
                dist, residue_min_distance.get(residue_key, dist)
            )
            residue_contact_counts[residue_key] += 1
            row = {
                "ligand_atom": lig_atom.name,
                "ligand_element": lig_atom.element,
                "protein_chain": rec_atom.chain,
                "protein_resseq": rec_atom.resseq,
                "protein_icode": rec_atom.icode,
                "protein_resname": rec_atom.resname,
                "protein_atom": rec_atom.name,
                "protein_element": rec_atom.element,
                "distance_angstrom": round(dist, 3),
                "ligand_selection": lig_atom.chimerax_serial_selection,
                "protein_selection": rec_atom.chimerax_serial_selection,
                "ligand_residue_atom_selection": lig_atom.chimerax_atom_selection,
                "protein_residue_atom_selection": rec_atom.chimerax_atom_selection,
                "ligand_serial": lig_atom.serial,
                "protein_serial": rec_atom.serial,
            }
            contacts.append(row)
            if (
                dist <= args.polar_cutoff
                and lig_atom.element in POLAR_ELEMENTS
                and rec_atom.element in POLAR_ELEMENTS
            ):
                polar_contacts.append(row)
            if (
                dist <= args.aromatic_cutoff
                and lig_atom.element == "C"
                and rec_atom.element == "C"
                and rec_atom.resname in AROMATIC_RESIDUES
            ):
                aromatic_candidates.append(row)
            if (
                dist <= args.hydrophobic_cutoff
                and lig_atom.element == "C"
                and rec_atom.element == "C"
                and rec_atom.resname in HYDROPHOBIC_RESIDUES
            ):
                hydrophobic_contacts.append(row)
            if dist < args.clash_cutoff:
                clashes.append(row)

    residue_keys = sorted(
        residue_min_distance,
        key=lambda key: residue_sort_key(key, residue_min_distance),
    )
    residue_rows = []
    for chain, resseq, icode, resname in residue_keys:
        key = (chain, resseq, icode, resname)
        residue_rows.append(
            {
                "chain": chain,
                "resseq": resseq,
                "icode": icode,
                "resname": resname,
                "min_distance_angstrom": round(residue_min_distance[key], 3),
                "contact_count": residue_contact_counts[key],
                "selection": (f"/{chain}" if chain else "") + f":{resseq}{icode or ''}",
            }
        )

    contacts.sort(key=lambda row: row["distance_angstrom"])
    polar_contacts.sort(key=lambda row: row["distance_angstrom"])
    aromatic_candidates.sort(key=lambda row: row["distance_angstrom"])
    hydrophobic_contacts.sort(key=lambda row: row["distance_angstrom"])
    clashes.sort(key=lambda row: row["distance_angstrom"])
    interaction_summary = summarize_interactions(
        contacts,
        polar_contacts,
        aromatic_candidates,
        hydrophobic_contacts,
    )

    ligand_serials = {atom.serial for atom in ligand_atoms}
    ligand_bonds = [
        {"from_serial": source, "to_serial": target}
        for source, target in read_conect(structure)
        if source in ligand_serials and target in ligand_serials
    ]
    ligand_diagram_atoms = [
        {
            "serial": atom.serial,
            "name": atom.name,
            "element": atom.element,
            "x": atom.x,
            "y": atom.y,
            "z": atom.z,
        }
        for atom in ligand_atoms
    ]

    warnings = []
    if not any(is_hydrogen(atom) for atom in atoms):
        warnings.append(
            "No hydrogens detected; hydrogen_bond_candidates are distance-only polar contacts."
        )
    elif not any(is_hydrogen(atom) for atom in ligand_atoms):
        warnings.append(
            "No ligand hydrogens detected; hydrogen_bond_candidates are distance-only polar contacts."
        )
    if not detected_candidates and args.ligand_resname:
        detected_candidates = [{"resname": ligand_resname, "source": "user"}]
    rejected_candidates = [c for c in detected_candidates if "rejected_reason" in c]
    if rejected_candidates:
        warnings.append(
            "Small-molecule candidates below --min-ligand-atoms were excluded: "
            + ", ".join(
                f"{c['resname']}({c['heavy_atom_count']} atoms)"
                for c in rejected_candidates
            )
            + "."
        )
    if not polar_contacts:
        warnings.append("No polar contacts found under the configured cutoff.")

    ligand_selection = f":{ligand_resname}"
    if args.ligand_chain:
        ligand_selection = f"/{args.ligand_chain}{ligand_selection}"

    analysis = {
        "schema_version": "1.0",
        "complex_type": "pli",
        "analysis_level": "geometry_interactions",
        "method": {
            "name": "heavy_atom_distance_geometry",
            "binding_site_cutoff_angstrom": args.contact_cutoff,
            "polar_cutoff_angstrom": args.polar_cutoff,
            "aromatic_cutoff_angstrom": args.aromatic_cutoff,
            "hydrophobic_cutoff_angstrom": args.hydrophobic_cutoff,
            "clash_cutoff_angstrom": args.clash_cutoff,
            "model": args.model,
        },
        "structure": {
            "path": str(structure),
            "format": structure.suffix.lower().lstrip(".") or "pdb",
        },
        "ligand": {
            "resname": ligand_resname,
            "chain": args.ligand_chain or "",
            "heavy_atom_count": len(ligand_atoms),
            "selection": ligand_selection,
            "detected_candidates": detected_candidates,
            "diagram_atoms": ligand_diagram_atoms,
            "diagram_bonds": ligand_bonds,
        },
        "receptor": {
            "protein_chain": args.protein_chain or "",
            "heavy_atom_count": len(receptor_atoms),
        },
        "binding_site_residues": residue_rows,
        "atom_contacts": contacts,
        "polar_contacts": polar_contacts,
        "hydrogen_bond_candidates": polar_contacts,
        "aromatic_contact_candidates": aromatic_candidates,
        "hydrophobic_contacts": hydrophobic_contacts,
        "interaction_summary": interaction_summary,
        "clashes": clashes,
        "scores": parse_vina_score(structure),
        "visualization_hints": {
            "ligand_selection": ligand_selection,
            "pocket_selection": chimerax_residue_set(residue_keys),
            "hbond_contacts": polar_contacts[: args.max_hbond_lines],
            "interaction_summary": interaction_summary,
            "show_distance_labels": False,
        },
        "warnings": warnings,
    }

    analysis_path = output_dir / "complex_analysis.json"
    contacts_path = output_dir / "atom_contacts.csv"
    residue_path = output_dir / "residue_contacts.csv"
    interactions_path = output_dir / "interaction_summary.csv"
    report_path = output_dir / "analysis_report.md"

    analysis_path.write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")
    write_csv(contacts_path, contacts)
    write_csv(residue_path, residue_rows)
    write_csv(interactions_path, interaction_summary)
    write_report(report_path, analysis)

    print(f"Success! Analysis written to: {analysis_path}")
    print(f"Atom contacts: {contacts_path}")
    print(f"Residue contacts: {residue_path}")
    print(f"Interaction summary: {interactions_path}")
    print(f"Report: {report_path}")
    return 0


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_report(path: Path, analysis: dict[str, Any]) -> None:
    ligand = analysis["ligand"]
    method = analysis["method"]
    lines = [
        "# Docking Complex Geometry Analysis",
        "",
        f"- Complex type: `{analysis['complex_type']}`",
        f"- Ligand: `{ligand['resname']}`",
        f"- Structure: `{analysis['structure']['path']}`",
        f"- Binding-site cutoff: `{method['binding_site_cutoff_angstrom']} A`",
        f"- Binding-site residues: `{len(analysis['binding_site_residues'])}`",
        f"- Atom contacts: `{len(analysis['atom_contacts'])}`",
        f"- H-bond candidates: `{len(analysis['hydrogen_bond_candidates'])}`",
        f"- Aromatic-contact candidates: `{len(analysis['aromatic_contact_candidates'])}`",
        f"- Hydrophobic contacts: `{len(analysis['hydrophobic_contacts'])}`",
        f"- Clashes: `{len(analysis['clashes'])}`",
        "",
        "## Top Binding-Site Residues",
        "",
    ]
    for row in analysis["binding_site_residues"][:20]:
        lines.append(
            f"- {row['resname']} {row['chain']}:{row['resseq']}{row['icode']} "
            f"min={row['min_distance_angstrom']} A contacts={row['contact_count']}"
        )
    if analysis["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in analysis["warnings"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def analyze_ppi(args: argparse.Namespace) -> int:
    structure = Path(args.structure).expanduser().resolve()
    if not structure.exists():
        raise AnalysisError(f"Structure not found: {structure}")

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    atoms = read_pdb(structure, args.model)

    chain_a_atoms = [
        a
        for a in atoms
        if a.chain == args.chain_a
        and not is_hydrogen(a)
        and a.resname not in SOLVENT_IONS
    ]
    chain_b_atoms = [
        a
        for a in atoms
        if a.chain == args.chain_b
        and not is_hydrogen(a)
        and a.resname not in SOLVENT_IONS
    ]

    if not chain_a_atoms or not chain_b_atoms:
        raise AnalysisError("Could not find heavy atoms for both Chain A and Chain B.")

    contacts: list[dict[str, Any]] = []
    polar_contacts: list[dict[str, Any]] = []
    aromatic_candidates: list[dict[str, Any]] = []
    hydrophobic_contacts: list[dict[str, Any]] = []
    clashes: list[dict[str, Any]] = []

    # Interface tracking for A
    interface_A: dict[tuple[str, str, str, str], float] = {}
    contact_counts_A: dict[tuple[str, str, str, str], int] = defaultdict(int)
    # Interface tracking for B
    interface_B: dict[tuple[str, str, str, str], float] = {}
    contact_counts_B: dict[tuple[str, str, str, str], int] = defaultdict(int)

    for atom_b in chain_b_atoms:
        for atom_a in chain_a_atoms:
            dist = distance(atom_b, atom_a)
            if dist > args.contact_cutoff:
                continue

            key_a = atom_a.residue_key
            interface_A[key_a] = min(dist, interface_A.get(key_a, dist))
            contact_counts_A[key_a] += 1

            key_b = atom_b.residue_key
            interface_B[key_b] = min(dist, interface_B.get(key_b, dist))
            contact_counts_B[key_b] += 1

            row = {
                "ligand_atom": atom_b.name,
                "ligand_element": atom_b.element,
                "protein_chain": atom_a.chain,
                "protein_resseq": atom_a.resseq,
                "protein_icode": atom_a.icode,
                "protein_resname": atom_a.resname,
                "protein_atom": atom_a.name,
                "protein_element": atom_a.element,
                "distance_angstrom": round(dist, 3),
                "ligand_selection": atom_b.chimerax_serial_selection,
                "protein_selection": atom_a.chimerax_serial_selection,
                "ligand_residue_atom_selection": atom_b.chimerax_atom_selection,
                "protein_residue_atom_selection": atom_a.chimerax_atom_selection,
                "ligand_serial": atom_b.serial,
                "protein_serial": atom_a.serial,
            }
            contacts.append(row)

            if (
                dist <= args.polar_cutoff
                and atom_b.element in POLAR_ELEMENTS
                and atom_a.element in POLAR_ELEMENTS
            ):
                polar_contacts.append(row)
            if (
                dist <= args.aromatic_cutoff
                and atom_b.element == "C"
                and atom_a.element == "C"
                and atom_a.resname in AROMATIC_RESIDUES
                and atom_b.resname in AROMATIC_RESIDUES
            ):
                aromatic_candidates.append(row)
            if (
                dist <= args.hydrophobic_cutoff
                and atom_b.element == "C"
                and atom_a.element == "C"
                and atom_a.resname in HYDROPHOBIC_RESIDUES
                and atom_b.resname in HYDROPHOBIC_RESIDUES
            ):
                hydrophobic_contacts.append(row)
            if dist < args.clash_cutoff:
                clashes.append(row)

    contacts.sort(key=lambda row: row["distance_angstrom"])
    polar_contacts.sort(key=lambda row: row["distance_angstrom"])
    aromatic_candidates.sort(key=lambda row: row["distance_angstrom"])
    hydrophobic_contacts.sort(key=lambda row: row["distance_angstrom"])
    clashes.sort(key=lambda row: row["distance_angstrom"])

    interaction_summary = summarize_interactions(
        contacts, polar_contacts, aromatic_candidates, hydrophobic_contacts
    )

    def to_residue_rows(iface_dict, counts_dict):
        keys = sorted(iface_dict, key=lambda k: residue_sort_key(k, iface_dict))
        rows = []
        for chain, resseq, icode, resname in keys:
            rows.append(
                {
                    "chain": chain,
                    "resseq": resseq,
                    "icode": icode,
                    "resname": resname,
                    "min_distance_angstrom": round(
                        iface_dict[(chain, resseq, icode, resname)], 3
                    ),
                    "contact_count": counts_dict[(chain, resseq, icode, resname)],
                    "selection": f"/{chain}:{resseq}{icode or ''}",
                }
            )
        return rows

    rows_A = to_residue_rows(interface_A, contact_counts_A)
    rows_B = to_residue_rows(interface_B, contact_counts_B)

    sel_A = chimerax_residue_set(list(interface_A.keys()))
    sel_B = chimerax_residue_set(list(interface_B.keys()))

    analysis = {
        "schema_version": "1.0",
        "complex_type": "ppi",
        "analysis_level": "geometry_interactions",
        "method": {
            "name": "heavy_atom_distance_geometry",
            "binding_site_cutoff_angstrom": args.contact_cutoff,
            "polar_cutoff_angstrom": args.polar_cutoff,
            "model": args.model,
        },
        "structure": {
            "path": str(structure),
            "format": structure.suffix.lower().lstrip(".") or "pdb",
        },
        "ligand": {
            "resname": "CHAIN_B",
            "chain": args.chain_b,
            "heavy_atom_count": len(chain_b_atoms),
            "selection": f"/{args.chain_b}",
        },
        "receptor": {
            "protein_chain": args.chain_a,
            "heavy_atom_count": len(chain_a_atoms),
            "selection": f"/{args.chain_a}",
        },
        "binding_site_residues": rows_A,
        "binding_site_residues_B": rows_B,
        "atom_contacts": contacts,
        "hydrogen_bond_candidates": polar_contacts,
        "hydrophobic_contacts": hydrophobic_contacts,
        "interaction_summary": interaction_summary,
        "clashes": clashes,
        "visualization_hints": {
            "ligand_selection": f"/{args.chain_b}",
            "pocket_selection": sel_A,
            "pocket_selection_B": sel_B,
            "hbond_contacts": polar_contacts[: args.max_hbond_lines],
            "interaction_summary": interaction_summary,
            "show_distance_labels": False,
        },
        "warnings": [],
    }

    analysis_path = output_dir / "complex_analysis.json"
    analysis_path.write_text(json.dumps(analysis, indent=2) + "\n", encoding="utf-8")

    print(f"Success! PPI Analysis written to: {analysis_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze molecular docking complexes.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    pli = subparsers.add_parser("pli", help="Protein-ligand geometry analysis.")
    pli.add_argument("--structure", required=True, help="Input complex PDB.")
    pli.add_argument("--ligand-resname", help="Ligand residue name, e.g. UNL or LIG.")
    pli.add_argument(
        "--min-ligand-atoms",
        type=int,
        default=DEFAULT_MIN_LIGAND_HEAVY_ATOMS,
        help="Minimum heavy atoms for auto-detected ligand candidates (filters solvent/additives).",
    )
    pli.add_argument("--ligand-chain", help="Optional ligand chain ID.")
    pli.add_argument("--protein-chain", help="Optional receptor/protein chain ID.")
    pli.add_argument(
        "--model", type=int, default=1, help="PDB model number to analyze."
    )
    pli.add_argument(
        "--contact-cutoff",
        type=float,
        default=5.0,
        help="Binding-site/contact cutoff in A.",
    )
    pli.add_argument(
        "--polar-cutoff",
        type=float,
        default=4.0,
        help="Polar/H-bond candidate cutoff in A.",
    )
    pli.add_argument(
        "--aromatic-cutoff",
        type=float,
        default=4.0,
        help="Aromatic-contact candidate cutoff in A.",
    )
    pli.add_argument(
        "--hydrophobic-cutoff",
        type=float,
        default=4.5,
        help="Hydrophobic carbon-contact cutoff in A.",
    )
    pli.add_argument(
        "--clash-cutoff", type=float, default=2.0, help="Clash warning cutoff in A."
    )
    pli.add_argument(
        "--max-hbond-lines",
        type=int,
        default=8,
        help="Max H-bond candidate lines suggested for visualization.",
    )
    pli.add_argument(
        "--output-dir", required=True, help="Directory for JSON/CSV/report outputs."
    )
    pli.set_defaults(func=analyze_pli)

    ppi = subparsers.add_parser("ppi", help="Protein-protein geometry analysis.")
    ppi.add_argument("--structure", required=True, help="Input complex PDB.")
    ppi.add_argument("--chain-a", required=True, help="Chain ID for protein A.")
    ppi.add_argument("--chain-b", required=True, help="Chain ID for protein B.")
    ppi.add_argument(
        "--model", type=int, default=1, help="PDB model number to analyze."
    )
    ppi.add_argument(
        "--contact-cutoff", type=float, default=5.0, help="Interface cutoff in A."
    )
    ppi.add_argument(
        "--polar-cutoff",
        type=float,
        default=4.0,
        help="Polar/H-bond candidate cutoff in A.",
    )
    ppi.add_argument(
        "--aromatic-cutoff",
        type=float,
        default=4.0,
        help="Aromatic-contact candidate cutoff in A.",
    )
    ppi.add_argument(
        "--hydrophobic-cutoff",
        type=float,
        default=4.5,
        help="Hydrophobic carbon-contact cutoff in A.",
    )
    ppi.add_argument(
        "--clash-cutoff", type=float, default=2.0, help="Clash warning cutoff in A."
    )
    ppi.add_argument(
        "--max-hbond-lines",
        type=int,
        default=8,
        help="Max H-bond candidate lines suggested for visualization.",
    )
    ppi.add_argument(
        "--output-dir", required=True, help="Directory for JSON/CSV outputs."
    )
    ppi.set_defaults(func=analyze_ppi)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except PdbGeometryError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
