"""T3.3: SIGTERM-only stop, grace timeout, and checkpoint recovery validation."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from web.runner import db, lifecycle, submission
from web.runner.tests import helpers

DIGEST = "nvcr.io/nvidia/gromacs@sha256:" + "a" * 64


class FakeDocker:
    """Records signal calls; no docker daemon is ever required."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def signal_container(self, container_id: str, signal: str = "TERM") -> str:
        self.calls.append(["kill", f"--signal={signal}", container_id])
        return container_id


class LifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.conn = helpers.make_db(self.root / "runner.db", boot_id="boot-A")
        self.work = self.root / "work"
        self.work.mkdir()

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def _receipt(self, image_digest: str = DIGEST) -> dict:
        return {
            "schema_version": "1.1",
            "artifact_type": "molecular_modeling_environment_receipt",
            "created_at": db.now(),
            "profile": "linux-gpu",
            "ready": True,
            "report": {
                "tools": {"docker": {"available": True, "path": "/usr/bin/docker"}},
                "gromacs_container": {"available": True, "digest": image_digest},
            },
        }

    def _running_run(self, request_id: str = "req-1") -> str:
        run = submission.submit_run(
            self.conn, request_id, "project", "em", str(self.work)
        )["run"]
        submission.allocate_attempt(self.conn, run["run_id"], "em", str(self.work))
        db.set_run_status(self.conn, run["run_id"], "running")
        return run["run_id"]

    def _record_container(self, run_id: str, container_id: str = "c" * 64) -> None:
        self.conn.execute(
            "INSERT INTO containers(container_id, attempt_id, run_id, stage, name, "
            "image_digest, labels, state, first_seen_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                container_id,
                1,
                run_id,
                "em",
                f"ai4s-md-{run_id}-em-1",
                DIGEST,
                "{}",
                "running",
                db.now(),
            ),
        )

    def test_request_stop_sends_sigterm_only_and_moves_to_stopping(self) -> None:
        run_id = self._running_run()
        self._record_container(run_id)
        docker = FakeDocker()
        result = lifecycle.request_stop(
            self.conn, run_id, docker, self._receipt(), container_id="c" * 64
        )
        self.assertEqual(result["signal"], "TERM")
        self.assertEqual(result["status"], "stopping")
        self.assertEqual(db.run_status(self.conn, run_id), "stopping")
        # SIGTERM only; `docker stop` (finite timeout -> SIGKILL) is never used.
        self.assertEqual(docker.calls, [["kill", "--signal=TERM", "c" * 64]])
        self.assertFalse(any(call[0] == "stop" for call in docker.calls))

    def test_request_stop_refuses_nonowned_container(self) -> None:
        run_id = self._running_run()
        self._record_container(run_id)
        docker = FakeDocker()
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.request_stop(
                self.conn, run_id, docker, self._receipt(), container_id="d" * 64
            )
        self.assertEqual(docker.calls, [])

    def test_request_stop_refuses_unverified_entrypoint(self) -> None:
        run_id = self._running_run()
        self._record_container(run_id)
        docker = FakeDocker()
        # receipt binds a different digest -> signal forwarding unverified
        other = "nvcr.io/nvidia/gromacs@sha256:" + "b" * 64
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.request_stop(
                self.conn, run_id, docker, self._receipt(other), container_id="c" * 64
            )
        self.assertEqual(docker.calls, [])

    def test_grace_timeout_moves_to_attention_without_kill(self) -> None:
        run_id = self._running_run()
        self._record_container(run_id)
        lifecycle.request_stop(
            self.conn, run_id, FakeDocker(), self._receipt(), container_id="c" * 64
        )
        self.assertGreaterEqual(lifecycle.grace_seconds(), 15 * 60)
        result = lifecycle.mark_grace_timeout(self.conn, run_id)
        self.assertEqual(result["status"], "attention")
        self.assertEqual(db.run_status(self.conn, run_id), "attention")

    def test_force_kill_requires_authorization_and_never_claims_safe_stop(self) -> None:
        run_id = self._running_run()
        self._record_container(run_id)
        docker = FakeDocker()
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.force_kill(self.conn, run_id, docker, "c" * 64, authorized=False)
        result = lifecycle.force_kill(
            self.conn, run_id, docker, "c" * 64, authorized=True
        )
        self.assertFalse(result["safely_stopped"])
        self.assertEqual(result["signal"], "KILL")
        self.assertEqual(db.run_status(self.conn, run_id), "attention")

    def _checkpoint(
        self, name: str = "em.cpt", content: str = "checkpoint bytes\n"
    ) -> Path:
        path = self.work / name
        path.write_text(content, encoding="utf-8")
        return path

    def _tpr(self, name: str = "em.tpr", content: str = "tpr bytes\n") -> Path:
        path = self.work / name
        path.write_text(content, encoding="utf-8")
        return path

    def test_validate_checkpoint_accepts_valid_and_rejects_damaged(self) -> None:
        run_id = self._running_run()
        cpt = self._checkpoint()
        tpr = self._tpr()
        expected = hashlib.sha256(cpt.read_bytes()).hexdigest()
        verdict = lifecycle.validate_checkpoint(
            self.conn,
            run_id,
            "em",
            1,
            cpt,
            tpr,
            probe=lambda c, t: True,
            expected_checksum=expected,
        )
        self.assertTrue(verdict["valid"], verdict)

        # damaged (empty) checkpoint is refused even though it "exists"
        empty = self._checkpoint(name="empty.cpt", content="")
        verdict = lifecycle.validate_checkpoint(
            self.conn, run_id, "em", 1, empty, tpr, probe=lambda c, t: True
        )
        self.assertFalse(verdict["valid"])
        self.assertIn("missing or empty", verdict["reason"])

    def test_validate_checkpoint_rejects_checksum_probe_and_origin_mismatch(
        self,
    ) -> None:
        run_id = self._running_run()
        cpt = self._checkpoint()
        tpr = self._tpr()
        # checksum mismatch
        verdict = lifecycle.validate_checkpoint(
            self.conn, run_id, "em", 1, cpt, tpr, expected_checksum="0" * 64
        )
        self.assertFalse(verdict["valid"])
        self.assertIn("checksum", verdict["reason"])
        # readability probe rejection
        verdict = lifecycle.validate_checkpoint(
            self.conn, run_id, "em", 1, cpt, tpr, probe=lambda c, t: False
        )
        self.assertFalse(verdict["valid"])
        self.assertIn("probe", verdict["reason"])
        # attempt origin mismatch (no attempt 2 recorded)
        verdict = lifecycle.validate_checkpoint(
            self.conn, run_id, "em", 2, cpt, tpr, probe=lambda c, t: True
        )
        self.assertFalse(verdict["valid"])
        self.assertIn("attempt", verdict["reason"])

    def test_validate_checkpoint_rejects_step_ahead_of_log(self) -> None:
        run_id = self._running_run()
        cpt = self._checkpoint()
        tpr = self._tpr()
        verdict = lifecycle.validate_checkpoint(
            self.conn,
            run_id,
            "em",
            1,
            cpt,
            tpr,
            probe=lambda c, t: True,
            cpt_step=1000,
            log_step=500,
        )
        self.assertFalse(verdict["valid"])
        self.assertIn("ahead", verdict["reason"])

    def test_approve_resume_enqueues_new_attempt_only_after_validation(self) -> None:
        run_id = self._running_run()
        db.set_run_status(self.conn, run_id, "interrupted")
        cpt = self._checkpoint()
        tpr = self._tpr()
        expected = hashlib.sha256(cpt.read_bytes()).hexdigest()
        result = lifecycle.approve_resume(
            self.conn,
            run_id,
            "em",
            1,
            cpt,
            tpr,
            probe=lambda c, t: True,
            expected_checksum=expected,
        )
        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["attempt_id"], 2)
        self.assertEqual(db.run_status(self.conn, run_id), "queued")

    def test_approve_resume_refuses_damaged_checkpoint(self) -> None:
        run_id = self._running_run()
        db.set_run_status(self.conn, run_id, "interrupted")
        empty = self._checkpoint(content="")
        tpr = self._tpr()
        with self.assertRaises(lifecycle.LifecycleError):
            lifecycle.approve_resume(
                self.conn,
                run_id,
                "em",
                1,
                empty,
                tpr,
                probe=lambda c, t: True,
            )
        # still interrupted; nothing was enqueued
        self.assertEqual(db.run_status(self.conn, run_id), "interrupted")

    def test_boot_change_interrupts_without_auto_advance(self) -> None:
        run_id = self._running_run()
        self.assertEqual(db.classify_after_restart("running", True), "interrupted")
        db.set_run_status(self.conn, run_id, "interrupted")
        self.assertEqual(db.run_status(self.conn, run_id), "interrupted")


if __name__ == "__main__":
    unittest.main()
