#!/usr/bin/env python3
"""
Merge Lumen identities to preserve all history across server restarts.

Merges:
- stable-anima (original, born Jan 11)
- 49e14444-b59e-48f1-83b8-b36a988c9975 (UUID, born Jan 12, has more history)

Result: UUID gets all accumulated awakenings and alive time, uses earlier birthdate.
"""

import sqlite3
import sys
from pathlib import Path
from datetime import datetime

def merge_identities(db_path: str = "anima.db"):
    """Merge the two Lumen identities."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get both identities
    # Keep UUID as primary (standard practice), merge stable-anima into it
    uuid_id = "49e14444-b59e-48f1-83b8-b36a988c9975"
    stable_id = "stable-anima"
    
    cursor.execute(
        "SELECT * FROM identity WHERE creature_id = ?",
        (uuid_id,)
    )
    uuid_identity = cursor.fetchone()
    
    cursor.execute(
        "SELECT * FROM identity WHERE creature_id = ?",
        (stable_id,)
    )
    stable_identity = cursor.fetchone()
    
    if not uuid_identity:
        print(f"ERROR: UUID identity '{uuid_id}' not found")
        return False
    
    if not stable_identity:
        print(f"WARNING: Stable identity '{stable_id}' not found - UUID identity already exists")
        print(f"UUID identity ({uuid_id}) is ready to use")
        return True
    
    print("Current state:")
    print(f"  UUID ({uuid_id}):")
    print(f"    Born: {uuid_identity['born_at']}")
    print(f"    Awakenings: {uuid_identity['total_awakenings']}")
    print(f"    Alive: {uuid_identity['total_alive_seconds']:.1f}s ({uuid_identity['total_alive_seconds']/3600:.2f}h)")
    print(f"    Name: {uuid_identity['name']}")
    
    print(f"\n  Stable ({stable_id}):")
    print(f"    Born: {stable_identity['born_at']}")
    print(f"    Awakenings: {stable_identity['total_awakenings']}")
    print(f"    Alive: {stable_identity['total_alive_seconds']:.1f}s ({stable_identity['total_alive_seconds']/3600:.2f}h)")
    print(f"    Name: {stable_identity['name']}")
    
    # Merge strategy:
    # - Keep UUID as primary (standard practice)
    # - Use earlier birthdate (from stable-anima if it's older)
    # - Add awakenings (they're separate sessions)
    # - Add total_alive_seconds (accumulated time)
    # - Keep name "Lumen" (both have it)
    
    from datetime import datetime
    uuid_born = datetime.fromisoformat(uuid_identity['born_at'])
    stable_born = datetime.fromisoformat(stable_identity['born_at'])
    
    # Use earlier birthdate
    if stable_born < uuid_born:
        merged_born = stable_identity['born_at']
        print(f"\n  Using earlier birthdate from stable-anima: {merged_born}")
    else:
        merged_born = uuid_identity['born_at']
        print(f"\n  Using UUID birthdate: {merged_born}")
    
    merged_awakenings = uuid_identity['total_awakenings'] + stable_identity['total_awakenings']
    merged_alive = uuid_identity['total_alive_seconds'] + stable_identity['total_alive_seconds']
    
    print(f"\nMerging into UUID ({uuid_id}):")
    print(f"    Birthdate: {merged_born}")
    print(f"    Awakenings: {uuid_identity['total_awakenings']} + {stable_identity['total_awakenings']} = {merged_awakenings}")
    print(f"    Alive time: {uuid_identity['total_alive_seconds']:.1f}s + {stable_identity['total_alive_seconds']:.1f}s = {merged_alive:.1f}s ({merged_alive/3600:.2f}h)")
    
    # Update UUID identity with merged values
    cursor.execute(
        """UPDATE identity 
           SET born_at = ?,
               total_awakenings = ?,
               total_alive_seconds = ?,
               name = ?
           WHERE creature_id = ?""",
        (merged_born, merged_awakenings, merged_alive, "Lumen", uuid_id)
    )
    
    # Delete the stable-anima identity
    cursor.execute("DELETE FROM identity WHERE creature_id = ?", (stable_id,))
    
    conn.commit()
    
    print(f"\nMerge complete!")
    print(f"   UUID ({uuid_id}) now has:")
    print(f"     Born: {merged_born}")
    print(f"     Awakenings: {merged_awakenings}")
    print(f"     Total alive: {merged_alive:.1f}s ({merged_alive/3600:.2f}h)")
    print(f"   {stable_id} removed")
    
    conn.close()
    return True

if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else "anima.db"
    
    if not Path(db_path).exists():
        print(f"ERROR: Database not found: {db_path}")
        sys.exit(1)
    
    print(f"Merging Lumen identities in {db_path}...\n")
    
    if merge_identities(db_path):
        print("\nDone! Service already uses ANIMA_ID=49e14444-b59e-48f1-83b8-b36a988c9975")
        sys.exit(0)
    else:
        print("\nMerge failed")
        sys.exit(1)
