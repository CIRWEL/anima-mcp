#!/usr/bin/env python3
"""
Bump the anima epoch.

Run this when a model change invalidates existing stored data
(e.g., anima dimension definitions, drawing EISV model, sensor mappings).

Most changes (bug fixes, new features, display changes) do NOT require an epoch bump.

Usage:
    python3 scripts/bump_epoch.py --reason "changed anima dimension weights"
    python3 scripts/bump_epoch.py --reason "restructured state model" --dry-run
"""

import argparse
import os
import sys
from datetime import datetime


def bump_epoch(reason: str, dry_run: bool = False):
    store_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "src", "anima_mcp", "identity", "store.py",
    )

    with open(store_path, "r") as f:
        content = f.read()

    # Find current epoch
    import re
    match = re.search(r"CURRENT_EPOCH = (\d+)", content)
    if not match:
        print(f"ERROR: Could not find CURRENT_EPOCH in {store_path}")
        sys.exit(1)

    current = int(match.group(1))
    new_epoch = current + 1

    print(f"Current epoch: {current}")
    print(f"New epoch:     {new_epoch}")
    print(f"Reason:        {reason}")
    print()

    if dry_run:
        print("[DRY RUN] No changes made. Remove --dry-run to apply.")
        return

    # 1. Update the source file
    content = content.replace(f"CURRENT_EPOCH = {current}", f"CURRENT_EPOCH = {new_epoch}", 1)
    with open(store_path, "w") as f:
        f.write(content)
    print(f"[OK] Updated CURRENT_EPOCH to {new_epoch} in identity/store.py")

    # 2. Log the epoch bump to a local file
    log_dir = os.path.expanduser("~/.anima")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "epoch_log.jsonl")

    import json
    entry = {
        "epoch": new_epoch,
        "previous": current,
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
        "bumped_by": "manual",
    }
    with open(log_path, "a") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"[OK] Logged epoch bump to {log_path}")

    print()
    print(f"Epoch bumped: {current} -> {new_epoch}")
    print(f"Old data (epoch {current}) remains in SQLite but is excluded from active queries.")
    print()
    print("Next steps:")
    print("  1. Commit and push the change")
    print("  2. Deploy to Pi: mcp__anima__git_pull(restart=true)")
    print("  3. Wait 2 minutes for Pi restart")


def main():
    parser = argparse.ArgumentParser(description="Bump the anima epoch")
    parser.add_argument("--reason", required=True, help="Why this epoch bump is needed")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen without making changes")
    args = parser.parse_args()

    bump_epoch(args.reason, args.dry_run)


if __name__ == "__main__":
    main()
