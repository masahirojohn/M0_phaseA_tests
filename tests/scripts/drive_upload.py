#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
drive_upload.py
- サービスアカウントでGoogleドライブにファイルをアップロード
- 共有フォルダ(folder_id)に配置し、必要に応じて「リンクを知っている全員に閲覧可」にする
使い方:
  export GOOGLE_APPLICATION_CREDENTIALS=/tmp/drive_sa.json
  python tests/scripts/drive_upload.py \
    --file tests/out/videos/phaseA_demo.mp4 \
    --name phaseA_demo.mp4 \
    --folder 16GORNGJNG5k2sgBYH-vMKOKiF67ajoFt \
    --public yes
"""

import argparse
import os
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True)
    ap.add_argument("--name", required=True, help="Drive上のファイル名")
    ap.add_argument("--folder", required=True, help="アップロード先フォルダID")
    ap.add_argument("--public", choices=["yes","no"], default="no",
                    help="yesで'リンクを知っている全員'閲覧可にする")
    args = ap.parse_args()

    sa_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not sa_path or not Path(sa_path).exists():
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS が未設定 or ファイルが存在しません。")

    creds = service_account.Credentials.from_service_account_file(sa_path, scopes=SCOPES)
    service = build("drive", "v3", credentials=creds)

    media = MediaFileUpload(args.file, resumable=True)
    metadata = {"name": args.name, "parents": [args.folder]}
    f = service.files().create(body=metadata, media_body=media,
                               fields="id, webViewLink, webContentLink").execute()

    file_id = f["id"]
    if args.public == "yes":
        service.permissions().create(fileId=file_id, body={"role":"reader", "type":"anyone"}).execute()
        f = service.files().get(fileId=file_id, fields="webViewLink, webContentLink").execute()

    # プレビュー用URL（最終出力）
    print(f.get("webViewLink") or f.get("webContentLink") or f"https://drive.google.com/file/d/{file_id}/view")

if __name__ == "__main__":
    main()
