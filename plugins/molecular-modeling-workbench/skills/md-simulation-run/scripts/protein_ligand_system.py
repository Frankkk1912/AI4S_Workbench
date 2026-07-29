#!/usr/bin/env python3
"""Create auditable plans and reviewed protein records for ligand MD assembly."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


class PreparationError(ValueError):
    pass


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreparationError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PreparationError(f"{path} must contain a JSON object.")
    return data


def hashf(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reference(path: Path) -> dict[str, str]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file() or resolved.stat().st_size == 0:
        raise PreparationError(f"Required nonempty file is missing: {resolved}")
    return {"path": str(resolved), "sha256": hashf(resolved)}


def verify_reference(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str) or not isinstance(value.get("sha256"), str):
        raise PreparationError(f"{label} reference is incomplete.")
    actual = reference(Path(value["path"]))
    if actual["sha256"] != value["sha256"]:
        raise PreparationError(f"{label} hash does not match.")
    return actual


def payload_hash(data: dict[str, Any], key: str) -> str:
    payload = {name: value for name, value in data.items() if name != key}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def validate_receipt(path: Path) -> dict[str, str]:
    receipt = load(path)
    if receipt.get("schema_version") != "1.1" or receipt.get("artifact_type") != "molecular_modeling_environment_receipt":
        raise PreparationError("Environment receipt schema is unsupported.")
    if receipt.get("profile") != "wsl2-gpu" or receipt.get("ready") is not True:
        raise PreparationError("Preparation requires a ready wsl2-gpu environment receipt.")
    try:
        created = dt.datetime.fromisoformat(str(receipt["created_at"]).replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise PreparationError("Environment receipt has no valid created_at timestamp.") from exc
    if dt.datetime.now(dt.timezone.utc) - created.astimezone(dt.timezone.utc) > dt.timedelta(days=7):
        raise PreparationError("Environment receipt is older than seven days.")
    container = receipt.get("report", {}).get("gromacs_container", {})
    if not isinstance(container, dict) or container.get("available") is not True or not isinstance(container.get("digest"), str) or "@sha256:" not in container["digest"]:
        raise PreparationError("Environment receipt lacks a verified GROMACS container digest.")
    return reference(path)


def validate_termini(path: Path) -> dict[str, str]:
    data = load(path)
    chains = data.get("chains")
    if data.get("artifact_type") != "protein_termini_record" or data.get("schema_version") != "1.0" or not isinstance(chains, list) or not chains:
        raise PreparationError("Terminal-state record is invalid.")
    for chain in chains:
        if not isinstance(chain, dict) or not all(isinstance(chain.get(key), str) and chain[key].strip() for key in ("chain_id", "n_terminus", "c_terminus")):
            raise PreparationError("Terminal-state record requires nonempty chain_id, n_terminus, and c_terminus values.")
    return reference(path)


def validate_handoff(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    handoff = load(path)
    if handoff.get("artifact_type") != "docking_to_md_handoff" or handoff.get("system_type") != "protein-ligand" or handoff.get("validation", {}).get("status") != "validated":
        raise PreparationError("A validated protein-ligand MD handoff is required.")
    ligand = handoff.get("ligand", {})
    if ligand.get("validation", {}).get("status") != "validated" or ligand.get("force_field") != "amber-gaff" or not str(ligand.get("protein_force_field", "")).lower().startswith("amber"):
        raise PreparationError("Preparation supports only validated amber-gaff ligand with an AMBER-family protein force field.")
    refs = {
        "handoff": reference(path),
        "selected_pose": verify_reference(handoff.get("selection", {}).get("coordinates"), "selected pose"),
        "ligand_topology": verify_reference(ligand.get("topology"), "ligand topology"),
        "ligand_coordinates": verify_reference(ligand.get("coordinates"), "ligand coordinates"),
    }
    return handoff, refs


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    if args.water_model != "tip3p" or args.box_shape != "dodecahedron":
        raise PreparationError("v0.1 preparation supports only tip3p water in a dodecahedron box.")
    if not 0 < args.box_distance_nm <= 2.0:
        raise PreparationError("--box-distance-nm must be greater than 0 and no more than 2.0.")
    if not 0 <= args.salt_molar <= 1.0:
        raise PreparationError("--salt-molar must be between 0 and 1.0.")
    handoff, inputs = validate_handoff(args.handoff)
    inputs["environment_receipt"] = validate_receipt(args.environment_receipt)
    inputs["receptor_pdb"] = reference(args.receptor_pdb)
    inputs["termini_record"] = validate_termini(args.termini_record)
    plan: dict[str, Any] = {
        "schema_version": "1.0",
        "artifact_type": "protein_ligand_system_preparation_plan",
        "created_at": now(),
        "inputs": inputs,
        "force_fields": {"protein": handoff["ligand"]["protein_force_field"], "ligand": handoff["ligand"]["force_field"]},
        "parameters": {"water_model": args.water_model, "box_shape": args.box_shape, "box_distance_nm": args.box_distance_nm, "salt_molar": args.salt_molar},
        "execution": {"status": "awaiting_reviewed_protein_preparation", "policy": "No free-form shell commands; assembly is deferred to a later plan-derived command stage."},
    }
    plan["plan_sha256"] = payload_hash(plan, "plan_sha256")
    return plan


def read_plan(path: Path) -> dict[str, Any]:
    plan = load(path)
    if plan.get("artifact_type") != "protein_ligand_system_preparation_plan" or plan.get("schema_version") != "1.0" or plan.get("plan_sha256") != payload_hash(plan, "plan_sha256"):
        raise PreparationError("System preparation plan is invalid or has been modified.")
    inputs = plan.get("inputs", {})
    if not isinstance(inputs, dict):
        raise PreparationError("System preparation plan inputs are missing.")
    for label in ("handoff", "selected_pose", "ligand_topology", "ligand_coordinates", "environment_receipt", "receptor_pdb", "termini_record"):
        verify_reference(inputs.get(label), label.replace("_", " "))
    return plan


def prepare_protein(args: argparse.Namespace) -> dict[str, Any]:
    plan = read_plan(args.plan)
    return {
        "schema_version": "1.0",
        "artifact_type": "reviewed_protein_preparation",
        "created_at": now(),
        "plan": reference(args.plan),
        "protein_topology": reference(args.protein_topology),
        "protein_coordinates": reference(args.protein_coordinates),
        "termini_record": plan["inputs"]["termini_record"],
        "status": "reviewed",
        "scope": "Records user-reviewed pdb2gmx outputs; it does not itself infer terminal states or execute GROMACS.",
    }


def write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--handoff", type=Path, required=True)
    plan.add_argument("--environment-receipt", type=Path, required=True)
    plan.add_argument("--receptor-pdb", type=Path, required=True)
    plan.add_argument("--termini-record", type=Path, required=True)
    plan.add_argument("--water-model", required=True)
    plan.add_argument("--box-shape", required=True)
    plan.add_argument("--box-distance-nm", type=float, required=True)
    plan.add_argument("--salt-molar", type=float, required=True)
    plan.add_argument("--output", type=Path, required=True)
    protein = sub.add_parser("prepare-protein")
    protein.add_argument("--plan", type=Path, required=True)
    protein.add_argument("--protein-topology", type=Path, required=True)
    protein.add_argument("--protein-coordinates", type=Path, required=True)
    protein.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        data = build_plan(args) if args.command == "plan" else prepare_protein(args)
        write(args.output, data)
    except PreparationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Success! Data written to: {args.output}")


if __name__ == "__main__":
    main()
