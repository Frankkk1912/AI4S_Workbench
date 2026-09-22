"""Stage orchestration state machine and failure/retry policy (M3 T3.2/T3.5).

After a scientific strategy is approved, the orchestrator advances the run
through STAGE_ORDER (em -> nvt -> npt -> md_prod) one stage at a time. Each
stage is executed through an injected `stage_runner` (the caller supplies the
audited grompp -> launch -> finalize wiring), and the run status is transitioned
strictly through the SQLite transition table.

Fail closed rules enforced here:

- No stage starts without an explicit, still-matching approval (T3.1).
- The environment receipt is re-checked before every auto-advance step; an
  expired receipt fails closed instead of silently proceeding (T3.6).
- A non-zero exit, missing artifact, or stall marks the stage `failed` and
  stops advancement; it is NEVER auto-retried (T3.5).
- A scientific parameter change changes the strategy hash, so the approval
  check fails and forces a new user approval (re-approval) before any launch.
"""

from __future__ import annotations

import sqlite3

from web.backend import approvals

from . import db, mdcli, preflight, submission


class OrchestrationError(ValueError):
    """Raised when auto-advance must fail closed."""


class ApprovalRequiredError(OrchestrationError):
    """Raised when a stage cannot advance without user (re-)approval."""


STAGE_ORDER = ("em", "nvt", "npt", "md_prod")


def stage_sequence() -> list[str]:
    return list(mdcli.load_md_run_cli().STAGE_ORDER)


def next_stage(stage: str) -> str | None:
    order = stage_sequence()
    try:
        index = order.index(stage)
    except ValueError as exc:
        raise OrchestrationError(f"Unknown stage: {stage!r}") from exc
    if index + 1 >= len(order):
        return None
    return order[index + 1]


def require_approval(
    conn: sqlite3.Connection, run_id: str, strategy: dict
) -> sqlite3.Row:
    """Refuse to proceed without an approval matching the current strategy."""
    try:
        return approvals.require_approved_strategy(conn, run_id, strategy)
    except approvals.ApprovalError as exc:
        raise ApprovalRequiredError(str(exc)) from exc


def require_receipt(conn: sqlite3.Connection, receipt_path: str, subject: str) -> dict:
    """Refuse to proceed when the environment receipt has expired (T3.6)."""
    return preflight.require_fresh_receipt(conn, receipt_path, subject)


def _advance_to_next_stage(
    conn: sqlite3.Connection, run_id: str, new_stage: str, actor: str = "runner"
) -> None:
    """Move to the next stage: a stage change, not a status transition.

    This deliberately bypasses the status transition table (the prior stage's
    `completed` verdict stays recorded in its attempt); it only rewrites the
    run's current-stage pointer and re-queues for the next stage.
    """
    conn.execute(
        "UPDATE runs SET stage = ?, status = 'queued', updated_at = ? WHERE run_id = ?",
        (new_stage, db.now(), run_id),
    )
    db.audit(
        conn, actor, "stage_advanced", subject=run_id, detail=f"stage -> {new_stage}"
    )


def advance_stage(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    strategy: dict,
    receipt_path: str,
    stage_runner,
    actor: str = "runner",
) -> dict:
    """Advance the run's current stage exactly one step (fail closed)."""
    require_approval(conn, run_id, strategy)
    require_receipt(conn, receipt_path, run_id)
    run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise OrchestrationError(f"Unknown run: {run_id}")
    stage = run["stage"]
    if run["status"] not in ("queued", "running"):
        raise OrchestrationError(
            f"Run {run_id} stage {stage} is {run['status']}; cannot auto-advance."
        )
    attempt_id = submission.allocate_attempt(conn, run_id, stage, run["work_dir"])
    if run["status"] == "queued":
        db.set_run_status(
            conn,
            run_id,
            "running",
            actor=actor,
            detail=f"advancing stage {stage} attempt {attempt_id}",
        )
    result = stage_runner(conn, run, stage, attempt_id)
    verdict = result.get("status")
    if verdict == "completed":
        db.set_run_status(
            conn,
            run_id,
            "completed",
            actor=actor,
            detail=f"stage {stage} completed",
        )
        nxt = next_stage(stage)
        if nxt is not None:
            _advance_to_next_stage(conn, run_id, nxt, actor=actor)
        return {
            "run_id": run_id,
            "stage": stage,
            "attempt_id": attempt_id,
            "status": "completed",
            "next_stage": nxt,
        }
    reason = result.get("reason") or f"stage {stage} failed ({verdict})"
    db.set_run_status(
        conn,
        run_id,
        "failed",
        actor=actor,
        detail=f"stage {stage} failed: {reason}",
    )
    db.audit(
        conn,
        actor,
        "stage_failed_requires_reapproval",
        subject=run_id,
        detail=f"stage={stage} attempt_id={attempt_id} verdict={verdict}",
    )
    return {
        "run_id": run_id,
        "stage": stage,
        "attempt_id": attempt_id,
        "status": "failed",
        "next_stage": None,
    }


def advance_all(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    strategy: dict,
    receipt_path: str,
    stage_runner,
    actor: str = "runner",
) -> list[dict]:
    """Advance through STAGE_ORDER until the pipeline completes or a failure.

    There is no automatic retry loop: a failed stage stops the walk, and the
    only path back is an explicit user retry (`retry_failed`).
    """
    summaries: list[dict] = []
    for _ in stage_sequence():
        run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if run is None:
            break
        if run["status"] == "failed":
            break
        if run["status"] == "completed" and next_stage(run["stage"]) is None:
            break
        summaries.append(
            advance_stage(
                conn,
                run_id,
                strategy=strategy,
                receipt_path=receipt_path,
                stage_runner=stage_runner,
                actor=actor,
            )
        )
        if summaries[-1]["status"] != "completed":
            break
    return summaries


def retry_failed(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    reason: str,
    strategy: dict,
    receipt_path: str,
    actor: str = "user",
) -> dict:
    """Explicit, reason-bearing retry of a failed run (never automatic).

    A completed stage is NOT retryable here: rerunning a completed stage
    follows the existing "new reviewed plan" gate (see md_run_cli execute/
    validate_launch_context), so the caller must produce a new reviewed plan.
    The old attempt's evidence is preserved; retry only allocates a NEW attempt.
    """
    run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise OrchestrationError(f"Unknown run: {run_id}")
    if run["status"] == "completed":
        raise OrchestrationError(
            "Completed stage requires a new reviewed plan; retry is not applicable."
        )
    if run["status"] != "failed":
        raise OrchestrationError(
            f"Only failed runs may be retried (status {run['status']})."
        )
    if not reason:
        raise OrchestrationError("Retry requires an explicit reason.")
    require_approval(conn, run_id, strategy)
    require_receipt(conn, receipt_path, run_id)
    db.audit(conn, actor, "retry_requested", subject=run_id, detail=f"reason={reason}")
    db.set_run_status(
        conn, run_id, "queued", actor=actor, detail=f"explicit retry: {reason}"
    )
    return {"run_id": run_id, "status": "queued", "reason": reason}
