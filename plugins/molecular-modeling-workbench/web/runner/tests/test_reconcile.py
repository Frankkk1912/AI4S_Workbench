# pyright: reportMissingImports=false
"""T1.2/T1.3: detached identity reconciliation and boot-identity handling.

Uses the shared mock docker executable; never requires a real Docker daemon or
GPU. Verifies full ownership matching (digest/work_dir/command hash/labels),
multiple-match and mismatch fail-closed, boot change -> interrupted, and that a
verified exited container is never reported as completed here.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from web.runner import db, submission
from web.runner.reconcile import DockerPort, reconcile
from web.runner.tests import helpers

DIGEST = "nvcr.io/nvidia/gromacs@sha256:" + "a" * 64


class RealFormatDocker(DockerPort):
    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        if args[0] == "ps":
            row = {
                "ID": "c" * 12,
                "Names": "container-name",
                "Labels": "ai4s.workbench.run_id=run-1",
                "State": "running",
            }
            return subprocess.CompletedProcess(args, 0, json.dumps(row) + "\n", "")
        if "{{.Config.Image}}" in args:
            return subprocess.CompletedProcess(args, 0, DIGEST + "\n", "")
        if "{{json .Config.Labels}}" in args:
            labels = {"ai4s.workbench.run_id": "run-1"}
            return subprocess.CompletedProcess(args, 0, json.dumps(labels) + "\n", "")
        return subprocess.CompletedProcess(args, 1, "", "unsupported")


def container_record(cid: str, name: str, labels: dict, state: str = "running") -> dict:
    return {
        "ID": cid,
        "Names": name,
        "Image": DIGEST,
        "Labels": labels,
        "State": state,
    }


class ReconcileTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.conn = helpers.make_db(self.root / "runner.db", boot_id="boot-A")
        self.mock = helpers.load_mock_docker()
        self.docker_path, self.env, self.state = self.mock.install_mock_docker(
            self.root
        )

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    def _submit_and_intent(self, run_id_hint: str, work_dir: str) -> str:
        run = submission.submit_run(self.conn, run_id_hint, "project", "em", work_dir)[
            "run"
        ]
        submission.allocate_attempt(self.conn, run["run_id"], "em", work_dir)
        return run["run_id"]

    def _record_launched_attempt(
        self, run_id: str, attempt_id: int, labels: dict
    ) -> None:
        # Two-phase registration: the container row already exists (second phase).
        self.conn.execute(
            "UPDATE attempts SET status='launched', container_at=?, image_digest=?, "
            "work_dir_hash=?, command_hash=?, ownership_labels=?, cid_file=? "
            "WHERE run_id=? AND stage='em' AND attempt_id=?",
            (
                db.now(),
                DIGEST,
                labels["ai4s.workbench.work_dir_hash"],
                labels["ai4s.workbench.command_hash"],
                json.dumps(labels, sort_keys=True),
                "/work/.runner/cid",
                run_id,
                attempt_id,
            ),
        )

    def _reconcile(self, current_boot: str | None = "boot-A") -> list[dict]:
        return reconcile(
            self.conn, DockerPort(str(self.docker_path)), current_boot=current_boot
        )

    def _labels(self, run_id: str, work_dir: str, command: list) -> dict:
        module = helpers.load_md_run_cli()
        return {
            "ai4s.workbench.run_id": run_id,
            "ai4s.workbench.stage": "em",
            "ai4s.workbench.attempt": "1",
            "ai4s.workbench.image_digest": DIGEST,
            "ai4s.workbench.work_dir_hash": module.command_hash([work_dir]),
            "ai4s.workbench.command_hash": module.command_hash(command),
            "ai4s.workbench.owner": "1000:1000",
        }

    def test_real_docker_label_string_is_resolved_via_inspect(self) -> None:
        records = RealFormatDocker().find_by_label(
            "ai4s.workbench.run_id", "run-1"
        )
        self.assertEqual(records[0]["labels"], {"ai4s.workbench.run_id": "run-1"})
        self.assertEqual(records[0]["image_digest"], DIGEST)

    def test_boot_change_interrupts_active_run(self) -> None:
        run_id = self._submit_and_intent("req-1", "/work")
        self.conn.execute("UPDATE runs SET status='running' WHERE run_id=?", (run_id,))
        summary = self._reconcile(current_boot="boot-B")
        self.assertEqual(db.run_status(self.conn, run_id), "interrupted")
        self.assertEqual(summary[0]["action"], "interrupted")

    def test_verified_running_container_is_adopted(self) -> None:
        run_id = self._submit_and_intent("req-1", "/work")
        self.conn.execute("UPDATE runs SET status='running' WHERE run_id=?", (run_id,))
        command = ["gmx", "mdrun", "-deffnm", "em"]
        labels = self._labels(run_id, "/work", command)
        self._record_launched_attempt(run_id, 1, labels)
        self.mock.inject_containers(
            self.state,
            [container_record("c" * 64, f"ai4s-md-{run_id}-em-1", labels, "running")],
        )
        summary = self._reconcile()
        self.assertEqual(db.run_status(self.conn, run_id), "running")
        self.assertTrue(any(s["action"] == "adopted" for s in summary))

    def test_exited_container_is_attention_not_completed(self) -> None:
        run_id = self._submit_and_intent("req-1", "/work")
        self.conn.execute("UPDATE runs SET status='running' WHERE run_id=?", (run_id,))
        command = ["gmx", "mdrun", "-deffnm", "em"]
        labels = self._labels(run_id, "/work", command)
        self._record_launched_attempt(run_id, 1, labels)
        self.mock.inject_containers(
            self.state,
            [container_record("c" * 64, f"ai4s-md-{run_id}-em-1", labels, "exited")],
        )
        summary = self._reconcile()
        self.assertEqual(db.run_status(self.conn, run_id), "attention")
        self.assertTrue(any(s["action"] == "attention" for s in summary))

    def test_identity_mismatch_fails_closed(self) -> None:
        run_id = self._submit_and_intent("req-1", "/work")
        self.conn.execute("UPDATE runs SET status='running' WHERE run_id=?", (run_id,))
        command = ["gmx", "mdrun", "-deffnm", "em"]
        labels = self._labels(run_id, "/work", command)
        self._record_launched_attempt(run_id, 1, labels)
        bad_labels = dict(labels)
        bad_labels["ai4s.workbench.command_hash"] = "0" * 64
        self.mock.inject_containers(
            self.state,
            [
                container_record(
                    "c" * 64, f"ai4s-md-{run_id}-em-1", bad_labels, "running"
                )
            ],
        )
        summary = self._reconcile()
        self.assertEqual(db.run_status(self.conn, run_id), "attention")
        self.assertTrue(any("mismatch" in s["reason"] for s in summary))

    def test_multiple_matching_containers_fails_closed(self) -> None:
        run_id = self._submit_and_intent("req-1", "/work")
        self.conn.execute("UPDATE runs SET status='running' WHERE run_id=?", (run_id,))
        command = ["gmx", "mdrun", "-deffnm", "em"]
        labels = self._labels(run_id, "/work", command)
        self._record_launched_attempt(run_id, 1, labels)
        name = f"ai4s-md-{run_id}-em-1"
        self.mock.inject_containers(
            self.state,
            [
                container_record("c" * 64, name, labels, "running"),
                container_record("d" * 64, name, labels, "running"),
            ],
        )
        summary = self._reconcile()
        self.assertEqual(db.run_status(self.conn, run_id), "attention")
        self.assertTrue(any("multiple" in s["reason"] for s in summary))

    def test_recorded_container_vanished_is_unknown(self) -> None:
        run_id = self._submit_and_intent("req-1", "/work")
        self.conn.execute("UPDATE runs SET status='running' WHERE run_id=?", (run_id,))
        command = ["gmx", "mdrun", "-deffnm", "em"]
        labels = self._labels(run_id, "/work", command)
        self._record_launched_attempt(run_id, 1, labels)
        # no containers at all -> the recorded container is gone
        summary = self._reconcile()
        self.assertEqual(db.run_status(self.conn, run_id), "unknown")
        self.assertTrue(any(s["action"] == "unknown" for s in summary))


if __name__ == "__main__":
    unittest.main()
