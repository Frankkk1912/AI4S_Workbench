#!/usr/bin/env python3
"""Plan, benchmark, run, resume, and monitor auditable GROMACS MD stages."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

GPU_PROFILES = {"wsl2-gpu", "linux-gpu"}
STAGE_ORDER = ("em", "nvt", "npt", "md_prod")
STAGE_PREDECESSOR = {"em": None, "nvt": "em", "npt": "nvt", "md_prod": "npt"}


class MDError(ValueError):
    pass


def now() -> str: return dt.datetime.now(dt.timezone.utc).isoformat()
def load(path: Path) -> dict:
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc: raise MDError(f"Cannot read {path}: {exc}") from exc
def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
def hashf(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def plan_hash(plan: dict) -> str: return hashlib.sha256(json.dumps({key: value for key, value in plan.items() if key != "plan_sha256"}, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
def build_stage_plan(stage: str, deffnm: str, profile: str, threads: int, resume: bool) -> dict:
    if stage not in STAGE_ORDER: raise MDError("Unsupported MD stage.")
    if profile not in {"cpu-fallback", "wsl2-gpu", "linux-gpu", "linux-ssh"}: raise MDError("Unsupported MD profile.")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", deffnm): raise MDError("--deffnm must be a safe GROMACS output prefix.")
    if threads <= 0: raise MDError("--threads must be positive.")
    command = ["gmx", "mdrun", "-deffnm", deffnm, "-ntmpi", "1", "-ntomp", str(threads)]
    if profile in GPU_PROFILES: command.extend(["-nb", "gpu"])
    if resume: command.extend(["-cpi", f"{deffnm}.cpt"])
    # GROMACS writes checkpoints on its checkpoint interval; short EM runs can
    # complete successfully before producing one. A checkpoint is therefore not
    # completion evidence for a fresh stage (but is required by --resume).
    expected_artifacts = [f"{deffnm}.tpr", f"{deffnm}.gro", f"{deffnm}.log", f"{deffnm}.edr"]
    if resume:
        expected_artifacts.append(f"{deffnm}.cpt")
    if stage == "md_prod": expected_artifacts.append(f"{deffnm}.xtc")
    plan = {"schema_version": "1.0", "artifact_type": "md_stage_plan", "created_at": now(), "stage": stage, "profile": profile, "deffnm": deffnm, "resume": resume, "command": command, "expected_artifacts": expected_artifacts}
    plan["plan_sha256"] = plan_hash(plan)
    return plan
def read_stage_plan(path: Path) -> dict:
    plan = load(path)
    if plan.get("artifact_type") != "md_stage_plan" or plan.get("schema_version") != "1.0" or plan.get("plan_sha256") != plan_hash(plan): raise MDError("Stage plan is invalid or its hash does not match.")
    command = plan.get("command", [])
    try: threads = int(command[command.index("-ntomp") + 1])
    except (ValueError, IndexError) as exc: raise MDError("Stage plan has no valid thread count.") from exc
    expected = build_stage_plan(plan.get("stage"), plan.get("deffnm"), plan.get("profile"), threads, bool(plan.get("resume")))
    if plan["command"] != expected["command"] or plan["expected_artifacts"] != expected["expected_artifacts"]: raise MDError("Stage plan command differs from the permitted structured plan.")
    return plan
def validate_stage_prerequisites(manifest: dict, plan: dict) -> None:
    predecessor = STAGE_PREDECESSOR[plan["stage"]]
    if predecessor is not None:
        record = manifest.get("stages", {}).get(predecessor, {})
        reference = record.get("artifacts", {}).get("gro")
        if record.get("status") != "completed" or not isinstance(reference, dict): raise MDError(f"{plan['stage']} requires a completed {predecessor} stage artifact.")
        artifact = Path(reference.get("path", ""))
        if not artifact.is_file() or hashf(artifact) != reference.get("sha256"): raise MDError(f"{plan['stage']} required artifact from {predecessor} is missing or changed.")
    tpr = Path(manifest["work_dir"]) / f"{plan['deffnm']}.tpr"
    if not tpr.is_file() or tpr.stat().st_size == 0: raise MDError(f"{plan['stage']} required input is missing or empty: {tpr.name}")
def validate_receipt(receipt: dict, profile: str) -> None:
    if receipt.get("artifact_type") != "molecular_modeling_environment_receipt" or receipt.get("schema_version") != "1.1": raise MDError("Environment receipt schema is unsupported; rerun environment verify.")
    if receipt.get("profile") != profile: raise MDError("Environment receipt profile does not match the MD duration plan.")
    if receipt.get("ready") is not True: raise MDError("Environment receipt is not ready; resolve its warnings before MD preparation.")
    try: created_at = dt.datetime.fromisoformat(receipt["created_at"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc: raise MDError("Environment receipt has no valid created_at timestamp.") from exc
    if dt.datetime.now(dt.timezone.utc) - created_at.astimezone(dt.timezone.utc) > dt.timedelta(days=7): raise MDError("Environment receipt is older than seven days; rerun environment verify.")
    report = receipt.get("report")
    if not isinstance(report, dict) or not isinstance(report.get("tools"), dict): raise MDError("Environment receipt lacks the verified tool report.")
    container = report.get("gromacs_container", {})
    if not isinstance(container, dict):
        container = {}
    container_verified = (
        container.get("available") is True
        and isinstance(container.get("digest"), str)
        and "@sha256:" in container["digest"]
    )
    if profile in GPU_PROFILES:
        if not container_verified: raise MDError("Environment receipt does not verify the pinned GROMACS container.")
    elif not report["tools"].get("gmx", {}).get("available"):
        raise MDError("Environment receipt does not verify GROMACS.")


def receipt_executable(receipt: dict, tool: str) -> str:
    record = receipt.get("report", {}).get("tools", {}).get(tool, {})
    path = record.get("path") if isinstance(record, dict) else None
    if not record or not record.get("available") or not isinstance(path, str):
        raise MDError(f"Environment receipt does not verify {tool} at an absolute executable path.")
    executable = Path(path)
    try:
        valid = executable.is_absolute() and executable.is_file() and bool(executable.stat().st_mode & 0o111)
    except OSError:
        valid = False
    if not valid:
        raise MDError(f"Environment receipt does not verify {tool} at an absolute executable path.")
    return str(executable.resolve())

def gromacs_command(receipt: dict, work_dir: Path, gmx_args: list[str]) -> list[str]:
    if not gmx_args or gmx_args[0] != "gmx": raise MDError("GROMACS plan must begin with gmx.")
    container = receipt.get("report", {}).get("gromacs_container", {})
    if not isinstance(container, dict):
        container = {}
    digest = container.get("digest")
    if container.get("available") is not True or not isinstance(digest, str) or "@sha256:" not in digest:
        raise MDError("Environment receipt does not contain a verified GROMACS container digest.")
    return [receipt_executable(receipt, "docker"), "run", "--rm", "--gpus", "all", "-v", f"{work_dir.resolve()}:/work", "-w", "/work", digest, "gmx", *gmx_args[1:]]


def require_file(path: Path, label: str) -> Path:
    try:
        valid = path.is_file() and path.stat().st_size > 0
    except OSError:
        valid = False
    if not valid:
        raise MDError(f"{label} is missing or empty: {path}")
    return path.resolve()


def file_reference(path: Path) -> dict:
    resolved = path.resolve()
    return {"path": str(resolved), "sha256": hashf(resolved)}


def work_relative(path: Path, work: Path, label: str) -> str:
    resolved = require_file(path, label)
    try:
        return resolved.relative_to(work.resolve()).as_posix()
    except ValueError as exc:
        raise MDError(f"{label} must resolve inside the manifest work directory.") from exc


def validate_grompp_manifest(manifest: dict) -> Path:
    if manifest.get("artifact_type") != "md_run_manifest" or manifest.get("schema_version") != "1.0":
        raise MDError("MD manifest is invalid or unsupported.")
    work_value = manifest.get("work_dir")
    if not isinstance(work_value, str) or not Path(work_value).is_absolute():
        raise MDError("MD manifest does not contain an absolute work directory.")
    work = Path(work_value).resolve()
    if not work.is_dir():
        raise MDError("MD manifest work directory does not exist.")
    return work


def mdp_has_position_restraints(path: Path) -> bool:
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.split(";", 1)[0].strip()
        if re.match(r"^define\s*=", line, flags=re.IGNORECASE) and re.search(r"(?:^|\s)-DPOSRES(?:\S*)?(?:\s|$)", line, flags=re.IGNORECASE):
            return True
    return False


def predecessor_coordinate(manifest: dict, stage: str) -> tuple[Path, str]:
    predecessor = STAGE_PREDECESSOR[stage]
    if predecessor is None:
        raise MDError("EM grompp requires an explicit source coordinate.")
    record = manifest.get("stages", {}).get(predecessor, {})
    reference = record.get("artifacts", {}).get("gro")
    if record.get("status") != "completed" or not isinstance(reference, dict):
        raise MDError(f"{stage} grompp requires a completed {predecessor} stage GRO artifact.")
    path_value = reference.get("path")
    if not isinstance(path_value, str) or not isinstance(reference.get("sha256"), str):
        raise MDError(f"{predecessor} stage GRO artifact reference is incomplete.")
    artifact = require_file(Path(path_value), f"{predecessor} stage GRO artifact")
    if hashf(artifact) != reference["sha256"]:
        raise MDError(f"{predecessor} stage GRO artifact hash changed.")
    return artifact, predecessor


def build_grompp_plan(args: argparse.Namespace) -> dict:
    manifest_path = require_file(args.manifest, "MD manifest")
    stage_plan_path = require_file(args.stage_plan, "MD stage plan")
    manifest = load(manifest_path)
    work = validate_grompp_manifest(manifest)
    stage_plan = read_stage_plan(stage_plan_path)
    stage = stage_plan["stage"]
    profile = stage_plan["profile"]
    if profile not in GPU_PROFILES:
        raise MDError("Audited grompp currently requires a GPU profile and the pinned GROMACS Docker container.")
    if profile != manifest.get("duration_plan", {}).get("profile"):
        raise MDError("Stage plan profile does not match the prepared MD manifest.")
    mdp = require_file(args.mdp, "MDP input")
    topology = require_file(args.topology, "topology input")
    mdp_rel = work_relative(mdp, work, "MDP input")
    topology_rel = work_relative(topology, work, "topology input")
    if stage == "em":
        if args.coordinate is None:
            raise MDError("EM grompp requires --coordinate.")
        coordinate = require_file(args.coordinate, "EM source coordinate")
        coordinate_source = {"kind": "explicit", "stage": None}
    else:
        if args.coordinate is not None:
            raise MDError("Successor grompp coordinates must come from the completed predecessor recorded in the manifest; do not pass --coordinate.")
        coordinate, predecessor = predecessor_coordinate(manifest, stage)
        coordinate_source = {"kind": "predecessor_gro", "stage": predecessor}
    coordinate_rel = work_relative(coordinate, work, "grompp coordinate input")
    reference = None
    reference_rel = None
    if args.reference is not None:
        if stage not in {"nvt", "npt"} or not mdp_has_position_restraints(mdp):
            raise MDError("--reference is permitted only for NVT or NPT MDPs that explicitly define POSRES restraints.")
        reference_path = require_file(args.reference, "restraint reference coordinate")
        reference_rel = work_relative(reference_path, work, "restraint reference coordinate")
        reference = file_reference(reference_path)
    if args.maxwarn < 0 or args.maxwarn > 2:
        raise MDError("--maxwarn must be between 0 and 2.")
    if args.maxwarn and not args.warning_rationale:
        raise MDError("Nonzero --maxwarn requires --warning-rationale.")
    receipt_value = manifest.get("environment_receipt", {}).get("path")
    if not isinstance(receipt_value, str):
        raise MDError("MD manifest does not reference an environment receipt.")
    receipt_path = require_file(Path(receipt_value), "environment receipt")
    receipt = load(receipt_path)
    validate_receipt(receipt, profile)
    docker_path = receipt_executable(receipt, "docker")
    container = receipt.get("report", {}).get("gromacs_container", {})
    image_digest = container.get("digest")
    command = ["gmx", "grompp", "-f", mdp_rel, "-c", coordinate_rel, "-p", topology_rel, "-o", f"{stage_plan['deffnm']}.tpr"]
    if reference_rel is not None:
        command.extend(["-r", reference_rel])
    if args.maxwarn:
        command.extend(["-maxwarn", str(args.maxwarn)])
    plan = {
        "schema_version": "1.0",
        "artifact_type": "md_grompp_plan",
        "created_at": now(),
        "stage": stage,
        "deffnm": stage_plan["deffnm"],
        "profile": profile,
        "work_dir": str(work),
        "inputs": {
            "manifest": file_reference(manifest_path),
            "stage_plan": file_reference(stage_plan_path),
            "mdp": file_reference(mdp),
            "topology": file_reference(topology),
            "coordinate": {**file_reference(coordinate), "source": coordinate_source},
            "reference": reference,
            "environment_receipt": file_reference(receipt_path),
        },
        "runtime": {"docker_path": docker_path, "gromacs_image_digest": image_digest},
        "parameters": {"maxwarn": args.maxwarn, "warning_rationale": args.warning_rationale},
        "output": {"path": str((work / f"{stage_plan['deffnm']}.tpr").resolve()), "deffnm": stage_plan["deffnm"]},
        "command": command,
    }
    plan["plan_sha256"] = plan_hash(plan)
    return plan


def read_grompp_plan(path: Path) -> dict:
    plan = load(path)
    if plan.get("artifact_type") != "md_grompp_plan" or plan.get("schema_version") != "1.0" or plan.get("plan_sha256") != plan_hash(plan):
        raise MDError("Grompp plan is invalid or its hash does not match.")
    command = plan.get("command")
    if not isinstance(command, list) or command[:2] != ["gmx", "grompp"]:
        raise MDError("Grompp plan command is invalid.")
    return plan


def match_planned_input(plan: dict, key: str, supplied: Path | None) -> None:
    expected = plan.get("inputs", {}).get(key)
    if expected is None:
        if supplied is not None:
            raise MDError(f"{key} was not approved by the grompp plan.")
        return
    if supplied is None:
        raise MDError(f"{key} required by the grompp plan was not supplied.")
    actual = file_reference(require_file(supplied, f"{key} input"))
    if actual != {"path": expected.get("path"), "sha256": expected.get("sha256")}:
        raise MDError(f"{key} input does not match the grompp plan.")


def execute_grompp(args: argparse.Namespace) -> dict:
    plan_path = require_file(args.plan, "grompp plan")
    plan = read_grompp_plan(plan_path)
    for key in ("manifest", "stage_plan", "mdp", "topology"):
        match_planned_input(plan, key, getattr(args, key))
    match_planned_input(plan, "reference", args.reference)
    if plan.get("inputs", {}).get("coordinate", {}).get("source", {}).get("kind") == "explicit":
        match_planned_input(plan, "coordinate", args.coordinate)
    elif args.coordinate is not None:
        raise MDError("Successor coordinates are receipt-bound predecessor artifacts; do not pass --coordinate.")
    manifest = load(args.manifest)
    work = validate_grompp_manifest(manifest)
    if str(work) != plan.get("work_dir"):
        raise MDError("Manifest work directory does not match the grompp plan.")
    stage_plan = read_stage_plan(args.stage_plan)
    if stage_plan.get("stage") != plan.get("stage") or stage_plan.get("deffnm") != plan.get("deffnm") or stage_plan.get("profile") != plan.get("profile"):
        raise MDError("Stage plan fields do not match the grompp plan.")
    if plan.get("profile") not in GPU_PROFILES:
        raise MDError("Grompp execution requires a GPU profile and the pinned GROMACS Docker container.")
    expected_output = {"path": str((work / f"{plan['deffnm']}.tpr").resolve()), "deffnm": plan["deffnm"]}
    if plan.get("output") != expected_output:
        raise MDError("Grompp output binding does not match the structured plan.")
    coordinate_ref = plan.get("inputs", {}).get("coordinate", {})
    coordinate = require_file(Path(coordinate_ref.get("path", "")), "grompp coordinate input")
    if hashf(coordinate) != coordinate_ref.get("sha256"):
        raise MDError("grompp coordinate input hash changed.")
    source = coordinate_ref.get("source", {})
    if plan["stage"] == "em":
        if source != {"kind": "explicit", "stage": None}:
            raise MDError("EM grompp plan does not bind an explicit source coordinate.")
    else:
        expected_predecessor = STAGE_PREDECESSOR[plan["stage"]]
        if source != {"kind": "predecessor_gro", "stage": expected_predecessor}:
            raise MDError("Successor grompp plan does not bind its required predecessor GRO.")
        current, predecessor = predecessor_coordinate(manifest, plan["stage"])
        if predecessor != source.get("stage") or file_reference(current) != {"path": coordinate_ref.get("path"), "sha256": coordinate_ref.get("sha256")}:
            raise MDError("Manifest predecessor artifact does not match the grompp plan.")
    receipt_ref = plan.get("inputs", {}).get("environment_receipt", {})
    receipt_path = require_file(Path(receipt_ref.get("path", "")), "environment receipt")
    if hashf(receipt_path) != receipt_ref.get("sha256"):
        raise MDError("Environment receipt hash changed after grompp planning.")
    receipt = load(receipt_path)
    validate_receipt(receipt, plan["profile"])
    docker_path = receipt_executable(receipt, "docker")
    container = receipt.get("report", {}).get("gromacs_container", {})
    if docker_path != plan.get("runtime", {}).get("docker_path") or container.get("digest") != plan.get("runtime", {}).get("gromacs_image_digest"):
        raise MDError("Receipt-bound Docker path or GROMACS image digest changed after planning.")
    expected_command = ["gmx", "grompp", "-f", work_relative(args.mdp, work, "MDP input"), "-c", work_relative(coordinate, work, "grompp coordinate input"), "-p", work_relative(args.topology, work, "topology input"), "-o", f"{plan['deffnm']}.tpr"]
    if args.reference is not None:
        if plan["stage"] not in {"nvt", "npt"} or not mdp_has_position_restraints(args.mdp):
            raise MDError("Grompp reference is allowed only for NVT or NPT MDPs that explicitly define POSRES restraints.")
        expected_command.extend(["-r", work_relative(args.reference, work, "restraint reference coordinate")])
    maxwarn = plan.get("parameters", {}).get("maxwarn")
    if not isinstance(maxwarn, int) or maxwarn < 0 or maxwarn > 2:
        raise MDError("Grompp plan contains an invalid maxwarn value.")
    if maxwarn and not plan.get("parameters", {}).get("warning_rationale"):
        raise MDError("Grompp plan has nonzero maxwarn without a reviewed rationale.")
    if maxwarn:
        expected_command.extend(["-maxwarn", str(maxwarn)])
    if plan.get("command") != expected_command:
        raise MDError("Grompp command differs from the permitted structured argument vector.")
    tpr = work / f"{plan['deffnm']}.tpr"
    log = work / f"{plan['deffnm']}.grompp.log"
    protected_outputs = {tpr.resolve(), log.resolve(), plan_path.resolve(), *(Path(item["path"]).resolve() for item in plan["inputs"].values() if isinstance(item, dict) and isinstance(item.get("path"), str))}
    if args.output.resolve() in protected_outputs:
        raise MDError("Grompp receipt output must not overwrite a plan, input, TPR, or log.")
    if tpr.exists():
        tpr.unlink()
    command = gromacs_command(receipt, work, expected_command)
    try:
        result = subprocess.run(command, cwd=work, text=True, capture_output=True, check=False)
    except OSError as exc:
        result = subprocess.CompletedProcess(command, 127, "", f"Cannot execute receipt-bound Docker: {exc}")
    log.write_text(result.stdout + "\n--- STDERR ---\n" + result.stderr, encoding="utf-8")
    completed = result.returncode == 0 and tpr.is_file() and tpr.stat().st_size > 0
    status_value = "completed" if completed else "failed" if result.returncode else "incomplete"
    receipt_doc = {
        "schema_version": "1.0",
        "artifact_type": "md_grompp_receipt",
        "created_at": now(),
        "status": status_value,
        "stage": plan["stage"],
        "deffnm": plan["deffnm"],
        "plan": file_reference(plan_path),
        "profile": plan["profile"],
        "gromacs_image_digest": container.get("digest"),
        "command": command,
        "returncode": result.returncode,
        "log": file_reference(log),
        "artifacts": {"tpr": file_reference(tpr)} if completed else {},
    }
    write(args.output, receipt_doc)
    if not completed:
        reason = "grompp failed; inspect its receipt-bound log." if result.returncode else "grompp returned zero but did not create a nonempty TPR."
        raise MDError(reason)
    return receipt_doc


def valid_handoff(path: Path) -> dict:
    data = load(path)
    if data.get("artifact_type") != "docking_to_md_handoff" or data.get("validation", {}).get("status") != "validated": raise MDError("MD handoff is not validated")
    if data.get("system_type") == "protein-ligand" and data.get("ligand", {}).get("validation", {}).get("status") != "validated": raise MDError("Ligand MD requires validated parameterization/topology")
    for reference in (data.get("selection", {}).get("coordinates"), data.get("ligand", {}).get("topology"), data.get("ligand", {}).get("coordinates")):
        if reference is None: continue
        if not isinstance(reference, dict) or not isinstance(reference.get("path"), str) or not isinstance(reference.get("sha256"), str): raise MDError("MD handoff contains an incomplete protected file reference")
        candidate = Path(reference["path"])
        if not candidate.is_file() or hashf(candidate) != reference["sha256"]: raise MDError("MD handoff protected input hash does not match")
    return data


def duration_plan(args: argparse.Namespace) -> dict:
    duration = args.duration_ns if args.duration_ns is not None else 100.0
    default_used = args.duration_ns is None
    if duration <= 0 or args.system_mass_kda <= 0 or args.atom_count <= 0: raise MDError("Duration, system mass, and atom count must be positive.")
    warning = None; confirmation_required = False
    if args.profile == "cpu-fallback":
        warning = "CPU MD may run for a long time. A duration of 10 ns or less is recommended."
        confirmation_required = duration > 10
        if confirmation_required and not args.confirm_long_cpu: raise MDError("CPU duration above 10 ns requires --confirm-long-cpu after the warning is shown to the user.")
    else:
        warning = "GPU duration was selected before execution; 100 ns is the disclosed default when no explicit duration is supplied."
    return {"schema_version": "1.0", "artifact_type": "md_duration_plan", "created_at": now(), "profile": args.profile, "duration_ns": duration, "duration_source": "disclosed_default_100_ns" if default_used else "user_selected", "system": {"mass_kda": args.system_mass_kda, "atom_count": args.atom_count}, "warning": warning, "confirmation": {"required": confirmation_required, "recorded": bool(args.confirm_long_cpu)}, "estimate": {"status": "benchmark_required", "message": "Mass and atom count are system-size descriptors; run a 5–10 minute benchmark for an ETA."}}


def parse_log(log: Path, total_steps: int, stale_minutes: float) -> dict:
    if total_steps <= 0: raise MDError("--total-steps must be positive.")
    if not log.is_file(): raise MDError(f"GROMACS log does not exist: {log}")
    text = log.read_text(errors="replace"); steps = [int(value) for value in re.findall(r"\bStep\s+(\d+)", text)]
    if not steps:
        rows = re.findall(r"^\s*(\d+)\s+[-+]?\d+(?:\.\d+)?\s*$", text, flags=re.MULTILINE)
        steps = [int(value) for value in rows]
    step = max(steps) if steps else 0; percent = min(100.0, step / total_steps * 100.0)
    remaining = re.findall(r"remaining wall clock time:\s*([^\n]+)", text, flags=re.IGNORECASE)
    ns_day = re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*ns/day", text, flags=re.IGNORECASE)
    age_seconds = max(0.0, time.time() - log.stat().st_mtime); stale = age_seconds > stale_minutes * 60
    filled = min(10, int(percent // 10)); bar = "[" + "█" * filled + "░" * (10 - filled) + "]"
    eta = remaining[-1].strip() if remaining else "unavailable"
    return {"schema_version": "1.0", "artifact_type": "md_progress", "checked_at": now(), "log": str(log.resolve()), "step": step, "total_steps": total_steps, "percent": round(percent, 2), "ns_per_day": float(ns_day[-1]) if ns_day else None, "eta": eta, "log_age_seconds": round(age_seconds, 1), "stale": stale, "warnings": ([f"Log has not changed for {age_seconds / 3600:.1f} hours."] if stale else []) + (["No step value was parsed from the log."] if not steps else []), "progress_bar": f"{bar} {percent:.0f}% | Step: {step:,} / {total_steps:,} | {ns_day[-1] + ' ns/day' if ns_day else 'throughput unavailable'} | ETA: {eta}"}


def progress_report(data: dict) -> str:
    warnings = data["warnings"] or ["None."]
    return "\n".join(["# MD Progress", "", data["progress_bar"], "", "## Warnings", *[f"- {item}" for item in warnings]]) + "\n"


def status(args: argparse.Namespace) -> Path:
    data = parse_log(args.log, args.total_steps, args.stale_after_minutes); write(args.output, data); args.output.with_suffix(".md").write_text(progress_report(data), encoding="utf-8"); return args.output


def watch(args: argparse.Namespace) -> Path:
    if args.interval_minutes <= 0 or args.iterations <= 0: raise MDError("--interval-minutes and --iterations must be positive.")
    path = args.output
    for index in range(args.iterations):
        path = status(args)
        if index + 1 < args.iterations: time.sleep(args.interval_minutes * 60)
    return path


def prepare(args: argparse.Namespace) -> dict:
    handoff = valid_handoff(args.handoff); receipt = load(args.environment_receipt); plan = load(args.duration_plan)
    if plan.get("artifact_type") != "md_duration_plan": raise MDError("--duration-plan is invalid.")
    validate_receipt(receipt, plan.get("profile"))
    if plan.get("confirmation", {}).get("required") and not plan.get("confirmation", {}).get("recorded"): raise MDError("Long CPU duration lacks recorded confirmation.")
    args.work_dir.mkdir(parents=True, exist_ok=True)
    return {"schema_version": "1.0", "artifact_type": "md_run_manifest", "created_at": now(), "work_dir": str(args.work_dir.resolve()), "handoff": {"path": str(args.handoff.resolve()), "sha256": hashf(args.handoff)}, "environment_receipt": {"path": str(args.environment_receipt.resolve()), "ready": receipt.get("ready")}, "duration_plan": {"path": str(args.duration_plan.resolve()), "profile": plan["profile"], "duration_ns": plan["duration_ns"]}, "system_type": handoff["system_type"], "stages": {}, "analysis_handoff": {"required_outputs": ["md_prod.tpr", "md_prod.xtc"], "consumer": "md-trajectory-analysis"}, "warnings": []}


def execute(args: argparse.Namespace) -> dict:
    manifest = load(args.manifest); work = Path(manifest["work_dir"]); plan = read_stage_plan(args.stage_plan); validate_stage_prerequisites(manifest, plan)
    if plan["profile"] != manifest.get("duration_plan", {}).get("profile"): raise MDError("Stage plan profile does not match the prepared MD manifest.")
    if manifest.get("stages", {}).get(plan["stage"], {}).get("status") == "completed": raise MDError("Stage is already completed; create a new reviewed plan before rerunning it.")
    receipt = load(Path(manifest["environment_receipt"]["path"]))
    validate_receipt(receipt, plan["profile"])
    if plan["profile"] in GPU_PROFILES:
        command = gromacs_command(receipt, work, plan["command"])
    else:
        command = [receipt_executable(receipt, "gmx"), *plan["command"][1:]]
    result = subprocess.run(command, cwd=work, text=True, capture_output=True, check=False); log = work / f"{plan['stage']}.runner.log"; log.write_text(result.stdout + "\n--- STDERR ---\n" + result.stderr, encoding="utf-8")
    artifacts = {Path(name).suffix.lstrip("."): {"path": str((work / name).resolve()), "sha256": hashf(work / name)} for name in plan["expected_artifacts"] if (work / name).is_file() and (work / name).stat().st_size > 0}
    complete = result.returncode == 0 and len(artifacts) == len(plan["expected_artifacts"])
    manifest.setdefault("stages", {})[plan["stage"]] = {"at": now(), "status": "completed" if complete else "failed" if result.returncode else "incomplete", "plan": {"path": str(args.stage_plan.resolve()), "sha256": hashf(args.stage_plan)}, "command": command, "returncode": result.returncode, "log": str(log), "artifacts": artifacts}
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__); sub = parser.add_subparsers(dest="command_name", required=True)
    p = sub.add_parser("plan-duration"); p.add_argument("--profile", choices=("cpu-fallback", "wsl2-gpu", "linux-gpu", "linux-ssh"), required=True); p.add_argument("--system-mass-kda", type=float, required=True); p.add_argument("--atom-count", type=int, required=True); p.add_argument("--duration-ns", type=float); p.add_argument("--confirm-long-cpu", action="store_true"); p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("plan-stage"); p.add_argument("--stage", choices=STAGE_ORDER, required=True); p.add_argument("--deffnm", required=True); p.add_argument("--profile", choices=("cpu-fallback", "wsl2-gpu", "linux-gpu", "linux-ssh"), required=True); p.add_argument("--threads", type=int, required=True); p.add_argument("--resume", action="store_true"); p.add_argument("--output", type=Path, required=True)
    for name in ("status", "watch"):
        p = sub.add_parser(name); p.add_argument("--manifest", type=Path, required=True); p.add_argument("--log", type=Path, required=True); p.add_argument("--total-steps", type=int, required=True); p.add_argument("--stale-after-minutes", type=float, default=180.0); p.add_argument("--output", type=Path, required=True)
        if name == "watch": p.add_argument("--interval-minutes", type=float, required=True); p.add_argument("--iterations", type=int, required=True)
    p = sub.add_parser("prepare"); p.add_argument("--handoff", type=Path, required=True); p.add_argument("--environment-receipt", type=Path, required=True); p.add_argument("--duration-plan", type=Path, required=True); p.add_argument("--work-dir", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("plan-grompp"); p.add_argument("--manifest", type=Path, required=True); p.add_argument("--stage-plan", type=Path, required=True); p.add_argument("--mdp", type=Path, required=True); p.add_argument("--topology", type=Path, required=True); p.add_argument("--coordinate", type=Path); p.add_argument("--reference", type=Path); p.add_argument("--maxwarn", type=int, choices=(0, 1, 2), required=True); p.add_argument("--warning-rationale"); p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("grompp"); p.add_argument("--plan", type=Path, required=True); p.add_argument("--manifest", type=Path, required=True); p.add_argument("--stage-plan", type=Path, required=True); p.add_argument("--mdp", type=Path, required=True); p.add_argument("--topology", type=Path, required=True); p.add_argument("--coordinate", type=Path); p.add_argument("--reference", type=Path); p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("run"); p.add_argument("--manifest", type=Path, required=True); p.add_argument("--stage-plan", type=Path, required=True); p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command_name == "plan-duration": data = duration_plan(args); write(args.output, data); path = args.output
        elif args.command_name == "plan-stage": data = build_stage_plan(args.stage, args.deffnm, args.profile, args.threads, args.resume); write(args.output, data); path = args.output
        elif args.command_name == "status": path = status(args)
        elif args.command_name == "watch": path = watch(args)
        elif args.command_name == "prepare": data = prepare(args); write(args.output, data); path = args.output
        elif args.command_name == "plan-grompp": data = build_grompp_plan(args); write(args.output, data); path = args.output
        elif args.command_name == "grompp": data = execute_grompp(args); path = args.output
        else: data = execute(args); write(args.output, data); path = args.output
    except MDError as exc: print(f"Error: {exc}", file=sys.stderr); raise SystemExit(1)
    print(f"Success! Data written to: {path}")
    if args.command_name == "run" and next(reversed(data["stages"].values()))["status"] != "completed": raise SystemExit(1)


if __name__ == "__main__": main()
