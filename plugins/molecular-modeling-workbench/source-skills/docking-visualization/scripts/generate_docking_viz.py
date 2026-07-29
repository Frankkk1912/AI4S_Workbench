#!/usr/bin/env python3
"""Generate docking visualization scripts and 2D interaction diagrams."""

from __future__ import annotations

import argparse
import html
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


class VizError(ValueError):
    """Raised when visualization inputs are invalid."""


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VizError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise VizError("Analysis root must be a JSON object.")
    return data


def py_string(value: Any) -> str:
    return repr(str(value))


def warnable(command: str, comment: str | None = None) -> list[str]:
    lines = []
    if comment:
        lines.append(f"# {comment}")
    lines.append(f"r({py_string(command)})")
    return lines


def analysis_parts(analysis: dict[str, Any]) -> tuple[Path, str, str]:
    if analysis.get("complex_type") != "pli":
        raise VizError("Only complex_type='pli' is supported for these views.")
    structure = Path(analysis.get("structure", {}).get("path", "")).expanduser().resolve()
    if not structure.exists():
        raise VizError(f"Structure not found: {structure}")
    hints = analysis.get("visualization_hints", {})
    ligand_sel = hints.get("ligand_selection") or analysis.get("ligand", {}).get("selection")
    pocket_sel = hints.get("pocket_selection")
    if not ligand_sel:
        raise VizError("Analysis is missing ligand selection.")
    if not pocket_sel:
        raise VizError("Analysis has no binding-site residues to visualize.")
    return structure, str(ligand_sel), str(pocket_sel)


def hbond_label_selection(contacts: list[dict[str, Any]]) -> str:
    residues = []
    for contact in contacts:
        residue_atom = contact.get("protein_residue_atom_selection")
        if isinstance(residue_atom, str) and "@" in residue_atom:
            residue = residue_atom.rsplit("@", 1)[0]
            if residue not in residues:
                residues.append(residue)
    return " | ".join(residues)


def script_prelude(structure: Path, args: argparse.Namespace) -> list[str]:
    return [
        "# Auto-generated ChimeraX script from docking-complex-analysis.",
        "# Edit analysis parameters and regenerate rather than hand-editing repeated scripts.",
        "from chimerax.core.commands import run",
        "",
        "WARNINGS = []",
        "",
        "def r(cmd):",
        "    try:",
        "        run(session, cmd)",
        "    except Exception as exc:",
        "        WARNINGS.append(f\"{cmd!r} -> {exc}\")",
        "        print(f\"[WARN] {cmd!r} -> {exc}\")",
        "",
        f"r({py_string('open ' + str(structure).replace(os.sep, '/'))})",
        "r('~select')",
        "r('hide atoms')",
        "r('show cartoons')",
        f"r('color protein {args.color_protein}')",
        "",
    ]


def script_footer(output_dir: Path, image_path: Path, args: argparse.Namespace, quit_after_save: bool) -> list[str]:
    lines = [
        "",
        "# Global publication style.",
        "r('graphics silhouettes true width 1.5')",
        "r('lighting soft')",
        "r('set bgColor white')",
        "",
    ]
    lines.extend(
        warnable(
            f"save {str(image_path).replace(os.sep, '/')} "
            f"width {args.width} height {args.height} "
            f"transparentBackground false supersample {args.supersample}",
            "Save high-resolution render.",
        )
    )
    lines.append("")
    warning_path = (output_dir / f"{image_path.stem}_warnings.txt").resolve()
    lines.append(f"with open({py_string(str(warning_path))}, 'w', encoding='utf-8') as handle:")
    lines.append("    if WARNINGS:")
    lines.append("        handle.write('\\n'.join(WARNINGS) + '\\n')")
    lines.append("    else:")
    lines.append("        handle.write('No ChimeraX command warnings.\\n')")
    if quit_after_save:
        lines.append("r('quit')")
    lines.append("")
    return lines


