import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "generate_visualization_scene.py"


def pdb_line(record, serial, name, resname, chain, resid, x, y, z, element):
    return f"{record:<6}{serial:5d} {name:<4} {resname:>3} {chain}{resid:4d}    {x:8.3f}{y:8.3f}{z:8.3f}{1.0:6.2f}{0.0:6.2f}          {element:>2}\n"


class DirectPdbVisualizationTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], check=True, text=True, capture_output=True)

    def test_ligand_glass_scene_writes_disclosure_and_adapters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); pdb = root / "complex.pdb"
            pdb.write_text("".join([
                pdb_line("ATOM", 1, "N", "SER", "A", 10, 0, 0, 0, "N"),
                pdb_line("ATOM", 2, "OG", "SER", "A", 10, 1.5, 0, 0, "O"),
                pdb_line("HETATM", 3, "C1", "LIG", "B", 501, 3, 0, 0, "C"),
                pdb_line("HETATM", 4, "O1", "LIG", "B", 501, 3.8, 0, 0, "O"),
                pdb_line("HETATM", 5, "N1", "LIG", "B", 501, 3, 1, 0, "N"),
                "END\n",
            ]))
            request = root / "request.json"; out = root / "viz"
            self.run_cli("template", "--kind", "protein-ligand", "--output", request)
            payload = json.loads(request.read_text()); payload["request_trace"] = {"user_request": "半透明气泡+内部骨架，重点看口袋氢键", "interpretation_confidence": "medium"}; request.write_text(json.dumps(payload))
            self.run_cli("infer", "--structure", pdb, "--request", request, "--output-dir", out)
            self.run_cli("generate", "--structure", pdb, "--request", request, "--output-dir", out)
            scene = json.loads((out / "visualization_scene.json").read_text())
            self.assertEqual(scene["kind"], "protein-ligand")
            self.assertTrue((out / "render_chimerax.cxc").is_file())
            self.assertTrue((out / "render_pymol.pml").is_file())
            self.assertIn("geometry candidates", (out / "visualization_report.md").read_text())

    def test_poor_interface_inference_falls_back_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); pdb = root / "protein.pdb"
            pdb.write_text("".join([pdb_line("ATOM", 1, "CA", "ALA", "A", 1, 0, 0, 0, "C"), pdb_line("ATOM", 2, "CA", "GLY", "B", 2, 30, 0, 0, "C"), "END\n"]))
            request = root / "request.json"; out = root / "viz"
            self.run_cli("template", "--kind", "protein-protein", "--output", request)
            self.run_cli("infer", "--structure", pdb, "--request", request, "--output-dir", out)
            data = json.loads((out / "inference.json").read_text())
            self.assertEqual(data["kind"], "protein")
            self.assertTrue(data["warnings"])


if __name__ == "__main__":
    unittest.main()
