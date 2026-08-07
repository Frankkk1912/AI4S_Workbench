import matplotlib.pyplot as plt
import numpy as np
import md_style
import parser_gmx

def plot_tier5_rdf(sys1_rdf_xvg, sys2_rdf_xvg=None, output_name="tier5_rdf", 
                   sys1_label="System 1", sys2_label="System 2", target_name="Target"):
    """
    Plot Radial Distribution Function g(r) for specific interactions.
    Supports single-system mode.
    """
    is_single = (sys2_rdf_xvg is None)
    md_style.set_style()
    
    r1, g1 = parser_gmx.read_xvg(sys1_rdf_xvg, [0, 1])
    
    fig, ax = plt.subplots(figsize=(4.0, 3.0))
    
    ax.plot(r1, g1, color=md_style.StyleConfig.SYS1_COLOR, lw=1.5, label=sys1_label)
    
    # Fill under the first peak
    max_idx1 = np.argmax(g1[:len(g1)//3]) if len(g1) > 10 else 0
    ax.axvline(r1[max_idx1], color=md_style.StyleConfig.SYS1_COLOR, ls=':', lw=1.0)
    
    max_r = r1.max()
    
    if not is_single:
        r2, g2 = parser_gmx.read_xvg(sys2_rdf_xvg, [0, 1])
        ax.plot(r2, g2, color=md_style.StyleConfig.SYS2_COLOR, lw=1.5, label=sys2_label)
        max_idx2 = np.argmax(g2[:len(g2)//3]) if len(g2) > 10 else 0
        ax.axvline(r2[max_idx2], color=md_style.StyleConfig.SYS2_COLOR, ls=':', lw=1.0)
        max_r = max(max_r, r2.max())
    
    ax.set_xlim(0, max_r * 0.8)
    ax.set_xlabel("Distance $r$ (nm)")
    ax.set_ylabel("Radial Distribution $g(r)$")
    ax.set_title(f"Targeted RDF: {target_name}", fontweight='bold', loc='left')
    ax.legend(loc='upper right', frameon=False)
    
    md_style.save_pub_py(fig, output_name)
    plt.close(fig)
