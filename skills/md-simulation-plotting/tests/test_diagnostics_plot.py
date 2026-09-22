# pyright: reportMissingImports=false
"""M5 diagnostics gallery exports and style-only redraw contract."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.image as mpimg  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import md_style  # noqa: E402
from plot_diagnostics import plot_diagnostics  # noqa: E402

ENERGY = """@ xaxis label \"Time (ps)\"
@ yaxis label \"(kJ/mol), (K), (bar)\"
0 300 1 -100
1 301 1.1 -99
2 299 0.9 -101
"""
RMSD = """@ xaxis label \"Time (ns)\"
0 0
0.001 0.1
0.002 0.12
"""
RMSF = """@ xaxis label \"Residue\"
1 0.05
2 0.08
"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DiagnosticsPlotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "energy.xvg").write_text(ENERGY, encoding="utf-8")
        (self.root / "rmsd.xvg").write_text(RMSD, encoding="utf-8")
        (self.root / "rmsf.xvg").write_text(RMSF, encoding="utf-8")
        self.original_size = md_style.StyleConfig.FIG_SIZE_DIAGNOSTICS
        self.original_font = md_style.StyleConfig.FONT_SIZE

    def tearDown(self) -> None:
        md_style.StyleConfig.FIG_SIZE_DIAGNOSTICS = self.original_size
        md_style.StyleConfig.FONT_SIZE = self.original_font
        self.tmp.cleanup()

    def test_png_svg_pdf_exports_are_openable_and_share_panel_content(self) -> None:
        prefix = self.root / "figures" / "diagnostics"
        prefix.parent.mkdir()
        plot_diagnostics(self.root, prefix, eq_start_ns=0.001)

        png = prefix.with_suffix(".png")
        svg = prefix.with_suffix(".svg")
        pdf = prefix.with_suffix(".pdf")
        for path in (png, svg, pdf):
            self.assertTrue(path.is_file(), path)
            self.assertGreater(path.stat().st_size, 100, path)
        image = mpimg.imread(png)
        self.assertGreater(image.shape[0], 0)
        self.assertGreater(image.shape[1], 0)
        svg_text = svg.read_text(encoding="utf-8")
        self.assertIn("<svg", svg_text)
        self.assertIn("</svg>", svg_text)
        for title in ("Temperature", "Pressure", "Potential energy", "RMSD", "RMSF"):
            self.assertIn(title, svg_text)
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF-"))

    def test_style_redraw_changes_figure_only_and_preserves_numeric_inputs(
        self,
    ) -> None:
        inputs = [self.root / name for name in ("energy.xvg", "rmsd.xvg", "rmsf.xvg")]
        before = {path.name: sha256(path) for path in inputs}
        first = self.root / "first"
        plot_diagnostics(self.root, first)

        style = self.root / "style.json"
        style.write_text(
            json.dumps({"fig_size_diagnostics": [10.0, 8.0], "font_size": 12}),
            encoding="utf-8",
        )
        md_style.load_style_config(style)
        second = self.root / "second"
        plot_diagnostics(self.root, second)

        after = {path.name: sha256(path) for path in inputs}
        self.assertEqual(after, before)
        self.assertEqual(tuple(md_style.StyleConfig.FIG_SIZE_DIAGNOSTICS), (10.0, 8.0))
        self.assertNotEqual(
            sha256(first.with_suffix(".png")),
            sha256(second.with_suffix(".png")),
        )


if __name__ == "__main__":
    unittest.main()
