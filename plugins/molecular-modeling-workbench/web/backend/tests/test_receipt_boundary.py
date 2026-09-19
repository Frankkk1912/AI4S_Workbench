"""T3.6: 7-day environment receipt boundary and re-verify lineage."""

from __future__ import annotations

import datetime as dt
import json
import unittest
from pathlib import Path

from web.backend.tests import helpers
from web.runner import db


def write_receipt(workspace: Path, days_old: float, name: str = "receipt.json") -> Path:
    created = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_old)
    path = workspace / name
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


def write_manifest_with_receipt(work: Path, receipt: Path) -> Path:
    manifest = work / "md_run_manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "artifact_type": "md_run_manifest",
                "work_dir": str(work.resolve()),
                "environment_receipt": {"path": str(receipt), "ready": True},
            }
        ),
        encoding="utf-8",
    )
    return manifest


class ReceiptBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self.tmp, self.workspace = helpers.make_client()
        self.work = self.workspace / "project"
        self.work.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _connect(self):
        return db.connect(Path(self.tmp.name) / "runner.db")

    def _status(self, receipt: Path) -> dict:
        resp = self.client.get(
            f"/params/receipt-status?receipt_path={receipt}",
            headers=helpers.auth_headers(),
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        return resp.json()

    def _submit(self, receipt: Path, request_id: str = "req-1"):
        manifest = write_manifest_with_receipt(self.work, receipt)
        body = {
            "request_id": request_id,
            "project": "nrlp3",
            "stage": "em",
            "manifest_path": str(manifest),
            "stage_plan": {
                "deffnm": "em",
                "profile": "linux-gpu",
                "threads": 8,
                "resume": False,
            },
        }
        return self.client.post(
            "/runs",
            json=body,
            headers=helpers.auth_headers(**{"X-AI4S-Request": "1"}),
        )

    def test_receipt_status_fresh(self) -> None:
        receipt = write_receipt(self.workspace, days_old=1.0)
        self.assertEqual(self._status(receipt)["status"], "fresh")

    def test_receipt_status_expiring(self) -> None:
        receipt = write_receipt(self.workspace, days_old=6.5)
        self.assertEqual(self._status(receipt)["status"], "expiring")

    def test_receipt_status_expired_on_day8(self) -> None:
        receipt = write_receipt(self.workspace, days_old=8.0)
        data = self._status(receipt)
        self.assertEqual(data["status"], "expired")
        self.assertIn("re-run environment verify", data["message"])

    def test_day8_receipt_blocks_new_submission(self) -> None:
        receipt = write_receipt(self.workspace, days_old=8.0)
        resp = self._submit(receipt)
        self.assertEqual(resp.status_code, 409)
        self.assertIn("re-run environment verify", resp.json()["detail"])

    def test_fresh_receipt_allows_new_submission(self) -> None:
        receipt = write_receipt(self.workspace, days_old=1.0)
        resp = self._submit(receipt)
        self.assertEqual(resp.status_code, 201, resp.text)

    def test_reverify_records_new_lineage_and_preserves_history(self) -> None:
        old = write_receipt(self.workspace, days_old=8.0, name="old.json")
        new = write_receipt(self.workspace, days_old=0.0, name="new.json")
        body = {
            "previous_receipt_path": str(old),
            "new_receipt_path": str(new),
        }
        resp = self.client.post(
            "/params/receipt-verify",
            json=body,
            headers=helpers.auth_headers(**{"X-AI4S-Request": "1"}),
        )
        self.assertEqual(resp.status_code, 201, resp.text)
        first = resp.json()
        self.assertIsNotNone(first["previous_sha256"])
        self.assertNotEqual(first["new_sha256"], first["previous_sha256"])

        # Re-posting is immutable: the historical hash reference is not rewritten.
        again = self.client.post(
            "/params/receipt-verify",
            json=body,
            headers=helpers.auth_headers(**{"X-AI4S-Request": "1"}),
        ).json()
        self.assertEqual(again["new_sha256"], first["new_sha256"])
        self.assertEqual(again["previous_sha256"], first["previous_sha256"])

        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT * FROM receipt_lineage WHERE receipt_sha256 = ?",
                (first["new_sha256"],),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["previous_sha256"], first["previous_sha256"])
        finally:
            conn.close()

    def test_reverify_identical_receipt_rejected(self) -> None:
        same = write_receipt(self.workspace, days_old=0.0, name="same.json")
        resp = self.client.post(
            "/params/receipt-verify",
            json={
                "previous_receipt_path": str(same),
                "new_receipt_path": str(same),
            },
            headers=helpers.auth_headers(**{"X-AI4S-Request": "1"}),
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("new receipt", resp.json()["detail"])


if __name__ == "__main__":
    unittest.main()
