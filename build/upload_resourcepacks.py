#!/usr/bin/python3

import concurrent.futures
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path


# ============================================================
# Configuration
# ============================================================

CONFIG = Path("/home/firebot/git/minecraft/build/config.json")
BUILDER = Path("/home/firebot/git/minecraft/build/build_resourcepack.py")

BUILD_JOBS = 8
MAX_ATTEMPTS = 5
REQUEST_TIMEOUT = 120
UPLOAD_TIMEOUT = 300

os.environ.update({
    "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin",
    "HOME": "/home/firebot",
    "USER": "firebot",
    "LOGNAME": "firebot",
    "XDG_RUNTIME_DIR": "/run/user/1000",
})


# ============================================================
# Helpers
# ============================================================

def fail(message):
    raise RuntimeError(message)


def format_id(pack_format):
    if isinstance(pack_format, list):
        return "-".join(str(value) for value in pack_format)
    return str(pack_format)


def load_json(path):
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        fail(f"Could not read JSON from {path}: {error}")


def sha512_file(path):
    digest = hashlib.sha512()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def request(method, url, token, data=None, headers=None, timeout=REQUEST_TIMEOUT):
    request_headers = {
        "Authorization": token,
        "User-Agent": "Fiaguhop137-ResourcePack-Publisher/1.0",
    }

    if headers:
        request_headers.update(headers)

    req = urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read()

    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read()


def request_with_retries(method, url, token):
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            status, headers, body = request(method, url, token)
        except (OSError, urllib.error.URLError) as error:
            if attempt == MAX_ATTEMPTS:
                raise RuntimeError(f"Request failed: {error}") from error

            print(f"Request error: {error}. Retrying in 10 seconds.")
            time.sleep(10)
            continue

        if status != 429 or attempt == MAX_ATTEMPTS:
            return status, headers, body

        try:
            wait_seconds = int(headers.get("Retry-After", "10"))
            if wait_seconds < 0:
                wait_seconds = 10
        except (TypeError, ValueError):
            wait_seconds = 10

        print("Modrinth rate limit reached.")
        print(f"Retrying in {wait_seconds}s...")
        time.sleep(wait_seconds)

    fail("Request retry loop ended unexpectedly.")


# ============================================================
# Multipart upload
# ============================================================

def upload_version(api_url, token, project_id, version_number,
                   version_name, game_versions, archive):
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

    body = bytearray()

    def add_field(name, value, content_type=None, filename=None):
        body.extend(f"--{boundary}\r\n".encode())

        disposition = f'Content-Disposition: form-data; name="{name}"'

        if filename is not None:
            disposition += f'; filename="{filename}"'

        body.extend((disposition + "\r\n").encode())

        if content_type:
            body.extend(f"Content-Type: {content_type}\r\n".encode())

        body.extend(b"\r\n")
        body.extend(value)
        body.extend(b"\r\n")

    add_field(
        "data",
        json.dumps(metadata, separators=(",", ":")).encode("utf-8"),
        "application/json",
    )

    with archive.open("rb") as file:
        add_field(
            "file_payload",
            file.read(),
            "application/zip",
            archive.name,
        )

    body.extend(f"--{boundary}--\r\n".encode())

    return request(
        "POST",
        f"{api_url}/version",
        token,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        timeout=UPLOAD_TIMEOUT,
    )


# ============================================================
# Configuration validation
# ============================================================

