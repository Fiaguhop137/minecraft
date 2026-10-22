#!/usr/bin/python3
"""Build and publish configured Minecraft resource packs to Modrinth.

Build output is discovered from the builder's own ``Output: ...`` line, rather
than guessed from a second, potentially different output-directory setting.
Archive comparisons are removed immediately after each comparison, uploads are
streamed, and the temporary workspace is removed on success or failure.
"""

import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

CONFIG = Path("/home/firebot/git/minecraft/build/config.json")
BUILDER = Path("/home/firebot/git/minecraft/build/build_resourcepack.py")
BUILD_JOBS = 8
MAX_ATTEMPTS = 5
REQUEST_TIMEOUT = 120
UPLOAD_TIMEOUT = 300
CHUNK_SIZE = 1024 * 1024

os.environ.update({
    "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin",
    "HOME": "/home/firebot",
    "USER": "firebot",
    "LOGNAME": "firebot",
    "XDG_RUNTIME_DIR": "/run/user/1000",
})


def fail(message):
    raise RuntimeError(message)


def format_id(pack_format):
    return "-".join(map(str, pack_format)) if isinstance(pack_format, list) else str(pack_format)


def safe_name(name):
    return name.replace("/", "_")


def sha512_file(path):
    digest = hashlib.sha512()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path):
    try:
        with Path(path).open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        fail(f"Could not read valid JSON from {path}: {error}")


def request(method, url, token, data=None, headers=None, timeout=REQUEST_TIMEOUT):
    request_headers = {
        "Authorization": token,
        "User-Agent": "Fiaguhop137-ResourcePack-Publisher/1.0",
    }
    if headers:
        request_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def request_with_retries(method, url, token, timeout=REQUEST_TIMEOUT):
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            status, headers, body = request(method, url, token, timeout=timeout)
        except (OSError, urllib.error.URLError) as error:
            if attempt == MAX_ATTEMPTS:
                raise RuntimeError(f"Request failed: {error}") from error
            print(f"Request error: {error}. Retrying in 10 seconds.")
            time.sleep(10)
            continue
        if status != 429 or attempt == MAX_ATTEMPTS:
            return status, headers, body
        try:
            wait_seconds = max(0, int(headers.get("Retry-After", "10")))
        except (TypeError, ValueError):
            wait_seconds = 10
        print(f"Modrinth rate limit reached. Retrying in {wait_seconds}s...")
        time.sleep(wait_seconds)
    fail("Request retry loop ended unexpectedly.")


def extract_archive(archive, destination):
    """Extract a ZIP while rejecting unsafe paths and special files."""
    destination = Path(destination)
    with zipfile.ZipFile(archive) as zipped:
        for info in zipped.infolist():
            name = info.filename
            if not name or "\x00" in name:
                continue
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError(f"Unsafe path in archive {archive}: {name!r}")
            target = destination / relative
            mode = info.external_attr >> 16
            file_type = stat.S_IFMT(mode)
            if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise RuntimeError(f"Unsupported special file in archive: {name!r}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if file_type == stat.S_IFDIR:
                raise RuntimeError(f"Invalid directory entry in archive: {name!r}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zipped.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=CHUNK_SIZE)


def hash_directory(directory):
    digest = hashlib.sha512()
    for path in sorted(p for p in Path(directory).rglob("*") if p.is_file()):
        relative = path.relative_to(directory).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha512_file(path)))
    return digest.hexdigest()


def hash_archive_contents(archive, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    extract_archive(archive, destination)
    return hash_directory(destination)


def download_archive(url, destination):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Fiaguhop137-ResourcePack-Publisher/1.0",
    })
    with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as response:
        with Path(destination).open("wb") as output:
            shutil.copyfileobj(response, output, length=CHUNK_SIZE)


def download_archive_with_retries(url, destination):
    destination = Path(destination)
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            download_archive(url, destination)
            return
        except (OSError, urllib.error.URLError) as error:
            destination.unlink(missing_ok=True)
            if attempt == MAX_ATTEMPTS:
                raise RuntimeError(f"Could not download existing artifact: {error}") from error
            print(f"Download error: {error}. Retrying in 10 seconds.")
            time.sleep(10)


