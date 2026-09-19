# pyright: reportMissingImports=false
"""Real GROMACS CPU fixture for diagnostics scientific contracts.

This suite is intentionally separate from the mock command suite. It creates a
fixed six-atom/two-residue protein, runs 100 deterministic CPU MD steps, and
validates actual gmx energy/rms/rmsf output with explicit tolerances. Hosts
without gmx skip rather than substituting mocked numerical evidence.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import diagnostics  # noqa: E402

GRO = """Tiny peptide
    9
    1ALA      N    1   0.100   0.100   0.100
    1ALA     CA    2   0.245   0.100   0.100
    1ALA      C    3   0.390   0.100   0.100
    2ALA      N    4   0.535   0.100   0.100
    2ALA     CA    5   0.680   0.100   0.100
    2ALA      C    6   0.825   0.100   0.100
    3ALA      N    7   0.970   0.100   0.100
    3ALA     CA    8   1.115   0.100   0.100
    3ALA      C    9   1.260   0.100   0.100
   2.00000   2.00000   2.00000
"""
TOP = """[ defaults ]
1 2 no 1.0 1.0
[ atomtypes ]
N  14.007 0.0 A 0.325 0.71128
C  12.011 0.0 A 0.340 0.45773
[ moleculetype ]
Protein 3
[ atoms ]
1 N 1 ALA N  1 0.0 14.007
2 C 1 ALA CA 1 0.0 12.011
3 C 1 ALA C  1 0.0 12.011
4 N 2 ALA N  2 0.0 14.007
5 C 2 ALA CA 2 0.0 12.011
6 C 2 ALA C  2 0.0 12.011
7 N 3 ALA N  3 0.0 14.007
8 C 3 ALA CA 3 0.0 12.011
9 C 3 ALA C  3 0.0 12.011
[ bonds ]
1 2 1 0.145 100000
2 3 1 0.145 100000
3 4 1 0.145 100000
4 5 1 0.145 100000
5 6 1 0.145 100000
6 7 1 0.145 100000
7 8 1 0.145 100000
8 9 1 0.145 100000
[ system ]
Tiny peptide
[ molecules ]
Protein 1
"""
MDP = """integrator = md
nsteps = 100
dt = 0.002
nstxout-compressed = 1
nstenergy = 1
nstlog = 10
cutoff-scheme = Verlet
rlist = 0.8
rcoulomb = 0.8
rvdw = 0.8
coulombtype = Cut-off
vdwtype = Cut-off
pbc = xyz
constraints = none
tcoupl = v-rescale
tc-grps = System
tau_t = 0.1
ref_t = 300
pcoupl = no
gen_vel = yes
gen_temp = 300
gen_seed = 12345
"""


def read_xvg(path: Path) -> tuple[str, list[list[float]]]:
    metadata = []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(("#", "@")):
            metadata.append(line)
        elif line.strip():
            rows.append([float(value) for value in line.split()])
    return "\n".join(metadata), rows


@unittest.skipUnless(shutil.which("gmx"), "real gmx CPU fixture requires gmx")
class RealGmxDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        (cls.root / "conf.gro").write_text(GRO, encoding="utf-8")
        (cls.root / "topol.top").write_text(TOP, encoding="utf-8")
        (cls.root / "md.mdp").write_text(MDP, encoding="utf-8")
        subprocess.run(
            [
                "gmx",
                "grompp",
                "-f",
                "md.mdp",
                "-c",
                "conf.gro",
                "-p",
                "topol.top",
                "-o",
                "fixture.tpr",
                "-maxwarn",
                "2",
            ],
            cwd=cls.root,
            text=True,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["gmx", "mdrun", "-s", "fixture.tpr", "-deffnm", "fixture", "-nt", "1"],
            cwd=cls.root,
            text=True,
            capture_output=True,
            check=True,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def run_real(self, name: str, **kwargs) -> Path:
        out = self.root / name
        diagnostics.run_diagnostics(
            self.root / "fixture.tpr",
            self.root / "fixture.xtc",
            self.root / "fixture.edr",
            out,
            **kwargs,
        )
        return out

    def test_energy_units_time_window_pbc_fit_and_group_are_real(self) -> None:
        backbone = self.run_real(
            "backbone", begin=0.04, end=0.16, group="backbone", fit_group="protein"
        )
        c_alpha = self.run_real(
            "calpha", begin=0.04, end=0.16, group="c-alpha", fit_group="protein"
        )
        fit_c_alpha = self.run_real(
            "fit-calpha", begin=0.04, end=0.16, group="backbone", fit_group="c-alpha"
        )
        wider = self.run_real(
            "wider", begin=0.0, end=0.2, group="backbone", fit_group="protein"
        )
        energy_meta, energy = read_xvg(backbone / "energy.xvg")
        rmsd_meta, rmsd = read_xvg(backbone / "rmsd.xvg")
        _, ca_rmsd = read_xvg(c_alpha / "rmsd.xvg")
        _, ca_fit_rmsd = read_xvg(fit_c_alpha / "rmsd.xvg")
        _, wide_energy = read_xvg(wider / "energy.xvg")
        _, wide_rmsd = read_xvg(wider / "rmsd.xvg")
        _, rmsf = read_xvg(backbone / "rmsf.xvg")

        self.assertIn("(kJ/mol), (K), (bar)", energy_meta)
        self.assertIn('@ s0 legend "Temperature"', energy_meta)
        self.assertIn('@ s1 legend "Pressure"', energy_meta)
        self.assertIn('@ s2 legend "Potential"', energy_meta)
        self.assertTrue(energy)
        self.assertTrue(all(len(row) == 4 for row in energy))
        self.assertGreaterEqual(energy[0][0], 0.04 - 1e-9)
        self.assertLessEqual(energy[-1][0], 0.16 + 1e-9)
        # Physical plausibility bounds; temperature in a 9-atom v-rescale
        # thermostat fluctuates by hundreds of Kelvin so we only check the
        # output column is numeric and finite, not a fixed reference value.
        self.assertTrue(all(math.isfinite(v) for row in energy for v in row))
        self.assertGreater(energy[0][1], 0)  # temperature > 0 K
        self.assertLess(energy[0][1], 5000)  # temperature < 5000 K (physical)
        # Potential energy should be finite; sign is system-dependent.
        self.assertTrue(math.isfinite(energy[0][3]))
        self.assertIn('xaxis  label "Time (ns)"', rmsd_meta)
        self.assertGreaterEqual(rmsd[0][0], 0.00004 - 1e-9)
        self.assertLessEqual(rmsd[-1][0], 0.00016 + 1e-9)
        self.assertTrue(all(math.isfinite(value) for row in rmsd for value in row))
        self.assertTrue(all(value >= 0 for _, value in rmsd))
        self.assertTrue(rmsf)
        self.assertTrue((backbone / "md_fit.xtc").is_file())
        self.assertGreater((backbone / "md_fit.xtc").stat().st_size, 0)
        # Time window, output group, and fit group all change real outputs.
        self.assertGreater(len(wide_energy), len(energy))
        self.assertGreater(len(wide_rmsd), len(rmsd))
        self.assertNotEqual([row[1] for row in rmsd], [row[1] for row in ca_rmsd])
        self.assertNotEqual([row[1] for row in rmsd], [row[1] for row in ca_fit_rmsd])

    def test_same_parameters_repeat_within_explicit_tolerance(self) -> None:
        first = self.run_real(
            "repeat-a", begin=0.04, end=0.16, group="backbone", fit_group="protein"
        )
        second = self.run_real(
            "repeat-b", begin=0.04, end=0.16, group="backbone", fit_group="protein"
        )
        for name in ("energy.xvg", "rmsd.xvg", "rmsf.xvg"):
            _, left = read_xvg(first / name)
            _, right = read_xvg(second / name)
            self.assertEqual(len(left), len(right), name)
            for left_row, right_row in zip(left, right, strict=True):
                self.assertEqual(len(left_row), len(right_row), name)
                for left_value, right_value in zip(left_row, right_row, strict=True):
                    self.assertAlmostEqual(
                        left_value, right_value, delta=1e-6, msg=name
                    )


if __name__ == "__main__":
    unittest.main()
