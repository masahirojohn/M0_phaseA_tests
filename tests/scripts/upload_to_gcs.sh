#!/usr/bin/env bash
set -euo pipefail

: "${GCP_SA_KEY_JSON:?Missing secret GCP_SA_KEY_JSON}"
: "${GCP_PROJECT_ID:?Missing secret GCP_PROJECT_ID}"
: "${GCS_BUCKET_NAME:?Missing secret GCS_BUCKET_NAME}"
: "${GCS_PREFIX:=runs}"

MP4_PATH="${1:?Usage: $0 /path/to/out.mp4}"
RUN_ID="${2:-$(date +%Y%m%d-%H%M%S)}"
PR_NUMBER="${PR_NUMBER:-local}"

# 一時的に鍵を展開（ローカルには残さない）
SA_FILE="$(mktemp)"
trap 'rm -f "$SA_FILE"' EXIT
printf "%s" "$GCP_SA_KEY_JSON" > "$SA_FILE"

# 認証
gcloud auth activate-service-account --key-file="$SA_FILE" --project="$GCP_PROJECT_ID" 1>/dev/null

# 宛先（例：gs://bucket/runs/PR-123/20251106-153012/demo.mp4）
BASENAME="$(basename "$MP4_PATH")"
DEST="gs://${GCS_BUCKET_NAME}/${GCS_PREFIX}/PR-${PR_NUMBER}/${RUN_ID}/${BASENAME}"

# アップロード
gsutil -h "Cache-Control:no-cache" cp -n "$MP4_PATH" "$DEST" 1>/dev/null

# 公開URL（匿名閲覧可の前提。バケットが公開不可ポリシーなら後述の署名URLに切替）
PUBLIC_URL="https://storage.googleapis.com/${GCS_BUCKET_NAME}/${GCS_PREFIX}/PR-${PR_NUMBER}/${RUN_ID}/${BASENAME}"

# 出力（標準出力にURLのみ）
echo "$PUBLIC_URL"
