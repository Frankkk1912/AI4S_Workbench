"""Pre-launch resource checks (M1 T1.5). Fail closed, always audited.

Before a submission may launch, the working directory's volume must have at
least 2x the estimated artifact size free (D7) and docker must be reachable.
Any failure rejects the submission with a readable reason; both the decision
and its evidence land in audit_log. An unreadable environment is never treated
as "probably fine".
"""

from __future__ import annotations

import shutil
import sqlite3

from . import db
from .reconcile import DockerPort


class PreflightError(ValueError):
    """Raised when preflight must fail closed (readable reason attached)."""


def check_disk(work_dir: str, estimated_bytes: int, factor: int = 2) -> dict:
    """Disk headroom check (D7: free < 2x estimated artifacts -> reject)."""
    try:
        usage = shutil.disk_usage(str(work_dir))
    except OSError as exc:
        return {
            "ok": False,
            "free_bytes": None,
            "required_bytes": factor * int(estimated_bytes),
            "reason": f"cannot inspect the work directory's disk: {exc}",
        }
    required = factor * int(estimated_bytes)
    ok = usage.free >= required
    return {
        "ok": ok,
        "free_bytes": usage.free,
        "required_bytes": required,
        "reason": None
        if ok
        else (
            f"insufficient disk space for {work_dir}: {usage.free} bytes free, "
            f"but {required} bytes (2x the estimated {int(estimated_bytes)}-byte artifacts) are required"
        ),
    }


def check_docker(docker: DockerPort) -> dict:
    """Docker reachability check; unreachable docker fails closed."""
    try:
        reachable = docker.is_reachable()
    except Exception as exc:  # noqa: BLE001 - any docker failure must fail closed
        return {"ok": False, "reason": f"docker is not reachable: {exc}"}
    if not reachable:
        return {
            "ok": False,
            "reason": "docker is not reachable; resolve the environment before submitting",
        }
    return {"ok": True, "reason": None}


def run_preflight(
    conn: sqlite3.Connection,
    work_dir: str,
    estimated_bytes: int,
    docker: DockerPort,
    subject: str,
    actor: str = "runner",
) -> dict:
    """Run both checks, audit evidence, and fail closed on any failure."""
    disk = check_disk(work_dir, estimated_bytes)
    docker_result = check_docker(docker)
    db.audit(
        conn,
        actor,
        "preflight_disk",
        subject=subject,
        detail=f"ok={disk['ok']} free={disk['free_bytes']} required={disk['required_bytes']}",
    )
    db.audit(
        conn,
        actor,
        "preflight_docker",
        subject=subject,
        detail=f"ok={docker_result['ok']}",
    )
    if not disk["ok"]:
        raise PreflightError(disk["reason"] or "disk preflight failed")
    if not docker_result["ok"]:
        raise PreflightError(docker_result["reason"] or "docker preflight failed")
    return {"ok": True, "disk": disk, "docker": docker_result}
