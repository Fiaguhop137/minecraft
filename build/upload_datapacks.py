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
BUILD_TIMEOUT = 600
MAX_ATTEMPTS = 5
TIMEOUT = 120
UPLOAD_TIMEOUT = 300
USER_AGENT = "Fiaguhop137-Datapack-Publisher/2.1"

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
    return value.replace("/", "_").replace("\\", "_").replace(" ", "_")


def sha512_file(path):
    digest = hashlib.sha512()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request(method, url, token, data=None, headers=None, timeout=TIMEOUT):
    request_headers = {"Authorization": token, "User-Agent": USER_AGENT}
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
                raise RuntimeError(f"Request failed after {attempt} attempts: {exc}") from exc
            print(f"Request error: {exc}. Retrying in 10 seconds.")
            time.sleep(10)
            continue
        if status == 429 and attempt < MAX_ATTEMPTS:
            try:
                delay = max(0, int(headers.get("Retry-After", "10")))
            except (ValueError, TypeError):
                delay = 10
            print(f"Modrinth rate limit reached; retrying in {delay}s.")
            time.sleep(delay)
            continue
        if 500 <= status <= 599 and attempt < MAX_ATTEMPTS:
            delay = min(10 * attempt, 30)
            print(f"Modrinth returned HTTP {status}; retrying in {delay}s.")
            time.sleep(delay)
            continue
        return status, headers, body
    fail("Request retry loop ended unexpectedly.")


def extract_archive(archive, destination):
    with zipfile.ZipFile(archive) as zipped:
        for info in zipped.infolist():
            name = info.filename
            if not name or "\x00" in name:
                continue
            normalized = name.replace("\\", "/")
            relative = Path(normalized)
            if relative.is_absolute() or ".." in relative.parts or (relative.parts and relative.parts[0].endswith(":")):
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
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
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
                raise RuntimeError(f"Could not download artifact after {attempt} attempts: {exc}") from exc
            time.sleep(10)


