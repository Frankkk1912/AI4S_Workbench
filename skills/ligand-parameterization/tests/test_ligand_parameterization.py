import json
import datetime as dt
import hashlib
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).parents[1] / "scripts" / "ligand_parameterization.py"
SPEC = importlib.util.spec_from_file_location("ligand_parameterization", SCRIPT)
assert SPEC and SPEC.loader
LIGAND_PARAMETERIZATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LIGAND_PARAMETERIZATION)

LIGAND_SDF = """LIG
  test

  0  0  0  0  0  0  0  0  0  0999 V2000
M  END
$$$$
"""

LIGAND_PDB = """HETATM    1  C1  LIG A   1       0.000   0.000   0.000  1.00  0.00           C
END
"""

LIGAND_MOL2 = """@<TRIPOS>MOLECULE
LIG
 3 2 1 0 0
SMALL
@<TRIPOS>ATOM
 1 C1 0.0 0.0 0.0 C.3 1 LIG 0.0
 2 C2 1.5 0.0 0.0 C.3 1 LIG 0.0
 3 O1 2.3 0.9 0.0 O.3 1 LIG -0.4
@<TRIPOS>BOND
 1 1 2 1
 2 2 3 1
"""


def run_cli(*args: str, check: bool = True, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], text=True, capture_output=True, check=check, env=env)


