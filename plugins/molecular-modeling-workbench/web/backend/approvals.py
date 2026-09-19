"""Scientific strategy approval records and lineage (M3 T3.1).

An approval is a user's explicit, persistent confirmation of a scientific
strategy/template: the ordered stage sequence, the MDP template references and
their hashes, the total/target duration in ns, and any constraint options. It
is stored twice, in lockstep:

- a SQLite row in the runner `approvals` table (lifecycle authority), and
- a sidecar JSON artifact at `<workspace>/approvals/<approval_id>.json`.

Lineage (which earlier approval a re-approval supersedes, and the immutable
hash chain) lives ONLY in the runner DB and the sidecar. It is deliberately
NEVER written into the `plan_sha256`-covered plan/manifest files: `plan_hash`
hashes every key except itself, so adding a lineage field there would break the
existing CLI's hash verification. No future artifact hash is pre-filled; the
two-phase hash gates stay untouched. A strategy that has not been approved is
refused before any stage is launched.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path

from web.runner import db

APPROVAL_ARTIFACT_TYPE = "md_approval"
APPROVAL_SCHEMA_VERSION = "1.0"
STRATEGY_KINDS = ("strategy", "extension", "resume", "retry")


class ApprovalError(ValueError):
    """Raised when an approval is missing, invalid, or does not match a strategy."""


def strategy_hash(strategy: dict) -> str:
    """Canonical content hash of a scientific strategy/template document."""
    return hashlib.sha256(
        json.dumps(strategy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def new_approval_id() -> str:
    return "appr-" + uuid.uuid4().hex[:12]


def build_approval(
    run_id: str | None,
    strategy: dict,
    kind: str = "strategy",
    approved_by: str = "user",
    previous: dict | None = None,
    created_at: str | None = None,
) -> dict:
    """Build the approval sidecar document (not yet persisted)."""
    if kind not in STRATEGY_KINDS:
        raise ApprovalError(f"Unsupported approval kind: {kind!r}")
    if not isinstance(strategy, dict):
        raise ApprovalError("Approval strategy must be a JSON object.")
    approval_id = new_approval_id()
    doc = {
        "schema_version": APPROVAL_SCHEMA_VERSION,
        "artifact_type": APPROVAL_ARTIFACT_TYPE,
        "approval_id": approval_id,
        "created_at": created_at or db.now(),
        "kind": kind,
        "run_id": run_id,
        "strategy": strategy,
        "strategy_hash": strategy_hash(strategy),
        "approved_by": approved_by,
        "confirmed": True,
        "lineage": {
            "previous_approval_id": previous.get("approval_id") if previous else None,
            "previous_approval_hash": (
                previous.get("strategy_hash") if previous else None
            ),
        },
    }
    return doc


def sidecar_path(workspace: str | Path, approval_id: str) -> Path:
    return Path(workspace) / "approvals" / f"{approval_id}.json"


def write_sidecar(workspace: str | Path, doc: dict) -> Path:
    """Atomically persist the approval sidecar under the workspace."""
    path = sidecar_path(workspace, doc["approval_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def record_approval(
    conn: sqlite3.Connection,
    run_id: str,
    strategy: dict,
    workspace: str | Path,
    kind: str = "strategy",
    approved_by: str = "user",
    previous: dict | None = None,
    actor: str = "user",
) -> dict:
    """Persist a user approval as a SQLite row plus a workspace sidecar."""
    doc = build_approval(
        run_id, strategy, kind=kind, approved_by=approved_by, previous=previous
    )
    path = write_sidecar(workspace, doc)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "INSERT INTO approvals(approval_id, run_id, kind, payload_hash, sidecar_path, "
            "approved_by, approved_at, lineage) VALUES (?,?,?,?,?,?,?,?)",
            (
                doc["approval_id"],
                run_id,
                kind,
                doc["strategy_hash"],
                str(path.resolve()),
                approved_by,
                doc["created_at"],
                json.dumps(doc["lineage"], sort_keys=True),
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
        "approval_recorded",
        subject=run_id,
        detail=(
            f"approval_id={doc['approval_id']} kind={kind} "
            f"strategy_hash={doc['strategy_hash']}"
        ),
    )
    return doc


def latest_approval(
    conn: sqlite3.Connection, run_id: str, kind: str | None = None
) -> sqlite3.Row | None:
    """Return the most recent approval for a run (optionally filtered by kind)."""
    if kind is None:
        row = conn.execute(
            "SELECT * FROM approvals WHERE run_id = ? ORDER BY approved_at DESC, rowid DESC LIMIT 1",
            (run_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM approvals WHERE run_id = ? AND kind = ? "
            "ORDER BY approved_at DESC, rowid DESC LIMIT 1",
            (run_id, kind),
        ).fetchone()
    return row


def load_approval_row(conn: sqlite3.Connection, approval_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)
    ).fetchone()


def verify_approval_artifact(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    """Confirm the sidecar on disk still matches the SQLite row (consistency).

    The strategy content is re-hashed so a tampered (fabricated) strategy can
    never be accepted merely because its stored hash field was left untouched.
    """
    path = Path(row["sidecar_path"])
    if not path.is_file():
        raise ApprovalError(f"Approval sidecar is missing: {path}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if (
        doc.get("artifact_type") != APPROVAL_ARTIFACT_TYPE
        or doc.get("approval_id") != row["approval_id"]
    ):
        raise ApprovalError(
            f"Approval sidecar does not match the SQLite record: {path}"
        )
    strategy = doc.get("strategy")
    if not isinstance(strategy, dict) or strategy_hash(strategy) != doc.get(
        "strategy_hash"
    ):
        raise ApprovalError(
            f"Approval sidecar strategy hash does not match its content: {path}"
        )
    if doc.get("strategy_hash") != row["payload_hash"]:
        raise ApprovalError(
            f"Approval sidecar hash does not match the SQLite record: {path}"
        )
    return doc


def require_approved_strategy(
    conn: sqlite3.Connection, run_id: str, strategy: dict
) -> sqlite3.Row:
    """Refuse execution unless the strategy has an explicit matching approval.

    A re-approval is required whenever the scientific strategy changes: the
    content hash of the strategy being executed must equal the payload hash of
    a recorded approval. Missing approval or a changed strategy both fail
    closed here; the caller must never start a stage on the strength of a
    hash-complete plan alone (hash integrity != human approval).
    """
    expected = strategy_hash(strategy)
    row = latest_approval(conn, run_id, kind="strategy")
    if row is None:
        raise ApprovalError(
            f"Run {run_id} has no approved scientific strategy; user approval is required."
        )
    if row["payload_hash"] != expected:
        raise ApprovalError(
            f"Run {run_id} strategy has changed since approval; re-approval is required."
        )
    verify_approval_artifact(conn, row)
    return row