def load_config():
    if not CONFIG.is_file():
        fail(f"config.json not found: {CONFIG}")

    if not BUILDER.is_file():
        fail(f"Resource-pack builder not found: {BUILDER}")

    config = load_json(CONFIG)

    token = config.get("TOKEN")
    api_url = config.get("MODRINTH_API")
    upload_dir_value = config.get("UPLOAD_DIR")
    formats = config.get("resourcepack_formats")

    if not isinstance(token, str) or not token or token == "censored":
        fail("Modrinth token is missing from config.json.")

    if not isinstance(api_url, str) or not api_url.startswith(
        ("https://", "http://")
    ):
        fail("MODRINTH_API must be a valid HTTP(S) URL.")

    if not isinstance(upload_dir_value, str) or not upload_dir_value:
        fail("UPLOAD_DIR is missing from config.json.")

    if not isinstance(formats, dict) or not formats:
        fail("resourcepack_formats must be a nonempty object in config.json.")

    for key in ("PROJECT_NAMES", "PROJECT_IDS", "SOURCE_DIRS", "TYPE"):
        if not isinstance(config.get(key), list):
            fail(f"{key} must be an array in config.json.")

    project_count = len(config["PROJECT_IDS"])

    if project_count == 0:
        fail("No projects configured.")

    for key in ("PROJECT_NAMES", "SOURCE_DIRS", "TYPE"):
        if len(config[key]) != project_count:
            fail(
                f"{key} contains {len(config[key])} entries; "
                f"expected {project_count}."
            )

    for version, pack_format in formats.items():
        if not isinstance(version, str):
            fail("Minecraft version keys must be strings.")

        if isinstance(pack_format, bool) or not isinstance(
            pack_format, (int, list)
        ):
            fail(f"Invalid resource-pack format for {version}: {pack_format}")

        if isinstance(pack_format, list) and (
            not pack_format
            or any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in pack_format
            )
        ):
            fail(f"Invalid resource-pack format for {version}: {pack_format}")

    upload_dir = Path(upload_dir_value)
    upload_dir.mkdir(parents=True, exist_ok=True)

    return config, token, api_url.rstrip("/"), formats, upload_dir


# ============================================================
# Build list
# ============================================================

def create_build_list(config, formats, upload_dir):
    print("\nCreating grouped build list...")

    grouped = {}

    for version, pack_format in formats.items():
        key = json.dumps(pack_format, separators=(",", ":"), sort_keys=True)

        if key not in grouped:
            grouped[key] = {
                "format": pack_format,
                "versions": [],
                "representative": version,
            }

        grouped[key]["versions"].append(version)

    builds = []

    for index, project_type in enumerate(config["TYPE"]):
        if project_type != "resourcepack":
            continue

        project_name = config["PROJECT_NAMES"][index]

        for group in grouped.values():
            pack_format = group["format"]
            versions = group["versions"]
            representative = group["representative"]

            archive = upload_dir / (
                f"{project_name}-{format_id(pack_format)}.zip"
            )

            builds.append({
                "index": index,
                "format": pack_format,
                "format_arg": json.dumps(
                    pack_format, separators=(",", ":")
                ),
                "representative": representative,
                "versions": versions,
                "archive": archive,
            })

    print(f"Resource-pack builds required: {len(builds)}")
    print(f"Minecraft versions configured: {len(formats)}")
    print(f"Parallel build jobs:            {BUILD_JOBS}")

    if not builds:
        fail("No resource-pack projects are configured.")

    return builds


# ============================================================
# Build one archive
# ============================================================

def build_one(build, config):
    project_name = config["PROJECT_NAMES"][build["index"]]

    command = [
        "/usr/bin/python3",
        str(BUILDER),
        str(build["index"]),
        build["format_arg"],
        build["representative"],
    ]

    try:
        result = __import__("subprocess").run(
            command,
            cwd=str(BUILDER.parent),
            stdout=__import__("subprocess").PIPE,
            stderr=__import__("subprocess").STDOUT,
            text=True,
            check=False,
        )
    except OSError as error:
        return {
            "success": False,
            "build": build,
            "output": "",
            "error": f"Could not start builder: {error}",
        }

    output = result.stdout or ""

    if result.returncode != 0:
        return {
            "success": False,
            "build": build,
            "output": output,
            "error": f"Builder exited with status {result.returncode}.",
        }

    if not build["archive"].is_file():
        return {
            "success": False,
            "build": build,
            "output": output,
            "error": f"Builder did not create {build['archive']}",
        }

    try:
        digest = sha512_file(build["archive"])
    except OSError as error:
        return {
            "success": False,
            "build": build,
            "output": output,
            "error": f"Could not hash archive: {error}",
        }

    return {
        "success": True,
        "build": build,
        "output": output,
        "hash": digest,
        "project_name": project_name,
    }


# ============================================================
# Upload one build
# ============================================================

