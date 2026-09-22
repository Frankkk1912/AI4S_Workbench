"""T1.4 (idempotency, single-instance lock, double-stage refusal) and
T1.5 (disk preflight fail-closed)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from web.runner import lock, preflight, submission
from web.runner.reconcile import DockerPort
from web.runner.tests import helpers


class SubmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.conn = helpers.make_db(self.root / "runner.db", boot_id="boot-A")

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def _submit(self, request_id: str, work_dir: str, stage: str = "em"):
        return submission.submit_run(self.conn, request_id, "project", stage, work_dir)

    def test_repeated_request_id_returns_same_run(self) -> None:
        first = self._submit("req-1", "/work")
        second = self._submit("req-1", "/work")
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["run"]["run_id"], second["run"]["run_id"])

    def test_same_work_dir_concurrent_stage_refused(self) -> None:
        self._submit("req-1", "/work", stage="em")
        with self.assertRaises(submission.SubmissionError):
            self._submit("req-2", "/work", stage="nvt")

    def test_second_runner_lock_refused(self) -> None:
        lock_path = self.root / "runner.lock"
        first = lock.RunnerLock(lock_path)
        first.acquire()
        second = lock.RunnerLock(lock_path)
        with self.assertRaises(lock.LockHeldError):
            second.acquire()
        first.release()
        # after release, a new lock can be acquired
        third = lock.RunnerLock(lock_path)
        third.acquire()
        third.release()

    def test_allocate_attempt_is_monotonic_and_two_phase(self) -> None:
        run = self._submit("req-1", "/work")["run"]
        first = submission.allocate_attempt(self.conn, run["run_id"], "em", "/work")
        second = submission.allocate_attempt(self.conn, run["run_id"], "em", "/work")
        self.assertEqual(first, 1)
        self.assertEqual(second, 2)
        rows = self.conn.execute(
            "SELECT * FROM attempts WHERE run_id = ? ORDER BY attempt_id",
            (run["run_id"],),
        ).fetchall()
        self.assertEqual([r["attempt_id"] for r in rows], [1, 2])
        self.assertEqual([r["status"] for r in rows], ["intent", "intent"])
        self.assertIsNone(rows[0]["container_at"])


class PreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.conn = helpers.make_db(self.root / "runner.db", boot_id="boot-A")

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def test_disk_check_fails_closed_on_tiny_headroom(self) -> None:
        result = preflight.check_disk(str(self.root), estimated_bytes=10**12)
        self.assertFalse(result["ok"])
        self.assertIn("insufficient disk", result["reason"])

    def test_disk_check_passes_on_reasonable_headroom(self) -> None:
        result = preflight.check_disk(str(self.root), estimated_bytes=1)
        self.assertTrue(result["ok"])

    def test_docker_unreachable_fails_closed(self) -> None:
        result = preflight.check_docker(DockerPort("/nonexistent/docker"))
        self.assertFalse(result["ok"])
        self.assertIn("not reachable", result["reason"])

    def test_run_preflight_rejects_and_audits(self) -> None:
        with self.assertRaises(preflight.PreflightError):
            preflight.run_preflight(
                self.conn,
                str(self.root),
                estimated_bytes=10**12,
                docker=DockerPort("/nonexistent/docker"),
                subject="run-x",
            )
        rows = self.conn.execute(
            "SELECT event FROM audit_log WHERE subject = 'run-x'"
        ).fetchall()
        self.assertIn("preflight_disk", [r["event"] for r in rows])
        self.assertIn("preflight_docker", [r["event"] for r in rows])


class AnalysisTaskSubmissionTests(unittest.TestCase):
    """T5.5: analysis shares the same idempotency/lock/audit channels as MD."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.conn = helpers.make_db(self.root / "runner.db", boot_id="boot-A")

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def _submit(self, request_id, work_dir, stage, kind="container"):
        return submission.submit_run(
            self.conn, request_id, "project", stage, work_dir, kind=kind
        )

    def test_analysis_submission_is_idempotent(self) -> None:
        first = self._submit("req-a", "/work", "analysis", kind="analysis")
        second = self._submit("req-a", "/work", "analysis", kind="analysis")
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(first["run"]["run_id"], second["run"]["run_id"])
        self.assertEqual(first["run"]["stage"], "analysis")

    def test_analysis_stage_is_reserved(self) -> None:
        with self.assertRaises(submission.SubmissionError):
            self._submit("req-a", "/work", "analysis", kind="container")

    def test_analysis_requires_analysis_stage(self) -> None:
        with self.assertRaises(submission.SubmissionError):
            self._submit("req-a", "/work", "em", kind="analysis")

    def test_unsupported_kind_rejected(self) -> None:
        with self.assertRaises(submission.SubmissionError):
            self._submit("req-a", "/work", "em", kind="bogus")

    def test_analysis_and_md_share_workdir_lock(self) -> None:
        self._submit("req-md", "/work", "em", kind="container")
        with self.assertRaises(submission.SubmissionError):
            self._submit("req-analysis", "/work", "analysis", kind="analysis")

    def test_analysis_attempt_records_analysis_kind(self) -> None:
        run = self._submit("req-a", "/work", "analysis", kind="analysis")["run"]
        attempt_id = submission.allocate_attempt(
            self.conn, run["run_id"], "analysis", "/work", kind="analysis"
        )
        self.assertEqual(attempt_id, 1)
        row = self.conn.execute(
            "SELECT kind, stage FROM attempts WHERE run_id = ?", (run["run_id"],)
        ).fetchone()
        self.assertEqual(row["kind"], "analysis")
        self.assertEqual(row["stage"], "analysis")


if __name__ == "__main__":
    unittest.main()
