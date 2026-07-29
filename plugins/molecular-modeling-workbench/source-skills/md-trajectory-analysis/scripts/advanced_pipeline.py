import subprocess
import os
import sys

def run_gmx_cmd(cmd_list, input_str=None):
    print(f"Running: {' '.join(cmd_list)}")
    try:
        proc = subprocess.run(cmd_list, input=input_str, text=True, capture_output=True, check=True)
        return proc.stdout
    except subprocess.CalledProcessError as e:
        print(f"FAILED: {' '.join(cmd_list)}", file=sys.stderr)
        print(f"Error Output:\n{e.stderr}", file=sys.stderr)
        raise

def run_advanced_fel(tpr_file, xtc_file, outdir="analysis_out"):
    """
    Computes Covariance matrix and projects PCA (Tier 2).
    """
    os.makedirs(outdir, exist_ok=True)
    
    print("\n--- Advanced: Covariance & PCA ---")
    covar_eigenvec = os.path.join(outdir, "eigenvec.trr")
    covar_eigenval = os.path.join(outdir, "eigenval.xvg")
    
    # 1. Calculate Covariance matrix (fit to Backbone, output Backbone)
    if not os.path.exists(covar_eigenvec):
        run_gmx_cmd(["gmx", "covar", "-s", tpr_file, "-f", xtc_file, "-v", covar_eigenvec, "-o", covar_eigenval], "Backbone\nBackbone\n")
        
    # 2. Project PCA 2D Landscape (PC1 vs PC2)
    pca_proj = os.path.join(outdir, "pca_2dproj.xvg")
    if not os.path.exists(pca_proj):
        run_gmx_cmd(["gmx", "anaeig", "-v", covar_eigenvec, "-f", xtc_file, "-s", tpr_file, "-first", "1", "-last", "2", "-2d", pca_proj], "Backbone\nBackbone\n")
        
    print(f"✅ FEL/PCA Analysis Complete. Output: {pca_proj}")

def run_advanced_network(tpr_file, xtc_file, outdir="analysis_out"):
    """
    Computes Dynamic Cross-Correlation Matrix (DCCM) and Contact Map using MDAnalysis.
    """
    os.makedirs(outdir, exist_ok=True)
    dccm_out = os.path.join(outdir, "dccm.csv")
    contact_out = os.path.join(outdir, "contact.csv")
    
    print("\n--- Advanced: Dynamic Network (MDAnalysis) ---")
    try:
        import MDAnalysis as mda
        from MDAnalysis.analysis import align
        from MDAnalysis.analysis.base import AnalysisFromFunction
        import numpy as np
        
        print("Loading trajectory into MDAnalysis...")
        u = mda.Universe(tpr_file, xtc_file)
        calphas = u.select_atoms("name CA")
        
        # 1. Align trajectory to first frame to remove translation/rotation
        print("Aligning trajectory...")
        align.AlignTraj(u, u, select="name CA", in_memory=True).run()
        
        # 2. Compute DCCM (Cross-correlation of fluctuations)
        print("Computing DCCM...")
        # Get coordinates array (n_frames, n_atoms, 3)
        coords = np.array([calphas.positions for ts in u.trajectory])
        # Mean positions
        mean_coords = coords.mean(axis=0)
        # Fluctuations
        flucts = coords - mean_coords
        
        n_atoms = calphas.n_atoms
        dccm = np.zeros((n_atoms, n_atoms))
        
        # Dot product of fluctuations over time
        for i in range(n_atoms):
            for j in range(i, n_atoms):
                dot_ij = np.sum(flucts[:, i, :] * flucts[:, j, :], axis=1).mean()
                mag_i = np.sqrt(np.sum(flucts[:, i, :]**2, axis=1).mean())
                mag_j = np.sqrt(np.sum(flucts[:, j, :]**2, axis=1).mean())
                corr = dot_ij / (mag_i * mag_j)
                dccm[i, j] = corr
                dccm[j, i] = corr
                
        np.savetxt(dccm_out, dccm, delimiter=",", fmt="%.4f")
        print(f"DCCM saved to {dccm_out}")
        
        # 3. Compute Distance/Contact Map (Mean distance over trajectory)
        print("Computing Contact Map...")
        from scipy.spatial.distance import pdist, squareform
        dist_matrices = []
        for ts in u.trajectory[::10]: # Subsample to save time
            d = squareform(pdist(calphas.positions))
            dist_matrices.append(d)
        mean_dist = np.mean(dist_matrices, axis=0)
        
        # Convert distance to contact probability (e.g., cutoff 8 Angstroms)
        contact_prob = np.zeros_like(mean_dist)
        contact_prob[mean_dist < 8.0] = 1.0
        
        np.savetxt(contact_out, contact_prob, delimiter=",", fmt="%.4f")
        print(f"Contact map saved to {contact_out}")
        
    except ImportError:
        print("ERROR: MDAnalysis is not installed. Please run: uv pip install MDAnalysis", file=sys.stderr)
        raise

def run_advanced_mmpbsa(tpr_file, xtc_file, top_file, outdir="analysis_out"):
    """
    Wraps gmx_MMPBSA calculation.
    """
    os.makedirs(outdir, exist_ok=True)
    print("\n--- Advanced: MM/PBSA ---")
    
    mmpbsa_in = os.path.join(outdir, "mmpbsa.in")
    if not os.path.exists(mmpbsa_in):
        with open(mmpbsa_in, "w") as f:
            f.write("&general\nstartframe=1,\ninterval=10,\n/\n&gb\nigb=5, saltcon=0.150,\n/\n&decomp\nidecomp=2, dec_verbose=0,\n/\n")
            
    print("WARNING: gmx_MMPBSA is computationally expensive and requires proper index.ndx selections.")
    print("Please execute gmx_MMPBSA manually via MPI if this is a large complex:")
    print(f"mpirun -np 8 gmx_MMPBSA -O -i {mmpbsa_in} -cs {tpr_file} -ct {xtc_file} -cp {top_file} -nogui")
