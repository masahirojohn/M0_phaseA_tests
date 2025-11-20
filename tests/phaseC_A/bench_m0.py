# tests/phaseC_A/bench_m0.py
from __future__ import annotations
import argparse
import json
import time
import sys
from pathlib import Path
from typing import Any, Dict

import yaml


# -----------------------------
# sys.path 調整（src を見つけるため）
# -----------------------------
def _setup_sys_path_for_src() -> None:
    """
    bench_m0.py の位置からリポジトリルートを推定し、
    src / vendor/src を import パスに追加する。
    """
    here = Path(__file__).resolve()
    # .../tests/phaseC_A/bench_m0.py -> リポジトリルートは 2 つ上
    repo_root = here.parents[2]

    candidates = [
        repo_root,           # ルート直下に src/ がある場合
        repo_root / "vendor" # vendor/src/ になっている場合
    ]

    for p in candidates:
        if p.is_dir():
            s = str(p)
            if s not in sys.path:
                sys.path.insert(0, s)


_setup_sys_path_for_src()


# -----------------------------
# 基本ユーティリティ（m0_runner と互換）
# -----------------------------
def load_yaml(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    txt = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        return yaml.safe_load(txt) or {}
    # JSON も許容
    return json.loads(txt)


def _import_timeline_and_render():
    """
    m0_runner と同じく、依存を遅延 import。
    ここまでに _setup_sys_path_for_src() 済みなので src が見えるはず。:contentReference[oaicite:0]{index=0}
    """
    from src.timeline import Timeline
    from src.render_core import render_video
    return Timeline, render_video


def _abs_assets_path(assets_dir: Path, rel_or_abs: str) -> str:
    """
    inputs.* に対して:
      - 絶対パスならそのまま
      - 相対パスなら assets_dir を基準に解決
    """
    p = Path(rel_or_abs)
    if p.is_absolute():
        return str(p)
    return str((assets_dir / p).resolve())


def _build_merged_value_fn(mouth_tl, pose_tl, expr_tl):
    """
    PhaseC-A では yaw 軸固定でよいので、単純に 3 つのタイムラインをマージ。
    （m0_runner の yaw ケースと同等の挙動）:contentReference[oaicite:1]{index=1}
    """
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


# -----------------------------
# メイン
# -----------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="PhaseC-A: M0 Benchmark Runner")
    ap.add_argument(
        "--config",
        "-c",
        default="configs/phaseC_A.bench.yaml",
        help="ベンチ用 config のパス (YAML/JSON)",
    )
    args = ap.parse_args()

    cfg = load_yaml(args.config)

    # ---- IO / VIDEO 設定 ----
    io = cfg["io"]
    video = cfg["video"]
    render_cfg = cfg.get("render", {}) or {}
    atlas_cfg = cfg.get("atlas", {}) or {}
    inputs_cfg = cfg.get("inputs", {}) or {}
    transform_cfg = cfg.get("transform", None)

    assets_dir = Path(io["assets_dir"]).resolve()
    out_dir = Path(io["out_dir"]).resolve()
    exp_name = io.get("exp_name", "phaseC_A_bench")

    width = int(video["width"])
    height = int(video["height"])
    fps = int(video["fps"])
    duration_s = float(video["duration_s"])
    crossfade_frames = int(render_cfg.get("crossfade_frames", 0))

    out_dir.mkdir(parents=True, exist_ok=True)
    exp_dir = out_dir / exp_name
    exp_dir.mkdir(parents=True, exist_ok=True)
    out_mp4 = exp_dir / "bench.mp4"
    out_log = exp_dir / "bench.log.json"

    # ---- Timeline / Renderer 読み込み ----
    Timeline, render_video = _import_timeline_and_render()

    # mouth / pose / expression タイムライン
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

    # atlas パス（assets_dir を基準とした相対パス前提）
    atlas_rel = atlas_cfg.get("atlas_json", None)

    # ---- ベンチマーク実行 ----
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
    )
    t1 = time.perf_counter()

    elapsed_s = t1 - t0
    elapsed_ms = elapsed_s * 1000.0
    avg_ms_per_frame = elapsed_ms / max(frames_expected, 1)
    fps_effective = frames_expected / elapsed_s if elapsed_s > 0 else 0.0

    # render_video から返る stats（fallback_frames, views など）をそのままマージ:contentReference[oaicite:2]{index=2}
    bench_log: Dict[str, Any] = {
        "label": cfg.get("benchmark", {}).get("label", "phaseC_A"),
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
    }
    if isinstance(stats, dict):
        bench_log.update(stats)

    out_log.write_text(json.dumps(bench_log, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[M0 BENCH] label={bench_log['label']}")
    print(f"  out_mp4           : {out_mp4}")
    print(f"  frames_expected   : {frames_expected}")
    print(f"  elapsed_s         : {elapsed_s:.3f} s")
    print(f"  avg_ms_per_frame  : {avg_ms_per_frame:.3f} ms")
    print(f"  fps_effective     : {fps_effective:.3f} fps")


if __name__ == "__main__":
    main()
