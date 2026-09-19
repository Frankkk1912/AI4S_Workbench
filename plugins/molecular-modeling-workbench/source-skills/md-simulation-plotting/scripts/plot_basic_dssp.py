import matplotlib.pyplot as plt
import md_style
import numpy as np
import parser_gmx
from matplotlib.colors import BoundaryNorm, ListedColormap

_DSSP_STATES = {
    "~": ("#F0F0F0", "Coil"),
    "H": ("#D73027", "Alpha helix"),
    "B": ("#4575B4", "Beta bridge"),
    "E": ("#74ADD1", "Beta strand"),
    "G": ("#F46D43", "3-10 helix"),
    "I": ("#A50026", "Pi helix"),
    "T": ("#FDAE61", "Turn"),
    "S": ("#ABDDA4", "Bend"),
}


def read_dssp(path):
    """Read legacy XPM or the GROMACS 2023+ one-character-per-residue DAT."""
    if str(path).endswith(".xpm"):
        mat, cmap, time, residues = parser_gmx.read_xpm(path)
        return mat, cmap, time, residues, "Time (ns)"
    rows = [line.strip() for line in open(path, encoding="utf-8") if line.strip()]
    if not rows or len({len(row) for row in rows}) != 1:
        raise ValueError("DSSP DAT must contain equal-length nonempty state rows.")
    unknown = sorted(set("".join(rows)) - set(_DSSP_STATES))
    if unknown:
        raise ValueError(f"Unsupported DSSP state symbols: {''.join(unknown)}")
    codes = {state: index for index, state in enumerate(_DSSP_STATES)}
    matrix = np.array([[codes[state] for state in row] for row in rows], dtype=int).T
    cmap = {index: _DSSP_STATES[state] for index, state in enumerate(_DSSP_STATES)}
    return matrix, cmap, np.arange(len(rows)), np.arange(1, len(rows[0]) + 1), "Frame"


def plot_tier1_dssp(
    sys1_xpm,
    sys2_xpm=None,
    output_name="tier1_dssp",
    sys1_label="System 1",
    sys2_label="System 2",
):
    """
    Generate Secondary Structure Heatmaps (DSSP).
    Plots 1 panel if single system, 2 stacked panels if sys2 provided.
    """
    is_single = sys2_xpm is None
    md_style.set_style()

    # Parse legacy XPM or current GROMACS DSSP DAT files.
    mat1, cmap_dict1, t1, res1, x_label = read_dssp(sys1_xpm)

    if not is_single:
        mat2, cmap_dict2, t2, res2, _ = read_dssp(sys2_xpm)
        num_colors = max(len(cmap_dict1), len(cmap_dict2))
    else:
        num_colors = len(cmap_dict1)

    # Build matplotlib colormap
    colors = []
    labels = []
    for i in range(num_colors):
        color, label = cmap_dict1.get(i, ("#FFFFFF", "Unknown"))
        colors.append(color)
        labels.append(label)

    cmap = ListedColormap(colors)
    bounds = np.arange(-0.5, num_colors + 0.5, 1)
    norm = BoundaryNorm(bounds, cmap.N)

    n_rows = 1 if is_single else 2
    fig_width, fig_height = md_style.StyleConfig.FIG_SIZE_DSSP
    fig, axes = plt.subplots(
        n_rows, 1, figsize=(fig_width, fig_height * n_rows), sharex=True
    )
    if not is_single:
        plt.subplots_adjust(hspace=0.3)
        ax1 = axes[0]
        ax2 = axes[1]
    else:
        ax1 = axes

    extent1 = [t1.min(), t1.max(), res1.min(), res1.max()]

    # System 1
    im1 = ax1.imshow(
        mat1,
        aspect="auto",
        cmap=cmap,
        norm=norm,
        origin="upper",
        extent=extent1,
        interpolation="none",
    )
    ax1.set_ylabel("Residue Index")
    ax1.set_title(f"A. {sys1_label} Secondary Structure", fontweight="bold", loc="left")

    if is_single:
        ax1.set_xlabel(x_label)
    else:
        extent2 = [t2.min(), t2.max(), res2.min(), res2.max()]
        im2 = ax2.imshow(
            mat2,
            aspect="auto",
            cmap=cmap,
            norm=norm,
            origin="upper",
            extent=extent2,
            interpolation="none",
        )
        ax2.set_ylabel("Residue Index")
        ax2.set_xlabel(x_label)
        ax2.set_title(
            f"B. {sys2_label} Secondary Structure", fontweight="bold", loc="left"
        )

    from matplotlib.patches import Patch

    legend_elements = [
        Patch(facecolor=colors[i], label=labels[i])
        for i in range(len(colors))
        if labels[i] != "Coil"
    ]

    fig.legend(
        handles=legend_elements,
        loc="center left",
        bbox_to_anchor=(0.92, 0.5),
        frameon=False,
        title="Structure",
    )

    md_style.save_pub_py(fig, output_name)
    plt.close(fig)
