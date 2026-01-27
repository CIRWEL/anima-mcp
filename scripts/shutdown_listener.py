#!/usr/bin/env python3
"""
Shutdown Listener for BrainCraft HAT

Watches for a long press (3 seconds) on the BrainCraft HAT button (GPIO 17).
Triggers a safe shutdown when detected.

Run as root (required for shutdown command).
"""

import time
import subprocess
import signal
import sys
import os

# Add project root to path to import BrainHatInput
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.anima_mcp.input.brainhat_input import get_brainhat_input

# Config
LONG_PRESS_SECONDS = 3.0
CHECK_INTERVAL = 0.1
BUTTON_GPIO = 17  # Default BrainCraft button

def shutdown():
    """Trigger safe shutdown - saves Lumen's state first."""
    print("shutdown_listener: Triggering safe shutdown...")
    
    # Save Lumen's state before shutdown
    try:
        # Try to save identity state (alive time) via anima service
        # Send SIGTERM to anima service to trigger graceful shutdown
        print("shutdown_listener: Saving Lumen's state...")
        subprocess.run(['systemctl', '--user', 'stop', 'anima'], 
                      timeout=5, stderr=subprocess.DEVNULL)
        time.sleep(1)  # Give service time to save state
    except Exception as e:
        print(f"shutdown_listener: Could not save state gracefully: {e}", file=sys.stderr)
        # Continue anyway - better to shutdown than hang
    
    # Blink LED or give feedback if possible (future enhancement)
    try:
        print("shutdown_listener: Shutting down system...")
        subprocess.run(['shutdown', '-h', 'now'], check=True)
    except Exception as e:
        print(f"shutdown_listener: Failed to shut down: {e}", file=sys.stderr)

def main():
    print("shutdown_listener: Starting...")
    
    input_handler = get_brainhat_input()
    input_handler.enable()
    
    if not input_handler.is_available():
        print("shutdown_listener: Input hardware not available. Exiting.", file=sys.stderr)
        return

    press_start_time = None
    
    try:
        while True:
            state = input_handler.read()
            if not state:
                time.sleep(CHECK_INTERVAL)
                continue
            
            # Check separate button (D17) or Joystick Center (D16)
            is_pressed = state.separate_button or state.joystick_button
            
            if is_pressed:
                if press_start_time is None:
                    press_start_time = time.time()
                    print("shutdown_listener: Button pressed...")
                else:
                    duration = time.time() - press_start_time
                    if duration >= LONG_PRESS_SECONDS:
                        print(f"shutdown_listener: Long press detected ({duration:.1f}s)!")
                        shutdown()
                        break  # Exit loop (system will shut down)
            else:
                if press_start_time is not None:
                    print("shutdown_listener: Button released (too short).")
                    press_start_time = None
            
            time.sleep(CHECK_INTERVAL)
            
    except KeyboardInterrupt:
        print("shutdown_listener: Stopping.")

if __name__ == "__main__":
    main()
