import datetime as dt
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "protein_ligand_system.py"


def reference(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def fixture(root: Path) -> dict[str, Path]:
    pose = root / "pose_001.pdbqt"; pose.write_text("MODEL 1\nENDMDL\n")
    topology = root / "BNZ.itp"; topology.write_text("[ moleculetype ]\nBNZ 3\n")
    ligand_coordinates = root / "BNZ.gro"; ligand_coordinates.write_text("BNZ\n0\n   1.0   1.0   1.0\n")
    receptor = root / "receptor.pdb"; receptor.write_text("ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00  0.00           N\nEND\n")
    termini = root / "termini.json"; termini.write_text(json.dumps({"schema_version": "1.0", "artifact_type": "protein_termini_record", "chains": [{"chain_id": "A", "n_terminus": "NH3+", "c_terminus": "COO-"}]}))
    docker = root / "docker"; docker.write_text("#!/bin/sh\n"); docker.chmod(0o755)
    receipt = root / "environment_receipt.json"; receipt.write_text(json.dumps({"schema_version": "1.1", "artifact_type": "molecular_modeling_environment_receipt", "created_at": dt.datetime.now(dt.timezone.utc).isoformat(), "profile": "wsl2-gpu", "ready": True, "report": {"tools": {"docker": {"available": True, "path": str(docker)}}, "gromacs_container": {"available": True, "digest": "nvcr.io/nvidia/gromacs@sha256:" + "a" * 64}}}))
    handoff = root / "md_handoff.json"; handoff.write_text(json.dumps({"schema_version": "1.0", "artifact_type": "docking_to_md_handoff", "system_type": "protein-ligand", "selection": {"coordinates": reference(pose)}, "ligand": {"applicable": True, "force_field": "amber-gaff", "force_field_family": "amber", "protein_force_field": "amber99sb-ildn", "topology": reference(topology), "coordinates": reference(ligand_coordinates), "validation": {"status": "validated"}}, "validation": {"status": "validated"}}))
    return {"handoff": handoff, "receipt": receipt, "receptor": receptor, "termini": termini}


class ProteinLigandSystemTests(unittest.TestCase):
    def run_cli(self, *args, check=True):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], text=True, capture_output=True, check=check)

    def test_plan_hashes_validated_inputs_and_fixed_acceptance_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); paths = fixture(root); plan = root / "system_plan.json"
            self.run_cli("plan", "--handoff", paths["handoff"], "--environment-receipt", paths["receipt"], "--receptor-pdb", paths["receptor"], "--termini-record", paths["termini"], "--water-model", "tip3p", "--box-shape", "dodecahedron", "--box-distance-nm", 1.2, "--salt-molar", 0.15, "--output", plan)
            data = json.loads(plan.read_text())
            self.assertEqual(data["artifact_type"], "protein_ligand_system_preparation_plan")
            self.assertEqual(data["parameters"], {"water_model": "tip3p", "box_shape": "dodecahedron", "box_distance_nm": 1.2, "salt_molar": 0.15})
            self.assertEqual(data["inputs"]["selected_pose"], reference(root / "pose_001.pdbqt"))
            self.assertEqual(len(data["plan_sha256"]), 64)

    def test_prepare_protein_requires_plan_bound_nonempty_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); paths = fixture(root); plan = root / "system_plan.json"
            self.run_cli("plan", "--handoff", paths["handoff"], "--environment-receipt", paths["receipt"], "--receptor-pdb", paths["receptor"], "--termini-record", paths["termini"], "--water-model", "tip3p", "--box-shape", "dodecahedron", "--box-distance-nm", 1.2, "--salt-molar", 0.15, "--output", plan)
            topology = root / "topol.top"; topology.write_text("#include \"amber99sb-ildn.ff/forcefield.itp\"\n")
            coordinates = root / "protein.gro"; coordinates.write_text("protein\n0\n   1.0   1.0   1.0\n")
            output = root / "protein_preparation.json"
            self.run_cli("prepare-protein", "--plan", plan, "--protein-topology", topology, "--protein-coordinates", coordinates, "--output", output)
            data = json.loads(output.read_text())
            self.assertEqual(data["artifact_type"], "reviewed_protein_preparation")
            self.assertEqual(data["protein_topology"], reference(topology))


if __name__ == "__main__":
    unittest.main()
