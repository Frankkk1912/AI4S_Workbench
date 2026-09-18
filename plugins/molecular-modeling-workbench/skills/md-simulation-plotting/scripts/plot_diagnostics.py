"""Plot formal M5 diagnostics without altering their numeric data."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import md_style


def read_xvg(path: str | Path) -> list[list[float]]:
    rows: list[list[float]] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped and not stripped.startswith(("#", "@")):
                rows.append([float(value) for value in stripped.split()])
    if not rows:
        raise ValueError(f"XVG file has no numeric rows: {path}")
    return rows


def _series(rows: list[list[float]], index: int) -> tuple[list[float], list[float]]:
    if any(len(row) <= index for row in rows):
        raise ValueError(f"XVG does not contain data column {index}")
    return [row[0] for row in rows], [row[index] for row in rows]


def plot_diagnostics(
    analysis_dir: str | Path,
    output_name: str | Path,
    eq_start_ns: float = 0.0,
) -> None:
    """Render temperature, pressure, energy, RMSD, and RMSF in one gallery item."""
    root = Path(analysis_dir)
    energy = read_xvg(root / "energy.xvg")
    rmsd = read_xvg(root / "rmsd.xvg")
    rmsf = read_xvg(root / "rmsf.xvg")
    if any(len(row) < 4 for row in energy):
        raise ValueError("energy.xvg must contain Temperature, Pressure, Potential")

    md_style.set_style()
    fig, axes = plt.subplots(
        3,
        2,
        figsize=md_style.StyleConfig.FIG_SIZE_DIAGNOSTICS,
        constrained_layout=True,
    )
    panels = (
        (axes[0][0], energy, 1, "Temperature", "K", md_style.StyleConfig.SYS1_COLOR),
        (axes[0][1], energy, 2, "Pressure", "bar", md_style.StyleConfig.SYS2_COLOR),
        (
            axes[1][0],
            energy,
            3,
            "Potential energy",
            "kJ/mol",
            md_style.StyleConfig.PURPLE_ACCENT,
        ),
        (axes[1][1], rmsd, 1, "RMSD", "nm", md_style.StyleConfig.TEAL_ACCENT),
        (axes[2][0], rmsf, 1, "RMSF", "nm", md_style.StyleConfig.ORANGE_WARN),
    )
    for axis, rows, column, title, unit, color in panels:
        x, y = _series(rows, column)
        axis.plot(x, y, color=color)
        axis.set_title(title)
        axis.set_ylabel(unit)
        x_label = "Residue"
        if title != "RMSF":
            x_label = "Time (ns)" if title == "RMSD" else "Time (ps)"
        axis.set_xlabel(x_label)
    if eq_start_ns > 0:
        axes[1][1].axvline(
            eq_start_ns,
            color=md_style.StyleConfig.GRAY_DARK,
            linestyle="--",
        )
    axes[2][1].axis("off")
    md_style.save_pub_py(fig, str(output_name))
    plt.close(fig)
