#!/usr/bin/env bash
set -euo pipefail

workspace_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source_dir="$workspace_dir/phoenixWings"
prism_mods_dir="/home/firebot/.var/app/org.prismlauncher.PrismLauncher/data/PrismLauncher/instances/Fabric Mods/minecraft/mods"
jar_name="phoenixwings-26.2.jar"

if [[ ! -d "$source_dir" ]]; then
    printf 'Source directory not found: %s\n' "$source_dir" >&2
    exit 1
fi

if ! command -v zip >/dev/null 2>&1; then
    printf 'The zip command is required but was not found in PATH.\n' >&2
    exit 1
fi

temporary_dir="$(mktemp -d)"
trap 'rm -rf "$temporary_dir"' EXIT

(cd -- "$source_dir" && zip -q -r "$temporary_dir/$jar_name" .)
mkdir -p "$prism_mods_dir"
mv -- "$temporary_dir/$jar_name" "$prism_mods_dir/$jar_name"

printf 'Built and installed: %s\n' "$prism_mods_dir/$jar_name"