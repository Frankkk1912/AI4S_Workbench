import matplotlib.pyplot as plt
import numpy as np
from scipy.stats import gaussian_kde
import md_style
import parser_gmx

def plot_tier5_geometry(sys1_dist_xvg, sys2_dist_xvg=None, output_name="tier5_geometry", 
                        sys1_label="System 1", sys2_label="System 2", metric_name="Distance", unit="nm"):
    """
    Plot targeted density distributions for a specific structural parameter.
    Supports single-system mode.
    """
    is_single = (sys2_dist_xvg is None)
    md_style.set_style()
    
    t1, val1 = parser_gmx.read_xvg(sys1_dist_xvg, [0, 1])
    kde1 = gaussian_kde(val1)
    
    if not is_single:
        t2, val2 = parser_gmx.read_xvg(sys2_dist_xvg, [0, 1])
        kde2 = gaussian_kde(val2)
        x_min = min(val1.min(), val2.min())
        x_max = max(val1.max(), val2.max())
    else:
        x_min = val1.min()
        x_max = val1.max()
        
    x_range = np.linspace(x_min, x_max, 500)
    y1 = kde1(x_range)
    
    fig, axes = plt.subplots(1, 2, figsize=(6.8, 2.5), gridspec_kw={'width_ratios': [2, 1]})
    plt.subplots_adjust(wspace=0.3)
    
    # 1. Timeline scatter/line
    ax1 = axes[0]
    stride1 = max(1, len(t1) // 1000)
    ax1.plot(t1[::stride1], val1[::stride1], color=md_style.StyleConfig.SYS1_COLOR, alpha=0.3, lw=0.5)
    
    sm1 = parser_gmx.convolve_smooth(val1, 50)
    ax1.plot(t1[49:], sm1, color=md_style.StyleConfig.SYS1_COLOR, lw=1.2, label=sys1_label)
    
    if not is_single:
        stride2 = max(1, len(t2) // 1000)
        ax1.plot(t2[::stride2], val2[::stride2], color=md_style.StyleConfig.SYS2_COLOR, alpha=0.3, lw=0.5)
        sm2 = parser_gmx.convolve_smooth(val2, 50)
        ax1.plot(t2[49:], sm2, color=md_style.StyleConfig.SYS2_COLOR, lw=1.2, label=sys2_label)
    
    ax1.set_xlabel("Time (ns)")
    ax1.set_ylabel(f"{metric_name} ({unit})")
    ax1.set_title("A. Metric Timeline", fontweight='bold', loc='left')
    ax1.legend(loc='best', frameon=False)
    
    # 2. KDE Density
    ax2 = axes[1]
    ax2.fill_between(x_range, y1, alpha=0.2, color=md_style.StyleConfig.SYS1_COLOR)
    ax2.plot(x_range, y1, color=md_style.StyleConfig.SYS1_COLOR, lw=1.5, label=sys1_label)
    ax2.axvline(val1.mean(), color=md_style.StyleConfig.SYS1_COLOR, ls='--', lw=1.0)
    
    if not is_single:
        y2 = kde2(x_range)
        ax2.fill_between(x_range, y2, alpha=0.2, color=md_style.StyleConfig.SYS2_COLOR)
        ax2.plot(x_range, y2, color=md_style.StyleConfig.SYS2_COLOR, lw=1.5, label=sys2_label)
        ax2.axvline(val2.mean(), color=md_style.StyleConfig.SYS2_COLOR, ls='--', lw=1.0)
    
    ax2.set_xlabel(f"{metric_name} ({unit})")
    ax2.set_ylabel("Probability Density")
    ax2.set_title("B. Population Shift", fontweight='bold', loc='left')
    
    md_style.save_pub_py(fig, output_name)
    plt.close(fig)
