#!/usr/bin/env python3
"""
Test sensor connection and shared memory reading.
Run this to diagnose why sensors aren't registering.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.anima_mcp.shared_memory import SharedMemoryClient
from src.anima_mcp.sensors import get_sensors
import subprocess

print("=== Sensor Connection Diagnostic ===\n")

# 1. Check if broker is running
print("1. Checking if broker (stable_creature.py) is running...")
try:
    result = subprocess.run(
        ['pgrep', '-f', 'stable_creature.py'],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        pids = result.stdout.strip().split('\n')
        pids = [p for p in pids if p]
        print(f"   ✓ Broker is running (PIDs: {', '.join(pids)})")
        broker_running = True
    else:
        print("   ✗ Broker is NOT running")
        broker_running = False
except Exception as e:
    print(f"   ✗ Error checking broker: {e}")
    broker_running = False

print()

# 2. Check shared memory
print("2. Checking shared memory...")
try:
    shm_client = SharedMemoryClient(mode="read", backend="file")
    print(f"   Backend: {shm_client.backend}")
    print(f"   File path: {shm_client.filepath}")
    
    shm_data = shm_client.read()
    if shm_data:
        print("   ✓ Shared memory contains data")
        print(f"   Keys: {list(shm_data.keys())}")
        
        if "readings" in shm_data:
            readings = shm_data["readings"]
            print(f"   ✓ Readings found: {list(readings.keys())}")
        else:
            print("   ✗ No 'readings' key in shared memory")
            
        if "anima" in shm_data:
            anima = shm_data["anima"]
            print(f"   ✓ Anima found: {list(anima.keys())}")
        else:
            print("   ✗ No 'anima' key in shared memory")
    else:
        print("   ✗ Shared memory is empty or not accessible")
        if broker_running:
            print("   ⚠️  Broker is running but not writing to shared memory!")
except Exception as e:
    print(f"   ✗ Error reading shared memory: {e}")
    import traceback
    traceback.print_exc()

print()

# 3. Test direct sensor access (only if broker not running)
print("3. Testing direct sensor access...")
if broker_running:
    print("   ⚠️  Skipping (broker is running - direct access would conflict)")
else:
    try:
        sensors = get_sensors()
        readings = sensors.read()
        print(f"   ✓ Direct sensor read successful")
        print(f"   Available sensors: {sensors.available_sensors()}")
        print(f"   Is Pi: {sensors.is_pi()}")
        print(f"   Readings: temp={readings.ambient_temp_c}°C, humidity={readings.humidity_pct}%, light={readings.light_lux}lx")
    except Exception as e:
        print(f"   ✗ Direct sensor read failed: {e}")
        import traceback
        traceback.print_exc()

print("\n=== Diagnostic Complete ===")
