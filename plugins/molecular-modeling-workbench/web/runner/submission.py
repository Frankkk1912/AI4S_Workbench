"""Request idempotency and attempt registration (M1 T1.4).

The submission idempotency key is the client request_id (NOT the execution
attempt): a repeated request returns the existing run's state. Execution
attempts are allocated server-side as monotonic (run_id, stage, attempt_id)
triples, so retries and resumes create NEW attempts and never collide with the
deterministic container names of previous attempts. Registration is two-phase
(intent row before docker runs, container row after) so the crash window
between intent and container creation is always discoverable.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from . import db, mdcli

# Task kinds: container-backed MD stages vs native (uv locked) analysis tasks.
# Analysis reuses the same idempotency / lock / audit channels and the T1.7
# interruption handling, but is executed locally (GROMACS containers are only
# used for the scientific-computation path; analysis never re-runs MD).
TASK_KINDS = ("container", "analysis")
ANALYSIS_STAGE = "analysis"


class SubmissionError(ValueError):
    """Raised when a submission must be refused (readable reason attached)."""


def submit_run(
    conn: sqlite3.Connection,
    request_id: str,
    project: str,
    stage: str,
    work_dir: str,
    manifest_path: str | None = None,
    stage_plan_path: str | None = None,
    actor: str = "runner",
    kind: str = "container",
) -> dict:
    """Idempotent run submission keyed by request_id.

    ``kind`` selects the task type: ``container`` (MD stage) or ``analysis``
    (native uv CLI). The ``analysis`` stage is reserved for analysis tasks, and
    analysis tasks must use it, so the two task types can never collide in the
    stage namespace while still sharing the same work_dir single-active lock.
    """
    if kind not in TASK_KINDS:
        raise SubmissionError(f"unsupported task kind: {kind!r}")
    if kind == "analysis" and stage != ANALYSIS_STAGE:
        raise SubmissionError(f"analysis tasks must use stage {ANALYSIS_STAGE!r}")
    if kind != "analysis" and stage == ANALYSIS_STAGE:
        raise SubmissionError(
            f"stage {ANALYSIS_STAGE!r} is reserved for analysis tasks"
        )

    existing = conn.execute(
        "SELECT * FROM runs WHERE request_id = ?", (request_id,)
    ).fetchone()
    if existing is not None:
        db.audit(
            conn,
            actor,
            "run_request_deduplicated",
            subject=existing["run_id"],
            detail=request_id,
        )
        return {"run": existing, "created": False}
    run_id = uuid.uuid4().hex[:12]
    stamp = db.now()
    try:
        conn.execute("BEGIN IMMEDIATE")
        # Recheck after acquiring the write lock. Two simultaneous requests can
        # both miss the fast-path SELECT above; the loser must still deduplicate.
        existing = conn.execute(
            "SELECT * FROM runs WHERE request_id = ?", (request_id,)
        ).fetchone()
        if existing is not None:
            conn.execute("COMMIT")
            db.audit(
                conn,
                actor,
                "run_request_deduplicated",
                subject=existing["run_id"],
                detail=request_id,
            )
            return {"run": existing, "created": False}
        active = conn.execute(
            "SELECT run_id, stage FROM runs WHERE work_dir = ? AND status IN ('queued','running','stopping')",
            (str(work_dir),),
        ).fetchone()
        if active is not None:
            raise SubmissionError(
                f"work_dir {work_dir} already has an active stage "
                f"({active['stage']}, run {active['run_id']}); concurrent stages are refused."
            )
        conn.execute(
            "INSERT INTO runs(run_id, request_id, project, stage, status, work_dir, "
            "manifest_path, stage_plan_path, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                run_id,
                request_id,
                project,
                stage,
                "queued",
                str(work_dir),
                manifest_path,
                stage_plan_path,
                stamp,
                stamp,
            ),
        )
        conn.execute("COMMIT")
    except sqlite3.IntegrityError:
        conn.execute("ROLLBACK")
        existing = conn.execute(
            "SELECT * FROM runs WHERE request_id = ?", (request_id,)
        ).fetchone()
        if existing is None:
            raise
        db.audit(
            conn,
            actor,
            "run_request_deduplicated",
            subject=existing["run_id"],
            detail=request_id,
        )
        return {"run": existing, "created": False}
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    db.audit(
        conn,
        actor,
        "run_submitted",
        subject=run_id,
        detail=f"request_id={request_id} stage={stage}",
    )
    run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return {"run": run, "created": True}


def allocate_attempt(
    conn: sqlite3.Connection,
    run_id: str,
    stage: str,
    work_dir: str,
    kind: str = "container",
    actor: str = "runner",
) -> int:
    """Allocate the next attempt identity for (run_id, stage) and record intent.

    The intent row exists BEFORE docker is ever invoked, so a crash between
    intent and container creation is discoverable by reconcile (T1.3).
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT COALESCE(MAX(attempt_id), 0) FROM attempts WHERE run_id = ? AND stage = ?",
            (run_id, stage),
        ).fetchone()
        attempt_id = int(row[0]) + 1
        module = mdcli.load_md_run_cli()
        container_name = module.launch_container_name(run_id, stage, attempt_id)
        conn.execute(
            "INSERT INTO attempts(attempt_id, run_id, stage, status, kind, container_name, "
            "work_dir, intent_at, boot_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                attempt_id,
                run_id,
                stage,
                "intent",
                kind,
                container_name,
                str(work_dir),
                db.now(),
                db.current_boot_id(),
            ),
        )
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    db.audit(
        conn,
        actor,
        "attempt_intent_recorded",
        subject=run_id,
        detail=f"stage={stage} attempt_id={attempt_id} name={container_name}",
    )
    return attempt_id


