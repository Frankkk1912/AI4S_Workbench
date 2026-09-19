import json
import os

import matplotlib as mpl


# Define softer, publication-friendly colors (Defaults)
class StyleConfig:
    SYS1_COLOR = "#4a90e2"  # Soft elegant blue for System 1 (e.g. WT / Apo)
    SYS2_COLOR = "#e95c4b"  # Soft coral / muted red for System 2 (e.g. Mutant / Holo)
    GRAY_LIGHT = "#cccccc"  # Auxiliary light gray for grids and borders
    GRAY_DARK = "#666666"  # Auxiliary dark gray for text and secondary labels
    GREEN_SAFE = (
        "#50b168"  # Soft green for ordered secondary structure / stable regions
    )
    ORANGE_WARN = (
        "#f5a623"  # Soft orange for transitional structures / intermediate regions
    )
    PURPLE_ACCENT = "#9b7bc7"  # Soft purple for structural loops / special bands
    TEAL_ACCENT = "#4a9b9e"  # Soft teal for secondary interfaces
    FONT_FAMILY = "sans-serif"
    FONT_SANS_SERIF = ["Arial", "Helvetica", "DejaVu Sans", "Liberation Sans"]
    # Font sizes (points). Defaults match the previously hard-coded rcParams in
    # set_style() so existing output is unchanged when no JSON override is applied.
    FONT_SIZE = 8
    TITLE_SIZE = 9
    LABEL_SIZE = 8
    TICK_SIZE = 7.5
    LEGEND_SIZE = 7.5
    LEGEND_TITLE_SIZE = 8
    # Figure sizes in inches ((width, height)). Defaults match the previously
    # hard-coded figsize=() values in each plot module.
    FIG_SIZE_QC_4PANEL = (6.8, 5.0)
    FIG_SIZE_HBONDS_2PANEL = (6.8, 3.0)
    FIG_SIZE_HBONDS_SINGLE = (3.4, 3.0)
    FIG_SIZE_DSSP = (6.8, 2.0)
    FIG_SIZE_FEL_PANEL = (3.5, 3.5)
    FIG_SIZE_GEOMETRY = (6.8, 2.5)
    FIG_SIZE_NETWORK_2PANEL = (6.8, 3.2)
    FIG_SIZE_NETWORK_4PANEL = (7.2, 6.0)
    FIG_SIZE_RDF = (4.0, 3.0)
    FIG_SIZE_DIAGNOSTICS = (6.8, 7.5)


def load_style_config(config_path):
    """Load a custom style configuration from a JSON file."""
    if not config_path or not os.path.exists(config_path):
        return
    with open(config_path, encoding="utf-8") as f:
        custom_styles = json.load(f)

    for key, value in custom_styles.items():
        if hasattr(StyleConfig, key.upper()):
            setattr(StyleConfig, key.upper(), value)


def set_style():
    """Apply global matplotlib settings for publication-quality panels (Nature/Science tier)."""
    mpl.rcParams.update(
        {
            # Font settings
            "font.family": StyleConfig.FONT_FAMILY,
            "font.sans-serif": StyleConfig.FONT_SANS_SERIF,
            "font.size": StyleConfig.FONT_SIZE,  # 8pt is typical Nature standard
            "axes.titlesize": StyleConfig.TITLE_SIZE,  # Panel title (bold)
            "axes.labelsize": StyleConfig.LABEL_SIZE,  # Axis labels (X/Y)
            "xtick.labelsize": StyleConfig.TICK_SIZE,  # Tick values
            "ytick.labelsize": StyleConfig.TICK_SIZE,
            "legend.fontsize": StyleConfig.LEGEND_SIZE,
            "legend.title_fontsize": StyleConfig.LEGEND_TITLE_SIZE,
            # Line widths and markers
            "lines.linewidth": 1.2,
            "lines.markersize": 4,
            "axes.linewidth": 0.8,  # Axis spine thickness
            # Grid settings
            "axes.grid": False,
            "grid.color": StyleConfig.GRAY_LIGHT,
            "grid.linestyle": "--",
            "grid.linewidth": 0.5,
            "grid.alpha": 0.5,
            # Minimalist axis spines (remove top and right)
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.spines.left": True,
            "axes.spines.bottom": True,
            # Tick settings pointing outwards
            "xtick.direction": "out",
            "ytick.direction": "out",
            "xtick.major.width": 0.8,
            "ytick.major.width": 0.8,
            "xtick.major.size": 3.5,
            "ytick.major.size": 3.5,
            # Vector and rendering settings
            "svg.fonttype": "none",  # Editable text in SVG
            "pdf.fonttype": 42,  # Editable TrueType text in PDF
            "savefig.dpi": 300,  # High resolution standard
            "savefig.bbox": "tight",  # Prevent clipping of labels
            "savefig.transparent": False,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
        }
    )


def save_pub_py(fig, filename, dpi=600):
    """
    Save the figure in vector (PDF, SVG) and submission-ready raster (TIFF) formats.
    """
    # Save editable vector formats
    fig.savefig(f"{filename}.pdf", bbox_inches="tight", transparent=True)
    fig.savefig(f"{filename}.svg", bbox_inches="tight", transparent=True)
    # Save high-resolution publication raster format
    fig.savefig(f"{filename}.tiff", dpi=dpi, bbox_inches="tight", transparent=False)
    # Save quick-preview PNG format
    fig.savefig(f"{filename}.png", dpi=300, bbox_inches="tight", transparent=False)
    print(f"Success! Data written to: {filename}.{{pdf,svg,tiff,png}}")


def apply_significance(ax, x1, x2, y, h, text, color=None):
    """Helper to draw beautiful statistical significance bracket bars."""
    if color is None:
        color = StyleConfig.GRAY_DARK
    ax.plot([x1, x1, x2, x2], [y, y + h, y + h, y], lw=0.8, c=color)
    ax.text(
        (x1 + x2) * 0.5,
        y + h,
        text,
        ha="center",
        va="bottom",
        color=color,
        fontsize=8,
        fontweight="bold",
    )
