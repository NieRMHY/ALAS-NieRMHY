import argparse
import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

API_BASE = "https://open-api.123pan.com"
PLATFORM = "open_platform"
MAX_WORKERS = 8
SINGLE_UPLOAD_MAX_BYTES = 100 * 1024 * 1024  # 100MB — use single-step upload below this
RETRY_MAX = 10
RETRY_BACKOFF_MAX = 500


class Pan123Error(RuntimeError):
    pass


def mask(s):
    """Replace all characters with *"""
    return "*" * len(str(s))


def log(msg):
    print(mask(msg))


def info(msg):
    """Show progress info — numbers only, no paths/IDs."""
    print(msg)


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def request_with_retry(session, method, url, attempts=RETRY_MAX, timeout=(30, 600), **kwargs):
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return session.request(method, url, timeout=timeout, **kwargs)
        except requests.RequestException as e:
            last_error = e
            if attempt == attempts:
                break
            wait = min(2 ** attempt, RETRY_BACKOFF_MAX)
            time.sleep(wait)
    raise last_error


def md5_file(path):
    digest = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def api_json(session, method, url, token=None, **kwargs):
    headers = kwargs.pop("headers", {})
    headers["Platform"] = PLATFORM
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = request_with_retry(session, method, url, headers=headers, **kwargs)
    response.raise_for_status()
    data = response.json()
    if data.get("code") == 20103:
        raise Pan123Error("upload is still verifying")
    if data.get("code") != 0:
        raise Pan123Error(f"code={data.get('code')}, message={data.get('message')}")
    return data.get("data")


def get_access_token(session, client_id, client_secret):
    data = api_json(
        session,
        "POST",
        f"{API_BASE}/api/v1/access_token",
        headers={"Content-Type": "application/json"},
        json={"clientID": client_id, "clientSecret": client_secret},
    )
    return data["accessToken"]


