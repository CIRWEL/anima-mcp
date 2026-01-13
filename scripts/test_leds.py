#!/usr/bin/env python3
"""
Test LED display directly - diagnostic tool.
Run on Pi to verify LEDs are working.
"""

import sys
import time
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

try:
    from anima_mcp.display.leds import get_led_display, LEDDisplay
    
    print("=" * 60)
    print("LED Display Diagnostic Test")
    print("=" * 60)
    print()
    
    # Get LED display
    print("1. Initializing LED display...")
    leds = get_led_display()
    
    print(f"   LEDs available: {leds.is_available()}")
    
    if not leds.is_available():
        print()
        print("❌ LEDs not available!")
        print()
        print("Troubleshooting:")
        print("  1. Check SPI is enabled: sudo raspi-config")
        print("  2. Check library: pip list | grep dotstar")
        print("  3. Check pins D5 (data) and D6 (clock)")
        print("  4. Check hardware connection")
        sys.exit(1)
    
    print("   ✅ LEDs initialized")
    print()
    
    # Test 1: Clear (all off)
    print("2. Test: Clear all LEDs (should turn off)...")
    leds.clear()
    time.sleep(1)
    print("   ✅ Cleared")
    print()
    
    # Test 2: Set individual LEDs
    print("3. Test: Set individual LEDs...")
    print("   LED 0 (left): Red")
    leds.set_led(0, (255, 0, 0))
    time.sleep(1)
    
    print("   LED 1 (center): Green")
    leds.set_led(1, (0, 255, 0))
    time.sleep(1)
    
    print("   LED 2 (right): Blue")
    leds.set_led(2, (0, 0, 255))
    time.sleep(1)
    print("   ✅ Individual LEDs working")
    print()
    
    # Test 3: Brightness
    print("4. Test: Brightness control...")
    for brightness in [0.1, 0.3, 0.5, 0.7, 1.0]:
        print(f"   Setting brightness to {brightness:.1f}")
        leds.set_brightness(brightness)
        time.sleep(0.5)
    print("   ✅ Brightness control working")
    print()
    
    # Test 4: Anima state mapping
    print("5. Test: Anima state mapping...")
    test_cases = [
        ("Cold, low clarity, unstable", 0.2, 0.3, 0.3, 0.2),
        ("Warm, clear, stable", 0.7, 0.8, 0.7, 0.8),
        ("Hot, perfect clarity, perfect stability", 0.9, 1.0, 0.9, 1.0),
    ]
    
    for name, warmth, clarity, stability, presence in test_cases:
        print(f"   Testing: {name}")
        print(f"     warmth={warmth:.1f} clarity={clarity:.1f} stability={stability:.1f} presence={presence:.1f}")
        state = leds.update_from_anima(warmth, clarity, stability, presence)
        print(f"     LED 0: {state.led0} (warmth)")
        print(f"     LED 1: {state.led1} (clarity)")
        print(f"     LED 2: {state.led2} (stability+presence)")
        time.sleep(2)
    print("   ✅ Anima mapping working")
    print()
    
    # Test 5: Continuous updates (simulate display loop)
    print("6. Test: Continuous updates (simulating display loop)...")
    print("   Updating every 1 second for 10 seconds...")
    print("   (Press Ctrl+C to stop early)")
    
    import signal
    stop_flag = False
    
    def signal_handler(sig, frame):
        global stop_flag
        stop_flag = True
        print("\n   Stopping...")
    
    signal.signal(signal.SIGINT, signal_handler)
    
    import math
    for i in range(10):
        if stop_flag:
            break
        # Simulate varying anima state
        t = i / 10.0
        warmth = 0.3 + 0.4 * math.sin(t * math.pi * 2)
        clarity = 0.5 + 0.3 * math.cos(t * math.pi * 2)
        stability = 0.6 + 0.2 * math.sin(t * math.pi * 3)
        presence = 0.7 + 0.2 * math.cos(t * math.pi * 1.5)
        
        # Clamp to [0, 1]
        warmth = max(0, min(1, warmth))
        clarity = max(0, min(1, clarity))
        stability = max(0, min(1, stability))
        presence = max(0, min(1, presence))
        
        state = leds.update_from_anima(warmth, clarity, stability, presence)
        print(f"   [{i+1}/10] warmth={warmth:.2f} clarity={clarity:.2f} → LED0={state.led0[0]} LED1={state.led1[0]}")
        time.sleep(1)
    
    print("   ✅ Continuous updates working")
    print()
    
    # Final: Clear
    print("7. Clearing LEDs...")
    leds.clear()
    print("   ✅ Test complete!")
    print()
    print("=" * 60)
    print("All tests passed! LEDs are working correctly.")
    print("=" * 60)
    
except KeyboardInterrupt:
    print("\n\nTest interrupted by user")
    sys.exit(0)
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
