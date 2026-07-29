import json
import datetime as dt
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "ligand_parameterization.py"

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


def run_cli(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], text=True, capture_output=True, check=check)


def make_environment_receipt(root: Path, *, ready: bool = True, acpype: bool = False) -> Path:
    path = root / "environment_receipt.json"
    path.write_text(json.dumps({"schema_version": "1.1", "artifact_type": "molecular_modeling_environment_receipt", "created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "profile": "cpu-fallback", "ready": ready, "report": {"tools": {"acpype": {"available": acpype}}}}))
    return path


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
            self.assertIn("-c", plan["actions"][0]["command"])
            self.assertEqual(len(plan["plan_sha256"]), 64)

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
