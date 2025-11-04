#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_pr_body.py
- summary.csv を軽く要約（1行目ヘッダをキーに辞書化）
- サムネを列挙
- 署名URLを差し込み、PR本文(Markdown)を標準出力へ
- 使い方:
    python tests/scripts/make_pr_body.py \
        --summary tests/out/logs/summary.csv \
        --thumb_dir tests/out/thumbs \
        --video_url "https://signed.example.com/..."
"""

import argparse
import csv
import sys
from pathlib import Path

def read_summary(path: Path):
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows[0] if rows else {}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", required=False, default="tests/out/logs/summary.csv")
    ap.add_argument("--thumb_dir", required=False, default="tests/out/thumbs")
    ap.add_argument("--video_url", required=True)
    args = ap.parse_args()

    summary = read_summary(Path(args.summary))
    thumbs = sorted(Path(args.thumb_dir).glob("*.png"))

    # --- Markdown ---
    print("## Results")
    print("")
    print(f"- **Video (signed URL, ~48h):** [{args.video_url}]({args.video_url})")
    print("")
    if summary:
        print("### Metrics")
        print("")
        print("| key | value |")
        print("| --- | ----- |")
        for k, v in summary.items():
            print(f"| {k} | {v} |")
        print("")
    if thumbs:
        print("### Thumbnails")
        print("")
        for t in thumbs:
            # GitHubは相対パス画像をPRで表示しづらいので、ここはファイル名のみ列挙に留める
            print(f"- {t.name}")
        print("")
    print("> Artifactsを使わず、外部ストレージの署名URLだけを掲載する最軽量モード。")

if __name__ == "__main__":
    main()
