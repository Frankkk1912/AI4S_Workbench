import contextlib
import io
import json
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).parents[1] / "scripts" / "molecular_modeling_environment.py"
SPEC = importlib.util.spec_from_file_location("molecular_modeling_environment", SCRIPT)
assert SPEC and SPEC.loader
ENVIRONMENT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ENVIRONMENT)


class EnvironmentCliTests(unittest.TestCase):
    def test_audit_and_plan_write_structured_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run([sys.executable, str(SCRIPT), "audit", "--profile", "cpu-fallback", "--output-dir", str(root)], check=True)
            subprocess.run([sys.executable, str(SCRIPT), "plan", "--profile", "cpu-fallback", "--components", "pymol-open-source", "--output-dir", str(root)], check=True)
            report = json.loads((root / "environment_report.json").read_text())
            plan = json.loads((root / "install_plan.json").read_text())
            self.assertEqual(report["artifact_type"], "molecular_modeling_environment_report")
            self.assertEqual(plan["actions"][0]["component"], "pymol-open-source")
            self.assertIn("ChimeraX download", plan["blocked_actions"])
            self.assertIn("diagnostics", report)
            self.assertEqual(len(plan["plan_sha256"]), 64)

    def test_plan_hash_prevents_unreviewed_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run([sys.executable, str(SCRIPT), "plan", "--profile", "cpu-fallback", "--components", "gromacs", "--output-dir", str(root)], check=True)
            path = root / "install_plan.json"
            plan = json.loads(path.read_text())
            plan["actions"][0]["component"] = "vina"
            path.write_text(json.dumps(plan))
            result = subprocess.run([sys.executable, str(SCRIPT), "bootstrap", "--plan", str(path), "--output-dir", str(root)], text=True, capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Plan hash does not match", result.stderr)

    def test_gromacs_plan_uses_the_pinned_gpu_container(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = ENVIRONMENT.build_plan("wsl2-gpu", ["gromacs"], Path(tmp))
        self.assertEqual(plan["actions"], [{
            "component": "gromacs",
            "scope": "docker-user",
            "kind": "docker-pull",
            "image": "nvcr.io/nvidia/gromacs:v2023.3",
            "retry": "bounded exponential backoff for transient image pull failures",
        }])

    def test_cpu_gromacs_plan_uses_a_managed_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = ENVIRONMENT.build_plan("cpu-fallback", ["gromacs"], root)
        self.assertEqual(plan["actions"][0]["kind"], "micromamba")
        self.assertEqual(plan["actions"][0]["prefix"], str(root / "environments" / "gromacs"))
        self.assertEqual(plan["actions"][0]["smoke_test"], [str(root / "environments" / "gromacs" / "bin" / "gmx"), "--version"])

    def test_gpu_plan_installs_the_pinned_mmpbsa_analysis_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = ENVIRONMENT.build_plan("wsl2-gpu", ["gmx-mmpbsa"], root)
        action = plan["actions"][0]
        self.assertEqual(action["component"], "gmx-mmpbsa")
        self.assertEqual(action["kind"], "micromamba")
        self.assertEqual(action["prefix"], str(root / "environments" / "gmx-mmpbsa"))
        self.assertEqual(action["channels"], ["conda-forge"])
        self.assertEqual(action["command"][-2:], ["gromacs=2023.4", "gmx_MMPBSA=1.6.5"])
        self.assertEqual(action["smoke_test"], [str(root / "environments" / "gmx-mmpbsa" / "bin" / "gmx_MMPBSA"), "--version"])

    def test_vina_plan_uses_the_conda_forge_vina_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = ENVIRONMENT.build_plan("cpu-fallback", ["vina"], Path(tmp))
        self.assertEqual(plan["actions"][0]["command"][-1], "vina")

    def test_dssp_plan_uses_dssp_package_and_mkdssp_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            action = ENVIRONMENT.build_plan("cpu-fallback", ["dssp"], root)["actions"][0]
        self.assertEqual(action["command"][-1], "dssp")
        self.assertNotIn("mkdssp", action["command"])
        self.assertEqual(action["smoke_test"], [str(root / "environments" / "dssp" / "bin" / "mkdssp"), "--version"])
        self.assertEqual(ENVIRONMENT.MANAGED_TOOL_COMPONENTS["mkdssp"], "dssp")

    def test_bootstrap_rejects_a_signed_legacy_dssp_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = ENVIRONMENT.build_plan("cpu-fallback", ["dssp"], root)
            plan["actions"][0]["command"][-1] = "mkdssp"
            plan["plan_sha256"] = ENVIRONMENT.plan_hash(plan)
            plan_path = root / "legacy_install_plan.json"
            ENVIRONMENT.write_json(plan_path, plan)
            with self.assertRaisesRegex(ENVIRONMENT.EnvironmentError, "Legacy DSSP plan"):
                ENVIRONMENT.bootstrap(plan_path, root)

    def test_acpype_plan_uses_a_dedicated_ambertools_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = ENVIRONMENT.build_plan("wsl2-gpu", ["acpype"], root)
        action = plan["actions"][0]
        self.assertEqual(action["component"], "acpype")
        self.assertEqual(action["prefix"], str(root / "environments" / "acpype"))
        self.assertEqual(action["command"][-2:], ["acpype", "ambertools"])
        self.assertEqual(action["smoke_test"], [str(root / "environments" / "acpype" / "bin" / "acpype"), "--version"])

    def test_plan_normalizes_managed_prefixes_to_absolute_paths(self):
        plan = ENVIRONMENT.build_plan("cpu-fallback", ["vina"], Path("relative-environment"))
        self.assertTrue(Path(plan["actions"][0]["prefix"]).is_absolute())
        self.assertTrue(Path(plan["actions"][0]["smoke_test"][0]).is_absolute())

    def test_bootstrap_uses_mamba_when_micromamba_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = ENVIRONMENT.build_plan("cpu-fallback", ["vina"], root)
            plan_path = root / "install_plan.json"
            ENVIRONMENT.write_json(plan_path, plan)
            completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="installed", stderr="")
            with mock.patch.object(ENVIRONMENT.shutil, "which", side_effect=lambda name: {"micromamba": None, "mamba": "/usr/bin/mamba", "conda": None}.get(name)), mock.patch.object(ENVIRONMENT.subprocess, "run", return_value=completed) as run:
                receipt = ENVIRONMENT.bootstrap(plan_path, root)
        self.assertEqual(receipt["actions"][0]["status"], "installed")
        self.assertEqual(run.call_args_list[0].args[0][0], "/usr/bin/mamba")

    def test_bootstrap_action_failure_writes_receipt_and_cli_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "install_plan.json"
            ENVIRONMENT.write_json(plan_path, ENVIRONMENT.build_plan("cpu-fallback", ["vina"], root))
            failed = subprocess.CompletedProcess(args=[], returncode=7, stdout="solver output", stderr="package missing")
            stdout = io.StringIO()
            stderr = io.StringIO()
            argv = [str(SCRIPT), "bootstrap", "--plan", str(plan_path), "--output-dir", str(root)]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(ENVIRONMENT.shutil, "which", side_effect=lambda name: "/usr/bin/micromamba" if name == "micromamba" else None), mock.patch.object(ENVIRONMENT.subprocess, "run", return_value=failed), mock.patch.object(ENVIRONMENT.time, "sleep"), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
                ENVIRONMENT.main()
            receipt = json.loads((root / "environment_receipt.json").read_text())
        self.assertEqual(raised.exception.code, 1)
        self.assertNotIn("Success", stdout.getvalue())
        self.assertIn("Receipt written", stderr.getvalue())
        action = receipt["actions"][0]
        self.assertEqual(action["status"], "failed")
        self.assertEqual(action["stdout"], "solver output")
        self.assertEqual(action["stderr"], "package missing")
        self.assertEqual(len(action["attempts"]), 3)

    def test_bootstrap_smoke_failure_writes_receipt_and_cli_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "install_plan.json"
            ENVIRONMENT.write_json(plan_path, ENVIRONMENT.build_plan("cpu-fallback", ["vina"], root))
            installed = subprocess.CompletedProcess(args=[], returncode=0, stdout="installed", stderr="")
            smoke_failed = subprocess.CompletedProcess(args=[], returncode=9, stdout="", stderr="cannot start")
            argv = [str(SCRIPT), "bootstrap", "--plan", str(plan_path), "--output-dir", str(root)]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(ENVIRONMENT.shutil, "which", side_effect=lambda name: "/usr/bin/micromamba" if name == "micromamba" else None), mock.patch.object(ENVIRONMENT.subprocess, "run", side_effect=[installed, smoke_failed]), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                ENVIRONMENT.main()
            receipt = json.loads((root / "environment_receipt.json").read_text())
        self.assertEqual(raised.exception.code, 1)
        action = receipt["actions"][0]
        self.assertEqual(action["status"], "failed")
        self.assertEqual(action["failure_stage"], "smoke_test")
        self.assertEqual(action["smoke_test"]["returncode"], 9)
        self.assertEqual(action["smoke_test"]["stderr"], "cannot start")

    def test_blocked_bootstrap_writes_receipt_and_cli_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path = root / "install_plan.json"
            ENVIRONMENT.write_json(plan_path, ENVIRONMENT.build_plan("cpu-fallback", ["vina"], root))
            argv = [str(SCRIPT), "bootstrap", "--plan", str(plan_path), "--output-dir", str(root)]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(ENVIRONMENT.shutil, "which", return_value=None), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                ENVIRONMENT.main()
            receipt = json.loads((root / "environment_receipt.json").read_text())
        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(receipt["actions"][0]["status"], "blocked")

    def test_audit_discovers_acpype_in_its_managed_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acpype = root / "environments" / "acpype" / "bin" / "acpype"
            acpype.parent.mkdir(parents=True)
            acpype.write_text("#!/bin/sh\n")
            acpype.chmod(0o755)
            def fake_version(command, executable=None):
                return {"command": command, "path": executable, "available": bool(executable)}
            with mock.patch.object(ENVIRONMENT.shutil, "which", return_value=None), mock.patch.object(ENVIRONMENT, "command_version", side_effect=fake_version), mock.patch.object(ENVIRONMENT, "run_probe", return_value={"returncode": 1, "stdout": "", "stderr": ""}):
                report = ENVIRONMENT.audit("wsl2-gpu", root)
        self.assertEqual(report["tools"]["acpype"]["path"], str(acpype.resolve()))
        self.assertTrue(report["tools"]["acpype"]["available"])

    def test_audit_discovers_vina_in_its_managed_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vina = root / "environments" / "vina" / "bin" / "vina"
            vina.parent.mkdir(parents=True)
            vina.write_text("#!/bin/sh\n")
            vina.chmod(0o755)
            def fake_version(command, executable=None):
                return {"command": command, "path": executable, "available": bool(executable)}
            with mock.patch.object(ENVIRONMENT.shutil, "which", return_value=None), mock.patch.object(ENVIRONMENT, "command_version", side_effect=fake_version), mock.patch.object(ENVIRONMENT, "run_probe", return_value={"returncode": 1, "stdout": "", "stderr": ""}):
                report = ENVIRONMENT.audit("cpu-fallback", root)
        self.assertEqual(report["tools"]["vina"]["path"], str(vina.resolve()))
        self.assertTrue(report["tools"]["vina"]["available"])

    def test_audit_discovers_mmpbsa_gromacs_and_reports_trajectory_capability(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gmx = root / "environments" / "gmx-mmpbsa" / "bin" / "gmx"
            gmx.parent.mkdir(parents=True)
            gmx.write_text("#!/bin/sh\necho 'GROMACS test'\n")
            gmx.chmod(0o755)
            mmpbsa = gmx.parent / "gmx_MMPBSA"
            mmpbsa.write_text("#!/bin/sh\necho 'gmx_MMPBSA test'\n")
            mmpbsa.chmod(0o755)
            def fake_version(command, executable=None):
                return {"command": command, "path": executable, "available": bool(executable)}
            with mock.patch.object(ENVIRONMENT.shutil, "which", return_value=None), mock.patch.object(ENVIRONMENT, "command_version", side_effect=fake_version), mock.patch.object(ENVIRONMENT, "run_probe", return_value={"returncode": 1, "stdout": "", "stderr": ""}):
                report = ENVIRONMENT.audit("wsl2-gpu", root)
        self.assertEqual(report["tools"]["gmx"]["path"], str(gmx.resolve()))
        self.assertTrue(report["trajectory_analysis"]["gromacs"]["available"])
        self.assertEqual(report["trajectory_analysis"]["gromacs"]["path"], str(gmx.resolve()))
        self.assertEqual(report["trajectory_analysis"]["environment_component"], "gmx-mmpbsa")

    def test_audit_rejects_an_unpaired_gmx_for_mmpbsa_trajectory_analysis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            gmx = root / "environments" / "gmx-mmpbsa" / "bin" / "gmx"
            gmx.parent.mkdir(parents=True)
            gmx.write_text("#!/bin/sh\necho 'GROMACS test'\n")
            gmx.chmod(0o755)
            with mock.patch.object(ENVIRONMENT.shutil, "which", return_value=None), mock.patch.object(ENVIRONMENT, "run_probe", return_value={"returncode": 1, "stdout": "", "stderr": ""}):
                report = ENVIRONMENT.audit("wsl2-gpu", root)
        self.assertFalse(report["trajectory_analysis"]["ready"])
        self.assertIsNone(report["trajectory_analysis"]["gromacs"]["path"])

    def test_missing_vina_is_installed_to_a_prefix_then_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = ENVIRONMENT.build_plan("cpu-fallback", ["vina"], root)
            plan_path = root / "install_plan.json"
            ENVIRONMENT.write_json(plan_path, plan)
            completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="installed", stderr="")
            with mock.patch.object(ENVIRONMENT.shutil, "which", side_effect=lambda name: {"micromamba": "/usr/bin/micromamba", "mamba": None, "conda": None}.get(name)), mock.patch.object(ENVIRONMENT.subprocess, "run", return_value=completed):
                bootstrap = ENVIRONMENT.bootstrap(plan_path, root)
            self.assertEqual(bootstrap["actions"][0]["status"], "installed")
            vina = root / "environments" / "vina" / "bin" / "vina"
            vina.parent.mkdir(parents=True)
            vina.write_text("#!/bin/sh\n")
            vina.chmod(0o755)
            with mock.patch.object(ENVIRONMENT.shutil, "which", return_value=None), mock.patch.object(ENVIRONMENT, "run_probe", return_value={"returncode": 1, "stdout": "", "stderr": ""}):
                report = ENVIRONMENT.audit("cpu-fallback", root)
        self.assertTrue(report["tools"]["vina"]["available"])
        self.assertEqual(report["tools"]["vina"]["path"], str(vina.resolve()))

    def test_gpu_readiness_requires_the_pinned_gromacs_image(self):
        report = {
            "tools": {"uv": {"available": True}},
            "host": {"wsl": True},
            "gpu": {"returncode": 0},
            "diagnostics": {"gpu": {"status": "available"}, "docker": {"status": "available"}},
            "gromacs_container": {"available": False},
        }
        ready, warnings = ENVIRONMENT.readiness(report, "wsl2-gpu")
        self.assertFalse(ready)
        self.assertTrue(any("Pinned GROMACS" in warning for warning in warnings))

    def test_cpu_readiness_requires_gromacs(self):
        report = {"tools": {"uv": {"available": True}, "gmx": {"available": False}}, "host": {"wsl": False}, "diagnostics": {}}
        ready, warnings = ENVIRONMENT.readiness(report, "cpu-fallback")
        self.assertFalse(ready)
        self.assertTrue(any("GROMACS" in warning for warning in warnings))

    def test_host_recheck_writes_read_only_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run([sys.executable, str(SCRIPT), "host-recheck", "--profile", "linux-gpu", "--output-dir", str(root)], check=True)
            receipt = json.loads((root / "host_recheck_receipt.json").read_text())
            self.assertTrue(receipt["read_only"])
            self.assertEqual(receipt["artifact_type"], "molecular_modeling_host_recheck_receipt")

    def test_isolated_wsl_context_is_not_reported_as_host_failure(self):
        report = {
            "host": {"wsl": True},
            "tools": {"docker": {"available": True}, "gmx": {"available": False}},
            "gpu": {"returncode": 255, "stdout": "Failed to initialize NVML: GPU access blocked by the operating system"},
            "container": {"returncode": 1, "stderr": "permission denied while trying to connect to the docker API"},
            "execution_context": {"can_write_home": False, "wsl_gpu_device": {"exists": False}, "docker_socket": {"exists": True, "gid": 65534}},
        }
        diagnostics = ENVIRONMENT.classify_diagnostics(report)
        self.assertEqual(diagnostics["gpu"]["status"], "execution_isolation")
        self.assertEqual(diagnostics["docker"]["status"], "execution_isolation")
        self.assertTrue(diagnostics["host_recheck"]["recommended"])


class CondaDetectionTests(unittest.TestCase):
    def test_audit_reports_conda_tools_and_active_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run([sys.executable, str(SCRIPT), "audit", "--profile", "cpu-fallback", "--output-dir", str(root)], check=True)
            report = json.loads((root / "environment_report.json").read_text())
            for executable in ("conda", "mamba", "micromamba"):
                self.assertIn(executable, report["tools"])
                self.assertIn("available", report["tools"][executable])
            conda = report["conda"]
            for key in ("active_environment", "prefix", "conda_exe", "mamba_root_prefix", "python_inside_active_env", "policy"):
                self.assertIn(key, conda)

    def test_conda_context_reads_active_environment(self):
        env = {
            "CONDA_PREFIX": sys.prefix,
            "CONDA_DEFAULT_ENV": "workbench",
            "CONDA_EXE": "/opt/conda/bin/conda",
            "MAMBA_ROOT_PREFIX": "/home/user/micromamba",
        }
        with mock.patch.dict("os.environ", env, clear=True):
            context = ENVIRONMENT.conda_context()
        self.assertEqual(context["active_environment"], "workbench")
        self.assertEqual(context["prefix"], sys.prefix)
        self.assertEqual(context["conda_exe"], "/opt/conda/bin/conda")
        self.assertEqual(context["mamba_root_prefix"], "/home/user/micromamba")
        self.assertTrue(context["python_inside_active_env"])

    def test_conda_context_without_active_environment(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            context = ENVIRONMENT.conda_context()
        self.assertIsNone(context["active_environment"])
        self.assertIsNone(context["prefix"])
        self.assertFalse(context["python_inside_active_env"])


class OnboardTests(unittest.TestCase):
    def test_onboard_writes_json_and_markdown_checklist(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run([sys.executable, str(SCRIPT), "onboard", "--profile", "cpu-fallback", "--output-dir", str(root)], check=True)
            checklist = json.loads((root / "onboarding_checklist.json").read_text())
            markdown = (root / "onboarding_checklist.md").read_text()
            self.assertEqual(checklist["artifact_type"], "molecular_modeling_onboarding_checklist")
            summary = checklist["summary"]
            self.assertEqual(summary["total"], len(checklist["steps"]))
            self.assertEqual(summary["total"], summary["done"] + summary["action_needed"] + summary["handoff"])
            self.assertIn("# Onboarding checklist", markdown)

    def test_onboard_covers_components_and_handoffs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run([sys.executable, str(SCRIPT), "onboard", "--profile", "cpu-fallback", "--output-dir", str(root)], check=True)
            checklist = json.loads((root / "onboarding_checklist.json").read_text())
            statuses = {step["status"] for step in checklist["steps"]}
            self.assertTrue(statuses <= {"done", "action-needed", "handoff"})
            titles = " ".join(step["title"] for step in checklist["steps"])
            for component in sorted(ENVIRONMENT.ALLOWED_COMPONENTS):
                self.assertIn(component, titles)
            missing = [step for step in checklist["steps"] if step["status"] == "action-needed"]
            for step in missing:
                self.assertIn("command", step)
            chimerax = next(step for step in checklist["steps"] if "ChimeraX" in step["title"])
            self.assertIn(chimerax["status"], {"done", "handoff"})

    def test_onboard_final_step_is_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run([sys.executable, str(SCRIPT), "onboard", "--profile", "cpu-fallback", "--output-dir", str(root)], check=True)
            checklist = json.loads((root / "onboarding_checklist.json").read_text())
            final = checklist["steps"][-1]
            self.assertIn("verify", final["command"])


if __name__ == "__main__":
    unittest.main()
