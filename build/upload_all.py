#!/usr/bin/python3
import subprocess,sys
SCRIPT_DIR="/home/firebot/git/minecraft/build"
RESOURCE_PACK_PUBLISHER=f"{SCRIPT_DIR}/upload_resourcepacks.py"
DATAPACK_PUBLISHER=f"{SCRIPT_DIR}/upload_datapacks.py"
CLEAN=f"{SCRIPT_DIR}/clean.py"
def run_script(path):
    subprocess.run([path],check=True)
def main():
    print("Deleting 0 download stuff")
    run_script(CLEAN)
    print("Publishing resource packs")
    run_script(RESOURCE_PACK_PUBLISHER)
    print("Publishing datapacks")
    run_script(DATAPACK_PUBLISHER)
    print("Done")
try:
    main()
except (OSError,subprocess.CalledProcessError) as error:
    print(f"Error: {error}",file=sys.stderr)
    sys.exit(1)