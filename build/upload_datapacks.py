
#!/usr/bin/python3

import concurrent.futures
import hashlib
import json
import os
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


# ============================================================
# Configuration
# ============================================================

CONFIG = Path("/home/firebot/git/minecraft/build/config.json")
DATAPACKS_DIR = Path("/home/firebot/git/minecraft")
UPLOAD_DIR = Path("/home/firebot/git/minecraft/build/working_dir")
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


# ============================================================
# General helpers
# ============================================================

def fail(message):
    raise RuntimeError(message)


def format_id(pack_format):
    if isinstance(pack_format, list):
        return "-".join(str(value) for value in pack_format)
    return str(pack_format)


def safe_name(name):
    return name.replace("/", "_").replace(" ", "_")


def sha512_file(path):
    digest = hashlib.sha512()

    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def load_json(path):
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as error:
        fail(f"Could not read valid JSON from {path}: {error}")


def request(method, url, token, data=None, headers=None, timeout=TIMEOUT):
    request_headers = {
        "Authorization": token,
        "User-Agent": "Fiaguhop137-Datapack-Publisher/1.0",
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


def request_with_retries(method, url, token, timeout=TIMEOUT):
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            status, headers, body = request(
                method, url, token, timeout=timeout
            )
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
# Archive content comparison
# ============================================================

def extract_archive(archive, destination):
    """Safely extract an archive without preserving timestamps."""
    with zipfile.ZipFile(archive) as zipped:
        for info in zipped.infolist():
            name = info.filename

            if not name or "\x00" in name:
                continue

            relative = Path(name)

            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError(
                    f"Unsafe path in archive {archive}: {name!r}"
                )

            target = destination / relative

            # Reject symlinks and other non-regular special file types.
            mode = info.external_attr >> 16
            file_type = stat.S_IFMT(mode)

            if file_type not in (
                0,
                stat.S_IFREG,
                stat.S_IFDIR,
            ):
                raise RuntimeError(
                    f"Unsupported special file in archive: {name!r}"
                )

            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            if file_type == stat.S_IFDIR:
                raise RuntimeError(
                    f"Invalid directory entry in archive: {name!r}"
                )

            target.parent.mkdir(parents=True, exist_ok=True)

            with zipped.open(info) as source, target.open("wb") as output:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)


def hash_directory(directory):
    """Hash file paths and contents, ignoring archive metadata."""
    digest = hashlib.sha512()

    files = sorted(
        path for path in directory.rglob("*")
        if path.is_file()
    )

    for path in files:
        relative = path.relative_to(directory).as_posix().encode("utf-8")

        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(bytes.fromhex(sha512_file(path)))

    return digest.hexdigest()


def hash_archive_contents(archive, destination):
    """Extract an archive and hash its canonical contents."""
    destination.mkdir(parents=True, exist_ok=False)
    extract_archive(archive, destination)
    return hash_directory(destination)


def download_archive(url, destination):
    """Download a public Modrinth CDN artifact to disk."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Fiaguhop137-Datapack-Publisher/1.0",
        },
    )

    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        with destination.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)


def download_archive_with_retries(url, destination):
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            download_archive(url, destination)
            return
        except (OSError, urllib.error.URLError) as error:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass

            if attempt == MAX_ATTEMPTS:
                raise RuntimeError(
                    f"Could not download existing artifact: {error}"
                ) from error

            print(
                f"Download error: {error}. "
                "Retrying in 10 seconds."
            )
            time.sleep(10)


def already_uploaded(existing_versions, local_archive, cache_dir):
    """
    Return True if any existing project artifact has identical contents.

    Existing artifact ZIP hashes are used as a quick shortcut. Otherwise,
    both archives are extracted and their path/content hashes are compared.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)

    local_zip_hash = sha512_file(local_archive)

    local_extract = cache_dir / "local-extracted"

    local_content_hash = hash_archive_contents(
        local_archive, local_extract
    )

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
            if not isinstance(url, str) or not url.startswith(
                ("https://", "http://")
            ):
                continue

            hashes = file_info.get("hashes", {})
            if not isinstance(hashes, dict):
                hashes = {}

            # Identical archive bytes guarantee identical archive contents.
            if hashes.get("sha512") == local_zip_hash:
                return True

            remote_zip = cache_dir / (
                f"remote-{version_index}-{file_index}.zip"
            )
            remote_extract = cache_dir / (
                f"remote-{version_index}-{file_index}-extracted"
            )

            print(
                f"        Comparing existing artifact "
                f"{version_index + 1}, file {file_index + 1}..."
            )

            try:
                download_archive_with_retries(url, remote_zip)

                remote_content_hash = hash_archive_contents(
                    remote_zip, remote_extract
                )

            except (
                OSError,
                RuntimeError,
                urllib.error.URLError,
                zipfile.BadZipFile,
                zipfile.LargeZipFile,
            ) as error:
                fail(
                    f"Could not verify existing artifact "
                    f"{url}: {error}"
                )

            if remote_content_hash == local_content_hash:
                return True

    return False


