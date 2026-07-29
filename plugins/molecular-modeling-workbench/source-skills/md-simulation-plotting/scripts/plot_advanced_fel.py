import matplotlib.pyplot as plt
import md_style
import numpy as np
import parser_gmx


def calculate_fel(pc1, pc2, temp=300.0, grid_size=100):
    """Calculate Free Energy Landscape (kcal/mol) from PCA 2D projections."""
    k_B = 0.0019872041  # kcal / (mol K)

    # Create 2D histogram
    H, xedges, yedges = np.histogram2d(pc1, pc2, bins=grid_size)

    # Calculate free energy
    H = H.T  # Transpose to match x,y orientation
    prob = H / np.sum(H)
    prob[prob == 0] = np.nan  # avoid log(0)

    F = -k_B * temp * np.log(prob)
    F = F - np.nanmin(F)  # Shift minimum to 0

    # Create grid centers
    xc = (xedges[:-1] + xedges[1:]) / 2
    yc = (yedges[:-1] + yedges[1:]) / 2
    X, Y = np.meshgrid(xc, yc)

    return X, Y, F


def plot_tier2_fel(
    sys1_pca,
    sys2_pca=None,
    output_name="tier2_fel",
    sys1_label="System 1",
    sys2_label="System 2",
    temp=300.0,
):
    """
    Generate Free Energy Landscape (FEL) plots from 2D PCA projections.
    """
    is_single = sys2_pca is None
    md_style.set_style()

    # Read PCA projection (assumes format: PC1, PC2)
    pc1_1, pc2_1 = parser_gmx.read_xvg(sys1_pca, [0, 1])
    X1, Y1, F1 = calculate_fel(pc1_1, pc2_1, temp)

    if not is_single:
        pc1_2, pc2_2 = parser_gmx.read_xvg(sys2_pca, [0, 1])
        X2, Y2, F2 = calculate_fel(pc1_2, pc2_2, temp)

    n_cols = 1 if is_single else 2
    fig, axes = plt.subplots(1, n_cols, figsize=(3.5 * n_cols, 3.5), squeeze=False)
    plt.subplots_adjust(wspace=0.3)

    # Fixed global scale for objective scientific comparison (prevents false illusion of high energy)
    max_level = 5.0

    fill_levels = np.linspace(0, max_level, 100)  # Smooth continuous gradient
    line_levels = np.linspace(0, max_level, 6)  # Lines at 0, 1, 2, 3, 4, 5
    # Sequential, colorblind-safe colormap: FEL is a single-ended quantity
    # (0 = basin), so a diverging map like RdBu_r would imply a false midpoint.
    cmap = "viridis"

    # System 1 FEL
    ax1 = axes[0, 0]
    c1 = ax1.contourf(X1, Y1, F1, levels=fill_levels, cmap=cmap, extend="max")
    ax1.contour(
        X1, Y1, F1, levels=line_levels, colors="white", alpha=0.3, linewidths=0.5
    )

    # Mark global minimum
    min_idx = np.unravel_index(np.nanargmin(F1), F1.shape)
    ax1.plot(
        X1[min_idx],
        Y1[min_idx],
        "*",
        color="white",
        markersize=8,
        markeredgecolor="black",
    )

    ax1.set_xlabel("PC1")
    ax1.set_ylabel("PC2")
    title_a = "A." if not is_single else ""
    ax1.set_title(f"{title_a} {sys1_label} FEL", fontweight="bold", loc="left")

    # System 2 FEL
    if not is_single:
        ax2 = axes[0, 1]
        ax2.contourf(X2, Y2, F2, levels=fill_levels, cmap=cmap, extend="max")
        ax2.contour(
            X2, Y2, F2, levels=line_levels, colors="white", alpha=0.3, linewidths=0.5
        )

        min_idx2 = np.unravel_index(np.nanargmin(F2), F2.shape)
        ax2.plot(
            X2[min_idx2],
            Y2[min_idx2],
            "*",
            color="white",
            markersize=8,
            markeredgecolor="black",
        )

        ax2.set_xlabel("PC1")
        ax2.set_ylabel("PC2")
        ax2.set_title(f"B. {sys2_label} FEL", fontweight="bold", loc="left")

    # Shared colorbar
    cbar_ax = fig.add_axes([0.92, 0.15, 0.02, 0.7])
    cbar = fig.colorbar(c1, cax=cbar_ax, ticks=[0, 1, 2, 3, 4, 5])
    cbar.set_label("Free Energy (kcal/mol)")

    md_style.save_pub_py(fig, output_name)
    plt.close(fig)
