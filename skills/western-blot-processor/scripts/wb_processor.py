import cv2
import numpy as np
import os
import argparse
import sys
import json
from pathlib import Path

def get_crop_bbox(img_gray, pad=40):
    """
    Attempts to find the bounding box of the membrane/bands in a Western Blot image.
    Uses Canny edge detection and morphological dilation to find the main content area.
    """
    # Apply a slight blur to reduce noise
    blurred = cv2.GaussianBlur(img_gray, (5, 5), 0)
    
    # Use Canny edge detector
    edges = cv2.Canny(blurred, 30, 150)
    
    # Dilate edges massively to connect distant bands into a single cohesive block
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25))
    dilated = cv2.dilate(edges, kernel, iterations=3)
    
    coords = cv2.findNonZero(dilated)
    if coords is None:
        return None
        
    x, y, w, h = cv2.boundingRect(coords)
    
    # Add padding
    x_start = max(0, x - pad)
    y_start = max(0, y - pad)
    x_end = min(img_gray.shape[1], x + w + pad)
    y_end = min(img_gray.shape[0], y + h + pad)
    
    return (x_start, y_start, x_end - x_start, y_end - y_start)

def deskew_image(img_gray):
    """
    Attempts to detect the rotation of the membrane bands and rotates the image
    to align them horizontally/vertically.
    """
    blurred = cv2.GaussianBlur(img_gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 30, 150)
    
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=50, minLineLength=50, maxLineGap=10)
    
    if lines is None:
        return img_gray
        
    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if angle < -45:
            angle += 180
        elif angle > 45:
            angle -= 180
            
        if -20 <= angle <= 20:
            angles.append(angle)
            
    if not angles:
        return img_gray
        
    median_angle = np.median(angles)
    
    if abs(median_angle) < 0.5:
        return img_gray
        
    (h, w) = img_gray.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    
    cos = np.abs(M[0, 0])
    sin = np.abs(M[0, 1])
    nW = int((h * sin) + (w * cos))
    nH = int((h * cos) + (w * sin))
    M[0, 2] += (nW / 2) - center[0]
    M[1, 2] += (nH / 2) - center[1]
    
    rotated = cv2.warpAffine(img_gray, M, (nW, nH), borderMode=cv2.BORDER_CONSTANT, borderValue=255)
    return rotated

def process_image(input_path, output_dir, gamma=1.0, auto_crop=False, auto_deskew=False, padding=40, comparison=False):
    img = cv2.imread(str(input_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"Failed to load image: {input_path}")

    # 0. Auto-deskew
    if auto_deskew:
        img = deskew_image(img)

    # 1. Auto-crop
    if auto_crop:
        bbox = get_crop_bbox(img, pad=padding)
        if bbox is None:
            raise RuntimeError(f"CropFailureError: Could not detect membrane boundaries in {input_path}. Please have the Agent review the image or disable --auto-crop.")
        x, y, w, h = bbox
        img = img[y:y+h, x:x+w]

    # 2. Gamma Correction (Shadow Lift / Contrast Enhancement)
    if gamma != 1.0:
        table = np.array([((i / 255.0) ** gamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
        processed = cv2.LUT(img, table)
    else:
        processed = img.copy()

    # 3. Save outputs
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    base_name = Path(input_path).stem
    ext = Path(input_path).suffix
    
    out_file = out_dir / f"{base_name}_processed{ext}"
    cv2.imwrite(str(out_file), processed)
    
    comp_file = None
    if comparison:
        h_orig, w_orig = img.shape
        comp_img = np.zeros((h_orig, w_orig*2), dtype=np.uint8)
        comp_img[:, :w_orig] = img
        comp_img[:, w_orig:] = processed
        comp_file = out_dir / f"{base_name}_comparison{ext}"
        cv2.imwrite(str(comp_file), comp_img)
        
    return {
        "input": str(input_path),
        "output": str(out_file),
        "comparison": str(comp_file) if comparison else None,
        "status": "success",
        "cropped": auto_crop
    }

def main():
    parser = argparse.ArgumentParser(description="Western Blot Processor")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # 'process' command
    process_parser = subparsers.add_parser("process", help="Process Western Blot images")
    process_parser.add_argument("--input", required=True, help="Path to input image or directory")
    process_parser.add_argument("--output-dir", required=True, help="Directory to save processed images")
    process_parser.add_argument("--gamma", type=float, default=1.0, help="Gamma value for shadow lift (< 1.0 makes dark bands lighter)")
    process_parser.add_argument("--padding", type=int, default=40, help="Padding in pixels around the cropped area (default 40)")
    process_parser.add_argument("--auto-deskew", action="store_true", help="Attempt to automatically align/rotate the bands horizontally")
    process_parser.add_argument("--auto-crop", action="store_true", help="Attempt to automatically crop to membrane boundaries")
    process_parser.add_argument("--comparison", action="store_true", help="Generate side-by-side comparison images")
    
    args = parser.parse_args()
    
    if args.command == "process":
        input_path = Path(args.input)
        if not input_path.exists():
            print(f"Error: Input path {input_path} does not exist.", file=sys.stderr)
            sys.exit(1)
            
        files_to_process = []
        if input_path.is_file():
            files_to_process.append(input_path)
        elif input_path.is_dir():
            valid_exts = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
            files_to_process = [f for f in input_path.iterdir() if f.suffix.lower() in valid_exts]
            
        if not files_to_process:
            print("Error: No valid images found.", file=sys.stderr)
            sys.exit(1)
            
        results = []
        has_error = False
        
        for f in files_to_process:
            try:
                res = process_image(f, args.output_dir, gamma=args.gamma, auto_crop=args.auto_crop, auto_deskew=args.auto_deskew, padding=args.padding, comparison=args.comparison)
                results.append(res)
            except Exception as e:
                print(f"Error processing {f.name}: {str(e)}", file=sys.stderr)
                has_error = True
                
        # Output JSON summary
        print(json.dumps({"processed_count": len(results), "results": results}, indent=2))
        
        if has_error and len(results) == 0:
            sys.exit(1)

if __name__ == "__main__":
    main()
