import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import requests
from requests import RequestException


API_BASE = "https://open-api.123pan.com"
PLATFORM = "open_platform"


class Pan123Error(RuntimeError):
    pass


def request_with_retry(method, url, attempts=5, timeout=(30, 600), **kwargs):
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return requests.request(method, url, timeout=timeout, **kwargs)
        except RequestException as e:
            last_error = e
            if attempt == attempts:
                break
            wait = min(2 ** attempt, 30)
            print(f"request failed, retrying in {wait}s ({attempt}/{attempts}): {e}")
            time.sleep(wait)
    raise last_error


def md5_file(path):
    digest = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def api_json(method, url, token=None, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Platform"] = PLATFORM
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = request_with_retry(method, url, headers=headers, **kwargs)
    response.raise_for_status()
    data = response.json()
    if data.get("code") == 20103:
        raise Pan123Error("upload is still verifying")
    if data.get("code") != 0:
        raise Pan123Error(f"{url} failed: code={data.get('code')}, message={data.get('message')}, response={data}")
    return data.get("data")


def get_access_token(client_id, client_secret):
    data = api_json(
        "POST",
        f"{API_BASE}/api/v1/access_token",
        headers={"Content-Type": "application/json"},
        json={"clientID": client_id, "clientSecret": client_secret},
    )
    return data["accessToken"]


def create_file(token, parent_file_id, remote_path, path):
    return api_json(
        "POST",
        f"{API_BASE}/upload/v2/file/create",
        token=token,
        headers={"Content-Type": "application/json"},
        json={
            "parentFileID": parent_file_id,
            "filename": remote_path,
            "etag": md5_file(path),
            "size": path.stat().st_size,
            "duplicate": 2,
            "containDir": True,
        },
    )


def upload_slices(token, create_data, path):
    preupload_id = create_data["preuploadID"]
    slice_size = int(create_data["sliceSize"])
    server = create_data["servers"][0].rstrip("/")

    with path.open("rb") as f:
        slice_no = 1
        while True:
            chunk = f.read(slice_size)
            if not chunk:
                break
            files = {"slice": (path.name, chunk, "application/octet-stream")}
            data = {
                "preuploadID": preupload_id,
                "sliceNo": str(slice_no),
                "sliceMD5": hashlib.md5(chunk).hexdigest(),
            }
            api_json(
                "POST",
                f"{server}/upload/v2/file/slice",
                token=token,
                data=data,
                files=files,
            )
            print(f"uploaded slice {slice_no}: {path}")
            slice_no += 1


def complete_upload(token, preupload_id):
    for _ in range(30):
        try:
            data = api_json(
                "POST",
                f"{API_BASE}/upload/v2/file/upload_complete",
                token=token,
                headers={"Content-Type": "application/json"},
                json={"preuploadID": preupload_id},
            )
        except Pan123Error as e:
            if "still verifying" in str(e):
                time.sleep(1)
                continue
            raise
        if data.get("completed") and data.get("fileID"):
            return data["fileID"]
        time.sleep(1)
    raise Pan123Error(f"Upload was not completed: preuploadID={preupload_id}")


def upload_file(token, parent_file_id, local_root, path, remote_prefix):
    rel = path.relative_to(local_root).as_posix()
    remote_path = f"/{remote_prefix.strip('/')}/{rel}" if remote_prefix else f"/{rel}"
    create_data = create_file(token, parent_file_id, remote_path, path)
    if create_data.get("reuse"):
        print(f"reuse {remote_path} -> fileID={create_data.get('fileID')}")
        return create_data.get("fileID")

    upload_slices(token, create_data, path)
    file_id = complete_upload(token, create_data["preuploadID"])
    print(f"uploaded {remote_path} -> fileID={file_id}")
    return file_id


def main():
    parser = argparse.ArgumentParser(description="Upload git-over-cdn files to 123pan.")
    parser.add_argument("--source", default="dist/git-over-cdn")
    parser.add_argument("--parent-file-id", type=int, default=int(os.environ.get("PAN123_PARENT_FILE_ID", "0")))
    parser.add_argument("--remote-prefix", default=os.environ.get("PAN123_REMOTE_PREFIX", "AzurPilot_master"))
    args = parser.parse_args()

    client_id = os.environ["PAN123_CLIENT_ID"]
    client_secret = os.environ["PAN123_CLIENT_SECRET"]
    source = Path(args.source)

    token = get_access_token(client_id, client_secret)
    files = sorted(
        path for path in source.rglob("*")
        if path.is_file() and (path.name == "latest.json" or path.suffix == ".zip")
    )
    print(f"uploading {len(files)} file(s) from {source} to /{args.remote_prefix.strip('/')}")
    for path in files:
        upload_file(token, args.parent_file_id, source, path, args.remote_prefix)


if __name__ == "__main__":
    main()
