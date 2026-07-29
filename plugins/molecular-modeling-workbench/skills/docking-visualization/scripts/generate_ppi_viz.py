#!/usr/bin/env python3
"""Generate ChimeraX scripts for protein-protein docking visualizations."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


DEFAULT_TEMPLATE: dict[str, Any] = {
    "structure": {
        "path": "docking/complex_ox.pdb",
        "description": "Protein-protein docking complex in PDB or mmCIF format",
    },
    "domains": [
        {
            "name": "receptor catalytic domain",
            "selection": "/A:1-377",
            "color": "cornflower blue",
            "surface": False,
        },
        {
            "name": "receptor accessory domain",
            "selection": "/A:378-817",
            "color": "pale green",
            "surface": True,
            "surface_transparency": 70,
        },
        {
            "name": "binding partner",
            "selection": "/B",
            "color": "plum",
            "surface": True,
            "surface_transparency": 75,
        },
    ],
    "interface_groups": [
        {
            "name": "receptor hotspot residues",
            "selection": "/A:705,708,768,770",
            "style": "stick",
            "color": "medium violet red",
            "surface": True,
            "surface_transparency": 25,
        },
        {
            "name": "partner contact motif",
            "selection": "/B:31-34",
            "style": "stick",
            "color": "gold",
            "surface": True,
            "surface_transparency": 25,
        },
    ],
    "distances": [
        {
            "name": "L705 CD2 to C32 SG",
            "from": "/A:705@CD2",
            "to": "/B:32@SG",
            "color": "black",
            "radius": 0.08,
            "dashes": 6,
        }
    ],
    "labels": [
        {
            "selection": "/A:705@CA",
            "text": "L705",
            "height": 1.8,
            "color": "white",
            "bgColor": "#2C3E50",
            "offset": "0.5,0.5,0",
        },
        {
            "selection": "/A:768@CA",
            "text": "L768",
            "height": 1.8,
            "color": "white",
            "bgColor": "#2C3E50",
            "offset": "0.5,0.5,0",
        },
        {
            "selection": "/A:770@CA",
            "text": "D770",
            "height": 1.8,
            "color": "white",
            "bgColor": "#2C3E50",
            "offset": "0.5,0.5,0",
        },
        {
            "selection": "/B:31@CA",
            "text": "W31",
            "height": 1.8,
            "color": "white",
            "bgColor": "#2C3E50",
            "offset": "0.5,0.5,0",
        },
        {
            "selection": "/B:32@CA",
            "text": "C32",
            "height": 1.8,
            "color": "white",
            "bgColor": "#2C3E50",
            "offset": "0.5,0.5,0",
        },
    ],
    "view": {
        "background": "white",
        "silhouettes": True,
        "silhouette_width": 1.5,
        "lighting": "soft",
        "orient": True,
        "focus": "/A:680-800 | /B:25-100",
        "turns": [
            {"axis": "z", "angle": 90},
            {"axis": "y", "angle": 180},
        ],
        "zoom": 0.9,
        "width": 1920,
        "height": 1080,
        "supersample": 3,
        "transparentBackground": False,
        "quit_after_save": False,
    },
    "output": {
        "script_name": "render_ppi.py",
        "image_name": "protein_complex.png",
        "warnings_name": "render_ppi_warnings.txt",
    },
}


class ConfigError(ValueError):
    """Raised when the visualization config is invalid."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("Config root must be a JSON object.")
    return data


