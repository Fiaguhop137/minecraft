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
    sys.exit(1)


def load_config():
    if not CONFIG_FILE.is_file():
        fail(f"config.json not found: {CONFIG_FILE}")

    try:
        with CONFIG_FILE.open(encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"Cannot read config.json: {exc}")


def main():
    if len(sys.argv) != 4:
        fail(
            "Usage: build_resourcepack.py "
            "<project_index> <pack_format> "
            "<representative_minecraft_version>"
        )

    index_arg, format_arg, version = sys.argv[1:]

    try:
        project_index = int(index_arg)
        pack_format = json.loads(format_arg)
    except (ValueError, json.JSONDecodeError):
        fail("Project index must be an integer and pack format must be valid JSON.")

    if project_index < 0:
        fail(f"Invalid project index: {project_index}")

    config = load_config()

    try:
        project_name = config["PROJECT_NAMES"][project_index]
        source_dir = Path(config["SOURCE_DIRS"][project_index])
        project_type = config["TYPE"][project_index]
        upload_dir = Path(config["UPLOAD_DIR"])
    except (KeyError, IndexError, TypeError):
        fail(f"Invalid project index or missing configuration: {project_index}")

    if not isinstance(project_name, str) or not project_name:
        fail("Invalid project name in config.json.")

    if project_type != "resourcepack":
        fail(f"Project is not a resource pack: {project_name}")

    if not str(config.get("UPLOAD_DIR", "")).strip():
        fail("UPLOAD_DIR is missing from config.json.")

    # Resolve relative paths against the script directory.
    if not source_dir.is_absolute():
        source_dir = SCRIPT_DIR / source_dir

    if not upload_dir.is_absolute():
        upload_dir = SCRIPT_DIR / upload_dir

    # Validate the Minecraft pack format.
    formats = config.get("resourcepack_formats", {})

    if not isinstance(formats, dict) or version not in formats:
        fail(f"Minecraft version is not listed in config.json: {version}")

    expected_format = formats[version]

    if pack_format != expected_format:
        fail(
            "Supplied pack format does not match config.json.\n"
            f"Minecraft: {version}\n"
            f"Expected:  {json.dumps(expected_format)}\n"
            f"Received:  {json.dumps(pack_format)}"
        )

    is_format_array = isinstance(pack_format, list)

    if is_format_array:
        if (
            len(pack_format) != 2
            or any(type(value) is not int or value < 0
                   for value in pack_format)
        ):
            fail("Array pack formats must contain two non-negative integers.")
        format_id = f"{pack_format[0]}-{pack_format[1]}"
    else:
        if type(pack_format) is not int or pack_format < 0:
            fail("Pack format must be a non-negative integer or a two-integer array.")
        format_id = str(pack_format)

    if not source_dir.is_dir():
        fail(f"Source directory does not exist: {source_dir}")

    output_file = upload_dir / f"{project_name}-{format_id}.zip"
    description = (
        f"{project_name}, for Minecraft Java {version} by Fiaguhop137"
    )

    print()
    print("=" * 60)
    print("Building resource pack")
    print(f"Project:       {project_name}")
    print(f"Minecraft:     {version}")
    print(f"Pack format:   {json.dumps(pack_format)}")
    print(f"Source:        {source_dir}")
    print(f"Output:        {output_file}")
    print("=" * 60)

    upload_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="resourcepack-") as temp:
        build_dir = Path(temp) / "build"
        build_dir.mkdir()

        # Copy visible top-level entries, matching the old ./* behavior.
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

        # Generate pack.mcmeta. Any source version is overwritten.
        if is_format_array:
            metadata = {
                "pack": {
                    "min_format": pack_format,
                    "max_format": pack_format,
                    "description": description,
                }
            }
        else:
            metadata = {
                "pack": {
                    "pack_format": pack_format,
                    "description": description,
                }
            }

        (build_dir / "pack.mcmeta").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        # Build a deterministic ZIP, excluding top-level hidden entries.
        # Write to a temporary archive first so a failed build doesn't
        # destroy an existing successful output.
        temporary_zip = Path(temp) / "output.zip"

        with zipfile.ZipFile(
            temporary_zip, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            paths = sorted(
                build_dir.rglob("*"),
                key=lambda path: path.relative_to(build_dir).as_posix(),
            )

            for path in paths:
                relative_path = path.relative_to(build_dir).as_posix()
                info = zipfile.ZipInfo(
                    relative_path + ("/" if path.is_dir() else ""),
                    date_time=ZIP_TIMESTAMP,
                )
                info.create_system = 3

                if path.is_dir():
                    info.external_attr = (0o40755 << 16) | 0x10
                    archive.writestr(info, b"")
                elif path.is_file():
                    info.external_attr = (0o100644 << 16)
                    archive.writestr(
                        info,
                        path.read_bytes(),
                        compress_type=zipfile.ZIP_DEFLATED,
                    )

        temporary_output = output_file.with_name(
            f".{output_file.name}.tmp"
        )
        try:
            shutil.copyfile(temporary_zip, temporary_output)
            os.replace(temporary_output, output_file)
        finally:
            temporary_output.unlink(missing_ok=True)

    print()
    print("Successfully built:")
    print(output_file)


if __name__ == "__main__":
    main()
