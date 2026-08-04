#!/usr/bin/env python3
"""Create and validate a strict, file-based docking-to-MD handoff."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

SYSTEM_TYPES = ("protein-ligand", "protein-protein", "protein-only")
FORCE_FIELD_FAMILIES = {
    "amber-gaff": "amber",
    "charmm-cgenff": "charmm",
}


class HandoffError(ValueError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HandoffError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise HandoffError(f"{path} must contain a JSON object")
    return data


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def existing_file(path_value: str | None, label: str) -> dict[str, str]:
    if not path_value:
        raise HandoffError(f"{label} is required")
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise HandoffError(f"{label} does not exist: {path}")
    return {"path": str(path), "sha256": sha256(path)}


def verify_file_reference(reference: Any, label: str) -> str | None:
    if not isinstance(reference, dict) or not isinstance(reference.get("path"), str) or not isinstance(reference.get("sha256"), str):
        return f"{label} reference is incomplete"
    path = Path(reference["path"]).expanduser()
    if not path.is_file():
        return f"{label} file is missing: {path}"
    if sha256(path) != reference["sha256"]:
        return f"{label} hash does not match"
    return None


def validated_environment_receipt(path_value: str) -> dict[str, str]:
    reference = existing_file(path_value, "environment receipt")
    try:
        receipt = read_json(Path(reference["path"]))
        created_at = dt.datetime.fromisoformat(receipt["created_at"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise HandoffError("Environment receipt is invalid; rerun environment verify.") from exc
    if receipt.get("artifact_type") != "molecular_modeling_environment_receipt" or receipt.get("schema_version") != "1.1" or receipt.get("ready") is not True:
        raise HandoffError("Environment receipt is not ready; resolve its warnings before creating the handoff.")
    if dt.datetime.now(dt.timezone.utc) - created_at.astimezone(dt.timezone.utc) > dt.timedelta(days=7):
        raise HandoffError("Environment receipt is older than seven days; rerun environment verify.")
    return {**reference, "profile": receipt.get("profile")}


def selected_pose(poses: dict[str, Any], pose_id: str) -> dict[str, Any]:
    candidates = poses.get("poses") or poses.get("ranked_poses")
    if not isinstance(candidates, list):
        raise HandoffError("ranked poses must contain a poses array")
    for pose in candidates:
        if isinstance(pose, dict) and pose.get("pose_id") == pose_id:
            return pose
    raise HandoffError(f"Pose {pose_id!r} is not present in ranked poses")


def selected_coordinate_reference(pose: dict[str, Any]) -> dict[str, Any]:
    reference = pose.get("coordinate_file")
    if not isinstance(reference, dict):
        raise HandoffError("Selected pose requires a hash-bound individual coordinate_file.")
    failure = verify_file_reference(reference, "selected pose coordinate_file")
    if failure:
        raise HandoffError(failure)
    path = Path(reference["path"]).expanduser().resolve()
    return {**reference, "path": str(path)}


def ligand_parameterization(path: Path) -> dict[str, Any]:
    data = read_json(path)
    required = ("ligand_identity", "net_charge", "topology", "coordinates", "validation")
    missing = [field for field in required if field not in data or data[field] is None or data[field] == ""]
    if missing:
        raise HandoffError(f"Parameterization is missing: {', '.join(missing)}")
    validation = data["validation"]
    if not isinstance(validation, dict) or validation.get("status") != "validated":
        raise HandoffError("Ligand parameterization validation.status must be 'validated'")
    for field in ("topology", "coordinates"):
        value = data[field]
        if not isinstance(value, str):
            raise HandoffError(f"Parameterization {field} must be a file path")
        existing_file(value, f"parameterization.{field}")
    return data


def pdbqt_atom_names(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise HandoffError(f"Cannot read selected pose PDBQT {path}: {exc}") from exc
    names: list[str] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.startswith(("ATOM", "HETATM")):
            continue
        if len(line) >= 16:
            name = line[12:16].strip()
        else:
            fields = line.split()
            name = fields[2] if len(fields) >= 3 else ""
        if not name:
            raise HandoffError(f"Selected pose PDBQT has a missing atom name at line {line_number}")
        names.append(name)
    if not names:
        raise HandoffError("Selected pose PDBQT contains no ATOM/HETATM records")
    duplicates = {name: count for name, count in Counter(names).items() if count > 1}
    if duplicates:
        details = ", ".join(f"{name} ({count} occurrences)" for name, count in sorted(duplicates.items()))
        raise HandoffError(
            f"Selected pose PDBQT contains duplicate docking atom names: {details}. "
            "Regenerate the ligand PDBQT with unique, stable atom names before docking and rerun docking; "
            "atom mappings for symmetric ligands must not be inferred or reordered."
        )
    return names


def gro_atom_names(path: Path) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise HandoffError(f"Cannot read ligand GRO coordinates {path}: {exc}") from exc
    if len(lines) < 3:
        raise HandoffError("Ligand GRO coordinates are incomplete")
    try:
        count = int(lines[1].strip())
    except ValueError as exc:
        raise HandoffError("Ligand GRO atom count is invalid") from exc
    if count < 1 or len(lines) < count + 3:
        raise HandoffError("Ligand GRO atom records are incomplete")
    names: list[str] = []
    for index, line in enumerate(lines[2 : 2 + count], start=1):
        name = line[10:15].strip() if len(line) >= 15 else ""
        if not name:
            raise HandoffError(f"Ligand GRO has a missing atom name at atom record {index}")
        names.append(name)
    return names


def alignment_admission(pose_path: Path, ligand_gro_path: Path) -> dict[str, Any]:
    pose_names = set(pdbqt_atom_names(pose_path))
    gro_names = list(dict.fromkeys(gro_atom_names(ligand_gro_path)))
    shared = [name for name in gro_names if name in pose_names and not name.upper().startswith("H")]
    if len(shared) < 3:
        raise HandoffError(
            f"Pose-to-ligand alignment requires at least three shared non-hydrogen atom names; found {len(shared)}: "
            f"{', '.join(shared) if shared else 'none'}. Regenerate the ligand PDBQT with unique, stable names "
            "matching the validated ligand GRO before docking; do not infer or reorder atom mappings."
        )
    return {
        "status": "validated",
        "shared_non_hydrogen_atom_names": shared,
        "shared_non_hydrogen_atom_count": len(shared),
        "minimum_required": 3,
    }


def create(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = Path(args.docking_manifest).expanduser().resolve()
    poses_path = Path(args.ranked_poses).expanduser().resolve()
    manifest = read_json(manifest_path)
    poses = read_json(poses_path)
    environment = validated_environment_receipt(args.environment_receipt)
    pose = selected_pose(poses, args.pose_id)
    pose_ref = selected_coordinate_reference(pose)
    source_hashes = {"docking_manifest": sha256(manifest_path), "ranked_poses": sha256(poses_path), "selected_pose": pose_ref["sha256"]}
    ligand: dict[str, Any]
    if args.system_type == "protein-ligand":
        if not args.parameterization:
            raise HandoffError("--parameterization is required for protein-ligand MD")
        parameterization_path = Path(args.parameterization).expanduser().resolve()
        parameterization = ligand_parameterization(parameterization_path)
        parameter_force_field = parameterization.get("force_field")
        parameter_family = FORCE_FIELD_FAMILIES.get(parameter_force_field)
        if not parameter_family:
            raise HandoffError("Parameterization force_field must be amber-gaff or charmm-cgenff")
        if not args.protein_force_field:
            raise HandoffError("--protein-force-field is required for protein-ligand MD")
        protein_family = args.protein_force_field.strip().lower().split()[0]
        if not protein_family.startswith(parameter_family):
            raise HandoffError(f"Force-field family mismatch: ligand {parameter_force_field} requires a {parameter_family}-family protein force field")
        source_hashes["parameterization"] = sha256(parameterization_path)
        topology_ref = existing_file(parameterization["topology"], "parameterization.topology")
        coordinates_ref = existing_file(parameterization["coordinates"], "parameterization.coordinates")
        admission = alignment_admission(Path(pose_ref["path"]), Path(coordinates_ref["path"]))
        ligand = {
            "applicable": True,
            "identity": parameterization["ligand_identity"],
            "net_charge": parameterization["net_charge"],
            "force_field": parameter_force_field,
            "force_field_family": parameter_family,
            "protein_force_field": args.protein_force_field,
            "topology": topology_ref,
            "coordinates": coordinates_ref,
            "parameterization_provenance": parameterization.get("provenance", {}),
            "validation": parameterization["validation"],
            "alignment_admission": admission,
        }
    else:
        ligand = {"applicable": False, "reason": "not applicable to protein-only/PPI workflow"}
    receptor = manifest.get("receptor") or manifest.get("inputs", {}).get("receptor")
    if not receptor:
        raise HandoffError("docking manifest must identify the receptor input")
    return {
        "schema_version": "1.0",
        "artifact_type": "docking_to_md_handoff",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "system_type": args.system_type,
        "selection": {"pose_id": args.pose_id, "rationale": args.rationale, "selected_pose": pose, "coordinates": pose_ref},
        "receptor": receptor,
        "environment_receipt": environment,
        "ligand": ligand,
        "source": {"docking_manifest": str(manifest_path), "ranked_poses": str(poses_path), "hashes": source_hashes},
        "validation": {"status": "validated", "checks": ["selected pose exists", "source hashes recorded", "ligand topology and coordinates validated" if ligand["applicable"] else "ligand fields not applicable", f"pose-to-ligand named-atom alignment admitted ({ligand['alignment_admission']['shared_non_hydrogen_atom_count']} shared non-hydrogen atom names)" if ligand["applicable"] else "pose-to-ligand alignment not applicable", "force-field families are compatible" if ligand["applicable"] else "force-field family not applicable"], "unresolved_warnings": args.warning or []},
        "scientific_interpretation": {"docking_score": "A docking-engine ranking output, not experimental affinity or binding free energy.", "post_md_free_energy": "Not computed by this handoff."},
    }


def validate(data: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if data.get("artifact_type") != "docking_to_md_handoff": failures.append("artifact_type must be docking_to_md_handoff")
    system_type = data.get("system_type")
    if system_type not in SYSTEM_TYPES: failures.append("system_type is invalid")
    if data.get("validation", {}).get("status") != "validated": failures.append("validation.status must be validated")
    source = data.get("source", {})
    if not isinstance(source.get("hashes"), dict): failures.append("source hashes are required")
    else:
        for label, path_key in (("docking_manifest", "docking_manifest"), ("ranked_poses", "ranked_poses")):
            path_value = source.get(path_key)
            expected = source["hashes"].get(label)
            if not isinstance(path_value, str) or not isinstance(expected, str): failures.append(f"source {label} reference is incomplete")
            elif not Path(path_value).is_file(): failures.append(f"source {label} file is missing: {path_value}")
            elif sha256(Path(path_value)) != expected: failures.append(f"source {label} hash does not match")
    selected = data.get("selection", {}).get("coordinates")
    failure = verify_file_reference(selected, "selected pose")
    selected_path: Path | None = None
    if failure: failures.append(failure)
    elif isinstance(selected, dict): selected_path = Path(selected["path"]).expanduser()
    environment = data.get("environment_receipt")
    failure = verify_file_reference(environment, "environment receipt")
    if failure: failures.append(failure)
    elif isinstance(environment, dict):
        try:
            receipt = read_json(Path(environment["path"]))
            created_at = dt.datetime.fromisoformat(receipt["created_at"].replace("Z", "+00:00"))
            if receipt.get("artifact_type") != "molecular_modeling_environment_receipt" or receipt.get("schema_version") != "1.1" or receipt.get("ready") is not True: failures.append("environment receipt is not ready")
            elif dt.datetime.now(dt.timezone.utc) - created_at.astimezone(dt.timezone.utc) > dt.timedelta(days=7): failures.append("environment receipt is older than seven days")
        except (KeyError, TypeError, ValueError): failures.append("environment receipt is invalid")
    ligand = data.get("ligand", {})
    if system_type == "protein-ligand":
        if not ligand.get("applicable"): failures.append("ligand must be applicable")
        if ligand.get("validation", {}).get("status") != "validated": failures.append("ligand parameterization is not validated")
        valid_ligand_references: dict[str, Path] = {}
        for field in ("topology", "coordinates"):
            reference = ligand.get(field, {})
            failure = verify_file_reference(reference, f"ligand.{field}")
            if failure: failures.append(failure)
            elif isinstance(reference, dict): valid_ligand_references[field] = Path(reference["path"]).expanduser()
        if ligand.get("force_field_family") not in {"amber", "charmm"}: failures.append("ligand force-field family is invalid")
        if not isinstance(ligand.get("protein_force_field"), str) or not ligand["protein_force_field"].strip(): failures.append("protein force field is required")
        recorded_admission = ligand.get("alignment_admission")
        if not isinstance(recorded_admission, dict):
            failures.append("ligand.alignment_admission is required for protein-ligand handoffs; recreate this legacy handoff")
        if selected_path is not None and "coordinates" in valid_ligand_references:
            try:
                checked_admission = alignment_admission(selected_path, valid_ligand_references["coordinates"])
            except HandoffError as exc:
                failures.append(f"pose-to-ligand alignment admission failed: {exc}")
            else:
                if isinstance(recorded_admission, dict) and recorded_admission != checked_admission:
                    failures.append("ligand.alignment_admission does not match the checked pose/GRO atom-name mapping")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create"); p.add_argument("--docking-manifest", required=True); p.add_argument("--ranked-poses", required=True); p.add_argument("--pose-id", required=True); p.add_argument("--system-type", choices=SYSTEM_TYPES, required=True); p.add_argument("--parameterization"); p.add_argument("--environment-receipt", required=True); p.add_argument("--protein-force-field"); p.add_argument("--rationale", required=True); p.add_argument("--warning", action="append"); p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("validate"); p.add_argument("--handoff", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "create": data = create(args); failures: list[str] = []
        else: data = read_json(args.handoff); failures = validate(data)
        result = {"valid": not failures, "failures": failures, "handoff": data}
        args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(data if args.command == "create" else result, indent=2) + "\n", encoding="utf-8")
    except HandoffError as exc:
        print(f"Error: {exc}", file=sys.stderr); raise SystemExit(1)
    print(f"Success! Data written to: {args.output}")
    if failures: raise SystemExit(1)


if __name__ == "__main__": main()
