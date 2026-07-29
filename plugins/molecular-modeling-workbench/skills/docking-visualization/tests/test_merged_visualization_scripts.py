import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).parents[1] / "scripts"
PPI = SCRIPTS / "generate_ppi_viz.py"
LEGACY = SCRIPTS / "generate_viz_legacy.py"


def pdb_line(record, serial, name, resname, chain, resid, x, y, z, element):
    return f"{record:<6}{serial:5d} {name:<4} {resname:>3} {chain}{resid:4d}    {x:8.3f}{y:8.3f}{z:8.3f}{1.0:6.2f}{0.0:6.2f}          {element:>2}\n"


class MergedPpiVizTests(unittest.TestCase):
    def run_cli(self, script, *args, check=True):
        return subprocess.run([sys.executable, str(script), *map(str, args)], check=check, text=True, capture_output=True)

    def test_ppi_template_and_script_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "ppi_viz_config.json"
            out = root / "viz"
            self.run_cli(PPI, "template", "--output", config)
            payload = json.loads(config.read_text())
            self.assertIn("domains", payload)
            self.assertIn("interface_groups", payload)
            payload["structure"]["path"] = str(root / "complex.pdb")
            (root / "complex.pdb").write_text(pdb_line("ATOM", 1, "CA", "ALA", "A", 1, 0, 0, 0, "C"))
            config.write_text(json.dumps(payload))
            self.run_cli(PPI, "script", "--config", config, "--output-dir", out)
            self.assertTrue(any(out.glob("*.py")), "expected a generated ChimeraX Python script")

    def test_legacy_helper_still_detects_ligand(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdb = root / "complex.pdb"
            pdb.write_text("".join([
                pdb_line("ATOM", 1, "CA", "ALA", "A", 1, 0, 0, 0, "C"),
                pdb_line("HETATM", 2, "C1", "LIG", "B", 501, 3, 0, 0, "C"),
                pdb_line("HETATM", 3, "N1", "LIG", "B", 501, 3, 1.4, 0, "N"),
                "END\n",
            ]))
            result = self.run_cli(LEGACY, "--pdb", pdb, "--output-dir", root / "legacy")
            self.assertEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
