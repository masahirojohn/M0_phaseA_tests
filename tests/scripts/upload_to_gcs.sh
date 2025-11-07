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
BYTES=$(stat -c%s "$MP4_PATH" 2>/dev/null || stat -f%z "$MP4_PATH" 2>/dev/null || echo 0)
if [ "${BYTES:-0}" -lt 200000 ]; then
  echo "[ERROR] MP4 too small (${BYTES} bytes): $MP4_PATH" >&2
  exit 3
fi
echo "[INFO] Local MP4 size: ${BYTES} bytes"

# 2) 宛先（例：gs://bucket/runs/PR-123/20251107-120000/phaseA_demo.mp4）
BASENAME="$(basename "$MP4_PATH")"
REMOTE_KEY="${GCS_PREFIX}/PR-${PR_NUMBER}/${RUN_ID}/${BASENAME}"

# 3) Pythonスクリプトでアップロード
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
PUBLIC_URL=$(python "$SCRIPT_DIR/upload_to_gcs.py" "$MP4_PATH" "$REMOTE_KEY")

# 4) 結果を出力
echo "$PUBLIC_URL"
