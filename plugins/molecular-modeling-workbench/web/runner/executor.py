# pyright: reportMissingImports=false
"""Concrete hosted-container execution loop for the user-owned runner.

This module closes the boundary between the persisted queue and the audited
``md_run_cli`` launch/finalize contracts.  Approval remains file+hash
controlled; Docker is only invoked after attempt identity is durably recorded.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from web.backend import approvals

from . import db, finalize, mdcli, preflight, reconcile, submission


class ExecutorError(RuntimeError):
    """Raised when a queued run cannot be executed safely."""


def _load_json(path: str | Path) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExecutorError(f"Cannot read JSON artifact {path}: {exc}") from exc


def _verified_approval(conn: sqlite3.Connection, run_id: str) -> dict | None:
    row = approvals.latest_approval(conn, run_id, kind="strategy")
    if row is None:
        return None
    return approvals.verify_approval_artifact(conn, row)


def _artifact_paths(work_dir: str | Path, container_name: str) -> dict[str, Path]:
    root = Path(work_dir).resolve() / ".runner"
    root.mkdir(parents=True, exist_ok=True)
    return {
        "plan": root / f"{container_name}.launch-plan.json",
        "launch": root / f"{container_name}.launch-receipt.json",
        "finalize": root / f"{container_name}.finalize-receipt.json",
    }


def launch_approved(
    conn: sqlite3.Connection,
    docker: reconcile.DockerPort,
    *,
    actor: str = "runner",
    module=None,
) -> list[dict]:
    """Launch approved queued runs that do not yet have an attempt."""
    module = module or mdcli.load_md_run_cli()
    summaries: list[dict] = []
    queued = conn.execute(
        "SELECT * FROM runs WHERE status = 'queued' ORDER BY created_at, run_id"
    ).fetchall()
    for run in queued:
        run_id = run["run_id"]
        existing = conn.execute(
            "SELECT 1 FROM attempts WHERE run_id = ? LIMIT 1", (run_id,)
        ).fetchone()
        if existing is not None:
            continue
        approval = _verified_approval(conn, run_id)
        if approval is None:
            summaries.append(
                {"run_id": run_id, "action": "waiting", "reason": "approval required"}
            )
            continue
        try:
            manifest = _load_json(run["manifest_path"])
            receipt_path = manifest["environment_receipt"]["path"]
            preflight.require_fresh_receipt(conn, receipt_path, run_id, actor=actor)
            preflight.run_preflight(
                conn, run["work_dir"], 0, docker, run_id, actor=actor
            )
            attempt_id = submission.allocate_attempt(
                conn, run_id, run["stage"], run["work_dir"], actor=actor
            )
            attempt = conn.execute(
                "SELECT * FROM attempts WHERE run_id=? AND stage=? AND attempt_id=?",
                (run_id, run["stage"], attempt_id),
            ).fetchone()
            paths = _artifact_paths(run["work_dir"], attempt["container_name"])
            launch_plan = module.build_launch_plan(
                argparse.Namespace(
                    manifest=Path(run["manifest_path"]),
                    stage_plan=Path(run["stage_plan_path"]),
                    stage=run["stage"],
                    run_id=run_id,
                    attempt_id=attempt_id,
                    uid=os.getuid(),
                    gid=os.getgid(),
                )
            )
            finalize.atomic_write_json(paths["plan"], launch_plan)
            identity = launch_plan["identity"]
            submission.bind_attempt_identity(
                conn,
                run_id,
                run["stage"],
                attempt_id,
                image_digest=launch_plan["runtime"]["gromacs_image_digest"],
                work_dir_hash=identity["work_dir_hash"],
                command_hash=identity["command_hash"],
                ownership_labels=identity["labels"],
                cid_file=identity["cid_file"],
                actor=actor,
            )
            # Persist running before Docker starts.  If the process dies after
            # docker run, reconciliation can adopt the identity-bound attempt.
            db.set_run_status(
                conn,
                run_id,
                "running",
                actor=actor,
                detail=f"launching stage {run['stage']} attempt {attempt_id}",
            )
            try:
                launch_receipt = module.launch(
                    argparse.Namespace(
                        detach=True,
                        plan=paths["plan"],
                        manifest=Path(run["manifest_path"]),
                        stage_plan=Path(run["stage_plan_path"]),
                        output=paths["launch"],
                    )
                )
            except BaseException as exc:
                conn.execute(
                    "UPDATE attempts SET status='failed', finished_at=? WHERE run_id=? AND stage=? AND attempt_id=?",
                    (db.now(), run_id, run["stage"], attempt_id),
                )
                db.set_run_status(
                    conn,
                    run_id,
                    "failed",
                    actor=actor,
                    detail=f"container launch failed: {exc}",
                )
                summaries.append(
                    {"run_id": run_id, "action": "failed", "reason": str(exc)}
                )
                continue
            finalize.atomic_write_json(paths["launch"], launch_receipt)
            submission.record_container(
                conn,
                run_id,
                run["stage"],
                attempt_id,
                str(paths["launch"]),
                actor=actor,
            )
            summaries.append(
                {
                    "run_id": run_id,
                    "action": "launched",
                    "attempt_id": attempt_id,
                    "container_id": launch_receipt["container_id"],
                }
            )
        except (
            KeyError,
            OSError,
            ValueError,
            ExecutorError,
            approvals.ApprovalError,
            preflight.PreflightError,
            submission.SubmissionError,
        ) as exc:
            if db.run_status(conn, run_id) == "queued":
                db.set_run_status(
                    conn, run_id, "attention", actor=actor, detail=f"dispatch refused: {exc}"
                )
            summaries.append(
                {"run_id": run_id, "action": "attention", "reason": str(exc)}
            )
    return summaries


def finalize_exited(
    conn: sqlite3.Connection,
    docker: reconcile.DockerPort,
    *,
    actor: str = "runner",
) -> list[dict]:
    """Finalize identity-verified containers that have exited on this boot."""
    summaries: list[dict] = []
    rows = conn.execute(
        "SELECT r.*, a.attempt_id, a.container_name, a.status AS attempt_status "
        "FROM runs r JOIN attempts a ON a.run_id=r.run_id AND a.stage=r.stage "
        "WHERE r.status IN ('running','attention') AND a.container_at IS NOT NULL "
        "AND a.attempt_id=(SELECT MAX(a2.attempt_id) FROM attempts a2 WHERE a2.run_id=r.run_id AND a2.stage=r.stage)"
    ).fetchall()
    for row in rows:
        matches = [
            item
            for item in docker.find_by_label(reconcile.RUN_ID_LABEL, row["run_id"])
            if item.get("name") == row["container_name"]
        ]
        if len(matches) != 1 or matches[0].get("state") not in {"exited", "dead"}:
            continue
        container = matches[0]
        returncode = docker.container_returncode(container["id"])
        if returncode is None:
            continue
        paths = _artifact_paths(row["work_dir"], row["container_name"])
        receipt = finalize.finalize_container(
            conn,
            row["run_id"],
            row["stage"],
            row["attempt_id"],
            row["manifest_path"],
            row["stage_plan_path"],
            returncode,
            paths["finalize"],
            actor=actor,
        )
        conn.execute(
            "UPDATE attempts SET status=?, finished_at=?, returncode=?, receipt_path=? "
            "WHERE run_id=? AND stage=? AND attempt_id=?",
            (
                receipt["status"],
                db.now(),
                returncode,
                str(paths["finalize"]),
                row["run_id"],
                row["stage"],
                row["attempt_id"],
            ),
        )
        conn.execute(
            "UPDATE containers SET state=? WHERE container_id=?",
            (container.get("state", "exited"), container["id"]),
        )
        summaries.append(
            {
                "run_id": row["run_id"],
                "action": "finalized",
                "status": receipt["status"],
                "returncode": returncode,
            }
        )
    return summaries


def tick(
    conn: sqlite3.Connection,
    docker: reconcile.DockerPort,
    *,
    current_boot: str | None = None,
    actor: str = "runner",
) -> dict[str, list[dict]]:
    """Run one deterministic reconciliation/finalization/dispatch cycle."""
    reconciled = reconcile.reconcile(
        conn, docker, current_boot=current_boot, actor=actor
    )
    finalized = finalize_exited(conn, docker, actor=actor)
    launched = launch_approved(conn, docker, actor=actor)
    return {
        "reconciled": reconciled,
        "finalized": finalized,
        "launched": launched,
    }
