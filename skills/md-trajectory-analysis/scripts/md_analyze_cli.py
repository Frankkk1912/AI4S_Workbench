#!/usr/bin/env python3
import argparse
import sys
from auto_index import generate_default_index
from basic_pipeline import run_basic_pipeline
from advanced_pipeline import run_advanced_fel, run_advanced_network, run_advanced_mmpbsa

def main():
    parser = argparse.ArgumentParser(
        description="Automated MD Trajectory Analysis (Producer for md-simulation-plotting)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # --- Basic Pipeline ---
    p_basic = subparsers.add_parser("basic", help="Run automated basic reporting (PBC, RMSD, RMSF, Rg, SASA, DSSP, Hbonds)")
    p_basic.add_argument("--tpr", required=True, help="Input .tpr file")
    p_basic.add_argument("--xtc", required=True, help="Input .xtc file (raw, without PBC fix)")
    p_basic.add_argument("--outdir", default="analysis_out", help="Output directory for generated .xvg/.xpm files")
    
    # --- Advanced: FEL ---
    p_fel = subparsers.add_parser("advanced-fel", help="Run advanced PCA and Covariance (FEL) analysis")
    p_fel.add_argument("--tpr", required=True, help="Input .tpr file")
    p_fel.add_argument("--xtc", required=True, help="Input .xtc file (MUST be PBC fixed)")
    p_fel.add_argument("--outdir", default="analysis_out", help="Output directory")
    
    # --- Advanced: Network ---
    p_net = subparsers.add_parser("advanced-network", help="Run MDAnalysis DCCM and Contact Map")
    p_net.add_argument("--tpr", required=True, help="Input .tpr file")
    p_net.add_argument("--xtc", required=True, help="Input .xtc file (MUST be PBC fixed)")
    p_net.add_argument("--outdir", default="analysis_out", help="Output directory")

    # --- Advanced: MMPBSA ---
    p_mmpbsa = subparsers.add_parser("advanced-mmpbsa", help="Setup gmx_MMPBSA calculation")
    p_mmpbsa.add_argument("--tpr", required=True, help="Input .tpr file")
    p_mmpbsa.add_argument("--xtc", required=True, help="Input .xtc file (MUST be PBC fixed)")
    p_mmpbsa.add_argument("--top", required=True, help="Input .top file")
    p_mmpbsa.add_argument("--outdir", default="analysis_out", help="Output directory")

    args = parser.parse_args()
    
    # Execute commands
    try:
        if args.command == "basic":
            generate_default_index(args.tpr)
            run_basic_pipeline(args.tpr, args.xtc, args.outdir)
        elif args.command == "advanced-fel":
            run_advanced_fel(args.tpr, args.xtc, args.outdir)
        elif args.command == "advanced-network":
            run_advanced_network(args.tpr, args.xtc, args.outdir)
        elif args.command == "advanced-mmpbsa":
            run_advanced_mmpbsa(args.tpr, args.xtc, args.top, args.outdir)
    except Exception as e:
        print(f"\nExecution Failed: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
