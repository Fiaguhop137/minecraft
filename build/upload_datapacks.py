#!/usr/bin/python3

import concurrent.futures
import hashlib
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

CONFIG = Path("/home/firebot/git/minecraft/build/config.json")
BUILDER = Path("/home/firebot/git/minecraft/build/build_datapack.py")
BUILD_JOBS = 8
MAX_ATTEMPTS = 5
TIMEOUT = 120
UPLOAD_TIMEOUT = 300

os.environ.update({
    "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin",
    "HOME": "/home/firebot",
    "USER": "firebot",
    "LOGNAME": "firebot",
    "XDG_RUNTIME_DIR": "/run/user/1000",
})


def fail(message):
    raise RuntimeError(message)


def load_json(path):
    try:
        with path.open(encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"Cannot read {path}: {exc}")


def format_id(value):
    return "-".join(map(str, value)) if isinstance(value, list) else str(value)


def safe_name(value):
    return value.replace("/", "_").replace(" ", "_")


def sha512_file(path):
    digest = hashlib.sha512()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request(method, url, token, data=None, headers=None, timeout=TIMEOUT):
    request_headers = {
        "Authorization": token,
        "User-Agent": "Fiaguhop137-Datapack-Publisher/2.0",
    }
    request_headers.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def request_retry(method, url, token):
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            status, headers, body = request(method, url, token)
        except (OSError, urllib.error.URLError) as exc:
            if attempt == MAX_ATTEMPTS:
                raise RuntimeError(f"Request failed: {exc}") from exc
            print(f"Request error: {exc}. Retrying in 10 seconds.")
            time.sleep(10)
            continue
        if status != 429 or attempt == MAX_ATTEMPTS:
            return status, headers, body
        try:
            delay = max(0, int(headers.get("Retry-After", "10")))
        except (ValueError, TypeError):
            delay = 10
        print(f"Modrinth rate limit reached; retrying in {delay}s.")
        time.sleep(delay)
    fail("Request retry loop ended unexpectedly.")


def extract_archive(archive, destination):
    with zipfile.ZipFile(archive) as zipped:
        for info in zipped.infolist():
            name = info.filename
            if not name or "\x00" in name:
                continue
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError(f"Unsafe archive path: {name!r}")
            target = destination / relative
            kind = (info.external_attr >> 16) & 0o170000
            if kind not in (0, 0o100000, 0o040000):
                raise RuntimeError(f"Unsupported special file: {name!r}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)


def hash_directory(directory):
    digest = hashlib.sha512()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        relative = path.relative_to(directory).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha512_file(path)))
    return digest.hexdigest()


def hash_archive(archive, destination):
    destination.mkdir(parents=True, exist_ok=False)
    extract_archive(archive, destination)
    return hash_directory(destination)


