#!/usr/bin/env python3
"""Persistent docking brief, decision-log, and report artifacts."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    init = sub.add_parser("init")
    init.add_argument("--project-name", required=True)
    init.add_argument(
        "--system-type", choices=("protein-ligand", "protein-protein"), required=True
    )
    init.add_argument("--question", required=True)
    init.add_argument("--output-dir", type=Path, required=True)

    decision = sub.add_parser("decision")
    decision.add_argument("--brief", type=Path, required=True)
    decision.add_argument("--decision", required=True)
    decision.add_argument("--reason", required=True)
    decision.add_argument("--output", type=Path, required=True)

    report = sub.add_parser("report")
    report.add_argument("--brief", type=Path, required=True)
    report.add_argument(
        "--artifacts", required=True, help="Comma-separated artifact paths"
    )
    report.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()

    if args.cmd == "init":
        data = {
            "schema_version": "1.0",
            "artifact_type": "docking_project_brief",
            "created_at": now(),
            "project_name": args.project_name,
            "system_type": args.system_type,
            "scientific_question": args.question,
            "structure_sources": [],
            "assumptions": {
                "protonation": [],
                "pocket_basis": [],
                "missing_regions": [],
            },
            "routing": [
                "environment verification",
                "preparation",
                "docking",
                "complex analysis",
                "visualization",
            ],
            "decisions": [],
            "limitations": [
                (
                    "Docking score, CNN score, confidence, and post-MD free-energy "
                    "estimate are distinct quantities."
                )
            ],
        }
        path = args.output_dir / "docking_project_brief.json"
        write(path, data)
    elif args.cmd == "decision":
        data = read(args.brief)
        data.setdefault("decisions", []).append(
            {"at": now(), "decision": args.decision, "reason": args.reason}
        )
        path = args.output
        write(path, data)
    else:
        brief = read(args.brief)
        paths = [
            str(Path(x).expanduser().resolve()) for x in args.artifacts.split(",") if x
        ]
        lines = [
            f"# Docking final report: {brief['project_name']}",
            "",
            f"Generated: {now()}",
            "",
            "## Scope",
            brief["scientific_question"],
            "",
            "## Evidence artifacts",
            *[f"- `{x}`" for x in paths],
            "",
            "## Interpretation boundary",
            (
                "Docking scores and GNINA CNN outputs are model-specific ranking "
                "outputs, not experimental affinities or binding free energies."
            ),
        ]
        path = args.output
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Success! Data written to: {path}")


if __name__ == "__main__":
    main()
