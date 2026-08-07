#!/usr/bin/env python3
"""Create direct-PDB visualization scenes and editable ChimeraX/PyMOL scripts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_SHARED = Path(__file__).resolve().parents[2] / "molecular-geometry-common" / "scripts"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))
from pdb_geometry import (
    POLAR_ELEMENTS as POLAR,
)
from pdb_geometry import (
    SOLVENT_IONS,
    STANDARD_AA,
    Atom,
    PdbGeometryError,
    distance,
    read_pdb,
)


class SceneError(PdbGeometryError):
    pass


def stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SceneError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SceneError(f"{path} must contain a JSON object")
    return data


def parse_pdb(path: Path) -> list[Atom]:
    if path.suffix.lower() not in {".pdb", ".ent"}:
        raise SceneError(
            "Direct automatic inference currently supports PDB files. Convert mmCIF to PDB or provide explicit selections."
        )
    try:
        return read_pdb(path)
    except PdbGeometryError as exc:
        raise SceneError(str(exc)) from exc


def residues_selection(residues: list[tuple[str, str, str]], backend: str) -> str:
    grouped: dict[str, list[str]] = defaultdict(list)
    for chain, resid, _resname in residues:
        if resid not in grouped[chain]:
            grouped[chain].append(resid)
    if backend == "chimerax":
        return " | ".join(
            f"/{chain}:{','.join(values)}" if chain else f":{','.join(values)}"
            for chain, values in grouped.items()
        )
    return " or ".join(
        f"(chain {chain} and resi {'+'.join(values)})"
        if chain
        else f"(resi {'+'.join(values)})"
        for chain, values in grouped.items()
    )


def largest_ligand(atoms: list[Atom]) -> list[Atom]:
    groups: dict[tuple[str, str, str], list[Atom]] = defaultdict(list)
    for atom in atoms:
        if atom.record == "HETATM" and atom.resname not in SOLVENT_IONS:
            groups[atom.residue].append(atom)
    candidates = [group for group in groups.values() if len(group) >= 3]
    return max(candidates, key=len) if candidates else []


def protein_atoms(atoms: list[Atom]) -> list[Atom]:
    return [a for a in atoms if a.record == "ATOM" and a.resname in STANDARD_AA]


def pocket_and_hbonds(
    ligand: list[Atom], protein: list[Atom]
) -> tuple[list[tuple[str, str, str]], list[dict[str, Any]]]:
    residues: list[tuple[str, str, str]] = []
    hbonds: list[dict[str, Any]] = []
    for receptor in protein:
        nearest = min((distance(receptor, lig) for lig in ligand), default=999.0)
        if nearest <= 5.0 and receptor.residue not in residues:
            residues.append(receptor.residue)
        if receptor.element in POLAR:
            for lig in ligand:
                if lig.element in POLAR and distance(receptor, lig) <= 4.0:
                    hbonds.append(
                        {
                            "ligand": lig.chimerax,
                            "protein": receptor.chimerax,
                            "ligand_pymol": lig.pymol,
                            "protein_pymol": receptor.pymol,
                            "distance_angstrom": round(distance(receptor, lig), 3),
                            "kind": "hydrogen_bond_candidate",
                        }
                    )
    return residues, sorted(hbonds, key=lambda item: item["distance_angstrom"])[:8]


def interface_residues(
    protein: list[Atom],
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    chains = sorted({a.chain for a in protein if a.chain})
    if len(chains) < 2:
        return [], []
    best: tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]] = ([], [])
    for index, first in enumerate(chains):
        left = [a for a in protein if a.chain == first]
        for second in chains[index + 1 :]:
            right = [a for a in protein if a.chain == second]
            hit_left: list[tuple[str, str, str]] = []
            hit_right: list[tuple[str, str, str]] = []
            for a in left:
                for b in right:
                    if distance(a, b) <= 5.0:
                        if a.residue not in hit_left:
                            hit_left.append(a.residue)
                        if b.residue not in hit_right:
                            hit_right.append(b.residue)
            if len(hit_left) + len(hit_right) > len(best[0]) + len(best[1]):
                best = hit_left, hit_right
    return best


def default_request(kind: str) -> dict[str, Any]:
    template = {
        "protein-ligand": "pocket-glass",
        "protein-protein": "ppi-interface",
        "protein": "protein-context",
    }[kind]
    return {
        "schema_version": "1.0",
        "artifact_type": "visualization_request",
        "kind": kind,
        "template": template,
        "backend": "auto",
        "style": {
            "background": "white",
            "lighting": "soft",
            "silhouettes": True,
            "surface_transparency_percent": 65,
            "width": 1920,
            "height": 1080,
            "supersample": 3,
        },
        "focus": {"infer_if_missing": True},
        "annotations": {
            "hbond_candidates": kind == "protein-ligand",
            "residue_labels": "key-candidates",
        },
        "explicit": {},
        "assumptions": [],
        "warnings": [],
    }


def infer(structure: Path, request: dict[str, Any]) -> dict[str, Any]:
    atoms = parse_pdb(structure)
    protein = protein_atoms(atoms)
    ligand = largest_ligand(atoms)
    requested = request.get("kind", "auto")
    detected = (
        "protein-ligand"
        if ligand
        else "protein-protein"
        if len({a.chain for a in protein if a.chain}) >= 2
        else "protein"
    )
    kind = detected if requested == "auto" else requested
    warnings = list(request.get("warnings", []))
    assumptions = list(request.get("assumptions", []))
    if requested not in {"auto", detected}:
        warnings.append(
            f"Requested kind '{requested}' differs from inferred kind '{detected}'; explicit request was retained."
        )
    data: dict[str, Any] = {
        "schema_version": "1.0",
        "artifact_type": "direct_structure_inference",
        "created_at": stamp(),
        "structure": str(structure.resolve()),
        "kind": kind,
        "detected_kind": detected,
        "atom_counts": {
            "all": len(atoms),
            "protein": len(protein),
            "ligand": len(ligand),
        },
        "selections": {
            "protein_chimerax": "protein",
            "protein_pymol": "polymer.protein",
        },
        "hbond_candidates": [],
        "assumptions": assumptions,
        "warnings": warnings,
    }
    if kind == "protein-ligand":
        if not ligand:
            data["warnings"].append(
                "No non-solvent HETATM ligand was inferred; generated protein-context fallback."
            )
            data["kind"] = "protein"
        else:
            pocket, hbonds = pocket_and_hbonds(ligand, protein)
            data["selections"].update(
                {
                    "ligand_chimerax": residues_selection(
                        [ligand[0].residue], "chimerax"
                    ),
                    "ligand_pymol": residues_selection([ligand[0].residue], "pymol"),
                    "pocket_chimerax": residues_selection(pocket, "chimerax"),
                    "pocket_pymol": residues_selection(pocket, "pymol"),
                }
            )
            data["ligand"] = {
                "resname": ligand[0].resname,
                "chain": ligand[0].chain,
                "resid": ligand[0].resid,
            }
            data["hbond_candidates"] = hbonds
            if not pocket:
                data["warnings"].append(
                    "No pocket residues were found within 5.0 Å of the inferred ligand."
                )
    elif kind == "protein-protein":
        left, right = interface_residues(protein)
        if not left or not right:
            data["warnings"].append(
                "No chain-pair interface was inferred within 5.0 Å; generated protein-context fallback."
            )
            data["kind"] = "protein"
        else:
            data["selections"].update(
                {
                    "interface_a_chimerax": residues_selection(left, "chimerax"),
                    "interface_b_chimerax": residues_selection(right, "chimerax"),
                    "interface_a_pymol": residues_selection(left, "pymol"),
                    "interface_b_pymol": residues_selection(right, "pymol"),
                }
            )
    return data


def renderer(backend: str, receipt: dict[str, Any] | None) -> str | None:
    available = {
        "chimerax": bool(shutil.which("chimerax")),
        "pymol": bool(shutil.which("pymol")),
    }
    if receipt:
        tools = receipt.get("report", receipt).get("tools", {})
        for name, detected in available.items():
            available[name] = detected or bool(tools.get(name, {}).get("available"))
    if backend == "auto":
        return (
            "chimerax"
            if available["chimerax"]
            else "pymol"
            if available["pymol"]
            else None
        )
    return backend if available[backend] else None


def direct_scripts(
    inference: dict[str, Any], request: dict[str, Any], outdir: Path
) -> tuple[str, str]:
    structure = inference["structure"]
    selections = inference["selections"]
    kind = inference["kind"]
    style = request.get("style", {})
    image = outdir / "scene.png"
    cx = [
        f"open {structure}",
        "hide atoms",
        "show cartoons",
        "color protein slate gray",
        f"set bgColor {style.get('background', 'white')}",
        f"lighting {style.get('lighting', 'soft')}",
        "graphics silhouettes true width 1.5",
    ]
    pml = [
        f"load {structure}",
        "hide everything",
        "show cartoon, polymer.protein",
        "color gray70, polymer.protein",
        f"bg_color {style.get('background', 'white')}",
        "set ray_opaque_background, off",
    ]
    if kind == "protein-ligand":
        ligand_cx, pocket_cx = (
            selections["ligand_chimerax"],
            selections.get("pocket_chimerax", ""),
        )
        ligand_pm, pocket_pm = (
            selections["ligand_pymol"],
            selections.get("pocket_pymol", ""),
        )
        cx += [
            f"show {ligand_cx}",
            f"style {ligand_cx} stick",
            f"color {ligand_cx} magenta",
            f"show {pocket_cx}",
            f"style {pocket_cx} stick",
            f"color {pocket_cx} cyan",
            f"surface {pocket_cx}",
            f"transparency {pocket_cx} {style.get('surface_transparency_percent', 65)} target s",
            f"view {ligand_cx} | {pocket_cx}",
        ]
        pml += [
            f"show sticks, {ligand_pm}",
            f"color magenta, {ligand_pm}",
            f"show sticks, {pocket_pm}",
            f"color cyan, {pocket_pm}",
            f"show surface, {pocket_pm}",
            f"set transparency, {style.get('surface_transparency_percent', 65) / 100:.2f}, {pocket_pm}",
            f"zoom ({ligand_pm}) or ({pocket_pm})",
        ]
        for index, candidate in enumerate(inference.get("hbond_candidates", []), 1):
            cx.append(
                f"distance {candidate['ligand']} {candidate['protein']} color cornflower blue radius 0.08 dashes 6"
            )
            pml.append(
                f"distance hbond_candidate_{index}, {candidate['ligand_pymol']}, {candidate['protein_pymol']}"
            )
    elif kind == "protein-protein":
        for suffix, color in (("a", "cornflower blue"), ("b", "plum")):
            cxsel, pmsel = (
                selections[f"interface_{suffix}_chimerax"],
                selections[f"interface_{suffix}_pymol"],
            )
            cx += [
                f"show {cxsel}",
                f"style {cxsel} stick",
                f"color {cxsel} {color}",
                f"surface {cxsel}",
                f"transparency {cxsel} {style.get('surface_transparency_percent', 65)} target s",
            ]
            pml += [
                f"show sticks, {pmsel}",
                f"color {color.replace(' ', '')}, {pmsel}",
                f"show surface, {pmsel}",
                f"set transparency, {style.get('surface_transparency_percent', 65) / 100:.2f}, {pmsel}",
            ]
        cx.append(
            f"view {selections['interface_a_chimerax']} | {selections['interface_b_chimerax']}"
        )
    else:
        cx += [
            "surface protein",
            f"transparency protein {style.get('surface_transparency_percent', 75)} target s",
            "view all",
        ]
        pml += [
            "show surface, polymer.protein",
            f"set transparency, {style.get('surface_transparency_percent', 75) / 100:.2f}, polymer.protein",
            "zoom polymer.protein",
        ]
    cx.append(
        f"save {image.resolve()} width {style.get('width', 1920)} height {style.get('height', 1080)} supersample {style.get('supersample', 3)}"
    )
    pml.append(
        f"png {image.resolve()}, {style.get('width', 1920)}, {style.get('height', 1080)}, ray=1"
    )
    return "\n".join(cx) + "\n", "\n".join(pml) + "\n"


def write_direct_scene(
    structure: Path,
    request: dict[str, Any],
    inference_data: dict[str, Any],
    outdir: Path,
    receipt: dict[str, Any] | None,
) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    active = renderer(request.get("backend", "auto"), receipt)
    cx, pml = direct_scripts(inference_data, request, outdir)
    (outdir / "render_chimerax.cxc").write_text(cx, encoding="utf-8")
    (outdir / "render_pymol.pml").write_text(pml, encoding="utf-8")
    scene = {
        "schema_version": "1.0",
        "artifact_type": "docking_visualization_scene",
        "created_at": stamp(),
        "structure": str(structure.resolve()),
        "kind": inference_data["kind"],
        "template": request.get("template"),
        "request": request,
        "inference": str(outdir / "inference.json"),
        "requested_backend": request.get("backend", "auto"),
        "selected_backend": active,
        "rendering_complete": False,
        "artifacts": {
            "chimerax": str((outdir / "render_chimerax.cxc").resolve()),
            "pymol": str((outdir / "render_pymol.pml").resolve()),
        },
        "warnings": inference_data.get("warnings", [])
        + (
            []
            if active
            else [
                "No verified renderer found; editable scripts were generated but not rendered."
            ]
        ),
    }
    path = outdir / "visualization_scene.json"
    write_json(path, scene)
    report = [
        "# Direct structure visualization report",
        "",
        f"Template: `{scene['template']}`",
        f"Inferred structure class: `{inference_data['kind']}`",
        "",
        "## Assumptions",
        *[
            f"- {x}"
            for x in inference_data.get("assumptions", []) or ["None recorded."]
        ],
        "",
        "## Warnings",
        *[f"- {x}" for x in scene["warnings"] or ["None."]],
        "",
        "Hydrogen-bond lines, if present, are distance-based geometry candidates rather than validated interactions.",
    ]
    (outdir / "visualization_report.md").write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )
    return path


def legacy_scene(args: argparse.Namespace) -> Path:
    analysis = read_json(args.analysis)
    receipt = read_json(args.environment_receipt) if args.environment_receipt else None
    if analysis.get("complex_type") != "pli":
        raise SceneError(
            "Unified PLI scene requires complex_type='pli'; use direct-PDB commands for PPI/protein structures."
        )
    structure = Path(analysis.get("structure", {}).get("path", "")).expanduser()
    ligand = analysis.get("visualization_hints", {}).get(
        "ligand_selection"
    ) or analysis.get("ligand", {}).get("selection")
    pocket = analysis.get("visualization_hints", {}).get("pocket_selection")
    if not structure.is_file() or not ligand or not pocket:
        raise SceneError(
            "Analysis must include existing structure, ligand selection, and pocket selection"
        )
    request = default_request("protein-ligand")
    request["backend"] = args.backend
    request["template"] = "pocket-glass"
    inference_data = {
        "kind": "protein-ligand",
        "selections": {
            "ligand_chimerax": ligand,
            "pocket_chimerax": pocket,
            "ligand_pymol": ligand,
            "pocket_pymol": pocket,
        },
        "hbond_candidates": [],
        "warnings": [],
    }
    return write_direct_scene(
        structure, request, inference_data, args.output_dir, receipt
    )


def command_template(args: argparse.Namespace) -> Path:
    data = default_request(args.kind)
    data["kind"] = args.kind
    path = args.output
    write_json(path, data)
    return path


def command_infer(args: argparse.Namespace) -> Path:
    request = read_json(args.request)
    data = infer(args.structure.resolve(), request)
    path = args.output_dir / "inference.json"
    write_json(path, data)
    return path


def command_generate(args: argparse.Namespace) -> Path:
    request = read_json(args.request)
    inference_path = args.inference or args.output_dir / "inference.json"
    data = (
        read_json(inference_path)
        if inference_path.is_file()
        else infer(args.structure.resolve(), request)
    )
    write_json(args.output_dir / "inference.json", data)
    receipt = read_json(args.environment_receipt) if args.environment_receipt else None
    return write_direct_scene(
        args.structure.resolve(), request, data, args.output_dir, receipt
    )


def command_render(args: argparse.Namespace) -> Path:
    scene = read_json(args.scene)
    backend = args.backend if args.backend != "auto" else scene.get("selected_backend")
    if backend not in {"chimerax", "pymol"}:
        raise SceneError(
            "No verified renderer selected; scripts remain available for manual execution."
        )
    script = Path(scene["artifacts"][backend])
    executable = shutil.which(backend)
    if not executable:
        raise SceneError(f"{backend} is not available on PATH")
    command = (
        [executable, "--offscreen", str(script)]
        if backend == "chimerax"
        else [executable, "-cq", str(script)]
    )
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    path = args.output_dir / "render_receipt.json"
    write_json(
        path,
        {
            "backend": backend,
            "command": command,
            "returncode": result.returncode,
            "stdout": result.stdout[-2000:],
            "stderr": result.stderr[-2000:],
        },
    )
    if result.returncode:
        raise SceneError(f"{backend} render failed; see {path}")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("scene", help="Compatibility: scene from complex_analysis.json.")
    p.add_argument("--analysis", type=Path, required=True)
    p.add_argument("--backend", choices=("auto", "chimerax", "pymol"), required=True)
    p.add_argument("--environment-receipt", type=Path)
    p.add_argument("--output-dir", type=Path, required=True)
    p.set_defaults(func=legacy_scene)
    p = sub.add_parser(
        "template", help="Write a direct-PDB visualization request template."
    )
    p.add_argument(
        "--kind",
        choices=("protein-ligand", "protein-protein", "protein"),
        required=True,
    )
    p.add_argument("--output", type=Path, required=True)
    p.set_defaults(func=command_template)
    p = sub.add_parser(
        "infer", help="Infer structure class and defensible focus selections from PDB."
    )
    p.add_argument("--structure", type=Path, required=True)
    p.add_argument("--request", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.set_defaults(func=command_infer)
    p = sub.add_parser(
        "generate", help="Generate scene, editable scripts, and disclosure report."
    )
    p.add_argument("--structure", type=Path, required=True)
    p.add_argument("--request", type=Path, required=True)
    p.add_argument("--inference", type=Path)
    p.add_argument("--environment-receipt", type=Path)
    p.add_argument("--output-dir", type=Path, required=True)
    p.set_defaults(func=command_generate)
    p = sub.add_parser(
        "render", help="Optionally render a generated scene with a verified executable."
    )
    p.add_argument("--scene", type=Path, required=True)
    p.add_argument("--backend", choices=("auto", "chimerax", "pymol"), required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.set_defaults(func=command_render)
    args = parser.parse_args()
    try:
        path = args.func(args)
    except SceneError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Success! Data written to: {path}")


if __name__ == "__main__":
    main()
