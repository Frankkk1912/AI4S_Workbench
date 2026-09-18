"""Pre-launch resource checks (M1 T1.5). Fail closed, always audited.

Before a submission may launch, the working directory's volume must have at
least 2x the estimated artifact size free (D7) and docker must be reachable.
Any failure rejects the submission with a readable reason; both the decision
and its evidence land in audit_log. An unreadable environment is never treated
as "probably fine".
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

from . import db
from .reconcile import DockerPort

RECEIPT_MAX_AGE_DAYS = 7
RECEIPT_EXPIRY_WARNING_DAYS = 1


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


def receipt_age_days(receipt: dict, now_utc: dt.datetime | None = None) -> float:
    """Age of an environment receipt in days (same 7-day boundary as the CLI)."""
    created = dt.datetime.fromisoformat(receipt["created_at"].replace("Z", "+00:00"))
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    return (now_utc - created.astimezone(dt.timezone.utc)).total_seconds() / 86400.0


def receipt_boundary(
    receipt: dict,
    max_age_days: int = RECEIPT_MAX_AGE_DAYS,
    warning_days: int = RECEIPT_EXPIRY_WARNING_DAYS,
    now_utc: dt.datetime | None = None,
) -> dict:
    """Classify a receipt as fresh / expiring / expired (T3.6).

    Expiry only ever blocks NEW submissions or auto-advance; it never stops a
    running container. The near-expiry band drives the UI warning.
    """
    age = receipt_age_days(receipt, now_utc)
    if age > max_age_days:
        status = "expired"
    elif age >= (max_age_days - warning_days):
        status = "expiring"
    else:
        status = "fresh"
    return {
        "status": status,
        "age_days": round(age, 3),
        "remaining_days": round(max_age_days - age, 3),
        "created_at": receipt.get("created_at"),
        "max_age_days": max_age_days,
    }


def require_fresh_receipt(
    conn: sqlite3.Connection,
    receipt_path: str,
    subject: str,
    max_age_days: int = RECEIPT_MAX_AGE_DAYS,
    actor: str = "runner",
) -> dict:
    """Fail closed when a receipt has expired; always audit the boundary.

    This is the web-layer boundary that keeps stale credentials from starting
    new work. It does not change `md_run_cli.validate_receipt` (whose hard
    7-day check remains the scientific gate) and never touches a running
    container.
    """
    path = Path(receipt_path)
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreflightError(f"cannot read environment receipt {path}: {exc}") from exc
    boundary = receipt_boundary(receipt, max_age_days=max_age_days)
    db.audit(
        conn,
        actor,
        "receipt_boundary",
        subject=subject,
        detail=json.dumps(boundary, sort_keys=True),
    )
    if boundary["status"] == "expired":
        raise PreflightError(
            "Environment receipt is older than 7 days; re-run environment verify "
            "before submitting or advancing."
        )
    return boundary


def receipt_sha256_of(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record_receipt_verification(
    conn: sqlite3.Connection,
    previous_receipt_path: str,
    new_receipt_path: str,
    actor: str = "user",
) -> dict:
    """Record an immutable re-verify lineage (new hash -> old hash).

    Re-verification produces a NEW immutable receipt; the lineage row is keyed
    by the new receipt's hash and references the previous receipt's hash. No
    historical hash reference is rewritten in place.
    """
    previous_path = Path(previous_receipt_path)
    new_path = Path(new_receipt_path)
    new_sha = receipt_sha256_of(new_path)
    previous_sha = receipt_sha256_of(previous_path) if previous_path.is_file() else None
    if previous_sha is not None and previous_sha == new_sha:
        raise PreflightError(
            "Re-verify must produce a new receipt; the hashes are identical."
        )
    conn.execute(
        "INSERT INTO receipt_lineage(receipt_sha256, previous_sha256, receipt_path, verified_at) "
        "VALUES (?,?,?,?) ON CONFLICT(receipt_sha256) DO NOTHING",
        (new_sha, previous_sha, str(new_path.resolve()), db.now()),
    )
    db.audit(
        conn,
        actor,
        "receipt_reverified",
        subject=str(new_path),
        detail=f"previous={previous_sha} new={new_sha}",
    )
    return {
        "new_sha256": new_sha,
        "previous_sha256": previous_sha,
        "path": str(new_path.resolve()),
    }
