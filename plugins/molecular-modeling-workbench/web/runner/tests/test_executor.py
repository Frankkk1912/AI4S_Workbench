# pyright: reportMissingImports=false
"""Hosted runner dispatch/finalize integration tests (mock Docker only)."""

from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from web.backend import approvals
from web.runner import db, executor, submission
from web.runner.reconcile import DockerPort
from web.runner.tests import helpers

DIGEST = "nvcr.io/nvidia/gromacs@sha256:" + "a" * 64
STRATEGY = {"stages": ["em"], "constraints": {"profile": "wsl2-gpu"}}


class ExitDocker(DockerPort):
    def container_returncode(self, container_id: str) -> int | None:
        return 0


class HostedExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.work = self.root / "work"
        self.work.mkdir()
        mock = helpers.load_mock_docker()
        self.mock = mock
        self.docker_path, _env, self.state = mock.install_mock_docker(self.root)
        receipt = self.root / "environment_receipt.json"
        receipt.write_text(
            json.dumps(
                {
                    "schema_version": "1.1",
                    "artifact_type": "molecular_modeling_environment_receipt",
                    "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "profile": "wsl2-gpu",
                    "ready": True,
                    "report": {
                        "tools": {
                            "docker": {
                                "available": True,
                                "path": str(self.docker_path),
                            }
                        },
                        "gromacs_container": {
                            "available": True,
                            "digest": DIGEST,
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        module = helpers.load_md_run_cli()
        self.stage_plan = self.root / "em_stage_plan.json"
        self.stage_plan.write_text(
            json.dumps(module.build_stage_plan("em", "em", "wsl2-gpu", 8, False)),
            encoding="utf-8",
        )
        (self.work / "em.tpr").write_text("fake tpr\n", encoding="utf-8")
        self.manifest = self.root / "md_run_manifest.json"
        self.manifest.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "artifact_type": "md_run_manifest",
                    "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "work_dir": str(self.work.resolve()),
                    "duration_plan": {"profile": "wsl2-gpu"},
                    "environment_receipt": {
                        "path": str(receipt.resolve()),
                        "ready": True,
                    },
                    "stages": {},
                }
            ),
            encoding="utf-8",
        )
        self.db_path = self.root / "runner.db"
        self.conn = helpers.make_db(self.db_path, boot_id=db.current_boot_id())
        result = submission.submit_run(
            self.conn,
            "request-1",
            "project",
            "em",
            str(self.work),
            manifest_path=str(self.manifest),
            stage_plan_path=str(self.stage_plan),
        )
        self.run_id = result["run"]["run_id"]
        approvals.record_approval(self.conn, self.run_id, STRATEGY, self.work)

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def test_approved_queue_launches_once(self) -> None:
        docker = DockerPort(str(self.docker_path))
        first = executor.launch_approved(self.conn, docker)
        second = executor.launch_approved(self.conn, docker)
        self.assertEqual(first[0]["action"], "launched")
        self.assertEqual(second, [])
        self.assertEqual(db.run_status(self.conn, self.run_id), "running")
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM attempts WHERE run_id=?", (self.run_id,)
            ).fetchone()[0],
            1,
        )

    def test_unstarted_approved_queue_survives_boot_change(self) -> None:
        self.conn.execute(
            "UPDATE meta SET value='previous-boot' WHERE key='boot_id'"
        )
        result = executor.tick(
            self.conn,
            DockerPort(str(self.docker_path)),
            current_boot=db.current_boot_id(),
        )
        self.assertEqual(result["launched"][0]["action"], "launched")
        self.assertEqual(db.run_status(self.conn, self.run_id), "running")

    def test_exited_container_is_finalized_once(self) -> None:
        executor.launch_approved(self.conn, DockerPort(str(self.docker_path)))
        for name in ("em.gro", "em.log", "em.edr"):
            (self.work / name).write_text("artifact\n", encoding="utf-8")
        state_doc = json.loads(Path(self.state["state_path"]).read_text(encoding="utf-8"))
        state_doc["containers"][0]["State"] = "exited"
        Path(self.state["state_path"]).write_text(
            json.dumps(state_doc), encoding="utf-8"
        )
        docker = ExitDocker(str(self.docker_path))
        result = executor.tick(
            self.conn, docker, current_boot=db.current_boot_id()
        )
        self.assertEqual(result["finalized"][0]["status"], "completed")
        self.assertEqual(db.run_status(self.conn, self.run_id), "completed")
        attempt = self.conn.execute(
            "SELECT * FROM attempts WHERE run_id=?", (self.run_id,)
        ).fetchone()
        self.assertEqual(attempt["status"], "completed")
        self.assertEqual(attempt["returncode"], 0)
        self.assertTrue(Path(attempt["receipt_path"]).is_file())
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest["stages"]["em"]["status"], "completed")
        self.assertEqual(
            manifest["stages"]["em"]["artifacts"]["gro"]["path"],
            str((self.work / "em.gro").resolve()),
        )
        module = helpers.load_md_run_cli()
        nvt_plan = self.root / "nvt_stage_plan.json"
        nvt_plan.write_text(
            json.dumps(module.build_stage_plan("nvt", "nvt", "wsl2-gpu", 8, False)),
            encoding="utf-8",
        )
        (self.work / "nvt.tpr").write_text("fake tpr\n", encoding="utf-8")
        state_doc["run_result"] = {"returncode": 0, "container_id": "e" * 64}
        Path(self.state["state_path"]).write_text(
            json.dumps(state_doc), encoding="utf-8"
        )
        executor.queue_prepared_stage(self.conn, self.run_id, "nvt", nvt_plan)
        cycle = executor.tick(
            self.conn,
            DockerPort(str(self.docker_path)),
            current_boot=db.current_boot_id(),
        )
        self.assertEqual(cycle["launched"][0]["action"], "launched")
        current = self.conn.execute(
            "SELECT stage, status FROM runs WHERE run_id=?", (self.run_id,)
        ).fetchone()
        self.assertEqual((current["stage"], current["status"]), ("nvt", "running"))


if __name__ == "__main__":
    unittest.main()
