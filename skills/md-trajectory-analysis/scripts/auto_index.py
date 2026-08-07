import subprocess
import sys
import os

def generate_default_index(tpr_file, output_ndx="index.ndx"):
    """
    Generate a default GROMACS index file from a .tpr or .gro file.
    This avoids interactive prompt hell by safely piping 'q' to make_ndx.
    """
    if os.path.exists(output_ndx):
        print(f"Index file {output_ndx} already exists. Skipping generation.")
        return output_ndx

    cmd = ["gmx", "make_ndx", "-f", tpr_file, "-o", output_ndx]
    
    try:
        # Pipe "q\n" to quit make_ndx immediately after it generates default groups
        process = subprocess.run(cmd, input="q\n", text=True, capture_output=True, check=True)
        print(f"Successfully generated default index file: {output_ndx}")
        return output_ndx
    except subprocess.CalledProcessError as e:
        print(f"Error generating index file:\n{e.stderr}", file=sys.stderr)
        raise

def get_group_name(group_name, ndx_file=None):
    """
    Utility to safely map biological names to GROMACS defaults.
    """
    # GROMACS Built-in Defaults
    gmx_defaults = {
        "protein": "Protein",
        "backbone": "Backbone",
        "c-alpha": "C-alpha",
        "non-protein": "Non-Protein",
        "water": "Water",
        "ions": "Ions",
        "system": "System"
    }
    
    name_lower = group_name.lower()
    return gmx_defaults.get(name_lower, group_name)
