from __future__ import annotations
import argparse, os, json
import time
from typing import Dict, Any
import yaml
from src.timeline import Timeline
from src.render_core import render_video


def load_yaml(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def deep_update(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_update(base[k], v)
        else:
            base[k] = v
    return base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--override", action="append", default=[])
    args = ap.parse_args()

    cfg = load_yaml(args.config)
    for o in args.override:
        cfg = deep_update(cfg, load_yaml(o))

    assets_dir = cfg["io"]["assets_dir"]
    out_dir = cfg["io"]["out_dir"]
    exp_name = cfg["io"]["exp_name"]

    width = int(cfg["video"]["width"])
    height = int(cfg["video"]["height"])
    fps = int(cfg["video"]["fps"])
    duration_s = int(cfg["video"]["duration_s"])

    crossfade_frames = int(cfg["render"]["crossfade_frames"])

    inputs = cfg.get("inputs", {})
    mouth_tl = Timeline.load_json(os.path.join(assets_dir, inputs["mouth_timeline"])) if "mouth_timeline" in inputs else Timeline([])
    pose_tl = Timeline.load_json(os.path.join(assets_dir, inputs["pose_timeline"])) if "pose_timeline" in inputs else Timeline([])
    expr_tl = Timeline.load_json(os.path.join(assets_dir, inputs["expression_timeline"])) if "expression_timeline" in inputs else Timeline([])

    def merged_value(t_ms: int) -> Dict[str, Any]:
        vals = {}
        vals.update(mouth_tl.value_at(t_ms))
        vals.update(pose_tl.value_at(t_ms))
        vals.update(expr_tl.value_at(t_ms))
        return vals

    exp_dir = os.path.join(out_dir, exp_name)
    os.makedirs(exp_dir, exist_ok=True)
    out_mp4 = os.path.join(exp_dir, "demo.mp4")

    # Measure wall time and get stats from render_video
    t0 = time.time()
    stats = render_video(
        out_mp4, width, height, fps, duration_s, crossfade_frames, merged_value,
        assets_dir=assets_dir, atlas_json_rel=cfg.get("atlas", {}).get("atlas_json", None)
    )
    elapsed_s = time.time() - t0

    run_log = {
        "out_mp4": out_mp4,
        "fps": fps,
        "duration_s": duration_s,
        "frames": int(duration_s * fps),
        "assets_dir": assets_dir,
        "exp_name": exp_name,
        "elapsed_s": round(elapsed_s, 3),
    }
    run_log.update(stats)

    with open(os.path.join(exp_dir, "run.log.json"), "w", encoding="utf-8") as f:
        json.dump(run_log, f, ensure_ascii=False, indent=2)

    # Output summary CSV for key metrics
    summary_keys = ["exp_name", "duration_s", "elapsed_s", "fallback_frames", "first_fallback_ms"]
    with open(os.path.join(exp_dir, "summary.csv"), "w", encoding="utf-8") as f:
        f.write("key,value\n")
        for k in summary_keys:
            if k in run_log:
                f.write(f"{k},{run_log[k]}\n")
        views = run_log.get("views", {})
        for view_name, count in views.items():
            f.write(f"views_{view_name},{count}\n")


if __name__ == "__main__":
    main()