def _already_uploaded(existing_versions, local_archive, cache_dir):
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    local_zip_hash = sha512_file(local_archive)
    local_content_hash = hash_archive_contents(local_archive, cache_dir / "local-extracted")

    for version_index, version in enumerate(existing_versions):
        if not isinstance(version, dict):
            continue
        files = version.get("files", [])
        if not isinstance(files, list):
            continue
        for file_index, file_info in enumerate(files):
            if not isinstance(file_info, dict):
                continue
            url = file_info.get("url")
            if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                continue
            hashes = file_info.get("hashes", {})
            if not isinstance(hashes, dict):
                hashes = {}
            if hashes.get("sha512") == local_zip_hash:
                return True

            remote_zip = cache_dir / f"remote-{version_index}-{file_index}.zip"
            remote_extract = cache_dir / f"remote-{version_index}-{file_index}-extracted"
            print(f"        Comparing existing artifact {version_index + 1}, file {file_index + 1}...")
            try:
                download_archive_with_retries(url, remote_zip)
                remote_content_hash = hash_archive_contents(remote_zip, remote_extract)
            except (
                OSError, RuntimeError, urllib.error.URLError,
                zipfile.BadZipFile, zipfile.LargeZipFile,
            ) as error:
                fail(f"Could not verify existing artifact {url}: {error}")
            if remote_content_hash == local_content_hash:
                return True
    return False


def already_uploaded(existing_versions, local_archive, cache_dir):
    """Always remove extracted files and downloaded archives after comparison."""
    try:
        return _already_uploaded(existing_versions, local_archive, cache_dir)
    finally:
        shutil.rmtree(cache_dir, ignore_errors=True)


def upload_version(api_url, token, project_id, version_number, version_name, game_versions, archive):
    """Send multipart data while streaming the ZIP instead of buffering it in RAM."""
    boundary = "----PythonModrinth" + uuid.uuid4().hex
    metadata = {
        "project_id": project_id,
        "version_number": version_number,
        "name": version_name,
        "changelog": "Automated release",
        "dependencies": [],
        "featured": False,
        "loaders": ["minecraft"],
        "game_versions": game_versions,
        "version_type": "release",
        "file_parts": ["file_payload"],
        "primary_file": "file_payload",
    }
    metadata_bytes = json.dumps(metadata, separators=(",", ":")).encode("utf-8")
    prefix = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="data"\r\n'
        "Content-Type: application/json\r\n\r\n"
    ).encode() + metadata_bytes + b"\r\n" + (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file_payload"; filename="{Path(archive).name}"\r\n'
        "Content-Type: application/zip\r\n\r\n"
    ).encode()
    suffix = f"\r\n--{boundary}--\r\n".encode()
    archive = Path(archive)
    content_length = len(prefix) + archive.stat().st_size + len(suffix)

    # urllib supports file-like request bodies with a known Content-Length.
    class MultipartBody:
        def __init__(self, file_path):
            self.file_path = Path(file_path)
            self.parts = (prefix, suffix)
            self.length = content_length

        def __len__(self):
            return self.length

        def __iter__(self):
            yield prefix
            with self.file_path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
                    yield chunk
            yield suffix

        def read(self, amount=-1):
            # urllib's HTTP handler may call read(); provide bounded streaming.
            if not hasattr(self, "_iterator"):
                self._iterator = iter(self)
                self._buffer = b""
            if amount is None or amount < 0:
                chunks = [self._buffer]
                self._buffer = b""
                chunks.extend(self._iterator)
                return b"".join(chunks)
            while len(self._buffer) < amount:
                try:
                    self._buffer += next(self._iterator)
                except StopIteration:
                    break
            result, self._buffer = self._buffer[:amount], self._buffer[amount:]
            return result

    body = MultipartBody(archive)
    return request(
        "POST",
        f"{api_url}/version",
        token,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                 "Content-Length": str(content_length)},
        timeout=UPLOAD_TIMEOUT,
    )


