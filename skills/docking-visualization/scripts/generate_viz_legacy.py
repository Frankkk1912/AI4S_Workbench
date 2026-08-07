#!/usr/bin/env python3
import argparse
import os
import sys
import subprocess
import json
from collections import defaultdict

def detect_ligand(pdb_path):
    """Parses PDB to find the largest HETATM residue (ignoring solvent/ions)."""
    exclude_resnames = {"HOH", "WAT", "NA", "CL", "MG", "CA", "ZN", "K", "SO4", "PO4", "EDO", "GOL", "PEG"}
    ligand_counts = defaultdict(int)
    
    with open(pdb_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            if line.startswith("HETATM"):
                resname = line[17:20].strip()
                if resname not in exclude_resnames:
                    ligand_counts[resname] += 1
                    
    if not ligand_counts:
        return None, []
        
    sorted_ligands = sorted(ligand_counts.items(), key=lambda x: x[1], reverse=True)
    return sorted_ligands[0][0], [k for k, v in sorted_ligands]

def generate_chimerax_script(pdb_path, lig_name, output_dir):
    """Generates a customized ChimeraX python script for 3D rendering."""
    pdb_abs = os.path.abspath(pdb_path).replace("\\", "/")
    script_content = f"""# Auto-generated ChimeraX rendering script for {lig_name}
from chimerax.core.commands import run

def render():
    # 1. Load Model
    run(session, "open {pdb_abs}")
    run(session, "~select")
    run(session, "hide atoms")
    run(session, "show ribbons")
    run(session, "color protein white")
    
    # 2. Ligand
    ligand_sel = "resname {lig_name}"
    run(session, f"show {{ligand_sel}}")
    run(session, f"style {{ligand_sel}} stick")
    run(session, f"color {{ligand_sel}} magenta")
    run(session, f"color {{ligand_sel}} byhetero")
    
    # 3. Pocket Surface
    pocket_sel = f"(protein) & {{ligand_sel}} :<5.0"
    run(session, f"show {{pocket_sel}}")
    run(session, f"style {{pocket_sel}} stick")
    run(session, f"color {{pocket_sel}} cyan")
    run(session, f"color {{pocket_sel}} byhetero")
    
    run(session, f"surface {{pocket_sel}}")
    run(session, f"color {{pocket_sel}} cyan target s")
    run(session, f"transparency {{pocket_sel}} 60 target s")
    
    # 4. Global aesthetics
    run(session, "graphics silhouettes true width 1.5")
    run(session, "lighting soft")
    run(session, "set bgColor white")
    
    # Focus
    run(session, f"view {{ligand_sel}} | {{pocket_sel}}")
    run(session, "zoom 0.7")
    
    print("==================================================")
    print("Render script finished. You can now manually adjust")
    print("the camera angle, and type the following to save:")
    print("save figures/high_res.png width 1920 height 1080 supersample 3")
    print("==================================================")

render()
"""
    out_file = os.path.join(output_dir, f"render_3D_{lig_name}.py")
    with open(out_file, "w") as f:
        f.write(script_content)
    return out_file

def generate_2d_diagram(pdb_path, lig_name, output_dir):
    """Generates a ProLIF script and runs it to produce a 2D HTML diagram."""
    pdb_abs = os.path.abspath(pdb_path).replace("\\", "/")
    html_out = os.path.abspath(os.path.join(output_dir, f"2d_interaction_{lig_name}.html")).replace("\\", "/")
    
    # Create a runner script for ProLIF
    prolif_script = os.path.join(output_dir, "_run_prolif.py")
    script_content = f"""import sys
try:
    import prolif as plf
    import MDAnalysis as mda
    from prolif.plotting.network import LigNetwork
except ImportError:
    print("Error: ProLIF or MDAnalysis not installed. Run: uv pip install prolif MDAnalysis")
    sys.exit(1)

u = mda.Universe("{pdb_abs}")
lig = u.select_atoms("resname {lig_name}")
prot = u.select_atoms("protein")

if len(lig) == 0:
    print("Ligand {lig_name} not found by MDAnalysis.")
    sys.exit(1)

fp = plf.Fingerprint()
fp.run(u.trajectory[::1], lig, prot)
net = LigNetwork.from_fingerprint(fp, lig, kind="frame", frame=0)
net.save("{html_out}")
print("2D Diagram saved to {html_out}")
"""
    with open(prolif_script, "w") as f:
        f.write(script_content)
        
    print("Generating 2D interaction diagram via ProLIF...")
    # Run the script using uv to ensure dependencies are available
    subprocess.run(["uv", "run", "--with", "prolif", "--with", "MDAnalysis", "--with", "rdkit", "python", prolif_script], capture_output=False)
    
    # Cleanup runner
    if os.path.exists(prolif_script):
        os.remove(prolif_script)
        
    return html_out

def main():
    parser = argparse.ArgumentParser(description="Generate 3D and 2D docking visualization scripts/images.")
    parser.add_argument("--pdb", required=True, help="Path to the complex PDB file")
    parser.add_argument("--output-dir", required=True, help="Directory to save the generated scripts and diagrams")
    parser.add_argument("--ligand-name", help="Optional: 3-letter code of the ligand (auto-detected if omitted)")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.pdb):
        print(f"Error: PDB file not found: {args.pdb}")
        sys.exit(1)
        
    os.makedirs(args.output_dir, exist_ok=True)
    
    lig_name = args.ligand_name
    if not lig_name:
        lig_name, candidates = detect_ligand(args.pdb)
        if not lig_name:
            print("Error: No suitable HETATM ligand found in the PDB file.")
            sys.exit(1)
        print(f"Auto-detected ligand: {lig_name} (Other candidates: {', '.join(candidates)})")
    else:
        print(f"Using provided ligand name: {lig_name}")
        
    # Generate 3D Script
    cxc_script = generate_chimerax_script(args.pdb, lig_name, args.output_dir)
    print(f"Success! Generated ChimeraX script: {cxc_script}")
    
    # Generate 2D Diagram
    html_out = generate_2d_diagram(args.pdb, lig_name, args.output_dir)
    print(f"Success! Generated 2D Interaction Diagram: {html_out}")
    print("\nNext steps:")
    print(f"1. 3D: Open ChimeraX and run: open {os.path.basename(cxc_script)}")
    print(f"2. 2D: Open {os.path.basename(html_out)} in any web browser and take a screenshot.")

if __name__ == "__main__":
    main()