def bind_attempt_identity(
    conn: sqlite3.Connection,
    run_id: str,
    stage: str,
    attempt_id: int,
    *,
    image_digest: str,
    work_dir_hash: str,
    command_hash: str,
    ownership_labels: dict[str, str],
    cid_file: str | None = None,
    actor: str = "runner",
) -> None:
    """Persist launch identity before Docker starts, closing the crash window."""
    required = {
        "ai4s.workbench.run_id": run_id,
        "ai4s.workbench.stage": stage,
        "ai4s.workbench.attempt": str(attempt_id),
        "ai4s.workbench.image_digest": image_digest,
        "ai4s.workbench.work_dir_hash": work_dir_hash,
        "ai4s.workbench.command_hash": command_hash,
    }
    if any(ownership_labels.get(key) != value for key, value in required.items()):
        raise SubmissionError("launch identity labels do not match the attempt")
    cursor = conn.execute(
        "UPDATE attempts SET image_digest=?, work_dir_hash=?, command_hash=?, "
        "ownership_labels=?, cid_file=? WHERE run_id=? AND stage=? AND attempt_id=? "
        "AND status='intent' AND container_at IS NULL",
        (
            image_digest,
            work_dir_hash,
            command_hash,
            json.dumps(ownership_labels, sort_keys=True),
            cid_file,
            run_id,
            stage,
            attempt_id,
        ),
    )
    if cursor.rowcount != 1:
        raise SubmissionError("launch identity requires an unstarted intent attempt")
    db.audit(
        conn,
        actor,
        "attempt_identity_bound",
        subject=run_id,
        detail=f"stage={stage} attempt_id={attempt_id}",
    )


def record_container(
    conn: sqlite3.Connection,
    run_id: str,
    stage: str,
    attempt_id: int,
    launch_receipt_path: str,
    actor: str = "runner",
) -> None:
    """Second registration phase: the detached container exists (crash closed)."""
    receipt = json.loads(Path(launch_receipt_path).read_text(encoding="utf-8"))
    labels = receipt.get("labels", {})
    attempt = conn.execute(
        "SELECT * FROM attempts WHERE run_id=? AND stage=? AND attempt_id=?",
        (run_id, stage, attempt_id),
    ).fetchone()
    if attempt is None or not attempt["ownership_labels"]:
        raise SubmissionError("launch identity was not bound before Docker started")
    expected_labels = json.loads(attempt["ownership_labels"])
    if (
        receipt.get("gromacs_image_digest") != attempt["image_digest"]
        or labels != expected_labels
        or labels.get("ai4s.workbench.work_dir_hash") != attempt["work_dir_hash"]
        or labels.get("ai4s.workbench.command_hash") != attempt["command_hash"]
    ):
        raise SubmissionError("launch receipt does not match the bound attempt identity")
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE attempts SET status = 'launched', container_at = ?, image_digest = ?, "
            "work_dir_hash = ?, command_hash = ?, ownership_labels = ?, cid_file = ?, "
            "receipt_path = ? WHERE run_id = ? AND stage = ? AND attempt_id = ?",
            (
                db.now(),
                receipt.get("gromacs_image_digest"),
                labels.get("ai4s.workbench.work_dir_hash"),
                labels.get("ai4s.workbench.command_hash"),
                json.dumps(labels, sort_keys=True),
                receipt.get("cid_file"),
                str(launch_receipt_path),
                run_id,
                stage,
                attempt_id,
            ),
        )
        conn.execute(
            "INSERT INTO containers(container_id, attempt_id, run_id, stage, name, image_digest, labels, state, first_seen_at) "
            "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(container_id) DO UPDATE SET state = excluded.state",
            (
                receipt["container_id"],
                attempt_id,
                run_id,
                stage,
                receipt["container_name"],
                receipt.get("gromacs_image_digest"),
                json.dumps(labels, sort_keys=True),
                "running",
                db.now(),
            ),
        )
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    db.audit(
        conn,
        actor,
        "attempt_container_recorded",
        subject=run_id,
        detail=f"stage={stage} attempt_id={attempt_id} container={receipt['container_id']}",
    )