def load_config():
    if not CONFIG.is_file():
        fail(f"config.json not found: {CONFIG}")
    if not BUILDER.is_file():
        fail(f"Resource-pack builder not found: {BUILDER}")
    config = load_json(CONFIG)
    token = config.get("TOKEN")
    api_url = config.get("MODRINTH_API")
    formats = config.get("resourcepack_formats")
    if not isinstance(token, str) or not token or token == "censored":
        fail("A valid Modrinth token is required in config.json.")
    if not isinstance(api_url, str) or not api_url.startswith(("https://", "http://")):
        fail("MODRINTH_API must be a valid HTTP(S) URL.")
    if not isinstance(formats, dict) or not formats:
        fail("resourcepack_formats must be a nonempty object in config.json.")
    for key in ("PROJECT_NAMES", "PROJECT_IDS", "SOURCE_DIRS", "TYPE"):
        if not isinstance(config.get(key), list):
            fail(f"{key} must be an array in config.json.")
    project_count = len(config["PROJECT_IDS"])
    if not project_count:
        fail("No projects configured.")
    for key in ("PROJECT_NAMES", "SOURCE_DIRS", "TYPE"):
        if len(config[key]) != project_count:
            fail(f"{key} contains {len(config[key])} entries; expected {project_count}.")
    for version, pack_format in formats.items():
        if not isinstance(version, str):
            fail("Minecraft version keys must be strings.")
        if (
            isinstance(pack_format, bool)
            or not isinstance(pack_format, (int, list))
            or (isinstance(pack_format, list) and (
                not pack_format or any(isinstance(v, bool) or not isinstance(v, int) for v in pack_format)
            ))
        ):
            fail(f"Invalid resource-pack format for Minecraft {version}: {pack_format}")
    return config, token, api_url.rstrip("/"), formats


def create_build_list(config, formats, build_dir):
    print("\nCreating grouped build list...")
    grouped = {}
    for version, pack_format in formats.items():
        key = json.dumps(pack_format, separators=(",", ":"), sort_keys=True)
        if key not in grouped:
            grouped[key] = {"format": pack_format, "versions": [], "representative": version}
        grouped[key]["versions"].append(version)

    builds = []
    for index, project_type in enumerate(config["TYPE"]):
        if project_type != "resourcepack":
            continue
        project_name = config["PROJECT_NAMES"][index]
        for group in grouped.values():
            pack_format = group["format"]
            archive = build_dir / f"{safe_name(project_name)}-{format_id(pack_format)}.zip"
            builds.append({
                "index": index,
                "format": pack_format,
                "format_arg": json.dumps(pack_format, separators=(",", ":")),
                "representative": group["representative"],
                "versions": group["versions"],
                "versions_text": ",".join(group["versions"]),
                "archive": archive,
            })
    print(f"Unique resource-pack builds: {len(builds)}")
    print(f"Configured Minecraft versions: {len(formats)}")
    print(f"Parallel build jobs: {BUILD_JOBS}")
    if not builds:
        fail("No resource-pack projects are configured.")
    return builds


OUTPUT_LINE = re.compile(r"^\s*Output:\s*(.+?)\s*$", re.MULTILINE)


def build_one(build, config, workspace):
    """Run the builder and use the exact archive path it reports."""
    index = build["index"]
    command = [
        "/usr/bin/python3", str(BUILDER), str(index),
        build["format_arg"], build["representative"],
    ]
    try:
        builder_env = os.environ.copy()
        builder_env["RESOURCEPACK_OUTPUT_DIR"] = str(Path(workspace) / "builds")
        builder_env["RESOURCEPACK_BUILD_DIR"] = str(Path(workspace) / "builds")
        result = subprocess.run(
            command, cwd=str(BUILDER.parent), env=builder_env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        )
    except OSError as error:
        return {"success": False, "build": build, "output": "", "error": f"Could not start builder: {error}"}

    output = result.stdout or ""
    match = OUTPUT_LINE.search(output)
    reported_archive = Path(match.group(1)).expanduser() if match else None

    if result.returncode != 0:
        return {"success": False, "build": build, "output": output,
                "error": f"Builder exited with status {result.returncode}."}
    if reported_archive is None:
        return {"success": False, "build": build, "output": output,
                "error": "Builder succeeded but did not report an 'Output: /path/to/archive.zip' line."}

    try:
        reported_archive = reported_archive.resolve(strict=True)
    except OSError:
        return {"success": False, "build": build, "output": output,
                "error": f"Builder reported an archive that does not exist: {reported_archive}"}

    if not reported_archive.is_file():
        return {"success": False, "build": build, "output": output,
                "error": f"Builder reported an output that is not a file: {reported_archive}"}

    # build_resourcepack.py currently writes to /tmp/minecraft-builds instead
    # of honoring the caller's temporary workspace. Move the completed archive
    # into this run's private workspace so later cleanup is reliable.
    target_archive = Path(build["archive"])
    target_archive.parent.mkdir(parents=True, exist_ok=True)
    try:
        if reported_archive != target_archive.resolve():
            shutil.move(str(reported_archive), str(target_archive))
        reported_archive = target_archive.resolve(strict=True)
    except OSError as error:
        return {"success": False, "build": build, "output": output,
                "error": f"Could not move builder output into the temporary workspace: {error}"}

    build["archive"] = reported_archive
    try:
        digest = sha512_file(reported_archive)
    except OSError as error:
        return {"success": False, "build": build, "output": output, "error": f"Could not hash {reported_archive}: {error}"}
    return {"success": True, "build": build, "output": output, "hash": digest}


