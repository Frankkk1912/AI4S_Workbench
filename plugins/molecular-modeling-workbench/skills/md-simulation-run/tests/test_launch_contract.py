import datetime as dt
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "md_run_cli.py"
SPEC = importlib.util.spec_from_file_location("md_run_cli", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

MOCK_SPEC = importlib.util.spec_from_file_location(
    "mock_docker", Path(__file__).parent / "mock_docker.py"
)
assert MOCK_SPEC.loader is not None
mock_docker = importlib.util.module_from_spec(MOCK_SPEC)
MOCK_SPEC.loader.exec_module(mock_docker)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LaunchContractTests(unittest.TestCase):
    def run_cli(self, *args, check=True, env=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, args)],
            text=True,
            capture_output=True,
            check=check,
            env=env,
        )

    def fixture(self, root: Path, env: dict) -> dict:
        work = root / "work"
        work.mkdir()
        docker, env, state = mock_docker.install_mock_docker(root)
        receipt = root / "environment_receipt.json"
        image_digest = "nvcr.io/nvidia/gromacs@sha256:" + "a" * 64
        receipt.write_text(
            json.dumps(
                {
                    "schema_version": "1.1",
                    "artifact_type": "molecular_modeling_environment_receipt",
                    "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "profile": "wsl2-gpu",
                    "ready": True,
                    "report": {
                        "tools": {"docker": {"available": True, "path": str(docker)}},
                        "gromacs_container": {
                            "available": True,
                            "digest": image_digest,
                        },
                    },
                }
            )
        )
        stage_plan = root / "em_stage_plan.json"
        self.run_cli(
            "plan-stage",
            "--stage",
            "em",
            "--deffnm",
            "em",
            "--profile",
            "wsl2-gpu",
            "--threads",
            "8",
            "--output",
            stage_plan,
        )
        (work / "em.tpr").write_text("fake tpr\n")
        manifest = root / "md_run_manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "artifact_type": "md_run_manifest",
                    "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "work_dir": str(work.resolve()),
                    "duration_plan": {"profile": "wsl2-gpu"},
                    "environment_receipt": {
                        "path": str(receipt.resolve()),
                        "ready": True,
                    },
                    "stages": {},
                }
            )
        )
        return {
            "work": work,
            "receipt": receipt,
            "image_digest": image_digest,
            "stage_plan": stage_plan,
            "manifest": manifest,
            "env": env,
            "state": state,
        }

    def plan_launch(self, fixture, root: Path, attempt_id=1, run_id="run1"):
        output = root / f"launch_plan_{run_id}_{attempt_id}.json"
        result = self.run_cli(
            "plan-launch",
            "--manifest",
            fixture["manifest"],
            "--stage-plan",
            fixture["stage_plan"],
            "--stage",
            "em",
            "--run-id",
            run_id,
            "--attempt-id",
            attempt_id,
            "--uid",
            1000,
            "--gid",
            1000,
            "--output",
            output,
            check=False,
            env=fixture["env"],
        )
        return result, output

    def launch(self, fixture, root: Path, plan: Path, detach=True):
        output = root / "launch_receipt.json"
        args = ["launch"]
        if detach:
            args.append("-d")
        args.extend(
            [
                "--plan",
                str(plan),
                "--manifest",
                str(fixture["manifest"]),
                "--stage-plan",
                str(fixture["stage_plan"]),
                "--output",
                output,
            ]
        )
        return self.run_cli(*args, check=False, env=fixture["env"]), output

    def test_plan_launch_binds_attempt_identity_labels_and_detached_vector(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self.fixture(root, {})
            result, output = self.plan_launch(fixture, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(output.read_text())
            self.assertEqual(plan["artifact_type"], "md_launch_plan")
            self.assertTrue(plan["detach"])
            identity = plan["identity"]
            self.assertEqual(identity["container_name"], "ai4s-md-run1-em-1")
            self.assertIn("ai4s-md-run1-em-1.cid", identity["cid_file"])
            self.assertEqual(identity["owner"], "1000:1000")
            labels = identity["labels"]
            for key, value in {
                "ai4s.workbench.run_id": "run1",
                "ai4s.workbench.stage": "em",
                "ai4s.workbench.attempt": "1",
                "ai4s.workbench.image_digest": fixture["image_digest"],
                "ai4s.workbench.owner": "1000:1000",
            }.items():
                self.assertEqual(labels.get(key), value)
            self.assertEqual(
                identity["work_dir_hash"],
                hashlib.sha256(str(fixture["work"].resolve()).encode()).hexdigest(),
            )
            self.assertEqual(
                identity["command_hash"], MODULE.command_hash(plan["gromacs_command"])
            )
            vector = plan["docker_command"]
            self.assertEqual(vector[1:3], ["run", "-d"])
            self.assertNotIn("--rm", vector)
            for fragment in (
                "--user",
                "1000:1000",
                "--name",
                "ai4s-md-run1-em-1",
                "--cidfile",
                "--gpus",
                "all",
            ):
                self.assertIn(fragment, vector)
            self.assertTrue(
                any(
                    fragment == "--label"
                    and vector[i + 1].startswith("ai4s.workbench.")
                    for i, fragment in enumerate(vector)
                )
            )
            self.assertEqual(len(plan["plan_sha256"]), 64)

    def test_launch_requires_explicit_detach_and_rejects_unsafe_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self.fixture(root, {})
            result, plan = self.plan_launch(fixture, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            missing_detach, _ = self.launch(fixture, root, plan, detach=False)
            self.assertNotEqual(missing_detach.returncode, 0)
            self.assertIn("detach", missing_detach.stderr)
            unsafe_run_id = root / "bad_plan.json"
            bad = self.run_cli(
                "plan-launch",
                "--manifest",
                fixture["manifest"],
                "--stage-plan",
                fixture["stage_plan"],
                "--stage",
                "em",
                "--run-id",
                "../escape",
                "--attempt-id",
                1,
                "--uid",
                1000,
                "--gid",
                1000,
                "--output",
                unsafe_run_id,
                check=False,
                env=fixture["env"],
            )
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("run-id", bad.stderr)

    def test_launch_runs_detached_container_and_records_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self.fixture(root, {})
            result, plan = self.plan_launch(fixture, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            result, output = self.launch(fixture, root, plan)
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(output.read_text())
            self.assertEqual(receipt["artifact_type"], "md_launch_receipt")
            self.assertEqual(receipt["status"], "launched")
            self.assertRegex(receipt["container_id"], r"^[0-9a-f]{12,64}$")
            self.assertEqual(receipt["container_name"], "ai4s-md-run1-em-1")
            self.assertNotIn("--rm", receipt["docker_command"])
            self.assertIn("-d", receipt["docker_command"])
            calls = mock_docker.recorded_calls(fixture["state"]["calls_path"])
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0:2], ["run", "-d"])
            self.assertNotIn("--rm", calls[0])
            cidfile = Path(receipt["cid_file"])
            self.assertTrue(cidfile.is_file())
            self.assertEqual(cidfile.read_text().strip(), receipt["container_id"])

    def test_launch_rejects_tampered_plan_and_changed_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self.fixture(root, {})
            result, plan_path = self.plan_launch(fixture, root)
            self.assertEqual(result.returncode, 0, result.stderr)
            plan = json.loads(plan_path.read_text())
            plan["docker_command"].extend(["--privileged"])
            plan["plan_sha256"] = MODULE.plan_hash(plan)
            tampered = root / "tampered_plan.json"
            tampered.write_text(json.dumps(plan))
            result, _ = self.launch(fixture, root, tampered)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("structured argument vector", result.stderr)
            plan = json.loads(plan_path.read_text())
            plan["plan_sha256"] = "0" * 64
            broken_hash = root / "broken_hash_plan.json"
            broken_hash.write_text(json.dumps(plan))
            result, _ = self.launch(fixture, root, broken_hash)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("hash", result.stderr)
            manifest = json.loads(fixture["manifest"].read_text())
            manifest["stages"]["em"] = {"status": "completed"}
            fixture["manifest"].write_text(json.dumps(manifest))
            result, _ = self.launch(fixture, root, plan_path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not match the launch plan", result.stderr)
            completed_plan = root / "completed_stage_plan.json"
            result = self.run_cli(
                "plan-launch",
                "--manifest",
                fixture["manifest"],
                "--stage-plan",
                fixture["stage_plan"],
                "--stage",
                "em",
                "--run-id",
                "run1",
                "--attempt-id",
                3,
                "--uid",
                1000,
                "--gid",
                1000,
                "--output",
                completed_plan,
                check=False,
                env=fixture["env"],
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("already completed", result.stderr)

    def test_attempt_ids_derive_distinct_container_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self.fixture(root, {})
            _, first = self.plan_launch(fixture, root, attempt_id=1)
            _, second = self.plan_launch(fixture, root, attempt_id=2)
            plan_one, plan_two = (
                json.loads(first.read_text()),
                json.loads(second.read_text()),
            )
            self.assertNotEqual(
                plan_one["identity"]["container_name"],
                plan_two["identity"]["container_name"],
            )
            self.assertNotEqual(
                plan_one["identity"]["cid_file"], plan_two["identity"]["cid_file"]
            )
            self.assertEqual(
                plan_two["identity"]["container_name"], "ai4s-md-run1-em-2"
            )

    def test_foreground_run_docker_command_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = self.fixture(root, {})
            receipt = json.loads(fixture["receipt"].read_text())
            vector = MODULE.gromacs_command(
                receipt,
                fixture["work"],
                [
                    "gmx",
                    "mdrun",
                    "-deffnm",
                    "em",
                    "-ntmpi",
                    "1",
                    "-ntomp",
                    "8",
                    "-nb",
                    "gpu",
                ],
            )
            self.assertIn("--rm", vector)
            self.assertNotIn("-d", vector)
            self.assertNotIn("--user", vector)
            self.assertNotIn("--name", vector)
            self.assertNotIn("--label", vector)


if __name__ == "__main__":
    unittest.main()
