#!/usr/bin/env python3
"""
Test BrainCraft HAT input hardware.

Run this to verify joystick and buttons are working.
"""

import sys
import time
sys.path.insert(0, 'src')

from anima_mcp.input.brainhat_input import get_brainhat_input, JoystickDirection

def main():
    print("BrainCraft HAT Input Test")
    print("=" * 40)
    print("\nMove joystick left/right or press buttons...")
    print("Press Ctrl+C to exit\n")
    
    brainhat = get_brainhat_input()
    brainhat.enable()
    
    if not brainhat.is_available():
        print("ERROR: Input hardware not available!")
        print("Check GPIO pins: D16, D17, D22, D23, D24, D27")
        return 1
    
    print("Input hardware initialized successfully!\n")
    print("Controls:")
    print("  Joystick Left/Right = switch screens")
    print("  Joystick Button (D16) = next screen")
    print("  Separate Button (D17) = face screen")
    print("\nReading input...\n")
    
    prev_state = None
    try:
        while True:
            state = brainhat.read()
            if state:
                # Check for changes
                changed = False
                if prev_state:
                    if state.joystick_direction != prev_state.joystick_direction:
                        print(f"  Direction: {prev_state.joystick_direction.value} → {state.joystick_direction.value}")
                        changed = True
                    if state.joystick_button != prev_state.joystick_button:
                        print(f"  Joystick Button: {prev_state.joystick_button} → {state.joystick_button} {'PRESSED' if state.joystick_button else 'RELEASED'}")
                        changed = True
                    if state.separate_button != prev_state.separate_button:
                        print(f"  Separate Button: {prev_state.separate_button} → {state.separate_button} {'PRESSED' if state.separate_button else 'RELEASED'}")
                        changed = True
                elif state.joystick_direction != JoystickDirection.CENTER or state.joystick_button or state.separate_button:
                    # First read with input
                    print(f"  Initial state: dir={state.joystick_direction.value}, joy_btn={state.joystick_button}, sep_btn={state.separate_button}")
                    changed = True
                
                if not changed and (state.joystick_direction != JoystickDirection.CENTER or state.joystick_button or state.separate_button):
                    # Show current state if something is active
                    print(f"  Active: dir={state.joystick_direction.value}, joy_btn={state.joystick_button}, sep_btn={state.separate_button}")
                
                prev_state = state
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\nTest complete.")
        return 0

if __name__ == "__main__":
    sys.exit(main())
