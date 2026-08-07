import subprocess
import os
import sys

def run_gmx_cmd(cmd_list, input_str=None):
    """Run a GROMACS command with optional standard input."""
    print(f"Running: {' '.join(cmd_list)}")
    try:
        proc = subprocess.run(
            cmd_list, 
            input=input_str, 
            text=True, 
            capture_output=True, 
            check=True
        )
        return proc.stdout
    except subprocess.CalledProcessError as e:
        print(f"FAILED: {' '.join(cmd_list)}", file=sys.stderr)
        print(f"Error Output:\n{e.stderr}", file=sys.stderr)
        raise

def run_basic_pipeline(tpr_file, xtc_file, outdir="analysis_out"):
    """
    Executes the standard Basic Reporting pipeline (Tier 1 + Tier 3 Hbonds).
    """
    os.makedirs(outdir, exist_ok=True)
    
    # 1. PBC Correction (Center Protein and Output System)
    xtc_pbc = os.path.join(outdir, "md_fit.xtc")
    print("\n--- 1. PBC Correction ---")
    if not os.path.exists(xtc_pbc):
        # Center on Protein, output System
        run_gmx_cmd(["gmx", "trjconv", "-s", tpr_file, "-f", xtc_file, "-o", xtc_pbc, "-pbc", "mol", "-center"], "Protein\nSystem\n")
    else:
        print(f"Skipping PBC correction, {xtc_pbc} already exists.")

    # 2. RMSD (Backbone against Backbone)
    rmsd_out = os.path.join(outdir, "rmsd.xvg")
    print("\n--- 2. RMSD ---")
    if not os.path.exists(rmsd_out):
        run_gmx_cmd(["gmx", "rms", "-s", tpr_file, "-f", xtc_pbc, "-o", rmsd_out, "-tu", "ns"], "Backbone\nBackbone\n")

    # 3. RMSF (C-alpha)
    rmsf_out = os.path.join(outdir, "rmsf.xvg")
    print("\n--- 3. RMSF ---")
    if not os.path.exists(rmsf_out):
        run_gmx_cmd(["gmx", "rmsf", "-s", tpr_file, "-f", xtc_pbc, "-o", rmsf_out, "-res"], "C-alpha\n")

    # 4. Radius of Gyration
    rg_out = os.path.join(outdir, "rg.xvg")
    print("\n--- 4. Radius of Gyration ---")
    if not os.path.exists(rg_out):
        run_gmx_cmd(["gmx", "gyrate", "-s", tpr_file, "-f", xtc_pbc, "-o", rg_out], "Protein\n")

    # 5. SASA
    sasa_out = os.path.join(outdir, "sasa.xvg")
    print("\n--- 5. SASA ---")
    if not os.path.exists(sasa_out):
        run_gmx_cmd(["gmx", "sasa", "-s", tpr_file, "-f", xtc_pbc, "-o", sasa_out], "Protein\n")

    # 6. Hydrogen Bonds
    hbond_out = os.path.join(outdir, "hbonds.xvg")
    print("\n--- 6. Hydrogen Bonds ---")
    if not os.path.exists(hbond_out):
        # Default to Protein-Protein internal hbonds for single system QC
        run_gmx_cmd(["gmx", "hbond", "-s", tpr_file, "-f", xtc_pbc, "-num", hbond_out], "Protein\nProtein\n")

    # 7. DSSP (Secondary Structure)
    dssp_out = os.path.join(outdir, "dssp.dat")
    print("\n--- 7. DSSP ---")
    if not os.path.exists(dssp_out):
        # GROMACS 2023.4 replaces deprecated do_dssp with built-in dssp.
        try:
            run_gmx_cmd(["gmx", "dssp", "-s", tpr_file, "-f", xtc_pbc, "-o", dssp_out], "Protein\n")
        except Exception:
            print("Warning: GROMACS DSSP calculation failed; basic QC remains available without secondary-structure output.", file=sys.stderr)

    print(f"\n✅ Basic Analysis Pipeline Complete! Files saved to '{outdir}'")
    print("Next step: Pass these files to the md-simulation-plotting skill.")