def fetch_versions(config, token, api_url, cache_dir):
    print("\n" + "=" * 60 + "\nFETCHING EXISTING MODRINTH VERSIONS\n" + "=" * 60)
    cache = {}
    for index, project_type in enumerate(config["TYPE"]):
        if project_type != "resourcepack":
            continue
        project_name, project_id = config["PROJECT_NAMES"][index], config["PROJECT_IDS"][index]
        print(f"\nFetching versions for {project_name}...")
        status, _, body = request_with_retries("GET", f"{api_url}/project/{project_id}/version", token)
        if status == 404:
            versions = []
        elif 200 <= status < 300:
            try:
                versions = json.loads(body)
            except json.JSONDecodeError as error:
                fail(f"Invalid JSON returned for {project_id}: {error}")
            if not isinstance(versions, list):
                fail(f"Unexpected versions response for project {project_id}.")
        else:
            fail(f"Modrinth returned HTTP {status} for {project_id}:\n{body.decode('utf-8', errors='replace')}")
        cache[project_id] = versions
        (cache_dir / f"{project_id}.json").write_text(json.dumps(versions, indent=2), encoding="utf-8")
        print(f"Cached {project_name}: {len(versions)} existing version(s)")
    return cache


def upload_one(build, config, token, api_url):
    index = build["index"]
    project_name = config["PROJECT_NAMES"][index]
    project_id = config["PROJECT_IDS"][index]
    pack_format_id = format_id(build["format"])
    print(f"[UPLOAD] {project_name} format {pack_format_id}")
    print(f"         Versions: {build['versions_text']}")
    version_number = datetime.now().strftime("%Y%m%d%H%M%S") + f"-{pack_format_id}"
    try:
        status, _, body = upload_version(
            api_url, token, project_id, version_number,
            f"Pack format {pack_format_id}", build["versions"], build["archive"],
        )
    except (OSError, urllib.error.URLError, ValueError) as error:
        print(f"[ERROR] Upload request failed for {project_name}: {error}")
        return False
    if 200 <= status < 300:
        print(f"[DONE ] {project_name} format {pack_format_id}")
        return True
    print(f"[ERROR] Failed to upload {project_name} format {pack_format_id}: HTTP {status}")
    print(body.decode("utf-8", errors="replace"))
    return False


