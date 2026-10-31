#!/usr/bin/python3
import json,sys,time,urllib.error,urllib.request
from pathlib import Path
SCRIPT_DIR=Path(__file__).resolve().parent
CONFIG_FILE=SCRIPT_DIR/"config.json"
MAX_ATTEMPTS=5
TIMEOUT=120
DEFAULT_RETRY_SECONDS=10
def fail(message):
    print(f"Error: {message}",file=sys.stderr)
    raise SystemExit(1)
def load_config():
    if not CONFIG_FILE.is_file():
        fail(f"config.json not found: {CONFIG_FILE}")
    try:
        with CONFIG_FILE.open(encoding="utf-8") as file:
            return json.load(file)
    except (OSError,json.JSONDecodeError) as exc:
        fail(f"Cannot read config.json: {exc}")
def retry_after(headers):
    value=headers.get("Retry-After", "")
    try:
        seconds=int(value)
        return seconds if seconds>=0 else DEFAULT_RETRY_SECONDS
    except (ValueError,TypeError):
        return DEFAULT_RETRY_SECONDS
def request(method, url, token):
    req=urllib.request.Request(url,method=method,headers={"Authorization":token,"User-Agent":"Fiaguhop137-Modrinth-Cleanup/1.0"})
    try:
        with urllib.request.urlopen(req,timeout=TIMEOUT) as response:
            return (response.status,response.headers,response.read())
    except urllib.error.HTTPError as exc:
        try:
            return exc.code,exc.headers,exc.read()
        finally:
            exc.close()
def request_with_retries(method,url,token):
    for attempt in range(1,MAX_ATTEMPTS+1):
        status,headers,body=request(method,url,token)
        if status!=429 or attempt==MAX_ATTEMPTS:return status,headers,body
        wait=retry_after(headers)
        print("Modrinth rate limit reached.")
        print(f"Retrying in {wait}s...")
        print(f"Attempt {attempt+1}/{MAX_ATTEMPTS}")
        time.sleep(wait)
    raise RuntimeError("Unreachable retry state")
def delete_version(version_id,api_url,token):
    url=f"{api_url}/version/{version_id}"
    try:
        status,_,body=request_with_retries("DELETE",url,token)
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        print(f"\nError deleting {version_id}: {exc}",file=sys.stderr)
        return False
    if 200<=status<300:
        return True
    print(f"\nError deleting {version_id}.")
    print(f"HTTP status: {status}")
    if body:
        print(body.decode("utf-8",errors="replace"),file=sys.stderr)
    return False
def get_versions(project_id,api_url,token):
    url=f"{api_url}/project/{project_id}/version"
    status,_,body=request_with_retries("GET",url,token)
    if status==404:
        print("No readable versions found; Modrinth returned 404.")
        return None
    if not 200<=status<300:
        if body:
            print(body.decode("utf-8",errors="replace"),file=sys.stderr)
        fail(f"Modrinth returned HTTP {status} for project {project_id}.")
    try:
        versions=json.loads(body)
    except (json.JSONDecodeError,UnicodeDecodeError):
        fail(f"Modrinth returned invalid JSON for {project_id}.")
    if not isinstance(versions,list):
        fail(f"Expected a JSON array of versions for {project_id}.")
    return versions
def main():
    config=load_config()
    token=config.get("TOKEN")
    api_url=config.get("MODRINTH_API")
    if not isinstance(token, str) or not token or token=="null":
        fail("Modrinth token is missing from config.json.")
    if not isinstance(api_url, str) or not api_url or api_url=="null":
        fail("Modrinth API URL is missing from config.json.")
    api_url=api_url.rstrip("/")
    if not api_url.startswith(("https://", "http://")):
        fail("MODRINTH_API must be an HTTP or HTTPS URL.")
    project_ids=config.get("PROJECT_IDS")
    project_names=config.get("PROJECT_NAMES")
    project_types=config.get("TYPE")
    if not isinstance(project_ids, list) or not project_ids:
        fail("No projects configured.")
    project_count=len(project_ids)
    for key,values in (("PROJECT_NAMES",project_names),("TYPE",project_types)):
        if not isinstance(values,list) or len(values)!=project_count:
            count=len(values) if isinstance(values,list) else 0
            fail(f"{key} contains {count} entries. Expected {project_count}.")
    retry_list=[]
    for project_name,project_id,project_type in zip(project_names,project_ids,project_types):
        if project_type not in ("resourcepack", "datapack"):
            print()
            print("Skipping unknown project type:")
            print(f"  Project: {project_name}")
            print(f"  Type:    {project_type}")
            continue
        print(f"Project:    {project_name}")
        print(f"Project ID: {project_id}")
        print(f"Type:       {project_type}")
        versions=get_versions(project_id,api_url,token)
        if versions is None:continue
        zero_downloads=[version for version in versions if isinstance(version, dict) and version.get("downloads")==0]
        if not zero_downloads:
            print("No versions with 0 downloads.")
            continue
        print(f"Found {len(zero_downloads)} zero-download version(s).")
        deleted,failed=0,0
        for version in zero_downloads:
            version_id=version.get("id","")
            version_number=version.get("version_number","")
            version_name=version.get("name","")
            date_published=version.get("date_published","")
            print("Found zero-download version:")
            print(f"  Name:      {version_name}")
            print(f"  Version:   {version_number}")
            print(f"  ID:        {version_id}")
            print(f"  Published: {date_published}")
            if not isinstance(version_id, str) or not version_id:
                print("Failed: version has no valid ID.")
                failed+=1
                continue
            if delete_version(version_id,api_url,token):
                print(f"Deleted {version_number}.")
                deleted+=1
            else:
                print(f"Failed to delete {version_number}.")
                retry_list.append({"id": version_id,"number": version_number,"name": version_name,"date": date_published,"project": project_name,})
                failed+=1
        print("Project cleanup complete:")
        print(f"  Deleted: {deleted}")
        print(f"  Failed:  {failed}")
    final_failed=0
    if retry_list:
        print("RETRYING FAILED DELETIONS")
        print(f"Versions requiring retry: {len(retry_list)}")
        for version in retry_list:
            print("Retrying deletion:")
            print(f"  Project:   {version['project']}")
            print(f"  Name:      {version['name']}")
            print(f"  Version:   {version['number']}")
            print(f"  ID:        {version['id']}")
            print(f"  Published: {version['date']}")
            if delete_version(version["id"], api_url, token):
                print(f"Retry succeeded: {version['number']}")
            else:
                print(f"Retry failed: {version['number']}")
                final_failed+=1
    print("Finished cleaning zero-download versions.")
    if final_failed:
        print(f"Failed after retry: {final_failed}")
        return 1
    print("All zero-download versions were handled successfully.")
    return 0
if __name__=="__main__":
    try:
        sys.exit(main())
    except (OSError,urllib.error.URLError) as exc:
        fail(f"Network or filesystem error: {exc}")