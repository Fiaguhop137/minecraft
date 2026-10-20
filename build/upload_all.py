#!/usr/bin/python3

import subprocess
import sys
SCRIPT_DIR="/home/firebot/git/minecraft/build"
RESOURCE_PACK_PUBLISHER=f"{SCRIPT_DIR}/upload_resourcepacks.py"
DATAPACK_PUBLISHER=f"{SCRIPT_DIR}/upload_datapacks.py"
CLEAN=f"{SCRIPT_DIR}/clean.py"
def run_script(path):
    subprocess.run([path],check=True)
def main():
    print("============================================================")
    print("Cleaning up older artifacts")
    print("============================================================")
    run_script(CLEAN)
    print("============================================================")
    print("Publishing resource packs")
    print("============================================================")
    run_script(RESOURCE_PACK_PUBLISHER)
    print()
    print("============================================================")
    print("Publishing datapacks")
    print("============================================================")
    run_script(DATAPACK_PUBLISHER)
    print()
    print("============================================================")
    print("All resource packs and datapacks processed successfully!")
    print("============================================================")
try:
    main()
except (OSError,subprocess.CalledProcessError) as error:
    print(f"Error: {error}",file=sys.stderr)
    sys.exit(1)