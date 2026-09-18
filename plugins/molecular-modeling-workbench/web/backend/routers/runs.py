"""Structured allowlist submission router (M2 T2.4).

The submission is expressed as structured JSON with a strict field allowlist;
the server assembles the audited command vector through the plan-hash gated
`build_stage_plan` primitive and never accepts or joins shell strings. Unknown
fields and injection-shaped values are rejected by the pydantic strict models
and by the audited validators, and `request_id` gives idempotency through the
M1 runner submission authority.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from web.runner import db, mdcli, submission

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
