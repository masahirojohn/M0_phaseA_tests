# =============================================
# tests/scripts/run_phaseA.py  (UPDATED: --transform)
# =============================================
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PhaseA runner (axis-aware view metrics + transform pass-through)
- FLATポーズを消費してM0を実行
- 実行後に view をフレーム単位で再構成し、frames.csv とジッター指標を run.log.json に追記
- 軸（yaw/pitch/roll）・front閾値・ラベルは override.yaml から切替可能
- transform 設定は configs/{phaseA,phaseT}_transform.yaml から読み込み、
  最終configに埋め込んで m0_runner へ引き渡す

例:
  # 従来どおり（変形OFF、phaseA_transform.yaml準拠）
  python tests/scripts/run_phaseA.py \
    --pose tests/flats/yaw.flat.json

  # pitchテスト + PhaseT 変形（roll+yaw/pitch係数ON）
  python tests/scripts/run_phaseA.py \
    --pose tests/flats/pitch.flat.json \
    --transform phaseT
"""

import os
import sys
import json
import shutil
import argparse
import subprocess
from pathlib import Path
from statistics import median
from collections import Counter
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


def to_runner_schema(cfg: dict, repo: Path) -> dict:
    # 旧→runner用スキーマ最小変換
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
        "render": {"crossfade_frames": 4},
        "inputs": {"pose_timeline": "timelines/pose_timeline_yaw.flat.json"},
        "atlas": {
            "atlas_json": "atlas.min.json" if "atlas.min.json" in atlas_path else atlas_path
        }
    }


# ------------------------------
# view metrics helpers
# ------------------------------
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


def _write_frames_csv(rows, path: Path):
    import csv
    ensure_dir(path.parent)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["frame", "view"])
        w.writerows(rows)


def _bucket_from_value(v: float, thr: float, zero="front", neg="neg", pos="pos"):
    if -thr <= v <= +thr:
        return zero
    return neg if v < -thr else pos


def _derive_frames_from_flat(
    flat_path: Path,
    thr_front: float,
    fps_hint: int | None = None,
    value_key: str = "yaw",
    zero_label: str = "front",
    neg_label: str = "left30",
    pos_label: str = "right30",
):
    data = json.loads(flat_path.read_text(encoding="utf-8"))
    rows, seq = [], []
    for i, item in enumerate(data):
        v = item.get(f"{value_key}_deg", item.get(value_key, 0.0))
        v = float(v)
        lab = _bucket_from_value(v, thr_front, zero_label, neg_label, pos_label)
        rows.append((i, lab))
        seq.append(lab)
    metrics = _metrics_from_seq(seq)
    metrics["fps"] = int(fps_hint or 25)
    metrics["source"] = f"derived_from_pose_flat({value_key})"
    return rows, metrics


def _maybe_load_vendor_frames(exp_dir: Path):
    p = exp_dir / "frames.csv"
    if not p.exists():
        return None
    import csv
    seq, rows = [], []
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
    runlog_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ------------------------------
# main
# ------------------------------
def main():
    repo = Path(__file__).resolve().parents[2]
    cfg_dir = repo / "configs"

    # CLI
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
        default="phaseA",
        help="どの transform 設定を使うか (phaseA=従来/ほぼOFF, phaseT=roll+yaw/pitch係数ON)",
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

    # override 自動選択（pose名に pitch/roll が含まれていれば切替）
    default_override = cfg_dir / "phaseA_yaw.override.yaml"
    pose_path = (
        Path(args.pose).resolve()
        if args.pose
        else (repo / "tests" / "flats" / "yaw.flat.json")
    )
    lower = str(pose_path.name).lower()
    if "pitch" in lower:
        override_path = cfg_dir / "phaseA_pitch.override.yaml"
    elif "roll" in lower:
        override_path = cfg_dir / "phaseA_roll.override.yaml"
    else:
        override_path = default_override

    # base & override → 正規化
    base_cfg_path = cfg_dir / "phaseA.base.json"
    base_cfg = json.loads(base_cfg_path.read_text(encoding="utf-8"))
    override = load_yaml(override_path)
    final_cfg = deep_merge(base_cfg, override) if override else base_cfg
    final_cfg = to_runner_schema(final_cfg, repo)

    if not pose_path.exists():
        raise FileNotFoundError(f"[run_phaseA] pose timeline not found: {pose_path}")
    final_cfg["inputs"]["pose_timeline"] = str(pose_path)

    # duration_s = auto → TLの最大 t_ms から算出
    if final_cfg.get("video", {}).get("duration_s") == "auto":
        pose_tl = json.loads(pose_path.read_text(encoding="utf-8"))
        max_t_ms = max(item.get("t_ms", 0) for item in pose_tl) if pose_tl else 3000
        final_cfg["video"]["duration_s"] = max_t_ms / 1000.0

    # パス正規化
    final_cfg["io"]["assets_dir"] = str(repo / final_cfg["io"]["assets_dir"])
    if "atlas" in final_cfg and "atlas_json" in final_cfg["atlas"]:
        final_cfg["atlas"]["atlas_json"] = str(
            Path(final_cfg["io"]["assets_dir"]) / final_cfg["atlas"]["atlas_json"]
        )

    # 不要なTLキーを除去
    for k in ("mouth_timeline", "expression_timeline"):
        if k in final_cfg.get("inputs", {}):
            del final_cfg["inputs"][k]

    # 出力ルート固定
    final_cfg["io"]["out_dir"] = str(out_root)

    # NEW: transform の読み込み（--transform に応じて YAML 切替）
    transform_name = args.transform or "phaseA"

    # 優先順:
    #   1) {name}_transform.override.yaml
    #   2) {name}_transform.yaml
    cand_override = cfg_dir / f"{transform_name}_transform.override.yaml"
    cand_plain    = cfg_dir / f"{transform_name}_transform.yaml"

    if cand_override.exists():
        transform_yaml_path = cand_override
    elif cand_plain.exists():
        transform_yaml_path = cand_plain
    else:
        transform_yaml_path = None

    if transform_yaml_path is not None:
        transform_yaml = load_yaml(transform_yaml_path)
    else:
        # ファイルが存在しない場合は transform 無効
        transform_yaml = {}

    # transform_yaml の構造に応じて final_cfg["transform"] を決定
    if "transform" in transform_yaml and isinstance(transform_yaml["transform"], dict):
        # 新形式: { transform: { enabled: ..., roll_coef: ... } }
        final_cfg["transform"] = transform_yaml["transform"]
    else:
        # 旧形式: enabled/roll_coef/... がトップレベルにある場合もサポート
        if any(
            k in transform_yaml
            for k in ("enabled", "roll_coef", "yaw_coef", "pitch_coef", "roll", "yaw", "pitch")
        ):
            final_cfg["transform"] = transform_yaml
        else:
            # 何も設定が無ければ transform 無効
            final_cfg["transform"] = {"enabled": False}



    # 最終設定の書き出し
    final_json = cfg_dir / "phaseA.config.json"
    final_json.write_text(
        json.dumps(final_cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 実行
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

    # 生成物コピー
    exp_dir = Path(final_cfg["io"]["out_dir"]) / final_cfg["io"]["exp_name"]
    src_mp4 = exp_dir / "demo.mp4"
    dst_mp4 = videos_dir / "phaseA_demo.mp4"
    if src_mp4.exists():
        shutil.copy2(src_mp4, dst_mp4)
    for name in ["run.log.json", "summary.csv", "frames.csv"]:
        p = exp_dir / name
        if p.exists():
            shutil.copy2(p, logs_dir / name)

    # view frames とメトリクス生成（override尊重）
    mconf = override.get("metrics", {}) if override else {}
    thr_front = float(mconf.get("thr_front", 16.0))
    value_key = mconf.get("value_key", "yaw")
    zero_label = mconf.get("zero_label", "front")
    neg_label = mconf.get("neg_label", "left30")
    pos_label = mconf.get("pos_label", "right30")

    vendor_frames = _maybe_load_vendor_frames(exp_dir)
    if vendor_frames is not None:
        rows, metrics = vendor_frames
    else:
        fps_hint = final_cfg.get("video", {}).get("fps", 25)
        rows, metrics = _derive_frames_from_flat(
            pose_path,
            thr_front=thr_front,
            fps_hint=fps_hint,
            value_key=value_key,
            zero_label=zero_label,
            neg_label=neg_label,
            pos_label=pos_label,
        )

    frames_csv = logs_dir / "frames.csv"
    _write_frames_csv(rows, frames_csv)

    runlog_path = logs_dir / "run.log.json"
    _update_run_log(runlog_path, metrics)

    print(f"[OK] phaseA completed. MP4: {dst_mp4}")
    print(f"[OK] frames.csv: {frames_csv}")
    print(f"[OK] view metrics -> {runlog_path} (metrics.view)")


if __name__ == "__main__":
    main()
