"""Structured allowlist submission router (M2 T2.4).

The submission is expressed as structured JSON with a strict field allowlist;
the server assembles the audited command vector through the plan-hash gated
`build_stage_plan` primitive and never accepts or joins shell strings. Unknown
fields and injection-shaped values are rejected by the pydantic strict models
and by the audited validators, and `request_id` gives idempotency through the
M1 runner submission authority.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from web.runner import db, lifecycle, mdcli, orchestrator, preflight, submission

from .. import approvals
from ..paths import PathEscapeError, PathNotFoundError, resolve_workspace_path
from ..security import require_local_request, require_token

router = APIRouter(
    prefix="/runs",
    tags=["runs"],
    dependencies=[Depends(require_token), Depends(require_local_request)],
)


class StagePlanPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deffnm: str = Field(min_length=1, max_length=128)
    profile: Literal["cpu-fallback", "wsl2-gpu", "linux-gpu", "linux-ssh"]
    threads: int = Field(gt=0)
    resume: bool = False


class RunSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    project: str = Field(min_length=1)
    stage: Literal["em", "nvt", "npt", "md_prod"]
    manifest_path: str
    stage_plan: StagePlanPayload


def _resolve_or_400(roots: Sequence[str | Path], value: str, label: str) -> Path:
    try:
        return resolve_workspace_path(roots, value, label=label, must_exist=True)
    except (PathEscapeError, PathNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("", status_code=201)
def submit_run(body: RunSubmission, request: Request) -> dict:
    module = mdcli.load_md_run_cli()
    roots = request.app.state.workspace_roots
    manifest_path = _resolve_or_400(roots, body.manifest_path, "manifest")
    manifest = module.load(manifest_path)
    work = module.validate_grompp_manifest(manifest)
    # The manifest's work directory must also be inside a registered root
    # (cross-project isolation, T2.3).
    _resolve_or_400(roots, str(work), "manifest work_dir")

    # T3.6: an expired environment receipt blocks NEW submissions only (never a
    # running container). The hard 7-day check in md_run_cli.validate_receipt is
    # unchanged; this is the earlier web-layer boundary with a clear message.
    receipt_ref = manifest.get("environment_receipt", {})
    if isinstance(receipt_ref, dict) and isinstance(receipt_ref.get("path"), str):
        receipt_path = _resolve_or_400(
            roots, receipt_ref["path"], "environment receipt"
        )
        conn = db.connect(request.app.state.db_path)
        try:
            preflight.require_fresh_receipt(
                conn, str(receipt_path), body.request_id, actor="api"
            )
        except preflight.PreflightError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        finally:
            conn.close()

    # Assemble the audited command vector through the plan-hash gate. No shell
    # string is accepted or concatenated anywhere in this path.
    try:
        plan = module.build_stage_plan(
            body.stage,
            body.stage_plan.deffnm,
            body.stage_plan.profile,
            body.stage_plan.threads,
            body.stage_plan.resume,
        )
    except module.MDError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    stage_plan_path = work / f"{plan['deffnm']}_stage_plan.json"

    conn = db.connect(request.app.state.db_path)
    try:
        result = submission.submit_run(
            conn,
            body.request_id,
            body.project,
            body.stage,
            str(work),
            str(manifest_path),
            str(stage_plan_path),
        )
        run = result["run"]
        if result["created"]:
            module.write(stage_plan_path, plan)
        return {
            "run_id": run["run_id"],
            "request_id": run["request_id"],
            "project": run["project"],
            "stage": run["stage"],
            "status": run["status"],
            "created": result["created"],
            "command": plan["command"],
            "plan_sha256": plan["plan_sha256"],
            "stage_plan_path": str(stage_plan_path),
        }
    finally:
        conn.close()


def _run_row(request: Request, run_id: str) -> sqlite3.Row:
    conn = db.connect(request.app.state.db_path)
    try:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")
    return row


@router.get("/{run_id}")
def get_run(run_id: str, request: Request) -> dict:
    row = _run_row(request, run_id)
    return {
        "run_id": row["run_id"],
        "request_id": row["request_id"],
        "project": row["project"],
        "stage": row["stage"],
        "status": row["status"],
        "work_dir": row["work_dir"],
    }


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: dict
    kind: Literal["strategy", "extension", "resume", "retry"] = "strategy"


class RetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)
    strategy: dict
    receipt_path: str


class StopRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    container_id: str | None = None
    receipt_path: str
    docker_path: str = "docker"


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: Literal["em", "nvt", "npt", "md_prod"]
    attempt_id: int
    cpt_path: str
    tpr_path: str
    expected_checksum: str | None = None
    cpt_step: int | None = None
    log_step: int | None = None


@router.post("/{run_id}/approve", status_code=201)
def approve_run(run_id: str, body: ApprovalRequest, request: Request) -> dict:
    row = _run_row(request, run_id)
    conn = db.connect(request.app.state.db_path)
    try:
        doc = approvals.record_approval(
            conn,
            run_id,
            body.strategy,
            row["work_dir"],
            kind=body.kind,
            approved_by="user",
        )
        return {
            "approval_id": doc["approval_id"],
            "run_id": run_id,
            "kind": doc["kind"],
            "strategy_hash": doc["strategy_hash"],
            "sidecar_path": str(
                approvals.sidecar_path(row["work_dir"], doc["approval_id"])
            ),
        }
    except approvals.ApprovalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        conn.close()


@router.get("/{run_id}/approval")
def get_approval(run_id: str, request: Request) -> dict:
    _run_row(request, run_id)
    conn = db.connect(request.app.state.db_path)
    try:
        row = approvals.latest_approval(conn, run_id)
        if row is None:
            return {"run_id": run_id, "approval": None}
        doc = approvals.verify_approval_artifact(conn, row)
        return {
            "run_id": run_id,
            "approval": {
                "approval_id": row["approval_id"],
                "kind": row["kind"],
                "payload_hash": row["payload_hash"],
                "sidecar_path": row["sidecar_path"],
                "approved_by": row["approved_by"],
                "approved_at": row["approved_at"],
                "lineage": json.loads(row["lineage"]) if row["lineage"] else {},
                "confirmed": doc.get("confirmed"),
            },
        }
    except approvals.ApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/{run_id}/retry")
def retry_run(run_id: str, body: RetryRequest, request: Request) -> dict:
    _run_row(request, run_id)
    roots = request.app.state.workspace_roots
    receipt = _resolve_or_400(roots, body.receipt_path, "receipt")
    conn = db.connect(request.app.state.db_path)
    try:
        return orchestrator.retry_failed(
            conn,
            run_id,
            reason=body.reason,
            strategy=body.strategy,
            receipt_path=str(receipt),
        )
    except (orchestrator.OrchestrationError, preflight.PreflightError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/{run_id}/stop")
def stop_run(run_id: str, body: StopRequest, request: Request) -> dict:
    _run_row(request, run_id)
    roots = request.app.state.workspace_roots
    receipt = _resolve_or_400(roots, body.receipt_path, "receipt")
    receipt_doc = json.loads(receipt.read_text(encoding="utf-8"))
    docker = lifecycle.LifecycleDocker(body.docker_path)
    conn = db.connect(request.app.state.db_path)
    try:
        return lifecycle.request_stop(
            conn,
            run_id,
            docker,
            receipt_doc,
            container_id=body.container_id,
        )
    except lifecycle.LifecycleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/{run_id}/resume")
def resume_run(run_id: str, body: ResumeRequest, request: Request) -> dict:
    _run_row(request, run_id)
    roots = request.app.state.workspace_roots
    cpt = _resolve_or_400(roots, body.cpt_path, "checkpoint")
    tpr = _resolve_or_400(roots, body.tpr_path, "tpr")
    conn = db.connect(request.app.state.db_path)
    try:
        return lifecycle.approve_resume(
            conn,
            run_id,
            body.stage,
            body.attempt_id,
            cpt,
            tpr,
            expected_checksum=body.expected_checksum,
            cpt_step=body.cpt_step,
            log_step=body.log_step,
        )
    except lifecycle.LifecycleError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        conn.close()
