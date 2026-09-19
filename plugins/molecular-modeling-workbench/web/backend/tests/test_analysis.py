# pyright: reportMissingImports=false
"""M5 analysis API: trusted admission, immutable sessions, style, exports."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from web.backend.tests import helpers
from web.runner import db


def hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AnalysisApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client, self.tmp, self.workspace = helpers.make_client()
        self.db_path = Path(self.client.app.state.db_path)
        self.work = self.workspace / "project"
        self.work.mkdir()
        self.files = {}
        artifacts = {}
        for key in ("tpr", "xtc", "edr"):
            path = self.work / f"md_prod.{key}"
            path.write_bytes((key + "-trusted-input").encode())
            self.files[key] = path
            artifacts[key] = {"path": str(path), "sha256": hash_file(path)}
        self.manifest = self.work / "manifest.json"
        self.manifest.write_text(
            json.dumps(
                {
                    "artifact_type": "md_run_manifest",
                    "work_dir": str(self.work),
                    "stages": {
                        "md_prod": {
                            "status": "completed",
                            "artifacts": artifacts,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        conn = db.connect(self.db_path)
        try:
            stamp = db.now()
            conn.execute(
                "INSERT INTO runs(run_id, request_id, project, stage, status, work_dir, "
                "manifest_path, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    "source-run",
                    "source-request",
                    "project",
                    "md_prod",
                    "completed",
                    str(self.work),
                    str(self.manifest),
                    stamp,
                    stamp,
                ),
            )
        finally:
            conn.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _headers(self):
        return helpers.auth_headers(**{"X-AI4S-Request": "1"})

    def _body(self, request_id="analysis-request", **updates):
        body = {
            "request_id": request_id,
            "run_id": "source-run",
            "source_kind": "completed",
            "source_stage": "md_prod",
            "group": "backbone",
            "fit_group": "protein",
            "begin_ps": 0,
            "end_ps": 1000,
            "eq_start_ns": 0,
            "style": {
                "colors": {"system": "#123456"},
                "font_family": "sans-serif",
                "font_size": 8,
                "fig_size": [6.8, 7.5],
                "style_schema_version": "1.0",
            },
        }
        body.update(updates)
        return body

    def _post_session(self, body):
        return self.client.post(
            "/analysis/sessions", json=body, headers=self._headers()
        )

    def _mark_task_completed(self, task_run_id: str) -> None:
        conn = db.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE runs SET status = 'completed', updated_at = ? WHERE run_id = ?",
                (db.now(), task_run_id),
            )
            conn.execute(
                "UPDATE analysis_sessions SET status = 'completed' WHERE run_id = ?",
                (task_run_id,),
            )
        finally:
            conn.close()

    def test_completed_stage_creates_queued_session_with_separate_provenance(
        self,
    ) -> None:
        response = self._post_session(self._body())
        self.assertEqual(response.status_code, 201, response.text)
        doc = response.json()
        self.assertTrue(doc["created"])
        self.assertEqual(doc["source_kind"], "completed")
        self.assertEqual(doc["status"], "queued")
        self.assertEqual(len(doc["science"]["tpr_sha256"]), 64)
        self.assertEqual(doc["science"]["science_schema_version"], "1.0")
        self.assertEqual(doc["style"]["style_schema_version"], "1.0")
        self.assertFalse(set(doc["science"]) & set(doc["style"]))
        command_path = (
            self.work
            / "analysis"
            / "source-run"
            / doc["session_id"]
            / "analysis_command.json"
        )
        command = json.loads(command_path.read_text(encoding="utf-8"))["command"]
        self.assertEqual(command[:2], ["uv", "run"])
        self.assertIn("--locked", command)
        self.assertNotIn("mdrun", command)

    def test_drift_and_non_completed_sources_fail_closed(self) -> None:
        self.files["xtc"].write_bytes(b"changed-after-manifest")
        response = self._post_session(self._body())
        self.assertEqual(response.status_code, 409)
        self.assertIn("hash mismatch", response.json()["detail"])

        conn = db.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE runs SET status = 'running' WHERE run_id = 'source-run'"
            )
        finally:
            conn.close()
        response = self._post_session(self._body(request_id="other"))
        self.assertEqual(response.status_code, 409)
        self.assertIn("completed run", response.json()["detail"])

    def test_snapshot_requires_safely_stopped_backend_freeze(self) -> None:
        running = self.client.post(
            "/analysis/snapshots",
            json={"run_id": "source-run", "stage": "md_prod"},
            headers=self._headers(),
        )
        self.assertEqual(running.status_code, 409)
        self.assertIn("safely stopped", running.json()["detail"])

        conn = db.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE runs SET status = 'stopped' WHERE run_id = 'source-run'"
            )
        finally:
            conn.close()
        frozen = self.client.post(
            "/analysis/snapshots",
            json={"run_id": "source-run", "stage": "md_prod"},
            headers=self._headers(),
        )
        self.assertEqual(frozen.status_code, 201, frozen.text)
        snapshot_id = frozen.json()["snapshot_id"]
        session = self._post_session(
            self._body(
                source_kind="snapshot",
                snapshot_id=snapshot_id,
            )
        )
        self.assertEqual(session.status_code, 201, session.text)
        self.assertEqual(session.json()["source_kind"], "snapshot")

    def test_user_reported_or_unknown_snapshot_is_not_trusted(self) -> None:
        conn = db.connect(self.db_path)
        try:
            conn.execute(
                "UPDATE runs SET status = 'stopped' WHERE run_id = 'source-run'"
            )
        finally:
            conn.close()
        response = self._post_session(
            self._body(source_kind="snapshot", snapshot_id="user-copy")
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("not backend-registered", response.json()["detail"])

    def test_repeat_analysis_uses_new_session_and_old_bytes_stay_unchanged(
        self,
    ) -> None:
        first = self._post_session(self._body()).json()
        first_receipt = (
            self.work
            / "analysis"
            / "source-run"
            / first["session_id"]
            / "analysis_receipt.json"
        )
        before = first_receipt.read_bytes()
        self._mark_task_completed(first["task_run_id"])
        second_response = self._post_session(
            self._body(request_id="analysis-request-2")
        )
        self.assertEqual(second_response.status_code, 201, second_response.text)
        second = second_response.json()
        self.assertNotEqual(first["session_id"], second["session_id"])
        self.assertEqual(first_receipt.read_bytes(), before)

        gallery = self.client.get(
            "/analysis/runs/source-run/sessions", headers=helpers.auth_headers()
        )
        self.assertEqual(gallery.status_code, 200)
        self.assertEqual(len(gallery.json()["sessions"]), 2)

    def test_style_approval_queues_redraw_only_and_exports_are_allowlisted(
        self,
    ) -> None:
        created = self._post_session(self._body()).json()
        self._mark_task_completed(created["task_run_id"])
        before = created["science"]
        original_receipt = (
            self.work
            / "analysis"
            / "source-run"
            / created["session_id"]
            / "analysis_receipt.json"
        )
        original_bytes = original_receipt.read_bytes()
        restyled = self.client.post(
            f"/analysis/sessions/{created['session_id']}/style",
            json={
                "request_id": "redraw-request",
                "style": {
                    "colors": {"system": "#abcdef"},
                    "font_family": "serif",
                    "font_size": 12,
                    "fig_size": [10, 8],
                    "style_schema_version": "1.0",
                },
            },
            headers=self._headers(),
        )
        self.assertEqual(restyled.status_code, 200, restyled.text)
        restyled_doc = restyled.json()
        self.assertEqual(restyled_doc["science"], before)
        self.assertEqual(restyled_doc["style"]["font_size"], 12)
        self.assertEqual(restyled_doc["status"], "queued")
        self.assertEqual(original_receipt.read_bytes(), original_bytes)
        conn = db.connect(self.db_path)
        try:
            redraw = conn.execute(
                "SELECT * FROM runs WHERE run_id = ?",
                (restyled_doc["task_run_id"],),
            ).fetchone()
            command_doc = json.loads(
                Path(redraw["stage_plan_path"]).read_text(encoding="utf-8")
            )
            self.assertIsNone(command_doc["command"])
            plot_command = " ".join(command_doc["plot_command"])
            self.assertIn("md_plot_cli.py", plot_command)
            self.assertNotIn("md_analyze_cli.py", plot_command)
        finally:
            conn.close()
        self._mark_task_completed(restyled_doc["task_run_id"])

        session_dir = self.work / "analysis" / "source-run" / created["session_id"]
        figures = session_dir / "figures"
        figures.mkdir()
        payloads = {
            "png": b"\x89PNG\r\n\x1a\nfixture",
            "svg": b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
            "pdf": b"%PDF-1.4\nfixture\n%%EOF",
        }
        for extension, payload in payloads.items():
            (figures / f"diagnostics.{extension}").write_bytes(payload)
            response = self.client.get(
                f"/analysis/sessions/{created['session_id']}/exports/{extension}",
                headers=helpers.auth_headers(),
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.content, payload)
        denied = self.client.get(
            f"/analysis/sessions/{created['session_id']}/exports/html",
            headers=helpers.auth_headers(),
        )
        self.assertEqual(denied.status_code, 404)

    def test_analysis_artifact_path_escape_is_rejected(self) -> None:
        outside = Path(self.tmp.name) / "outside.xtc"
        outside.write_bytes(b"outside-workspace")
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        manifest["stages"]["md_prod"]["artifacts"]["xtc"] = {
            "path": str(outside),
            "sha256": hash_file(outside),
        }
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        response = self._post_session(self._body())
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("workspace root", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
