import csv

import matplotlib.pyplot as plt
import md_style
import numpy as np


def read_matrix_csv(filepath):
    """Read a CSV/TXT square matrix into a numpy array."""
    data = []
    with open(filepath) as f:
        # Check if comma or space separated
        first_line = f.readline()
        delimiter = "," if "," in first_line else None
        f.seek(0)

        reader = (
            csv.reader(f, delimiter=delimiter)
            if delimiter
            else csv.reader(f, delimiter=" ")
        )
        for row in reader:
            if not row or row[0].startswith("#"):
                continue
            # Filter out empty strings from multiple spaces
            row_vals = [float(v) for v in row if v.strip() != ""]
            data.append(row_vals)
    return np.array(data)


def plot_tier4_network(
    sys1_contact,
    sys2_contact,
    sys1_dccm,
    sys2_dccm,
    output_name="tier4_network",
    sys1_label="System 1",
    sys2_label="System 2",
    network_xlabel="Residue i",
    network_ylabel="Residue j",
):
    """
    Generate Tier 4: Global Dynamics Network.
    If sys2_contact or sys2_dccm is None, it plots a 1x2 panel instead of 2x2.
    """
    is_single = (sys2_contact is None) or (sys2_dccm is None)
    md_style.set_style()

    mat1_c = read_matrix_csv(sys1_contact)
    mat1_d = read_matrix_csv(sys1_dccm)

    if not is_single:
        mat2_c = read_matrix_csv(sys2_contact)
        mat2_d = read_matrix_csv(sys2_dccm)

    if is_single:
        fig, axes = plt.subplots(
            1,
            2,
            figsize=md_style.StyleConfig.FIG_SIZE_NETWORK_2PANEL,
            layout="constrained",
        )
        ax_c1 = axes[0]
        ax_d1 = axes[1]
    else:
        fig, axes = plt.subplots(
            2,
            2,
            figsize=md_style.StyleConfig.FIG_SIZE_NETWORK_4PANEL,
            layout="constrained",
        )
        ax_c1 = axes[0, 0]
        ax_c2 = axes[0, 1]
        ax_d1 = axes[1, 0]
        ax_d2 = axes[1, 1]

    # ---------------------------------------------------------
    # Panel(s): Contact Maps (Top row, or left)
    # ---------------------------------------------------------
    cmap_contact = "Blues"

    im_c1 = ax_c1.imshow(mat1_c, cmap=cmap_contact, origin="lower", vmin=0, vmax=1)
    ax_c1.set_title(f"A. {sys1_label} Contact Map", fontweight="bold", loc="left")
    ax_c1.set_xlabel(network_xlabel)
    ax_c1.set_ylabel(network_ylabel)
    fig.colorbar(im_c1, ax=ax_c1, fraction=0.046, pad=0.04, label="Contact Probability")

    if not is_single:
        im_c2 = ax_c2.imshow(mat2_c, cmap=cmap_contact, origin="lower", vmin=0, vmax=1)
        ax_c2.set_title(f"B. {sys2_label} Contact Map", fontweight="bold", loc="left")
        ax_c2.set_xlabel(network_xlabel)
        ax_c2.set_ylabel(network_ylabel)
        fig.colorbar(
            im_c2, ax=ax_c2, fraction=0.046, pad=0.04, label="Contact Probability"
        )

    # ---------------------------------------------------------
    # Panel(s): DCCM Matrices (Bottom row, or right)
    # ---------------------------------------------------------
    cmap_dccm = "RdBu_r"

    title_d1 = "B." if is_single else "C."
    im_d1 = ax_d1.imshow(mat1_d, cmap=cmap_dccm, origin="lower", vmin=-1, vmax=1)
    ax_d1.set_title(f"{title_d1} {sys1_label} DCCM", fontweight="bold", loc="left")
    ax_d1.set_xlabel(network_xlabel)
    ax_d1.set_ylabel(network_ylabel)
    fig.colorbar(im_d1, ax=ax_d1, fraction=0.046, pad=0.04, label="Cross-Correlation")

    if not is_single:
        im_d2 = ax_d2.imshow(mat2_d, cmap=cmap_dccm, origin="lower", vmin=-1, vmax=1)
        ax_d2.set_title(f"D. {sys2_label} DCCM", fontweight="bold", loc="left")
        ax_d2.set_xlabel(network_xlabel)
        ax_d2.set_ylabel(network_ylabel)
        fig.colorbar(
            im_d2, ax=ax_d2, fraction=0.046, pad=0.04, label="Cross-Correlation"
        )

    md_style.save_pub_py(fig, output_name)
    plt.close(fig)
