# -*- coding: utf-8 -*-
"""
Convert all 922 science textbook figures from D:\src\books\科学\OCR to WebP
and save in pages/science/figures/<vol_dir>/<file>.webp
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from PIL import Image

OCR_DIR = r"D:\src\books\科学\OCR"
OUT_BASE = r"pages\science\figures"

def convert_one(args):
    src_path, dst_path = args
    if os.path.exists(dst_path) and os.path.getsize(dst_path) > 0:
        return os.path.getsize(src_path), os.path.getsize(dst_path), True
    try:
        im = Image.open(src_path)
        # Convert RGBA / P to RGB if saving as WebP
        if im.mode in ("RGBA", "LA"):
            background = Image.new("RGB", im.size, (255, 255, 255))
            background.paste(im, mask=im.split()[-1])
            im = background
        elif im.mode != "RGB":
            im = im.convert("RGB")
        im.save(dst_path, "WEBP", quality=85, method=4)
        return os.path.getsize(src_path), os.path.getsize(dst_path), False
    except Exception as e:
        print(f"Error converting {src_path}: {e}")
        return 0, 0, False

def main():
    t0 = time.time()
    vols = sorted([d for d in os.listdir(OCR_DIR) if d[:2].isdigit() and "_" in d])
    tasks = []
    
    for vol in vols:
        src_fig_dir = os.path.join(OCR_DIR, vol, "figures")
        if not os.path.exists(src_fig_dir):
            continue
        dst_fig_dir = os.path.join(OUT_BASE, vol)
        os.makedirs(dst_fig_dir, exist_ok=True)
        
        for f in os.listdir(src_fig_dir):
            if f.lower().endswith(".png"):
                src_file = os.path.join(src_fig_dir, f)
                dst_file = os.path.join(dst_fig_dir, f[:-4] + ".webp")
                tasks.append((src_file, dst_file))
                
    print(f"Found {len(tasks)} figure files across {len(vols)} volumes. Starting parallel conversion...")
    
    total_src = 0
    total_dst = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        for src_sz, dst_sz, cached in pool.map(convert_one, tasks):
            total_src += src_sz
            total_dst += dst_sz
            
    t1 = time.time()
    print(f"Done in {t1-t0:.2f}s!")
    print(f"Original PNG size: {total_src / 1024 / 1024:.2f} MB")
    print(f"WebP output size:  {total_dst / 1024 / 1024:.2f} MB")
    print(f"Compression ratio: {total_dst / (total_src or 1) * 100:.1f}%")

if __name__ == "__main__":
    main()
