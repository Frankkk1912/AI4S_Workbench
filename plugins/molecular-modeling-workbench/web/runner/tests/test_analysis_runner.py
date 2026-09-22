# pyright: reportMissingImports=false
"""M5 T5.2/T5.3/T5.5 analysis runner contracts."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from web.runner import analysis_runner, db, reconcile, submission
from web.runner.tests import helpers


class AnalysisAdmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.files = {}
        self.artifacts = {}
        for key in ("tpr", "xtc", "edr"):
            path = self.root / f"md_prod.{key}"
            path.write_bytes((key + "-content").encode())
            self.files[key] = path
            self.artifacts[key] = {
                "path": str(path),
                "sha256": analysis_runner.sha256_file(path),
            }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_completed_manifest_is_admitted_and_drift_is_rejected(self) -> None:
        manifest = {
            "stages": {"md_prod": {"status": "completed", "artifacts": self.artifacts}}
        }
        hashes, files = analysis_runner.admit_completed_manifest(manifest, "md_prod")
        self.assertEqual(hashes["xtc_sha256"], self.artifacts["xtc"]["sha256"])
        self.assertEqual(files["tpr"], self.files["tpr"])
        self.files["xtc"].write_bytes(b"half-written-drift")
        with self.assertRaisesRegex(
            analysis_runner.AnalysisAdmissionError, "hash mismatch"
        ):
            analysis_runner.admit_completed_manifest(manifest, "md_prod")

    def test_incomplete_stage_and_user_reported_snapshot_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            analysis_runner.AnalysisAdmissionError, "not completed"
        ):
            analysis_runner.admit_completed_manifest(
                {"stages": {"md_prod": {"status": "running"}}}, "md_prod"
            )
        with self.assertRaisesRegex(
            analysis_runner.AnalysisAdmissionError, "user-reported"
        ):
            analysis_runner.admit_snapshot(
                {
                    "artifact_type": analysis_runner.SNAPSHOT_ARTIFACT_TYPE,
                    "created_by": "user",
                    "files": self.artifacts,
                }
            )

    def test_frozen_snapshot_is_copied_registered_and_reverified(self) -> None:
        conn = helpers.make_db(self.root / "runner.db", boot_id="boot-A")
        try:
            record, path = analysis_runner.freeze_snapshot(
                "source-run", "md_prod", self.files, self.root / "snapshots"
            )
            analysis_runner.register_snapshot(conn, record, path)
            loaded = analysis_runner.load_registered_snapshot(
                conn, record["snapshot_id"], "source-run"
            )
            hashes, frozen = analysis_runner.admit_snapshot(loaded)
            self.assertEqual(hashes["edr_sha256"], self.artifacts["edr"]["sha256"])
            self.assertNotEqual(frozen["xtc"], self.files["xtc"])
            Path(loaded["files"]["xtc"]["path"]).write_bytes(b"drift")
            with self.assertRaisesRegex(
                analysis_runner.AnalysisAdmissionError, "hash mismatch"
            ):
                analysis_runner.admit_snapshot(loaded)
        finally:
            conn.close()

    def test_sessions_are_exclusive_and_receipt_sections_are_disjoint(self) -> None:
        first_id, first = analysis_runner.create_session_dir(self.root, "run-1")
        second_id, second = analysis_runner.create_session_dir(self.root, "run-1")
        self.assertNotEqual(first_id, second_id)
        self.assertNotEqual(first, second)
        science = {
            "tpr_sha256": "a" * 64,
            "xtc_sha256": "b" * 64,
            "edr_sha256": "c" * 64,
            "group": "backbone",
            "fit_group": "backbone",
            "begin_ps": 0,
            "end_ps": 1000,
            "eq_start_ns": 0,
            "cli_version": "1.0",
        }
        style = {
            "colors": {"system": "#123456"},
            "font_family": "sans-serif",
            "font_size": 8,
            "fig_size": [6.8, 7.5],
            "style_schema_version": "1.0",
        }
        receipt = analysis_runner.build_analysis_receipt(
            science,
            style,
            source_kind="completed",
            style_source_sha256="d" * 64,
        )
        self.assertFalse(set(receipt["science"]) & set(receipt["style"]))
        self.assertEqual(receipt["science"]["science_schema_version"], "1.0")
        self.assertEqual(receipt["style"]["style_schema_version"], "1.0")
        self.assertEqual(len(receipt["science"]["science_source_artifact_sha256"]), 64)
        self.assertEqual(len(receipt["style"]["style_source_artifact_sha256"]), 64)
        with self.assertRaises(analysis_runner.AnalysisReceiptError):
            analysis_runner.build_analysis_receipt(
                {**science, "font_size": 8},
                style,
                source_kind="completed",
                style_source_sha256="d" * 64,
            )


class AnalysisTaskTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.conn = helpers.make_db(self.root / "runner.db", boot_id="boot-A")

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def _task(self):
        return submission.submit_run(
            self.conn,
            "analysis-request",
            "project",
            "analysis",
            str(self.root),
            kind="analysis",
        )["run"]

    def test_native_task_uses_analysis_attempt_and_never_constructs_mdrun(self) -> None:
        run = self._task()
        self.conn.execute(
            "INSERT INTO analysis_sessions(session_id, run_id, stage, status, params, created_at) "
            "VALUES (?,?,?,?,?,?)",
            ("session-1", run["run_id"], "md_prod", "queued", "{}", db.now()),
        )
        seen = []

        def fake_runner(command, **kwargs):
            seen.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, "ok", "")

        result = analysis_runner.run_analysis_task(
            self.conn,
            run["run_id"],
            "session-1",
            ["uv", "run", "python", "md_analyze_cli.py", "diagnostics"],
            plot_command=["python3", "md_plot_cli.py", "diagnostics"],
            runner=fake_runner,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(seen), 2)
        self.assertNotIn("mdrun", seen[0][0])
        self.assertNotIn("mdrun", seen[1][0])
        row = self.conn.execute(
            "SELECT kind, status FROM attempts WHERE run_id = ?", (run["run_id"],)
        ).fetchone()
        self.assertEqual((row["kind"], row["status"]), ("analysis", "completed"))
        self.assertEqual(db.run_status(self.conn, run["run_id"]), "completed")

    def test_service_restart_interrupts_native_analysis_without_docker_lookup(
        self,
    ) -> None:
        run = self._task()
        submission.allocate_attempt(
            self.conn, run["run_id"], "analysis", str(self.root), kind="analysis"
        )
        self.conn.execute(
            "INSERT INTO analysis_sessions(session_id, run_id, stage, status, params, created_at) "
            "VALUES (?,?,?,?,?,?)",
            ("session-1", run["run_id"], "md_prod", "queued", "{}", db.now()),
        )

        class NoDocker:
            def find_by_label(self, *_args):
                raise AssertionError("native analysis must not query Docker")

        summary = reconcile.reconcile(self.conn, NoDocker(), current_boot="boot-A")
        self.assertEqual(summary[0]["action"], "interrupted")
        self.assertEqual(db.run_status(self.conn, run["run_id"]), "interrupted")
        status = self.conn.execute(
            "SELECT status FROM analysis_sessions WHERE session_id = 'session-1'"
        ).fetchone()["status"]
        self.assertEqual(status, "interrupted")

    def test_command_is_uv_locked_and_export_allowlist_fails_closed(self) -> None:
        command = analysis_runner.build_analysis_command(
            self.root,
            {"tpr": "a.tpr", "xtc": "a.xtc", "edr": "a.edr"},
            self.root / "session",
            {"group": "backbone", "fit_group": "protein"},
        )
        self.assertEqual(command[:2], ["uv", "run"])
        self.assertIn("--locked", command)
        self.assertIn("diagnostics", command)
        self.assertNotIn("mdrun", command)
        style_path, _ = analysis_runner.write_style(
            self.root,
            {
                "colors": {"system": "#123456"},
                "font_family": "sans-serif",
                "font_size": 8,
                "fig_size": [6.8, 7.5],
            },
        )
        style_config = json.loads(style_path.read_text(encoding="utf-8"))
        self.assertEqual(style_config["sys1_color"], "#123456")
        self.assertEqual(style_config["fig_size_diagnostics"], [6.8, 7.5])
        plot = analysis_runner.build_plot_command(
            self.root, self.root / "session", style_path, 20.0
        )
        self.assertEqual(plot[:2], ["uv", "run"])
        self.assertIn("--locked", plot)
        self.assertIn("md_plot_cli.py", " ".join(plot))
        self.assertIn("diagnostics", plot)
        with self.assertRaises(analysis_runner.AnalysisAdmissionError):
            analysis_runner.session_export_path(self.root, "html")

    def test_plot_only_redraw_never_runs_scientific_command(self) -> None:
        run = submission.submit_run(
            self.conn,
            "redraw-request",
            "project",
            "analysis",
            str(self.root),
            kind="analysis",
        )["run"]
        plot_command = ["uv", "run", "python", "md_plot_cli.py", "diagnostics"]
        self.conn.execute(
            "INSERT INTO analysis_sessions(session_id, run_id, stage, status, params, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (
                "session-redraw",
                run["run_id"],
                "md_prod",
                "queued",
                json.dumps({"command": None, "plot_command": plot_command}),
                db.now(),
            ),
        )
        seen = []

        def fake_runner(command, **_kwargs):
            seen.append(command)
            return subprocess.CompletedProcess(command, 0, "ok", "")

        result = analysis_runner.run_queued_analysis_task(
            self.conn,
            run["run_id"],
            runner=fake_runner,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(seen), 1)
        self.assertIn("md_plot_cli.py", seen[0])
        self.assertNotIn("md_analyze_cli.py", seen[0])
        self.assertEqual(db.run_status(self.conn, run["run_id"]), "completed")


if __name__ == "__main__":
    unittest.main()
