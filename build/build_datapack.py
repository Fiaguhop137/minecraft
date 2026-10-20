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


def load_json(path):
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"Cannot read {path}: {exc}")


def write_json(path, data):
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def resolve_path(value):
    path = Path(value)
    return path if path.is_absolute() else SCRIPT_DIR / path


def format_id(pack_format):
    if isinstance(pack_format, list):
        return "-".join(map(str, pack_format))
    return str(pack_format)


def validate_format(pack_format):
    if type(pack_format) is int and pack_format >= 0:
        return

    if (
        isinstance(pack_format, list)
        and len(pack_format) == 2
        and all(type(value) is int and value >= 0 for value in pack_format)
    ):
        return

    fail("Pack format must be a non-negative integer or a two-integer array.")


def update_fabric_metadata(path, version):
    metadata = load_json(path)

    if not isinstance(metadata, dict):
        fail("fabric.mod.json must contain a JSON object.")

    depends = metadata.get("depends") or {}

    if not isinstance(depends, dict):
        fail("fabric.mod.json 'depends' must be a JSON object.")

    depends = dict(depends)
    depends["minecraft"] = ">=" + version

    # Preserve the fields selected by the original jq filter.
    updated = {
        "schemaVersion": metadata.get("schemaVersion", 1),
        "id": metadata.get("id"),
        "version": version,
        "name": metadata.get("name"),
        "environment": metadata.get("environment", "*"),
        "depends": depends,
        "entrypoints": metadata.get("entrypoints", {}),
        "mixins": metadata.get("mixins", []),
    }

    write_json(path, updated)


def update_pack_metadata(path, pack_format):
    metadata = load_json(path)

    if not isinstance(metadata, dict):
        fail("pack.mcmeta must contain a JSON object.")

    pack = metadata.setdefault("pack", {})

    if not isinstance(pack, dict):
        fail("pack.mcmeta 'pack' must be a JSON object.")

    pack["min_format"] = pack_format
    pack["max_format"] = pack_format

    write_json(path, metadata)


def create_jar(source_dir, output_file):
    with tempfile.NamedTemporaryFile(
        prefix=".datapack-",
        suffix=".jar",
        dir=output_file.parent,
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)

    try:
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            paths = sorted(
                source_dir.rglob("*"),
                key=lambda path: path.relative_to(source_dir).as_posix(),
            )

            for path in paths:
                relative = path.relative_to(source_dir).as_posix()
                info = zipfile.ZipInfo(
                    relative + ("/" if path.is_dir() and not path.is_symlink() else ""),
                    date_time=ZIP_TIMESTAMP,
                )
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED

                if path.is_symlink():
                    info.external_attr = (0o120777 << 16)
                    archive.writestr(info, os.readlink(path).encode("utf-8"))

                elif path.is_dir():
                    info.external_attr = (0o40755 << 16) | 0x10
                    archive.writestr(info, b"")

                elif path.is_file():
                    info.external_attr = (0o100644 << 16)
                    archive.writestr(info, path.read_bytes())

                else:
                    fail(f"Unsupported filesystem entry: {path}")

        os.replace(temporary_path, output_file)

    finally:
        temporary_path.unlink(missing_ok=True)


def main():
    if len(sys.argv) != 4:
        fail(
            "Usage: build_datapack.py "
            "<project_index> <pack_format> <representative_minecraft_version>"
        )

    index_arg, format_arg, version = sys.argv[1:]

    try:
        project_index = int(index_arg)
        pack_format = json.loads(format_arg)
    except (ValueError, json.JSONDecodeError):
        fail("Project index must be an integer and pack format must be valid JSON.")

    if project_index < 0:
        fail(f"Invalid project index: {project_index}")

    validate_format(pack_format)

    if not version:
        fail("Minecraft version cannot be empty.")

    config = load_json(CONFIG_FILE)

    try:
        project_name = config["PROJECT_NAMES"][project_index]
        source_dir = resolve_path(config["SOURCE_DIRS"][project_index])
        project_type = config["TYPE"][project_index]
        upload_dir = resolve_path(config["UPLOAD_DIR"])
    except (KeyError, IndexError, TypeError):
        fail(f"Invalid project index or missing configuration: {project_index}")

    if not isinstance(project_name, str) or not project_name:
        fail("Invalid project name in config.json.")

    if project_type != "datapack":
        fail(f"Project is not a datapack: {project_name}")

    if not upload_dir.is_dir() and upload_dir.exists():
        fail(f"Upload path is not a directory: {upload_dir}")

    formats = config.get("datapack_formats")

    if not isinstance(formats, dict) or version not in formats:
        fail(f"Minecraft version is not listed in datapack_formats: {version}")

    expected_format = formats[version]

    if pack_format != expected_format:
        fail(
            "Supplied pack format does not match config.json.\n"
            f"Minecraft version: {version}\n"
            f"Expected format:   {json.dumps(expected_format)}\n"
            f"Supplied format:   {json.dumps(pack_format)}"
        )

    if not source_dir.is_dir():
        fail(f"Source directory does not exist: {source_dir}")

    for required_file in ("fabric.mod.json", "pack.mcmeta"):
        if not (source_dir / required_file).is_file():
            fail(
                f"Datapack requires {required_file}:\n{source_dir}"
            )

    safe_name = project_name.translate(str.maketrans({
        "/": "_",
        " ": "_",
    }))

    output_file = upload_dir / f"{safe_name}-{format_id(pack_format)}.jar"

    print()
    print("=" * 60)
    print("Building datapack")
    print(f"Project:       {project_name}")
    print(f"Minecraft:     {version}")
    print(f"Pack format:   {json.dumps(pack_format)}")
    print(f"Source:        {source_dir}")
    print(f"Output:        {output_file}")
    print("=" * 60)

    upload_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="datapack-build-") as temporary:
        build_dir = Path(temporary) / "build"

        # Copy everything, including hidden files and symlinks.
        shutil.copytree(source_dir, build_dir, symlinks=True)

        update_fabric_metadata(build_dir / "fabric.mod.json", version)
        update_pack_metadata(build_dir / "pack.mcmeta", pack_format)

        create_jar(build_dir, output_file)

    print()
    print("Successfully built datapack JAR:")
    print(output_file)


if __name__ == "__main__":
    main()
