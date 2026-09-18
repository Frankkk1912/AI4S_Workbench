"""Formal analysis admission, queueing, gallery, and export routes (M5)."""

# The FastAPI runtime is installed by ``uv --project web --locked`` rather than
# the repository-level interpreter used by lightweight static editors.
# pyright: reportMissingImports=false

from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from web.runner import analysis_runner, db, submission

from ..paths import PathEscapeError, PathNotFoundError, resolve_workspace_path
from ..security import require_local_request, require_token

router = APIRouter(
    prefix="/analysis",
    tags=["analysis"],
    dependencies=[Depends(require_token), Depends(require_local_request)],
)
PLUGIN_ROOT = Path(__file__).resolve().parents[3]
PREDEFINED_GROUPS = (
    "protein",
    "backbone",
    "c-alpha",
    "non-protein",
    "water",
    "ions",
    "system",
)


class SnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    stage: Literal["em", "nvt", "npt", "md_prod"] = "md_prod"


class StylePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    colors: dict[str, str] = Field(default_factory=dict)
    font_family: str = "sans-serif"
    font_size: float = Field(default=8.0, gt=0, le=72)
    fig_size: tuple[float, float] = Field(default=(6.8, 7.5))
    style_schema_version: str = "1.0"

    @model_validator(mode="after")
    def validate_figure_size(self):
        if any(value <= 0 or value > 100 for value in self.fig_size):
            raise ValueError("fig_size values must be in (0, 100]")
        return self


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    source_kind: Literal["completed", "snapshot"]
    source_stage: Literal["em", "nvt", "npt", "md_prod"] = "md_prod"
    snapshot_id: str | None = None
    group: Literal[
        "protein",
        "backbone",
        "c-alpha",
        "non-protein",
        "water",
        "ions",
        "system",
    ] = "backbone"
    fit_group: Literal[
        "protein",
        "backbone",
        "c-alpha",
        "non-protein",
        "water",
        "ions",
        "system",
    ] = "backbone"
    begin_ps: float | None = Field(default=None, ge=0)
    end_ps: float | None = Field(default=None, ge=0)
    eq_start_ns: float = Field(default=0.0, ge=0)
    style: StylePayload = Field(default_factory=StylePayload)

    @model_validator(mode="after")
    def validate_source_and_window(self):
        if self.source_kind == "snapshot" and not self.snapshot_id:
            raise ValueError("snapshot source requires snapshot_id")
        if self.source_kind == "completed" and self.snapshot_id is not None:
            raise ValueError("completed source must not provide snapshot_id")
        if (
            self.begin_ps is not None
            and self.end_ps is not None
            and self.begin_ps >= self.end_ps
        ):
            raise ValueError("begin_ps must be less than end_ps")
        return self


class RestyleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1)
    style: StylePayload


def _run_row(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"unknown run: {run_id}")
    return row


def _manifest(run: sqlite3.Row, roots: list[str]) -> tuple[dict, Path]:
    if not run["manifest_path"]:
        raise HTTPException(status_code=409, detail="run has no trusted manifest")
    try:
        path = resolve_workspace_path(
            roots, run["manifest_path"], label="manifest", must_exist=True
        )
    except (PathEscapeError, PathNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return json.loads(path.read_text(encoding="utf-8")), path
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="manifest is unreadable") from exc