def _already_uploaded(versions, archive, work):
    work.mkdir(parents=True, exist_ok=True)
    local_hash = sha512_file(archive)
    local_contents = hash_archive(archive, work / "local")
    comparison_failures = []

    for vi, version in enumerate(versions):
        if not isinstance(version, dict):
            continue
        files = version.get("files", [])
        if not isinstance(files, list):
            continue
        for fi, item in enumerate(files):
            if not isinstance(item, dict):
                continue
            hashes = item.get("hashes") or {}
            if isinstance(hashes, dict) and hashes.get("sha512") == local_hash:
                return True
            url = item.get("url")
            if not isinstance(url, str) or not url.startswith("https://"):
                continue
            remote_zip = work / f"remote-{vi}-{fi}.zip"
            remote_dir = work / f"remote-{vi}-{fi}"
            print(f"        Comparing existing artifact {vi + 1}, file {fi + 1}...")
            try:
                download_retry(url, remote_zip)
                if hash_archive(remote_zip, remote_dir) == local_contents:
                    return True
            except (OSError, RuntimeError, urllib.error.URLError, zipfile.BadZipFile) as exc:
                comparison_failures.append(f"{url}: {exc}")
            finally:
                remote_zip.unlink(missing_ok=True)
                shutil.rmtree(remote_dir, ignore_errors=True)

    if comparison_failures:
        extra = len(comparison_failures) - 1
        suffix = f" (and {extra} more comparison failure(s))" if extra else ""
        raise RuntimeError(
            "Duplicate check incomplete; refusing to upload. First failure: "
            f"{comparison_failures[0]}{suffix}"
        )
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
        "loaders": ["minecraft"],
        "game_versions": versions,
        "version_type": "release",
        "file_parts": ["file_payload"],
        "primary_file": "file_payload",
    }
    url = urllib.parse.urlsplit(f"{api_url}/version")
    if url.scheme != "https" or not url.hostname:
        raise RuntimeError("Modrinth API URL must be a valid HTTPS URL.")
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
    connection = http.client.HTTPSConnection(url.hostname, url.port, timeout=UPLOAD_TIMEOUT)
    try:
        connection.putrequest("POST", path)
        connection.putheader("Authorization", token)
        connection.putheader("User-Agent", USER_AGENT)
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
    if not isinstance(config, dict):
        fail("config.json must contain a JSON object.")
    token = config.get("TOKEN")
    api_url = config.get("MODRINTH_API")
    formats = config.get("datapack_formats")
    if not isinstance(token, str) or not token or token == "censored":
        fail("A valid Modrinth token is required in config.json.")
    if not isinstance(api_url, str):
        fail("MODRINTH_API must be an HTTPS URL.")
    parsed = urllib.parse.urlsplit(api_url)
    if parsed.scheme != "https" or not parsed.hostname:
        fail("MODRINTH_API must be a valid HTTPS URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        fail("MODRINTH_API must not contain credentials, a query string, or a fragment.")
    if not isinstance(formats, dict) or not formats:
        fail("datapack_formats must be a nonempty object.")
    for key in ("PROJECT_NAMES", "PROJECT_IDS", "SOURCE_DIRS", "TYPE"):
        if not isinstance(config.get(key), list):
            fail(f"{key} must be an array.")
    count = len(config["PROJECT_IDS"])
    if not count or any(len(config[key]) != count for key in ("PROJECT_NAMES", "SOURCE_DIRS", "TYPE")):
        fail("Project configuration arrays must have matching nonzero lengths.")
    for i, kind in enumerate(config["TYPE"]):
        if kind == "datapack":
            if not isinstance(config["PROJECT_NAMES"][i], str) or not config["PROJECT_NAMES"][i]:
                fail(f"PROJECT_NAMES[{i}] must be a nonempty string.")
            if not isinstance(config["PROJECT_IDS"][i], str) or not config["PROJECT_IDS"][i]:
                fail(f"PROJECT_IDS[{i}] must be a nonempty string.")
    for version, fmt in formats.items():
        if not isinstance(version, str) or not version:
            fail("Every datapack_formats key must be a nonempty Minecraft version string.")
        if not isinstance(fmt, (str, int, float, list, dict)):
            fail(f"Unsupported format value for Minecraft {version}: {fmt!r}")
    return config, token, api_url.rstrip("/"), formats


def create_builds(config, formats, build_dir):
    groups = {}
    for version, fmt in formats.items():
        key = json.dumps(fmt, separators=(",", ":"), sort_keys=True)
        groups.setdefault(key, {"format": fmt, "versions": [], "representative": version})
        groups[key]["versions"].append(version)
    builds = []
    archive_paths = set()
    for index, kind in enumerate(config["TYPE"]):
        if kind != "datapack":
            continue
        name = safe_name(config["PROJECT_NAMES"][index])
        for group in groups.values():
            fmt = group["format"]
            archive = build_dir / f"{name}-{format_id(fmt)}.jar"
            if archive in archive_paths:
                fail(f"Archive filename collision detected: {archive.name}")
            archive_paths.add(archive)
            builds.append({
                "index": index,
                "format": fmt,
                "format_arg": json.dumps(fmt, separators=(",", ":")),
                "versions": group["versions"],
                "versions_text": ",".join(group["versions"]),
                "representative": group["representative"],
                "archive": archive,
            })
    if not builds:
        fail("No datapack projects are configured.")
    return builds


def build_one(build, build_dir):
    env = os.environ.copy()
    env["MINECRAFT_BUILD_DIR"] = str(build_dir)
    command = ["/usr/bin/python3", str(BUILDER), str(build["index"]), build["format_arg"], build["representative"]]
    try:
        result = subprocess.run(
            command, cwd=str(BUILDER.parent), env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=BUILD_TIMEOUT, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        return {"success": False, "build": build, "output": output,
                "error": f"Builder timed out after {BUILD_TIMEOUT} seconds."}
    except OSError as exc:
        return {"success": False, "build": build, "output": "",
                "error": f"Could not start builder: {exc}"}
    archive = build["archive"]
    if result.returncode != 0 or not archive.is_file():
        return {"success": False, "build": build, "output": result.stdout or "",
                "error": f"Builder failed (status {result.returncode}) or did not create {archive.name}."}
    return {"success": True, "build": build, "output": result.stdout or "",
            "hash": sha512_file(archive)}


def fetch_versions(config, token, api_url, cache_dir):
    cache = {}
    for i, kind in enumerate(config["TYPE"]):
        if kind != "datapack":
            continue
        project_id = config["PROJECT_IDS"][i]
        encoded_id = urllib.parse.quote(project_id, safe="")
        status, _, body = request_retry("GET", f"{api_url}/project/{encoded_id}/version", token)
        if status == 404:
            fail(f"Modrinth returned HTTP 404 for project {project_id}. Check PROJECT_IDS; refusing to treat a missing project as empty.")
        if not 200 <= status < 300:
            fail(f"Modrinth HTTP {status} for project {project_id}: {body.decode(errors='replace')}")
        try:
            versions = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            fail(f"Modrinth returned invalid JSON for project {project_id}: {exc}")
        if not isinstance(versions, list):
            fail(f"Unexpected versions response for {project_id}: expected a JSON array.")
        cache[project_id] = versions
        (cache_dir / f"{safe_name(project_id)}.json").write_text(json.dumps(versions), encoding="utf-8")
    return cache


def upload_one(build, config, token, api_url):
    project_id = config["PROJECT_IDS"][build["index"]]
    version_number = datetime.now().strftime("%Y%m%d%H%M%S") + f"-{format_id(build['format'])}"
    status, _, body = upload_version(api_url, token, project_id, version_number,
                                     build["versions"], build["archive"])
    if 200 <= status < 300:
        print(f"[DONE] {config['PROJECT_NAMES'][build['index']]} {format_id(build['format'])}")
        return True
    print(f"[ERROR] Upload HTTP {status}: {body.decode(errors='replace')}")
    return False


def main():
    config, token, api_url, formats = load_config()
    if not BUILDER.is_file():
        fail(f"Builder script does not exist: {BUILDER}")
    with tempfile.TemporaryDirectory(prefix="datapack-publisher-", dir="/tmp") as temp:
        root = Path(temp)
        build_dir, cache_dir, compare_dir = root / "builds", root / "cache", root / "compare"
        for directory in (build_dir, cache_dir, compare_dir):
            directory.mkdir()
        builds = create_builds(config, formats, build_dir)
        print(f"Building {len(builds)} unique datapack archives with {BUILD_JOBS} workers.")
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=BUILD_JOBS) as pool:
            futures = {pool.submit(build_one, build, build_dir): build for build in builds}
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result["output"]:
                    print(result["output"], end="" if result["output"].endswith("\n") else "\n")
                results.append(result)
                if not result["success"]:
                    print(f"[ERROR] {result['error']}")
        if any(not result["success"] for result in results):
            fail("At least one build failed. No uploads attempted.")
        by_id = {id(result["build"]): result for result in results}
        results = [by_id[id(build)] for build in builds]
        cache = fetch_versions(config, token, api_url, cache_dir)
        uploaded = skipped = failed = 0
        for result in results:
            build = result["build"]
            project_id = config["PROJECT_IDS"][build["index"]]
            comparison = compare_dir / f"{build['index']}-{safe_name(format_id(build['format']))}"
            try:
                if already_uploaded(cache[project_id], build["archive"], comparison):
                    print(f"[SKIP] {config['PROJECT_NAMES'][build['index']]} {format_id(build['format'])}")
                    skipped += 1
                    continue
                if upload_one(build, config, token, api_url):
                    uploaded += 1
                    cache[project_id].append({"files": [{"url": None, "hashes": {"sha512": result["hash"]}}]})
                else:
                    failed += 1
            except Exception as exc:
                print(f"[ERROR] {config['PROJECT_NAMES'][build['index']]} {format_id(build['format'])}: {exc}")
                failed += 1
        print(f"Datapacks complete. Built: {len(results)}, uploaded: {uploaded}, skipped: {skipped}, failed: {failed}")
        return 1 if failed else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, urllib.error.URLError, zipfile.BadZipFile) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
