"""T1.1: schema authority, status set, transition table, unknown vs interrupted."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from web.runner import db
from web.runner.tests import helpers


class DbAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.conn = helpers.make_db(self.root / "runner.db", boot_id="boot-A")

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def test_schema_records_version_and_boot_id(self) -> None:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        self.assertEqual(row["value"], str(db.SCHEMA_VERSION))
        self.assertEqual(db.recorded_boot_id(self.conn), "boot-A")
        self.assertFalse(db.boot_changed(self.conn, current="boot-A"))

    def test_request_id_unique_constraint(self) -> None:
        stamp = db.now()
        args = ("r1", "req-1", "p", "em", "queued", "/work", stamp, stamp)
        self.conn.execute(
            "INSERT INTO runs(run_id, request_id, project, stage, status, work_dir, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            args,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO runs(run_id, request_id, project, stage, status, work_dir, "
                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                ("r2", "req-1", "p", "em", "queued", "/work2", stamp, stamp),
            )

    def test_attempts_primary_key_is_run_stage_attempt(self) -> None:
        self.conn.execute(
            "INSERT INTO runs(run_id, request_id, project, stage, status, work_dir, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            ("r1", "req-1", "p", "em", "queued", "/work", db.now(), db.now()),
        )
        args = (
            1,
            "r1",
            "em",
            "intent",
            "container",
            "ai4s-md-r1-em-1",
            "/work",
            db.now(),
            db.current_boot_id(),
        )
        self.conn.execute(
            "INSERT INTO attempts(attempt_id, run_id, stage, status, kind, container_name, "
            "work_dir, intent_at, boot_id) VALUES (?,?,?,?,?,?,?,?,?)",
            args,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO attempts(attempt_id, run_id, stage, status, kind, container_name, "
                "work_dir, intent_at, boot_id) VALUES (?,?,?,?,?,?,?,?,?)",
                args,
            )

    def test_status_set_and_transition_legality(self) -> None:
        self.assertIn("unknown", db.RUN_STATUSES)
        self.assertIn("interrupted", db.RUN_STATUSES)
        # canonical chain
        self.assertTrue(db.can_transition("queued", "running"))
        self.assertTrue(db.can_transition("running", "stopping"))
        self.assertTrue(db.can_transition("stopping", "stopped"))
        self.assertTrue(db.can_transition("running", "completed"))
        self.assertTrue(db.can_transition("running", "failed"))
        self.assertTrue(db.can_transition("running", "interrupted"))
        # self-transition allowed (idempotent no-op)
        self.assertTrue(db.can_transition("completed", "completed"))
        # illegal jumps
        self.assertFalse(db.can_transition("completed", "running"))
        self.assertFalse(db.can_transition("failed", "running"))
        self.assertFalse(db.can_transition("interrupted", "running"))
        self.assertFalse(db.can_transition("stopped", "completed"))
        with self.assertRaises(db.UnknownStatusError):
            db.validate_status("bogus")

    def test_classify_after_restart(self) -> None:
        # host restart interrupts every active/undecidable run, never terminal.
        self.assertEqual(db.classify_after_restart("running", True), "interrupted")
        self.assertEqual(db.classify_after_restart("queued", True), "interrupted")
        self.assertEqual(db.classify_after_restart("unknown", True), "interrupted")
        self.assertEqual(db.classify_after_restart("completed", True), "completed")
        self.assertEqual(db.classify_after_restart("failed", True), "failed")
        self.assertEqual(db.classify_after_restart("stopped", True), "stopped")
        # no host restart -> status unchanged
        self.assertEqual(db.classify_after_restart("running", False), "running")
        self.assertEqual(db.classify_after_restart("unknown", False), "unknown")

    def test_set_run_status_transitions_and_audits(self) -> None:
        self.conn.execute(
            "INSERT INTO runs(run_id, request_id, project, stage, status, work_dir, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            ("r1", "req-1", "p", "em", "queued", "/work", db.now(), db.now()),
        )
        db.set_run_status(self.conn, "r1", "running")
        self.assertEqual(db.run_status(self.conn, "r1"), "running")
        # running -> queued is not in the transition table (illegal)
        with self.assertRaises(db.TransitionError):
            db.set_run_status(self.conn, "r1", "queued")
        # verify audit trail recorded the first transition
        rows = self.conn.execute(
            "SELECT * FROM audit_log WHERE subject = 'r1' AND event = 'run_status'"
        ).fetchall()
        self.assertGreaterEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
