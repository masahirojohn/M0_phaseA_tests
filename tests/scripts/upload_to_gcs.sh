#!/usr/bin/env bash
set -euo pipefail

# === required secrets (Jules側で環境変数として注入) ===
: "${GCP_SA_KEY_JSON:?Missing secret GCP_SA_KEY_JSON}"
: "${GCP_PROJECT_ID:?Missing secret GCP_PROJECT_ID}"
: "${GCS_BUCKET_NAME:?Missing secret GCS_BUCKET_NAME}"

# === optional ===
GCS_PREFIX="${GCS_PREFIX:-runs}"
PR_NUMBER="${PR_NUMBER:-local}"

# === args ===
MP4_PATH="${1:?Usage: $0 /path/to/out.mp4 [RUN_ID]}"
RUN_ID="${2:-$(date +%Y%m%d-%H%M%S)}"

# 0) 入力チェック
if [ ! -f "$MP4_PATH" ]; then
  echo "[ERROR] File not found: $MP4_PATH" >&2
  exit 1
fi

# 1) ローカルMP4の健全性チェック（小さすぎるファイルは弾く）
#    Linux/macOS 両対応で stat を試す
BYTES=$(stat -c%s "$MP4_PATH" 2>/dev/null || stat -f%z "$MP4_PATH" 2>/dev/null || echo 0)
if [ "${BYTES:-0}" -lt 200000 ]; then
  echo "[ERROR] MP4 too small (${BYTES} bytes): $MP4_PATH" >&2
  exit 3
fi
echo "[INFO] Local MP4 size: ${BYTES} bytes"

# 2) SAキーを一時ファイルに展開（終了時に削除）
SA_FILE="$(mktemp)"
trap 'rm -f "$SA_FILE"' EXIT
printf "%s" "$GCP_SA_KEY_JSON" > "$SA_FILE"

# 3) 認証
gcloud auth activate-service-account --key-file="$SA_FILE" --project="$GCP_PROJECT_ID" 1>/dev/null

# 4) 宛先（例：gs://bucket/runs/PR-123/20251107-120000/phaseA_demo.mp4）
BASENAME="$(basename "$MP4_PATH")"
REMOTE_KEY="${GCS_PREFIX}/PR-${PR_NUMBER}/${RUN_ID}/${BASENAME}"
DEST="gs://${GCS_BUCKET_NAME}/${REMOTE_KEY}"

# 5) アップロード（上書きする。Content-Typeを明示、キャッシュ無効化）
gsutil -h "Cache-Control:no-cache" \
       -h "Content-Type:video/mp4" \
       cp "$MP4_PATH" "$DEST" 1>/dev/null

# 6) 公開URL（バケットが allUsers: objectViewer 前提）
PUBLIC_URL="https://storage.googleapis.com/${GCS_BUCKET_NAME}/${REMOTE_KEY}"
echo "$PUBLIC_URL"
