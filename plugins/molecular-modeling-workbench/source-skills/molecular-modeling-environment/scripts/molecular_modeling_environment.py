#!/usr/bin/env python3
"""Auditable environment inventory and user-space bootstrap for modeling."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from hashlib import sha256
from pathlib import Path
from typing import Any

PROFILES = ("wsl2-gpu", "linux-gpu", "linux-ssh", "cpu-fallback")
TOOLS = ("uv", "docker", "gmx", "gnina", "vina", "obabel", "mkdssp", "gmx_MMPBSA", "acpype", "pymol", "chimerax", "micromamba", "conda", "mamba")
MMPBSA_ANALYSIS_COMPONENT = "gmx-mmpbsa"
ALLOWED_COMPONENTS = {"uv", "pymol-open-source", "gromacs", "vina", "dssp", "openbabel", "acpype", MMPBSA_ANALYSIS_COMPONENT}
GROMACS_GPU_IMAGE = "nvcr.io/nvidia/gromacs:v2023.3"
PACKAGE_SPECS = {
    "pymol-open-source": ["pymol-open-source"],
    "acpype": ["acpype", "ambertools"],
    "gromacs": ["gromacs"],
    "vina": ["vina"],
    "dssp": ["mkdssp"],
    "openbabel": ["openbabel"],
    MMPBSA_ANALYSIS_COMPONENT: ["gromacs=2023.4", "gmx_MMPBSA=1.6.5"],
}
MANAGED_TOOL_COMPONENTS = {
    "pymol": "pymol-open-source",
    "gmx": MMPBSA_ANALYSIS_COMPONENT,
    "vina": "vina",
    "mkdssp": "dssp",
    "obabel": "openbabel",
    "acpype": "acpype",
    "gmx_MMPBSA": MMPBSA_ANALYSIS_COMPONENT,
}


class EnvironmentError(ValueError):
    pass


def stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def command_version(command: str, executable: str | None = None) -> dict[str, Any]:
    executable = executable or shutil.which(command)
    record: dict[str, Any] = {"command": command, "path": executable, "available": bool(executable)}
    if not executable:
        return record
    for args in ([executable, "--version"], [executable, "-version"], [executable, "-V"]):
        try:
            result = subprocess.run(args, text=True, capture_output=True, timeout=12, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            record["version_error"] = str(exc)
            return record
        text = (result.stdout or result.stderr).strip()
        if text:
            record["version"] = text.splitlines()[0][:500]
            record["returncode"] = result.returncode
            return record
    return record


def run_probe(args: list[str]) -> dict[str, Any]:
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=15, check=False)
        return {"command": args, "returncode": result.returncode, "stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": args, "error": str(exc)}


def managed_prefix_executable(output_dir: Path | None, command: str) -> str | None:
    components = MANAGED_TOOL_COMPONENTS.get(command)
    if output_dir is None or components is None:
        return None
    if isinstance(components, str):
        components = (components,)
    for component in components:
        candidate = output_dir / "environments" / component / "bin" / command
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    return None


def package_channels(component: str) -> tuple[str, ...]:
    return ("conda-forge",)


def package_create_command(component: str, prefix: Path) -> list[str]:
    command = ["micromamba", "create", "-y", "-p", str(prefix)]
    for channel in package_channels(component):
        command.extend(["-c", channel])
    return [*command, *PACKAGE_SPECS[component]]


def mmpbsa_analysis_gmx(output_dir: Path | None) -> str | None:
    """Return only a GROMACS binary paired with gmx_MMPBSA, never an arbitrary gmx."""
    managed = managed_prefix_executable(output_dir, "gmx")
    if managed and (Path(managed).parent / "gmx_MMPBSA").is_file():
        return managed
    mmpbsa = shutil.which("gmx_MMPBSA")
    if not mmpbsa:
        return None
    candidate = Path(mmpbsa).resolve().parent / "gmx"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


def is_wsl() -> bool:
    release = platform.release().lower()
    return "microsoft" in release or "wsl" in release or Path("/proc/sys/fs/binfmt_misc/WSLInterop").exists()


def docker_socket() -> dict[str, Any]:
    path = Path("/var/run/docker.sock")
    record: dict[str, Any] = {"path": str(path), "exists": path.exists()}
    if path.exists():
        stat = path.stat()
        record.update({"mode": oct(stat.st_mode & 0o777), "uid": stat.st_uid, "gid": stat.st_gid})
    return record


def conda_context() -> dict[str, Any]:
    prefix = os.environ.get("CONDA_PREFIX")
    python_inside = False
    if prefix:
        try:
            resolved_prefix = Path(prefix).resolve()
            # In a virtual environment, sys.executable can be a symlink to the
            # base interpreter while sys.prefix remains the active environment.
            python_inside = (
                Path(sys.executable).resolve().is_relative_to(resolved_prefix)
                or Path(sys.prefix).resolve().is_relative_to(resolved_prefix)
            )
        except OSError:
            python_inside = False
    return {
        "active_environment": os.environ.get("CONDA_DEFAULT_ENV"),
        "prefix": prefix,
        "conda_exe": os.environ.get("CONDA_EXE"),
        "mamba_root_prefix": os.environ.get("MAMBA_ROOT_PREFIX"),
        "python_inside_active_env": python_inside,
        "policy": "detection only; bootstrap keeps per-component micromamba prefixes and never activates, installs into, or mutates a shared conda environment",
    }


def execution_context() -> dict[str, Any]:
    groups = sorted(set(getattr(os, "getgroups", lambda: [])()))
    return {
        "uid": getattr(os, "getuid", lambda: None)(),
        "groups": groups,
        "can_write_home": os.access(Path.home(), os.W_OK),
        "wsl_gpu_device": {"path": "/dev/dxg", "exists": Path("/dev/dxg").exists()},
        "docker_socket": docker_socket(),
        "hostname": socket.gethostname(),
    }


def classify_diagnostics(report: dict[str, Any]) -> dict[str, Any]:
    context = report["execution_context"]
    gpu = report["gpu"]
    gpu_text = "\n".join(str(gpu.get(key, "")) for key in ("stdout", "stderr", "error")).lower()
    if gpu.get("returncode") == 0:
        gpu_status = "available"
    elif report["host"]["wsl"] and (not context["wsl_gpu_device"]["exists"] or (not context["can_write_home"] and "gpu access blocked" in gpu_text)):
        gpu_status = "execution_isolation"
    else:
        gpu_status = "host_configuration_failure"
    docker = report["container"]
    docker_text = "\n".join(str(docker.get(key, "")) for key in ("stdout", "stderr", "error")).lower()
    if docker.get("returncode") == 0:
        docker_status = "available"
    elif not report["tools"]["docker"]["available"]:
        docker_status = "not_installed_or_not_on_path"
    elif "permission denied" in docker_text and not context["can_write_home"]:
        docker_status = "execution_isolation"
    elif "permission denied" in docker_text:
        docker_status = "permission_or_daemon_failure"
    else:
        docker_status = "host_configuration_failure"
    missing = [name for name, tool in report["tools"].items() if not tool["available"]]
    if "gmx" in missing and report.get("profile") in {"wsl2-gpu", "linux-gpu"} and report.get("gromacs_container", {}).get("available"):
        missing.remove("gmx")
    host_recheck_recommended = gpu_status == "execution_isolation" or docker_status == "execution_isolation"
    return {
        "gpu": {"status": gpu_status, "evidence": {"nvidia_smi_returncode": gpu.get("returncode"), "dxg_present": context["wsl_gpu_device"]["exists"], "can_write_home": context["can_write_home"]}},
        "docker": {"status": docker_status, "evidence": {"returncode": docker.get("returncode"), "socket": context["docker_socket"]}},
        "tools": {"missing": missing, "status": "not_installed_or_not_on_path" if missing else "available"},
        "host_recheck": {"recommended": host_recheck_recommended, "requires_explicit_command_authorization": True, "reason": "Active execution context appears isolated from host hardware or Docker." if host_recheck_recommended else "No execution-isolation evidence was detected."},
    }


def audit(profile: str, output_dir: Path | None = None) -> dict[str, Any]:
    tools = {
        name: command_version(name, shutil.which(name) or managed_prefix_executable(output_dir, name))
        for name in TOOLS
    }
    gpu = run_probe(["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"])
    docker = run_probe(["docker", "info", "--format", "{{json .Runtimes}}"])
    gromacs_container = run_probe(["docker", "image", "inspect", GROMACS_GPU_IMAGE, "--format", "{{index .RepoDigests 0}}"])
    gromacs_digest = gromacs_container.get("stdout", "").strip()
    chimerax = tools["chimerax"]
    analysis_gromacs = command_version("gmx", mmpbsa_analysis_gmx(output_dir))
    return {
        "schema_version": "1.1",
        "artifact_type": "molecular_modeling_environment_report",
        "created_at": stamp(),
        "profile": profile,
        "host": {"system": platform.system(), "release": platform.release(), "machine": platform.machine(), "python": sys.version.split()[0], "wsl": is_wsl()},
        "tools": tools,
        "trajectory_analysis": {
            "gromacs": analysis_gromacs,
            "ready": bool(analysis_gromacs["available"]),
            "environment_component": MMPBSA_ANALYSIS_COMPONENT,
            "install_component": MMPBSA_ANALYSIS_COMPONENT,
            "policy": "Trajectory analysis uses the native gmx paired with the pinned gmx_MMPBSA environment; do not use the GPU MD container or an unrelated gmx executable for this capability.",
        },
        "gpu": gpu,
        "container": docker,
        "gromacs_container": {"image": GROMACS_GPU_IMAGE, "available": gromacs_container.get("returncode") == 0 and "@sha256:" in gromacs_digest, "digest": gromacs_digest if "@sha256:" in gromacs_digest else None, "probe": gromacs_container},
        "conda": conda_context(),
        "chimerax": {
            "detected": bool(chimerax["available"]),
            "path": chimerax["path"],
            "policy": "detected only; never automatically downloaded",
            "official_download_handoff": "https://www.cgl.ucsf.edu/chimerax/download.html",
        },
        "execution_context": execution_context(),
    }


def add_diagnostics(report: dict[str, Any]) -> dict[str, Any]:
    report["diagnostics"] = classify_diagnostics(report)
    return report


def readiness(report: dict[str, Any], profile: str) -> tuple[bool, list[str]]:
    warnings: list[str] = []
    tools = report["tools"]
    if not tools["uv"]["available"]:
        warnings.append("uv is unavailable.")
    if profile == "wsl2-gpu" and not report["host"]["wsl"]:
        warnings.append("wsl2-gpu requires execution inside WSL2.")
    if profile in {"wsl2-gpu", "linux-gpu"}:
        if report["gpu"].get("returncode") != 0:
            status = report["diagnostics"]["gpu"]["status"]
            warnings.append(f"NVIDIA GPU is unavailable in this context ({status}).")
            if status == "execution_isolation":
                warnings.append("Request one authorized host recheck before diagnosing a user WSL2 GPU failure.")
        docker_status = report["diagnostics"]["docker"]["status"]
        if docker_status != "available":
            warnings.append(f"Docker route cannot be verified ({docker_status}).")
        if not report["gromacs_container"]["available"]:
            warnings.append(f"Pinned GROMACS image cannot be verified ({GROMACS_GPU_IMAGE}).")
    if profile == "cpu-fallback" and not tools["gmx"]["available"]:
        warnings.append("GROMACS is unavailable for the CPU fallback profile.")
    if profile == "linux-ssh":
        warnings.append("Remote profile requires the separate read-only remote audit.")
    return not warnings, warnings


def build_plan(profile: str, components: list[str], output_dir: Path) -> dict[str, Any]:
    output_dir = output_dir.resolve()
    unknown = sorted(set(components) - ALLOWED_COMPONENTS)
    if unknown:
        raise EnvironmentError(f"Unsupported automatic component(s): {', '.join(unknown)}")
    actions: list[dict[str, Any]] = []
    for component in components:
        if component == "uv":
            actions.append({"component": "uv", "scope": "user", "kind": "handoff", "reason": "Use the official installer; bootstrap does not alter shell profiles.", "command": "https://docs.astral.sh/uv/getting-started/installation/"})
        if component == "gromacs" and profile in {"wsl2-gpu", "linux-gpu"}:
            actions.append({"component": "gromacs", "scope": "docker-user", "kind": "docker-pull", "image": GROMACS_GPU_IMAGE, "retry": "bounded exponential backoff for transient image pull failures"})
        elif component == "gromacs" and profile == "linux-ssh":
            actions.append({"component": "gromacs", "scope": "remote", "kind": "handoff", "reason": "Remote GROMACS installation is administrator- or module-controlled; use remote audit and follow the cluster policy."})
        elif component in PACKAGE_SPECS:
            prefix = output_dir / "environments" / component
            binary = {"pymol-open-source": "pymol", "gromacs": "gmx", "vina": "vina", "dssp": "mkdssp", "openbabel": "obabel", "acpype": "acpype", MMPBSA_ANALYSIS_COMPONENT: "gmx_MMPBSA"}[component]
            actions.append({"component": component, "scope": "user", "kind": "micromamba", "prefix": str(prefix), "channels": list(package_channels(component)), "command": package_create_command(component, prefix), "smoke_test": [str(prefix / "bin" / binary), "--version"], "retry": "bounded exponential backoff for transient package download failures"})
    plan = {"schema_version": "1.1", "artifact_type": "molecular_modeling_install_plan", "created_at": stamp(), "profile": profile, "actions": actions, "blocked_actions": ["enable WSL2", "reboot", "BIOS virtualization", "Docker Desktop installation", "Windows NVIDIA driver changes", "remote sudo", "cluster module changes", "ChimeraX download"]}
    plan["plan_sha256"] = plan_hash(plan)
    return plan


def plan_hash(plan: dict[str, Any]) -> str:
    canonical = {key: value for key, value in plan.items() if key != "plan_sha256"}
    return sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def bootstrap(plan_path: Path, output_dir: Path) -> dict[str, Any]:
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EnvironmentError(f"Invalid plan: {exc}") from exc
    if plan.get("plan_sha256") != plan_hash(plan):
        raise EnvironmentError("Plan hash does not match; regenerate and review the plan before bootstrap.")
    receipts: list[dict[str, Any]] = []
    for action in plan.get("actions", []):
        component = action.get("component")
        if component not in ALLOWED_COMPONENTS:
            raise EnvironmentError(f"Plan contains disallowed component: {component}")
        kind = action.get("kind")
        if kind not in {"micromamba", "docker-pull"}:
            receipts.append({"component": component, "status": "handoff_required", "detail": action.get("reason", "No automatic action.")})
            continue
        if kind == "micromamba":
            executable = next((shutil.which(name) for name in ("micromamba", "mamba", "conda") if shutil.which(name)), None)
            if not executable:
                receipts.append({"component": component, "status": "blocked", "detail": "No micromamba, mamba, or conda executable is available; install one in user space, then rerun bootstrap."})
                continue
            command = [executable, *action["command"][1:]]
        else:
            executable = shutil.which("docker")
            if not executable:
                receipts.append({"component": component, "status": "blocked", "detail": "Docker is unavailable; install/configure Docker manually, then rerun bootstrap."})
                continue
            command = [executable, "pull", action["image"]]
        attempts = []
        for attempt in range(3):
            result = subprocess.run(command, text=True, capture_output=True, check=False)
            attempts.append({"attempt": attempt + 1, "returncode": result.returncode, "stdout": result.stdout[-1000:], "stderr": result.stderr[-1000:]})
            if result.returncode == 0 or attempt == 2:
                break
            time.sleep(2 ** attempt)
        item = {"component": component, "status": "installed" if result.returncode == 0 else "failed", "command": command, "returncode": result.returncode, "stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:], "attempts": attempts}
        receipts.append(item)
        if result.returncode == 0:
            smoke = action.get("smoke_test")
            if smoke:
                smoke_result = subprocess.run(smoke, cwd=output_dir, text=True, capture_output=True, check=False)
                item["smoke_test"] = {"returncode": smoke_result.returncode, "stdout": smoke_result.stdout[-1000:], "stderr": smoke_result.stderr[-1000:]}
    return {"schema_version": "1.0", "artifact_type": "molecular_modeling_environment_receipt", "created_at": stamp(), "plan": str(plan_path.resolve()), "actions": receipts, "warnings": ["ChimeraX is never downloaded automatically."]}


COMPONENT_BINARIES = {"pymol-open-source": "pymol", "gromacs": "gmx", "vina": "vina", "dssp": "mkdssp", "openbabel": "obabel", "acpype": "acpype", MMPBSA_ANALYSIS_COMPONENT: "gmx_MMPBSA"}


def onboard(profile: str, output_dir: Path) -> dict[str, Any]:
    report = add_diagnostics(audit(profile, output_dir))
    tools = report["tools"]
    diagnostics = report["diagnostics"]
    steps: list[dict[str, Any]] = []

    def add(title: str, status: str, why: str, command: str | None = None, evidence: str | None = None) -> None:
        item: dict[str, Any] = {"step": len(steps) + 1, "title": title, "status": status, "why": why}
        if command:
            item["command"] = command
        if evidence:
            item["evidence"] = evidence
        steps.append(item)

    if profile == "wsl2-gpu":
        if report["host"]["wsl"]:
            add("Confirm you are inside WSL2", "done", "Docking and MD tooling is supported on Linux/WSL2, not native Windows.", evidence=f"kernel release: {report['host']['release']}")
        else:
            add("Confirm you are inside WSL2", "handoff", "This kernel does not look like WSL2. Enable WSL2 from Windows (wsl --install) yourself; it is never automated.", evidence=f"kernel release: {report['host']['release']}")
    if tools["uv"]["available"]:
        add("Install uv (Python runner)", "done", "All workbench helper scripts run through uv for isolated, consistent execution.", evidence=tools["uv"]["path"])
    else:
        add("Install uv (Python runner)", "action-needed", "All workbench helper scripts run through uv for isolated, consistent execution.", command="curl -LsSf https://astral.sh/uv/install.sh | sh")
    if tools["micromamba"]["available"] or tools["mamba"]["available"] or tools["conda"]["available"]:
        found = tools["micromamba"]["path"] or tools["mamba"]["path"] or tools["conda"]["path"]
        add("Install a conda-family package manager", "done", "Scientific components install into per-component user-space prefixes via micromamba; an existing conda/mamba also satisfies detection.", evidence=found)
    else:
        add("Install micromamba", "action-needed", "Components are installed into per-component user-space prefixes; no administrator rights are needed.", command='"${SHELL}" <(curl -L micro.mamba.pm/install.sh)')
    if profile in {"wsl2-gpu", "linux-gpu"}:
        gpu_status = diagnostics["gpu"]["status"]
        if gpu_status == "available":
            add("Verify NVIDIA GPU visibility", "done", "GPU acceleration is used by GNINA and GROMACS builds that support it.", evidence=str(report["gpu"].get("stdout", "")).strip().splitlines()[0] if report["gpu"].get("stdout") else "nvidia-smi succeeded")
        elif gpu_status == "execution_isolation":
            add("Verify NVIDIA GPU visibility", "handoff", "This execution context looks isolated from the host GPU. Ask the agent for one authorized host-recheck before changing any host setting.")
        else:
            add("Verify NVIDIA GPU visibility", "handoff", "nvidia-smi failed on the host. Driver installation is a manual Windows/Linux administrator action, never automated.", evidence=str(report["gpu"].get("stderr") or report["gpu"].get("error") or "")[:200])
        docker_status = diagnostics["docker"]["status"]
        if docker_status == "available":
            add("Verify Docker route", "done", "Some prepared containers (for example GNINA images) use Docker.", evidence=tools["docker"]["path"])
        elif docker_status == "not_installed_or_not_on_path":
            add("Install Docker", "handoff", "Docker Desktop (WSL2) or a native Docker engine is an administrator-controlled install; the workbench only detects it.")
        else:
            add("Verify Docker route", "handoff", f"Docker is present but not usable from here ({docker_status}). Adding your user to the docker group or starting the daemon is a manual step.")
    for component in sorted(ALLOWED_COMPONENTS - {"uv"}):
        if component == "gromacs" and profile in {"wsl2-gpu", "linux-gpu"}:
            container = report["gromacs_container"]
            if container["available"]:
                add("Install gromacs", "done", "Uses the pinned GPU GROMACS Docker image.", evidence=f"{GROMACS_GPU_IMAGE} {container['probe'].get('stdout', '').strip()}")
            else:
                add("Install gromacs", "action-needed", "Uses the pinned GPU GROMACS Docker image instead of a native CUDA/GROMACS installation.", command=f"docker pull {GROMACS_GPU_IMAGE}")
            continue
        binary = COMPONENT_BINARIES[component]
        if tools[binary]["available"]:
            add(f"Install {component}", "done", f"Provides `{binary}`.", evidence=tools[binary]["path"])
        else:
            prefix = output_dir / "environments" / component
            channel_flags = " ".join(f"-c {channel}" for channel in package_channels(component))
            add(f"Install {component}", "action-needed", f"Provides `{binary}` in its own user-space prefix so components never break each other.", command=f"micromamba create -y -p {prefix} {channel_flags} {' '.join(PACKAGE_SPECS[component])}")
    if tools["gnina"]["available"]:
        add("Install GNINA", "done", "Primary docking engine with CNN rescoring; docking scores remain ranking outputs, not affinities.", evidence=tools["gnina"]["path"])
    else:
        add("Install GNINA", "handoff", "GNINA is distributed as a prebuilt binary from its GitHub releases page; download and PATH setup are manual. Vina remains the fallback engine.", command="https://github.com/gnina/gnina/releases")
    if report["chimerax"]["detected"]:
        add("Install ChimeraX (optional renderer)", "done", "Publication-grade structure rendering; PyMOL is the fallback.", evidence=report["chimerax"]["path"])
    else:
        add("Install ChimeraX (optional renderer)", "handoff", "ChimeraX is never downloaded automatically; use the official download page when you want it.", command=report["chimerax"]["official_download_handoff"])
    add("Verify the finished environment", "action-needed", "Re-run the readiness check after the steps above; it writes a receipt that docking and MD skills consume.", command=f"uv run scripts/molecular_modeling_environment.py verify --profile {profile} --output-dir {output_dir}")
    done = sum(1 for step in steps if step["status"] == "done")
    actionable = [step for step in steps if step["status"] == "action-needed"]
    handoffs = [step for step in steps if step["status"] == "handoff"]
    return {"schema_version": "1.0", "artifact_type": "molecular_modeling_onboarding_checklist", "created_at": stamp(), "profile": profile, "summary": {"total": len(steps), "done": done, "action_needed": len(actionable), "handoff": len(handoffs)}, "steps": steps, "report": report}


def checklist_markdown(checklist: dict[str, Any]) -> str:
    summary = checklist["summary"]
    lines = [f"# Onboarding checklist ({checklist['profile']})", "", f"{summary['done']}/{summary['total']} steps already satisfied; {summary['action_needed']} to run yourself; {summary['handoff']} manual handoffs.", ""]
    boxes = {"done": "[x]", "action-needed": "[ ]", "handoff": "[!]"}
    for step in checklist["steps"]:
        lines.append(f"{step['step']}. {boxes[step['status']]} **{step['title']}** — {step['why']}")
        if step.get("command"):
            lines.append(f"   - Command/handoff: `{step['command']}`")
        if step.get("evidence"):
            lines.append(f"   - Evidence: {step['evidence']}")
    lines.append("")
    lines.append("Statuses: `[x]` satisfied, `[ ]` run the command yourself, `[!]` manual handoff the workbench never automates.")
    lines.append("")
    return "\n".join(lines)


def remote_audit(host: str, profile: str) -> dict[str, Any]:
    command = ["ssh", "-o", "BatchMode=yes", host, "uname -s; uname -r; command -v gmx; command -v gnina; command -v vina; command -v docker; command -v conda; command -v mamba; command -v micromamba; command -v sbatch; nvidia-smi --query-gpu=name,driver_version --format=csv,noheader"]
    record = run_probe(command)
    return {"schema_version": "1.0", "artifact_type": "molecular_modeling_remote_environment_report", "created_at": stamp(), "profile": profile, "host": host, "read_only": True, "probe": record, "boundaries": ["no sudo", "no module changes", "no sbatch submission"]}


def host_recheck(profile: str) -> dict[str, Any]:
    report = add_diagnostics(audit(profile))
    return {"schema_version": "1.0", "artifact_type": "molecular_modeling_host_recheck_receipt", "created_at": stamp(), "profile": profile, "read_only": True, "authorization_boundary": "Run only after one explicit command authorization from the user.", "report": report, "conclusion": "host_accessible" if not report["diagnostics"]["host_recheck"]["recommended"] else "active_context_still_isolated"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("audit", "verify", "onboard"):
        p = sub.add_parser(name); p.add_argument("--profile", choices=PROFILES, required=True); p.add_argument("--output-dir", type=Path, required=True)
    p = sub.add_parser("plan"); p.add_argument("--profile", choices=PROFILES, required=True); p.add_argument("--components", required=True); p.add_argument("--output-dir", type=Path, required=True)
    p = sub.add_parser("bootstrap"); p.add_argument("--plan", type=Path, required=True); p.add_argument("--output-dir", type=Path, required=True)
    p = sub.add_parser("host-recheck"); p.add_argument("--profile", choices=("wsl2-gpu", "linux-gpu"), required=True); p.add_argument("--output-dir", type=Path, required=True)
    p = sub.add_parser("remote"); p.add_argument("--host", required=True); p.add_argument("--profile", choices=["linux-ssh"], required=True); p.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "audit":
            path = args.output_dir / "environment_report.json"; write_json(path, add_diagnostics(audit(args.profile, args.output_dir)))
        elif args.command == "verify":
            report = add_diagnostics(audit(args.profile, args.output_dir)); ready, warnings = readiness(report, args.profile); path = args.output_dir / "environment_receipt.json"; write_json(path, {"schema_version": "1.1", "artifact_type": "molecular_modeling_environment_receipt", "created_at": stamp(), "profile": args.profile, "ready": ready, "warnings": warnings, "report": report})
        elif args.command == "plan":
            plan = build_plan(args.profile, [v.strip() for v in args.components.split(",") if v.strip()], args.output_dir); path = args.output_dir / "install_plan.json"; write_json(path, plan); (args.output_dir / "install_plan.md").write_text("# Installation plan\n\n```json\n" + json.dumps(plan, indent=2) + "\n```\n", encoding="utf-8")
        elif args.command == "bootstrap":
            path = args.output_dir / "environment_receipt.json"; write_json(path, bootstrap(args.plan, args.output_dir))
        elif args.command == "host-recheck":
            path = args.output_dir / "host_recheck_receipt.json"; write_json(path, host_recheck(args.profile))
        elif args.command == "onboard":
            checklist = onboard(args.profile, args.output_dir); path = args.output_dir / "onboarding_checklist.json"; write_json(path, checklist); (args.output_dir / "onboarding_checklist.md").write_text(checklist_markdown(checklist), encoding="utf-8")
        else:
            path = args.output_dir / "environment_report.json"; write_json(path, remote_audit(args.host, args.profile))
    except EnvironmentError as exc:
        print(f"Error: {exc}", file=sys.stderr); raise SystemExit(1)
    print(f"Success! Data written to: {path}")
    if args.command == "verify" and not ready:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