def _workspace_files(files: dict, roots: list[str]) -> dict[str, Path]:
    """Resolve every scientific input inside an approved workspace root."""
    resolved: dict[str, Path] = {}
    for key, value in files.items():
        try:
            resolved[key] = resolve_workspace_path(
                roots, value, label=f"analysis {key}", must_exist=True
            )
        except (PathEscapeError, PathNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return resolved


def _snapshot_source_files(
    run: sqlite3.Row, manifest: dict, stage: str, roots: list[str]
) -> dict[str, Path]:
    artifacts = ((manifest.get("stages") or {}).get(stage) or {}).get("artifacts") or {}
    if all(isinstance(artifacts.get(key), dict) for key in ("tpr", "xtc", "edr")):
        return _workspace_files(analysis_runner.artifact_files(artifacts), roots)
    deffnm = stage
    if run["stage_plan_path"]:
        try:
            plan = json.loads(Path(run["stage_plan_path"]).read_text(encoding="utf-8"))
            deffnm = plan.get("deffnm") or stage
        except (OSError, ValueError):
            pass
    work = Path(manifest.get("work_dir") or run["work_dir"])
    return _workspace_files(
        {key: work / f"{deffnm}.{key}" for key in ("tpr", "xtc", "edr")},
        roots,
    )


def _existing_session(conn: sqlite3.Connection, request_id: str) -> dict | None:
    for row in conn.execute("SELECT * FROM analysis_sessions").fetchall():
        params = json.loads(row["params"])
        if params.get("request_id") == request_id:
            return _session_doc(row)
    return None


def _session_doc(row: sqlite3.Row) -> dict:
    params = json.loads(row["params"])
    session_dir = Path(params["session_dir"])
    exports = {
        format_name: f"/analysis/sessions/{row['session_id']}/exports/{format_name}"
        for format_name in sorted(analysis_runner.EXPORT_FORMATS)
        if row["status"] == "completed"
        and analysis_runner.session_export_path(session_dir, format_name).is_file()
    }
    receipt = json.loads(Path(params["receipt_path"]).read_text(encoding="utf-8"))
    return {
        "session_id": row["session_id"],
        "source_run_id": params["source_run_id"],
        "task_run_id": params["task_run_id"],
        "source_stage": row["stage"],
        "status": row["status"],
        "created_at": row["created_at"],
        "source_kind": receipt["source_kind"],
        "science": receipt["science"],
        "style": receipt["style"],
        "exports": exports,
    }


@router.post("/snapshots", status_code=201)
def create_snapshot(body: SnapshotRequest, request: Request) -> dict:
    conn = db.connect(request.app.state.db_path)
    try:
        run = _run_row(conn, body.run_id)
        if run["status"] != "stopped":
            raise HTTPException(
                status_code=409,
                detail=(
                    "a controlled snapshot requires a safely stopped stage; "
                    "live monitoring is not a formal analysis source"
                ),
            )
        manifest, _ = _manifest(run, request.app.state.workspace_roots)
        files = _snapshot_source_files(
            run, manifest, body.stage, request.app.state.workspace_roots
        )
        snapshots_root = resolve_workspace_path(
            request.app.state.workspace_roots,
            Path(run["work_dir"]) / "analysis" / body.run_id / "snapshots",
            label="snapshot destination",
        )
        record, record_path = analysis_runner.freeze_snapshot(
            body.run_id, body.stage, files, snapshots_root
        )
        analysis_runner.register_snapshot(conn, record, record_path)
        return {
            "snapshot_id": record["snapshot_id"],
            "run_id": body.run_id,
            "stage": body.stage,
            "created_by": "backend",
            "record_sha256": analysis_runner.sha256_file(record_path),
        }
    except analysis_runner.AnalysisAdmissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        conn.close()


@router.post("/sessions", status_code=201)
def create_session(body: AnalysisRequest, request: Request) -> dict:
    conn = db.connect(request.app.state.db_path)
    session_dir: Path | None = None
    try:
        if existing := _existing_session(conn, body.request_id):
            return {**existing, "created": False}
        source_run = _run_row(conn, body.run_id)
        manifest, _ = _manifest(source_run, request.app.state.workspace_roots)
        if body.source_kind == "completed":
            if source_run["status"] != "completed":
                raise analysis_runner.AnalysisAdmissionError(
                    "completed-source analysis requires a completed run"
                )
            stage_doc = (manifest.get("stages") or {}).get(body.source_stage) or {}
            if stage_doc.get("status") != "completed":
                raise analysis_runner.AnalysisAdmissionError(
                    "stage is not completed and no backend frozen snapshot was provided"
                )
            files = _workspace_files(
                analysis_runner.artifact_files(stage_doc.get("artifacts") or {}),
                request.app.state.workspace_roots,
            )
            verified, files = analysis_runner.admit_completed_manifest(
                manifest, body.source_stage, files=files
            )
        else:
            record = analysis_runner.load_registered_snapshot(
                conn, body.snapshot_id or "", body.run_id
            )
            if record.get("stage") != body.source_stage:
                raise analysis_runner.AnalysisAdmissionError(
                    "snapshot stage does not match requested source stage"
                )
            files = _workspace_files(
                analysis_runner.artifact_files(record.get("files") or {}),
                request.app.state.workspace_roots,
            )
            verified, files = analysis_runner.admit_snapshot(record, files=files)

        session_id, session_dir = analysis_runner.create_session_dir(
            source_run["work_dir"], body.run_id
        )
        style = body.style.model_dump()
        style_path, style_hash = analysis_runner.write_style(session_dir, style)
        science = {
            **verified,
            "group": body.group,
            "fit_group": body.fit_group,
            "begin_ps": body.begin_ps,
            "end_ps": body.end_ps,
            "eq_start_ns": body.eq_start_ns,
            "cli_version": analysis_runner.ANALYSIS_CLI_VERSION,
        }
        receipt = analysis_runner.build_analysis_receipt(
            science,
            style,
            source_kind=body.source_kind,
            style_source_sha256=style_hash,
        )
        command = analysis_runner.build_analysis_command(
            PLUGIN_ROOT, files, session_dir, science
        )
        plot_command = analysis_runner.build_plot_command(
            PLUGIN_ROOT, session_dir, style_path, body.eq_start_ns
        )
        queued = analysis_runner.queue_analysis_task(
            conn,
            request_id=body.request_id,
            project=source_run["project"],
            source_run_id=body.run_id,
            source_work_dir=source_run["work_dir"],
            session_id=session_id,
            session_dir=session_dir,
            receipt=receipt,
            command=command,
            plot_command=plot_command,
            source_stage=body.source_stage,
        )
        if not queued["created"]:
            if session_dir is not None:
                shutil.rmtree(session_dir, ignore_errors=True)
            row = conn.execute(
                "SELECT * FROM analysis_sessions WHERE run_id = ?",
                (queued["run"]["run_id"],),
            ).fetchone()
            if row is None:
                raise HTTPException(
                    status_code=409,
                    detail="matching analysis request is not fully registered; retry",
                )
            return {**_session_doc(row), "created": False}
        row = conn.execute(
            "SELECT * FROM analysis_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return {**_session_doc(row), "created": True}
    except (analysis_runner.AnalysisAdmissionError, submission.SubmissionError) as exc:
        if session_dir is not None:
            shutil.rmtree(session_dir, ignore_errors=True)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception:
        if session_dir is not None:
            # A failed queue must not leave a directory that could be mistaken
            # for a historical analysis session.
            row = conn.execute(
                "SELECT 1 FROM analysis_sessions WHERE session_id = ?",
                (session_dir.name,),
            ).fetchone()
            if row is None:
                shutil.rmtree(session_dir, ignore_errors=True)
        raise
    finally:
        conn.close()


@router.get("/runs/{run_id}/sessions")
def list_sessions(run_id: str, request: Request) -> dict:
    conn = db.connect(request.app.state.db_path)
    try:
        _run_row(conn, run_id)
        sessions = []
        for row in conn.execute(
            "SELECT * FROM analysis_sessions ORDER BY created_at, session_id"
        ).fetchall():
            doc = _session_doc(row)
            if doc["source_run_id"] == run_id:
                sessions.append(doc)
        return {"run_id": run_id, "sessions": sessions}
    finally:
        conn.close()


@router.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request) -> dict:
    conn = db.connect(request.app.state.db_path)
    try:
        row = conn.execute(
            "SELECT * FROM analysis_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="unknown analysis session")
        return _session_doc(row)
    finally:
        conn.close()


@router.post("/sessions/{session_id}/style")
def restyle_session(session_id: str, body: RestyleRequest, request: Request) -> dict:
    conn = db.connect(request.app.state.db_path)
    pending_style: Path | None = None
    try:
        row = conn.execute(
            "SELECT * FROM analysis_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="unknown analysis session")
        existing_run = conn.execute(
            "SELECT run_id FROM runs WHERE request_id = ?", (body.request_id,)
        ).fetchone()
        if existing_run is not None:
            existing = conn.execute(
                "SELECT * FROM analysis_sessions WHERE run_id = ?",
                (existing_run["run_id"],),
            ).fetchone()
            if existing is None:
                raise HTTPException(
                    status_code=409,
                    detail="matching redraw request is not fully registered; retry",
                )
            return {**_session_doc(existing), "created": False}
        if row["status"] != "completed":
            raise HTTPException(
                status_code=409, detail="only a completed analysis can be redrawn"
            )
        params = json.loads(row["params"])
        source_run = _run_row(conn, params["source_run_id"])
        receipt_path = Path(params["receipt_path"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        science_before = json.dumps(receipt["science"], sort_keys=True)
        style = body.style.model_dump()
        pending_style, style_hash = analysis_runner.write_style(
            Path(params["session_dir"]),
            style,
            filename=f"styles/style-{uuid.uuid4().hex}.json",
        )
        rebuilt = analysis_runner.build_analysis_receipt(
            {
                key: value
                for key, value in receipt["science"].items()
                if key in analysis_runner.SCIENCE_KEYS
            },
            style,
            source_kind=receipt["source_kind"],
            style_source_sha256=style_hash,
        )
        if json.dumps(rebuilt["science"], sort_keys=True) != science_before:
            raise HTTPException(status_code=409, detail="style change altered science")
        plot_command = analysis_runner.build_plot_command(
            PLUGIN_ROOT,
            params["session_dir"],
            pending_style,
            receipt["science"].get("eq_start_ns", 0.0),
        )
        queued = analysis_runner.queue_redraw_task(
            conn,
            request_id=body.request_id,
            project=source_run["project"],
            session_id=session_id,
            source_work_dir=params.get("source_work_dir", source_run["work_dir"]),
            params=params,
            receipt=rebuilt,
            plot_command=plot_command,
        )
        if not queued["created"]:
            if pending_style is not None:
                pending_style.unlink(missing_ok=True)
            existing = conn.execute(
                "SELECT * FROM analysis_sessions WHERE run_id = ?",
                (queued["run"]["run_id"],),
            ).fetchone()
            if existing is None:
                raise HTTPException(
                    status_code=409,
                    detail="matching redraw request is not fully registered; retry",
                )
            return {**_session_doc(existing), "created": False}
        db.audit(
            conn,
            "user",
            "analysis_style_approved",
            subject=queued["run"]["run_id"],
            detail=f"session_id={session_id}; redraw only",
        )
        updated = conn.execute(
            "SELECT * FROM analysis_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return {**_session_doc(updated), "created": True}
    except submission.SubmissionError as exc:
        if pending_style is not None:
            pending_style.unlink(missing_ok=True)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        conn.close()


@router.get("/sessions/{session_id}/exports/{format_name}")
def export_result(session_id: str, format_name: str, request: Request):
    conn = db.connect(request.app.state.db_path)
    try:
        row = conn.execute(
            "SELECT status, params FROM analysis_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="unknown analysis session")
        if row["status"] != "completed":
            raise HTTPException(status_code=409, detail="analysis export is not ready")
        params = json.loads(row["params"])
        try:
            path = analysis_runner.session_export_path(
                params["session_dir"], format_name
            )
        except analysis_runner.AnalysisAdmissionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not path.is_file():
            raise HTTPException(status_code=404, detail="export is not available")
        media = {
            "png": "image/png",
            "svg": "image/svg+xml",
            "pdf": "application/pdf",
        }[format_name]
        return FileResponse(path, media_type=media, filename=path.name)
    finally:
        conn.close()
