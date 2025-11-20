# tests/tools/view_logger.py
from __future__ import annotations
import os, csv, json
from statistics import median
from collections import Counter

class ViewLogger:
    def __init__(self, out_dir: str = "tests/out/logs", fps: int = 25):
        self.out_dir = out_dir
        self.fps = fps
        self.rows = []  # list of (frame, view)

    def log(self, frame_idx: int, view: str | None):
        # view が None/空でもログしてOK（後で "None" として扱う）
        self.rows.append((int(frame_idx), "" if view is None else str(view)))

    def _ensure_dir(self):
        os.makedirs(self.out_dir, exist_ok=True)

    def _write_frames_csv(self, path: str):
        self._ensure_dir()
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["frame", "view"])
            w.writerows(self.rows)

    @staticmethod
    def _runs(seq):
        """連続ラン長を返す（[2,5,1,...]）"""
        if not seq:
            return []
        runs = []
        run = 1
        for a, b in zip(seq, seq[1:]):
            if a == b:
                run += 1
            else:
                runs.append(run)
                run = 1
        runs.append(run)
        return runs

    def _metrics_from_seq(self, seq):
        # 切替率
        if len(seq) <= 1:
            switch_count = 0
            compare_den = 1
        else:
            switch_count = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
            compare_den = len(seq) - 1

        switch_rate = (switch_count / compare_den) if compare_den else 0.0

        # ラン長（中央値）
        runs = self._runs(seq)
        med_run = int(median(runs)) if runs else 0

        # 配分
        cnt = Counter(seq)
        total = sum(cnt.values()) if cnt else 1
        breakdown = {k: {"frames": v, "ratio": v / total} for k, v in cnt.items()}

        return {
            "frames_total": len(seq),
            "switch_count": switch_count,
            "switch_rate": switch_rate,      # 0.0–1.0
            "runlen_median_frames": med_run,
            "breakdown": breakdown,          # {view: {frames, ratio}}
        }

    def finalize(self):
        """frames.csv を出力し、metrics を返す"""
        frames_csv = os.path.join(self.out_dir, "frames.csv")
        self._write_frames_csv(frames_csv)
        seq = [v if v else "None" for _, v in self.rows]
        metrics = self._metrics_from_seq(seq)
        return metrics

    def update_run_log(self, runlog_path: str, metrics: dict):
        """既存 run.log.json に metrics を追記（無ければ新規作成）"""
        data = {}
        if os.path.exists(runlog_path):
            try:
                with open(runlog_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}

        # 既存の構造に影響しないよう "metrics.view" に格納
        data.setdefault("metrics", {})
        data["metrics"]["view"] = {
            "fps": self.fps,
            **metrics,
        }

        os.makedirs(os.path.dirname(runlog_path), exist_ok=True)
        with open(runlog_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
