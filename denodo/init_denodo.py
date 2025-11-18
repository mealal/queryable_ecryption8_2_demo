"""
Denodo Initialization Script
Uses Denodo's import.sh script to execute VQL files
"""

import subprocess
import time
import sys
from pathlib import Path

# Denodo connection settings
DENODO_HOST = "localhost"
DENODO_PORT = "9999"
DENODO_USER = "admin"
DENODO_PASSWORD = "admin"

def wait_for_denodo(max_retries=30, retry_delay=5):
    """Wait for Denodo to be ready"""
    print("Waiting for Denodo to be ready...")

    for i in range(max_retries):
        try:
            result = subprocess.run(
                ["docker", "exec", "poc_denodo", "bash", "-c",
                 f"timeout 5 bash -c 'cat < /dev/null > /dev/tcp/{DENODO_HOST}/9999'"],
                capture_output=True,
                timeout=10
            )
            if result.returncode == 0:
                print("[OK] Denodo is ready\n")
                return True
        except Exception:
            pass

        print(f"  Waiting... ({i+1}/{max_retries})")
        time.sleep(retry_delay)

    print("[FAIL] Denodo failed to start")
    return False


def execute_vql_file(vql_file: Path):
    """Execute a VQL file using Denodo's import.sh script"""
    print(f"Executing {vql_file.name}...")

    # Server URI format: host:port/database?user@password
    server_uri = f"{DENODO_HOST}:{DENODO_PORT}/admin?{DENODO_USER}@{DENODO_PASSWORD}"

    # Copy VQL file to container
    container_vql_path = f"/tmp/{vql_file.name}"
    copy_cmd = ["docker", "cp", str(vql_file), f"poc_denodo:{container_vql_path}"]
    subprocess.run(copy_cmd, check=True, capture_output=True)

    # Execute via import.sh
    import_cmd = [
        "docker", "exec", "poc_denodo", "bash", "-c",
        f"//opt//denodo//bin//import.sh --file {container_vql_path} --server '{server_uri}'"
    ]

    try:
        result = subprocess.run(
            import_cmd,
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode == 0 or "already exists" in result.stdout.lower() or "already exists" in result.stderr.lower():
            print(f"  [OK] {vql_file.name} executed successfully")
            return True
        else:
            print(f"  [WARN] {vql_file.name}: {result.stderr[:200]}")
            return False

    except Exception as e:
        print(f"  [FAIL] {vql_file.name}: {str(e)[:200]}")
        return False


def initialize_denodo():
    """Initialize Denodo by executing VQL files"""
    print("="*80)
    print("Denodo Initialization")
    print("="*80 + "\n")

    if not wait_for_denodo():
        sys.exit(1)

    # Find VQL files
    init_dir = Path(__file__).parent / 'init'
    if not init_dir.exists():
        print(f"[FAIL] Init directory not found: {init_dir}")
        sys.exit(1)

    vql_files = sorted(init_dir.glob('*.vql'))
    if not vql_files:
        print(f"[FAIL] No VQL files found in {init_dir}")
        sys.exit(1)

    print(f"Found {len(vql_files)} VQL files\n")

    # Execute each VQL file
    success_count = 0
    for vql_file in vql_files:
        if execute_vql_file(vql_file):
            success_count += 1
        time.sleep(2)  # Brief delay between executions

    print("\n" + "="*80)
    print(f"Denodo Initialization Complete: {success_count}/{len(vql_files)} scripts executed")
    print("="*80 + "\n")

    if success_count == len(vql_files):
        print("[OK] Denodo is ready for use")
        print(f"  REST API: http://localhost:9090/denodo-restfulws/poc_integration")
        print(f"  Web Panel: http://localhost:9090")
        return True
    else:
        print("[WARN] Some scripts had warnings - check output above")
        return True  # Continue anyway


if __name__ == '__main__':
    success = initialize_denodo()
    sys.exit(0 if success else 1)
