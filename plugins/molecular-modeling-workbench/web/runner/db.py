"""Run/attempt/container lifecycle authority on SQLite (M1 T1.1).

Authority boundary: SQLite owns task and container lifecycle state and its
transition rules. Scientific artifacts (plans, manifests, receipts) stay
file + sha256 authoritative; this module only stores references and
verification values. Host identity is recorded at startup via
/proc/sys/kernel/random/boot_id so a machine restart is distinguishable from a
service restart (T1.3 depends on this).
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2
RUN_STATUSES = (
    "queued",
    "running",
    "stopping",
    "stopped",
    "completed",
    "failed",
    "attention",
    "unknown",
    "interrupted",
)
ACTIVE_STATUSES = frozenset({"queued", "running", "stopping"})
# Status set and transition table (T1.1): queued -> running -> stopping ->
# stopped (cpt verified) / completed / failed / attention / unknown /
# interrupted (host restart). `unknown` means the service is alive but the
# facts are undecidable; `interrupted` means a boot-identity change proves the
# computation cannot have continued.
TRANSITIONS: dict[str, frozenset[str]] = {
    "queued": frozenset({"running", "failed", "interrupted", "unknown", "attention"}),
    "running": frozenset(
        {
            "stopping",
            "stopped",
            "completed",
            "failed",
            "attention",
            "unknown",
            "interrupted",
        }
    ),
    "stopping": frozenset({"stopped", "attention", "unknown", "interrupted"}),
    "stopped": frozenset({"queued", "attention", "interrupted"}),
    "completed": frozenset({"attention"}),
    "failed": frozenset({"queued", "attention"}),
    "attention": frozenset(
        {"queued", "running", "completed", "failed", "interrupted", "unknown"}
    ),
    "unknown": frozenset({"running", "interrupted", "attention", "failed"}),
    "interrupted": frozenset({"queued", "attention"}),
}
BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")


class TransitionError(ValueError):
    """Raised when a status change is not in the transition table."""


class UnknownStatusError(ValueError):
    """Raised when a status value is outside the declared status set."""


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def connect(path: str | Path) -> sqlite3.Connection:
    # Autocommit mode: every DML statement commits on its own, and explicit
    # BEGIN IMMEDIATE / COMMIT / ROLLBACK in submission.py manage multi-step
    # transactions. Without this, db.init's inserts leave an implicit
    # transaction open and the first explicit BEGIN fails.
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init(
    conn: sqlite3.Connection,
    boot_id: str | None = None,
    schema_path: Path | None = None,
) -> None:
    """Create the schema and record schema version and boot identity."""
    path = schema_path or Path(__file__).with_name("schema.sql")
    conn.executescript(path.read_text(encoding="utf-8"))
    stamp = now()
    conn.execute(
        "INSERT INTO meta(key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    recorded_boot = boot_id if boot_id is not None else current_boot_id()
    conn.execute(
        "INSERT INTO meta(key, value) VALUES ('boot_id', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (recorded_boot,),
    )
    audit(
        conn,
        "runner",
        "db_initialized",
        detail=f"schema_version={SCHEMA_VERSION} boot_id={recorded_boot} at {stamp}",
    )


def current_boot_id() -> str:
    try:
        value = BOOT_ID_PATH.read_text(encoding="utf-8").strip()
        if value:
            return value
    except OSError:
        pass
    return "unavailable"


def recorded_boot_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = 'boot_id'").fetchone()
    return row["value"] if row else None


def boot_changed(conn: sqlite3.Connection, current: str | None = None) -> bool:
    """True when the host boot identity differs from the recorded one.

    A boot change proves the machine restarted, so any active computation is
    deterministically `interrupted` (never silently re-run, per R6).
    """
    recorded = recorded_boot_id(conn)
    current = current if current is not None else current_boot_id()
    return recorded is None or recorded != current


def audit(
    conn: sqlite3.Connection,
    actor: str,
    event: str,
    subject: str | None = None,
    detail: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO audit_log(at, actor, event, subject, detail) VALUES (?, ?, ?, ?, ?)",
        (now(), actor, event, subject, detail),
    )


def validate_status(status: str) -> None:
    if status not in RUN_STATUSES:
        raise UnknownStatusError(f"Unknown run status: {status!r}")


def can_transition(old: str, new: str) -> bool:
    validate_status(old)
    validate_status(new)
    if old == new:
        return True
    return new in TRANSITIONS[old]


def assert_transition(old: str, new: str) -> None:
    if not can_transition(old, new):
        raise TransitionError(f"Illegal run status transition: {old!r} -> {new!r}")


def run_status(conn: sqlite3.Connection, run_id: str) -> str:
    row = conn.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(f"Unknown run: {run_id}")
    return row["status"]


def set_run_status(
    conn: sqlite3.Connection,
    run_id: str,
    new_status: str,
    actor: str = "runner",
    detail: str | None = None,
) -> str:
    old = run_status(conn, run_id)
    assert_transition(old, new_status)
    conn.execute(
        "UPDATE runs SET status = ?, updated_at = ? WHERE run_id = ?",
        (new_status, now(), run_id),
    )
    audit(
        conn,
        actor,
        "run_status",
        subject=run_id,
        detail=f"{old} -> {new_status}" + (f" ({detail})" if detail else ""),
    )
    return new_status


def is_active(status: str) -> bool:
    return status in ACTIVE_STATUSES


def classify_after_restart(status: str, host_restarted: bool) -> str:
    """Determine run status after a service restart (T1.1 acceptance).

    A host restart (boot-identity change) deterministically interrupts every
    run that was active or undecidable; terminal verdicts (completed/failed/
    stopped) and states requiring explicit handling keep their status.
    """
    validate_status(status)
    if not host_restarted:
        return status
    if status in ACTIVE_STATUSES or status == "unknown":
        return "interrupted"
    return status
