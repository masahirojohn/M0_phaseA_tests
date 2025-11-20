# tests/phaseC_A/analyze_bench.py

from __future__ import annotations
import argparse
import json
from pathlib import Path
from typing import List, Sequence, Any, Dict


def _load_log(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _percentile(values: Sequence[float], q: float) -> float:
    """
    0 <= q <= 100 の単純なパーセンタイルを計算（線形補間あり）。
    """
    if not values:
        return float("nan")

    xs = sorted(values)
    n = len(xs)
    if n == 1:
        return xs[0]

    # 0〜100 → 0〜(n-1)
    pos = (n - 1) * (q / 100.0)
    i = int(pos)
    if i >= n - 1:
        return xs[-1]

    frac = pos - i
    return xs[i] * (1.0 - frac) + xs[i + 1] * frac


def _extract_frame_times_ms(data: Dict[str, Any]) -> List[float]:
    """
    bench.log.json から per-frame の render time(ms) を取り出す。
    - frame_stats: [{"render_time_ms": ...}, ...]
    - frame_times_ms: [ms0, ms1, ...]
    のどちらかがあれば使う。
    """
    # パターン1: frame_stats
    frame_stats = data.get("frame_stats")
    if isinstance(frame_stats, list) and frame_stats:
        times: List[float] = []
        for item in frame_stats:
            if isinstance(item, dict) and "render_time_ms" in item:
                try:
                    times.append(float(item["render_time_ms"]))
                except (TypeError, ValueError):
                    pass
        if times:
            return times

    # パターン2: frame_times_ms
    frame_times = data.get("frame_times_ms")
    if isinstance(frame_times, list) and frame_times:
        out: List[float] = []
        for v in frame_times:
            try:
                out.append(float(v))
            except (TypeError, ValueError):
                pass
        if out:
            return out

    # どちらも無い場合は空
    return []


def analyze(log_path: str | Path) -> None:
    data = _load_log(log_path)

    label = data.get("label", "unknown")
    frames_expected = data.get("frames_expected")
    elapsed_ms = data.get("elapsed_ms")
    avg_ms_per_frame = data.get("avg_ms_per_frame")
    fps_effective = data.get("fps_effective")

    print(f"=== M0 Benchmark Summary ===")
    print(f"label             : {label}")
    if frames_expected is not None:
        print(f"frames_expected   : {frames_expected}")
    if elapsed_ms is not None:
        print(f"elapsed_ms        : {elapsed_ms:.3f}")
    if avg_ms_per_frame is not None:
        print(f"avg_ms_per_frame  : {avg_ms_per_frame:.3f} ms")
    if fps_effective is not None:
        print(f"fps_effective     : {fps_effective:.3f} fps")
    print()

    times = _extract_frame_times_ms(data)
    if not times:
        print("※ frame_level のタイムスタンプが log に含まれていないため、")
        print("   p50/p95/p99 は計算できません。")
        print("   （必要であれば、bench_m0.py / render_video 側で per-frame 計測を追加してください）")
        return

    print(f"# frame_count      : {len(times)}")
    print(f"p50 (median)      : {_percentile(times, 50):.3f} ms")
    print(f"p95               : {_percentile(times, 95):.3f} ms")
    print(f"p99               : {_percentile(times, 99):.3f} ms")
    print(f"max               : {max(times):.3f} ms")


def main() -> None:
    ap = argparse.ArgumentParser(description="Analyze M0 benchmark log (bench.log.json)")
    ap.add_argument(
        "log_json",
        help="bench.log.json のパス",
    )
    args = ap.parse_args()
    analyze(args.log_json)


if __name__ == "__main__":
    main()
