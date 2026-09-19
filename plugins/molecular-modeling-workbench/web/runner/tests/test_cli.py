# pyright: reportMissingImports=false
"""T6.7: user service lifecycle commands and read-only diagnostics."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from web.backend.config import create_token_file
from web.runner import cli, db
from web.runner.migrate import data_paths


class CommandStub:
    def __init__(self, linger: str = "no") -> None:
        self.calls: list[list[str]] = []
        self.linger = linger

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        if args[0] == "loginctl":
            return subprocess.CompletedProcess(args, 0, self.linger + "\n", "")
        if args[:3] == ["systemctl", "--user", "is-active"]:
            return subprocess.CompletedProcess(args, 0, "active\n", "")
        if args[0] == "systemctl":
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[0] == "mock-docker":
            payload = json.dumps(
                {"ID": "cid-1", "Names": "ai4s-run", "State": "running"}
            )
            return subprocess.CompletedProcess(args, 0, payload + "\n", "")
        raise AssertionError(f"unexpected command: {args}")


class ServiceLifecycleTests(unittest.TestCase):
    def test_host_restart_is_recorded_even_when_docker_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = data_paths(Path(tmp) / "data")
            conn = db.connect(paths["db"])
            db.init(conn, boot_id="boot-old")
            stamp = db.now()
            conn.execute(
                "INSERT INTO runs(run_id, request_id, project, stage, status, work_dir, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                ("r1", "q1", "p", "em", "running", tmp, stamp, stamp),
            )
            conn.close()
            unavailable = mock.Mock()
            unavailable.is_reachable.return_value = False
            unavailable.find_by_label.side_effect = AssertionError(
                "host-restart classification must not query Docker"
            )
            with (
                mock.patch.object(cli.db, "current_boot_id", return_value="boot-new"),
                mock.patch.object(cli.reconcile, "DockerPort", return_value=unavailable),
            ):
                cli.serve(paths["root"], once=True)
            conn = db.connect(paths["db"])
            self.assertEqual(db.run_status(conn, "r1"), "interrupted")
            self.assertEqual(db.recorded_boot_id(conn), "boot-new")
            conn.close()

    def test_start_stop_status_use_systemd_user_without_sudo(self) -> None:
        stub = CommandStub()
        started = cli.service_control("start", stub)
        stopped = cli.service_control("stop", stub)
        status = cli.service_status(stub)
        vectors = [" ".join(call) for call in stub.calls]
        self.assertTrue(any("systemctl --user start" in item for item in vectors))
        self.assertTrue(any("systemctl --user stop" in item for item in vectors))
        self.assertFalse(any("sudo" in item for item in vectors))
        self.assertEqual(started["action"], "start")
        self.assertEqual(stopped["action"], "stop")
        self.assertEqual(set(status["units"]), set(cli.UNITS))
        self.assertFalse(status["linger"]["enabled"])
        self.assertIn("may stop after logout", status["linger"]["warning"])

    def test_systemd_files_are_user_units_without_root_directives(self) -> None:
        deploy = Path(cli.__file__).resolve().parents[1] / "deploy"
        for unit_name in cli.UNITS:
            text = (deploy / unit_name).read_text(encoding="utf-8")
            self.assertIn("WantedBy=default.target", text)
            self.assertIn("NoNewPrivileges=true", text)
            self.assertNotIn("sudo", text)
            self.assertNotIn("User=root", text)


class DiagnoseTests(unittest.TestCase):
    def test_missing_data_directory_is_reported_without_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            report = cli.diagnose(
                missing, docker_path="mock-docker", command_runner=CommandStub()
            )
            self.assertFalse(missing.exists())
            self.assertFalse(report["database"]["exists"])
            self.assertFalse(report["token"]["exists"])

    def test_diagnose_reports_db_containers_boot_token_disk_and_linger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = data_paths(Path(tmp) / "data")
            conn = db.connect(paths["db"])
            db.init(conn, boot_id="boot-recorded")
            stamp = db.now()
            conn.execute(
                "INSERT INTO runs(run_id, request_id, project, stage, status, work_dir, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                ("r1", "q1", "p", "em", "running", tmp, stamp, stamp),
            )
            conn.close()
            create_token_file(paths["token"])
            stub = CommandStub(linger="yes")

            report = cli.diagnose(paths["root"], docker_path="mock-docker", command_runner=stub)

            self.assertEqual(report["database"]["runs_by_status"], {"running": 1})
            self.assertEqual(report["database"]["schema_version"], str(db.SCHEMA_VERSION))
            self.assertEqual(len(report["containers"]["containers"]), 1)
            self.assertIn("current", report["boot"])
            self.assertEqual(report["token"]["mode"], "0o600")
            self.assertTrue(report["token"]["secure"])
            self.assertGreater(report["disk"]["free_bytes"], 0)
            self.assertTrue(report["linger"]["enabled"])
            docker_call = next(call for call in stub.calls if call[0] == "mock-docker")
            self.assertIn(f"label={cli.RUN_LABEL}", docker_call)
            self.assertNotIn(paths["token"].read_text(encoding="utf-8").strip(), json.dumps(report))


if __name__ == "__main__":
    unittest.main()