def upload_one(build, config, token, api_url):
    index = build["index"]
    project_name = config["PROJECT_NAMES"][index]
    project_id = config["PROJECT_IDS"][index]
    pack_format_id = format_id(build["format"])
    versions = build["versions"]

    print(f"[UPLOAD] {project_name} format {pack_format_id}")
    print(f"         Versions: {','.join(versions)}")

    version_number = (
        datetime.now().strftime("%Y%m%d%H%M%S")
        + f"-{pack_format_id}"
    )

    try:
        status, _, body = upload_version(
            api_url,
            token,
            project_id,
            version_number,
            f"Pack format {pack_format_id}",
            versions,
            build["archive"],
        )
    except (OSError, urllib.error.URLError) as error:
        print(f"[ERROR] Upload request failed: {error}")
        return False

    if 200 <= status < 300:
        print(f"[DONE ] {project_name} format {pack_format_id}")
        return True

    print(
        f"[ERROR] Failed to upload {project_name} "
        f"format {pack_format_id}: HTTP {status}"
    )
    print(body.decode("utf-8", errors="replace"))
    return False


# ============================================================
# Main
# ============================================================

def main():
    config, token, api_url, formats, upload_dir = load_config()
    builds = create_build_list(config, formats, upload_dir)

    # --------------------------------------------------------
    # Build phase
    # --------------------------------------------------------

    print("\n" + "=" * 60)
    print("BUILD PHASE")
    print("=" * 60)

    results_by_id = {}

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=BUILD_JOBS
    ) as executor:
        futures = {
            executor.submit(build_one, build, config): build
            for build in builds
        }

        for future in concurrent.futures.as_completed(futures):
            build = futures[future]

            try:
                result = future.result()
            except Exception as error:
                result = {
                    "success": False,
                    "build": build,
                    "output": "",
                    "error": str(error),
                }

            if result["output"]:
                print(result["output"], end="")
                if not result["output"].endswith("\n"):
                    print()

            results_by_id[id(build)] = result

            project_name = config["PROJECT_NAMES"][build["index"]]

            if result["success"]:
                print(
                    f"[DONE ] {project_name} "
                    f"format {format_id(build['format'])}"
                )
            else:
                print(f"[ERROR] {project_name}: {result['error']}")

    results = [results_by_id[id(build)] for build in builds]
    failed_builds = [result for result in results if not result["success"]]

    if failed_builds:
        fail(
            f"{len(failed_builds)} build(s) failed. "
            "No uploads were attempted."
        )

    built_count = len(results)

    print("\n" + "=" * 60)
    print("BUILD PHASE COMPLETE")
    print(f"Unique builds: {built_count} / {len(builds)}")
    print("=" * 60)

    # --------------------------------------------------------
    # Upload phase
    # --------------------------------------------------------

    print("\n" + "=" * 60)
    print("UPLOAD PHASE")
    print("=" * 60)

    uploaded = 0
    upload_failed = 0
    retry_list = []

    for result in results:
        build = result["build"]

        if upload_one(build, config, token, api_url):
            uploaded += 1
        else:
            retry_list.append(build)

    # --------------------------------------------------------
    # Retry failed uploads once
    # --------------------------------------------------------

    if retry_list:
        print("\n" + "=" * 60)
        print("RETRYING FAILED UPLOADS")
        print("=" * 60)
        print(f"Uploads requiring retry: {len(retry_list)}")

        for build in retry_list:
            print("\n[RETRY] Retrying upload...")

            if upload_one(build, config, token, api_url):
                uploaded += 1
            else:
                upload_failed += 1

    # --------------------------------------------------------
    # Cleanup generated ZIPs
    # --------------------------------------------------------

    print("\nCleaning generated ZIPs...")

    for build in builds:
        archive = build["archive"]

        try:
            if archive.is_file() or archive.is_symlink():
                archive.unlink()
        except OSError as error:
            print(f"[WARNING] Could not delete {archive}: {error}")

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print("\n" + "=" * 60)
    print("ALL RESOURCE PACKS PROCESSED")
    print("=" * 60)
    print(f"Minecraft versions: {len(formats)}")
    print(f"Unique builds:      {built_count}")
    print(f"Uploaded:           {uploaded}")
    print(f"Failed:             {upload_failed}")
    print("=" * 60)

    return 1 if upload_failed else 0


try:
    sys.exit(main())
except (RuntimeError, OSError, urllib.error.URLError) as error:
    print(f"\nError: {error}", file=sys.stderr)
    sys.exit(1)
