---
name: western-blot-processor
description: >-
  Automates Western Blot image processing, including auto-cropping to membrane boundaries and non-linear Gamma correction for natural contrast enhancement. Exposes key parameters to the agent for flexible biological reasoning.
---

# Western Blot Processor

## Overview

This skill provides a programmatic CLI for processing Western Blot images. It is designed to prepare raw scanned WB images for quantification or publication by allowing automated membrane cropping and non-linear contrast adjustment (Gamma correction) to make "blacked-out" or saturated bands distinguishable while preserving the natural background texture.

## Dependencies

- **uv**: The skill relies on `uv` to automatically manage the Python environment and dependencies (`opencv-python`, `numpy`).

## Quick Start

To process a single image or a directory of images:

```bash
uv run --with opencv-python --with numpy python path/to/wb_processor.py process \
  --input ./data/wb_image.png \
  --output-dir ./data/output \
  --gamma 0.55 \
  --auto-crop \
  --comparison
```

## Utility Scripts

### `wb_processor.py process`

Processes images using the specified parameters.

**Arguments:**

- `--input <path>`: (Required) Path to a single image file or a directory containing images (`.png`, `.jpg`, `.tif`).
- `--output-dir <path>`: (Required) Directory where processed images will be saved.
- `--gamma <float>`: The gamma correction value. Default is `1.0` (no change). To lift shadows and separate saturated dark bands, use a value < 1.0 (e.g., `0.4` to `0.8`).
- `--auto-deskew`: Flag to attempt to automatically detect the rotation of the membrane bands and align them horizontally/vertically before processing.
- `--auto-crop`: Flag to attempt to automatically detect the membrane and crop out white margins.
- `--comparison`: Flag to generate a side-by-side comparison image (original on the left, processed on the right).

**Example: Batch processing a directory with auto-crop and shadow lifting**

```bash
uv run --with opencv-python --with numpy python path/to/wb_processor.py process --input ./data/raw_wbs --output-dir ./data/processed_wbs --auto-deskew --auto-crop --gamma 0.6 --comparison
```

## Agent Guidelines

- **Tune Gamma based on balance:** By default, use `gamma=0.6`. If the bands are extremely dark and indistinguishable, use a lower gamma (e.g., `0.4`). If they just need a slight lift, use `0.8`.
- **Handling Auto-crop failures:** If `--auto-crop` fails due to poor image quality (a `CropFailureError` is raised in stderr), you should re-run the script *without* `--auto-crop` and inform the user that manual cropping in ImageJ may be necessary. Do not silently ignore crop failures.
- **File Output:** Always rely on the JSON output written to stdout to identify successfully processed files, and present the `--comparison` images to the user as embedded markdown images.

## Common Mistakes

- **Applying Gamma > 1.0**: This makes shadows darker and highlights brighter, which will crush already-dark bands into pure black. Always use Gamma < 1.0 if the goal is to differentiate saturated dark bands.
- **Assuming Auto-crop is perfect**: Auto-crop uses morphological closing and Canny edges. Very noisy backgrounds or extremely weak signal across the entire membrane might cause it to crop incorrectly or fail.