def plan_hash(plan: dict) -> str:
    canonical = {key: value for key, value in plan.items() if key != "plan_sha256"}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def make_environment_receipt(root: Path, *, ready: bool = True, acpype: bool = False) -> Path:
    path = root / "environment_receipt.json"
    path.write_text(json.dumps({"schema_version": "1.1", "artifact_type": "molecular_modeling_environment_receipt", "created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "profile": "cpu-fallback", "ready": ready, "report": {"tools": {"acpype": {"available": acpype}}}}))
    return path


class AcpypeRuntimeEnvironmentTests(unittest.TestCase):
    def test_discovers_only_exact_missing_sonames_in_prefix_lib(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prefix = root / "prefix"
            prefix_bin = prefix / "bin"
            prefix_lib = prefix / "lib"
            purelib = prefix_lib / "python3.12" / "site-packages"
            bundled_root = purelib / "acpype" / "amber_linux"
            bundled_bin = bundled_root / "bin"
            bundled_lib = bundled_root / "lib"
            prefix_bin.mkdir(parents=True)
            bundled_bin.mkdir(parents=True)
            bundled_lib.mkdir()

            interpreter = prefix_bin / "python3.12"
            interpreter.touch()
            acpype = prefix_bin / "acpype"
            acpype.write_text(f"#!{interpreter}\n")
            for binary_name in ("sqm", "teLeap"):
                (bundled_bin / binary_name).write_bytes(b"\x7fELFfixture")

            expected_sonames = [
                "libarpack.so.2",
                "libmfhdf.so.0",
                "libdf.so.0",
                "libhdf5_hl.so.310",
                "libhdf5.so.310",
                "libzip.so.5",
            ]
            expected_paths = [prefix_lib / soname for soname in expected_sonames]
            for path in expected_paths:
                path.touch()
            (prefix_lib / "libunrelated.so.9").touch()
            (root / "liboutside.so.1").touch()

            ldd_outputs = {
                "sqm": """\
\tlibarpack.so.2 => not found
\tlibunrelated.so.9 => /tmp/libunrelated.so.9 (0x0001)
\t../../escape.so => not found
""",
                "teLeap": """\
\tlibmfhdf.so.0 => not found
\tlibdf.so.0 => not found
\tlibhdf5_hl.so.310 => not found
\tlibhdf5.so.310 => not found
\tlibzip.so.5 => not found
\tliboutside.so.1 => not found
\tlibunrelated.so.9 not found
""",
            }
            calls = []

            def fake_run(command, **kwargs):
                calls.append((command, kwargs))
                if command[0] == str(interpreter):
                    return subprocess.CompletedProcess(command, 0, f"{purelib}\n", "")
                return subprocess.CompletedProcess(command, 1, ldd_outputs[Path(command[1]).name], "")

            inherited_library_path = os.pathsep.join(("inherited-one", "inherited-two"))
            inherited_preload = "libc.so.6"
            with mock.patch.dict(LIGAND_PARAMETERIZATION.os.environ, {
                "LD_LIBRARY_PATH": inherited_library_path,
                "LD_PRELOAD": inherited_preload,
                "PYTHONHOME": "not-recorded-home",
                "PYTHONPATH": "not-recorded-path",
            }, clear=True), mock.patch.object(LIGAND_PARAMETERIZATION, "system_ldd", return_value=Path("/fixture/ldd")), mock.patch.object(LIGAND_PARAMETERIZATION.subprocess, "run", side_effect=fake_run):
                child_environment, receipt_environment = LIGAND_PARAMETERIZATION.acpype_child_environment(str(acpype))

            self.assertIsNotNone(child_environment)
            self.assertEqual(child_environment["LD_LIBRARY_PATH"], inherited_library_path)
            self.assertEqual(child_environment["LD_PRELOAD"].split(os.pathsep), [*(str(path) for path in expected_paths), inherited_preload])
            self.assertEqual(receipt_environment, {
                "LD_PRELOAD_prepend": [str(path) for path in expected_paths],
            })
            self.assertEqual([Path(call[0][1]).name for call in calls[1:]], ["sqm", "teLeap"])
            self.assertNotIn("PYTHONHOME", calls[0][1]["env"])
            self.assertNotIn("PYTHONPATH", calls[0][1]["env"])
            self.assertTrue(all(call[1]["env"]["LD_LIBRARY_PATH"] == str(bundled_lib) for call in calls[1:]))
            self.assertTrue(all("LD_PRELOAD" not in call[1]["env"] for call in calls[1:]))
            self.assertNotIn(inherited_preload, json.dumps(receipt_environment))
            self.assertNotIn("libunrelated.so.9", child_environment["LD_PRELOAD"])
            self.assertNotIn("liboutside.so.1", child_environment["LD_PRELOAD"])

    def test_ldd_unavailable_does_not_override_inherited_preload(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / "prefix"
            prefix_bin = prefix / "bin"
            prefix_lib = prefix / "lib"
            prefix_bin.mkdir(parents=True)
            prefix_lib.mkdir()
            (prefix_lib / "libarpack.so.2").touch()
            acpype = prefix_bin / "acpype"
            acpype.write_text("#!/bin/sh\n")
            with mock.patch.dict(LIGAND_PARAMETERIZATION.os.environ, {"LD_PRELOAD": "inherited.so"}, clear=True), mock.patch.object(LIGAND_PARAMETERIZATION, "system_ldd", return_value=None):
                child_environment, receipt_environment = LIGAND_PARAMETERIZATION.acpype_child_environment(str(acpype))
            self.assertEqual(child_environment["LD_PRELOAD"], "inherited.so")
            self.assertNotIn("LD_LIBRARY_PATH", child_environment)
            self.assertEqual(receipt_environment, {})

    def test_non_prefix_acpype_preserves_no_adjustment(self):
        with tempfile.TemporaryDirectory() as tmp:
            acpype = Path(tmp) / "acpype"
            acpype.touch()
            self.assertEqual(LIGAND_PARAMETERIZATION.acpype_child_environment(str(acpype)), (None, None))


class PlanTests(unittest.TestCase):
    def test_plan_records_explicit_charge_and_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ligand = root / "lig.mol2"
            ligand.write_text(LIGAND_MOL2)
            run_cli("plan", "--ligand", str(ligand), "--force-field", "amber-gaff", "--net-charge", "-1", "--output-dir", str(root))
            plan = json.loads((root / "ligand_parameterization_plan.json").read_text())
            self.assertEqual(plan["net_charge"], -1)
            self.assertIn("never inferred", plan["net_charge_source"])
            self.assertEqual(plan["actions"][0]["engine"], "acpype")
            self.assertEqual(plan["charge_method"], "bcc")
            self.assertEqual(plan["actions"][0]["command"][plan["actions"][0]["command"].index("-c") + 1], "bcc")
            self.assertEqual(len(plan["plan_sha256"]), 64)

    def test_sdf_default_and_explicit_bcc_are_recorded_in_argv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ligand = root / "lig.sdf"
            ligand.write_text(LIGAND_SDF)
            for label, charge_args in (("default", []), ("explicit", ["--charge-method", "bcc"])):
                output_dir = root / label
                run_cli("plan", "--ligand", str(ligand), "--force-field", "amber-gaff", "--net-charge", "0", *charge_args, "--output-dir", str(output_dir))
                plan = json.loads((output_dir / "ligand_parameterization_plan.json").read_text())
                command = plan["actions"][0]["command"]
                self.assertEqual(plan["charge_method"], "bcc")
                self.assertEqual(command[command.index("-c") + 1], "bcc")

    def test_user_charge_method_rejects_sdf_and_pdb_but_accepts_mol2(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for suffix, content in ((".sdf", LIGAND_SDF), (".pdb", LIGAND_PDB)):
                ligand = root / f"rejected{suffix}"
                ligand.write_text(content)
                result = run_cli("plan", "--ligand", str(ligand), "--force-field", "amber-gaff", "--net-charge", "0", "--charge-method", "user", "--output-dir", str(root / suffix[1:]), check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("requires an explicitly reviewed MOL2", result.stderr)
            ligand = root / "accepted.mol2"
            ligand.write_text(LIGAND_MOL2)
            output_dir = root / "mol2"
            run_cli("plan", "--ligand", str(ligand), "--force-field", "amber-gaff", "--net-charge", "0", "--charge-method", "user", "--output-dir", str(output_dir))
            plan = json.loads((output_dir / "ligand_parameterization_plan.json").read_text())
            command = plan["actions"][0]["command"]
            self.assertEqual(plan["charge_method"], "user")
            self.assertEqual(command[command.index("-c") + 1], "user")

    def test_plan_requires_net_charge(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ligand = root / "lig.mol2"
            ligand.write_text(LIGAND_MOL2)
            result = run_cli("plan", "--ligand", str(ligand), "--force-field", "amber-gaff", "--output-dir", str(root), check=False)
            self.assertNotEqual(result.returncode, 0)

    def test_cgenff_route_is_handoff_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ligand = root / "lig.mol2"
            ligand.write_text(LIGAND_MOL2)
            run_cli("plan", "--ligand", str(ligand), "--force-field", "charmm-cgenff", "--net-charge", "0", "--output-dir", str(root))
            plan = json.loads((root / "ligand_parameterization_plan.json").read_text())
            self.assertEqual(plan["actions"][0]["kind"], "handoff")
            run_cli("run", "--plan", str(root / "ligand_parameterization_plan.json"), "--environment-receipt", str(make_environment_receipt(root)), "--output-dir", str(root))
            receipt = json.loads((root / "parameterization_receipt.json").read_text())
            self.assertEqual(receipt["actions"][0]["status"], "handoff_required")

    def test_run_rejects_tampered_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ligand = root / "lig.mol2"
            ligand.write_text(LIGAND_MOL2)
            run_cli("plan", "--ligand", str(ligand), "--force-field", "amber-gaff", "--net-charge", "0", "--output-dir", str(root))
            plan_path = root / "ligand_parameterization_plan.json"
            plan = json.loads(plan_path.read_text())
            plan["net_charge"] = 2
            plan_path.write_text(json.dumps(plan))
            result = run_cli("run", "--plan", str(plan_path), "--environment-receipt", str(make_environment_receipt(root)), "--output-dir", str(root), check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Plan hash does not match", result.stderr)

    def test_run_rejects_unready_environment_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); ligand = root / "lig.mol2"; ligand.write_text(LIGAND_MOL2)
            run_cli("plan", "--ligand", str(ligand), "--force-field", "charmm-cgenff", "--net-charge", "0", "--output-dir", str(root))
            result = run_cli("run", "--plan", str(root / "ligand_parameterization_plan.json"), "--environment-receipt", str(make_environment_receipt(root, ready=False)), "--output-dir", str(root), check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not ready", result.stderr)

    def test_run_rejects_hash_valid_legacy_sdf_user_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ligand = root / "lig.sdf"
            ligand.write_text(LIGAND_SDF)
            run_cli("plan", "--ligand", str(ligand), "--force-field", "amber-gaff", "--net-charge", "0", "--output-dir", str(root))
            plan_path = root / "ligand_parameterization_plan.json"
            plan = json.loads(plan_path.read_text())
            del plan["charge_method"]
            command = plan["actions"][0]["command"]
            command[command.index("-c") + 1] = "user"
            plan["actions"][0]["charge_policy"] = "legacy user-charge policy"
            plan["plan_sha256"] = plan_hash(plan)
            plan_path.write_text(json.dumps(plan))
            result = run_cli("run", "--plan", str(plan_path), "--environment-receipt", str(make_environment_receipt(root, acpype=True)), "--output-dir", str(root), check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Legacy SDF/PDB plan uses ACPYPE -c user", result.stderr)
            self.assertIn("regenerate", result.stderr)

    def test_prefixed_acpype_preserves_library_path_and_adds_only_discovered_preloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ligand = root / "lig.sdf"
            ligand.write_text(LIGAND_SDF)
            run_cli("plan", "--ligand", str(ligand), "--force-field", "amber-gaff", "--net-charge", "0", "--output-dir", str(root))
            plan_path = root / "ligand_parameterization_plan.json"
            plan = json.loads(plan_path.read_text())
            prefix = root / "fake-prefix"
            fake_bin = prefix / "bin"
            prefix_lib = prefix / "lib"
            fake_bin.mkdir(parents=True)
            prefix_lib.mkdir()
            preload_paths = [prefix_lib / "libfirst.so.1", prefix_lib / "libsecond.so.2"]
            acpype = fake_bin / "acpype"
            inherited_library_path = os.pathsep.join(("inherited-one", "inherited-two"))
            inherited_preload = "libc.so.6"
            expected_preload = os.pathsep.join([*(str(path) for path in preload_paths), inherited_preload])
            acpype.write_text(
                f"""#!{sys.executable}
import os
import sys
from pathlib import Path

if os.environ.get("LD_LIBRARY_PATH") != {inherited_library_path!r}:
    print("unexpected LD_LIBRARY_PATH", file=sys.stderr)
    raise SystemExit(23)
if os.environ.get("LD_PRELOAD") != {expected_preload!r}:
    print("unexpected LD_PRELOAD", file=sys.stderr)
    raise SystemExit(24)
identity = sys.argv[sys.argv.index("-b") + 1]
output = Path.cwd() / f"{{identity}}.acpype"
output.mkdir()
(output / f"{{identity}}_GMX.itp").write_text("[ moleculetype ]\\n")
(output / f"{{identity}}_GMX.gro").write_text("LIG\\n")
"""
            )
            acpype.chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
                "LD_LIBRARY_PATH": inherited_library_path,
                "LD_PRELOAD": inherited_preload,
            }
            environment_receipt = make_environment_receipt(root, acpype=True)
            with mock.patch.dict(LIGAND_PARAMETERIZATION.os.environ, env, clear=True), mock.patch.object(
                LIGAND_PARAMETERIZATION,
                "acpype_missing_prefix_libraries",
                return_value=preload_paths,
            ):
                receipt = LIGAND_PARAMETERIZATION.run_plan(plan_path, root, str(environment_receipt))
                self.assertEqual(LIGAND_PARAMETERIZATION.os.environ["LD_LIBRARY_PATH"], inherited_library_path)
                self.assertEqual(LIGAND_PARAMETERIZATION.os.environ["LD_PRELOAD"], inherited_preload)
            action = receipt["actions"][0]
            self.assertEqual(action["status"], "completed")
            self.assertEqual(action["command"][1:], plan["actions"][0]["command"][1:])
            self.assertEqual(action["runtime_environment"], {
                "LD_PRELOAD_prepend": [str(path) for path in preload_paths],
            })
            self.assertEqual(set(action["outputs"]), {"topology", "coordinates"})
            self.assertTrue(all("sha256" in output for output in action["outputs"].values()))
            self.assertNotIn("LD_LIBRARY_PATH_prepend", json.dumps(action))

    def test_local_acpype_failure_writes_receipt_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ligand = root / "lig.sdf"
            ligand.write_text(LIGAND_SDF)
            run_cli("plan", "--ligand", str(ligand), "--force-field", "amber-gaff", "--net-charge", "0", "--output-dir", str(root))
            fake_bin = root / "bin"
            fake_bin.mkdir()
            acpype = fake_bin / "acpype"
            acpype.write_text("#!/bin/sh\necho 'ACPYPE stdout evidence'\necho 'ACPYPE stderr evidence' >&2\nexit 19\n")
            acpype.chmod(0o755)
            env = {**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}"}
            result = run_cli("run", "--plan", str(root / "ligand_parameterization_plan.json"), "--environment-receipt", str(make_environment_receipt(root, acpype=True)), "--output-dir", str(root), check=False, env=env)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Success", result.stdout)
            receipt = json.loads((root / "parameterization_receipt.json").read_text())
            action = receipt["actions"][0]
            self.assertEqual(action["status"], "failed")
            self.assertNotIn("runtime_environment", action)
            self.assertEqual(action["returncode"], 19)
            self.assertEqual(len(action["attempts"]), 2)
            self.assertTrue(all(attempt["returncode"] == 19 for attempt in action["attempts"]))
            self.assertTrue(all("stdout evidence" in attempt["stdout"] for attempt in action["attempts"]))
            self.assertTrue(all("stderr evidence" in attempt["stderr"] for attempt in action["attempts"]))


class FinalizeTests(unittest.TestCase):
    def make_receipt(self, root: Path) -> Path:
        receipt = {
            "artifact_type": "ligand_parameterization_receipt",
            "ligand_identity": "LIG",
            "net_charge": -1,
            "force_field": "amber-gaff",
            "actions": [{"engine": "acpype", "status": "completed"}],
        }
        path = root / "parameterization_receipt.json"
        path.write_text(json.dumps(receipt))
        return path

    def test_finalize_requires_charge_inspection_for_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = self.make_receipt(root)
            (root / "LIG.itp").write_text("[ moleculetype ]\n")
            (root / "LIG.gro").write_text("LIG\n")
            run_cli("finalize", "--receipt", str(receipt), "--topology", str(root / "LIG.itp"), "--coordinates", str(root / "LIG.gro"), "--output", str(root / "ligand_parameters.json"))
            pending = json.loads((root / "ligand_parameters.json").read_text())
            self.assertEqual(pending["validation"]["status"], "pending_review")
            run_cli("finalize", "--receipt", str(receipt), "--topology", str(root / "LIG.itp"), "--coordinates", str(root / "LIG.gro"), "--charges-verified", "--output", str(root / "ligand_parameters.json"))
            validated = json.loads((root / "ligand_parameters.json").read_text())
            self.assertEqual(validated["validation"]["status"], "validated")
            for field in ("ligand_identity", "net_charge", "topology", "coordinates", "validation"):
                self.assertIn(field, validated)

    def test_finalize_rejects_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            receipt = self.make_receipt(root)
            result = run_cli("finalize", "--receipt", str(receipt), "--topology", str(root / "missing.itp"), "--coordinates", str(root / "missing.gro"), "--charges-verified", "--output", str(root / "out.json"), check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not exist", result.stderr)


class DetectTests(unittest.TestCase):
    def test_detect_writes_route_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_cli("detect", "--output-dir", str(root))
            report = json.loads((root / "parameterization_environment.json").read_text())
            for tool in ("acpype", "antechamber", "obabel", "gmx"):
                self.assertIn(tool, report["tools"])
            self.assertFalse(report["routes"]["charmm-cgenff"]["auto_runnable"])
            self.assertIn("no automatic tool downloads", report["boundaries"])


if __name__ == "__main__":
    unittest.main()