def create_file(session, token, parent_file_id, remote_path, path):
    return api_json(
        session,
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


def _upload_one_slice(session, server, token, preupload_id, slice_no, chunk_data):
    """Upload a single slice. Runs in a thread."""
    slice_md5 = hashlib.md5(chunk_data).hexdigest()
    files = {"slice": (f"slice_{slice_no}", chunk_data, "application/octet-stream")}
    data = {
        "preuploadID": preupload_id,
        "sliceNo": str(slice_no),
        "sliceMD5": slice_md5,
    }
    for attempt in range(1, RETRY_MAX + 1):
        try:
            api_json(
                session,
                "POST",
                f"{server}/upload/v2/file/slice",
                token=token,
                data=data,
                files=files,
                timeout=(30, 300),
            )
            return slice_no
        except Exception:
            if attempt == RETRY_MAX:
                raise
            time.sleep(min(2 ** attempt, RETRY_BACKOFF_MAX))


def upload_slices_parallel(token, create_data, path):
    preupload_id = create_data["preuploadID"]
    slice_size = int(create_data["sliceSize"])
    server = create_data["servers"][0].rstrip("/")

    chunks = []
    with path.open("rb") as f:
        while True:
            chunk = f.read(slice_size)
            if not chunk:
                break
            chunks.append(chunk)

    total = len(chunks)
    total_bytes = sum(len(c) for c in chunks)
    if total == 0:
        return

    info(f"  {total} slices, {fmt_size(slice_size)} each, {fmt_size(total_bytes)} total")

    t0 = time.time()
    uploaded = [0]  # mutable counter for thread-safe-ish progress

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for i, chunk in enumerate(chunks, start=1):
            s = requests.Session()
            futures[executor.submit(_upload_one_slice, s, server, token, preupload_id, i, chunk)] = i

        done = 0
        for future in as_completed(futures):
            slice_no = future.result()
            done += 1
            pct = done * 100 // total
            elapsed = time.time() - t0
            speed = (done * slice_size) / elapsed if elapsed > 0 else 0
            info(f"  [{done}/{total}] {pct}%  {fmt_size(speed)}/s")

    elapsed = time.time() - t0
    info(f"  all slices done in {elapsed:.1f}s  avg {fmt_size(total_bytes / elapsed)}/s" if elapsed > 0 else "")


def complete_upload(session, token, preupload_id):
    for _ in range(30):
        try:
            data = api_json(
                session,
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
    raise Pan123Error("Upload was not completed")


def single_upload(session, token, parent_file_id, remote_path, path):
    """Single-step upload for small files (<100MB)."""
    info("  single-step upload...")
    domain_data = api_json(
        session,
        "GET",
        f"{API_BASE}/upload/v2/file/domain",
        token=token,
    )
    server = domain_data[0].rstrip("/")

    with path.open("rb") as f:
        file_bytes = f.read()

    files = {"file": (path.name, file_bytes, "application/octet-stream")}
    data = {
        "parentFileID": str(parent_file_id),
        "filename": remote_path,
        "etag": hashlib.md5(file_bytes).hexdigest(),
        "size": str(len(file_bytes)),
        "containDir": "true",
        "duplicate": "2",
    }
    t0 = time.time()
    for attempt in range(1, RETRY_MAX + 1):
        try:
            result = api_json(
                session,
                "POST",
                f"{server}/upload/v2/file/single/create",
                token=token,
                data=data,
                files=files,
                timeout=(30, 600),
            )
            break
        except Exception as e:
            if attempt == RETRY_MAX:
                raise
            wait = min(2 ** attempt, RETRY_BACKOFF_MAX)
            info(f"  single upload attempt {attempt} failed ({e}), retrying in {wait}s...")
            time.sleep(wait)
    elapsed = time.time() - t0
    info(f"  done in {elapsed:.1f}s ({fmt_size(len(file_bytes))}/s)")
    if result.get("completed") and result.get("fileID"):
        return result["fileID"]
    raise Pan123Error("single upload did not complete")


def upload_file(session, token, parent_file_id, local_root, path, remote_prefix):
    rel = path.relative_to(local_root).as_posix()
    remote_path = f"/{remote_prefix.strip('/')}/{rel}" if remote_prefix else f"/{rel}"
    size = path.stat().st_size

    if size <= SINGLE_UPLOAD_MAX_BYTES:
        file_id = single_upload(session, token, parent_file_id, remote_path, path)
        return file_id

    create_data = create_file(session, token, parent_file_id, remote_path, path)
    if create_data.get("reuse"):
        info("  skip — already on server")
        return create_data.get("fileID")

    upload_slices_parallel(token, create_data, path)
    file_id = complete_upload(session, token, create_data["preuploadID"])
    return file_id


def list_files(session, token, parent_file_id):
    """List all files and folders in a directory. Returns list of file objects."""
    items = []
    last_file_id = 0
    while True:
        data = api_json(
            session,
            "GET",
            f"{API_BASE}/api/v2/file/list",
            token=token,
            params={"parentFileId": parent_file_id, "limit": 100, "lastFileId": last_file_id},
        )
        for f in data.get("fileList", []):
            if not f.get("trashed"):
                items.append(f)
        last_file_id = data.get("lastFileId", -1)
        if last_file_id == -1:
            break
    return items


def trash_files(session, token, file_ids):
    """Move files to trash by file ID. Max 100 per call."""
    for i in range(0, len(file_ids), 100):
        batch = file_ids[i:i + 100]
        api_json(
            session,
            "POST",
            f"{API_BASE}/api/v1/file/trash",
            token=token,
            headers={"Content-Type": "application/json"},
            json={"fileIDs": batch},
        )


def cleanup_old_versions(session, token, parent_file_id, remote_prefix, keep_count=1):
    """Keep only the `keep_count` most recent version directories, trash the rest."""
    prefix = remote_prefix.strip("/")
    # Find the prefix directory first
    top_files = list_files(session, token, parent_file_id)
    prefix_dir = None
    for f in top_files:
        if f["type"] == 1 and f["filename"] == prefix:
            prefix_dir = f
            break
    if not prefix_dir:
        info("  no prefix dir found, skip cleanup")
        return

    # List version directories inside (these are SHA-named)
    children = list_files(session, token, prefix_dir["fileId"])
    sha_dirs = [f for f in children if f["type"] == 1 and len(f["filename"]) == 40]
    sha_dirs.sort(key=lambda f: f.get("createAt", ""), reverse=True)

    if len(sha_dirs) <= keep_count:
        info(f"  {len(sha_dirs)} versions, no cleanup needed")
        return

    old = sha_dirs[keep_count:]
    old_ids = [f["fileId"] for f in old]
    info(f"  trashing {len(old_ids)} old version(s)")
    trash_files(session, token, old_ids)

    # Also trash their contents recursively
    for old_dir in old:
        contents = list_files(session, token, old_dir["fileId"])
        content_ids = [f["fileId"] for f in contents]
        if content_ids:
            trash_files(session, token, content_ids)


def main():
    parser = argparse.ArgumentParser(description="Upload git-over-cdn files to 123pan.")
    parser.add_argument("--source", default="dist/git-over-cdn")
    parser.add_argument("--parent-file-id", type=int, default=int(os.environ.get("PAN123_PARENT_FILE_ID", "0")))
    parser.add_argument("--remote-prefix", default=os.environ.get("PAN123_REMOTE_PREFIX", "AzurPilot_master"))
    parser.add_argument("--keep-versions", type=int, default=int(os.environ.get("PAN123_KEEP_VERSIONS", "1")))
    args = parser.parse_args()
    if args.keep_versions < 1:
        parser.error("--keep-versions must be at least 1")

    client_id = os.environ["PAN123_CLIENT_ID"]
    client_secret = os.environ["PAN123_CLIENT_SECRET"]
    source = Path(args.source)

    session = requests.Session()
    token = get_access_token(session, client_id, client_secret)

    files = sorted(
        path for path in source.rglob("*")
        if path.is_file() and (path.name == "latest.json" or path.suffix == ".zip")
    )

    total = len(files)
    info(f"[0/{total}]")
    for idx, path in enumerate(files, start=1):
        info(
            f"[{idx}/{total}] "
            f"{fmt_size(path.stat().st_size)}"
        )
        for attempt in range(1, RETRY_MAX + 1):
            try:
                upload_file(session, token, args.parent_file_id, source, path, args.remote_prefix)
                break
            except Exception as e:
                info(f"  attempt {attempt} failed: {e}")
                if attempt == RETRY_MAX:
                    info(f"FAIL: {type(e).__name__}")
                    raise
                wait = min(2 ** attempt, RETRY_BACKOFF_MAX)
                info(f"  retrying in {wait}s...")
                time.sleep(wait)

    info("cleanup old versions...")
    cleanup_old_versions(session, token, args.parent_file_id, args.remote_prefix, keep_count=args.keep_versions)


if __name__ == "__main__":
    main()
