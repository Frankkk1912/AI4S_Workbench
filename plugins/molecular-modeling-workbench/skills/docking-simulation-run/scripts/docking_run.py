#!/usr/bin/env python3
"""GNINA/Vina runner with a normalized, auditable result contract."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


class DockingError(ValueError):
    pass


def stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise DockingError(f"Cannot read {path}: {e}") from e


def validate_environment_receipt(
    receipt: dict[str, Any], profile: str, engine: str
) -> None:
    if (
        receipt.get("artifact_type") != "molecular_modeling_environment_receipt"
        or receipt.get("schema_version") != "1.1"
    ):
        raise DockingError(
            "Environment receipt schema is unsupported; rerun environment verify."
        )
    if receipt.get("profile") != profile:
        raise DockingError("Environment receipt profile does not match --profile.")
    ready = receipt.get("ready")
    if not isinstance(ready, bool) or not ready:
        raise DockingError(
            "Environment receipt is not ready; resolve its warnings before docking."
        )
    try:
        created_at = dt.datetime.fromisoformat(
            receipt["created_at"].replace("Z", "+00:00")
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DockingError(
            "Environment receipt has no valid created_at timestamp."
        ) from exc
    if dt.datetime.now(dt.timezone.utc) - created_at.astimezone(
        dt.timezone.utc
    ) > dt.timedelta(days=7):
        raise DockingError(
            "Environment receipt is older than seven days; rerun environment verify."
        )
    tools = receipt.get("report", {}).get("tools", {})
    if engine and not tools.get(engine, {}).get("available"):
        raise DockingError(f"Environment receipt does not verify {engine}.")


def receipt_executable(receipt: dict[str, Any], engine: str) -> str:
    """Return the exact executable that the verified receipt recorded.

    A later PATH lookup could select a different binary than the audited one,
    especially after a user-space package-manager install.  Require an
    absolute, currently executable path instead.
    """
    record = receipt.get("report", {}).get("tools", {}).get(engine, {})
    raw_path = record.get("path")
    if not record.get("available") or not isinstance(raw_path, str):
        raise DockingError(f"Environment receipt does not verify {engine}.")
    executable = Path(raw_path)
    try:
        valid = (
            executable.is_absolute()
            and executable.is_file()
            and os.access(executable, os.X_OK)
        )
    except OSError:
        valid = False
    if not valid:
        raise DockingError(
            f"Environment receipt does not contain a verified absolute executable path for {engine}; rerun environment verify."
        )
    return str(executable.resolve())


def parse_vector(value: str, name: str) -> list[float]:
    try:
        vals = [float(v) for v in value.split(",")]
    except ValueError as e:
        raise DockingError(f"{name} must be x,y,z") from e
    if len(vals) != 3:
        raise DockingError(f"{name} must contain three numbers")
    if name == "size" and any(v <= 0 for v in vals):
        raise DockingError(f"{name} must contain three positive numbers")
    return vals


def optional_float(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


def engine_command(
    engine: str,
    receptor: Path,
    ligand: Path,
    center: list[float],
    size: list[float],
    seed: int,
    out: Path,
) -> list[str]:
    if engine == "gnina":
        return [
            "gnina",
            "-r",
            str(receptor),
            "-l",
            str(ligand),
            "--center_x",
            str(center[0]),
            "--center_y",
            str(center[1]),
            "--center_z",
            str(center[2]),
            "--size_x",
            str(size[0]),
            "--size_y",
            str(size[1]),
            "--size_z",
            str(size[2]),
            "--seed",
            str(seed),
            "-o",
            str(out),
        ]
    return [
        "vina",
        "--receptor",
        str(receptor),
        "--ligand",
        str(ligand),
        "--center_x",
        str(center[0]),
        "--center_y",
        str(center[1]),
        "--center_z",
        str(center[2]),
        "--size_x",
        str(size[0]),
        "--size_y",
        str(size[1]),
        "--size_z",
        str(size[2]),
        "--seed",
        str(seed),
        "--out",
        str(out),
    ]


def make_pose(
    engine: str,
    rank: int,
    affinity: float,
    source_file: Path,
    score_source: str,
) -> dict[str, Any]:
    score_key = (
        "vina_affinity_kcal_mol" if engine == "vina" else "gnina_vina_affinity_kcal_mol"
    )
    return {
        "pose_id": f"pose_{rank:03d}",
        "rank": rank,
        "source_file": str(source_file.resolve()),
        "score_source": score_source,
        "scores": {score_key: affinity},
        "confidence": {},
    }


def parse_poses_from_pdbqt(engine: str, path: Path) -> list[dict[str, Any]]:
    """Primary parser: per-pose REMARK records inside the output PDBQT."""
    poses: list[dict[str, Any]] = []
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("REMARK VINA RESULT:"):
            parts = line.split()
            try:
                score = float(parts[3])
            except (IndexError, ValueError):
                continue
            poses.append(make_pose(engine, len(poses) + 1, score, path, "pdbqt_remark"))
        elif engine == "gnina" and line.startswith("REMARK minimizedAffinity"):
            try:
                score = float(line.split()[-1])
            except ValueError:
                continue
            poses.append(make_pose(engine, len(poses) + 1, score, path, "pdbqt_remark"))
        elif engine == "gnina" and poses and line.startswith("REMARK CNNscore"):
            parts = line.split()
            score = optional_float(parts[-1] if parts else None)
            if score is not None:
                poses[-1]["scores"]["gnina_cnn_score"] = score
        elif engine == "gnina" and poses and line.startswith("REMARK CNNaffinity"):
            parts = line.split()
            affinity = optional_float(parts[-1] if parts else None)
            if affinity is not None:
                poses[-1]["scores"]["gnina_cnn_affinity_kcal_mol"] = affinity
    return poses


# mode | affinity | rmsd l.b. | rmsd u.b.        (vina table)
# mode | affinity | CNNscore   | CNNaffinity      (gnina table)
_TABLE_ROW = re.compile(
    r"^\s*(\d+)\s+(-?\d+(?:\.\d+)?)(?:\s+(-?\d+(?:\.\d+)?))?(?:\s+(-?\d+(?:\.\d+)?))?\s*$"
)
_MINIMIZED_AFFINITY = re.compile(r"minimizedAffinity:\s*(-?\d+(?:\.\d+)?)")


def parse_poses_from_log(engine: str, log_path: Path) -> list[dict[str, Any]]:
    """Fallback parser: recover ranked scores from the engine's stdout table.

    Used when the PDBQT lacks parseable REMARK records (engine version drift,
    truncated output). Scores are identical to the REMARK values; only the
    provenance flag differs.
    """
    lines = log_path.read_text(errors="replace").splitlines()
    poses: list[dict[str, Any]] = []
    in_table = False
    for line in lines:
        if line.startswith("-----"):
            in_table = True
            continue
        if in_table:
            if not line.strip():
                in_table = False
                continue
            match = _TABLE_ROW.match(line)
            if not match:
                continue
            affinity = optional_float(match.group(2))
            if affinity is None:
                continue
            pose = make_pose(
                engine, len(poses) + 1, affinity, log_path, "engine_log_table"
            )
            if engine == "gnina" and match.group(3) and match.group(4):
                cnn_score = optional_float(match.group(3))
                cnn_affinity = optional_float(match.group(4))
                if cnn_score is not None and cnn_affinity is not None:
                    pose["scores"]["gnina_cnn_score"] = cnn_score
                    pose["scores"]["gnina_cnn_affinity_kcal_mol"] = cnn_affinity
            poses.append(pose)
    if poses:
        return poses
    if engine == "gnina":
        # Last resort: per-pose "minimizedAffinity:" lines from verbose GNINA logs.
        affinities = []
        for line in lines:
            match = _MINIMIZED_AFFINITY.search(line)
            if not match:
                continue
            affinity = optional_float(match.group(1))
            if affinity is not None:
                affinities.append(affinity)
        poses = [
            make_pose(engine, i + 1, score, log_path, "gnina_minimized_affinity")
            for i, score in enumerate(affinities)
        ]
    return poses


def parse_scores(
    engine: str, path: Path, log_path: Path | None = None
) -> list[dict[str, Any]]:
    poses = parse_poses_from_pdbqt(engine, path) if path.is_file() else []
    if not poses and log_path is not None and log_path.is_file():
        poses = parse_poses_from_log(engine, log_path)
    return poses


def export_pose_coordinates(
    source: Path, poses: list[dict[str, Any]], output_dir: Path
) -> None:
    """Write one hash-bound PDBQT file per ranked pose.

    A docking output with multiple MODEL blocks is not a safe MD coordinate
    reference until the selected model has its own immutable file.
    """
    if not poses:
        return
    text = source.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    models: list[str] = []
    current: list[str] | None = None
    for line in lines:
        if line.startswith("MODEL"):
            if current is not None:
                raise DockingError("Docking PDBQT contains a nested MODEL block.")
            current = [line]
        elif current is not None:
            current.append(line)
            if line.startswith("ENDMDL"):
                models.append("".join(current))
                current = None
    if current is not None:
        raise DockingError("Docking PDBQT has a MODEL block without ENDMDL.")
    if not models:
        if len(poses) != 1:
            raise DockingError(
                "Docking output has multiple ranked poses but no MODEL blocks."
            )
        models = [text]
    if len(models) != len(poses):
        raise DockingError("Docking MODEL count does not match the ranked-pose count.")
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, (pose, model) in enumerate(zip(poses, models, strict=True), start=1):
        path = output_dir / f"pose_{index:03d}.pdbqt"
        path.write_text(model, encoding="utf-8")
        pose["coordinate_file"] = {
            "path": str(path.resolve()),
            "sha256": digest(path),
            "format": "pdbqt",
        }


def run_engine(
    engine: str,
    executable: str,
    args: argparse.Namespace,
    center: list[float],
    size: list[float],
    outdir: Path,
) -> dict[str, Any]:
    raw = outdir / f"{engine}_poses.pdbqt"
    log_path = outdir / f"{engine}.log"
    command = engine_command(
        engine,
        Path(args.receptor).resolve(),
        Path(args.ligand).resolve(),
        center,
        size,
        args.seed,
        raw,
    )
    command[0] = executable
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    log_path.write_text(
        result.stdout + "\n--- STDERR ---\n" + result.stderr, encoding="utf-8"
    )
    poses = parse_scores(engine, raw, log_path) if result.returncode == 0 else []
    reason = None
    if poses:
        try:
            export_pose_coordinates(raw, poses, outdir / "individual-poses")
        except DockingError as exc:
            poses = []
            reason = str(exc)
    return {
        "engine": engine,
        "status": "completed" if poses else "failed",
        "returncode": result.returncode,
        "command": command,
        "raw_output": str(raw.resolve()),
        "poses": poses,
        "reason": None if poses else reason or "No valid pose output was produced.",
    }


def backend_fallback_reason(
    runs: list[dict[str, Any]], successful: dict[str, Any] | None
) -> str | None:
    if successful is None:
        return None
    return next(
        (
            str(run["reason"])
            for run in runs
            if run["status"] != "completed" and run.get("reason")
        ),
        None,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--backend", choices=("auto", "gnina", "vina"), required=True)
    run.add_argument(
        "--profile", choices=("wsl2-gpu", "linux-gpu", "cpu-fallback"), required=True
    )
    run.add_argument("--receptor", required=True)
    run.add_argument("--ligand", required=True)
    run.add_argument("--center", required=True)
    run.add_argument("--size", required=True)
    run.add_argument("--seed", type=int, required=True)
    run.add_argument("--environment-receipt", required=True)
    run.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    receptor = Path(args.receptor).resolve()
    ligand = Path(args.ligand).resolve()
    try:
        if not receptor.is_file() or not ligand.is_file():
            raise DockingError("Receptor and ligand input files are required")
        receipt = read_json(Path(args.environment_receipt))
        center = parse_vector(args.center, "center")
        size = parse_vector(args.size, "size")
        args.output_dir.mkdir(parents=True, exist_ok=True)

        if args.backend == "auto":
            validate_environment_receipt(receipt, args.profile, "")
            try:
                validate_environment_receipt(receipt, args.profile, "gnina")
                route = ["gnina", "vina"]
            except DockingError:
                validate_environment_receipt(receipt, args.profile, "vina")
                route = ["vina"]
        else:
            validate_environment_receipt(receipt, args.profile, args.backend)
            route = [args.backend]
        runs = []
        for engine in route:
            executable = receipt_executable(receipt, engine)
            attempt = run_engine(
                engine, executable, args, center, size, args.output_dir
            )
            runs.append(attempt)
            if attempt["status"] == "completed":
                break
        successful = next((r for r in runs if r["status"] == "completed"), None)

        manifest = {
            "schema_version": "1.0",
            "artifact_type": "docking_manifest",
            "created_at": stamp(),
            "inputs": {
                "receptor": {"path": str(receptor), "sha256": digest(receptor)},
                "ligand": {"path": str(ligand), "sha256": digest(ligand)},
            },
            "receptor": {"path": str(receptor)},
            "engine": successful["engine"] if successful else None,
            "engine_attempts": [
                {k: v for k, v in r.items() if k != "poses"} for r in runs
            ],
            "seed": args.seed,
            "search_box": {"center": center, "size": size},
            "environment_receipt": {
                "path": str(Path(args.environment_receipt).resolve()),
                "ready": receipt.get("ready"),
            },
            "backend_fallback": backend_fallback_reason(runs, successful),
            "warnings": [],
            "timestamps": {"completed_at": stamp()},
        }
        (args.output_dir / "docking_manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        poses_doc = {
            "schema_version": "1.0",
            "artifact_type": "ranked_docking_poses",
            "engine": successful["engine"] if successful else None,
            "poses": successful["poses"] if successful else [],
        }
        (args.output_dir / "ranked_poses.json").write_text(
            json.dumps(poses_doc, indent=2) + "\n", encoding="utf-8"
        )
        (args.output_dir / "docking_report.md").write_text(
            "# Docking report\n\n"
            f"Backend: {manifest['engine'] or 'failed'}\n\n"
            "Docking and CNN values are engine-specific ranking outputs, "
            "not experimental affinities or binding free energies.\n",
            encoding="utf-8",
        )
    except DockingError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1) from e
    print(f"Success! Data written to: {args.output_dir / 'docking_manifest.json'}")
    if not successful:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
