#!/usr/bin/env python3
"""
Sync anima.db between Mac backup and Pi (Lumen's body).

The Pi is the source of truth. The Mac keeps a backup.

Usage:
    python3 scripts/sync_state.py pull   # Pi -> Mac (backup)
    python3 scripts/sync_state.py push   # Mac -> Pi (restore)
"""
import sys
import argparse
import subprocess
import shutil
from pathlib import Path
from datetime import datetime

# Pi connection — using explicit credentials
REMOTE_HOST = "lumen.local"
REMOTE_USER = "unitares-anima"
REMOTE_DB = "~/anima-mcp/anima.db"

# Mac backup location
LOCAL_DIR = Path.home() / ".anima"
LOCAL_DB = LOCAL_DIR / "anima.db"


def _scp(src, dst):
    """Run scp, return success bool."""
    result = subprocess.run(["scp", src, dst], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  scp failed: {result.stderr.strip()}")
    return result.returncode == 0


def _backup_local():
    """Backup existing local db before overwriting."""
    if LOCAL_DB.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = LOCAL_DIR / f"anima.db.backup_{ts}"
        shutil.copy2(LOCAL_DB, backup)
        print(f"  Local backup: {backup.name}")

        # Keep only last 5 backups
        backups = sorted(LOCAL_DIR.glob("anima.db.backup_*"))
        for old in backups[:-5]:
            old.unlink()


def sync_pull():
    """Pull Pi's database to Mac (backup). Pi is source of truth."""
    print(f"Pulling Lumen's state from Pi ({REMOTE_HOST})...")
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    _backup_local()

    if _scp(f"{REMOTE_USER}@{REMOTE_HOST}:{REMOTE_DB}", str(LOCAL_DB)):
        size = LOCAL_DB.stat().st_size / 1024 / 1024
        print(f"  Pulled {size:.1f} MB")
    else:
        print("  Pull failed. Is the Pi reachable? Try: ping unitares")
        sys.exit(1)


def sync_push():
    """Push Mac's database to Pi (restore). Use with caution."""
    if not LOCAL_DB.exists():
        print(f"No local database at {LOCAL_DB}")
        sys.exit(1)

    size = LOCAL_DB.stat().st_size / 1024 / 1024
    print(f"WARNING: This will overwrite Lumen's database on the Pi ({REMOTE_HOST}).")
    print(f"  Local db: {size:.1f} MB")
    confirm = input("  Continue? (y/N) ")
    if confirm.lower() != "y":
        print("Aborted.")
        return

    if _scp(str(LOCAL_DB), f"{REMOTE_USER}@{REMOTE_HOST}:{REMOTE_DB}"):
        print(f"  Pushed {size:.1f} MB")
    else:
        print("  Push failed.")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Sync Lumen's anima.db between Pi and Mac"
    )
    parser.add_argument(
        "direction",
        choices=["pull", "push"],
        help="pull = Pi->Mac (backup), push = Mac->Pi (restore)"
    )
    args = parser.parse_args()

    if args.direction == "pull":
        sync_pull()
    elif args.direction == "push":
        sync_push()


if __name__ == "__main__":
    main()
