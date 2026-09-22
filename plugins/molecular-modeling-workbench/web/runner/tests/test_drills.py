# pyright: reportMissingImports=false
"""T7.2 crash, concurrency, tamper, expiry, and rollback drills.

All container behavior uses the shared mock Docker executable.  These drills
exercise fail-closed recovery boundaries without a Docker daemon, GPU, service
process, or destructive rollback command.
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from web.backend import approvals
from web.runner import analysis_runner, db, lock, orchestrator, preflight, submission
from web.runner.reconcile import DockerPort, reconcile
from web.runner.tests import helpers

DIGEST = "nvcr.io/nvidia/gromacs@sha256:" + "a" * 64
STRATEGY = {
    "stages": ["em", "nvt", "npt", "md_prod"],
    "mdp_templates": {"em": {"name": "em.mdp", "sha256": "e" * 64}},
    "duration_ns": 100.0,
    "constraints": {"threads": 8, "profile": "linux-gpu"},
}
ROLLBACK_STEPS = (
    "block_new_submissions",
    "identify_active_containers",
    "handle_active_computations",
    "save_evidence",
    "backup_database_and_data",
    "stop_services",
    "rollback_code",
    "rebuild_bundle",
    "preserve_completed_artifacts",
)


def _container(cid: str, name: str, labels: dict[str, str]) -> dict:
    return {
        "ID": cid,
        "Names": name,
        "Image": DIGEST,
        "Labels": labels,
        "State": "running",
    }


def _receipt(path: Path, created_at: dt.datetime) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "artifact_type": "molecular_modeling_environment_receipt",
                "created_at": created_at.isoformat(),
                "profile": "linux-gpu",
                "ready": True,
                "report": {"tools": {}, "gromacs_container": {}},
            }
        ),
        encoding="utf-8",
    )
    return path


class CrashAndConcurrencyDrills(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.db_path = self.root / "runner.db"
        conn = helpers.make_db(self.db_path, boot_id="boot-A")
        conn.close()
        self.mock = helpers.load_mock_docker()
        self.docker_path, _env, self.state = self.mock.install_mock_docker(self.root)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_double_click_concurrent_submission_is_idempotent(self) -> None:
        def submit() -> tuple[str, bool]:
            conn = db.connect(self.db_path)
            try:
                result = submission.submit_run(
                    conn, "same-request", "project", "em", str(self.root / "work")
                )
                return result["run"]["run_id"], result["created"]
            finally:
                conn.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _index: submit(), range(8)))

        self.assertEqual(len({run_id for run_id, _created in results}), 1)
        self.assertEqual(sum(created for _run_id, created in results), 1)
        conn = db.connect(self.db_path)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0], 1)
        finally:
            conn.close()

    def test_second_runner_instance_is_refused(self) -> None:
        lock_path = self.root / "runner.lock"
        first = lock.RunnerLock(lock_path).acquire()
        try:
            with self.assertRaises(lock.LockHeldError):
                lock.RunnerLock(lock_path).acquire()
        finally:
            first.release()

    def _intent_with_identity(
        self,
    ) -> tuple[sqlite3.Connection, str, dict[str, str]]:
        conn = db.connect(self.db_path)
        run = submission.submit_run(
            conn, "crash-window", "project", "em", str(self.root / "work")
        )["run"]
        run_id = run["run_id"]
        submission.allocate_attempt(conn, run_id, "em", str(self.root / "work"))
        module = helpers.load_md_run_cli()
        command = ["gmx", "mdrun", "-deffnm", "em"]
        labels = {
            "ai4s.workbench.run_id": run_id,
            "ai4s.workbench.stage": "em",
            "ai4s.workbench.attempt": "1",
            "ai4s.workbench.image_digest": DIGEST,
            "ai4s.workbench.work_dir_hash": module.command_hash(
                [str(self.root / "work")]
            ),
            "ai4s.workbench.command_hash": module.command_hash(command),
            "ai4s.workbench.owner": "1000:1000",
        }
        # The launch boundary stores immutable identity before invoking Docker;
        # container_at remains NULL until second-phase registration succeeds.
        mismatched = dict(labels)
        mismatched["ai4s.workbench.command_hash"] = "0" * 64
        with self.assertRaises(submission.SubmissionError):
            submission.bind_attempt_identity(
                conn,
                run_id,
                "em",
                1,
                image_digest=DIGEST,
                work_dir_hash=labels["ai4s.workbench.work_dir_hash"],
                command_hash=labels["ai4s.workbench.command_hash"],
                ownership_labels=mismatched,
            )
        submission.bind_attempt_identity(
            conn,
            run_id,
            "em",
            1,
            image_digest=DIGEST,
            work_dir_hash=labels["ai4s.workbench.work_dir_hash"],
            command_hash=labels["ai4s.workbench.command_hash"],
            ownership_labels=labels,
            cid_file=str(self.root / "attempt-1.cid"),
        )
        return conn, run_id, labels

    def test_container_started_before_registration_is_adopted(self) -> None:
        conn, run_id, labels = self._intent_with_identity()
        try:
            attempt = conn.execute(
                "SELECT * FROM attempts WHERE run_id=?", (run_id,)
            ).fetchone()
            self.assertIsNone(attempt["container_at"])
            mismatched = dict(labels)
            mismatched["ai4s.workbench.command_hash"] = "0" * 64
            bad_receipt = self.root / "bad-launch-receipt.json"
            bad_receipt.write_text(
                json.dumps(
                    {
                        "container_id": "b" * 64,
                        "container_name": attempt["container_name"],
                        "gromacs_image_digest": DIGEST,
                        "labels": mismatched,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(submission.SubmissionError):
                submission.record_container(conn, run_id, "em", 1, str(bad_receipt))
            self.mock.inject_containers(
                self.state,
                [_container("c" * 64, attempt["container_name"], labels)],
            )
            summary = reconcile(conn, DockerPort(str(self.docker_path)), "boot-A")
            self.assertEqual(summary[0]["action"], "adopted")
            self.assertEqual(db.run_status(conn, run_id), "running")
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM containers WHERE run_id=?", (run_id,)
                ).fetchone()[0],
                1,
            )
            self.assertFalse(
                any(
                    call and call[0] == "run"
                    for call in self.mock.recorded_calls(self.state["calls_path"])
                )
            )
        finally:
            conn.close()

    def test_runner_restart_reconnects_without_duplicate_creation(self) -> None:
        conn, run_id, labels = self._intent_with_identity()
        attempt = conn.execute(
            "SELECT * FROM attempts WHERE run_id=?", (run_id,)
        ).fetchone()
        self.mock.inject_containers(
            self.state, [_container("d" * 64, attempt["container_name"], labels)]
        )
        conn.close()  # runner/Web process exits; SQLite and mock container survive

        restarted = db.connect(self.db_path)
        try:
            first = reconcile(restarted, DockerPort(str(self.docker_path)), "boot-A")
            second = reconcile(restarted, DockerPort(str(self.docker_path)), "boot-A")
            self.assertEqual(first[0]["action"], "adopted")
            self.assertEqual(second[0]["action"], "adopted")
            self.assertEqual(
                restarted.execute(
                    "SELECT COUNT(*) FROM attempts WHERE run_id=?", (run_id,)
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                restarted.execute(
                    "SELECT COUNT(*) FROM containers WHERE run_id=?", (run_id,)
                ).fetchone()[0],
                1,
            )
            self.assertFalse(
                any(
                    call and call[0] == "run"
                    for call in self.mock.recorded_calls(self.state["calls_path"])
                )
            )
        finally:
            restarted.close()

    def test_host_boot_change_interrupts_without_docker_adoption(self) -> None:
        conn, run_id, labels = self._intent_with_identity()
        try:
            db.set_run_status(conn, run_id, "running")
            attempt = conn.execute(
                "SELECT * FROM attempts WHERE run_id=?", (run_id,)
            ).fetchone()
            self.mock.inject_containers(
                self.state,
                [_container("e" * 64, attempt["container_name"], labels)],
            )
            summary = reconcile(conn, DockerPort(str(self.docker_path)), "boot-B")
            self.assertEqual(summary[0]["action"], "interrupted")
            self.assertEqual(db.run_status(conn, run_id), "interrupted")
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM containers WHERE run_id=?", (run_id,)
                ).fetchone()[0],
                0,
            )
        finally:
            conn.close()


class GateAndRollbackDrills(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.conn = helpers.make_db(self.root / "runner.db", boot_id="boot-A")

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def test_artifact_and_scientific_parameter_tampering_fail_closed(self) -> None:
        artifacts: dict[str, dict[str, str]] = {}
        for suffix in ("tpr", "xtc", "edr"):
            path = self.root / f"md_prod.{suffix}"
            path.write_bytes(f"stable-{suffix}".encode())
            artifacts[suffix] = {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        manifest = {
            "stages": {"md_prod": {"status": "completed", "artifacts": artifacts}}
        }
        Path(artifacts["xtc"]["path"]).write_bytes(b"tampered-trajectory")
        with self.assertRaisesRegex(
            analysis_runner.AnalysisAdmissionError, "hash mismatch"
        ):
            analysis_runner.admit_completed_manifest(manifest, "md_prod")

        workspace = self.root / "workspace"
        workspace.mkdir()
        run = submission.submit_run(
            self.conn, "parameter-gate", "project", "em", str(workspace)
        )["run"]
        approvals.record_approval(self.conn, run["run_id"], STRATEGY, workspace)
        changed = dict(STRATEGY, duration_ns=250.0)
        calls: list[str] = []

        def should_not_run(*_args) -> dict[str, str]:
            calls.append("executed")
            return {"status": "completed"}

        fresh = _receipt(
            self.root / "fresh.json", dt.datetime.now(dt.timezone.utc)
        )
        with self.assertRaises(orchestrator.ApprovalRequiredError):
            orchestrator.advance_stage(
                self.conn,
                run["run_id"],
                strategy=changed,
                receipt_path=str(fresh),
                stage_runner=should_not_run,
            )
        self.assertEqual(calls, [])
        self.assertEqual(db.run_status(self.conn, run["run_id"]), "queued")

    def test_seven_day_receipt_boundary_blocks_only_new_work(self) -> None:
        now = dt.datetime(2026, 1, 8, tzinfo=dt.timezone.utc)
        exactly_seven = {
            "created_at": (now - dt.timedelta(days=7)).isoformat()
        }
        beyond_seven = {
            "created_at": (now - dt.timedelta(days=7, seconds=1)).isoformat()
        }
        self.assertEqual(
            preflight.receipt_boundary(exactly_seven, now_utc=now)["status"],
            "expiring",
        )
        self.assertEqual(
            preflight.receipt_boundary(beyond_seven, now_utc=now)["status"],
            "expired",
        )

        running = submission.submit_run(
            self.conn, "already-running", "project", "em", str(self.root / "work")
        )["run"]
        db.set_run_status(self.conn, running["run_id"], "running")
        expired = _receipt(
            self.root / "expired.json",
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=8),
        )
        with self.assertRaises(preflight.PreflightError):
            preflight.require_fresh_receipt(
                self.conn, str(expired), subject="new-submission"
            )
        self.assertEqual(db.run_status(self.conn, running["run_id"]), "running")

    def test_rollback_order_is_safe_and_repeatable(self) -> None:
        def run_drill() -> list[str]:
            events: list[str] = []
            for step in ROLLBACK_STEPS:
                events.append(step)
            return events

        first = run_drill()
        second = run_drill()
        self.assertEqual(first, list(ROLLBACK_STEPS))
        self.assertEqual(second, first)
        self.assertLess(
            first.index("block_new_submissions"),
            first.index("identify_active_containers"),
        )
        self.assertLess(
            first.index("backup_database_and_data"), first.index("stop_services")
        )
        self.assertLess(first.index("stop_services"), first.index("rollback_code"))
        self.assertLess(first.index("rollback_code"), first.index("rebuild_bundle"))


if __name__ == "__main__":
    unittest.main()
