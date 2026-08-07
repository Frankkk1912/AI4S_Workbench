import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import importlib.util
import datetime as dt
from types import SimpleNamespace

SCRIPT = Path(__file__).parents[1] / "scripts" / "md_run_cli.py"
# The test suite is run both from the private source tree and from the assembled
# plugin.  In each layout, ``parents[2]`` is the directory that contains the
# sibling skill directories.
SKILLS_ROOT = Path(__file__).parents[2]
HANDOFF_SCRIPT = SKILLS_ROOT / "docking-to-md-handoff" / "scripts" / "docking_to_md_handoff.py"
SPEC = importlib.util.spec_from_file_location("md_run_cli", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class DurationProgressTests(unittest.TestCase):
    def run_cli(self, *args, check=True):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], text=True, capture_output=True, check=check)

    def test_cpu_long_duration_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "duration.json"
            failed = self.run_cli("plan-duration", "--profile", "cpu-fallback", "--system-mass-kda", 80, "--atom-count", 120000, "--duration-ns", 20, "--output", output, check=False)
            self.assertNotEqual(failed.returncode, 0)
            self.run_cli("plan-duration", "--profile", "cpu-fallback", "--system-mass-kda", 80, "--atom-count", 120000, "--duration-ns", 20, "--confirm-long-cpu", "--output", output)
            plan = json.loads(output.read_text())
            self.assertTrue(plan["confirmation"]["recorded"])

    def test_gpu_default_and_progress_bar_are_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); plan = root / "duration.json"; manifest = root / "manifest.json"; log = root / "md_prod.log"; progress = root / "md_progress.json"
            self.run_cli("plan-duration", "--profile", "wsl2-gpu", "--system-mass-kda", 80, "--atom-count", 120000, "--output", plan)
            payload = json.loads(plan.read_text())
            self.assertEqual(payload["duration_ns"], 100.0)
            self.assertEqual(payload["duration_source"], "disclosed_default_100_ns")
            manifest.write_text(json.dumps({"work_dir": str(root), "duration_plan": {"path": str(plan)}}))
            log.write_text("Step 30000000\n4.8 ns/day\nremaining wall clock time: 8 h\n")
            self.run_cli("status", "--manifest", manifest, "--log", log, "--total-steps", 50000000, "--output", progress)
            status = json.loads(progress.read_text())
            self.assertEqual(status["percent"], 60.0)
            self.assertIn("60%", status["progress_bar"])
            self.assertEqual(status["ns_per_day"], 4.8)

    def test_receipt_rejects_not_ready_or_profile_mismatch(self):
        base = {"schema_version": "1.1", "artifact_type": "molecular_modeling_environment_receipt", "created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "profile": "wsl2-gpu", "ready": True, "report": {"tools": {"gmx": {"available": False}}, "gromacs_container": {"available": True, "digest": "nvcr.io/nvidia/gromacs@sha256:" + "c" * 64}}}
        MODULE.validate_receipt(base, "wsl2-gpu")
        base["ready"] = False
        with self.assertRaisesRegex(MODULE.MDError, "not ready"):
            MODULE.validate_receipt(base, "wsl2-gpu")
        base["ready"] = True
        with self.assertRaisesRegex(MODULE.MDError, "profile"):
            MODULE.validate_receipt(base, "linux-gpu")
        base["profile"] = "wsl2-gpu"; base["created_at"] = "2000-01-01T00:00:00+00:00"
        with self.assertRaisesRegex(MODULE.MDError, "older than seven days"):
            MODULE.validate_receipt(base, "wsl2-gpu")

    def test_gpu_receipt_accepts_verified_container_without_host_gmx(self):
        receipt = {
            "schema_version": "1.1", "artifact_type": "molecular_modeling_environment_receipt",
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "profile": "wsl2-gpu", "ready": True,
            "report": {"tools": {"gmx": {"available": False}}, "gromacs_container": {"available": True, "digest": "nvcr.io/nvidia/gromacs@sha256:" + "b" * 64}},
        }
        MODULE.validate_receipt(receipt, "wsl2-gpu")

    def test_stage_plan_is_hashed_and_contains_no_shell_text(self):
        plan = MODULE.build_stage_plan("em", "em", "wsl2-gpu", 8, False)
        self.assertEqual(plan["artifact_type"], "md_stage_plan")
        self.assertEqual(plan["command"], ["gmx", "mdrun", "-deffnm", "em", "-ntmpi", "1", "-ntomp", "8", "-nb", "gpu"])
        self.assertNotIn("em.cpt", plan["expected_artifacts"])
        self.assertIn("em.cpt", MODULE.build_stage_plan("em", "em", "wsl2-gpu", 8, True)["expected_artifacts"])
        self.assertEqual(len(plan["plan_sha256"]), 64)
        self.assertNotIn("bash", " ".join(plan["command"]))

    def test_gpu_md_command_uses_receipt_bound_container_digest(self):
        plan = MODULE.build_stage_plan("em", "em", "wsl2-gpu", 8, False)
        with tempfile.TemporaryDirectory() as tmp:
            docker = Path(tmp) / "docker"
            docker.write_text("#!/bin/sh\n")
            docker.chmod(0o755)
            receipt = {
                "schema_version": "1.1",
                "artifact_type": "molecular_modeling_environment_receipt",
                "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "profile": "wsl2-gpu",
                "ready": True,
                "report": {
                    "tools": {"docker": {"available": True, "path": str(docker)}},
                    "gromacs_container": {
                        "available": True,
                        "image": "nvcr.io/nvidia/gromacs:v2023.3",
                        "digest": "nvcr.io/nvidia/gromacs@sha256:" + "a" * 64,
                    },
                },
            }
            command = MODULE.gromacs_command(receipt, Path("/tmp/md-work"), plan["command"])
        self.assertEqual(command[:8], [str(docker.resolve()), "run", "--rm", "--gpus", "all", "-v", "/tmp/md-work:/work", "-w"])
        self.assertEqual(command[8:11], ["/work", receipt["report"]["gromacs_container"]["digest"], "gmx"])
        self.assertEqual(command[11:], plan["command"][1:])

    def test_gpu_md_rejects_a_mutable_gromacs_tag(self):
        receipt = {"report": {"gromacs_container": {"available": True, "image": "nvcr.io/nvidia/gromacs:v2023.3", "digest": None}}}
        with self.assertRaisesRegex(MODULE.MDError, "digest"):
            MODULE.gromacs_command(receipt, Path("/tmp/md-work"), ["gmx", "mdrun"])

    def test_stage_execution_revalidates_the_saved_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stage_plan = root / "em_stage_plan.json"
            stage_plan.write_text(json.dumps(MODULE.build_stage_plan("em", "em", "wsl2-gpu", 8, False)))
            (root / "em.tpr").write_text("input")
            receipt = root / "environment_receipt.json"
            receipt.write_text(json.dumps({
                "schema_version": "1.1", "artifact_type": "molecular_modeling_environment_receipt",
                "created_at": "2000-01-01T00:00:00+00:00", "profile": "wsl2-gpu", "ready": True,
                "report": {"tools": {}, "gromacs_container": {"available": True, "digest": "nvcr.io/nvidia/gromacs@sha256:" + "e" * 64}},
            }))
            manifest = root / "md_run_manifest.json"
            manifest.write_text(json.dumps({"work_dir": str(root), "duration_plan": {"profile": "wsl2-gpu"}, "environment_receipt": {"path": str(receipt)}, "stages": {}}))
            with self.assertRaisesRegex(MODULE.MDError, "older than seven days"):
                MODULE.execute(SimpleNamespace(manifest=manifest, stage_plan=stage_plan))

    def test_nvt_rejects_missing_completed_em_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = MODULE.build_stage_plan("nvt", "nvt", "wsl2-gpu", 8, False)
            manifest = {"work_dir": str(root), "stages": {"em": {"status": "completed", "artifacts": {"gro": {"path": str(root / "em.gro"), "sha256": "0" * 64}}}}}
            with self.assertRaisesRegex(MODULE.MDError, "required artifact"):
                MODULE.validate_stage_prerequisites(manifest, plan)

    def test_mock_docking_to_md_contract_pipeline_prepares_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pose = root / "pose.pdbqt"
            pose.write_text("MODEL 1\nATOM      1 C1   LIG A   1       1.000   2.000   3.000  0.00  0.00    +0.000 C\nATOM      2 C2   LIG A   1       2.000   3.000   4.000  0.00  0.00    +0.000 C\nATOM      3 C3   LIG A   1       3.000   4.000   5.000  0.00  0.00    +0.000 C\nENDMDL\n")
            topology = root / "ligand.itp"; topology.write_text("[ atoms ]\n")
            coordinates = root / "ligand.gro"
            coordinates.write_text("ligand\n3\n    1LIG     C1    1   0.100   0.100   0.100\n    1LIG     C2    2   0.200   0.200   0.200\n    1LIG     C3    3   0.300   0.300   0.300\n   1.00000   1.00000   1.00000\n")
            receipt = root / "environment_receipt.json"
            receipt.write_text(json.dumps({"schema_version": "1.1", "artifact_type": "molecular_modeling_environment_receipt", "created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "profile": "wsl2-gpu", "ready": True, "report": {"tools": {"gmx": {"available": False}}, "gromacs_container": {"available": True, "digest": "nvcr.io/nvidia/gromacs@sha256:" + "d" * 64}}}))
            docking_manifest = root / "docking_manifest.json"; docking_manifest.write_text(json.dumps({"receptor": {"path": "receptor.pdbqt"}}))
            ranked_poses = root / "ranked_poses.json"; ranked_poses.write_text(json.dumps({"poses": [{"pose_id": "pose_001", "source_file": str(pose), "coordinate_file": {"path": str(pose), "sha256": hashlib.sha256(pose.read_bytes()).hexdigest(), "format": "pdbqt"}}]}))
            parameters = root / "ligand_parameters.json"; parameters.write_text(json.dumps({"ligand_identity": "LIG", "net_charge": 0, "force_field": "amber-gaff", "topology": str(topology), "coordinates": str(coordinates), "validation": {"status": "validated"}}))
            handoff = root / "md_handoff.json"
            subprocess.run([sys.executable, str(HANDOFF_SCRIPT), "create", "--docking-manifest", str(docking_manifest), "--ranked-poses", str(ranked_poses), "--pose-id", "pose_001", "--system-type", "protein-ligand", "--parameterization", str(parameters), "--environment-receipt", str(receipt), "--protein-force-field", "amber99sb-ildn", "--rationale", "mock contract fixture", "--output", str(handoff)], check=True)
            duration = root / "duration.json"
            self.run_cli("plan-duration", "--profile", "wsl2-gpu", "--system-mass-kda", 80, "--atom-count", 120000, "--duration-ns", 1, "--output", duration)
            manifest = root / "md_run_manifest.json"
            self.run_cli("prepare", "--handoff", handoff, "--environment-receipt", receipt, "--duration-plan", duration, "--work-dir", root / "md", "--output", manifest)
            prepared = json.loads(manifest.read_text())
            self.assertEqual(prepared["system_type"], "protein-ligand")
            self.assertEqual(prepared["duration_plan"]["profile"], "wsl2-gpu")
            self.assertTrue(prepared["environment_receipt"]["ready"])


if __name__ == "__main__":
    unittest.main()
