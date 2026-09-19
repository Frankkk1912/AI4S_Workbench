"""T3.2 (auto-advance state machine) and T3.5 (failure/retry policy)."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from web.backend import approvals
from web.runner import db, orchestrator, preflight, submission
from web.runner.tests import helpers

STRATEGY = {
    "stages": ["em", "nvt", "npt", "md_prod"],
    "mdp_templates": {"em": {"name": "em.mdp", "sha256": "e" * 64}},
    "duration_ns": 100.0,
    "constraints": {"threads": 8, "profile": "linux-gpu"},
}


def write_receipt(
    root: Path, days_old: float = 0.0, name: str = "receipt.json"
) -> Path:
    created = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_old)
    path = root / name
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "artifact_type": "molecular_modeling_environment_receipt",
                "created_at": created.isoformat(),
                "profile": "linux-gpu",
                "ready": True,
                "report": {"tools": {}, "gromacs_container": {}},
            }
        ),
        encoding="utf-8",
    )
    return path


class OrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.conn = helpers.make_db(self.root / "runner.db", boot_id="boot-A")
        self.workspace = self.root / "workspace"
        self.workspace.mkdir()
        self.receipt = write_receipt(self.root)

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def _submit(self, request_id: str = "req-1") -> sqlite3.Row:
        return submission.submit_run(
            self.conn, request_id, "project", "em", str(self.workspace)
        )["run"]

    def _approve(self, run_id: str, strategy=None) -> dict:
        return approvals.record_approval(
            self.conn, run_id, strategy or STRATEGY, self.workspace
        )

    @staticmethod
    def _runner(results, calls):
        def run(conn, run, stage, attempt_id):
            calls["stages"].append(stage)
            calls["attempts"].append(attempt_id)
            return results.get(stage, {"status": "completed"})

        return run

    def test_advance_requires_approval(self) -> None:
        run = self._submit()
        calls = {"stages": [], "attempts": []}
        runner = self._runner({}, calls)
        with self.assertRaises(orchestrator.ApprovalRequiredError):
            orchestrator.advance_stage(
                self.conn,
                run["run_id"],
                strategy=STRATEGY,
                receipt_path=str(self.receipt),
                stage_runner=runner,
            )
        self.assertEqual(calls["stages"], [])
        self.assertEqual(db.run_status(self.conn, run["run_id"]), "queued")

    def test_advance_all_completes_four_stages_in_order(self) -> None:
        run = self._submit()
        self._approve(run["run_id"])
        calls = {"stages": [], "attempts": []}
        runner = self._runner({}, calls)
        summaries = orchestrator.advance_all(
            self.conn,
            run["run_id"],
            strategy=STRATEGY,
            receipt_path=str(self.receipt),
            stage_runner=runner,
        )
        self.assertEqual(calls["stages"], ["em", "nvt", "npt", "md_prod"])
        self.assertEqual([s["status"] for s in summaries], ["completed"] * 4)
        run_row = self.conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run["run_id"],)
        ).fetchone()
        self.assertEqual(run_row["stage"], "md_prod")
        self.assertEqual(run_row["status"], "completed")

    def test_mid_failure_stops_advancement_and_requires_reapproval(self) -> None:
        run = self._submit()
        self._approve(run["run_id"])
        calls = {"stages": [], "attempts": []}
        results = {
            "em": {"status": "completed"},
            "nvt": {"status": "failed", "reason": "nonzero exit"},
        }
        runner = self._runner(results, calls)
        summaries = orchestrator.advance_all(
            self.conn,
            run["run_id"],
            strategy=STRATEGY,
            receipt_path=str(self.receipt),
            stage_runner=runner,
        )
        self.assertEqual(calls["stages"], ["em", "nvt"])
        self.assertEqual(summaries[-1]["status"], "failed")
        run_row = self.conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run["run_id"],)
        ).fetchone()
        self.assertEqual(run_row["status"], "failed")
        self.assertEqual(run_row["stage"], "nvt")
        # re-approval signal is recorded in the audit trail
        rows = self.conn.execute(
            "SELECT event FROM audit_log WHERE subject = ? AND event = 'stage_failed_requires_reapproval'",
            (run["run_id"],),
        ).fetchall()
        self.assertEqual(len(rows), 1)

    def test_no_automatic_retry_after_failure(self) -> None:
        run = self._submit()
        self._approve(run["run_id"])
        calls = {"stages": [], "attempts": []}
        results = {"em": {"status": "failed", "reason": "missing artifact"}}
        runner = self._runner(results, calls)
        orchestrator.advance_all(
            self.conn,
            run["run_id"],
            strategy=STRATEGY,
            receipt_path=str(self.receipt),
            stage_runner=runner,
        )
        # exactly one attempt was made; the failed stage was never retried
        self.assertEqual(calls["stages"], ["em"])
        self.assertEqual(calls["attempts"], [1])
        self.assertEqual(db.run_status(self.conn, run["run_id"]), "failed")

    def test_explicit_retry_creates_new_attempt_and_preserves_old_evidence(
        self,
    ) -> None:
        run = self._submit()
        self._approve(run["run_id"])
        calls = {"stages": [], "attempts": []}
        results = {"em": {"status": "failed", "reason": "missing artifact"}}
        orchestrator.advance_all(
            self.conn,
            run["run_id"],
            strategy=STRATEGY,
            receipt_path=str(self.receipt),
            stage_runner=self._runner(results, calls),
        )
        retry = orchestrator.retry_failed(
            self.conn,
            run["run_id"],
            reason="re-run em after fixing inputs",
            strategy=STRATEGY,
            receipt_path=str(self.receipt),
        )
        self.assertEqual(retry["status"], "queued")
        calls2 = {"stages": [], "attempts": []}
        orchestrator.advance_stage(
            self.conn,
            run["run_id"],
            strategy=STRATEGY,
            receipt_path=str(self.receipt),
            stage_runner=self._runner({"em": {"status": "completed"}}, calls2),
        )
        # old attempt 1 and new attempt 2 both remain in the attempts table
        rows = self.conn.execute(
            "SELECT attempt_id FROM attempts WHERE run_id = ? AND stage = 'em' ORDER BY attempt_id",
            (run["run_id"],),
        ).fetchall()
        self.assertEqual([r["attempt_id"] for r in rows], [1, 2])
        audit = self.conn.execute(
            "SELECT event FROM audit_log WHERE subject = ? AND event = 'retry_requested'",
            (run["run_id"],),
        ).fetchall()
        self.assertEqual(len(audit), 1)

    def test_scientific_change_forces_reapproval(self) -> None:
        run = self._submit()
        self._approve(run["run_id"])
        changed = dict(STRATEGY, duration_ns=250.0)
        calls = {"stages": [], "attempts": []}
        with self.assertRaises(orchestrator.ApprovalRequiredError):
            orchestrator.advance_stage(
                self.conn,
                run["run_id"],
                strategy=changed,
                receipt_path=str(self.receipt),
                stage_runner=self._runner({}, calls),
            )

    def test_receipt_expired_fails_closed_before_next_stage(self) -> None:
        run = self._submit()
        self._approve(run["run_id"])
        calls = {"stages": [], "attempts": []}
        runner = self._runner({"em": {"status": "completed"}}, calls)
        summary = orchestrator.advance_stage(
            self.conn,
            run["run_id"],
            strategy=STRATEGY,
            receipt_path=str(self.receipt),
            stage_runner=runner,
        )
        self.assertEqual(summary["status"], "completed")
        # the run advanced to nvt; an expired receipt now fails closed
        expired = write_receipt(self.root, days_old=8.0, name="expired.json")
        with self.assertRaises(preflight.PreflightError):
            orchestrator.advance_stage(
                self.conn,
                run["run_id"],
                strategy=STRATEGY,
                receipt_path=str(expired),
                stage_runner=runner,
            )
        rows = self.conn.execute(
            "SELECT * FROM attempts WHERE run_id = ? AND stage = 'nvt'",
            (run["run_id"],),
        ).fetchall()
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
