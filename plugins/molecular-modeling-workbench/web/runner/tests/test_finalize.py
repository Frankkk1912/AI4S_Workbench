"""T1.7: background completion closure (finalize) and shared verdict."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from web.runner import db, finalize, submission
from web.runner.tests import helpers

EM_ARTIFACTS = ["em.tpr", "em.gro", "em.log", "em.edr"]


class FinalizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.work = self.root / "work"
        self.work.mkdir()
        self.conn = helpers.make_db(self.root / "runner.db", boot_id="boot-A")
        self.stage_plan = helpers.write_stage_plan(self.root, "em", "em")
        self.manifest = helpers.write_manifest(self.root, self.work)
        self.run_id = self._submit_running_run()

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def _submit_running_run(self) -> str:
        run = submission.submit_run(
            self.conn, "req-1", "project", "em", str(self.work.resolve())
        )["run"]
        submission.allocate_attempt(
            self.conn, run["run_id"], "em", str(self.work.resolve())
        )
        db.set_run_status(self.conn, run["run_id"], "running")
        return run["run_id"]

    def _touch(self, name: str) -> None:
        (self.work / name).write_text(f"{name} content\n", encoding="utf-8")

    def test_finalize_completed_and_idempotent(self) -> None:
        for name in EM_ARTIFACTS:
            self._touch(name)
        receipt_path = self.root / "finalize_receipt.json"
        first = finalize.finalize_container(
            self.conn,
            self.run_id,
            "em",
            1,
            self.manifest,
            self.stage_plan,
            returncode=0,
            receipt_path=receipt_path,
        )
        self.assertEqual(first["status"], "completed")
        self.assertEqual(db.run_status(self.conn, self.run_id), "completed")
        self.assertEqual(len(first["artifacts"]), len(EM_ARTIFACTS))

        second = finalize.finalize_container(
            self.conn,
            self.run_id,
            "em",
            1,
            self.manifest,
            self.stage_plan,
            returncode=0,
            receipt_path=receipt_path,
        )
        # idempotent redo: same verdict, same artifact hashes, stable DB state
        self.assertEqual(second["status"], "completed")
        self.assertEqual(first["artifacts"], second["artifacts"])
        self.assertEqual(db.run_status(self.conn, self.run_id), "completed")

    def test_exit_zero_with_missing_artifacts_is_not_completed(self) -> None:
        # only the TPR exists (required by validate_stage_prerequisites);
        # gro/log/edr are missing -> exit 0 must NOT be scientific completion.
        self._touch("em.tpr")
        receipt_path = self.root / "finalize_receipt.json"
        receipt = finalize.finalize_container(
            self.conn,
            self.run_id,
            "em",
            1,
            self.manifest,
            self.stage_plan,
            returncode=0,
            receipt_path=receipt_path,
        )
        self.assertEqual(receipt["status"], "incomplete")
        self.assertNotEqual(db.run_status(self.conn, self.run_id), "completed")
        self.assertEqual(db.run_status(self.conn, self.run_id), "failed")

    def test_nonzero_exit_is_failed(self) -> None:
        for name in EM_ARTIFACTS:
            self._touch(name)
        receipt = finalize.finalize_container(
            self.conn,
            self.run_id,
            "em",
            1,
            self.manifest,
            self.stage_plan,
            returncode=1,
            receipt_path=self.root / "finalize_receipt.json",
        )
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(db.run_status(self.conn, self.run_id), "failed")

    def test_crash_before_write_leaves_no_receipt_then_redo_is_consistent(self) -> None:
        for name in EM_ARTIFACTS:
            self._touch(name)
        receipt_path = self.root / "finalize_receipt.json"
        original = finalize.atomic_write_json
        calls = {"n": 0}

        def crashing(path: Path, doc: dict) -> None:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated crash before rename")
            original(path, doc)

        finalize.atomic_write_json = crashing
        try:
            with self.assertRaises(RuntimeError):
                finalize.finalize_container(
                    self.conn,
                    self.run_id,
                    "em",
                    1,
                    self.manifest,
                    self.stage_plan,
                    returncode=0,
                    receipt_path=receipt_path,
                )
        finally:
            finalize.atomic_write_json = original
        # no partial receipt survives the crash
        self.assertFalse(receipt_path.exists())
        # redo after crash produces a consistent completed verdict
        receipt = finalize.finalize_container(
            self.conn,
            self.run_id,
            "em",
            1,
            self.manifest,
            self.stage_plan,
            returncode=0,
            receipt_path=receipt_path,
        )
        self.assertEqual(receipt["status"], "completed")
        self.assertTrue(receipt_path.is_file())
        # no temp files left behind
        leftovers = [p for p in self.root.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_preprocessing_interrupted_preserves_evidence(self) -> None:
        finalize.finalize_interrupted(
            self.conn, self.run_id, "em", 1, "grompp interrupted by service restart"
        )
        self.assertEqual(db.run_status(self.conn, self.run_id), "interrupted")
        rows = self.conn.execute(
            "SELECT * FROM audit_log WHERE subject = ? AND event = 'attempt_interrupted'",
            (self.run_id,),
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertIn("grompp interrupted", rows[0]["detail"])


if __name__ == "__main__":
    unittest.main()
