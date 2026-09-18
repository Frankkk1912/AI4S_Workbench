import csv

import matplotlib.pyplot as plt
import md_style
import numpy as np
import parser_gmx


def read_mmpbsa_csv(filepath):
    """Parse simplified MM/PBSA per-residue decomposition CSV."""
    residues = []
    dg = []
    sem = []
    with open(filepath) as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            residues.append(row[0])
            dg.append(float(row[1]))
            sem.append(float(row[2]) if len(row) > 2 else 0.0)
    return residues, np.array(dg), np.array(sem)


def plot_tier3_energy(
    sys1_energy,
    sys2_energy,
    sys1_hb,
    sys2_hb,
    output_name="tier3_energy",
    sys1_label="System 1",
    sys2_label="System 2",
    eq_start_ns=20,
):
    """
    Generate Tier 3: Interaction Energy & Kinetics plots.
    Supports single-system mode if sys2 files are None.
    """
    is_single = sys2_hb is None
    has_energy = sys1_energy is not None
    md_style.set_style()

    # Read H-bond Data
    t1_hb, y1_hb = parser_gmx.read_xvg(sys1_hb, [0, 1])
    if t1_hb.max() > 1000:
        t1_hb /= 1000
    if not is_single:
        t2_hb, y2_hb = parser_gmx.read_xvg(sys2_hb, [0, 1])
        if t2_hb.max() > 1000:
            t2_hb /= 1000

    if has_energy:
        # Read Energy Data
        res1, dg1, sem1 = read_mmpbsa_csv(sys1_energy)
        if sys2_energy is not None:
            res2, dg2, sem2 = read_mmpbsa_csv(sys2_energy)
            is_energy_single = False
        else:
            is_energy_single = True

        fig, axes = plt.subplots(
            1,
            2,
            figsize=md_style.StyleConfig.FIG_SIZE_HBONDS_2PANEL,
            gridspec_kw={"width_ratios": [1.5, 1]},
        )
        plt.subplots_adjust(wspace=0.3, bottom=0.2)

        # Panel A: MM/PBSA Decomposition Bar Chart
        ax = axes[0]
        x = np.arange(len(res1))
        if is_energy_single:
            width = 0.6
            ax.bar(
                x,
                dg1,
                width,
                yerr=sem1,
                capsize=2,
                label=sys1_label,
                color=md_style.StyleConfig.SYS1_COLOR,
                edgecolor="white",
                linewidth=0.5,
            )
        else:
            width = 0.35
            ax.bar(
                x - width / 2,
                dg1,
                width,
                yerr=sem1,
                capsize=2,
                label=sys1_label,
                color=md_style.StyleConfig.SYS1_COLOR,
                edgecolor="white",
                linewidth=0.5,
            )
            x2 = np.arange(len(res2))
            ax.bar(
                x2 + width / 2,
                dg2,
                width,
                yerr=sem2,
                capsize=2,
                label=sys2_label,
                color=md_style.StyleConfig.SYS2_COLOR,
                edgecolor="white",
                linewidth=0.5,
            )

        ax.axhline(0, color=md_style.StyleConfig.GRAY_DARK, lw=0.6, ls="-")
        ax.set_xticks(x)
        ax.set_xticklabels(res1, rotation=30, ha="right")
        ax.set_ylabel(r"$\Delta$G Contribution (kcal/mol)")
        ax.set_title(
            "A. Per-Residue Binding Energy Breakdown", fontweight="bold", loc="left"
        )
        ax.legend(loc="upper right", frameon=False)

        ax_hb = axes[1]
    else:
        # Fallback to 1x1 H-bond plot
        fig, ax_hb = plt.subplots(figsize=md_style.StyleConfig.FIG_SIZE_HBONDS_SINGLE)
        plt.subplots_adjust(bottom=0.2)

    # Panel B: Hydrogen Bond Kinetics
    ax = ax_hb
    lengths = [len(t1_hb)] + ([] if is_single else [len(t2_hb)])
    w = max(1, min(50, *lengths))
    y1_hb_sm = parser_gmx.convolve_smooth(y1_hb, w)
    mask1_hb = t1_hb >= eq_start_ns
    mean1_hb = y1_hb[mask1_hb].mean() if mask1_hb.any() else y1_hb.mean()

    ax.plot(t1_hb, y1_hb, color=md_style.StyleConfig.SYS1_COLOR, alpha=0.15, lw=0.4)
    ax.plot(
        t1_hb[w - 1 :],
        y1_hb_sm,
        color=md_style.StyleConfig.SYS1_COLOR,
        lw=1.2,
        label=f"{sys1_label} (mean={mean1_hb:.1f})",
    )

    if not is_single:
        y2_hb_sm = parser_gmx.convolve_smooth(y2_hb, w)
        mask2_hb = t2_hb >= eq_start_ns
        mean2_hb = y2_hb[mask2_hb].mean() if mask2_hb.any() else y2_hb.mean()
        ax.plot(t2_hb, y2_hb, color=md_style.StyleConfig.SYS2_COLOR, alpha=0.15, lw=0.4)
        ax.plot(
            t2_hb[w - 1 :],
            y2_hb_sm,
            color=md_style.StyleConfig.SYS2_COLOR,
            lw=1.2,
            label=f"{sys2_label} (mean={mean2_hb:.1f})",
        )

    ax.set_xlabel("Time (ns)")
    ax.set_ylabel("Number of H-bonds")
    ax.set_title(
        "B. Interfacial Hydrogen Bonds" if has_energy else "Interfacial Hydrogen Bonds",
        fontweight="bold",
        loc="left",
    )
    ax.legend(loc="lower right", frameon=False)

    md_style.save_pub_py(fig, output_name)
    plt.close(fig)
