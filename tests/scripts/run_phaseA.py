#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PhaseA runner (slim)
- v1→flat 変換後の FLAT ポーズを消費して M0 を実行
- 既定: tests/flats/yaw.flat.json
- 例:
    python tests/scripts/run_phaseA.py
    python tests/scripts/run_phaseA.py --pose tests/flats/pitch.flat.json
"""

import os
import sys
import json
import shutil
import argparse
import subprocess
from pathlib import Path
import yaml


def deep_merge(base, override):
    if not isinstance(base, dict) or not isinstance(override, dict):
        return override
    out = dict(base)
    for k, v in override.items():
        out[k] = deep_merge(out.get(k), v)
    return out


def load_yaml(p: Path):
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}


def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


def to_runner_schema(cfg: dict, repo: Path) -> dict:
    """旧設定→runner用設定への最小変換（存在すればそのまま返す）"""
    if "io" in cfg and "video" in cfg and "inputs" in cfg:
        return cfg
    out_dir = cfg.get("output", {}).get("dir", "tests/out")
    basename = cfg.get("output", {}).get("basename", "phaseA_demo")
    fps = cfg.get("render", {}).get("fps", 25)
    atlas_path = cfg.get("atlas_path", "tests/assets_min/atlas.min.json")
    return {
        "io": {
            "assets_dir": "tests/assets_min",
            "out_dir": out_dir,
            "exp_name": basename
        },
        "video": {
            "width": 640,
            "height": 640,
            "fps": fps,
            "duration_s": 3
        },
        "render": {
            "crossfade_frames": 4
        },
        "inputs": {
            "mouth_timeline": "timelines/mouth_timeline.json",
            "pose_timeline": "timelines/pose_timeline_yaw.flat.json",  # 後で上書き
            "expression_timeline": "timelines/expression_timeline.json"
        },
        "atlas": {
            "atlas_json": "atlas.min.json" if "atlas.min.json" in atlas_path else atlas_path
        }
    }


def main():
    repo = Path(__file__).resolve().parents[2]  # <repo_root>
    cfg_dir = repo / "configs"

    # CLI
    ap = argparse.ArgumentParser()
    ap.add_argument("--pose", type=str, default=None,
                    help="Path to FLAT pose timeline json (default: tests/flats/yaw.flat.json)")
    args = ap.parse_args()

    # paths.yaml 読み込み（現行値: assets_dir, inputs_dir, logs_dir, out_root, videos_dir）
    paths = load_yaml(cfg_dir / "paths.yaml")
    # 必須ディレクトリを確実に作成
    videos_dir = repo / paths.get("videos_dir", "tests/out/videos")
    logs_dir   = repo / paths.get("logs_dir",   "tests/out/logs")
    out_root   = repo / paths.get("out_root",   "tests/out")
    ensure_dir(videos_dir)
    ensure_dir(logs_dir)
    ensure_dir(out_root)

    # base & override を読み込み → runner用スキーマに正規化
    base_cfg_path = cfg_dir / "phaseA.base.json"
    override_path = cfg_dir / "phaseA_yaw.override.yaml"
    base_cfg = json.loads(base_cfg_path.read_text(encoding="utf-8"))
    override = load_yaml(override_path)
    final_cfg = deep_merge(base_cfg, override) if override else base_cfg
    final_cfg = to_runner_schema(final_cfg, repo)

    # ポーズ（FLAT）を決める（既定: tests/flats/yaw.flat.json）
    default_flat = repo / "tests" / "flats" / "yaw.flat.json"
    pose_path = Path(args.pose).resolve() if args.pose else default_flat
    if not pose_path.exists():
        raise FileNotFoundError(f"[run_phaseA] pose timeline not found: {pose_path}")
    final_cfg["inputs"]["pose_timeline"] = str(pose_path)

    # 出力先を固定（paths.yaml に従う）
    final_cfg["io"]["out_dir"] = str(out_root)

    # 最終設定を書き出し
    final_json = cfg_dir / "phaseA.config.json"
    final_json.write_text(json.dumps(final_cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    # ベンダーRunnerを呼び出し
    runner = repo / "vendor" / "src" / "m0_runner.py"
    cmd = [sys.executable, str(runner), "--config", str(final_json)]
    try:
        subprocess.run(cmd, check=True)
    except Exception as e:
        (logs_dir / "error.log").write_text(str(e), encoding="utf-8")
        raise

    # 生成物を所定場所へコピー
    exp_dir = Path(final_cfg["io"]["out_dir"]) / final_cfg["io"]["exp_name"]
    src_mp4 = exp_dir / "demo.mp4"
    dst_mp4 = videos_dir / "phaseA_demo.mp4"
    if src_mp4.exists():
        shutil.copy2(src_mp4, dst_mp4)
    for name in ["run.log.json", "summary.csv"]:
        p = exp_dir / name
        if p.exists():
            shutil.copy2(p, logs_dir / name)

    print(f"[OK] phaseA completed. MP4: {dst_mp4}")


if __name__ == "__main__":
    main()
