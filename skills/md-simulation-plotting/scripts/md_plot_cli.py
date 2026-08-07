#!/usr/bin/env python3
import argparse
import sys
import os
from pathlib import Path

# Import our custom style and plotting modules
import md_style
from plot_basic_qc import plot_tier1_qc as plot_basic_qc
from plot_basic_dssp import plot_tier1_dssp as plot_basic_dssp
from plot_basic_energy import plot_tier3_energy as plot_basic_energy
from plot_advanced_fel import plot_tier2_fel as plot_advanced_fel
from plot_advanced_network import plot_tier4_network as plot_advanced_network
from plot_advanced_geometry import plot_tier5_geometry as plot_advanced_geometry
from plot_advanced_rdf import plot_tier5_rdf as plot_advanced_rdf

def resolve_file(dir_path, filename):
    """Helper to safely resolve a file path from a directory."""
    if not dir_path:
        return None
    p = os.path.join(dir_path, filename)
    return p if os.path.exists(p) else None

def main():
    parser = argparse.ArgumentParser(
        description="Publication-grade Molecular Dynamics Plotting (Basic vs Advanced Pipeline).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument("--style-config", type=str, help="Path to JSON configuration file to override default colors/fonts.")
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    def add_common_args(p):
        p.add_argument("--sys1-label", default="System 1", help="Label for System 1")
        p.add_argument("--sys2-label", default="System 2", help="Label for System 2")
        p.add_argument("--output", required=True, help="Output file prefix")

    # --- Basic Pipeline (QC, Hbonds, DSSP) ---
    p_basic = subparsers.add_parser("basic", help="Plot all standard reporting figures (QC, Hbonds, DSSP) automatically")
    p_basic.add_argument("--sys1-dir", required=True, help="Directory containing basic analysis outputs for System 1")
    p_basic.add_argument("--sys2-dir", default=None, help="Directory containing basic analysis outputs for System 2")
    p_basic.add_argument("--eq-start-ns", type=float, default=20.0, help="Equilibration start time in ns")
    p_basic.add_argument("--rmsd-ylabel", default="Backbone RMSD (nm)", help="Y-axis label for RMSD")
    p_basic.add_argument("--rmsf-ylabel", default="Cα RMSF (nm)", help="Y-axis label for RMSF")
    p_basic.add_argument("--rmsf-xlabel", default="Residue Number", help="X-axis label for RMSF")
    add_common_args(p_basic)

    # --- Advanced: FEL ---
    p_fel = subparsers.add_parser("advanced-fel", help="Plot 2D Free Energy Landscape (PCA projections)")
    p_fel.add_argument("--sys1-pca", required=True, help="System 1 pca_2dproj.xvg")
    p_fel.add_argument("--sys2-pca", default=None, help="System 2 pca_2dproj.xvg")
    p_fel.add_argument("--temp", type=float, default=300.0, help="Simulation temperature (K)")
    add_common_args(p_fel)
    
    # --- Advanced: Network ---
    p_net = subparsers.add_parser("advanced-network", help="Plot Contact Maps and DCCM matrices")
    p_net.add_argument("--sys1-contact", required=True, help="System 1 contact.csv")
    p_net.add_argument("--sys2-contact", default=None, help="System 2 contact.csv")
    p_net.add_argument("--sys1-dccm", required=True, help="System 1 dccm.csv")
    p_net.add_argument("--sys2-dccm", default=None, help="System 2 dccm.csv")
    p_net.add_argument("--network-xlabel", default="Residue i", help="X-axis label")
    p_net.add_argument("--network-ylabel", default="Residue j", help="Y-axis label")
    add_common_args(p_net)

    # --- Advanced: Geometry ---
    p_geom = subparsers.add_parser("advanced-geometry", help="Plot targeted Distance/Angle density distributions")
    p_geom.add_argument("--sys1-dist", required=True, help="System 1 distance/angle XVG")
    p_geom.add_argument("--sys2-dist", default=None, help="System 2 distance/angle XVG")
    p_geom.add_argument("--metric-name", default="Distance", help="Name of the metric")
    p_geom.add_argument("--unit", default="nm", help="Unit of the metric")
    add_common_args(p_geom)

    # --- Advanced: RDF ---
    p_rdf = subparsers.add_parser("advanced-rdf", help="Plot Radial Distribution Function g(r)")
    p_rdf.add_argument("--sys1-rdf", required=True, help="System 1 RDF XVG")
    p_rdf.add_argument("--sys2-rdf", default=None, help="System 2 RDF XVG")
    p_rdf.add_argument("--target-name", default="Target", help="Name of target molecule")
    add_common_args(p_rdf)

    args = parser.parse_args()
    output_parent = Path(args.output).expanduser().parent
    if output_parent != Path("."):
        output_parent.mkdir(parents=True, exist_ok=True)
    
    if args.style_config:
        try:
            md_style.load_style_config(args.style_config)
            print(f"Loaded custom style config from {args.style_config}")
        except Exception as e:
            print(f"Warning: Failed to load style config. {e}", file=sys.stderr)

    try:
        if args.command == "basic":
            print(f"--- Running Basic Plotting Pipeline ---")
            
            # Extract files from directories
            s1_rmsd = resolve_file(args.sys1_dir, "rmsd.xvg")
            s1_rmsf = resolve_file(args.sys1_dir, "rmsf.xvg")
            s1_rg   = resolve_file(args.sys1_dir, "rg.xvg")
            s1_sasa = resolve_file(args.sys1_dir, "sasa.xvg")
            s1_hb   = resolve_file(args.sys1_dir, "hbonds.xvg")
            s1_dssp = resolve_file(args.sys1_dir, "dssp.xpm") or resolve_file(args.sys1_dir, "dssp.dat")
            
            s2_rmsd = resolve_file(args.sys2_dir, "rmsd.xvg")
            s2_rmsf = resolve_file(args.sys2_dir, "rmsf.xvg")
            s2_rg   = resolve_file(args.sys2_dir, "rg.xvg")
            s2_sasa = resolve_file(args.sys2_dir, "sasa.xvg")
            s2_hb   = resolve_file(args.sys2_dir, "hbonds.xvg")
            s2_dssp = resolve_file(args.sys2_dir, "dssp.xpm") or resolve_file(args.sys2_dir, "dssp.dat")
            
            # 1. 4-Panel QC
            if all([s1_rmsd, s1_rmsf, s1_rg, s1_sasa]):
                print(">> Plotting 4-Panel QC...")
                plot_basic_qc(s1_rmsd, s2_rmsd, s1_rmsf, s2_rmsf, s1_rg, s2_rg, s1_sasa, s2_sasa,
                              f"{args.output}_qc_4panel", args.sys1_label, args.sys2_label, 
                              args.eq_start_ns, args.rmsd_ylabel, args.rmsf_ylabel, args.rmsf_xlabel)
            else:
                print(">> Missing some QC files (rmsd, rmsf, rg, sasa). Skipping 4-Panel QC.")
            
            # 2. Hydrogen Bonds
            if s1_hb:
                print(">> Plotting Hydrogen Bonds...")
                # We skip energy CSV since it's now advanced mmpbsa, but plot_basic_energy needs tweaking.
                # If we just pass None for energy, it falls back to 1x1 hbond plot.
                plot_basic_energy(None, None, s1_hb, s2_hb, f"{args.output}_hbonds", args.sys1_label, args.sys2_label, args.eq_start_ns)
            else:
                print(">> Missing hbonds.xvg. Skipping.")
                
            # 3. DSSP
            if s1_dssp:
                print(">> Plotting DSSP Heatmap...")
                plot_basic_dssp(s1_dssp, s2_dssp, f"{args.output}_dssp", args.sys1_label, args.sys2_label)
            else:
                print(">> Missing dssp.xpm. Skipping.")
                
            print("Basic Plotting Complete!")

        elif args.command == "advanced-fel":
            plot_advanced_fel(args.sys1_pca, args.sys2_pca, args.output, args.sys1_label, args.sys2_label, args.temp)
        elif args.command == "advanced-network":
            plot_advanced_network(args.sys1_contact, args.sys2_contact, args.sys1_dccm, args.sys2_dccm,
                                  args.output, args.sys1_label, args.sys2_label,
                                  args.network_xlabel, args.network_ylabel)
        elif args.command == "advanced-geometry":
            plot_advanced_geometry(args.sys1_dist, args.sys2_dist, args.output, args.sys1_label, args.sys2_label, args.metric_name, args.unit)
        elif args.command == "advanced-rdf":
            plot_advanced_rdf(args.sys1_rdf, args.sys2_rdf, args.output, args.sys1_label, args.sys2_label, args.target_name)
    except Exception as e:
        print(f"Error executing {args.command}: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
