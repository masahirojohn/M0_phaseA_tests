#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gcs_publish.py
- ローカルのMP4などをGCSへアップロードし、署名URL(V4, GET)を発行
- 使い方:
    export GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json
    python tests/scripts/gcs_publish.py \
        --bucket your-bucket \
        --file tests/out/videos/phaseA_demo.mp4 \
        --dest phaseA/phaseA_demo.mp4 \
        --hours 48
"""

import argparse
from pathlib import Path
from datetime import timedelta
from google.cloud import storage

def gcs_upload_and_sign(bucket_name: str, local_path: str, remote_key: str, hours: int = 48) -> str:
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(remote_key)
    blob.upload_from_filename(local_path)  # アップロード
    url = blob.generate_signed_url(
        version="v4",
        method="GET",
        expiration=timedelta(hours=hours),
    )
    return url

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--file", required=True, help="local path to upload")
    ap.add_argument("--dest", required=True, help="gcs object key (e.g. phaseA/phaseA_demo.mp4)")
    ap.add_argument("--hours", type=int, default=48)
    args = ap.parse_args()

    lp = Path(args.file)
    if not lp.exists():
        raise FileNotFoundError(lp)

    url = gcs_upload_and_sign(args.bucket, str(lp), args.dest, args.hours)
    print(url)  # 標準出力にURLだけ吐く（Jules側で拾う想定）

if __name__ == "__main__":
    main()
