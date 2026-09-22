"""Trusted analysis admission, provenance receipts, and native task wiring (M5).

Formal analysis accepts only completed manifest artifacts or backend-created,
DB-registered frozen snapshots. Inputs are hashed with a stable-file check so a
concurrent write fails closed. Analysis sessions use exclusive UUID directories
and never overwrite a previous session.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path

from . import db, submission
from .finalize import atomic_write_json

ANALYSIS_RECEIPT_SCHEMA_VERSION = "1.0"
SNAPSHOT_SCHEMA_VERSION = "1.0"
STYLE_SCHEMA_VERSION = "1.0"
ANALYSIS_CLI_VERSION = "1.0"
SNAPSHOT_ARTIFACT_TYPE = "md_analysis_snapshot"
RECEIPT_ARTIFACT_TYPE = "md_analysis_receipt"
EXPORT_FORMATS = frozenset({"png", "svg", "pdf"})

SCIENCE_KEYS = frozenset(
    {
        "tpr_sha256",
        "xtc_sha256",
        "edr_sha256",
        "group",
        "fit_group",
        "begin_ps",
        "end_ps",
        "eq_start_ns",
        "cli_version",
    }
)
STYLE_KEYS = frozenset(
    {
        "colors",
        "font_family",
        "font_size",
        "fig_size",
        "style_schema_version",
    }
)


class AnalysisAdmissionError(ValueError):
    """Raised when analysis admission must fail closed."""


class AnalysisReceiptError(ValueError):
    """Raised when an analysis receipt is malformed."""


def sha256_file(path: str | Path) -> str:
    """Hash a stable regular file and reject concurrent writes or empty input."""
    source = Path(path)
    try:
        before = source.stat()
    except OSError as exc:
        raise AnalysisAdmissionError(
            f"analysis input is not readable: {source}"
        ) from exc
    if not source.is_file() or before.st_size <= 0:
        raise AnalysisAdmissionError(f"analysis input is missing or empty: {source}")
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    after = source.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise AnalysisAdmissionError(
            f"analysis input changed while hashing (half-written): {source}"
        )
    return digest.hexdigest()


def _content_hash(doc: dict) -> str:
    return hashlib.sha256(
        json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def artifact_files(artifacts: dict) -> dict[str, Path]:
    """Return tpr/xtc/edr paths from a manifest/snapshot artifact mapping."""
    files: dict[str, Path] = {}
    for key in ("tpr", "xtc", "edr"):
        entry = artifacts.get(key)
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise AnalysisAdmissionError(f"trusted source does not record {key} path")
        files[key] = Path(entry["path"])
    return files


def freeze_snapshot(
    run_id: str,
    stage: str,
    files: Mapping[str, str | Path],
    snapshots_root: str | Path,
) -> tuple[dict, Path]:
    """Create a backend-owned frozen copy under a new exclusive directory."""
    snapshot_id = "snap-" + uuid.uuid4().hex[:12]
    target = Path(snapshots_root) / snapshot_id
    target.mkdir(parents=True, exist_ok=False)
    record_files: dict[str, dict] = {}
    try:
        for key in ("tpr", "xtc", "edr"):
            src = Path(files[key])
            source_hash = sha256_file(src)
            dst = target / f"input{src.suffix.lower()}"
            if dst.exists():
                raise AnalysisAdmissionError(
                    f"snapshot destination already exists: {dst}"
                )
            shutil.copyfile(src, dst)
            copied_hash = sha256_file(dst)
            # Re-hash the source after copying. A writer that changed bytes while
            # preserving the initial stat metadata is still refused.
            if source_hash != copied_hash or sha256_file(src) != source_hash:
                raise AnalysisAdmissionError(
                    f"{key} changed while the backend snapshot was being frozen"
                )
            record_files[key] = {
                "path": str(dst.resolve()),
                "sha256": copied_hash,
            }
        record = {
            "schema_version": SNAPSHOT_SCHEMA_VERSION,
            "artifact_type": SNAPSHOT_ARTIFACT_TYPE,
            "snapshot_id": snapshot_id,
            "run_id": run_id,
            "stage": stage,
            "created_by": "backend",
            "created_at": db.now(),
            "files": record_files,
        }
        record_path = target / "snapshot.json"
        atomic_write_json(record_path, record)
        return record, record_path
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        raise


def register_snapshot(
    conn: sqlite3.Connection, record: dict, record_path: str | Path
) -> None:
    """Register the backend snapshot record and its own hash in SQLite."""
    path = Path(record_path)
    conn.execute(
        "INSERT INTO analysis_snapshots(snapshot_id, run_id, stage, record_path, "
        "record_sha256, created_at) VALUES (?,?,?,?,?,?)",
        (
            record["snapshot_id"],
            record["run_id"],
            record["stage"],
            str(path.resolve()),
            sha256_file(path),
            record["created_at"],
        ),
    )
    db.audit(
        conn,
        "backend",
        "analysis_snapshot_created",
        subject=record["run_id"],
        detail=f"snapshot_id={record['snapshot_id']}",
    )


def load_registered_snapshot(
    conn: sqlite3.Connection, snapshot_id: str, run_id: str
) -> dict:
    row = conn.execute(
        "SELECT * FROM analysis_snapshots WHERE snapshot_id = ? AND run_id = ?",
        (snapshot_id, run_id),
    ).fetchone()
    if row is None:
        raise AnalysisAdmissionError("snapshot is not backend-registered for this run")
    path = Path(row["record_path"])
    if sha256_file(path) != row["record_sha256"]:
        raise AnalysisAdmissionError("backend snapshot record hash has drifted")
    record = json.loads(path.read_text(encoding="utf-8"))
    if (
        record.get("artifact_type") != SNAPSHOT_ARTIFACT_TYPE
        or record.get("created_by") != "backend"
        or record.get("snapshot_id") != snapshot_id
    ):
        raise AnalysisAdmissionError("snapshot record is not backend-controlled")
    return record


def _verify_hashes(recorded: dict, files: Mapping[str, str | Path]) -> dict:
    verified: dict[str, str] = {}
    for key in ("tpr", "xtc", "edr"):
        entry = recorded.get(key)
        if not isinstance(entry, dict) or not entry.get("sha256"):
            raise AnalysisAdmissionError(f"no recorded sha256 for {key}")
        path = Path(files[key])
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            raise AnalysisAdmissionError(
                f"{key} hash mismatch (half-written or drifted): "
                f"expected {entry['sha256']}, got {actual}"
            )
        verified[f"{key}_sha256"] = actual
    return verified


def admit_completed_manifest(
    manifest: dict,
    stage: str,
    files: Mapping[str, str | Path] | None = None,
) -> tuple[dict, dict[str, Path]]:
    stage_doc = (manifest.get("stages") or {}).get(stage) or {}
    if stage_doc.get("status") != "completed":
        raise AnalysisAdmissionError(
            "stage is not completed and no backend frozen snapshot was provided"
        )
    artifacts = stage_doc.get("artifacts") or {}
    trusted_files = (
        artifact_files(artifacts)
        if files is None
        else {key: Path(files[key]) for key in ("tpr", "xtc", "edr")}
    )
    return _verify_hashes(artifacts, trusted_files), trusted_files


def admit_snapshot(
    record: dict, files: Mapping[str, str | Path] | None = None
) -> tuple[dict, dict[str, Path]]:
    if (
        record.get("artifact_type") != SNAPSHOT_ARTIFACT_TYPE
        or record.get("created_by") != "backend"
    ):
        raise AnalysisAdmissionError("user-reported snapshots are not trusted")
    trusted_files = (
        artifact_files(record.get("files") or {})
        if files is None
        else {key: Path(files[key]) for key in ("tpr", "xtc", "edr")}
    )
    return _verify_hashes(record["files"], trusted_files), trusted_files


def create_session_dir(work_dir: str | Path, run_id: str) -> tuple[str, Path]:
    """Create analysis/<run_id>/<session> exclusively (no historical overwrite)."""
    session_id = "analysis-" + uuid.uuid4().hex[:12]
    session_dir = Path(work_dir) / "analysis" / run_id / session_id
    session_dir.mkdir(parents=True, exist_ok=False)
    return session_id, session_dir


def build_analysis_receipt(
    science: dict,
    style: dict,
    *,
    source_kind: str,
    style_source_sha256: str,
) -> dict:
    """Build a receipt with disjoint, versioned science and style sections."""
    if not isinstance(science, dict) or not isinstance(style, dict):
        raise AnalysisReceiptError("science and style must both be JSON objects")
    overlap = set(science) & set(style)
    if overlap:
        raise AnalysisReceiptError(
            f"science and style fields must be disjoint; overlap: {sorted(overlap)}"
        )
    unknown_science = set(science) - SCIENCE_KEYS
    unknown_style = set(style) - STYLE_KEYS
    if unknown_science:
        raise AnalysisReceiptError(f"unknown science fields: {sorted(unknown_science)}")
    if unknown_style:
        raise AnalysisReceiptError(f"unknown style fields: {sorted(unknown_style)}")
    required = {
        "tpr_sha256",
        "xtc_sha256",
        "edr_sha256",
        "group",
        "fit_group",
        "cli_version",
    }
    if missing := required - set(science):
        raise AnalysisReceiptError(f"missing science fields: {sorted(missing)}")

    science_doc = dict(science)
    science_doc["science_schema_version"] = ANALYSIS_RECEIPT_SCHEMA_VERSION
    science_doc["science_source_artifact_sha256"] = _content_hash(science)
    style_doc = dict(style)
    style_doc.setdefault("style_schema_version", STYLE_SCHEMA_VERSION)
    style_doc["style_source_artifact_sha256"] = style_source_sha256
    return {
        "schema_version": ANALYSIS_RECEIPT_SCHEMA_VERSION,
        "artifact_type": RECEIPT_ARTIFACT_TYPE,
        "source_kind": source_kind,
        "science": science_doc,
        "style": style_doc,
    }


def write_style(
    session_dir: Path, style: dict, filename: str = "style.json"
) -> tuple[Path, str]:
    """Write the flat JSON shape consumed by md_style.load_style_config."""
    color_names = {
        "system": "sys1_color",
        "comparison": "sys2_color",
        "sys1_color": "sys1_color",
        "sys2_color": "sys2_color",
        "gray_light": "gray_light",
        "gray_dark": "gray_dark",
        "green_safe": "green_safe",
        "orange_warn": "orange_warn",
        "purple_accent": "purple_accent",
        "teal_accent": "teal_accent",
    }
    config = {
        "font_family": style.get("font_family", "sans-serif"),
        "font_size": style.get("font_size", 8),
        "fig_size_diagnostics": style.get("fig_size", [6.8, 7.5]),
    }
    for name, value in (style.get("colors") or {}).items():
        if target := color_names.get(name):
            config[target] = value
    path = session_dir / filename
    atomic_write_json(path, config)
    return path, sha256_file(path)


def build_analysis_command(
    plugin_root: str | Path,
    files: Mapping[str, str | Path],
    session_dir: str | Path,
    science: dict,
) -> list[str]:
    """Return the shell-free uv locked diagnostics command vector."""
    root = Path(plugin_root)
    cli = root / "source-skills/md-trajectory-analysis/scripts/md_analyze_cli.py"
    command = [
        "uv",
        "run",
        "--project",
        str(root / "web"),
        "--locked",
        "python",
        str(cli),
        "diagnostics",
        "--tpr",
        str(files["tpr"]),
        "--xtc",
        str(files["xtc"]),
        "--edr",
        str(files["edr"]),
        "--outdir",
        str(session_dir),
        "--group",
        str(science["group"]),
        "--fit-group",
        str(science["fit_group"]),
        "--eq-start",
        str(science.get("eq_start_ns", 0.0)),
    ]
    if science.get("begin_ps") is not None:
        command += ["--begin", str(science["begin_ps"])]
    if science.get("end_ps") is not None:
        command += ["--end", str(science["end_ps"])]
    return command


def build_plot_command(
    plugin_root: str | Path,
    session_dir: str | Path,
    style_path: str | Path,
    eq_start_ns: float,
) -> list[str]:
    """Return the shell-free locked-runtime command for all export formats."""
    root = Path(plugin_root)
    cli = root / "source-skills/md-simulation-plotting/scripts/md_plot_cli.py"
    session = Path(session_dir)
    return [
        "uv",
        "run",
        "--project",
        str(root),
        "--locked",
        "python",
        str(cli),
        "--style-config",
        str(style_path),
        "diagnostics",
        "--analysis-dir",
        str(session),
        "--eq-start-ns",
        str(eq_start_ns),
        "--output",
        str(session / "figures" / "diagnostics"),
    ]


def queue_analysis_task(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    project: str,
    source_run_id: str,
    source_work_dir: str,
    session_id: str,
    session_dir: Path,
    receipt: dict,
    command: list[str],
    plot_command: list[str],
    source_stage: str,
) -> dict:
    """Queue analysis through the same idempotency/work-dir lock as MD."""
    result = submission.submit_run(
        conn,
        request_id,
        project,
        submission.ANALYSIS_STAGE,
        source_work_dir,
        manifest_path=str(session_dir / "analysis_receipt.json"),
        stage_plan_path=str(session_dir / "analysis_command.json"),
        kind="analysis",
    )
    if not result["created"]:
        return result
    run = result["run"]
    command_doc = {
        "schema_version": "1.0",
        "artifact_type": "md_analysis_command",
        "command": command,
        "plot_command": plot_command,
    }
    atomic_write_json(session_dir / "analysis_receipt.json", receipt)
    atomic_write_json(session_dir / "analysis_command.json", command_doc)
    params = {
        "request_id": request_id,
        "source_run_id": source_run_id,
        "source_work_dir": str(Path(source_work_dir).resolve()),
        "task_run_id": run["run_id"],
        "task_type": "analysis",
        "session_dir": str(session_dir.resolve()),
        "receipt_path": str((session_dir / "analysis_receipt.json").resolve()),
        "source_stage": source_stage,
        "command": command,
        "plot_command": plot_command,
    }
    conn.execute(
        "INSERT INTO analysis_sessions(session_id, run_id, stage, status, params, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (
            session_id,
            run["run_id"],
            source_stage,
            "queued",
            json.dumps(params, sort_keys=True),
            db.now(),
        ),
    )
    db.audit(
        conn,
        "backend",
        "analysis_session_queued",
        subject=run["run_id"],
        detail=f"session_id={session_id}",
    )
    return result


def queue_redraw_task(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    project: str,
    session_id: str,
    source_work_dir: str,
    params: dict,
    receipt: dict,
    plot_command: list[str],
) -> dict:
    """Queue a plot-only task without re-running any scientific analysis."""
    revision_id = uuid.uuid4().hex
    session_dir = Path(params["session_dir"])
    receipt_path = session_dir / f"analysis_receipt.redraw-{revision_id}.json"
    command_path = session_dir / f"redraw_command.{revision_id}.json"
    result = submission.submit_run(
        conn,
        request_id,
        project,
        submission.ANALYSIS_STAGE,
        source_work_dir,
        manifest_path=str(receipt_path),
        stage_plan_path=str(command_path),
        kind="analysis",
    )
    if not result["created"]:
        return result
    run = result["run"]
    command_doc = {
        "schema_version": "1.0",
        "artifact_type": "md_analysis_redraw_command",
        "command": None,
        "plot_command": plot_command,
    }
    atomic_write_json(command_path, command_doc)
    atomic_write_json(receipt_path, receipt)
    updated = {
        **params,
        "receipt_path": str(receipt_path.resolve()),
        "request_id": request_id,
        "task_run_id": run["run_id"],
        "task_type": "redraw",
        "command": None,
        "plot_command": plot_command,
    }
    conn.execute(
        "UPDATE analysis_sessions SET run_id = ?, status = 'queued', params = ? "
        "WHERE session_id = ?",
        (run["run_id"], json.dumps(updated, sort_keys=True), session_id),
    )
    db.audit(
        conn,
        "backend",
        "analysis_redraw_queued",
        subject=run["run_id"],
        detail=f"session_id={session_id}; scientific analysis not scheduled",
    )
    return result


def run_analysis_task(
    conn: sqlite3.Connection,
    task_run_id: str,
    session_id: str,
    command: list[str] | None,
    *,
    plot_command: list[str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    """Execute analysis and/or plot-only native work; never construct an MD run."""
    run = conn.execute("SELECT * FROM runs WHERE run_id = ?", (task_run_id,)).fetchone()
    if run is None or run["stage"] != submission.ANALYSIS_STAGE:
        raise AnalysisAdmissionError(
            "analysis task run is missing or has the wrong stage"
        )
    if command is None and plot_command is None:
        raise AnalysisAdmissionError("native analysis task has no command")
    attempt_id = submission.allocate_attempt(
        conn,
        task_run_id,
        submission.ANALYSIS_STAGE,
        run["work_dir"],
        kind="analysis",
    )
    db.set_run_status(conn, task_run_id, "running", detail="native analysis started")
    conn.execute(
        "UPDATE attempts SET status = 'running' WHERE run_id = ? AND stage = ? AND attempt_id = ?",
        (task_run_id, submission.ANALYSIS_STAGE, attempt_id),
    )
    try:
        if command is not None:
            result = runner(command, text=True, capture_output=True, check=False)
        else:
            result = subprocess.CompletedProcess([], 0, "", "")
        if result.returncode == 0 and plot_command is not None:
            result = runner(plot_command, text=True, capture_output=True, check=False)
    except Exception:
        conn.execute(
            "UPDATE attempts SET status = 'failed', finished_at = ?, returncode = ? "
            "WHERE run_id = ? AND stage = ? AND attempt_id = ?",
            (db.now(), 127, task_run_id, submission.ANALYSIS_STAGE, attempt_id),
        )
        db.set_run_status(
            conn, task_run_id, "failed", detail="native analysis launch failed"
        )
        conn.execute(
            "UPDATE analysis_sessions SET status = 'failed' WHERE session_id = ?",
            (session_id,),
        )
        raise
    final = "completed" if result.returncode == 0 else "failed"
    conn.execute(
        "UPDATE attempts SET status = ?, finished_at = ?, returncode = ? "
        "WHERE run_id = ? AND stage = ? AND attempt_id = ?",
        (
            final,
            db.now(),
            result.returncode,
            task_run_id,
            submission.ANALYSIS_STAGE,
            attempt_id,
        ),
    )
    db.set_run_status(conn, task_run_id, final, detail="native analysis finished")
    conn.execute(
        "UPDATE analysis_sessions SET status = ? WHERE session_id = ?",
        (final, session_id),
    )
    return result


def run_queued_analysis_task(
    conn: sqlite3.Connection,
    task_run_id: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    """Load one persisted native task and dispatch it through the runner seam."""
    row = conn.execute(
        "SELECT * FROM analysis_sessions WHERE run_id = ?", (task_run_id,)
    ).fetchone()
    if row is None:
        raise AnalysisAdmissionError("queued analysis session is missing")
    if row["status"] != "queued":
        raise AnalysisAdmissionError(
            f"analysis session is {row['status']}; only queued work can start"
        )
    params = json.loads(row["params"])
    command = params.get("command")
    plot_command = params.get("plot_command")
    for name, value in (("command", command), ("plot_command", plot_command)):
        if value is not None and (
            not isinstance(value, list)
            or not value
            or not all(isinstance(item, str) and item for item in value)
        ):
            raise AnalysisAdmissionError(f"persisted {name} is not a command vector")
    return run_analysis_task(
        conn,
        task_run_id,
        row["session_id"],
        command,
        plot_command=plot_command,
        runner=runner,
    )


def session_export_path(session_dir: str | Path, format_name: str) -> Path:
    if format_name not in EXPORT_FORMATS:
        raise AnalysisAdmissionError(f"unsupported export format: {format_name}")
    root = Path(session_dir).resolve()
    path = (root / "figures" / f"diagnostics.{format_name}").resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise AnalysisAdmissionError("export escaped its analysis session") from exc
    return path
