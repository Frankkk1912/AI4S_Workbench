import matplotlib.pyplot as plt
import md_style
import parser_gmx


def plot_tier1_qc(
    sys1_rmsd,
    sys2_rmsd,
    sys1_rmsf,
    sys2_rmsf,
    sys1_rg,
    sys2_rg,
    sys1_sasa,
    sys2_sasa,
    output_name="tier1_stability_solvent",
    sys1_label="System 1",
    sys2_label="System 2",
    eq_start_ns=20,
    rmsd_ylabel="Backbone RMSD (nm)",
    rmsf_ylabel="Cα RMSF (nm)",
    rmsf_xlabel="Residue Number",
):
    """
    Generate publication-grade 4-panel linked Quality Control plots.
    Supports single-system mode if sys2 files are None.
    """
    is_single = sys2_rmsd is None
    md_style.set_style()

    # Parse System 1 data
    t1_rmsd, y1_rmsd = parser_gmx.read_xvg(sys1_rmsd, [0, 1])
    res1, y1_rmsf = parser_gmx.read_xvg(sys1_rmsf, [0, 1])
    t1_rg, y1_rg = parser_gmx.read_xvg(sys1_rg, [0, 1])
    t1_sasa, y1_sasa = parser_gmx.read_xvg(sys1_sasa, [0, 1])

    # Parse System 2 data if available
    if not is_single:
        t2_rmsd, y2_rmsd = parser_gmx.read_xvg(sys2_rmsd, [0, 1])
        res2, y2_rmsf = parser_gmx.read_xvg(sys2_rmsf, [0, 1])
        t2_rg, y2_rg = parser_gmx.read_xvg(sys2_rg, [0, 1])
        t2_sasa, y2_sasa = parser_gmx.read_xvg(sys2_sasa, [0, 1])
        # Convert ps to ns if needed
        if t2_rmsd.max() > 1000:
            t2_rmsd /= 1000
        if t2_rg.max() > 1000:
            t2_rg /= 1000
        if t2_sasa.max() > 1000:
            t2_sasa /= 1000

    # Convert ps to ns for System 1 if needed
    if t1_rmsd.max() > 1000:
        t1_rmsd /= 1000
    if t1_rg.max() > 1000:
        t1_rg /= 1000
    if t1_sasa.max() > 1000:
        t1_sasa /= 1000

    fig, axes = plt.subplots(2, 2, figsize=md_style.StyleConfig.FIG_SIZE_QC_4PANEL)
    plt.subplots_adjust(wspace=0.28, hspace=0.35)
    # Keep time and smoothed-data lengths aligned for short technical smoke runs.
    series_lengths = [len(t1_rmsd), len(t1_rg), len(t1_sasa)]
    if not is_single:
        series_lengths.extend([len(t2_rmsd), len(t2_rg), len(t2_sasa)])
    w = max(1, min(50, *series_lengths))

    # =========================================================================
    # Panel A: RMSD
    # =========================================================================
    ax = axes[0, 0]
    y1_sm = parser_gmx.convolve_smooth(y1_rmsd, w)
    t1_sm = t1_rmsd[w - 1 :] if len(t1_rmsd) >= w else t1_rmsd

    mask1 = t1_rmsd >= eq_start_ns
    mean1 = y1_rmsd[mask1].mean() if mask1.any() else y1_rmsd.mean()
    std1 = y1_rmsd[mask1].std() if mask1.any() else y1_rmsd.std()

    ax.fill_between(
        t1_rmsd,
        mean1 - std1,
        mean1 + std1,
        color=md_style.StyleConfig.SYS1_COLOR,
        alpha=0.12,
        zorder=1,
    )
    ax.plot(
        t1_sm,
        y1_sm,
        color=md_style.StyleConfig.SYS1_COLOR,
        lw=1.2,
        label=f"{sys1_label}: {mean1:.2f}±{std1:.2f} nm",
    )

    if not is_single:
        y2_sm = parser_gmx.convolve_smooth(y2_rmsd, w)
        t2_sm = t2_rmsd[w - 1 :] if len(t2_rmsd) >= w else t2_rmsd
        mask2 = t2_rmsd >= eq_start_ns
        mean2 = y2_rmsd[mask2].mean() if mask2.any() else y2_rmsd.mean()
        std2 = y2_rmsd[mask2].std() if mask2.any() else y2_rmsd.std()

        ax.fill_between(
            t2_rmsd,
            mean2 - std2,
            mean2 + std2,
            color=md_style.StyleConfig.SYS2_COLOR,
            alpha=0.12,
            zorder=1,
        )
        ax.plot(
            t2_sm,
            y2_sm,
            color=md_style.StyleConfig.SYS2_COLOR,
            lw=1.2,
            label=f"{sys2_label}: {mean2:.2f}±{std2:.2f} nm",
        )

    ax.set_xlabel("Time (ns)")
    ax.set_ylabel(rmsd_ylabel)
    ax.set_title("A. Structural Deviation", fontweight="bold", loc="left")
    ax.legend(loc="lower right", frameon=False)

    # =========================================================================
    # Panel B: RMSF
    # =========================================================================
    ax = axes[0, 1]
    ax.plot(
        res1,
        y1_rmsf,
        color=md_style.StyleConfig.SYS1_COLOR,
        alpha=0.85,
        lw=0.8,
        label=sys1_label,
    )
    if not is_single:
        ax.plot(
            res2,
            y2_rmsf,
            color=md_style.StyleConfig.SYS2_COLOR,
            alpha=0.85,
            lw=0.8,
            label=sys2_label,
        )

    ax.set_xlabel(rmsf_xlabel)
    ax.set_ylabel(rmsf_ylabel)
    ax.set_title("B. Local Fluctuation (RMSF)", fontweight="bold", loc="left")
    ax.legend(loc="upper right", frameon=False)

    # =========================================================================
    # Panel C: Radius of Gyration (Rg)
    # =========================================================================
    ax = axes[1, 0]
    y1_rg_sm = parser_gmx.convolve_smooth(y1_rg, w)
    mask1_rg = t1_rg >= eq_start_ns
    mean1_rg = y1_rg[mask1_rg].mean() if mask1_rg.any() else y1_rg.mean()
    std1_rg = y1_rg[mask1_rg].std() if mask1_rg.any() else y1_rg.std()

    ax.fill_between(
        t1_rg,
        mean1_rg - std1_rg,
        mean1_rg + std1_rg,
        color=md_style.StyleConfig.SYS1_COLOR,
        alpha=0.12,
    )
    ax.plot(
        t1_rg[w - 1 :],
        y1_rg_sm,
        color=md_style.StyleConfig.SYS1_COLOR,
        lw=1.2,
        label=f"{sys1_label}: {mean1_rg:.2f} nm",
    )

    if not is_single:
        y2_rg_sm = parser_gmx.convolve_smooth(y2_rg, w)
        mask2_rg = t2_rg >= eq_start_ns
        mean2_rg = y2_rg[mask2_rg].mean() if mask2_rg.any() else y2_rg.mean()
        std2_rg = y2_rg[mask2_rg].std() if mask2_rg.any() else y2_rg.std()

        ax.fill_between(
            t2_rg,
            mean2_rg - std2_rg,
            mean2_rg + std2_rg,
            color=md_style.StyleConfig.SYS2_COLOR,
            alpha=0.12,
        )
        ax.plot(
            t2_rg[w - 1 :],
            y2_rg_sm,
            color=md_style.StyleConfig.SYS2_COLOR,
            lw=1.2,
            label=f"{sys2_label}: {mean2_rg:.2f} nm",
        )

    ax.set_xlabel("Time (ns)")
    ax.set_ylabel("Radius of Gyration Rg (nm)")
    ax.set_title("C. Global Fold Compactness", fontweight="bold", loc="left")
    ax.legend(loc="lower right", frameon=False)

    # =========================================================================
    # Panel D: SASA
    # =========================================================================
    ax = axes[1, 1]
    y1_sasa_sm = parser_gmx.convolve_smooth(y1_sasa, w)

    ax.plot(
        t1_sasa[w - 1 :],
        y1_sasa_sm,
        color=md_style.StyleConfig.SYS1_COLOR,
        lw=1.2,
        label=sys1_label,
    )

    if not is_single:
        y2_sasa_sm = parser_gmx.convolve_smooth(y2_sasa, w)
        p_val = parser_gmx.block_average_welch(
            y1_sasa[t1_sasa >= eq_start_ns], y2_sasa[t2_sasa >= eq_start_ns]
        )
        stars = parser_gmx.get_p_value_stars(p_val)
        ax.plot(
            t2_sasa[w - 1 :],
            y2_sasa_sm,
            color=md_style.StyleConfig.SYS2_COLOR,
            lw=1.2,
            label=f"{sys2_label} (p={p_val:.2e} {stars})",
        )

    ax.set_xlabel("Time (ns)")
    ax.set_ylabel(r"SASA ($\AA^2$)")
    ax.set_title("D. Solvent Accessible Surface Area", fontweight="bold", loc="left")
    ax.legend(loc="upper right", frameon=False)

    md_style.save_pub_py(fig, output_name)
    plt.close(fig)
