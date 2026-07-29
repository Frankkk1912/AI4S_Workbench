import hashlib
import json
import datetime as dt
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "docking_to_md_handoff.py"


def coordinate_reference(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "format": "pdbqt"}


def make_environment_receipt(root: Path) -> Path:
    path = root / "environment_receipt.json"
    path.write_text(json.dumps({"schema_version": "1.1", "artifact_type": "molecular_modeling_environment_receipt", "created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "profile": "wsl2-gpu", "ready": True, "report": {"tools": {"gmx": {"available": True}}}}))
    return path


class HandoffCliTests(unittest.TestCase):
    def test_ligand_handoff_requires_validated_parameterization(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pose = root / "pose.pdbqt"; pose.write_text("MODEL 1\nENDMDL\n")
            topology = root / "ligand.itp"; topology.write_text("[ atoms ]\n")
            coordinates = root / "ligand.gro"; coordinates.write_text("ligand\n")
            manifest = root / "docking_manifest.json"; manifest.write_text(json.dumps({"receptor": {"path": "receptor.pdbqt"}}))
            poses = root / "ranked_poses.json"; poses.write_text(json.dumps({"poses": [{"pose_id": "pose_001", "source_file": str(pose), "coordinate_file": coordinate_reference(pose)}]}))
            params = root / "parameters.json"; params.write_text(json.dumps({"ligand_identity": "LIG", "net_charge": 0, "force_field": "amber-gaff", "topology": str(topology), "coordinates": str(coordinates), "validation": {"status": "validated"}, "provenance": {"tool": "test"}}))
            output = root / "md_handoff.json"
            subprocess.run([sys.executable, str(SCRIPT), "create", "--docking-manifest", str(manifest), "--ranked-poses", str(poses), "--pose-id", "pose_001", "--system-type", "protein-ligand", "--parameterization", str(params), "--environment-receipt", str(make_environment_receipt(root)), "--protein-force-field", "amber99sb-ildn", "--rationale", "Top-ranked pose after review", "--output", str(output)], check=True)
            subprocess.run([sys.executable, str(SCRIPT), "validate", "--handoff", str(output), "--output", str(root / "validation.json")], check=True)
            handoff = json.loads(output.read_text())
            self.assertTrue(handoff["ligand"]["applicable"])
            self.assertEqual(handoff["ligand"]["validation"]["status"], "validated")
            self.assertEqual(handoff["selection"]["coordinates"], coordinate_reference(pose))

    def test_ligand_handoff_requires_a_hash_bound_individual_coordinate_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); pose = root / "pose.pdbqt"; pose.write_text("MODEL 1\nENDMDL\n")
            topology = root / "ligand.itp"; topology.write_text("[ atoms ]\n")
            coordinates = root / "ligand.gro"; coordinates.write_text("ligand\n")
            manifest = root / "docking_manifest.json"; manifest.write_text(json.dumps({"receptor": {"path": "receptor.pdbqt"}}))
            poses = root / "ranked_poses.json"; poses.write_text(json.dumps({"poses": [{"pose_id": "pose_001", "source_file": str(pose)}]}))
            params = root / "parameters.json"; params.write_text(json.dumps({"ligand_identity": "LIG", "net_charge": 0, "force_field": "amber-gaff", "topology": str(topology), "coordinates": str(coordinates), "validation": {"status": "validated"}}))
            result = subprocess.run([sys.executable, str(SCRIPT), "create", "--docking-manifest", str(manifest), "--ranked-poses", str(poses), "--pose-id", "pose_001", "--system-type", "protein-ligand", "--parameterization", str(params), "--environment-receipt", str(make_environment_receipt(root)), "--protein-force-field", "amber99sb-ildn", "--rationale", "reviewed", "--output", str(root / "handoff.json")], text=True, capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("individual coordinate_file", result.stderr)

    def test_validate_rejects_modified_parameter_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); topology = root / "LIG.itp"; coordinates = root / "LIG.gro"; pose = root / "pose.pdbqt"
            topology.write_text("topology"); coordinates.write_text("coordinates"); pose.write_text("pose")
            manifest = root / "manifest.json"; poses = root / "poses.json"
            manifest.write_text(json.dumps({"receptor": {"path": "receptor.pdbqt"}})); poses.write_text(json.dumps({"poses": [{"pose_id": "pose_001", "source_file": str(pose), "coordinate_file": coordinate_reference(pose)}]}))
            params = root / "parameters.json"; params.write_text(json.dumps({"ligand_identity": "LIG", "net_charge": 0, "force_field": "amber-gaff", "topology": str(topology), "coordinates": str(coordinates), "validation": {"status": "validated"}}))
            handoff = root / "handoff.json"
            subprocess.run([sys.executable, str(SCRIPT), "create", "--docking-manifest", str(manifest), "--ranked-poses", str(poses), "--pose-id", "pose_001", "--system-type", "protein-ligand", "--parameterization", str(params), "--environment-receipt", str(make_environment_receipt(root)), "--protein-force-field", "amber99sb-ildn", "--rationale", "reviewed", "--output", str(handoff)], check=True)
            topology.write_text("tampered")
            result = subprocess.run([sys.executable, str(SCRIPT), "validate", "--handoff", str(handoff), "--output", str(root / "validation.json")], text=True, capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            validation = json.loads((root / "validation.json").read_text())
            self.assertIn("ligand.topology hash does not match", validation["failures"])


if __name__ == "__main__":
    unittest.main()
