# pyright: reportMissingImports=false
"""T5.1 diagnostics mock suite: command assembly and rejection paths only.

This suite deliberately does NOT claim scientific correctness. It verifies:

- the audited `gmx` command vectors are assembled correctly (energy term
  selection, time-window flags, predefined group selection, PBC correction);
- invalid inputs fail closed (negative/empty time windows, free-expression or
  out-of-set atom groups).

Real numerical validation against a fixed small GROMACS CPU fixture is a
separate, explicitly tracked concern (see the M5 report: it is either executed
with a real `.tpr/.xtc/.edr` fixture or recorded as "not executed" with a
reason and owner — never simulated with mocks).
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import diagnostics  # noqa: E402


class DiagnosticsRejectionTests(unittest.TestCase):
    def test_negative_begin_rejected(self) -> None:
        with self.assertRaises(diagnostics.DiagnosticsError):
            diagnostics.validate_time_window(-1, None)

    def test_negative_end_rejected(self) -> None:
        with self.assertRaises(diagnostics.DiagnosticsError):
            diagnostics.validate_time_window(None, -5)

    def test_empty_time_window_rejected(self) -> None:
        with self.assertRaises(diagnostics.DiagnosticsError):
            diagnostics.validate_time_window(100, 50)

    def test_free_expression_group_rejected(self) -> None:
        with self.assertRaises(diagnostics.DiagnosticsError):
            diagnostics.validate_group("Protein and Water")

    def test_out_of_set_fit_group_rejected(self) -> None:
        with self.assertRaises(diagnostics.DiagnosticsError):
            diagnostics.validate_group("backbone", "custom_free_group")

    def test_predefined_group_accepted(self) -> None:
        name, fit = diagnostics.validate_group("c-alpha", "protein")
        self.assertEqual(name, "c-alpha")
        self.assertEqual(fit, "protein")


class DiagnosticsCommandAssemblyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[tuple[list[str], str | None]] = []
        patcher = mock.patch.object(
            diagnostics, "run_gmx_cmd", side_effect=self._record
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        idx = mock.patch.object(
            diagnostics, "generate_default_index", return_value="index.ndx"
        )
        idx.start()
        self.addCleanup(idx.stop)

    def _record(self, cmd, input_str=None):
        self.calls.append((cmd, input_str))
        if len(cmd) > 1 and cmd[1] == "energy":
            output = Path(cmd[cmd.index("-o") + 1])
            output.write_text(
                '@ s0 legend "Potential"\n'
                '@ s1 legend "Temperature"\n'
                '@ s2 legend "Pressure"\n'
                "0 -100 300 1\n",
                encoding="utf-8",
            )
        return "stdout"

    def _call(self, cmd_name):
        for cmd, _ in self.calls:
            if len(cmd) > 1 and cmd[1] == cmd_name:
                return cmd
        self.fail(f"no gmx {cmd_name} command was assembled")

    def _selection(self, cmd_name):
        for cmd, selection in self.calls:
            if len(cmd) > 1 and cmd[1] == cmd_name:
                return selection
        self.fail(f"no gmx {cmd_name} command was assembled")

    def _run(self, outdir, **kwargs):
        return diagnostics.run_diagnostics("a.tpr", "a.xtc", "a.edr", outdir, **kwargs)

    def test_energy_command_selects_temperature_pressure_potential(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp)
        cmd = self._call("energy")
        self.assertEqual(cmd[0], "gmx")
        self.assertIn("-f", cmd)
        self.assertIn("a.edr", cmd)
        self.assertIn("-o", cmd)
        self.assertTrue(cmd[-1].endswith("energy.xvg"), cmd)
        self.assertEqual(
            self._selection("energy"), "Temperature\nPressure\nPotential\n\n"
        )

    def test_energy_columns_are_normalized_to_documented_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp)
            rows = [
                line
                for line in (Path(tmp) / "energy.xvg").read_text().splitlines()
                if line and not line.startswith(("#", "@"))
            ]
            legends = [
                line
                for line in (Path(tmp) / "energy.xvg").read_text().splitlines()
                if "legend" in line
            ]
        self.assertEqual(rows, ["0 300 1 -100"])
        self.assertEqual(
            legends,
            [
                '@ s0 legend "Temperature"',
                '@ s1 legend "Pressure"',
                '@ s2 legend "Potential"',
            ],
        )

    def test_rmsd_uses_predefined_fit_and_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp, group="c-alpha", fit_group="protein")
        cmd = self._call("rms")
        self.assertIn("-tu", cmd)
        self.assertIn("ns", cmd)
        self.assertEqual(self._selection("rms"), "Protein\nC-alpha\n")

    def test_rmsf_uses_predefined_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp, group="c-alpha")
        cmd = self._call("rmsf")
        self.assertIn("-res", cmd)
        self.assertEqual(self._selection("rmsf"), "C-alpha\n")

    def test_time_window_flags_passed_to_rmsd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp, begin=0, end=1000)
        cmd = self._call("rms")
        self.assertIn("-b", cmd)
        self.assertIn("-e", cmd)
        self.assertEqual(cmd[cmd.index("-b") + 1], "0.0")
        # -b/-e are public API picoseconds, while gmx rms receives ns when
        # -tu ns is selected for the output time axis.
        self.assertEqual(cmd[cmd.index("-e") + 1], "1.0")

    def test_pbc_fit_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp)
        cmd = self._call("trjconv")
        self.assertIn("-pbc", cmd)
        self.assertIn("mol", cmd)
        self.assertIn("-center", cmd)
        self.assertEqual(cmd[cmd.index("-n") + 1], "index.ndx")

    def test_summary_records_scientific_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._run(tmp, begin=0, end=1000, eq_start=20, group="backbone")
            summary = json.loads(
                (Path(tmp) / "diagnostics_summary.json").read_text(encoding="utf-8")
            )
        self.assertEqual(summary["artifact_type"], "md_diagnostics_summary")
        self.assertEqual(summary["begin_ps"], 0)
        self.assertEqual(summary["end_ps"], 1000)
        self.assertEqual(summary["eq_start_ns"], 20)
        self.assertEqual(summary["group"], "backbone")
        self.assertEqual(
            summary["energy_terms"], ["Temperature", "Pressure", "Potential"]
        )


if __name__ == "__main__":
    unittest.main()
