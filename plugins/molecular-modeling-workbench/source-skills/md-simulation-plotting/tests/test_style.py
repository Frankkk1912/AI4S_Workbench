# pyright: reportMissingImports=false
"""D12: StyleConfig figure-size and font-size fields.

The plotting skill now sources its hardcoded font sizes (set_style rcParams)
and per-module figure sizes from `md_style.StyleConfig`, overridable through
`load_style_config` JSON. This suite proves two invariants:

1. The new defaults are byte-identical to the previous hardcoded values, so an
   untouched default configuration produces exactly the same figures as before.
2. A JSON override actually changes the values StyleConfig exposes and what
   `set_style` applies, while leaving style strictly separate from numeric data.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib as mpl  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import md_style  # noqa: E402

FONT_DEFAULTS = {
    "FONT_SIZE": 8,
    "TITLE_SIZE": 9,
    "LABEL_SIZE": 8,
    "TICK_SIZE": 7.5,
    "LEGEND_SIZE": 7.5,
    "LEGEND_TITLE_SIZE": 8,
}

FIG_DEFAULTS = {
    "FIG_SIZE_QC_4PANEL": (6.8, 5.0),
    "FIG_SIZE_HBONDS_2PANEL": (6.8, 3.0),
    "FIG_SIZE_HBONDS_SINGLE": (3.4, 3.0),
    "FIG_SIZE_DSSP": (6.8, 2.0),
    "FIG_SIZE_FEL_PANEL": (3.5, 3.5),
    "FIG_SIZE_GEOMETRY": (6.8, 2.5),
    "FIG_SIZE_NETWORK_2PANEL": (6.8, 3.2),
    "FIG_SIZE_NETWORK_4PANEL": (7.2, 6.0),
    "FIG_SIZE_RDF": (4.0, 3.0),
    "FIG_SIZE_DIAGNOSTICS": (6.8, 7.5),
}

# The literal tuples that previously lived inline in each plot module.
REMOVED_FIGSIZE_LITERALS = {
    "plot_basic_qc": ["(6.8, 5.0)"],
    "plot_basic_energy": ["(6.8, 3.0)", "(3.4, 3.0)"],
    "plot_basic_dssp": ["(6.8, 2.0 * n_rows)"],
    "plot_advanced_fel": ["(3.5 * n_cols, 3.5)"],
    "plot_advanced_geometry": ["(6.8, 2.5)"],
    "plot_advanced_network": ["(6.8, 3.2)", "(7.2, 6.0)"],
    "plot_advanced_rdf": ["(4.0, 3.0)"],
}

REMOVED_FONT_LITERALS = [
    "'font.size': 8",
    "'axes.titlesize': 9",
    "'axes.labelsize': 8",
    "'xtick.labelsize': 7.5",
    "'ytick.labelsize': 7.5",
    "'legend.fontsize': 7.5",
    "'legend.title_fontsize': 8",
]


class StyleConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._rc_snapshot = dict(mpl.rcParams)

    @classmethod
    def tearDownClass(cls) -> None:
        mpl.rcParams.update(cls._rc_snapshot)

    def tearDown(self) -> None:
        for name, value in FONT_DEFAULTS.items():
            setattr(md_style.StyleConfig, name, value)
        for name, value in FIG_DEFAULTS.items():
            setattr(md_style.StyleConfig, name, value)

    def test_default_font_sizes_match_previous_hardcoded_values(self) -> None:
        for name, value in FONT_DEFAULTS.items():
            self.assertEqual(getattr(md_style.StyleConfig, name), value, name)

    def test_default_fig_sizes_match_previous_hardcoded_values(self) -> None:
        for name, value in FIG_DEFAULTS.items():
            self.assertEqual(tuple(getattr(md_style.StyleConfig, name)), value, name)

    def test_load_style_config_overrides_font_and_fig_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "style.json"
            cfg.write_text(
                json.dumps({"font_size": 12, "fig_size_qc_4panel": [10.0, 8.0]}),
                encoding="utf-8",
            )
            md_style.load_style_config(str(cfg))
        self.assertEqual(md_style.StyleConfig.FONT_SIZE, 12)
        self.assertEqual(tuple(md_style.StyleConfig.FIG_SIZE_QC_4PANEL), (10.0, 8.0))

    def test_set_style_applies_configured_font_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "style.json"
            cfg.write_text(json.dumps({"font_size": 15}), encoding="utf-8")
            md_style.load_style_config(str(cfg))
            md_style.set_style()
            self.assertEqual(mpl.rcParams["font.size"], 15)

    def test_plot_modules_source_figsize_from_styleconfig(self) -> None:
        for name, literals in REMOVED_FIGSIZE_LITERALS.items():
            src = (SCRIPTS / f"{name}.py").read_text(encoding="utf-8")
            self.assertIn("StyleConfig.FIG_SIZE_", src, name)
            for literal in literals:
                self.assertNotIn(literal, src, f"{name} still hardcodes {literal}")

    def test_set_style_sources_font_sizes_from_styleconfig(self) -> None:
        src = (SCRIPTS / "md_style.py").read_text(encoding="utf-8")
        self.assertIn("StyleConfig.FONT_SIZE", src)
        for literal in REMOVED_FONT_LITERALS:
            self.assertNotIn(literal, src, f"md_style.py still hardcodes {literal}")


if __name__ == "__main__":
    unittest.main()
