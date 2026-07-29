import numpy as np
import scipy.stats as stats
import re

def read_xvg(filepath, cols=None):
    """
    Read a GROMACS .xvg file, filtering out comment lines (#) and designator lines (@).
    
    Parameters:
    filepath (str or Path): Path to the GROMACS xvg file.
    cols (list of int, optional): Column indices to extract.
    
    Returns:
    numpy.ndarray: Data matrix. If cols is specified, returns a list of column arrays.
    """
    data = []
    with open(filepath, 'r') as f:
        for line in f:
            # Skip GROMACS comment and parameter lines
            if line.startswith(('#', '@')):
                continue
            vals = line.split()
            if vals:
                data.append([float(v) for v in vals])
    
    arr = np.array(data)
    if arr.ndim == 2 and arr.shape[0] > 0:
        arr = arr[arr[:, 0].argsort()]
    if cols is not None:
        return [arr[:, c] for c in cols]
    return arr

def read_xpm(filepath):
    """
    Robustly parse a GROMACS .xpm file (e.g. from do_dssp).
    
    Returns:
        matrix (np.ndarray): 2D array of integers representing the categories.
        color_map (dict): Mapping of integer -> (color_hex, label).
        x_axis (np.ndarray): Values for the X-axis (usually time).
        y_axis (np.ndarray): Values for the Y-axis (usually residues).
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    width, height, num_colors, chars_per_pixel = 0, 0, 0, 0
    color_map = {}
    char_to_int = {}
    matrix_lines = []
    
    in_data = False
    
    x_axis = []
    y_axis = []
    
    for line in lines:
        if line.startswith('/* x-axis:'):
            vals = line.split('/* x-axis:')[1].replace('*/', '').split()
            x_axis.extend([float(v) for v in vals])
            continue
        elif line.startswith('/* y-axis:'):
            vals = line.split('/* y-axis:')[1].replace('*/', '').split()
            y_axis.extend([float(v) for v in vals])
            continue
            
        if line.startswith('static char'):
            in_data = True
            continue
            
        if in_data and line.startswith('"'):
            # Strip outer quotes
            content = line.strip().strip(',;')[1:-1]
            if width == 0:
                # Parse header
                parts = content.split()
                if len(parts) >= 4:
                    width = int(parts[0])
                    height = int(parts[1])
                    num_colors = int(parts[2])
                    chars_per_pixel = int(parts[3])
                continue
                
            if len(color_map) < num_colors:
                # Parse color map entry
                char_key = content[:chars_per_pixel]
                color_match = re.search(r'c\s+(#[0-9a-fA-F]+|\w+)', content)
                color = color_match.group(1) if color_match else '#FFFFFF'
                
                label_match = re.search(r'/\*\s*"(.+?)"\s*\*/', line)
                label = label_match.group(1) if label_match else f"Category_{len(color_map)}"
                
                idx = len(color_map)
                color_map[idx] = (color, label)
                char_to_int[char_key] = idx
                continue
                
            # Parse matrix data
            matrix_lines.append(content)
            
    matrix = np.zeros((height, width), dtype=int)
    for i, row_str in enumerate(matrix_lines):
        if i >= height:
            break
        # Chunk the string
        chunks = [row_str[k:k+chars_per_pixel] for k in range(0, len(row_str), chars_per_pixel)]
        for j, c in enumerate(chunks):
            if j < width:
                matrix[i, j] = char_to_int.get(c, 0)
                
    if not x_axis:
        x_axis = np.arange(width)
    if not y_axis:
        y_axis = np.arange(height)
        
    return matrix, color_map, np.array(x_axis), np.array(y_axis)

def convolve_smooth(data, window_size=50):
    """
    Smooth a 1D trace using a rolling average convolution.
    
    Parameters:
    data (numpy.ndarray): 1D array of noisy data.
    window_size (int): Convolution window size.
    
    Returns:
    numpy.ndarray: Smoothed 1D trace.
    """
    if len(data) < window_size:
        return data
    window = np.ones(window_size) / window_size
    return np.convolve(data, window, mode='valid')

def block_average_welch(wt_data, ox_data, n_blocks=10):
    """
    Perform statistical significance testing between WT and OX systems.
    To avoid false-positive inflation due to high temporal autocorrelation in MD,
    the data is split into contiguous blocks, block-averaged, and then
    subjected to Welch's t-test (two-sample unpaired t-test with unequal variance).
    """
    def get_block_means(x):
        x = np.asarray(x)
        x = x[~np.isnan(x)] # strip NaNs
        n = len(x) // n_blocks * n_blocks
        if n == 0:
            return np.array([x.mean()])
        return x[:n].reshape(n_blocks, -1).mean(axis=1)

    wt_blocks = get_block_means(wt_data)
    ox_blocks = get_block_means(ox_data)
    
    t_stat, p_val = stats.ttest_ind(wt_blocks, ox_blocks, equal_var=False)
    return p_val

def get_p_value_stars(p):
    """
    Convert a p-value into publication-standard significance stars.
    """
    if p < 0.001:
        return "***"
    elif p < 0.01:
        return "**"
    elif p < 0.05:
        return "*"
    return ""
