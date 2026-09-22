"""Additive SQLite schema migration and workbench data-directory layout (T6.9).

The default data directory lives inside the selected workspace so runs, the
SQLite authority, and local credentials share one user-owned boundary. A
caller may explicitly override it. Migrations are additive, idempotent, and
verify the persisted schema version before returning.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_DATA_DIR_NAME = ".ai4s-md-workbench"
ACCESS_FILE_NAME = "access.token"
DB_FILE_NAME = "runner.db"


class MigrationError(RuntimeError):
    """Raised when a database cannot be migrated safely."""


def resolve_data_dir(
    workspace_root: str | Path, configured: str | Path | None = None
) -> Path:
    """Return the configured data directory or the workspace-local default."""
    if configured is not None:
        return Path(configured).expanduser().resolve()
    return (Path(workspace_root).expanduser().resolve() / DEFAULT_DATA_DIR_NAME)


def ensure_data_dir(path: str | Path) -> Path:
    """Create a private user-owned data directory and enforce mode 0700."""
    resolved = Path(path).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(resolved, 0o700)
    return resolved


def data_paths(data_dir: str | Path) -> dict[str, Path]:
    root = ensure_data_dir(data_dir)
    logs = root / "logs"
    evidence = root / "evidence"
    for directory in (logs, evidence):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
    return {
        "root": root,
        "db": root / DB_FILE_NAME,
        "token": root / ACCESS_FILE_NAME,
        "logs": logs,
        "evidence": evidence,
    }


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def read_schema_version(conn: sqlite3.Connection) -> int:
    """Read the persisted version; an uninitialized database is version zero."""
    if not _table_exists(conn, "meta"):
        return 0
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError) as exc:
        raise MigrationError("schema_version is not an integer") from exc


def migrate(
    conn: sqlite3.Connection,
    *,
    schema_path: Path,
    target_version: int,
) -> int:
    """Apply known additive changes and verify the resulting version.

    Version 1/2 databases predate native analysis attempts and may not have the
    ``attempts.kind`` discriminator. The current schema script creates all new
    tables/indexes with ``IF NOT EXISTS``; the explicit ALTER covers the one
    additive column that CREATE TABLE cannot retrofit.
    """
    previous = read_schema_version(conn)
    if previous > target_version:
        raise MigrationError(
            f"database schema {previous} is newer than supported {target_version}"
        )

    conn.executescript(schema_path.read_text(encoding="utf-8"))
    if "kind" not in _columns(conn, "attempts"):
        conn.execute(
            "ALTER TABLE attempts ADD COLUMN kind TEXT NOT NULL DEFAULT 'container'"
        )

    conn.execute(
        "INSERT INTO meta(key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(target_version),),
    )
    persisted = read_schema_version(conn)
    if persisted != target_version:
        raise MigrationError(
            f"schema migration read-back failed: expected {target_version}, got {persisted}"
        )
    return previous
