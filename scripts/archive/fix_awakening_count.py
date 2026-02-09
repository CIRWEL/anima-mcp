#!/usr/bin/env python3
"""
Fix Historical Awakening Count

Analyzes wake events and identifies duplicates (multiple wakes within 60s).
Can mark duplicates or provide statistics for manual correction.

Usage:
    # Analyze only (no changes)
    python3 scripts/fix_awakening_count.py analyze

    # Mark duplicates (updates event_type to 'wake_duplicate')
    python3 scripts/fix_awakening_count.py fix

    # Set specific awakening count (manual correction)
    python3 scripts/fix_awakening_count.py set-count 42
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def analyze_wake_events(db_path="anima.db", dedupe_window_seconds=60):
    """
    Analyze wake events and show statistics.
    
    Returns:
        tuple: (total_wakes, duplicate_wakes, valid_wakes, analysis)
    """
    conn = sqlite3.connect(db_path)
    
    # Get all wake events
    wake_events = conn.execute(
        "SELECT id, timestamp FROM events WHERE event_type = 'wake' "
        "ORDER BY timestamp ASC"
    ).fetchall()
    
    if not wake_events:
        print("No wake events found")
        return 0, 0, 0, []
    
    duplicates = []
    last_valid_wake = None
    duplicate_count = 0
    
    for event_id, timestamp_str in wake_events:
        timestamp = datetime.fromisoformat(timestamp_str)
        
        if last_valid_wake is None:
            # First wake is always valid
            last_valid_wake = timestamp
            continue
        
        seconds_since_last = (timestamp - last_valid_wake).total_seconds()
        
        if seconds_since_last < dedupe_window_seconds:
            # This is a duplicate
            duplicate_count += 1
            duplicates.append({
                "id": event_id,
                "timestamp": timestamp_str,
                "seconds_since_last": seconds_since_last
            })
        else:
            # Valid wake
            last_valid_wake = timestamp
    
    valid_count = len(wake_events) - duplicate_count
    
    conn.close()
    
    return len(wake_events), duplicate_count, valid_count, duplicates


def mark_duplicates(db_path="anima.db", dedupe_window_seconds=60, dry_run=True):
    """
    Mark duplicate wake events by changing event_type to 'wake_duplicate'.
    
    This preserves the events but excludes them from awakening count calculation.
    """
    conn = sqlite3.connect(db_path)
    
    # Get all wake events
    wake_events = conn.execute(
        "SELECT id, timestamp FROM events WHERE event_type = 'wake' "
        "ORDER BY timestamp ASC"
    ).fetchall()
    
    last_valid_wake = None
    marked_count = 0
    
    for event_id, timestamp_str in wake_events:
        timestamp = datetime.fromisoformat(timestamp_str)
        
        if last_valid_wake is None:
            # First wake is always valid
            last_valid_wake = timestamp
            continue
        
        seconds_since_last = (timestamp - last_valid_wake).total_seconds()
        
        if seconds_since_last < dedupe_window_seconds:
            # Mark as duplicate
            marked_count += 1
            if not dry_run:
                conn.execute(
                    "UPDATE events SET event_type = 'wake_duplicate' WHERE id = ?",
                    (event_id,)
                )
            print(f"{'Would mark' if dry_run else 'Marked'} as duplicate: "
                  f"{timestamp_str} ({seconds_since_last:.1f}s since last)")
        else:
            # Valid wake
            last_valid_wake = timestamp
    
    if not dry_run:
        conn.commit()
        print(f"\n✓ Marked {marked_count} events as duplicates")
        
        # Recalculate awakening count (count wake events, not wake_duplicate)
        creature_id_row = conn.execute(
            "SELECT creature_id FROM identity LIMIT 1"
        ).fetchone()
        
        if creature_id_row:
            creature_id = creature_id_row[0]
            valid_wakes = conn.execute(
                "SELECT COUNT(*) FROM events WHERE event_type = 'wake'"
            ).fetchone()[0]
            
            conn.execute(
                "UPDATE identity SET total_awakenings = ? WHERE creature_id = ?",
                (valid_wakes, creature_id)
            )
            conn.commit()
            print(f"✓ Updated awakening count to {valid_wakes}")
    else:
        print(f"\nDRY RUN: Would mark {marked_count} events as duplicates")
    
    conn.close()
    return marked_count


def set_awakening_count(count, db_path="anima.db"):
    """
    Manually set the awakening count.
    
    Use this if you know the true awakening count and want to correct it.
    """
    conn = sqlite3.connect(db_path)
    
    creature_id_row = conn.execute(
        "SELECT creature_id, total_awakenings FROM identity LIMIT 1"
    ).fetchone()
    
    if not creature_id_row:
        print("No identity found in database")
        conn.close()
        return False
    
    creature_id, current_count = creature_id_row
    
    print(f"Current awakening count: {current_count}")
    print(f"New awakening count: {count}")
    print()
    
    response = input("Are you sure you want to update? (yes/no): ")
    if response.lower() != 'yes':
        print("Cancelled")
        return False
    
    conn.execute(
        "UPDATE identity SET total_awakenings = ? WHERE creature_id = ?",
        (count, creature_id)
    )
    conn.commit()
    conn.close()
    
    print(f"✓ Updated awakening count to {count}")
    return True


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    command = sys.argv[1]
    db_path = "anima.db"
    
    # Check if database exists
    if not Path(db_path).exists():
        print(f"Database not found: {db_path}")
        print("Run from anima-mcp directory or specify path")
        sys.exit(1)
    
    if command == "analyze":
        print("Analyzing wake events...")
        print()
        
        total, duplicates, valid, dup_list = analyze_wake_events(db_path)
        
        print(f"Total wake events: {total}")
        print(f"Duplicate wake events: {duplicates}")
        print(f"Valid wake events: {valid}")
        print()
        
        if duplicates > 0:
            print(f"Accuracy improvement: {total / valid:.1f}x")
            print()
            print("Recent duplicates:")
            for dup in dup_list[-10:]:  # Show last 10
                print(f"  {dup['timestamp']}: {dup['seconds_since_last']:.1f}s since last")
            print()
            print(f"Run 'fix' command to mark {duplicates} duplicates and update count")
        else:
            print("✓ No duplicates found - awakening count is accurate!")
    
    elif command == "fix":
        print("Analyzing and marking duplicate wake events...")
        print()
        
        # First show what would be done
        total, duplicates, valid, _ = analyze_wake_events(db_path)
        print(f"Found {duplicates} duplicate wake events")
        print(f"Will update awakening count from ~{total} to {valid}")
        print()
        
        response = input("Proceed with fix? (yes/no): ")
        if response.lower() != 'yes':
            print("Cancelled")
            sys.exit(0)
        
        print()
        marked = mark_duplicates(db_path, dry_run=False)
        print()
        print(f"✓ Fix complete - marked {marked} duplicates")
    
    elif command == "set-count":
        if len(sys.argv) < 3:
            print("Usage: fix_awakening_count.py set-count <number>")
            sys.exit(1)
        
        try:
            count = int(sys.argv[2])
            set_awakening_count(count, db_path)
        except ValueError:
            print(f"Invalid count: {sys.argv[2]}")
            sys.exit(1)
    
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
