
#!/usr/bin/python3

import json
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path


SOURCE_DIR = Path("/home/firebot/git/minecraft/2d-item-sprites")
DEST_DIR = Path(
    "/home/firebot/.var/app/org.prismlauncher.PrismLauncher/"
    "data/PrismLauncher/instances/Fabric Mods/minecraft/resourcepacks"
)

ZIP_NAME = "2d item sprites-88-0.zip"

PACK = SOURCE_DIR / "assets/minecraft"
TEXTURES = PACK / "textures/item"
ITEMS = PACK / "items"
MODELS = PACK / "models/item"


def log(message):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
        file.write("\n")


def generate_definitions():
    if not TEXTURES.is_dir():
        raise FileNotFoundError(f"Texture directory not found: {TEXTURES}")

    ITEMS.mkdir(parents=True, exist_ok=True)
    MODELS.mkdir(parents=True, exist_ok=True)

    textures = sorted(TEXTURES.rglob("*.png"))

    for texture in textures:
        relative = texture.relative_to(TEXTURES).with_suffix("")
        item = relative.as_posix()

        item_json = ITEMS / relative.with_suffix(".json")
        model_json = MODELS / relative.with_suffix(".json")

        if not item_json.exists():
            write_json(item_json, {
                "model": {
                    "type": "minecraft:model",
                    "model": f"minecraft:item/{item}",
                }
            })
            log(f"Created item: {item}")
        else:
            log(f"Skipped item: {item}")

        if not model_json.exists():
            write_json(model_json, {
                "parent": "minecraft:item/generated",
                "textures": {
                    "layer0": f"minecraft:item/{item}",
                },
            })
            log(f"Created model: {item}")
        else:
            log(f"Skipped model: {item}")


def create_zip():
    DEST_DIR.mkdir(parents=True, exist_ok=True)

    source_zip = SOURCE_DIR / ZIP_NAME
    destination_zip = DEST_DIR / ZIP_NAME

    # Build a temporary archive so a failed build does not
    # destroy the previously installed ZIP.
    temporary_zip = SOURCE_DIR / f".{ZIP_NAME}.tmp"

    try:
        with zipfile.ZipFile(
            temporary_zip,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            paths = sorted(
                (
                    path for path in SOURCE_DIR.rglob("*")
                    if path != temporary_zip
                    and path != source_zip
                    and not path.is_symlink()
                ),
                key=lambda path: path.relative_to(SOURCE_DIR).as_posix(),
            )

            for path in paths:
                relative = path.relative_to(SOURCE_DIR).as_posix()

                if path.is_dir():
                    archive.write(path, relative + "/")
                elif path.is_file():
                    archive.write(path, relative)

        # Move the completed archive into the resourcepacks directory.
        shutil.move(str(temporary_zip), str(destination_zip))

    finally:
        temporary_zip.unlink(missing_ok=True)

    log(f"Installed resource pack: {destination_zip}")


def main():
    try:
        if not SOURCE_DIR.is_dir():
            raise FileNotFoundError(
                f"Source directory not found: {SOURCE_DIR}"
            )

        generate_definitions()
        create_zip()

    except (OSError, zipfile.BadZipFile) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
