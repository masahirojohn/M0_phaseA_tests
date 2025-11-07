#!/usr/bin/env python3
import os
import sys
import json
import argparse
from google.cloud import storage
from google.oauth2 import service_account

def upload_to_gcs(local_file_path, remote_key):
    """Uploads a file to a GCS bucket and returns the public URL."""
    gcp_sa_key_json = os.environ.get("GCP_SA_KEY_JSON")
    gcp_project_id = os.environ.get("GCP_PROJECT_ID")
    gcs_bucket_name = os.environ.get("GCS_BUCKET_NAME")

    if not all([gcp_sa_key_json, gcp_project_id, gcs_bucket_name]):
        raise ValueError("Missing required environment variables for GCS upload.")

    try:
        credentials_info = json.loads(gcp_sa_key_json)
        credentials = service_account.Credentials.from_service_account_info(credentials_info)
        storage_client = storage.Client(project=gcp_project_id, credentials=credentials)
    except json.JSONDecodeError:
        raise ValueError("Failed to decode GCP_SA_KEY_JSON.")

    bucket = storage_client.bucket(gcs_bucket_name)
    blob = bucket.blob(remote_key)

    blob.upload_from_filename(local_file_path, content_type="video/mp4")

    public_url = f"https://storage.googleapis.com/{gcs_bucket_name}/{remote_key}"
    return public_url

def main():
    parser = argparse.ArgumentParser(description="Upload a file to GCS and print the public URL.")
    parser.add_argument("local_file_path", help="The path to the local file to upload.")
    parser.add_argument("remote_key", help="The destination key/name for the file in GCS.")
    args = parser.parse_args()

    try:
        public_url = upload_to_gcs(args.local_file_path, args.remote_key)
        print(public_url)
    except Exception as e:
        print(f"Error during GCS upload: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
