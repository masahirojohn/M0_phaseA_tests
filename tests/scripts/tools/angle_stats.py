#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/scripts/tools/angle_stats.py
汎用：yaw/pitch/roll の flat JSON を集計し、期待比率・分位点・ジッター指標を出す。
"""
import json, argparse
from pathlib import Path
import numpy as np
import csv

def load_series(flat_path: Path, axis: str):
    data = json.loads(flat_path.read_text(encoding="utf-8"))
    key1, key2 = f"{axis}_deg", axis   # pitch_deg or pitch
    vals = []
    tms  = []
    for it in data:
        v = it.get(key1, it.get(key2, None))
        if v is None: continue
        vals.append(float(v))
        tms.append(int(it.get("t_ms", len(vals)*40)))  # fallback: 25fps相当
    return np.array(tms, dtype=np.int64), np.array(vals, dtype=np.float64)

def classify(vals, thr_deg):
    # neg / zero / pos の符号ラベル
    lbl = np.where(vals < -thr_deg, -1, np.where(vals > thr_deg, +1, 0))
    return lbl

def switch_rate(labels):
    # 隣接フレームでラベルが変わった回数 / サンプル数
    if len(labels) < 2: return 0.0, 0
    sw = int(np.sum(labels[1:] != labels[:-1]))
    rate = sw / (len(labels)-1)
    return rate, sw

def runlen_median(labels):
    # 同一ラベルの連続長の中央値（frames）
    if len(labels) == 0: return 0
    runs = []
    cur = labels[0]; cnt = 1
    for x in labels[1:]:
        if x == cur:
            cnt += 1
        else:
            runs.append(cnt)
            cur = x; cnt = 1
    runs.append(cnt)
    return int(np.median(runs)) if runs else 0

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("flat_json", help="path to yaw/pitch/roll flat json")
    ap.add_argument("--axis", choices=["yaw","pitch","roll"], required=True)
    ap.add_argument("--thr", type=float, default=8.0, help="±front閾値[deg]（期待比率計算に使用）")
    ap.add_argument("--fps", type=float, default=25.0)
    args = ap.parse_args()

    flat = Path(args.flat_json)
    out_dir = Path("tests/out/logs"); out_dir.mkdir(parents=True, exist_ok=True)

    t_ms, vals = load_series(flat, args.axis)
    n = len(vals)
    if n == 0:
        print("no samples")
        return

    # 統計
    absv = np.abs(vals)
    pcts = {p: float(np.percentile(absv, p)) for p in [50,75,90,95,99]}
    mean = float(np.mean(vals))
    std  = float(np.std(vals))
    # 速度（度/フレーム）
    dvals = np.diff(vals)
    p90_speed = float(np.percentile(np.abs(dvals), 90)) if len(dvals)>0 else 0.0

    # 期待比率（front/up/down or neg/pos）
    lab = classify(vals, args.thr)
    cnt = { -1:int(np.sum(lab==-1)), 0:int(np.sum(lab==0)), +1:int(np.sum(lab==+1)) }
    ratio = {k: (cnt[k]/n) for k in cnt}
    sw_rate, sw_cnt = switch_rate(lab)
    run_med = runlen_median(lab)

    # 推奨パラメータ（経験則ベースの目安）
    smooth = 3 if sw_rate < 0.05 else (5 if sw_rate < 0.10 else 7)
    hyst   = max(0.3, round(0.2 * p90_speed, 2))     # deg
    clamp  = float(np.ceil(pcts[95]*2)/2.0)          # 0.5刻みで丸め上げ
    offset = round(mean, 2)

    report = {
        "axis": args.axis,
        "frames": n,
        "thr_deg": args.thr,
        "ratio": {"neg": ratio[-1], "front": ratio[0], "pos": ratio[+1]},
        "counts": {"neg": cnt[-1], "front": cnt[0], "pos": cnt[+1]},
        "switch_rate": sw_rate,
        "switch_count": sw_cnt,
        "runlen_median_frames": run_med,
        "abs_deg_percentiles": pcts,
        "mean_deg": mean,
        "std_deg": std,
        "p90_speed_deg_per_frame": p90_speed,
        "recommend": {
            "smooth_window_frames": smooth,
            "hysteresis_deg": hyst,
            "clamp_deg": clamp,
            "baseline_offset_deg": offset
        }
    }

    # 保存
    js_path = out_dir / f"angle_stats_{args.axis}.json"
    js_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # シリーズCSV（後で可視化や閾値再検討に使える）
    csv_path = out_dir / f"angle_series_{args.axis}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["frame","t_ms","deg","abs_deg","delta_deg","label(-1/0/+1)"])
        prev = vals[0]
        for i,(tm,v) in enumerate(zip(t_ms, vals)):
            dv = (v - prev) if i>0 else 0.0
            lab_i = -1 if v < -args.thr else (1 if v > args.thr else 0)
            w.writerow([i, tm, round(float(v),3), round(float(abs(v)),3), round(float(dv),3), lab_i])
            prev = v

    # コンソール出力（短く）
    print(json.dumps({
        "axis": args.axis,
        "frames": n,
        "front_ratio": round(ratio[0], 4),
        "switch_rate": round(sw_rate, 4),
        "runlen_median_frames": run_med,
        "p95_abs_deg": round(pcts[95], 3),
        "recommend": report["recommend"]
    }, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