def make_global_script(analysis: dict[str, Any], output_dir: Path, args: argparse.Namespace) -> str:
    structure, ligand_sel, pocket_sel = analysis_parts(analysis)
    image_path = (output_dir / args.global_image_name).resolve()
    lines = script_prelude(structure, args)
    lines.extend(warnable("hide cartoons", "Hide messy backbone for a clean global view."))
    lines.extend(warnable("surface protein", "Whole-protein context surface."))
    lines.extend(warnable(f"color protein {args.color_protein} target s", "Protein cloud."))
    lines.extend(warnable("transparency protein 85 target s", "High transparency for cloud effect."))
    lines.append("")
    lines.extend(warnable(f"show {ligand_sel}", "Ligand location in global context."))
    lines.extend(warnable(f"style {ligand_sel} stick"))
    lines.extend(warnable(f"size {ligand_sel} stickRadius 0.15", "Enforce thin sticks"))
    lines.extend(warnable(f"size {ligand_sel} atomRadius 0.15", "Remove ball spheres"))
    lines.extend(warnable(f"color {ligand_sel} {args.color_ligand}"))
    lines.extend(warnable(f"color {ligand_sel} byhetero"))
    lines.extend(warnable("hide H", "Hide all hydrogen atoms for clean stick look"))
    lines.extend(warnable("~label all", "Hide all labels in global view."))
    lines.extend(warnable("view all"))
    lines.extend(warnable(str(args.global_zoom_command)))
    lines.extend(script_footer(output_dir, image_path, args, args.quit_after_save))
    return "\n".join(lines)


def make_pocket_script(analysis: dict[str, Any], output_dir: Path, args: argparse.Namespace) -> str:
    structure, ligand_sel, pocket_sel = analysis_parts(analysis)
    image_path = (output_dir / args.pocket_image_name).resolve()
    hints = analysis.get("visualization_hints", {})
    hbond_contacts = hints.get("hbond_contacts", [])
    if not isinstance(hbond_contacts, list):
        hbond_contacts = []
    hbond_contacts = hbond_contacts[: args.max_hbond_lines]
    label_sel = hbond_label_selection(hbond_contacts)

    lines = script_prelude(structure, args)
    
    if args.style == "skeleton":
        lines.extend(warnable("hide ribbons", "Skeleton style: hide protein backbone ribbons."))
        lines.extend(warnable("hide cartoons"))
        args.surface = False  # Disable surface for pure skeleton
        
    lines.extend(warnable(f"show {ligand_sel}", "Ligand sticks."))
    lines.extend(warnable(f"style {ligand_sel} stick"))
    lines.extend(warnable(f"size {ligand_sel} stickRadius 0.15", "Enforce thin sticks"))
    lines.extend(warnable(f"size {ligand_sel} atomRadius 0.15", "Remove ball spheres"))
    lines.extend(warnable(f"color {ligand_sel} {args.color_ligand}"))
    lines.extend(warnable(f"color {ligand_sel} byhetero"))
    lines.append("")
    lines.extend(warnable(f"show {pocket_sel}", "Binding-site residues from analysis."))
    lines.extend(warnable(f"style {pocket_sel} stick"))
    lines.extend(warnable(f"size {pocket_sel} stickRadius 0.15", "Enforce thin sticks"))
    lines.extend(warnable(f"size {pocket_sel} atomRadius 0.15", "Remove ball spheres"))
    lines.extend(warnable(f"color {pocket_sel} {args.color_protein}", "Pocket matches protein color."))
    lines.extend(warnable(f"color {pocket_sel} byhetero"))
    lines.extend(warnable("hide H", "Hide all hydrogen atoms for clean stick look"))
    
    # Label ONLY hydrogen bond residues to avoid clutter
    for contact in hbond_contacts:
        chain = contact.get("protein_chain", "A")
        resseq = contact.get("protein_resseq")
        resname = contact.get("protein_resname", "UNK").capitalize()
        if resseq:
            sel = f"/{chain}:{resseq}@CA"
            text = f"{resname} {resseq}"
            lines.extend(warnable(f"label {sel} text {py_string(text)} height 1.0 color black bgColor #FFFFFFBB", f"Label {text}"))

    lines.append("")
    
    # Pocket view specific transparency settings
    lines.extend(warnable("~surface protein", "No surface cloud in pocket view."))
    lines.extend(warnable("show cartoons", "Show protein backbone ribbons."))
    lines.extend(warnable("transparency protein 80 target c", "Make non-pocket ribbons highly transparent (80%)."))
    lines.extend(warnable(f"transparency {pocket_sel} 0 target c", "Make pocket ribbons fully opaque."))
    lines.append("")
    lines.extend(warnable("hide pseudobonds", "Hide any automatic pseudobonds (e.g. missing structure)."))
    for contact in hbond_contacts:
        lig_serial = contact.get("ligand_serial")
        prot_serial = contact.get("protein_serial")
        
        if lig_serial is not None and prot_serial is not None:
            start = f"@@serial_number={lig_serial}"
            end = f"@@serial_number={prot_serial}"
        else:
            start = contact.get("ligand_residue_atom_selection")
            end = contact.get("protein_residue_atom_selection")
            if end and end.startswith(":"):
                chain = contact.get("protein_chain", "A")
                resseq = contact.get("protein_resseq")
                if resseq and "@" in end:
                    atom_name = end.split("@")[1]
                    end = f"/{chain}:{resseq}@{atom_name}"
            if not start or not end:
                continue

        lines.extend(
            warnable(
                f"distance {start} {end} color yellow radius {args.hbond_radius} dashes {args.hbond_dashes}",
                "H-bond candidate.",
            )
        )
    if hbond_contacts:
        lines.extend(warnable("~label all pseudobonds", "Hide distance text labels."))
    lines.extend(warnable(f"view {ligand_sel} | {pocket_sel}"))
    lines.extend(warnable(str(args.pocket_zoom_command)))
    lines.extend(script_footer(output_dir, image_path, args, args.quit_after_save))
    return "\n".join(lines)


