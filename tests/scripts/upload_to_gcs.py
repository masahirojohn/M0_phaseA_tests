
import os
import sys
import json
from datetime import datetime
from google.oauth2 import service_account
from google.cloud import storage

def upload_to_gcs(local_file_path):
    """Uploads a file to GCS and returns its public URL."""

    # --- (1) Get configuration from environment variables ---
    try:
        gcp_sa_key_json = os.environ["GCP_SA_KEY_JSON"]
        gcp_project_id = os.environ["GCP_PROJECT_ID"]
        gcs_bucket_name = os.environ["GCS_BUCKET_NAME"]
    except KeyError as e:
        print(f"[ERROR] Missing environment variable: {e}", file=sys.stderr)
        sys.exit(1)

    gcs_prefix = os.getenv("GCS_PREFIX", "runs")
    pr_number = os.getenv("PR_NUMBER", "local")
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    # --- (2) Authenticate ---
    try:
        credentials_info = json.loads(gcp_sa_key_json)
        credentials = service_account.Credentials.from_service_account_info(credentials_info)
        storage_client = storage.Client(project=gcp_project_id, credentials=credentials)
    except Exception as e:
        print(f"[ERROR] Authentication failed: {e}", file=sys.stderr)
        sys.exit(1)

    # --- (3) Define GCS destination path ---
    basename = os.path.basename(local_file_path)
    destination_blob_name = f"{gcs_prefix}/PR-{pr_number}/{run_id}/{basename}"

    # --- (4) Upload the file ---
    try:
        bucket = storage_client.bucket(gcs_bucket_name)
        blob = bucket.blob(destination_blob_name)

        # To prevent caching issues
        blob.cache_control = "no-cache"

        blob.upload_from_filename(local_file_path)

    except Exception as e:
        print(f"[ERROR] Upload failed: {e}", file=sys.stderr)
        sys.exit(1)

    # --- (5) Return the public URL ---
    public_url = blob.public_url

    # The default public_url is https://storage.googleapis.com/...
    # The script uses a slightly different format, let's stick to it.
    # Re-create the URL to match the shell script's output format.
    formatted_url = f"https://storage.googleapis.com/{gcs_bucket_name}/{destination_blob_name}"

    return formatted_url

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <path_to_local_file>", file=sys.stderr)
        sys.exit(1)

    file_path = sys.argv[1]
    if not os.path.exists(file_path):
        print(f"[ERROR] File not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    url = upload_to_gcs(file_path)
    print(url)
