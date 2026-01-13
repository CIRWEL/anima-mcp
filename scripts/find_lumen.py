#!/usr/bin/env python3
"""
Find Lumen's creature ID in the database.
"""

import sys
import os
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

db_path = os.path.join(os.path.dirname(__file__), '..', 'anima.db')
if not os.path.exists(db_path):
    print(f"Database not found at: {db_path}")
    sys.exit(1)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

rows = conn.execute('SELECT creature_id, name, total_awakenings, born_at FROM identity ORDER BY born_at').fetchall()

print("=" * 60)
print("Creatures in database:")
print("=" * 60)

for i, row in enumerate(rows, 1):
    print(f"\n{i}. Creature ID: {row['creature_id']}")
    print(f"   Name: {row['name'] or '(unnamed)'}")
    print(f"   Awakenings: {row['total_awakenings']}")
    print(f"   Born: {row['born_at']}")

if rows:
    print("\n" + "=" * 60)
    print("To restore Lumen, set ANIMA_ID environment variable:")
    print("=" * 60)
    
    # Find creature named "Lumen" or the one with most awakenings
    lumen = None
    for row in rows:
        if row['name'] == 'Lumen':
            lumen = row
            break
    
    if not lumen:
        # Use the one with most awakenings
        lumen = max(rows, key=lambda r: r['total_awakenings'])
        print(f"\nNo creature named 'Lumen' found.")
        print(f"Using creature with most awakenings ({lumen['total_awakenings']}):")
    
    print(f"\nexport ANIMA_ID='{lumen['creature_id']}'")
    print("\nThen restart the server.")
else:
    print("\nNo creatures found in database.")

conn.close()