def normalize_ligand_coords(atoms: list[dict[str, Any]], width: int = 420, height: int = 300) -> dict[int, tuple[float, float]]:
    if not atoms:
        return {}
    xs = [float(atom["x"]) for atom in atoms]
    ys = [float(atom["y"]) for atom in atoms]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 0.1)
    span_y = max(max_y - min_y, 0.1)
    scale = min(width / span_x, height / span_y)
    coords = {}
    for atom in atoms:
        x = 420 + (float(atom["x"]) - (min_x + max_x) / 2) * scale
        y = 300 - (float(atom["y"]) - (min_y + max_y) / 2) * scale
        coords[int(atom["serial"])] = (x, y)
    return coords


def interaction_style(interaction_type: str) -> tuple[str, str, str]:
    if interaction_type == "hydrogen_bond_candidate":
        return "#2563eb", "6,5", "H-bond"
    if interaction_type == "aromatic_contact_candidate":
        return "#7c3aed", "2,5", "Aromatic"
    return "#16a34a", "1,6", "Hydrophobic"


def residue_text(item: dict[str, Any]) -> str:
    return f"{item.get('protein_resname', '')} {item.get('protein_resseq', '')}".strip()


def write_interaction_svg(analysis: dict[str, Any], output_path: Path, max_hydrophobic: int) -> None:
    ligand = analysis.get("ligand", {})
    atoms = ligand.get("diagram_atoms", [])
    bonds = ligand.get("diagram_bonds", [])
    interactions = list(analysis.get("interaction_summary", []))
    if not atoms:
        raise VizError("Analysis has no ligand diagram atoms; rerun docking-complex-analysis.")

    kept = []
    hydrophobic_seen = 0
    for item in interactions:
        if item.get("interaction_type") == "hydrophobic_contact":
            hydrophobic_seen += 1
            if hydrophobic_seen > max_hydrophobic:
                continue
        kept.append(item)

    coords = normalize_ligand_coords(atoms)
    serial_to_atom = {int(atom["serial"]): atom for atom in atoms}
    residue_keys = []
    for item in kept:
        key = (
            item.get("protein_chain", ""),
            item.get("protein_resseq", ""),
            item.get("protein_icode", ""),
            item.get("protein_resname", ""),
        )
        if key not in residue_keys:
            residue_keys.append(key)
    residue_positions = {}
    center_x, center_y = 420, 300
    radius = 245
    for idx, key in enumerate(residue_keys):
        angle = -math.pi / 2 + (2 * math.pi * idx / max(len(residue_keys), 1))
        residue_positions[key] = (center_x + radius * math.cos(angle), center_y + radius * math.sin(angle))

    lines = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="660" viewBox="0 0 900 660">',
        '<rect width="900" height="660" fill="white"/>',
        '<text x="36" y="42" font-family="Arial" font-size="22" font-weight="700">Protein-ligand interaction diagram</text>',
        f'<text x="36" y="70" font-family="Arial" font-size="14" fill="#555">Ligand {html.escape(str(ligand.get("resname", "")))}; geometry-candidate interactions</text>',
    ]

    for item in kept:
        key = (
            item.get("protein_chain", ""),
            item.get("protein_resseq", ""),
            item.get("protein_icode", ""),
            item.get("protein_resname", ""),
        )
        rx, ry = residue_positions[key]
        lx, ly = coords.get(int(item.get("ligand_serial", 0)), (center_x, center_y))
        color, dash, _label = interaction_style(str(item.get("interaction_type", "")))
        lines.append(
            f'<line x1="{lx:.1f}" y1="{ly:.1f}" x2="{rx:.1f}" y2="{ry:.1f}" '
            f'stroke="{color}" stroke-width="2.2" stroke-dasharray="{dash}" opacity="0.82"/>'
        )

    for bond in bonds:
        a = coords.get(int(bond["from_serial"]))
        b = coords.get(int(bond["to_serial"]))
        if not a or not b:
            continue
        lines.append(
            f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" '
            'stroke="#1f2937" stroke-width="3" stroke-linecap="round"/>'
        )

    for serial, (x, y) in coords.items():
        atom = serial_to_atom.get(serial, {})
        element = str(atom.get("element", "C"))
        fill = {"O": "#ef4444", "N": "#6366f1", "S": "#eab308"}.get(element, "#f3d4a2")
        lines.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8" fill="{fill}" stroke="#111827" stroke-width="1"/>')
        if element != "C":
            lines.append(
                f'<text x="{x + 11:.1f}" y="{y + 4:.1f}" font-family="Arial" font-size="13" fill="#111827">{html.escape(element)}</text>'
            )

    for key, (x, y) in residue_positions.items():
        matching = [item for item in kept if (
            item.get("protein_chain", ""),
            item.get("protein_resseq", ""),
            item.get("protein_icode", ""),
            item.get("protein_resname", ""),
        ) == key]
        if not matching:
            continue
        priority = {"hydrogen_bond_candidate": 0, "aromatic_contact_candidate": 1, "hydrophobic_contact": 2}
        primary = sorted(matching, key=lambda item: priority.get(str(item.get("interaction_type", "")), 9))[0]
        color, _dash, label = interaction_style(str(primary.get("interaction_type", "")))
        text = residue_text(primary)
        width = max(74, len(text) * 9 + 22)
        lines.append(
            f'<rect x="{x - width / 2:.1f}" y="{y - 18:.1f}" width="{width:.1f}" height="36" rx="8" '
            f'fill="white" stroke="{color}" stroke-width="2"/>'
        )
        lines.append(
            f'<text x="{x:.1f}" y="{y + 5:.1f}" text-anchor="middle" font-family="Arial" '
            f'font-size="15" font-weight="700" fill="#111827">{html.escape(text)}</text>'
        )
        lines.append(
            f'<text x="{x:.1f}" y="{y + 32:.1f}" text-anchor="middle" font-family="Arial" '
            f'font-size="11" fill="{color}">{html.escape(label)}</text>'
        )

    legend = [("H-bond", "#2563eb", "6,5"), ("Aromatic", "#7c3aed", "2,5"), ("Hydrophobic", "#16a34a", "1,6")]
    y = 596
    for idx, (label, color, dash) in enumerate(legend):
        x = 36 + idx * 155
        lines.append(f'<line x1="{x}" y1="{y}" x2="{x + 42}" y2="{y}" stroke="{color}" stroke-width="2.5" stroke-dasharray="{dash}"/>')
        lines.append(f'<text x="{x + 52}" y="{y + 5}" font-family="Arial" font-size="13" fill="#374151">{label}</text>')
    lines.append("</svg>")
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_report_views(args: argparse.Namespace) -> int:
    analysis_path = Path(args.analysis).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    analysis = read_json(analysis_path)

    global_script = output_dir / args.global_script_name
    pocket_script = output_dir / args.pocket_script_name
    svg_path = output_dir / args.interaction_svg_name
    global_script.write_text(make_global_script(analysis, output_dir, args), encoding="utf-8")
    pocket_script.write_text(make_pocket_script(analysis, output_dir, args), encoding="utf-8")
    write_interaction_svg(analysis, svg_path, args.max_2d_hydrophobic)
    print(f"Success! Global view script written to: {global_script}")
    print(f"Success! Pocket view script written to: {pocket_script}")
    print(f"Success! 2D interaction SVG written to: {svg_path}")
    return 0


