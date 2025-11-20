# tests/phaseC_A/bench_m0_m3_5.py
from __future__ import annotations
import argparse
import json
import time
import sys
from pathlib import Path
from typing import Any, Dict

import yaml
import cv2
import numpy as np


# -----------------------------
# sys.path 調整（src を見つけるため）
# -----------------------------
def _setup_sys_path_for_src() -> None:
    here = Path(__file__).resolve()
    repo_root = here.parents[2]  # .../tests/phaseC_A/bench_m0_m3_5.py -> repo root

    candidates = [
        repo_root,
        repo_root / "vendor",
    ]
    for p in candidates:
        if p.is_dir():
            s = str(p)
            if s not in sys.path:
                sys.path.insert(0, s)


_setup_sys_path_for_src()


# -----------------------------
# ユーティリティ
# -----------------------------
def load_yaml(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    txt = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        return yaml.safe_load(txt) or {}
    return json.loads(txt)


def _import_timeline_and_render():
    from src.timeline import Timeline
    from src.render_core import render_video
    return Timeline, render_video


def _abs_assets_path(assets_dir: Path, rel_or_abs: str) -> str:
    p = Path(rel_or_abs)
    if p.is_absolute():
        return str(p)
    return str((assets_dir / p).resolve())


def _build_merged_value_fn(mouth_tl, pose_tl, expr_tl):
    def merged_value(t_ms: int) -> Dict[str, Any]:
        vals: Dict[str, Any] = {}
        if mouth_tl is not None:
            vals.update(mouth_tl.value_at(t_ms))
        if pose_tl is not None:
            vals.update(pose_tl.value_at(t_ms))
        if expr_tl is not None:
            vals.update(expr_tl.value_at(t_ms))
        return vals

    return merged_value


def _make_bg_bgr(width: int, height: int, bg_image_path: str | None) -> np.ndarray:
    """
    グリーンバック画像を BGR で読み込み、width/height にリサイズ。
    bg_image_path が None の場合は単色グリーンを生成。
    """
    if bg_image_path:
        img = cv2.imread(bg_image_path, cv2.IMREAD_COLOR)
        if img is None:
            raise FileNotFoundError(f"Failed to load bg_image: {bg_image_path}")
        bg = cv2.resize(img, (width, height), interpolation=cv2.INTER_AREA)
    else:
        bg = np.zeros((height, width, 3), dtype=np.uint8)
        bg[:, :, 1] = 255  # pure green
    return bg


def _make_per_frame_hook(bg_bgr: np.ndarray):
    """
    M3.5 相当の BG 合成を行う hook を生成。
    - fg_bgra: (H,W,4)
    - bg_bgr : (H,W,3)
    戻り値も BGRA（背景は不透明）にする。
    """
    h, w = bg_bgr.shape[:2]

    def hook(fg_bgra: np.ndarray, t_ms: int, frame_idx: int) -> np.ndarray:
        fg = fg_bgra
        # サイズが違えば resize（念のため）
        if fg.shape[0] != h or fg.shape[1] != w:
            fg = cv2.resize(fg, (w, h), interpolation=cv2.INTER_LINEAR)

        alpha = fg[:, :, 3:4].astype(np.float32) / 255.0
        comp_rgb = (
            fg[:, :, :3].astype(np.float32) * alpha
            + bg_bgr.astype(np.float32) * (1.0 - alpha)
        ).astype(np.uint8)

        # BGRA に戻す（背景は完全不透明）
        a = np.full((h, w, 1), 255, dtype=np.uint8)
        comp_bgra = np.concatenate([comp_rgb, a], axis=2)
        return comp_bgra

    return hook


# -----------------------------
# メイン
# -----------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="PhaseC-A: M0 + M3.5 Benchmark Runner")
    ap.add_argument(
        "--config",
        "-c",
        default="configs/phaseC_A.bench.yaml",
        help="ベンチ用 config のパス (YAML/JSON)",
    )
    ap.add_argument(
        "--bg_image",
        type=str,
        default=None,
        help="グリーンバック画像のパス（省略時は単色グリーン）",
    )
    args = ap.parse_args()

    cfg = load_yaml(args.config)

    io = cfg["io"]
    video = cfg["video"]
    render_cfg = cfg.get("render", {}) or {}
    atlas_cfg = cfg.get("atlas", {}) or {}
    inputs_cfg = cfg.get("inputs", {}) or {}
    transform_cfg = cfg.get("transform", None)

    assets_dir = Path(io["assets_dir"]).resolve()
    out_dir = Path(io["out_dir"]).resolve()
    exp_name = io.get("exp_name", "phaseC_A_bench_m0_m3_5")

    width = int(video["width"])
    height = int(video["height"])
    fps = int(video["fps"])
    duration_s = float(video["duration_s"])
    crossfade_frames = int(render_cfg.get("crossfade_frames", 0))

    out_dir.mkdir(parents=True, exist_ok=True)
    exp_dir = out_dir / exp_name
    exp_dir.mkdir(parents=True, exist_ok=True)
    out_mp4 = exp_dir / "bench_m0_m3_5.mp4"
    out_log = exp_dir / "bench_m0_m3_5.log.json"

    # Timeline / Renderer
    Timeline, render_video = _import_timeline_and_render()

    mouth_tl = None
    pose_tl = None
    expr_tl = None

    if "mouth_timeline" in inputs_cfg:
        mouth_path = _abs_assets_path(assets_dir, inputs_cfg["mouth_timeline"])
        mouth_tl = Timeline.load_json(mouth_path)
    if "pose_timeline" in inputs_cfg:
        pose_path = _abs_assets_path(assets_dir, inputs_cfg["pose_timeline"])
        pose_tl = Timeline.load_json(pose_path)
    if "expression_timeline" in inputs_cfg:
        expr_path = _abs_assets_path(assets_dir, inputs_cfg["expression_timeline"])
        expr_tl = Timeline.load_json(expr_path)

    merged_value = _build_merged_value_fn(mouth_tl, pose_tl, expr_tl)

    atlas_rel = atlas_cfg.get("atlas_json", None)

    # BG 用意（グリーンバック画像 or 単色グリーン）
    bg_bgr = _make_bg_bgr(width, height, args.bg_image)
    per_frame_hook = _make_per_frame_hook(bg_bgr)

    # ベンチ実行
    frames_expected = int(round(duration_s * fps))

    t0 = time.perf_counter()
    stats = render_video(
        str(out_mp4),
        width,
        height,
        fps,
        duration_s,
        crossfade_frames,
        merged_value,
        assets_dir=str(assets_dir),
        atlas_json_rel=atlas_rel,
        transform_cfg=transform_cfg,
        per_frame_hook=per_frame_hook,
    )
    t1 = time.perf_counter()

    elapsed_s = t1 - t0
    elapsed_ms = elapsed_s * 1000.0
    avg_ms_per_frame = elapsed_ms / max(frames_expected, 1)
    fps_effective = frames_expected / elapsed_s if elapsed_s > 0 else 0.0

    bench_log: Dict[str, Any] = {
        "label": cfg.get("benchmark", {}).get("label", "phaseC_A_m0_m3_5"),
        "config_path": str(Path(args.config).resolve()),
        "out_mp4": str(out_mp4),
        "assets_dir": str(assets_dir),
        "width": width,
        "height": height,
        "fps": fps,
        "duration_s": duration_s,
        "frames_expected": frames_expected,
        "elapsed_s": elapsed_s,
        "elapsed_ms": elapsed_ms,
        "avg_ms_per_frame": avg_ms_per_frame,
        "fps_effective": fps_effective,
        "pipeline": "m0+m3.5_hook",
    }
    if isinstance(stats, dict):
        bench_log.update(stats)

    out_log.write_text(json.dumps(bench_log, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[M0+M3.5 BENCH] label={bench_log['label']}")
    print(f"  out_mp4           : {out_mp4}")
    print(f"  frames_expected   : {frames_expected}")
    print(f"  elapsed_s         : {elapsed_s:.3f} s")
    print(f"  avg_ms_per_frame  : {avg_ms_per_frame:.3f} ms")
    print(f"  fps_effective     : {fps_effective:.3f} fps")


if __name__ == "__main__":
    main()
