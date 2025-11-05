from __future__ import annotations
import os, json
from typing import Dict, Any, Tuple
import numpy as np
import cv2
from functools import lru_cache

def _ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)

# ----------------------
# atlas.json 読み込み
# ----------------------
def load_atlas_index(atlas_json_path: str) -> Dict[str, Any]:
    with open(atlas_json_path, "r", encoding="utf-8") as f:
        idx = json.load(f)

    # "views" キーは使わず、"front" 等のビューがトップレベルにあると期待
    # また、mouth キーを小文字化
    views = {}
    for key, value in idx.items():
        if isinstance(value, dict) and "closed" in value:  # Assuming this identifies a view entry
            views[key] = {k.lower(): v for k, v in value.items()}
    idx["views"] = views  # Add a "views" key for compatibility with the rest of the code

    return idx

def _normalize_mouth(mouth: str) -> str:
    m = (mouth or "").strip().lower()
    return "closed" if m in ("close", "closed") else m

def _select_view(yaw_deg: float, rules: Dict[str, Any]) -> str:
    if yaw_deg <= float(rules.get("left30_max_yaw_deg", -10)):
        return "left30"
    if yaw_deg >= float(rules.get("right30_min_yaw_deg", 10)):
        return "right30"
    return "front"

@lru_cache(maxsize=128)
def _load_rgba(path: str) -> np.ndarray:
    img = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(path)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGRA)
    elif img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2BGRA)
    return img

def _alpha_paste(dst_bgra: np.ndarray, src_bgra: np.ndarray, cx: int, cy: int):
    h, w = dst_bgra.shape[:2]
    sh, sw = src_bgra.shape[:2]
    x0 = int(cx - sw // 2); y0 = int(cy - sh // 2)
    x1 = min(w, x0 + sw); y1 = min(h, y0 + sh)
    if x1 <= 0 or y1 <= 0 or x0 >= w or y0 >= h:
        return
    sx0 = max(0, -x0); sy0 = max(0, -y0)
    dx0 = max(0, x0);  dy0 = max(0, y0)
    region_dst = dst_bgra[dy0:y1, dx0:x1]
    region_src = src_bgra[sy0:sy0+(y1-dy0), sx0:sx0+(x1-dx0)]
    alpha = (region_src[..., 3:4].astype(np.float32) / 255.0)
    region_dst[..., :3] = (region_src[..., :3] * alpha + region_dst[..., :3] * (1 - alpha)).astype(np.uint8)
    region_dst[..., 3] = np.clip(region_dst[..., 3] + region_src[..., 3] * (1 - (region_dst[..., 3]/255.0)), 0, 255).astype(np.uint8)

def _solid_bg(width: int, height: int) -> np.ndarray:
    bg = np.zeros((height, width, 4), np.uint8)
    bg[..., 0:3] = (28, 28, 28)
    bg[..., 3] = 255
    return bg

def render_video(
    out_mp4: str,
    width: int,
    height: int,
    fps: int,
    duration_s: int,
    crossfade_frames: int,
    timeline_value_fn,
    assets_dir: str | None = None,
    atlas_json_rel: str | None = None,
) -> Dict[str, Any]:
    """動画を描画し、統計情報を返す"""
    _ensure_dir(os.path.dirname(out_mp4) or ".")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    vw = cv2.VideoWriter(out_mp4, fourcc, fps, (width, height))

    total_frames = int(duration_s * fps)
    prev_frame = None

    atlas_idx = None
    if assets_dir and atlas_json_rel:
        atlas_idx = load_atlas_index(os.path.join(assets_dir, atlas_json_rel))

    target_h_ratio = 0.32

    # ---- 統計カウンタ ----
    views_count = {"front": 0, "left30": 0, "right30": 0}
    fallback_frames = 0
    first_fallback_ms = None

    for i in range(total_frames):
        t_ms = int(1000 * i / fps)
        vals: Dict[str, Any] = timeline_value_fn(t_ms)
        mouth = _normalize_mouth(vals.get("mouth", "closed"))
        yaw = float(vals.get("yaw", 0))

        frame = _solid_bg(width, height)

        used_fallback = False
        if atlas_idx is not None:
            view = _select_view(yaw, atlas_idx.get("view_rules", {}))
            views_count[view] = views_count.get(view, 0) + 1
            views = atlas_idx["views"]

            path_rel = views.get(view, {}).get(mouth)
            if not path_rel:
                used_fallback = True
                fb_view = atlas_idx.get("fallback", {}).get("view", "front")
                fb_mouth = _normalize_mouth(atlas_idx.get("fallback", {}).get("mouth", "closed"))
                path_rel = views.get(fb_view, {}).get(fb_mouth)

            if path_rel:
                try:
                    asset_path = os.path.join(assets_dir, path_rel)
                    src = _load_rgba(asset_path)
                    tgt_h = max(1, int(height * target_h_ratio))
                    scale = tgt_h / src.shape[0]
                    tgt_w = max(1, int(src.shape[1] * scale))
                    src_rs = cv2.resize(src, (tgt_w, tgt_h), interpolation=cv2.INTER_AREA)
                    cx = width // 2; cy = int(height * 0.58)
                    _alpha_paste(frame, src_rs, cx, cy)
                except FileNotFoundError:
                    used_fallback = True  # 実ファイル未発見時もfallback扱いにする

        if used_fallback:
            fallback_frames += 1
            if first_fallback_ms is None:
                first_fallback_ms = t_ms

        if crossfade_frames > 0 and prev_frame is not None and i % (fps // 2 or 1) == 0:
            for k in range(crossfade_frames):
                alpha = (k + 1) / crossfade_frames
                blended = (prev_frame.astype(np.float32) * (1 - alpha) + frame.astype(np.float32) * alpha).astype(np.uint8)
                vw.write(cv2.cvtColor(blended, cv2.COLOR_BGRA2BGR))
            prev_frame = frame
        else:
            vw.write(cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR))
            prev_frame = frame

    vw.release()

    return {
        "views": views_count,
        "fallback_frames": int(fallback_frames),
        "first_fallback_ms": int(first_fallback_ms) if first_fallback_ms is not None else None,
        "total_frames": int(total_frames),
    }
