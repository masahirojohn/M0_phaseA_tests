#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PhaseA runner (with view metrics)
- v1→flat 変換後の FLAT ポーズを消費して M0 を実行
- 実行後に FLAT ポーズから view をフレーム単位で再構成し、
  frames.csv とジッター指標（切替率/ラン長中央値/配分）を run.log.json に追記

既定:
    python tests/scripts/run_phaseA.py
    python tests/scripts/run_phaseA.py --pose tests/flats/yaw.flat.json
"""

import os
import sys
import json
import shutil
import argparse
import subprocess
from pathlib import Path
import yaml
from statistics import median
from collections import Counter

# ------------------------------
# utils
# ------------------------------
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
            "pose_timeline": "timelines/pose_timeline_yaw.flat.json"
        },
        "atlas": {
            "atlas_json": "atlas.min.json" if "atlas.min.json" in atlas_path else atlas_path
        }
    }

# ------------------------------
# view metrics (frames.csv + metrics)
# ------------------------------
def _runs(seq):
    if not seq:
        return []
    out = []
    r = 1
    for a, b in zip(seq, seq[1:]):
        if a == b:
            r += 1
        else:
            out.append(r)
            r = 1
    out.append(r)
    return out

def _metrics_from_seq(seq):
    if len(seq) <= 1:
        switch_count = 0
        compare_den = 1
    else:
        switch_count = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
        compare_den = len(seq) - 1
    switch_rate = (switch_count / compare_den) if compare_den else 0.0
    runs = _runs(seq)
    med_run = int(median(runs)) if runs else 0
    cnt = Counter(seq)
    total = sum(cnt.values()) or 1
    breakdown = {k: {"frames": v, "ratio": v / total} for k, v in cnt.items()}
    return {
        "frames_total": len(seq),
        "switch_count": switch_count,
        "switch_rate": switch_rate,           # 0.0–1.0
        "runlen_median_frames": med_run,
        "breakdown": breakdown,
    }

def _write_frames_csv(rows, path: Path):
    import csv
    ensure_dir(path.parent)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["frame", "view"])
        w.writerows(rows)

def _bucket_from_yaw(yaw_deg: float, thr_front: float = 16.0) -> str:
    # front: [-thr, +thr] / left30: < -thr / right30: > +thr
    if -thr_front <= yaw_deg <= +thr_front:
        return "front"
    return "left30" if yaw_deg < -thr_front else "right30"

def _derive_frames_from_flat(flat_path: Path, thr_front: float, fps_hint: int | None = None):
    """
    FLAT ポーズ（[{t_ms, yaw_deg, ...}, ...]）から frame→view を再構成
    - FLAT が 1frame=1要素（25fps相当）で並んでいる前提
    - fps_hint はメトリクスの付加情報としてのみ使用
    """
    data = json.loads(flat_path.read_text(encoding="utf-8"))
    rows = []
    seq = []
    for i, item in enumerate(data):
        yaw = float(item.get("yaw_deg", item.get("yaw", 0.0)))
        v = _bucket_from_yaw(yaw, thr_front=thr_front)
        rows.append((i, v))
        seq.append(v)
    metrics = _metrics_from_seq(seq)
    # fps はヒントとして保持（無指定なら 25）
    metrics["fps"] = int(fps_hint or 25)
    metrics["source"] = "derived_from_pose_flat"
    return rows, metrics

def _maybe_load_vendor_frames(exp_dir: Path):
    """
    ベンダーが frames.csv を出した場合に利用する（なければ None を返す）
    期待形式: frame,view
    """
    p = exp_dir / "frames.csv"
    if not p.exists():
        return None
    import csv
    seq = []
    rows = []
    with p.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        if "frame" not in r.fieldnames or "view" not in r.fieldnames:
            return None
        for row in r:
            try:
                fi = int(row["frame"])
            except Exception:
                continue
            v = row.get("view") or "None"
            rows.append((fi, v))
            seq.append(v)
    if not rows:
        return None
    metrics = _metrics_from_seq(seq)
    metrics["source"] = "vendor_frames_csv"
    return rows, metrics

def _update_run_log(runlog_path: Path, view_metrics: dict):
    data = {}
    if runlog_path.exists():
        try:
            data = json.loads(runlog_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data.setdefault("metrics", {})
    data["metrics"]["view"] = view_metrics
    ensure_dir(runlog_path.parent)
    runlog_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# ------------------------------
# main
# ------------------------------
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
    videos_dir = repo / paths.get("videos_dir", "tests/out/videos")
    logs_dir   = repo / paths.get("logs_dir",   "tests/out/logs")
    out_root   = repo / paths.get("out_root",   "tests/out")
    ensure_dir(videos_dir); ensure_dir(logs_dir); ensure_dir(out_root)

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

    # duration_s が "auto" ならポーズTLのmax t_msから計算
    if final_cfg.get("video", {}).get("duration_s") == "auto":
        pose_tl = json.loads(pose_path.read_text(encoding="utf-8"))
        max_t_ms = max(item.get("t_ms", 0) for item in pose_tl) if pose_tl else 3000
        final_cfg["video"]["duration_s"] = max_t_ms / 1000.0

    # assets_dir を絶対パス化
    final_cfg["io"]["assets_dir"] = str(repo / final_cfg["io"]["assets_dir"])
    if "atlas" in final_cfg and "atlas_json" in final_cfg["atlas"]:
        final_cfg["atlas"]["atlas_json"] = str(Path(final_cfg["io"]["assets_dir"]) / final_cfg["atlas"]["atlas_json"])

    # 不要なタイムライン設定を削除
    if "mouth_timeline" in final_cfg["inputs"]:
        del final_cfg["inputs"]["mouth_timeline"]
    if "expression_timeline" in final_cfg["inputs"]:
        del final_cfg["inputs"]["expression_timeline"]

    # 出力先を固定（paths.yaml に従う）
    final_cfg["io"]["out_dir"] = str(out_root)

    # 最終設定を書き出し
    final_json = cfg_dir / "phaseA.config.json"
    final_json.write_text(json.dumps(final_cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    # ------------------------------
    # 実行
    # ------------------------------
    runner = repo / "vendor" / "src" / "m0_runner.py"
    cmd = [sys.executable, str(runner), "--config", str(final_json)]
    try:
        my_env = os.environ.copy()
        vendor_path = str(repo / "vendor")
        my_env["PYTHONPATH"] = f"{vendor_path}:{my_env.get('PYTHONPATH', '')}"
        subprocess.run(cmd, check=True, env=my_env, cwd=repo)
    except Exception as e:
        (logs_dir / "error.log").write_text(str(e), encoding="utf-8")
        raise

    # 生成物を所定場所へコピー
    exp_dir = Path(final_cfg["io"]["out_dir"]) / final_cfg["io"]["exp_name"]
    src_mp4 = exp_dir / "demo.mp4"
    dst_mp4 = videos_dir / "phaseA_demo.mp4"
    if src_mp4.exists():
        shutil.copy2(src_mp4, dst_mp4)
    for name in ["run.log.json", "summary.csv", "frames.csv"]:
        p = exp_dir / name
        if p.exists():
            shutil.copy2(p, logs_dir / name)

    # ------------------------------
    # view frames とメトリクス生成
    # ------------------------------
    # 閾値を override から拾う（無ければ 16.0）
    thr_front = float(override.get("metrics", {}).get("thr_front", 16.0))
    
    # 1) ベンダーが frames.csv を吐いていればそれを優先
    vendor_frames = _maybe_load_vendor_frames(exp_dir)
    if vendor_frames is not None:
        rows, metrics = vendor_frames
    else:
        # 2) 無ければ FLAT ポーズから派生
        thr_front = 16.0  # 閾値（必要なら override から拾う設計に拡張可）
        fps_hint = final_cfg.get("video", {}).get("fps", 25)
        rows, metrics = _derive_frames_from_flat(pose_path, thr_front=thr_front, fps_hint=fps_hint)

    frames_csv = logs_dir / "frames.csv"
    _write_frames_csv(rows, frames_csv)

    # run.log.json を更新（metrics.view を追記）
    runlog_path = logs_dir / "run.log.json"
    _update_run_log(runlog_path, metrics)

    print(f"[OK] phaseA completed. MP4: {dst_mp4}")
    print(f"[OK] frames.csv: {frames_csv}")
    print(f"[OK] view metrics -> {runlog_path} (metrics.view)")

if __name__ == "__main__":
    main()
