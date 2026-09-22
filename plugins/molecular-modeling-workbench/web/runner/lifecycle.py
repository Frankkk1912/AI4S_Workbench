"""Safe stop, checkpoint content validation, and recovery (M3 T3.3).

Stopping is SIGTERM-only. The runner sends `docker kill --signal=TERM` to a
verified, run-owned container and then independently observes the grace period
(D13: at least max(2x checkpoint interval, 15 minutes)). `docker stop` is
NEVER used: its finite timeout escalates to an unauthorized SIGKILL. If grace
elapses without a safe checkpoint the run moves to `attention` and the user
must handle it explicitly; a force kill (SIGKILL) requires separate explicit
authorization and never claims "safely stopped".

Checkpoint recovery refuses anything weaker than a content-level check:
existence + non-empty is not enough. A recovered checkpoint must pass (1) a
GROMACS readability probe in the same pinned container, (2) TPR/system +
attempt-origin consistency with step/time compatibility, and (3) a recorded
checksum. Resume = user approval -> a new attempt via `--resume`/`-cpi`.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from . import db, mdcli, submission
from .reconcile import DockerPort

DEFAULT_CHECKPOINT_INTERVAL_MINUTES = 15
MIN_GRACE_MINUTES = 15


class LifecycleError(ValueError):
    """Raised when a stop/recovery action must fail closed."""


class LifecycleDocker(DockerPort):
    """Docker adapter for lifecycle signals; never uses `docker stop`."""

    def signal_container(self, container_id: str, signal: str = "TERM") -> str:
        result = self._run(["kill", f"--signal={signal}", container_id])
        if result.returncode != 0:
            raise LifecycleError(
                f"docker kill --signal={signal} {container_id} failed "
                f"({result.returncode}): {result.stderr.strip()}"
            )
        return container_id


def grace_seconds(
    checkpoint_interval_minutes: float = DEFAULT_CHECKPOINT_INTERVAL_MINUTES,
    min_grace_minutes: float = MIN_GRACE_MINUTES,
) -> int:
    """Grace = max(2x checkpoint interval, 15 minutes), in seconds (D13)."""
    return int(max(2.0 * float(checkpoint_interval_minutes), min_grace_minutes) * 60)


def verify_signal_forwarding(receipt: dict, container_image_digest: str | None) -> bool:
    """Confirm the container runs the receipt-bound GROMACS image.

    The pinned `nvcr.io/nvidia/gromacs` entrypoint forwards SIGTERM to gmx, so
    a matching digest is the signal-forwarding gate. A mismatch means we must
    not signal the container (fail closed).
    """
    container = receipt.get("report", {}).get("gromacs_container", {})
    if not isinstance(container, dict):
        container = {}
    pinned = container.get("digest")
    return (
        container.get("available") is True
        and isinstance(pinned, str)
        and "@sha256:" in pinned
        and container_image_digest == pinned
    )


def _owned_container(
    conn: sqlite3.Connection, run_id: str, container_id: str
) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM containers WHERE container_id = ? AND run_id = ?",
        (container_id, run_id),
    ).fetchone()
    if row is None:
        raise LifecycleError(f"Container {container_id} is not owned by run {run_id}.")
    return row


def request_stop(
    conn: sqlite3.Connection,
    run_id: str,
    docker,
    receipt: dict,
    container_id: str | None = None,
    actor: str = "user",
) -> dict:
    """Send SIGTERM only, after identity + signal-forwarding verification."""
    cid = container_id
    if cid is None:
        row = conn.execute(
            "SELECT container_id FROM containers WHERE run_id = ? "
            "ORDER BY first_seen_at DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        if row is None:
            raise LifecycleError(
                f"No recorded container for run {run_id}; cannot signal."
            )
        cid = row["container_id"]
    row = _owned_container(conn, run_id, cid)
    if not verify_signal_forwarding(receipt, row["image_digest"]):
        raise LifecycleError(
            "Container entrypoint does not forward SIGTERM to GROMACS; refusing to stop."
        )
    status = db.run_status(conn, run_id)
    if status != "running":
        raise LifecycleError(f"Run {run_id} is {status}; cannot request stop.")
    docker.signal_container(cid, "TERM")
    db.set_run_status(
        conn, run_id, "stopping", actor=actor, detail=f"SIGTERM sent to {cid}"
    )
    db.audit(
        conn,
        actor,
        "stop_requested",
        subject=run_id,
        detail=f"container={cid} signal=TERM",
    )
    return {"container_id": cid, "signal": "TERM", "status": "stopping"}


def mark_grace_timeout(
    conn: sqlite3.Connection, run_id: str, actor: str = "runner"
) -> dict:
    """Grace elapsed without a safe checkpoint: escalate to attention.

    There is deliberately no automatic SIGKILL here; the user decides.
    """
    db.set_run_status(
        conn,
        run_id,
        "attention",
        actor=actor,
        detail="SIGTERM grace elapsed without a safe checkpoint; user handling required",
    )
    db.audit(conn, actor, "stop_grace_timeout", subject=run_id)
    return {"run_id": run_id, "status": "attention"}


def force_kill(
    conn: sqlite3.Connection,
    run_id: str,
    docker,
    container_id: str,
    authorized: bool = False,
    actor: str = "user",
) -> dict:
    """SIGKILL only under explicit authorization; never claims a safe stop."""
    if not authorized:
        raise LifecycleError(
            "Force kill requires explicit user authorization and does not promise a new checkpoint."
        )
    _owned_container(conn, run_id, container_id)
    docker.signal_container(container_id, "KILL")
    db.set_run_status(
        conn,
        run_id,
        "attention",
        actor=actor,
        detail="force kill (SIGKILL); no new checkpoint promised",
    )
    db.audit(
        conn,
        actor,
        "force_kill_authorized",
        subject=run_id,
        detail=f"container={container_id}",
    )
    return {
        "container_id": container_id,
        "signal": "KILL",
        "safely_stopped": False,
        "status": "attention",
    }


def checkpoint_probe_command(
    receipt: dict, work: str | Path, cpt: str | Path, tpr: str | Path
) -> list[str]:
    """Build the same-digest `gmx check -f <cpt> -s1 <tpr>` probe vector."""
    from . import mdcli

    work_path = Path(work)
    module = mdcli.load_md_run_cli()
    return module.gromacs_command(
        receipt,
        work_path,
        [
            "gmx",
            "check",
            "-f",
            str(Path(cpt).resolve().relative_to(work_path.resolve())),
            "-s1",
            str(Path(tpr).resolve().relative_to(work_path.resolve())),
        ],
    )


def _attempt_exists(
    conn: sqlite3.Connection, run_id: str, stage: str, attempt_id: int
) -> bool:
    row = conn.execute(
        "SELECT 1 FROM attempts WHERE run_id = ? AND stage = ? AND attempt_id = ?",
        (run_id, stage, attempt_id),
    ).fetchone()
    return row is not None


def validate_checkpoint(
    conn: sqlite3.Connection,
    run_id: str,
    stage: str,
    attempt_id: int,
    cpt_path: str | Path,
    tpr_path: str | Path,
    *,
    probe=None,
    expected_checksum: str | None = None,
    cpt_step: int | None = None,
    log_step: int | None = None,
) -> dict:
    """Content-level checkpoint validation; returns a verdict dict.

    Existence + non-empty is deliberately NOT sufficient: the checkpoint must
    pass the readability probe, match the recorded checksum, belong to a real
    attempt, bind a non-empty TPR, and be step/time compatible with the same
    attempt's log (not required to equal the log's last step — the two write at
    different frequencies).
    """
    cpt = Path(cpt_path)
    tpr = Path(tpr_path)
    if not cpt.is_file() or cpt.stat().st_size == 0:
        return {"valid": False, "reason": "checkpoint is missing or empty"}
    checksum = hashlib.sha256(cpt.read_bytes()).hexdigest()
    if expected_checksum is not None and checksum != expected_checksum:
        return {
            "valid": False,
            "reason": "checkpoint checksum does not match the recorded value",
            "checksum": checksum,
        }
    if probe is not None:
        try:
            accepted = probe(cpt, tpr)
        except Exception as exc:  # noqa: BLE001 - any probe failure must fail closed
            return {
                "valid": False,
                "reason": f"checkpoint readability probe failed: {exc}",
            }
        if not accepted:
            return {
                "valid": False,
                "reason": "GROMACS checkpoint readability probe rejected the checkpoint",
            }
    if not tpr.is_file() or tpr.stat().st_size == 0:
        return {"valid": False, "reason": "associated TPR is missing or empty"}
    if not _attempt_exists(conn, run_id, stage, attempt_id):
        return {
            "valid": False,
            "reason": "checkpoint does not belong to a recorded attempt",
        }
    if cpt_step is not None and log_step is not None and int(cpt_step) > int(log_step):
        return {
            "valid": False,
            "reason": "checkpoint step is ahead of the same-attempt log",
        }
    return {
        "valid": True,
        "checksum": checksum,
        "stage": stage,
        "attempt_id": attempt_id,
    }


def approve_resume(
    conn: sqlite3.Connection,
    run_id: str,
    stage: str,
    attempt_id: int,
    cpt_path: str | Path,
    tpr_path: str | Path,
    *,
    probe=None,
    expected_checksum: str | None = None,
    cpt_step: int | None = None,
    log_step: int | None = None,
    stage_plan_path: str | Path | None = None,
    actor: str = "user",
) -> dict:
    """User-approved checkpoint recovery: validate then enqueue a new attempt."""
    verdict = validate_checkpoint(
        conn,
        run_id,
        stage,
        attempt_id,
        cpt_path,
        tpr_path,
        probe=probe,
        expected_checksum=expected_checksum,
        cpt_step=cpt_step,
        log_step=log_step,
    )
    if not verdict["valid"]:
        raise LifecycleError(f"Checkpoint recovery refused: {verdict['reason']}")
    run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise LifecycleError(f"Unknown run: {run_id}")
    if run["status"] not in ("interrupted", "stopped"):
        raise LifecycleError(
            f"Run {run_id} is {run['status']}; resume requires interrupted or stopped."
        )
    if stage_plan_path is not None:
        plan_path = Path(stage_plan_path).resolve()
        plan = mdcli.load_md_run_cli().read_stage_plan(plan_path)
        if plan["stage"] != stage or not plan.get("resume"):
            raise LifecycleError(
                "Resume stage plan must match the stage and enable checkpoint resume."
            )
        conn.execute(
            "UPDATE runs SET stage_plan_path = ? WHERE run_id = ?",
            (str(plan_path), run_id),
        )
    new_attempt = submission.allocate_attempt(
        conn, run_id, stage, run["work_dir"], kind="resume"
    )
    db.set_run_status(
        conn,
        run_id,
        "queued",
        actor=actor,
        detail=f"resume approved from checkpoint (attempt {new_attempt})",
    )
    db.audit(
        conn,
        actor,
        "resume_approved",
        subject=run_id,
        detail=f"stage={stage} attempt_id={new_attempt} cpt_checksum={verdict['checksum']}",
    )
    return {
        "run_id": run_id,
        "stage": stage,
        "attempt_id": new_attempt,
        "status": "queued",
        "cpt_checksum": verdict["checksum"],
    }
