# pyright: reportMissingImports=false
"""T6.9: additive schema migration, read-back, and private data layout."""

from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

from web.runner import db, migrate


class MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.schema = Path(db.__file__).with_name("schema.sql")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_uninitialized_database_reaches_current_version(self) -> None:
        conn = db.connect(self.root / "fresh.db")
        previous = migrate.migrate(
            conn, schema_path=self.schema, target_version=db.SCHEMA_VERSION
        )
        self.assertEqual(previous, 0)
        self.assertEqual(migrate.read_schema_version(conn), db.SCHEMA_VERSION)
        self.assertIsNotNone(
            conn.execute(
                "SELECT name FROM sqlite_master WHERE name = 'analysis_sessions'"
            ).fetchone()
        )
        conn.close()

    def test_version_two_adds_attempt_kind_and_is_idempotent(self) -> None:
        conn = db.connect(self.root / "old.db")
        conn.executescript(
            """
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO meta(key, value) VALUES ('schema_version', '2');
            CREATE TABLE attempts (
                attempt_id INTEGER NOT NULL,
                run_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                status TEXT NOT NULL,
                container_name TEXT NOT NULL,
                work_dir TEXT NOT NULL,
                intent_at TEXT NOT NULL,
                boot_id TEXT NOT NULL,
                PRIMARY KEY (run_id, stage, attempt_id)
            );
            """
        )
        previous = migrate.migrate(
            conn, schema_path=self.schema, target_version=db.SCHEMA_VERSION
        )
        self.assertEqual(previous, 2)
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(attempts)").fetchall()
        }
        self.assertIn("kind", columns)
        self.assertEqual(
            migrate.migrate(
                conn, schema_path=self.schema, target_version=db.SCHEMA_VERSION
            ),
            db.SCHEMA_VERSION,
        )
        self.assertEqual(migrate.read_schema_version(conn), db.SCHEMA_VERSION)
        conn.close()

    def test_api_reinitialization_preserves_recorded_boot_identity(self) -> None:
        conn = db.connect(self.root / "boot.db")
        db.init(conn, boot_id="boot-before-restart")
        db.init(conn)
        self.assertEqual(db.recorded_boot_id(conn), "boot-before-restart")
        conn.close()

    def test_newer_schema_fails_closed(self) -> None:
        conn = db.connect(self.root / "future.db")
        conn.executescript(
            "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
            "INSERT INTO meta(key, value) VALUES ('schema_version', '999');"
        )
        with self.assertRaises(migrate.MigrationError):
            migrate.migrate(
                conn, schema_path=self.schema, target_version=db.SCHEMA_VERSION
            )
        conn.close()

    def test_data_directory_defaults_inside_workspace_and_is_private(self) -> None:
        workspace = self.root / "workspace"
        workspace.mkdir()
        data_dir = migrate.resolve_data_dir(workspace)
        paths = migrate.data_paths(data_dir)
        self.assertEqual(paths["root"], workspace / migrate.DEFAULT_DATA_DIR_NAME)
        self.assertEqual(stat.S_IMODE(paths["root"].stat().st_mode), 0o700)
        self.assertEqual(paths["db"].parent, paths["root"])
        self.assertEqual(paths["token"].parent, paths["root"])


if __name__ == "__main__":
    unittest.main()
