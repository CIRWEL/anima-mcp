#!/usr/bin/env python3
"""
One-time bootstrap: deploy anima-mcp from GitHub zip. No git needed.
Run on Pi when rsync/SSH unavailable: curl -s https://raw.githubusercontent.com/CIRWEL/anima-mcp/main/scripts/bootstrap_deploy.py | python3
"""
import urllib.request
import zipfile
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path("/home/unitares-anima/anima-mcp")
URL = "https://github.com/CIRWEL/anima-mcp/archive/refs/heads/main.zip"

def main():
    print("Downloading from GitHub...")
    zip_path = Path("/tmp/anima-mcp-main.zip")
    ext_path = Path("/tmp/anima-mcp-main")

    urllib.request.urlretrieve(URL, zip_path)
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(ext_path.parent)
    zip_path.unlink(missing_ok=True)

    print("Deploying to", REPO_ROOT)
    skip = {".venv", ".git", "__pycache__", ".env"}
    for item in ext_path.iterdir():
        if item.name in skip or item.name.endswith(".db"):
            continue
        dst = REPO_ROOT / item.name
        if item.is_dir():
            if dst.exists():
                shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(
                item, dst,
                ignore=shutil.ignore_patterns(".venv", ".git", "__pycache__", "*.db", ".env")
            )
        else:
            shutil.copy2(item, dst)
    shutil.rmtree(ext_path, ignore_errors=True)

    print("Synchronizing core systemd units...")
    for unit in ("anima.service", "anima-broker.service"):
        subprocess.run(
            ["sudo", "install", "-m", "0644", str(REPO_ROOT / "systemd" / unit),
             str(Path("/etc/systemd/system") / unit)],
            timeout=15,
            check=True,
        )
    subprocess.run(
        ["sudo", "systemctl", "daemon-reload"], timeout=15, check=True
    )

    print("Restarting broker and anima services...")
    subprocess.run(
        ["sudo", "systemctl", "restart", "anima-broker", "anima"],
        timeout=45,
        check=True,
    )
    print("Done. Run setup_tailscale via HTTP if needed.")

if __name__ == "__main__":
    main()
    sys.exit(0)
