#!/usr/bin/env python3
"""
Update server.py on Pi via MCP connection.
This script reads the fixed server.py and provides instructions for manual update.
"""

import sys
import os

# Read the fixed server.py
server_py_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src/anima_mcp/server.py")

print("=== Sensor Fix Deployment Guide ===")
print()
print("Since SSH isn't working, here are options to deploy the sensor fix:")
print()
print("OPTION 1: Manual file copy (if you have any Pi access)")
print("  The fixed file is at:")
print(f"  {server_py_path}")
print()
print("OPTION 2: Git pull on Pi (if git is set up)")
print("  If the Pi has git access, you can:")
print("  1. SSH to Pi (with password if needed)")
print("  2. cd ~/anima-mcp")
print("  3. git pull")
print("  4. systemctl --user restart anima")
print()
print("OPTION 3: Direct edit on Pi")
print("  The fix is in _get_readings_and_anima() function:")
print("  - Added staleness check for shared memory data")
print("  - Improved fallback to direct sensors even when broker is running")
print()
print("Key changes:")
print("  - Checks if shared memory timestamp is > 5 seconds old")
print("  - Falls back to direct sensors if shared memory is stale/empty")
print("  - Works even if broker is running but not writing properly")
print()

# Show the key section that was changed
print("=== Key Code Section (lines ~138-193) ===")
print()
with open(server_py_path, 'r') as f:
    lines = f.readlines()
    # Find the function
    start = None
    for i, line in enumerate(lines):
        if '_get_readings_and_anima' in line and 'def ' in line:
            start = i
            break
    
    if start:
        # Show the function
        end = start + 60  # Show ~60 lines
        for i in range(start, min(end, len(lines))):
            print(f"{i+1:4d}| {lines[i]}", end='')