# ============================================================
# Multipart upload
# ============================================================

def upload_version(
    api_url,
    token,
    project_id,
    version_number,
    versions,
    upload_file,
):
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

    with upload_file.open("rb") as file:
        add_field(
            "file_payload",
            file.read(),
            "application/java-archive",
            upload_file.name,
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
# Load and validate configuration
# ============================================================

def load_config():
    if not CONFIG.is_file():
        fail(f"config.json not found: {CONFIG}")

    if not DATAPACKS_DIR.is_dir():
        fail(f"Datapacks directory not found: {DATAPACKS_DIR}")

    if not BUILDER.is_file():
        fail(f"Datapack builder not found: {BUILDER}")

    config = load_json(CONFIG)

    token = config.get("TOKEN")
    api_url = config.get("MODRINTH_API")
    formats = config.get("datapack_formats")

    if not isinstance(token, str) or not token or token == "censored":
        fail("A valid Modrinth token is required in config.json.")

    if not isinstance(api_url, str) or not api_url.startswith(
        ("https://", "http://")
    ):
        fail("MODRINTH_API must be a valid HTTP(S) URL.")

    if not isinstance(formats, dict) or not formats:
        fail("datapack_formats must be a nonempty object in config.json.")

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
            fail(
                "Minecraft version keys in datapack_formats "
                "must be strings."
            )

        if (
            isinstance(pack_format, bool)
            or not isinstance(pack_format, (int, list))
            or (
                isinstance(pack_format, list)
                and (
                    not pack_format
                    or any(
                        isinstance(value, bool) or not isinstance(value, int)
                        for value in pack_format
                    )
                )
            )
        ):
            fail(
                f"Invalid datapack format for Minecraft "
                f"{version}: {pack_format}"
            )

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    return config, token, api_url.rstrip("/"), formats


# ============================================================
# Create grouped build list
# ============================================================

def create_build_list(config, formats):
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
        if project_type != "datapack":
            continue

        project_name = config["PROJECT_NAMES"][index]

        for group in grouped.values():
            pack_format = group["format"]
            versions = group["versions"]
            representative = group["representative"]

            archive = UPLOAD_DIR / (
                f"{safe_name(project_name)}-{format_id(pack_format)}.jar"
            )

            builds.append({
                "index": index,
                "format": pack_format,
                "format_arg": json.dumps(
                    pack_format, separators=(",", ":")
                ),
                "representative": representative,
                "versions": versions,
                "versions_text": ",".join(versions),
                "upload_file": archive,
            })

    print(f"Unique datapack builds: {len(builds)}")
    print(f"Configured Minecraft versions: {len(formats)}")
    print(f"Parallel build jobs: {BUILD_JOBS}")

    if not builds:
        fail("No datapack projects are configured.")

    return builds


# ============================================================
# Build one archive
# ============================================================

def build_one(build, config):
    index = build["index"]
    project_name = config["PROJECT_NAMES"][index]
    archive = build["upload_file"]

    command = [
        "/usr/bin/python3",
        str(BUILDER),
        str(index),
        build["format_arg"],
        build["representative"],
    ]

    try:
        result = subprocess.run(
            command,
            cwd=str(BUILDER.parent),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
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

    if not archive.is_file():
        return {
            "success": False,
            "build": build,
            "output": output,
            "error": f"Builder did not create {archive}",
        }

    try:
        local_hash = sha512_file(archive)
    except OSError as error:
        return {
            "success": False,
            "build": build,
            "output": output,
            "error": f"Could not hash {archive}: {error}",
        }

    return {
        "success": True,
        "build": build,
        "output": output,
        "hash": local_hash,
        "project_name": project_name,
    }


# ============================================================
# Fetch existing Modrinth versions
# ============================================================

def fetch_versions(config, token, api_url, cache_dir):
    print("\n" + "=" * 60)
    print("FETCHING EXISTING MODRINTH VERSIONS")
    print("=" * 60)

    cache = {}

    for index, project_type in enumerate(config["TYPE"]):
        if project_type != "datapack":
            continue

        project_name = config["PROJECT_NAMES"][index]
        project_id = config["PROJECT_IDS"][index]

        print(f"\nFetching versions for {project_name}...")

        status, _, body = request_with_retries(
            "GET",
            f"{api_url}/project/{project_id}/version",
            token,
        )

        if status == 404:
            versions = []
        elif 200 <= status < 300:
            try:
                versions = json.loads(body)
            except json.JSONDecodeError as error:
                fail(f"Invalid JSON returned for {project_id}: {error}")

            if not isinstance(versions, list):
                fail(
                    f"Unexpected versions response for project {project_id}."
                )
        else:
            fail(
                f"Modrinth returned HTTP {status} for {project_id}:\n"
                f"{body.decode('utf-8', errors='replace')}"
            )

        cache[project_id] = versions

        cache_file = cache_dir / f"{project_id}.json"
        cache_file.write_text(
            json.dumps(versions, indent=2),
            encoding="utf-8",
        )

        print(f"Cached {project_name}: {len(versions)} existing version(s)")

    return cache


# ============================================================
# Upload one build
# ============================================================

def upload_one(build, config, token, api_url):
    index = build["index"]
    project_name = config["PROJECT_NAMES"][index]
    project_id = config["PROJECT_IDS"][index]

    print(f"[UPLOAD] {project_name}")
    print(f"         Format: {build['format']}")
    print(f"         Representative: {build['representative']}")
    print(f"         Versions: {build['versions_text']}")

    version_number = (
        datetime.now().strftime("%Y%m%d%H%M%S")
        + f"-{format_id(build['format'])}"
    )

    try:
        status, _, body = upload_version(
            api_url,
            token,
            project_id,
            version_number,
            build["versions"],
            build["upload_file"],
        )
    except (OSError, urllib.error.URLError) as error:
        print(f"[ERROR] Upload request failed for {project_name}: {error}")
        return False

    if 200 <= status < 300:
        print(f"[DONE ] {project_name}")
        return True

    print(f"[ERROR] Failed to upload {project_name}: HTTP {status}")
    print(body.decode("utf-8", errors="replace"))
    return False


# ============================================================
# Main
# ============================================================

def main():
    config, token, api_url, formats = load_config()
    builds = create_build_list(config, formats)

    with tempfile.TemporaryDirectory(
        prefix="datapack-publisher-"
    ) as temp:
        temp_dir = Path(temp)
        cache_dir = temp_dir / "modrinth"
        comparison_dir = temp_dir / "comparison"
        cache_dir.mkdir()
        comparison_dir.mkdir()

        # ----------------------------------------------------
        # Build phase
        # ----------------------------------------------------

        print("\n" + "=" * 60)
        print("BUILD PHASE")
        print("=" * 60)

        results = []

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

                results.append(result)

                project_name = config["PROJECT_NAMES"][build["index"]]

                if result["success"]:
                    print(
                        f"[DONE ] {project_name} "
                        f"{build['representative']} "
                        f"(format {format_id(build['format'])})"
                    )
                else:
                    print(f"[ERROR] {project_name}: {result['error']}")

        failed_builds = [
            result for result in results if not result["success"]
        ]

        if failed_builds:
            fail(
                f"{len(failed_builds)} build(s) failed. "
                "No uploads were attempted."
            )

        results_by_build = {
            id(result["build"]): result for result in results
        }

        successful_builds = [
            results_by_build[id(build)] for build in builds
        ]

        built_count = len(successful_builds)

        print("\n" + "=" * 60)
        print("BUILD PHASE COMPLETE")
        print("=" * 60)
        print(f"Unique builds: {built_count} / {len(builds)}")
        print("=" * 60)

        # ----------------------------------------------------
        # Fetch existing versions once per project
        # ----------------------------------------------------

        cache = fetch_versions(config, token, api_url, cache_dir)

        # ----------------------------------------------------
        # Upload phase
        # ----------------------------------------------------

        print("\n" + "=" * 60)
        print("UPLOAD PHASE")
        print("=" * 60)

        uploaded = 0
        skipped = 0
        failed_uploads = []

        for result in successful_builds:
            build = result["build"]
            index = build["index"]
            project_id = config["PROJECT_IDS"][index]
            project_name = config["PROJECT_NAMES"][index]

            # Use a separate comparison directory for each build.
            build_compare_dir = comparison_dir / (
                f"{index}-{format_id(build['format'])}"
            )

            try:
                if already_uploaded(
                    cache[project_id],
                    build["build"]["upload_file"],
                    build_compare_dir,
                ):
                    print(f"[SKIP ] {project_name}")
                    print(f"        Format: {build['format']}")
                    print(f"        Versions: {build['versions_text']}")
                    print("        Identical contents already published.")
                    skipped += 1
                    continue

            except (
                RuntimeError,
                OSError,
                urllib.error.URLError,
                zipfile.BadZipFile,
                zipfile.LargeZipFile,
            ) as error:
                print(
                    f"[ERROR] Could not verify existing artifacts for "
                    f"{project_name}: {error}"
                )
                failed_uploads.append(build)
                continue

            if upload_one(build, config, token, api_url):
                uploaded += 1

                # Record this upload in the cache so later builds can
                # compare against it during this same run.
                cache[project_id].append({
                    "game_versions": build["versions"],
                    "files": [{
                        "url": None,
                        "hashes": {
                            "sha512": result["hash"],
                        },
                    }],
                })
            else:
                failed_uploads.append(build)

        # ----------------------------------------------------
        # Retry failed uploads once
        # ----------------------------------------------------

        upload_failed = 0

        if failed_uploads:
            print("\n" + "=" * 60)
            print("RETRYING FAILED UPLOADS")
            print("=" * 60)
            print(f"Uploads requiring retry: {len(failed_uploads)}")

            for build in failed_uploads:
                print("\n[RETRY] Rechecking and retrying upload...")

                index = build["index"]
                project_id = config["PROJECT_IDS"][index]
                project_name = config["PROJECT_NAMES"][index]

                retry_compare_dir = comparison_dir / (
                    f"retry-{index}-{format_id(build['format'])}"
                )

                try:
                    if already_uploaded(
                        cache[project_id],
                        build["upload_file"],
                        retry_compare_dir,
                    ):
                        print(
                            f"[SKIP ] {project_name}: identical contents "
                            "already published."
                        )
                        skipped += 1
                        continue
                except (
                    RuntimeError,
                    OSError,
                    urllib.error.URLError,
                    zipfile.BadZipFile,
                    zipfile.LargeZipFile,
                ) as error:
                    print(
                        f"[ERROR] Could not verify before retrying "
                        f"{project_name}: {error}"
                    )
                    upload_failed += 1
                    continue

                if upload_one(build, config, token, api_url):
                    uploaded += 1
                else:
                    upload_failed += 1

        # ----------------------------------------------------
        # Cleanup generated JARs
        # ----------------------------------------------------

        print("\nCleaning generated JARs...")

        for archive in UPLOAD_DIR.glob("*.jar"):
            try:
                if archive.is_file() or archive.is_symlink():
                    archive.unlink()
            except OSError as error:
                print(f"[WARNING] Could not delete {archive}: {error}")

        # ----------------------------------------------------
        # Summary
        # ----------------------------------------------------

        print("\n" + "=" * 60)
        print("ALL DATAPACKS PROCESSED")
        print("=" * 60)
        print(f"Unique builds: {built_count}")
        print(f"Uploaded:      {uploaded}")
        print(f"Skipped:       {skipped}")
        print(f"Failed:        {upload_failed}")
        print("=" * 60)

        if upload_failed:
            return 1

    return 0


try:
    sys.exit(main())
except (RuntimeError, OSError, urllib.error.URLError) as error:
    print(f"\nError: {error}", file=sys.stderr)
    sys.exit(1)
