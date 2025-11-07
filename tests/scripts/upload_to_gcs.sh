#!/usr/bin/env bash
set -euo pipefail

MP4_PATH="${1:?Usage: $0 /path/to/out.mp4}"

# Execute the python script and pass the arguments
python "$(dirname "$0")/upload_to_gcs.py" "$MP4_PATH"
