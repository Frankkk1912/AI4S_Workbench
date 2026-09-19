"""T3.1: approval records, sidecar/SQLite consistency, and the approval gate."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from web.backend import approvals
from web.backend.tests import helpers
from web.runner import db

STRATEGY = {
    "stages": ["em", "nvt", "npt", "md_prod"],
    "mdp_templates": {"em": {"name": "em.mdp", "sha256": "e" * 64}},
    "duration_ns": 100.0,
    "constraints": {"threads": 8, "profile": "linux-gpu"},
}


def write_manifest(work: Path) -> Path:
    manifest = work / "md_run_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "artifact_type": "md_run_manifest",
                "work_dir": str(work.resolve()),
            }
        ),
        encoding="utf-8",
    )
    return manifest


class ApprovalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self.tmp, self.workspace = helpers.make_client()
        self.work = self.workspace / "project"
        self.work.mkdir()
        self.manifest = write_manifest(self.work)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _connect(self):
        return db.connect(Path(self.tmp.name) / "runner.db")

    def _submit(self, request_id: str = "req-1") -> dict:
        body = {
            "request_id": request_id,
            "project": "nrlp3",
            "stage": "em",
            "manifest_path": str(self.manifest),
            "stage_plan": {
                "deffnm": "em",
                "profile": "linux-gpu",
                "threads": 8,
                "resume": False,
            },
        }
        resp = self.client.post(
            "/runs",
            json=body,
            headers=helpers.auth_headers(**{"X-AI4S-Request": "1"}),
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        return resp.json()

    def _approve(self, run_id: str, strategy=None, kind: str = "strategy"):
        return self.client.post(
            f"/runs/{run_id}/approve",
            json={"strategy": strategy or STRATEGY, "kind": kind},
            headers=helpers.auth_headers(**{"X-AI4S-Request": "1"}),
        )

    def test_approve_records_sidecar_and_sqlite_row(self) -> None:
        run = self._submit()
        resp = self._approve(run["run_id"])
        self.assertEqual(resp.status_code, 201, resp.text)
        data = resp.json()
        sidecar = Path(data["sidecar_path"])
        self.assertTrue(sidecar.is_file())
        doc = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertEqual(doc["artifact_type"], "md_approval")
        self.assertEqual(doc["strategy_hash"], data["strategy_hash"])
        self.assertTrue(doc["confirmed"])
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (data["approval_id"],),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["run_id"], run["run_id"])
            self.assertEqual(row["payload_hash"], data["strategy_hash"])
        finally:
            conn.close()

    def test_approval_strategy_hash_is_canonical(self) -> None:
        run = self._submit()
        data = self._approve(run["run_id"]).json()
        self.assertEqual(data["strategy_hash"], approvals.strategy_hash(STRATEGY))

    def test_get_approval_returns_lineage_and_confirmed(self) -> None:
        run = self._submit()
        self._approve(run["run_id"])
        resp = self.client.get(
            f"/runs/{run['run_id']}/approval", headers=helpers.auth_headers()
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        approval = resp.json()["approval"]
        self.assertEqual(approval["kind"], "strategy")
        self.assertTrue(approval["confirmed"])
        self.assertEqual(approval["payload_hash"], approvals.strategy_hash(STRATEGY))

    def test_unapproved_strategy_execution_refused(self) -> None:
        run = self._submit()
        conn = self._connect()
        try:
            with self.assertRaises(approvals.ApprovalError):
                approvals.require_approved_strategy(conn, run["run_id"], STRATEGY)
        finally:
            conn.close()
        # HTTP control surfaces refuse too: set failed, retry without approval.
        conn = self._connect()
        try:
            db.set_run_status(conn, run["run_id"], "failed")
        finally:
            conn.close()
        receipt = self.workspace / "receipt.json"
        receipt.write_text(
            json.dumps(
                {
                    "schema_version": "1.1",
                    "artifact_type": "molecular_modeling_environment_receipt",
                    "created_at": __import__("datetime")
                    .datetime.now(__import__("datetime").timezone.utc)
                    .isoformat(),
                    "profile": "linux-gpu",
                    "ready": True,
                    "report": {"tools": {}, "gromacs_container": {}},
                }
            ),
            encoding="utf-8",
        )
        resp = self.client.post(
            f"/runs/{run['run_id']}/retry",
            json={
                "reason": "fix inputs",
                "strategy": STRATEGY,
                "receipt_path": str(receipt),
            },
            headers=helpers.auth_headers(**{"X-AI4S-Request": "1"}),
        )
        self.assertEqual(resp.status_code, 409)
        self.assertIn("approval", resp.json()["detail"].lower())

    def test_changed_strategy_requires_reapproval(self) -> None:
        run = self._submit()
        self._approve(run["run_id"])
        conn = self._connect()
        try:
            changed = dict(STRATEGY, duration_ns=200.0)
            with self.assertRaises(approvals.ApprovalError):
                approvals.require_approved_strategy(conn, run["run_id"], changed)
        finally:
            conn.close()

    def test_sidecar_tamper_is_detected(self) -> None:
        run = self._submit()
        data = self._approve(run["run_id"]).json()
        sidecar = Path(data["sidecar_path"])
        doc = json.loads(sidecar.read_text(encoding="utf-8"))
        doc["strategy"]["duration_ns"] = 999.0
        sidecar.write_text(json.dumps(doc), encoding="utf-8")
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (data["approval_id"],),
            ).fetchone()
            with self.assertRaises(approvals.ApprovalError):
                approvals.verify_approval_artifact(conn, row)
        finally:
            conn.close()

    def test_lineage_lives_outside_plan_and_manifest_files(self) -> None:
        run = self._submit()
        first = self._approve(run["run_id"]).json()
        stage_plan_path = self.work / "em_stage_plan.json"
        self.assertTrue(stage_plan_path.is_file())
        stage_plan_before = stage_plan_path.read_bytes()
        manifest_before = self.manifest.read_bytes()
        conn = self._connect()
        try:
            changed = dict(STRATEGY, duration_ns=200.0)
            doc = approvals.record_approval(
                conn,
                run["run_id"],
                changed,
                self.work,
                previous={
                    "approval_id": first["approval_id"],
                    "strategy_hash": first["strategy_hash"],
                },
            )
        finally:
            conn.close()
        self.assertEqual(doc["lineage"]["previous_approval_id"], first["approval_id"])
        self.assertEqual(
            doc["lineage"]["previous_approval_hash"], first["strategy_hash"]
        )
        # Lineage is in the DB + sidecar only; the plan/manifest bytes are untouched.
        self.assertEqual(stage_plan_path.read_bytes(), stage_plan_before)
        self.assertEqual(self.manifest.read_bytes(), manifest_before)
        self.assertNotIn("approval", json.loads(self.manifest.read_text()))
        self.assertNotIn("lineage", json.loads(self.manifest.read_text()))


if __name__ == "__main__":
    unittest.main()
