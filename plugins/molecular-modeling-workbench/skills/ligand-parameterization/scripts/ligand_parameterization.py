#!/usr/bin/env python3
"""Auditable ligand parameterization preparation for docking-to-MD handoff."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

FORCE_FIELDS = ("amber-gaff", "charmm-cgenff")
ENGINES = ("acpype", "sobtop", "cgenff")
AUTO_ENGINES = ("acpype",)
HANDOFF_ENGINES = ("sobtop", "cgenff")
DETECT_TOOLS = ("acpype", "antechamber", "obabel", "sobtop", "gmx")
SUPPORTED_LIGAND_SUFFIXES = (".mol2", ".sdf", ".pdb")


class ParameterizationError(ValueError):
    pass


def stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def existing_file(path_value: str, label: str) -> dict[str, str]:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise ParameterizationError(f"{label} does not exist: {path}")
    return {"path": str(path), "sha256": sha256_file(path)}


def environment_receipt(path_value: str, required_tool: str | None = None) -> dict[str, str]:
    reference = existing_file(path_value, "environment receipt")
    try:
        receipt = json.loads(Path(reference["path"]).read_text(encoding="utf-8"))
        created_at = dt.datetime.fromisoformat(receipt["created_at"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ParameterizationError("Environment receipt is invalid; rerun environment verify.") from exc
    if receipt.get("artifact_type") != "molecular_modeling_environment_receipt" or receipt.get("schema_version") != "1.1" or receipt.get("ready") is not True:
        raise ParameterizationError("Environment receipt is not ready; resolve its warnings before parameterization.")
    if dt.datetime.now(dt.timezone.utc) - created_at.astimezone(dt.timezone.utc) > dt.timedelta(days=7):
        raise ParameterizationError("Environment receipt is older than seven days; rerun environment verify.")
    if required_tool and not receipt.get("report", {}).get("tools", {}).get(required_tool, {}).get("available"):
        raise ParameterizationError(f"Environment receipt does not verify {required_tool}.")
    return {**reference, "profile": receipt.get("profile")}


def tool_record(command: str) -> dict[str, Any]:
    executable = shutil.which(command)
    record: dict[str, Any] = {"command": command, "path": executable, "available": bool(executable)}
    if not executable:
        return record
    for args in ([executable, "--version"], [executable, "-v"], [executable, "--help"]):
        try:
            result = subprocess.run(args, text=True, capture_output=True, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            record["version_error"] = str(exc)
            return record
        text = (result.stdout or result.stderr).strip()
        if text:
            record["version"] = text.splitlines()[0][:300]
            return record
    return record


def default_engine(force_field: str) -> str:
    return "acpype" if force_field == "amber-gaff" else "cgenff"


def detect(output_dir: Path) -> dict[str, Any]:
    tools = {name: tool_record(name) for name in DETECT_TOOLS}
    routes = {
        "amber-gaff": {
            "engine": "acpype",
            "auto_runnable": bool(tools["acpype"]["available"]),
            "note": "GAFF2 parameters via acpype (Antechamber/parmchk2/tleap wrapper); -c user keeps the user-provided net charge.",
            "fallback": "sobtop is a manual-download alternative; it is never fetched automatically.",
        },
        "charmm-cgenff": {
            "engine": "cgenff",
            "auto_runnable": False,
            "note": "CGenFF requires the licensed program or official web service; this skill records a handoff instead of running it.",
        },
    }
    return {
        "schema_version": "1.0",
        "artifact_type": "ligand_parameterization_environment",
        "created_at": stamp(),
        "tools": tools,
        "routes": routes,
        "boundaries": ["no automatic tool downloads", "net charge is never inferred", "CGenFF/sobtop remain manual handoffs"],
    }


def build_plan(ligand: Path, force_field: str, net_charge: int, identity: str, engine: str | None) -> dict[str, Any]:
    chosen = engine or default_engine(force_field)
    if chosen not in ENGINES:
        raise ParameterizationError(f"Unsupported engine: {chosen}")
    if force_field == "charmm-cgenff" and chosen == "acpype":
        raise ParameterizationError("acpype produces GAFF/AMBER parameters; use engine cgenff for charmm-cgenff.")
    ligand_ref = existing_file(str(ligand), "ligand structure")
    actions: list[dict[str, Any]] = []
    if chosen in AUTO_ENGINES:
        actions.append({
            "engine": "acpype",
            "kind": "local_command",
            "command": ["acpype", "-i", ligand_ref["path"], "-b", identity, "-n", str(net_charge), "-c", "user", "-a", "gaff2", "-o", "gmx"],
            "expected_outputs": {"topology": f"{identity}.acpype/{identity}_GMX.itp", "coordinates": f"{identity}.acpype/{identity}_GMX.gro"},
            "charge_policy": "-c user: the explicit net charge is used as given; per-atom charges still come from the input structure.",
        })
    elif chosen == "sobtop":
        actions.append({
            "engine": "sobtop",
            "kind": "handoff",
            "reason": "sobtop is a manual download; obtain it from the author's site and run it yourself.",
            "handoff_url": "http://sobereva.com/soft/Sobtop",
            "expected_outputs": {"topology": f"{identity}.itp", "coordinates": f"{identity}.gro"},
        })
    else:
        actions.append({
            "engine": "cgenff",
            "kind": "handoff",
            "reason": "CGenFF needs the licensed program or the official web service; neither is automated.",
            "handoff_url": "https://cgenff.silcsbio.com/",
            "expected_outputs": {"topology": f"{identity}.itp", "coordinates": f"{identity}.gro"},
            "conversion_note": "Convert the CGenFF .str stream to GROMACS with the cgenff_charmm2gmx script (manual download) before finalize.",
        })
    plan = {
        "schema_version": "1.0",
        "artifact_type": "ligand_parameterization_plan",
        "created_at": stamp(),
        "ligand": ligand_ref,
        "ligand_identity": identity,
        "force_field": force_field,
        "net_charge": net_charge,
        "net_charge_source": "explicitly provided by the user; never inferred from docking outputs",
        "actions": actions,
        "blocked_actions": ["download acpype/sobtop/CGenFF", "guess net charge or protonation state", "run licensed CGenFF binaries"],
    }
    plan["plan_sha256"] = plan_hash(plan)
    return plan


def plan_hash(plan: dict[str, Any]) -> str:
    canonical = {key: value for key, value in plan.items() if key != "plan_sha256"}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def read_plan(plan_path: Path) -> dict[str, Any]:
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ParameterizationError(f"Invalid plan: {exc}") from exc
    if plan.get("plan_sha256") != plan_hash(plan):
        raise ParameterizationError("Plan hash does not match; regenerate and review the plan before run.")
    return plan


def run_plan(plan_path: Path, output_dir: Path, environment_receipt_path: str) -> dict[str, Any]:
    plan = read_plan(plan_path)
    required_tool = "acpype" if any(action.get("kind") == "local_command" for action in plan.get("actions", [])) else None
    receipt_reference = environment_receipt(environment_receipt_path, required_tool)
    receipts: list[dict[str, Any]] = []
    for action in plan.get("actions", []):
        engine = action.get("engine")
        if engine not in ENGINES:
            raise ParameterizationError(f"Plan contains unsupported engine: {engine}")
        if action.get("kind") != "local_command":
            receipts.append({"engine": engine, "status": "handoff_required", "detail": action.get("reason", "Manual step required."), "handoff_url": action.get("handoff_url")})
            continue
        executable = shutil.which(engine)
        if not executable:
            receipts.append({"engine": engine, "status": "blocked", "detail": f"{engine} is not on PATH; install it in user space or choose a handoff engine."})
            continue
        command = [executable, *action["command"][1:]]
        attempts = []
        for attempt in range(2):
            result = subprocess.run(command, cwd=output_dir, text=True, capture_output=True, check=False)
            attempts.append({"attempt": attempt + 1, "returncode": result.returncode, "stdout": result.stdout[-1000:], "stderr": result.stderr[-1000:]})
            if result.returncode == 0:
                break
            time.sleep(2 ** attempt)
        item: dict[str, Any] = {"engine": engine, "status": "completed" if result.returncode == 0 else "failed", "command": command, "returncode": result.returncode, "attempts": attempts}
        if result.returncode == 0:
            outputs: dict[str, Any] = {}
            for label, relative in action.get("expected_outputs", {}).items():
                candidate = output_dir / relative
                if candidate.is_file():
                    outputs[label] = {"path": str(candidate.resolve()), "sha256": sha256_file(candidate)}
                else:
                    item["status"] = "incomplete"
                    outputs[label] = {"path": str(candidate.resolve()), "error": "expected output missing"}
            item["outputs"] = outputs
        receipts.append(item)
    return {
        "schema_version": "1.0",
        "artifact_type": "ligand_parameterization_receipt",
        "created_at": stamp(),
        "plan": str(plan_path.resolve()),
        "ligand_identity": plan["ligand_identity"],
        "net_charge": plan["net_charge"],
        "force_field": plan["force_field"],
        "environment_receipt": receipt_reference,
        "actions": receipts,
    }


def finalize(receipt_path: Path, topology: str, coordinates: str, output: Path, charges_verified: bool, notes: list[str]) -> dict[str, Any]:
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ParameterizationError(f"Invalid receipt: {exc}") from exc
    if receipt.get("artifact_type") != "ligand_parameterization_receipt":
        raise ParameterizationError("Receipt must be a ligand_parameterization_receipt; handoff engines can reference a receipt whose actions are all handoff_required.")
    topology_ref = existing_file(topology, "topology")
    coordinates_ref = existing_file(coordinates, "coordinates")
    checks = [
        "net charge explicitly provided by the user",
        "topology and coordinate files exist and are hashed",
    ]
    if charges_verified:
        checks.append("per-atom charges inspected by the user")
    record = {
        "schema_version": "1.0",
        "artifact_type": "ligand_parameterization",
        "created_at": stamp(),
        "ligand_identity": receipt.get("ligand_identity"),
        "net_charge": receipt.get("net_charge"),
        "force_field": receipt.get("force_field"),
        "topology": topology_ref["path"],
        "coordinates": coordinates_ref["path"],
        "topology_sha256": topology_ref["sha256"],
        "coordinates_sha256": coordinates_ref["sha256"],
        "provenance": {"receipt": str(receipt_path.resolve()), "engines": [a.get("engine") for a in receipt.get("actions", [])]},
        "validation": {
            "status": "validated" if charges_verified else "pending_review",
            "checks": checks,
            "notes": notes,
            "scope": "bookkeeping validation only; it is not a physical accuracy guarantee of the parameters",
        },
    }
    write_json(output, record)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("detect"); p.add_argument("--output-dir", type=Path, required=True)
    p = sub.add_parser("plan"); p.add_argument("--ligand", type=Path, required=True); p.add_argument("--force-field", choices=FORCE_FIELDS, required=True); p.add_argument("--net-charge", type=int, required=True); p.add_argument("--ligand-identity"); p.add_argument("--engine", choices=ENGINES); p.add_argument("--output-dir", type=Path, required=True)
    p = sub.add_parser("run"); p.add_argument("--plan", type=Path, required=True); p.add_argument("--environment-receipt", required=True); p.add_argument("--output-dir", type=Path, required=True)
    p = sub.add_parser("finalize"); p.add_argument("--receipt", type=Path, required=True); p.add_argument("--topology", required=True); p.add_argument("--coordinates", required=True); p.add_argument("--charges-verified", action="store_true"); p.add_argument("--note", action="append", default=[]); p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "detect":
            path = args.output_dir / "parameterization_environment.json"; write_json(path, detect(args.output_dir))
        elif args.command == "plan":
            ligand = args.ligand.expanduser().resolve()
            if ligand.suffix.lower() not in SUPPORTED_LIGAND_SUFFIXES:
                raise ParameterizationError(f"Unsupported ligand format {ligand.suffix!r}; use one of {', '.join(SUPPORTED_LIGAND_SUFFIXES)}")
            identity = args.ligand_identity or ligand.stem
            plan = build_plan(ligand, args.force_field, args.net_charge, identity, args.engine)
            path = args.output_dir / "ligand_parameterization_plan.json"; write_json(path, plan)
        elif args.command == "run":
            path = args.output_dir / "parameterization_receipt.json"; write_json(path, run_plan(args.plan, args.output_dir, args.environment_receipt))
        else:
            path = args.output.expanduser().resolve()
            finalize(args.receipt, args.topology, args.coordinates, path, args.charges_verified, args.note)
    except ParameterizationError as exc:
        print(f"Error: {exc}", file=sys.stderr); raise SystemExit(1)
    print(f"Success! Data written to: {path}")


if __name__ == "__main__":
    main()
