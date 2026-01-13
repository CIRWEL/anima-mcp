#!/usr/bin/env python3
"""
Check if display loop is running and LEDs are updating.
Run on Pi to diagnose display loop issues.
"""

import sys
import os
import time

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

try:
    from anima_mcp.display.leds import get_led_display
    from anima_mcp.display import get_display
    from anima_mcp.sensors import get_sensors
    from anima_mcp.anima import sense_self
    
    print("=" * 60)
    print("Display Loop Diagnostic")
    print("=" * 60)
    print()
    
    # Check components
    print("1. Checking components...")
    
    sensors = get_sensors()
    print(f"   Sensors: {'✅' if sensors else '❌'}")
    
    display = get_display()
    print(f"   Display: {'✅ available' if display.is_available() else '⚠️  not available'}")
    
    leds = get_led_display()
    print(f"   LEDs: {'✅ available' if leds.is_available() else '⚠️  not available'}")
    print()
    
    if not leds.is_available():
        print("❌ LEDs not available - cannot test updates")
        print()
        print("Run: python3 scripts/test_leds.py to diagnose LED hardware")
        sys.exit(1)
    
    # Test manual update
    print("2. Testing manual LED update...")
    readings = sensors.read()
    anima = sense_self(readings)
    
    print(f"   Anima state:")
    print(f"     warmth={anima.warmth:.3f}")
    print(f"     clarity={anima.clarity:.3f}")
    print(f"     stability={anima.stability:.3f}")
    print(f"     presence={anima.presence:.3f}")
    
    state = leds.update_from_anima(
        anima.warmth, anima.clarity,
        anima.stability, anima.presence
    )
    
    print(f"   LED colors:")
    print(f"     LED 0: {state.led0}")
    print(f"     LED 1: {state.led1}")
    print(f"     LED 2: {state.led2}")
    print("   ✅ Manual update successful")
    print()
    
    # Check if server is running
    print("3. Checking if anima server is running...")
    import subprocess
    result = subprocess.run(
        ['pgrep', '-f', 'anima.*--sse'],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        pids = result.stdout.strip().split('\n')
        print(f"   ✅ Server running (PIDs: {', '.join(pids)})")
        print()
        print("4. Checking server logs for display loop...")
        print("   Look for '[Loop]' messages in server output")
        print("   If you don't see '[Loop] Starting', the loop isn't running")
        print()
        print("   To check logs:")
        print("     journalctl -u anima -f  # if systemd")
        print("     # or check stderr of running process")
    else:
        print("   ⚠️  Server not running")
        print("   Start with: anima --sse --host 0.0.0.0 --port 8765")
    print()
    
    print("=" * 60)
    print("Diagnostic complete!")
    print("=" * 60)
    print()
    print("If LEDs work manually but not in server:")
    print("  1. Check server logs for '[Loop]' messages")
    print("  2. Verify display loop is starting (should see '[Loop] Starting')")
    print("  3. Check for LED update errors in logs")
    print("  4. Verify _store and _sensors are initialized")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
