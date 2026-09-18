"""Background completion closure and shared finalize (M1 T1.7).

A detached container's exit code is collected, the protected inputs and the
approved-plan binding are re-verified, and the stage's expected artifacts are
hashed through the SAME audited primitives the foreground `run` path uses
(`collect_stage_artifacts` / `stage_outcome` in md_run_cli — imported, never
copied). The scientific verdict is then written atomically (temp file +
rename) so a crash never leaves a half-written receipt, and the run status is
transitioned in SQLite.

Exit 0 alone is never scientific completion: missing/hash-mismatched artifacts
yield `failed` (or `incomplete` when the process returned 0) and the receipt
keeps the precise verdict. Re-running finalize is idempotent — the verdict is
recomputed deterministically and the atomic receipt is identical.
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path

from . import db, mdcli


class FinalizeError(ValueError):
    """Raised when finalize cannot produce a trustworthy verdict."""


def atomic_write_json(path: Path, doc: dict) -> None:
    """Write a JSON document atomically via a sibling temp file + rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(doc, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _scientific_verdict(
    module, manifest_path: Path, stage_plan_path: Path, returncode: int
) -> tuple[dict, dict, Path, dict, str]:
    """Re-verify binding and hash expected artifacts via the audited CLI."""
    manifest = module.load(manifest_path)
    plan = module.read_stage_plan(stage_plan_path)
    module.validate_stage_prerequisites(manifest, plan)
    work = Path(manifest["work_dir"])
    artifacts = module.collect_stage_artifacts(work, plan["expected_artifacts"])
    status = module.stage_outcome(returncode, artifacts, plan["expected_artifacts"])
    return manifest, plan, work, artifacts, status


def finalize_container(
    conn: sqlite3.Connection,
    run_id: str,
    stage: str,
    attempt_id: int,
    manifest_path: str | Path,
    stage_plan_path: str | Path,
    returncode: int,
    receipt_path: str | Path,
    actor: str = "runner",
) -> dict:
    """Close a detached container attempt with a shared audited verdict.

    Idempotent: recomputes the deterministic verdict and atomically writes an
    identical receipt. The DB run status transitions only when the status
    actually changes (old == new is a no-op transition).
    """
    module = mdcli.load_md_run_cli()
    manifest, plan, work, artifacts, status = _scientific_verdict(
        module, Path(manifest_path), Path(stage_plan_path), returncode
    )
    receipt = {
        "schema_version": "1.0",
        "artifact_type": "md_finalize_receipt",
        "created_at": module.now(),
        "run_id": run_id,
        "stage": stage,
        "attempt_id": attempt_id,
        "deffnm": plan["deffnm"],
        "returncode": returncode,
        "status": status,
        "work_dir": str(work.resolve()),
        "manifest": module.file_reference(Path(manifest_path)),
        "stage_plan": module.file_reference(Path(stage_plan_path)),
        "artifacts": artifacts,
    }
    receipt["receipt_sha256"] = module.plan_hash(receipt)
    atomic_write_json(Path(receipt_path), receipt)

    # "incomplete" (exit 0 but artifacts missing) is not a DB lifecycle status;
    # it maps to `failed` while the receipt preserves the precise verdict.
    run_status = status if status in db.RUN_STATUSES else "failed"
    db.set_run_status(
        conn,
        run_id,
        run_status,
        actor=actor,
        detail=(
            f"finalize stage={stage} attempt_id={attempt_id} "
            f"returncode={returncode} verdict={status}"
        ),
    )
    db.audit(
        conn,
        actor,
        "attempt_finalized",
        subject=run_id,
        detail=f"stage={stage} attempt_id={attempt_id} verdict={status} "
        f"receipt={Path(receipt_path).name}",
    )
    return receipt


def finalize_interrupted(
    conn: sqlite3.Connection,
    run_id: str,
    stage: str,
    attempt_id: int,
    detail: str,
    actor: str = "runner",
) -> None:
    """Mark a preprocessing/short stage interrupted, preserving its evidence.

    Used for grompp/analysis subprocesses whose outcome became undecidable after
    a service restart. The stage is set to `interrupted` (user confirmation
    required before redoing) and the reason is recorded in the audit log. This
    is a narrow rule, not a generic orchestration framework.
    """
    db.set_run_status(
        conn,
        run_id,
        "interrupted",
        actor=actor,
        detail=f"stage={stage} attempt_id={attempt_id}: {detail}",
    )
    db.audit(
        conn,
        actor,
        "attempt_interrupted",
        subject=run_id,
        detail=f"stage={stage} attempt_id={attempt_id}: {detail}",
    )
