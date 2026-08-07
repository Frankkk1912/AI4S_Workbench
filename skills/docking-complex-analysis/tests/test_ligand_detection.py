import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyze_docking_complex.py"
SPEC = importlib.util.spec_from_file_location("analyze_docking_complex", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise ImportError(f"Unable to load {SCRIPT}")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE  # required for @dataclass type resolution
SPEC.loader.exec_module(MODULE)

Atom = MODULE.Atom


def make_atom(
    serial: int,
    name: str,
    resname: str,
    chain: str,
    resseq: int,
    element: str = "C",
):
    return Atom(
        serial=serial,
        record="HETATM",
        name=name,
        resname=resname,
        chain=chain,
        resseq=str(resseq),
        icode="",
        x=float(serial),
        y=0.0,
        z=0.0,
        element=element,
        model=1,
    )


def build_atoms(ligand_heavy=10, additive_heavy=4):
    atoms = [make_atom(i, "CA", "ALA", "A", i + 1) for i in range(20)]
    atoms += [make_atom(100 + i, f"C{i}", "LIG", "B", 1) for i in range(ligand_heavy)]
    atoms += [make_atom(200 + i, f"C{i}", "ACT", "C", 1) for i in range(additive_heavy)]
    return atoms


class LigandDetectionTests(unittest.TestCase):
    def test_largest_residue_above_threshold_wins(self):
        resname, candidates = MODULE.detect_ligand(build_atoms())
        self.assertEqual(resname, "LIG")
        self.assertEqual(candidates[0]["resname"], "LIG")

    def test_small_additives_are_rejected_with_reason(self):
        _resname, candidates = MODULE.detect_ligand(build_atoms())
        rejected = [c for c in candidates if "rejected_reason" in c]
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["resname"], "ACT")
        self.assertIn("min_ligand_atoms", rejected[0]["rejected_reason"])

    def test_error_when_all_candidates_below_threshold(self):
        atoms = build_atoms(ligand_heavy=0)
        with self.assertRaises(MODULE.AnalysisError) as ctx:
            MODULE.detect_ligand(atoms)
        self.assertIn("ACT(4 atoms)", str(ctx.exception))
        self.assertIn("--min-ligand-atoms", str(ctx.exception))

    def test_threshold_override_accepts_small_ligand(self):
        atoms = build_atoms(ligand_heavy=0)
        resname, _candidates = MODULE.detect_ligand(atoms, min_heavy_atoms=3)
        self.assertEqual(resname, "ACT")

    def test_solvent_and_standard_residues_are_ignored(self):
        atoms = build_atoms()
        atoms += [make_atom(300 + i, "O", "HOH", "D", i + 1, "O") for i in range(50)]
        atoms += [make_atom(400 + i, "CA", "GLY", "E", i + 1) for i in range(50)]
        resname, _candidates = MODULE.detect_ligand(atoms)
        self.assertEqual(resname, "LIG")


if __name__ == "__main__":
    unittest.main()