def main():
    config, token, api_url, formats = load_config()
    with tempfile.TemporaryDirectory(prefix="resourcepack-publisher-") as temp:
        workspace = Path(temp)
        build_dir = workspace / "builds"
        cache_dir = workspace / "modrinth"
        comparison_dir = workspace / "comparison"
        build_dir.mkdir()
        cache_dir.mkdir()
        comparison_dir.mkdir()
        builds = create_build_list(config, formats, build_dir)

        print("\n" + "=" * 60 + "\nBUILD PHASE\n" + "=" * 60)
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=BUILD_JOBS) as executor:
            futures = {executor.submit(build_one, build, config, workspace): build for build in builds}
            for future in concurrent.futures.as_completed(futures):
                build = futures[future]
                try:
                    result = future.result()
                except Exception as error:
                    result = {"success": False, "build": build, "output": "", "error": str(error)}
                if result["output"]:
                    print(result["output"], end="" if result["output"].endswith("\n") else "\n")
                project_name = config["PROJECT_NAMES"][build["index"]]
                if result["success"]:
                    print(f"[DONE ] {project_name} {build['representative']} (format {format_id(build['format'])})")
                else:
                    print(f"[ERROR] {project_name}: {result['error']}")
                results.append(result)

        failed_builds = [result for result in results if not result["success"]]
        if failed_builds:
            fail(f"{len(failed_builds)} build(s) failed. No uploads were attempted.")

        results_by_id = {id(result["build"]): result for result in results}
        successful_builds = [results_by_id[id(build)] for build in builds]
        print("\n" + "=" * 60 + "\nBUILD PHASE COMPLETE\n" + "=" * 60)
        print(f"Unique builds: {len(successful_builds)} / {len(builds)}")

        cache = fetch_versions(config, token, api_url, cache_dir)
        print("\n" + "=" * 60 + "\nUPLOAD PHASE\n" + "=" * 60)
        uploaded = skipped = upload_failed = 0
        failed_uploads = []

        for result in successful_builds:
            build = result["build"]
            index = build["index"]
            project_id = config["PROJECT_IDS"][index]
            project_name = config["PROJECT_NAMES"][index]
            compare_dir = comparison_dir / f"{index}-{format_id(build['format'])}"
            try:
                duplicate = already_uploaded(cache[project_id], build["archive"], compare_dir)
            except (RuntimeError, OSError, urllib.error.URLError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
                print(f"[ERROR] Could not verify existing artifacts for {project_name}: {error}")
                failed_uploads.append(build)
                continue
            if duplicate:
                print(f"[SKIP ] {project_name}\n        Format: {build['format']}\n        Versions: {build['versions_text']}\n        Identical contents already published.")
                skipped += 1
                continue
            if upload_one(build, config, token, api_url):
                uploaded += 1
                cache[project_id].append({
                    "game_versions": build["versions"],
                    "files": [{"url": None, "hashes": {"sha512": result["hash"]}}],
                })
            else:
                failed_uploads.append(build)

        if failed_uploads:
            print("\n" + "=" * 60 + "\nRETRYING FAILED UPLOADS\n" + "=" * 60)
            print(f"Uploads requiring retry: {len(failed_uploads)}")
            for build in failed_uploads:
                print("\n[RETRY] Rechecking and retrying upload...")
                index = build["index"]
                project_id = config["PROJECT_IDS"][index]
                project_name = config["PROJECT_NAMES"][index]
                compare_dir = comparison_dir / f"retry-{index}-{format_id(build['format'])}"
                try:
                    duplicate = already_uploaded(cache[project_id], build["archive"], compare_dir)
                except (RuntimeError, OSError, urllib.error.URLError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
                    print(f"[ERROR] Could not verify before retrying {project_name}: {error}")
                    upload_failed += 1
                    continue
                if duplicate:
                    print(f"[SKIP ] {project_name}: identical contents already published.")
                    skipped += 1
                elif upload_one(build, config, token, api_url):
                    uploaded += 1
                else:
                    upload_failed += 1

        print("\nCleaning generated ZIPs...")
        for archive in build_dir.glob("*.zip"):
            try:
                archive.unlink(missing_ok=True)
            except OSError as error:
                print(f"[WARNING] Could not delete {archive}: {error}")

        print("\n" + "=" * 60 + "\nALL RESOURCE PACKS PROCESSED\n" + "=" * 60)
        print(f"Minecraft versions: {len(formats)}")
        print(f"Unique builds:      {len(successful_builds)}")
        print(f"Uploaded:           {uploaded}")
        print(f"Skipped:            {skipped}")
        print(f"Failed:             {upload_failed}")
        print("=" * 60)
        return 1 if upload_failed else 0


try:
    sys.exit(main())
except (RuntimeError, OSError, urllib.error.URLError) as error:
    print(f"\nError: {error}", file=sys.stderr)
    sys.exit(1)