def download_archive(url, destination):
    req = urllib.request.Request(url, headers={"User-Agent": "Fiaguhop137-Datapack-Publisher/2.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output, length=1024 * 1024)


def download_retry(url, destination):
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            download_archive(url, destination)
            return
        except (OSError, urllib.error.URLError) as exc:
            destination.unlink(missing_ok=True)
            if attempt == MAX_ATTEMPTS:
                raise RuntimeError(f"Could not download artifact: {exc}") from exc
            time.sleep(10)


def _already_uploaded(versions, archive, work):
    work.mkdir(parents=True, exist_ok=True)
    local_hash = sha512_file(archive)
    local_contents = hash_archive(archive, work / "local")

    for vi, version in enumerate(versions):
        if not isinstance(version, dict):
            continue
        for fi, item in enumerate(version.get("files", [])):
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            hashes = item.get("hashes") or {}
            if hashes.get("sha512") == local_hash:
                return True
            if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                continue
            remote_zip = work / f"remote-{vi}-{fi}.jar"
            remote_dir = work / f"remote-{vi}-{fi}"
            print(f"        Comparing existing artifact {vi + 1}, file {fi + 1}...")
            download_retry(url, remote_zip)
            try:
                if hash_archive(remote_zip, remote_dir) == local_contents:
                    return True
            finally:
                remote_zip.unlink(missing_ok=True)
                shutil.rmtree(remote_dir, ignore_errors=True)
    return False


def already_uploaded(versions, archive, work):
    try:
        return _already_uploaded(versions, archive, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def upload_version(api_url, token, project_id, version_number, versions, archive):
    boundary = "----PythonModrinth" + uuid.uuid4().hex
    metadata = {
        "project_id": project_id,
        "version_number": version_number,
        "name": f"Version {version_number}",
        "changelog": "Automated datapack release",
        "dependencies": [],
        "featured": False,
        "loaders": ["fabric"],
        "game_versions": versions,
        "version_type": "release",
        "file_parts": ["file_payload"],
        "primary_file": "file_payload",
    }
    url = urllib.parse.urlsplit(f"{api_url}/version")
    if url.scheme not in ("https", "http") or not url.hostname:
        raise RuntimeError("Invalid Modrinth API URL.")

    metadata_bytes = json.dumps(metadata, separators=(",", ":")).encode()
    prefix = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"data\"\r\n"
        "Content-Type: application/json\r\n\r\n"
    ).encode() + metadata_bytes + b"\r\n" + (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file_payload\"; "
        f"filename=\"{archive.name}\"\r\nContent-Type: application/java-archive\r\n\r\n"
    ).encode()
    suffix = f"\r\n--{boundary}--\r\n".encode()
    length = len(prefix) + archive.stat().st_size + len(suffix)
    path = url.path or "/"
    if url.query:
        path += "?" + url.query

    connection_class = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    connection = connection_class(url.hostname, url.port, timeout=UPLOAD_TIMEOUT)
    try:
        connection.putrequest("POST", path)
        connection.putheader("Authorization", token)
        connection.putheader("User-Agent", "Fiaguhop137-Datapack-Publisher/2.0")
        connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
        connection.putheader("Content-Length", str(length))
        connection.endheaders()
        connection.send(prefix)
        with archive.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                connection.send(chunk)
        connection.send(suffix)
        response = connection.getresponse()
        return response.status, dict(response.getheaders()), response.read()
    finally:
        connection.close()


def load_config():
    config = load_json(CONFIG)
    token = config.get("TOKEN")
    api_url = config.get("MODRINTH_API")
    formats = config.get("datapack_formats")
    if not isinstance(token, str) or not token or token == "censored":
        fail("A valid Modrinth token is required in config.json.")
    if not isinstance(api_url, str) or not api_url.startswith(("https://", "http://")):
        fail("MODRINTH_API must be an HTTP(S) URL.")
    if not isinstance(formats, dict) or not formats:
        fail("datapack_formats must be a nonempty object.")
    for key in ("PROJECT_NAMES", "PROJECT_IDS", "SOURCE_DIRS", "TYPE"):
        if not isinstance(config.get(key), list):
            fail(f"{key} must be an array.")
    count = len(config["PROJECT_IDS"])
    if not count or any(len(config[key]) != count for key in ("PROJECT_NAMES", "SOURCE_DIRS", "TYPE")):
        fail("Project configuration arrays must have matching nonzero lengths.")
    return config, token, api_url.rstrip("/"), formats


def create_builds(config, formats, build_dir):
    groups = {}
    for version, fmt in formats.items():
        key = json.dumps(fmt, separators=(",", ":"), sort_keys=True)
        groups.setdefault(key, {"format": fmt, "versions": [], "representative": version})
        groups[key]["versions"].append(version)

    builds = []
    for index, kind in enumerate(config["TYPE"]):
        if kind != "datapack":
            continue
        name = safe_name(config["PROJECT_NAMES"][index])
        for group in groups.values():
            fmt = group["format"]
            builds.append({
                "index": index,
                "format": fmt,
                "format_arg": json.dumps(fmt, separators=(",", ":")),
                "versions": group["versions"],
                "versions_text": ",".join(group["versions"]),
                "representative": group["representative"],
                "archive": build_dir / f"{name}-{format_id(fmt)}.jar",
            })
    if not builds:
        fail("No datapack projects are configured.")
    return builds


def build_one(build, config, build_dir):
    env = os.environ.copy()
    env["MINECRAFT_BUILD_DIR"] = str(build_dir)
    command = [
        "/usr/bin/python3", str(BUILDER), str(build["index"]),
        build["format_arg"], build["representative"],
    ]
    result = subprocess.run(
        command, cwd=str(BUILDER.parent), env=env,
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    archive = build["archive"]
    if result.returncode != 0 or not archive.is_file():
        return {"success": False, "build": build, "output": result.stdout or "",
                "error": f"Builder failed (status {result.returncode})."}
    return {"success": True, "build": build, "output": result.stdout or "",
            "hash": sha512_file(archive)}


def fetch_versions(config, token, api_url, cache_dir):
    cache = {}
    for i, kind in enumerate(config["TYPE"]):
        if kind != "datapack":
            continue
        project_id = config["PROJECT_IDS"][i]
        status, _, body = request_retry("GET", f"{api_url}/project/{project_id}/version", token)
        if status == 404:
            versions = []
        elif 200 <= status < 300:
            versions = json.loads(body)
            if not isinstance(versions, list):
                fail(f"Unexpected versions response for {project_id}.")
        else:
            fail(f"Modrinth HTTP {status}: {body.decode(errors='replace')}")
        cache[project_id] = versions
        (cache_dir / f"{project_id}.json").write_text(json.dumps(versions), encoding="utf-8")
    return cache


def upload_one(build, config, token, api_url):
    project_id = config["PROJECT_IDS"][build["index"]]
    version_number = datetime.now().strftime("%Y%m%d%H%M%S") + f"-{format_id(build['format'])}"
    status, _, body = upload_version(
        api_url, token, project_id, version_number,
        build["versions"], build["archive"],
    )
    if 200 <= status < 300:
        print(f"[DONE] {config['PROJECT_NAMES'][build['index']]} {format_id(build['format'])}")
        return True
    print(f"[ERROR] Upload HTTP {status}: {body.decode(errors='replace')}")
    return False


def main():
    config, token, api_url, formats = load_config()
    with tempfile.TemporaryDirectory(prefix="datapack-publisher-", dir="/tmp") as temp:
        root = Path(temp)
        build_dir = root / "builds"
        cache_dir = root / "cache"
        compare_dir = root / "compare"
        for directory in (build_dir, cache_dir, compare_dir):
            directory.mkdir()

        builds = create_builds(config, formats, build_dir)
        print(f"Building {len(builds)} unique datapack archives with {BUILD_JOBS} workers.")

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=BUILD_JOBS) as pool:
            futures = {pool.submit(build_one, b, config, build_dir): b for b in builds}
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result["output"]:
                    print(result["output"], end="" if result["output"].endswith("\n") else "\n")
                results.append(result)
                if not result["success"]:
                    print(f"[ERROR] {result['error']}")

        if any(not r["success"] for r in results):
            fail("At least one build failed. No uploads attempted.")

        by_id = {id(r["build"]): r for r in results}
        results = [by_id[id(b)] for b in builds]
        cache = fetch_versions(config, token, api_url, cache_dir)
        uploaded = skipped = failed = 0

        for result in results:
            build = result["build"]
            project_id = config["PROJECT_IDS"][build["index"]]
            comparison = compare_dir / f"{build['index']}-{format_id(build['format'])}"
            try:
                if already_uploaded(cache[project_id], build["archive"], comparison):
                    print(f"[SKIP] {config['PROJECT_NAMES'][build['index']]} {format_id(build['format'])}")
                    skipped += 1
                    continue
                if upload_one(build, config, token, api_url):
                    uploaded += 1
                    cache[project_id].append({
                        "files": [{"url": None, "hashes": {"sha512": result["hash"]}}]
                    })
                else:
                    failed += 1
            except Exception as exc:
                print(f"[ERROR] {config['PROJECT_NAMES'][build['index']]}: {exc}")
                failed += 1

        print(f"Datapacks complete. Built: {len(results)}, uploaded: {uploaded}, skipped: {skipped}, failed: {failed}")
        return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, urllib.error.URLError, zipfile.BadZipFile) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)