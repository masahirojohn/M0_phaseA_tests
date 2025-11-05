#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
drive_upload.py
- サービスアカウントでGoogleドライブにファイルをアップロード
- 共有フォルダのfolder_idの中に置く（フォルダは事前にSA宛てに共有しておく）
- 任意で「リンクを知っている全員に閲覧可」に切替えて共有リンクを取得

使い方:
  export GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json
  python tests/scripts/drive_upload.py \
    --file tests/out/videos/phaseA_demo.mp4 \
    --name phaseA_demo.mp4 \
    --folder 16GORNGJNG5k2sgBYH-vMKOKiF67ajoFt \
    --public yes
"""

import argparse
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

    creds = service_account.Credentials.from_service_account_file(
        filename=Path().joinpath(
            # GOOGLE_APPLICATION_CREDENTIALS が優先されるので未指定でもOK
            # ただし google-auth は環境変数を自動参照しないので明示読込
            # ※環境変数に設定している場合は下の行を差し替えても構いません
            # 例: os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
        ),
        scopes=SCOPES
    )
    # 上の読み方が分かりづらければ、環境変数から読む書き方に差し替え可：
    # import os
    # creds = service_account.Credentials.from_service_account_file(os.environ["GOOGLE_APPLICATION_CREDENTIALS"], scopes=SCOPES)

    service = build("drive", "v3", credentials=creds)

    media = MediaFileUpload(args.file, resumable=True)
    metadata = {"name": args.name, "parents": [args.folder]}
    f = service.files().create(body=metadata, media_body=media, fields="id, webViewLink, webContentLink").execute()

    file_id = f["id"]
    web_view = f.get("webViewLink")     # Driveのプレビュー用リンク
    web_dl   = f.get("webContentLink")  # 直接ダウンロードリンク（サイズや権限で不可な場合あり）

    if args.public == "yes":
        service.permissions().create(
            fileId=file_id,
            body={"role":"reader", "type":"anyone"},
        ).execute()
        # 公開後にリンク再取得
        f2 = service.files().get(fileId=file_id, fields="webViewLink, webContentLink").execute()
        web_view = f2.get("webViewLink")
        web_dl   = f2.get("webContentLink")

    # 最後に使いやすいURLを標準出力
    print(web_view or web_dl or f"https://drive.google.com/file/d/{file_id}/view")

if __name__ == "__main__":
    main()
