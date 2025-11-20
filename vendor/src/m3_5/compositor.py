# src/m3_5/compositor.py
import numpy as np

def composite_bg(fg_bgra, bg_bgr):
    alpha = fg_bgra[:, :, 3:4] / 255.0
    return (fg_bgra[:, :, :3] * alpha + bg_bgr * (1 - alpha)).astype(np.uint8)
