#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PhaseB runner (mouth / expression 切替テスト)

- base: configs/phaseA.base.json
- pose_timeline: --pose 引数で指定（デフォルト: tests/flats/yaw.flat.json）
- mouth_timeline:
    --pattern short → tests/assets_min/timelines/mouth_phaseB_smoke.json
    --pattern long  → tests/assets_min/timelines/mouth_phaseB_long.json
- expression_timeline:
    --pattern short → tests/assets_min/timelines/expression_phaseB_smoke.json
    --pattern long  → tests/assets_min/timelines/expression_phaseB_long.json
- transform: --transform {phaseA, phaseT}

出力:
  - tests/out/videos/phaseB_demo.mp4
  - tests/out/logs/phaseB_run.log.json
    - metrics.mouth
    - metrics.expression
"""

import os
import sys
import json
import argparse
import subprocess
from pathlib import Path
from collections import Counter
from statistics import median
import shutil
import yaml


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


def _runs(seq):
    if not seq:
        return []
    out, r = [], 1
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
        switch_count, compare_den = 0, 1
    else:
        switch_count = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
        compare_den = len(seq) - 1
    switch_rate = (switch_count / compare_den) if compare_den else 0.0
    med_run = int(median(_runs(seq))) if seq else 0
    cnt = Counter(seq)
    total = sum(cnt.values()) or 1
    breakdown = {k: {"frames": v, "ratio": v / total} for k, v in cnt.items()}
    return {
        "frames_total": len(seq),
        "switch_count": switch_count,
        "switch_rate": switch_rate,
        "runlen_median_frames": med_run,
        "breakdown": breakdown,
    }


def _update_run_log(runlog_path: Path, updates: dict):
    data = {}
    if runlog_path.exists():
        try:
            data = json.loads(runlog_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data.setdefault("metrics", {})
    # metrics.mouth / metrics.expression を上書き
    for k, v in updates.items():
        data["metrics"][k] = v
    ensure_dir(runlog_path.parent)
    runlog_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ------------------------------
# main
# ------------------------------
def main():
    repo = Path(__file__).resolve().parents[2]
    cfg_dir = repo / "configs"

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--pose",
        type=str,
        default=None,
        help="Path to FLAT pose timeline json (default: tests/flats/yaw.flat.json)",
    )
    ap.add_argument(
        "--transform",
        type=str,
        choices=["phaseA", "phaseT"],
        default="phaseT",
        help="どの transform 設定を使うか (phaseA=OFF/従来, phaseT=baseline v1)",
    )
    ap.add_argument(
        "--pattern",
        type=str,
        choices=["short", "long"],
        default="short",
        help="mouth/expression タイムラインのパターン (short=スモーク, long=セリフっぽい長尺)",
    )
    args = ap.parse_args()

    # paths.yaml
    paths = load_yaml(cfg_dir / "paths.yaml")
    videos_dir = repo / paths.get("videos_dir", "tests/out/videos")
    logs_dir = repo / paths.get("logs_dir", "tests/out/logs")
    out_root = repo / paths.get("out_root", "tests/out")
    ensure_dir(videos_dir)
    ensure_dir(logs_dir)
    ensure_dir(out_root)

    # pose_timeline
    pose_path = (
        Path(args.pose).resolve()
        if args.pose
        else (repo / "tests" / "flats" / "yaw.flat.json")
    )
    if not pose_path.exists():
        raise FileNotFoundError(f"[run_phaseB] pose timeline not found: {pose_path}")

    # base config (PhaseA base を流用)
    base_cfg_path = cfg_dir / "phaseA.base.json"
    base_cfg = json.loads(base_cfg_path.read_text(encoding="utf-8"))

    # PhaseB 用の最低限の override（exp_name だけ変える）
    exp_name = "phaseB_demo_long" if args.pattern == "long" else "phaseB_demo"
    override = {
        "io": {"exp_name": exp_name},
    }
    final_cfg = deep_merge(base_cfg, override)
    # ランナー用スキーマは phaseA.base.json 時点で整っている前提

    # inputs: pose / mouth / expression を上書き
    final_cfg.setdefault("inputs", {})
    final_cfg["inputs"]["pose_timeline"] = str(pose_path)

    # PhaseB 用サンプル TL ルート
    tl_root = repo / "tests" / "assets_min" / "timelines"
    if args.pattern == "long":
        mouth_path = tl_root / "mouth_phaseB_long.json"
        expr_path = tl_root / "expression_phaseB_long.json"
    else:
        mouth_path = tl_root / "mouth_phaseB_smoke.json"
        expr_path = tl_root / "expression_phaseB_smoke.json"

    if not mouth_path.exists():
        raise FileNotFoundError(f"[run_phaseB] mouth timeline not found: {mouth_path}")
    if not expr_path.exists():
        raise FileNotFoundError(f"[run_phaseB] expression timeline not found: {expr_path}")

    # mouth / expression のパスを最終 config に反映
    final_cfg["inputs"]["mouth_timeline"] = str(mouth_path)
    final_cfg["inputs"]["expression_timeline"] = str(expr_path)

    # duration_s = auto → pose / mouth / expression の最大 t_ms から算出（3つのうち最大を採用）
    if final_cfg.get("video", {}).get("duration_s") == "auto":
        max_t_ms = 0

        def _max_t(path: Path, key_name: str) -> int:
            try:
                tl = json.loads(path.read_text(encoding="utf-8"))
                return max(item.get("t_ms", 0) for item in tl) if tl else 0
            except Exception:
                return 0

        max_t_ms = max(
            _max_t(pose_path, "pose"),
            _max_t(mouth_path, "mouth"),
            _max_t(expr_path, "expression"),
        )
        if max_t_ms <= 0:
            max_t_ms = 3000
        final_cfg["video"]["duration_s"] = max_t_ms / 1000.0

    # パス正規化
    final_cfg["io"]["assets_dir"] = str(repo / final_cfg["io"]["assets_dir"])
    if "atlas" in final_cfg and "atlas_json" in final_cfg["atlas"]:
        final_cfg["atlas"]["atlas_json"] = str(
            Path(final_cfg["io"]["assets_dir"]) / final_cfg["atlas"]["atlas_json"]
        )

    # 出力ルート
    final_cfg["io"]["out_dir"] = str(out_root)

    # transform 読み込み（PhaseA runner と同じロジック）
    transform_name = args.transform or "phaseT"
    cand_override = cfg_dir / f"{transform_name}_transform.override.yaml"
    cand_plain = cfg_dir / f"{transform_name}_transform.yaml"
    if cand_override.exists():
        tpath = cand_override
    elif cand_plain.exists():
        tpath = cand_plain
    else:
        tpath = None

    if tpath is not None:
        transform_yaml = load_yaml(tpath)
    else:
        transform_yaml = {}

    if "transform" in transform_yaml and isinstance(transform_yaml["transform"], dict):
        final_cfg["transform"] = transform_yaml["transform"]
    else:
        if any(
            k in transform_yaml
            for k in ("enabled", "roll_coef", "yaw_coef", "pitch_coef", "roll", "yaw", "pitch")
        ):
            final_cfg["transform"] = transform_yaml
        else:
            final_cfg["transform"] = {"enabled": False}

    # 最終config書き出し
    final_json = cfg_dir / "phaseB.config.json"
    final_json.write_text(
        json.dumps(final_cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 実行
    runner = repo / "vendor" / "src" / "m0_runner.py"
    cmd = [sys.executable, str(runner), "--config", str(final_json)]
    my_env = os.environ.copy()
    my_env["PYTHONPATH"] = f"{str(repo / 'vendor')}:{my_env.get('PYTHONPATH', '')}"
    subprocess.run(cmd, check=True, env=my_env, cwd=repo)

    # 出力コピー
    exp_dir = Path(final_cfg["io"]["out_dir"]) / final_cfg["io"]["exp_name"]
    src_mp4 = exp_dir / "demo.mp4"
    dst_mp4 = videos_dir / f"{exp_name}.mp4"
    if src_mp4.exists():
        ensure_dir(dst_mp4.parent)
        shutil.copy2(src_mp4, dst_mp4)

    # mouth / expression のメトリクス計算（タイムライン定義ベース）
    metrics_updates = {}
    try:
        mouth_tl = json.loads(mouth_path.read_text(encoding="utf-8"))
        mouth_seq = [item.get("mouth", "close") for item in mouth_tl]
        metrics_updates["mouth"] = _metrics_from_seq(mouth_seq)
    except Exception:
        pass

    try:
        expr_tl = json.loads(expr_path.read_text(encoding="utf-8"))
        expr_seq = [item.get("expression", "normal") for item in expr_tl]
        metrics_updates["expression"] = _metrics_from_seq(expr_seq)
    except Exception:
        pass

    # run.log.json に書き込み（PhaseB専用）
    runlog_path = logs_dir / "phaseB_run.log.json"
    _update_run_log(runlog_path, metrics_updates)

    print(f"[OK] phaseB completed. MP4: {dst_mp4}")
    print(f"[OK] metrics.mouth/expression -> {runlog_path}")


if __name__ == "__main__":
    main()