def from_analysis(args: argparse.Namespace) -> int:
    args.global_script_name = "render_global.py"
    args.pocket_script_name = args.script_name
    args.global_image_name = "global_view.png"
    args.pocket_image_name = args.image_name
    args.interaction_svg_name = "interaction_2d.svg"
    return write_report_views(args)


def render_script(args: argparse.Namespace) -> int:
    script = Path(args.script).expanduser().resolve()
    if not script.exists():
        raise VizError(f"ChimeraX script not found: {script}")
    chimerax = args.chimerax or shutil.which("chimerax")
    if chimerax and not Path(chimerax).expanduser().exists():
        chimerax = shutil.which(chimerax)
    if not chimerax:
        print("ChimeraX executable not found; script generation is still complete.")
        return 0
    completed = subprocess.run([chimerax, "--offscreen", "--exit", "--script", str(script)], check=False)
    if completed.returncode != 0:
        raise VizError(f"ChimeraX exited with code {completed.returncode}.")
    print("Success! ChimeraX render completed.")
    return 0


def add_common_view_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--style", choices=["classic", "skeleton"], default="classic", help="Overall visualization style: classic (ribbons+surface) or skeleton (sticks only).")
    parser.add_argument("--color-protein", default="cornflower blue", help="Color for the receptor protein ribbon/surface.")
    parser.add_argument("--color-ligand", default="plum", help="Color for the ligand sticks.")
    parser.add_argument("--color-pocket", default="forest green", help="Color for the pocket residues (sticks).")
    parser.add_argument("--max-hbond-lines", type=int, default=8, help="Maximum H-bond candidate lines to draw.")
    parser.add_argument("--surface", action=argparse.BooleanOptionalAction, default=True, help="Show transparent receptor surface in pocket view.")
    parser.add_argument("--surface-transparency", type=int, default=70, help="Pocket protein surface transparency percentage.")
    parser.add_argument("--global-surface-transparency", type=int, default=35, help="Global protein surface transparency percentage.")
    parser.add_argument("--global-pocket-surface-transparency", type=int, default=8, help="Global pocket surface transparency percentage.")
    parser.add_argument("--hbond-radius", type=float, default=0.08, help="H-bond candidate line radius.")
    parser.add_argument("--hbond-dashes", type=int, default=6, help="H-bond candidate line dashes.")
    parser.add_argument("--global-zoom-command", default="zoom 0.38", help="ChimeraX zoom command for global view.")
    parser.add_argument("--pocket-zoom-command", default="zoom 0.7", help="ChimeraX zoom command for pocket view.")
    parser.add_argument("--width", type=int, default=1920, help="Render width.")
    parser.add_argument("--height", type=int, default=1080, help="Render height.")
    parser.add_argument("--supersample", type=int, default=3, help="Render supersampling.")
    parser.add_argument("--max-2d-hydrophobic", type=int, default=10, help="Maximum hydrophobic residue nodes in the 2D SVG.")
    parser.add_argument("--quit-after-save", action="store_true", help="Quit ChimeraX after save.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate docking visualization scripts.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    report = subparsers.add_parser("report-views", help="Generate global, pocket, and 2D interaction views.")
    report.add_argument("--analysis", required=True, help="Path to complex_analysis.json.")
    report.add_argument("--output-dir", required=True, help="Directory for render scripts and figures.")
    report.add_argument("--global-script-name", default="render_global.py", help="Generated global ChimeraX script name.")
    report.add_argument("--pocket-script-name", default="render_pocket.py", help="Generated pocket ChimeraX script name.")
    report.add_argument("--global-image-name", default="global_view.png", help="Global rendered image name.")
    report.add_argument("--pocket-image-name", default="pocket_view.png", help="Pocket rendered image name.")
    report.add_argument("--interaction-svg-name", default="interaction_2d.svg", help="2D interaction SVG name.")
    add_common_view_args(report)
    report.set_defaults(func=write_report_views)

    analysis = subparsers.add_parser("from-analysis", help="Compatibility alias: generate report views from complex_analysis.json.")
    analysis.add_argument("--analysis", required=True, help="Path to complex_analysis.json.")
    analysis.add_argument("--output-dir", required=True, help="Directory for render scripts and figures.")
    analysis.add_argument("--script-name", default="render_pocket.py", help="Generated pocket ChimeraX script name.")
    analysis.add_argument("--image-name", default="pocket_view.png", help="Pocket rendered image name.")
    add_common_view_args(analysis)
    analysis.set_defaults(func=from_analysis)

    render = subparsers.add_parser("render", help="Run a generated ChimeraX script offscreen.")
    render.add_argument("--script", required=True, help="Generated ChimeraX script.")
    render.add_argument("--chimerax", help="Path to ChimeraX executable.")
    render.set_defaults(func=render_script)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except VizError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
