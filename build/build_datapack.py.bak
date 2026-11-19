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
        with path.open(encoding="utf-8") as file:
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


def format_id(value):
    return "-".join(map(str, value)) if isinstance(value, list) else str(value)


def validate_format(value):
    if type(value) is int and value >= 0:
        return
    if (
        isinstance(value, list)
        and len(value) == 2
        and all(type(item) is int and item >= 0 for item in value)
    ):
        return
    fail("Pack format must be a non-negative integer or a two-integer array.")


def update_fabric_metadata(path, version):
    data = load_json(path)
    if not isinstance(data, dict):
        fail("fabric.mod.json must contain a JSON object.")

    depends = data.get("depends") or {}
    if not isinstance(depends, dict):
        fail("fabric.mod.json 'depends' must be a JSON object.")

    depends = dict(depends)
    depends["minecraft"] = ">=" + version

    write_json(path, {
        "schemaVersion": data.get("schemaVersion", 1),
        "id": data.get("id"),
        "version": version,
        "name": data.get("name"),
        "environment": data.get("environment", "*"),
        "depends": depends,
        "entrypoints": data.get("entrypoints", {}),
        "mixins": data.get("mixins", []),
    })


def generate_pack_metadata(path, project_name, version, pack_format):
    description = (
        f"{project_name}, for Minecraft Java {version} by Fiaguhop137"
    )

    if isinstance(pack_format, list):
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

    write_json(path, metadata)


def create_jar(source_dir, output_file):
    temporary = output_file.with_name(f".{output_file.name}.tmp")
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            paths = sorted(
                source_dir.rglob("*"),
                key=lambda item: item.relative_to(source_dir).as_posix(),
            )
            for path in paths:
                relative = path.relative_to(source_dir).as_posix()
                is_dir = path.is_dir() and not path.is_symlink()
                info = zipfile.ZipInfo(
                    relative + ("/" if is_dir else ""),
                    date_time=ZIP_TIMESTAMP,
                )
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED

                if path.is_symlink():
                    info.external_attr = 0o120777 << 16
                    archive.writestr(info, os.readlink(path).encode())
                elif is_dir:
                    info.external_attr = (0o40755 << 16) | 0x10
                    archive.writestr(info, b"")
                elif path.is_file():
                    info.external_attr = 0o100644 << 16
                    with path.open("rb") as source, archive.open(info, "w") as out:
                        shutil.copyfileobj(source, out, length=1024 * 1024)
                else:
                    fail(f"Unsupported filesystem entry: {path}")

        os.replace(temporary, output_file)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    if len(sys.argv) != 4:
        fail(
            "Usage: build_datapack.py "
            "<project_index> <pack_format_json> <minecraft_version>"
        )

    try:
        index = int(sys.argv[1])
        pack_format = json.loads(sys.argv[2])
    except (ValueError, json.JSONDecodeError):
        fail("Invalid project index or pack format JSON.")

    if index < 0:
        fail("Invalid project index.")
    validate_format(pack_format)

    version = sys.argv[3]
    if not version:
        fail("Minecraft version cannot be empty.")

    config = load_json(CONFIG_FILE)
    try:
        project_name = config["PROJECT_NAMES"][index]
        source_dir = resolve_path(config["SOURCE_DIRS"][index])
        project_type = config["TYPE"][index]
        formats = config["datapack_formats"]
    except (KeyError, IndexError, TypeError):
        fail(f"Invalid project index or missing configuration: {index}")

    if project_type != "datapack":
        fail(f"Project is not a datapack: {project_name}")
    if not isinstance(formats, dict) or formats.get(version) != pack_format:
        fail(f"Pack format does not match config.json for Minecraft {version}.")
    if not source_dir.is_dir():
        fail(f"Source directory does not exist: {source_dir}")

    if not (source_dir / "fabric.mod.json").is_file():
        fail(f"Datapack requires fabric.mod.json: {source_dir}")

    output_dir = Path(
        os.environ.get("MINECRAFT_BUILD_DIR", "/tmp/minecraft-builds")
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    safe_name = project_name.replace("/", "_").replace(" ", "_")
    output_file = output_dir / f"{safe_name}-{format_id(pack_format)}.jar"

    print(f"Building {project_name} for Minecraft {version}")
    print(f"Output: {output_file}")

    with tempfile.TemporaryDirectory(prefix="datapack-build-") as temp:
        build_dir = Path(temp) / "build"

        shutil.copytree(source_dir, build_dir, symlinks=True)

        update_fabric_metadata(
            build_dir / "fabric.mod.json",
            version,
        )

        generate_pack_metadata(
            build_dir / "pack.mcmeta",
            project_name,
            version,
            pack_format,
        )

        create_jar(build_dir, output_file)

    print(f"Successfully built: {output_file}")


if __name__ == "__main__":
    main()