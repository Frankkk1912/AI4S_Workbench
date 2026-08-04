import datetime as dt
import hashlib
import json
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


def write_pose(path: Path, atom_names: list[str]) -> None:
    records = []
    for index, name in enumerate(atom_names, start=1):
        records.append(
            f"ATOM  {index:5d} {name:<4} LIG A   1    {index:8.3f}{index + 1:8.3f}{index + 2:8.3f}  0.00  0.00    +0.000 C\n"
        )
    path.write_text("MODEL 1\n" + "".join(records) + "ENDMDL\n")


def write_gro(path: Path, atom_names: list[str]) -> None:
    records = []
    for index, name in enumerate(atom_names, start=1):
        records.append(f"{1:5d}{'LIG':<5}{name:>5}{index:5d}{index / 10:8.3f}{index / 10:8.3f}{index / 10:8.3f}\n")
    path.write_text(f"ligand\n{len(atom_names)}\n" + "".join(records) + "   1.00000   1.00000   1.00000\n")


def make_inputs(root: Path, pose_names: list[str], gro_names: list[str], *, coordinate_file: bool = True) -> dict[str, Path]:
    pose = root / "pose.pdbqt"
    topology = root / "ligand.itp"
    coordinates = root / "ligand.gro"
    manifest = root / "docking_manifest.json"
    poses = root / "ranked_poses.json"
    params = root / "parameters.json"
    write_pose(pose, pose_names)
    topology.write_text("[ atoms ]\n")
    write_gro(coordinates, gro_names)
    manifest.write_text(json.dumps({"receptor": {"path": "receptor.pdbqt"}}))
    pose_entry = {"pose_id": "pose_001", "source_file": str(pose)}
    if coordinate_file:
        pose_entry["coordinate_file"] = coordinate_reference(pose)
    poses.write_text(json.dumps({"poses": [pose_entry]}))
    params.write_text(json.dumps({"ligand_identity": "LIG", "net_charge": 0, "force_field": "amber-gaff", "topology": str(topology), "coordinates": str(coordinates), "validation": {"status": "validated"}, "provenance": {"tool": "test"}}))
    return {"pose": pose, "topology": topology, "coordinates": coordinates, "manifest": manifest, "poses": poses, "params": params}


def create_command(root: Path, inputs: dict[str, Path], system_type: str = "protein-ligand") -> list[str]:
    command = [sys.executable, str(SCRIPT), "create", "--docking-manifest", str(inputs["manifest"]), "--ranked-poses", str(inputs["poses"]), "--pose-id", "pose_001", "--system-type", system_type, "--environment-receipt", str(make_environment_receipt(root)), "--rationale", "Top-ranked pose after review", "--output", str(root / "md_handoff.json")]
    if system_type == "protein-ligand":
        command.extend(["--parameterization", str(inputs["params"]), "--protein-force-field", "amber99sb-ildn"])
    return command


class HandoffCliTests(unittest.TestCase):
    def test_valid_named_ligand_handoff_creates_and_validates_alignment_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = make_inputs(root, ["C1", "C2", "C3", "H1"], ["C1", "C2", "C3", "H1"])
            output = root / "md_handoff.json"
            subprocess.run(create_command(root, inputs), check=True)
            subprocess.run([sys.executable, str(SCRIPT), "validate", "--handoff", str(output), "--output", str(root / "validation.json")], check=True)
            handoff = json.loads(output.read_text())
            self.assertTrue(handoff["ligand"]["applicable"])
            self.assertEqual(handoff["ligand"]["validation"]["status"], "validated")
            self.assertEqual(handoff["selection"]["coordinates"], coordinate_reference(inputs["pose"]))
            self.assertEqual(handoff["ligand"]["alignment_admission"], {"status": "validated", "shared_non_hydrogen_atom_names": ["C1", "C2", "C3"], "shared_non_hydrogen_atom_count": 3, "minimum_required": 3})

    def test_duplicate_pose_atom_names_are_rejected_at_create(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = make_inputs(root, ["C", "C", "C", "C", "C", "C"], ["C1", "C2", "C3"])
            result = subprocess.run(create_command(root, inputs), text=True, capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("duplicate docking atom names: C (6 occurrences)", result.stderr)
            self.assertIn("Regenerate the ligand PDBQT with unique, stable atom names before docking", result.stderr)

    def test_insufficient_shared_non_hydrogen_names_are_rejected_at_create(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = make_inputs(root, ["C1", "C2", "H1"], ["C1", "C2", "H1"])
            result = subprocess.run(create_command(root, inputs), text=True, capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("requires at least three shared non-hydrogen atom names; found 2: C1, C2", result.stderr)

    def test_validate_rejects_legacy_protein_ligand_handoff_without_alignment_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = make_inputs(root, ["C1", "C2", "C3"], ["C1", "C2", "C3"])
            handoff = root / "md_handoff.json"
            subprocess.run(create_command(root, inputs), check=True)
            data = json.loads(handoff.read_text())
            del data["ligand"]["alignment_admission"]
            handoff.write_text(json.dumps(data))
            validation_path = root / "validation.json"
            result = subprocess.run([sys.executable, str(SCRIPT), "validate", "--handoff", str(handoff), "--output", str(validation_path)], text=True, capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            validation = json.loads(validation_path.read_text())
            self.assertIn("ligand.alignment_admission is required for protein-ligand handoffs; recreate this legacy handoff", validation["failures"])

    def test_non_ligand_route_remains_unaffected_by_pose_atom_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = make_inputs(root, ["C", "C"], ["C1", "C2", "C3"])
            output = root / "md_handoff.json"
            subprocess.run(create_command(root, inputs, system_type="protein-only"), check=True)
            subprocess.run([sys.executable, str(SCRIPT), "validate", "--handoff", str(output), "--output", str(root / "validation.json")], check=True)
            self.assertFalse(json.loads(output.read_text())["ligand"]["applicable"])

    def test_ligand_handoff_requires_a_hash_bound_individual_coordinate_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = make_inputs(root, ["C1", "C2", "C3"], ["C1", "C2", "C3"], coordinate_file=False)
            result = subprocess.run(create_command(root, inputs), text=True, capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("individual coordinate_file", result.stderr)

    def test_validate_rejects_modified_parameter_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inputs = make_inputs(root, ["C1", "C2", "C3"], ["C1", "C2", "C3"])
            handoff = root / "md_handoff.json"
            subprocess.run(create_command(root, inputs), check=True)
            inputs["topology"].write_text("tampered")
            result = subprocess.run([sys.executable, str(SCRIPT), "validate", "--handoff", str(handoff), "--output", str(root / "validation.json")], text=True, capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            validation = json.loads((root / "validation.json").read_text())
            self.assertIn("ligand.topology hash does not match", validation["failures"])


if __name__ == "__main__":
    unittest.main()
