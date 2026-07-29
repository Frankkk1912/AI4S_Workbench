import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "ligand_pose_alignment.py"
SPEC = importlib.util.spec_from_file_location("ligand_pose_alignment", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PoseAlignmentTests(unittest.TestCase):
    def test_aligns_complete_gro_ligand_by_named_heavy_atoms(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pose = root / "pose.pdbqt"
            pose.write_text(
                "ATOM      1  C1  BNZ A 400       1.000   2.000   3.000\n"
                "ATOM      2  C2  BNZ A 400       2.000   2.000   3.000\n"
                "ATOM      3  C3  BNZ A 400       1.000   3.000   3.000\n"
            )
            source = root / "BNZ.gro"
            source.write_text(
                "BNZ\n4\n"
                "    1BNZ     C1    1   0.000   0.000   0.000\n"
                "    1BNZ     C2    2   0.100   0.000   0.000\n"
                "    1BNZ     C3    3   0.000   0.100   0.000\n"
                "    1BNZ      H    4   0.000   0.000   0.100\n"
                "   2.00000   2.00000   2.00000\n"
            )
            output = root / "aligned.gro"
            result = MODULE.align_pose_to_gro(pose, source, output)
            self.assertLess(result["heavy_atom_rmsd_nm"], 1e-9)
            rows = output.read_text().splitlines()
            self.assertIn("0.100", rows[2])
            self.assertIn("0.200", rows[3])
            self.assertIn("0.300", rows[4])


if __name__ == "__main__":
    unittest.main()
