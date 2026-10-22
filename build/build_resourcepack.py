#!/usr/bin/python3

import json
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIG_FILE = SCRIPT_DIR / "config.json"
ZIP_TIMESTAMP = (2000, 1, 1, 0, 0, 0)


def fail(message):
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_config():
    try:
        with CONFIG_FILE.open(encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"Cannot read {CONFIG_FILE}: {exc}")


def format_id(value):
    return "-".join(map(str, value)) if isinstance(value, list) else str(value)


def main():
    if len(sys.argv) != 4:
        fail("Usage: build_resourcepack.py <project_index> <pack_format_json> <minecraft_version>")

    try:
        index = int(sys.argv[1])
        pack_format = json.loads(sys.argv[2])
    except (ValueError, json.JSONDecodeError):
        fail("Invalid project index or pack format JSON.")

    if index < 0:
        fail("Invalid project index.")

    config = load_config()
    try:
        name = config["PROJECT_NAMES"][index]
        source_dir = Path(config["SOURCE_DIRS"][index])
        project_type = config["TYPE"][index]
        formats = config["resourcepack_formats"]
    except (KeyError, IndexError, TypeError):
        fail(f"Invalid project index or missing configuration: {index}")

    if not source_dir.is_absolute():
        source_dir = SCRIPT_DIR / source_dir

    version = sys.argv[3]
    if project_type != "resourcepack":
        fail(f"Project is not a resource pack: {name}")
    if not isinstance(formats, dict) or formats.get(version) != pack_format:
        fail(f"Pack format does not match config.json for Minecraft {version}.")
    if not source_dir.is_dir():
        fail(f"Source directory does not exist: {source_dir}")

    if isinstance(pack_format, list):
        if len(pack_format) != 2 or any(type(v) is not int or v < 0 for v in pack_format):
            fail("Array pack formats must contain two non-negative integers.")
        metadata = {
            "pack": {
                "min_format": pack_format,
                "max_format": pack_format,
                "description": f"{name}, for Minecraft Java {version} by Fiaguhop137",
            }
        }
    else:
        if type(pack_format) is not int or pack_format < 0:
            fail("Pack format must be a non-negative integer or a two-integer array.")
        metadata = {
            "pack": {
                "pack_format": pack_format,
                "description": f"{name}, for Minecraft Java {version} by Fiaguhop137",
            }
        }

    output_dir = Path(os.environ.get("MINECRAFT_BUILD_DIR", "/tmp/minecraft-builds"))
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{name}-{format_id(pack_format)}.zip"

    print(f"Building {name} for Minecraft {version}")
    print(f"Output: {output_file}")

    with tempfile.TemporaryDirectory(prefix="resourcepack-build-") as temp:
        build_dir = Path(temp) / "build"
        build_dir.mkdir()

        for entry in source_dir.iterdir():
            if entry.name.startswith("."):
                continue
            destination = build_dir / entry.name
            if entry.is_dir() and not entry.is_symlink():
                shutil.copytree(entry, destination, symlinks=True)
            elif entry.is_symlink():
                destination.symlink_to(os.readlink(entry))
            else:
                shutil.copy2(entry, destination)

        (build_dir / "pack.mcmeta").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        temporary = output_file.with_name(f".{output_file.name}.tmp")
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                paths = sorted(
                    build_dir.rglob("*"),
                    key=lambda item: item.relative_to(build_dir).as_posix(),
                )
                for path in paths:
                    relative = path.relative_to(build_dir).as_posix()
                    is_dir = path.is_dir() and not path.is_symlink()
                    info = zipfile.ZipInfo(
                        relative + ("/" if is_dir else ""),
                        date_time=ZIP_TIMESTAMP,
                    )
                    info.create_system = 3
                    info.compress_type = zipfile.ZIP_DEFLATED

                    if is_dir:
                        info.external_attr = (0o40755 << 16) | 0x10
                        archive.writestr(info, b"")
                    elif path.is_file():
                        info.external_attr = 0o100644 << 16
                        with path.open("rb") as source, archive.open(info, "w") as out:
                            shutil.copyfileobj(source, out, length=1024 * 1024)
                    elif path.is_symlink():
                        info.external_attr = 0o120777 << 16
                        archive.writestr(info, os.readlink(path).encode())

            os.replace(temporary, output_file)
        finally:
            temporary.unlink(missing_ok=True)

    print(f"Successfully built: {output_file}")


if __name__ == "__main__":
    main()