def _ensure_list(config: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = config.get(key, [])
    if not isinstance(value, list):
        raise ConfigError(f"`{key}` must be a list.")
    for idx, item in enumerate(value):
        if not isinstance(item, dict):
            raise ConfigError(f"`{key}[{idx}]` must be an object.")
    return value


def _validate_config(config: dict[str, Any], config_path: Path) -> None:
    structure = config.get("structure")
    if not isinstance(structure, dict):
        raise ConfigError("`structure` must be an object.")
    structure_path = structure.get("path")
    if not isinstance(structure_path, str) or not structure_path.strip():
        raise ConfigError("`structure.path` must be a non-empty string.")

    resolved = _resolve_path(structure_path, config_path.parent)
    if not resolved.exists():
        raise ConfigError(f"Structure file not found: {resolved}")

    for key in ("domains", "interface_groups", "distances", "labels"):
        _ensure_list(config, key)

    view = config.get("view", {})
    if not isinstance(view, dict):
        raise ConfigError("`view` must be an object.")

    output = config.get("output", {})
    if not isinstance(output, dict):
        raise ConfigError("`output` must be an object.")


def _resolve_path(path_value: str, base_dir: Path) -> Path:
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path
    candidate = base_dir / path
    if candidate.exists():
        return candidate.resolve()
    return (Path.cwd() / path).resolve()


def _py_string(value: Any) -> str:
    return repr(str(value))


def _warnable(command: str, comment: str | None = None) -> list[str]:
    lines = []
    if comment:
        lines.append(f"# {comment}")
    lines.append(f"r({_py_string(command)})")
    return lines


def _script_lines(config: dict[str, Any], config_path: Path, output_dir: Path) -> list[str]:
    structure_path = _resolve_path(config["structure"]["path"], config_path.parent)
    output = config.get("output", {})
    image_name = output.get("image_name", "protein_complex.png")
    warnings_name = output.get("warnings_name", "render_ppi_warnings.txt")

    view = config.get("view", {})
    image_path = (output_dir / image_name).resolve()
    warnings_path = (output_dir / warnings_name).resolve()

    lines = [
        "# Auto-generated ChimeraX script for protein-protein docking visualization.",
        "# Edit the config JSON and regenerate this file rather than hand-editing repeated scripts.",
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
        f"r({_py_string('open ' + str(structure_path).replace(os.sep, '/'))})",
        "r('~select')",
        "r('hide atoms')",
        "r('show ribbons')",
        "",
    ]

    for domain in _ensure_list(config, "domains"):
        name = domain.get("name", "domain")
        selection = domain.get("selection")
        color = domain.get("color")
        if not selection or not color:
            lines.append(f"# skipped incomplete domain: {name}")
            continue
        lines.extend(_warnable(f"color {selection} {color}", f"Domain: {name}"))
        if domain.get("surface"):
            lines.extend(
                _warnable(
                    f"surface {selection}",
                    "Local/chain surface; avoids fragile whole-scene surface toggles.",
                )
            )
            lines.extend(_warnable(f"color {selection} {color} target s"))
            transparency = domain.get("surface_transparency")
            if transparency is not None:
                lines.extend(_warnable(f"transparency {selection} {transparency} target s"))
        lines.append("")

    for group in _ensure_list(config, "interface_groups"):
        name = group.get("name", "interface group")
        selection = group.get("selection")
        if not selection:
            lines.append(f"# skipped incomplete interface group: {name}")
            continue
        lines.extend(_warnable(f"show {selection}", f"Interface: {name}"))
        if group.get("style"):
            lines.extend(_warnable(f"style {selection} {group['style']}"))
        if group.get("color"):
            lines.extend(_warnable(f"color {selection} {group['color']}"))
        if group.get("surface"):
            lines.extend(_warnable(f"surface {selection}"))
            if group.get("color"):
                lines.extend(_warnable(f"color {selection} {group['color']} target s"))
            transparency = group.get("surface_transparency")
            if transparency is not None:
                lines.extend(_warnable(f"transparency {selection} {transparency} target s"))
        lines.append("")

    for distance in _ensure_list(config, "distances"):
        name = distance.get("name", "distance")
        start = distance.get("from")
        end = distance.get("to")
        if not start or not end:
            lines.append(f"# skipped incomplete distance: {name}")
            continue
        lines.extend(_warnable(f"distance {start} {end}", f"Distance: {name}"))
        style_parts = [f"distance style {start} {end}"]
        if distance.get("color"):
            style_parts.extend(["color", str(distance["color"])])
        if distance.get("radius") is not None:
            style_parts.extend(["radius", str(distance["radius"])])
        if distance.get("dashes") is not None:
            style_parts.extend(["dashes", str(distance["dashes"])])
        lines.extend(_warnable(" ".join(style_parts)))
        lines.append("")

    for label in _ensure_list(config, "labels"):
        selection = label.get("selection")
        text = label.get("text")
        if not selection or text is None:
            lines.append("# skipped incomplete label")
            continue
        parts = [
            f"label {selection}",
            f"text {json.dumps(str(text))}",
            f"height {label.get('height', 1.8)}",
            f"color {label.get('color', 'white')}",
            f"bgColor {label.get('bgColor', '#333333')}",
        ]
        if label.get("offset"):
            parts.append(f"offset {label['offset']}")
        lines.extend(_warnable(" ".join(parts), f"Label: {text}"))
    lines.append("")

    lines.extend(_warnable(f"set bgColor {view.get('background', 'white')}", "Global publication style"))
    if view.get("silhouettes", True):
        lines.extend(
            _warnable(
                f"graphics silhouettes true width {view.get('silhouette_width', 1.5)}"
            )
        )
    if view.get("lighting"):
        lines.extend(_warnable(f"lighting {view['lighting']}"))
    if view.get("orient", True):
        lines.extend(_warnable("view orient"))
    for turn in view.get("turns", []):
        if isinstance(turn, dict) and turn.get("axis") and turn.get("angle") is not None:
            lines.extend(_warnable(f"turn {turn['axis']} {turn['angle']}"))
    if view.get("focus"):
        lines.extend(_warnable(f"view {view['focus']}"))
    if view.get("zoom") is not None:
        lines.extend(_warnable(f"zoom {view['zoom']}"))
    lines.append("")

    save_cmd = (
        f"save {str(image_path).replace(os.sep, '/')} "
        f"width {view.get('width', 1920)} "
        f"height {view.get('height', 1080)} "
        f"transparentBackground {str(bool(view.get('transparentBackground', False))).lower()} "
        f"supersample {view.get('supersample', 3)}"
    )
    lines.extend(_warnable(save_cmd, "Save high-resolution render."))
    lines.append("")
    lines.append(f"with open({_py_string(str(warnings_path))}, 'w', encoding='utf-8') as handle:")
    lines.append("    if WARNINGS:")
    lines.append("        handle.write('\\n'.join(WARNINGS) + '\\n')")
    lines.append("    else:")
    lines.append("        handle.write('No ChimeraX command warnings.\\n')")
    if view.get("quit_after_save", False):
        lines.append("r('quit')")
    lines.append("")
    return lines


def write_template(args: argparse.Namespace) -> int:
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        json.dump(DEFAULT_TEMPLATE, handle, indent=2)
        handle.write("\n")
    print(f"Success! Template written to: {output}")
    return 0


def write_script(args: argparse.Namespace) -> int:
    config_path = Path(args.config).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    config = _read_json(config_path)
    _validate_config(config, config_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    script_name = config.get("output", {}).get("script_name", "render_ppi.py")
    script_path = output_dir / script_name
    warnings_name = config.get("output", {}).get("warnings_name", "render_ppi_warnings.txt")
    warnings_path = output_dir / warnings_name

    lines = _script_lines(config, config_path, output_dir)
    script_path.write_text("\n".join(lines), encoding="utf-8")
    warnings_path.write_text("Script generated; ChimeraX has not been run yet.\n", encoding="utf-8")

    print(f"Success! ChimeraX script written to: {script_path}")
    print(f"Warnings file initialized at: {warnings_path}")
    return 0


def render_script(args: argparse.Namespace) -> int:
    script_path = Path(args.script).expanduser().resolve()
    if not script_path.exists():
        raise ConfigError(f"ChimeraX script not found: {script_path}")

    chimerax = args.chimerax or shutil.which("chimerax")
    if chimerax and not Path(chimerax).expanduser().exists():
        chimerax = shutil.which(chimerax)
    if not chimerax:
        print("ChimeraX executable not found; script generation is still complete.")
        return 0

    cmd = [chimerax, "--offscreen", "--script", str(script_path)]
    if args.output:
        print(f"Rendering with ChimeraX; expected image: {Path(args.output).expanduser()}")
    else:
        print("Rendering with ChimeraX.")
    try:
        completed = subprocess.run(cmd, check=False)
    except FileNotFoundError:
        print("ChimeraX executable not found; script generation is still complete.")
        return 0
    if completed.returncode != 0:
        raise ConfigError(f"ChimeraX exited with code {completed.returncode}: {' '.join(cmd)}")
    print("Success! ChimeraX render completed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate publication-style ChimeraX scripts for protein-protein docking complexes."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    template = subparsers.add_parser("template", help="Write an editable JSON config template.")
    template.add_argument("--output", required=True, help="Path for the JSON template.")
    template.set_defaults(func=write_template)

    script = subparsers.add_parser("script", help="Generate a ChimeraX Python script from a JSON config.")
    script.add_argument("--config", required=True, help="Explicit protein-protein visualization config.")
    script.add_argument("--output-dir", required=True, help="Directory for generated scripts and warnings.")
    script.set_defaults(func=write_script)

    render = subparsers.add_parser("render", help="Run a generated ChimeraX script with --offscreen.")
    render.add_argument("--script", required=True, help="Generated ChimeraX Python script.")
    render.add_argument("--output", help="Expected image path for status reporting.")
    render.add_argument("--chimerax", help="Path to ChimeraX executable; defaults to PATH lookup.")
    render.set_defaults(func=render_script)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
