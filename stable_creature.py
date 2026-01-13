"""
Stable Anima Creature Script

Continuous loop that:
1. Reads sensors with robust error handling (retries for I2C)
2. Updates anima state (proprioception)
3. Renders ASCII face based on state
4. Integrates with UNITARES governance bridge if available

Designed to run continuously on the Pi.

⚠️ CRITICAL WARNING ⚠️
─────────────────────────────────────────────────────────────
DO NOT run this script (stable_creature.py) and the main 
anima MCP server (anima --sse) at the same time.

They will fight for I2C sensors and crash the Pi.

Run ONLY ONE:
  - Either: stable_creature.py (standalone ASCII display)
  - Or:     anima --sse (MCP server with display/LEDs)

This script checks for running anima processes at startup
and will exit if detected to prevent conflicts.
─────────────────────────────────────────────────────────────
"""

import time
import os
import signal
import sys
import subprocess
import asyncio
from datetime import datetime
from typing import Optional

# Force UTF-8 for stdout/stderr (prevents crash in systemd service)
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass # If reconfigure fails (e.g. older python), we might be stuck

from src.anima_mcp.sensors import get_sensors
from src.anima_mcp.anima import sense_self
from src.anima_mcp.display.face import derive_face_state, face_to_ascii
# NOTE: LEDs are handled by MCP server, not broker (prevents I2C conflicts)
from src.anima_mcp.identity import IdentityStore
from src.anima_mcp.unitares_bridge import UnitaresBridge
from src.anima_mcp.shared_memory import SharedMemoryClient

# Config
UPDATE_INTERVAL = 2.0  # seconds
MAX_RETRIES = 3
RETRY_DELAY = 0.5

# Global shutdown flag
running = True

def signal_handler(sig, frame):
    global running
    print("\n[StableCreature] Shutdown signal received. Closing gracefully...")
    running = False

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def check_for_running_anima_server():
    """
    Check if anima --sse server is already running.
    
    With Phase 2 Hardware Broker Pattern, both can run simultaneously
    if the MCP server is using shared memory. This check now warns
    but allows continuation if shared memory is available.
    """
    try:
        # Check for anima --sse process
        result = subprocess.run(
            ['pgrep', '-f', 'anima --sse'],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            pids = result.stdout.strip().split('\n')
            pids = [p for p in pids if p]
            if pids:
                # Check if shared memory is available (Redis or file)
                # This indicates Phase 2+ broker pattern is active
                from pathlib import Path
                
                # Check for file-based shared memory (simpler, no import needed)
                shm_file = Path("/dev/shm/anima_state.json") if Path("/dev/shm").exists() else Path("/tmp/anima_state.json")
                file_exists = shm_file.exists()
                
                # Try to check Redis (if available)
                redis_available = False
                try:
                    import redis
                    r = redis.Redis(host='localhost', port=6379, socket_connect_timeout=0.5)
                    redis_available = r.ping() and r.exists("anima:state")
                except:
                    pass
                
                if redis_available or file_exists:
                    print("\n" + "="*70)
                    print("ℹ️  INFO: Main anima MCP server is running")
                    print("="*70)
                    print(f"Found running process(es): {', '.join(pids)}")
                    print(f"\n✅ Shared memory detected - both scripts can run safely!")
                    print("The MCP server will read from shared memory (no I2C conflicts).")
                    print("="*70 + "\n")
                else:
                    print("\n" + "="*70)
                    print("⚠️  WARNING: Main anima MCP server is already running!")
                    print("="*70)
                    print(f"Found running process(es): {', '.join(pids)}")
                    print("\n⚠️  Shared memory not detected - potential I2C conflicts!")
                    print("If the MCP server hasn't been updated to Phase 2, both scripts")
                    print("will access I2C sensors simultaneously and may crash the Pi.")
                    print("\nTo proceed safely:")
                    print("  1. Ensure MCP server is updated to Phase 2 (uses shared memory)")
                    print("  2. Or stop the main server: systemctl --user stop anima")
                    print("  3. Or use the main server instead of this script")
                    print("="*70 + "\n")
                    # Don't exit - allow user to decide, but warn clearly
    except FileNotFoundError:
        # pgrep not available (shouldn't happen on Pi, but handle gracefully)
        pass
    except Exception as e:
        print(f"[StableCreature] Warning: Could not check for running anima server: {e}")

def run_creature():
    # Check for conflicts BEFORE initializing sensors
    check_for_running_anima_server()
    
    print("[StableCreature] Starting up...")
    
    # Initialize components with error handling
    try:
        db_path = os.environ.get("ANIMA_DB", "anima.db")
        store = IdentityStore(db_path)
        identity = store.wake(str(os.environ.get("ANIMA_ID", "stable-anima")))
    except Exception as e:
        print(f"[StableCreature] CRITICAL: Failed to initialize identity store: {e}")
        print("[StableCreature] Exiting to prevent restart loop.")
        sys.exit(1)
    
    # Initialize sensors - allow graceful degradation if hardware unavailable
    try:
        sensors = get_sensors()
        # Check if sensors initialized (at least I2C should be available)
        if hasattr(sensors, '_i2c') and sensors._i2c is None:
            print("[StableCreature] WARNING: I2C initialization failed - hardware may be disconnected")
            print("[StableCreature] Continuing with degraded sensor access (CPU-only readings)")
    except Exception as e:
        print(f"[StableCreature] CRITICAL: Sensor initialization failed: {e}")
        print("[StableCreature] Hardware may be disconnected. Exiting to prevent restart loop.")
        print("[StableCreature] Wait 30 seconds, then check hardware connections before restarting.")
        time.sleep(30)  # Give hardware time to stabilize
        sys.exit(1)
    
    # NOTE: LEDs are NOT initialized here - they're handled by the MCP server
    # This prevents I2C conflicts between broker and MCP server
    
    unitares_url = os.environ.get("UNITARES_URL")
    bridge = UnitaresBridge(unitares_url=unitares_url) if unitares_url else None
    
    # Initialize Shared Memory (Broker Mode)
    # Using file backend for maximum stability (Redis caused hangs)
    try:
        shm_client = SharedMemoryClient(mode="write", backend="file")
        print(f"[StableCreature] Shared Memory active using backend: {shm_client.backend}")
        if shm_client.backend == "file":
            print(f"[StableCreature] File path: {shm_client.filepath}")
    except Exception as e:
        print(f"[StableCreature] CRITICAL: Shared memory initialization failed: {e}")
        print("[StableCreature] Exiting to prevent restart loop.")
        sys.exit(1)
    
    if bridge:
        try:
            bridge.set_agent_id(identity.creature_id)
            bridge.set_session_id(f"anima-{identity.creature_id[:8]}")
            print(f"[StableCreature] UNITARES bridge active: {unitares_url}")
        except Exception as e:
            print(f"[StableCreature] WARNING: UNITARES bridge setup failed: {e}")
            bridge = None  # Continue without governance

    print(f"[StableCreature] Creature '{identity.name or '(unnamed)'}' is alive.")
    print("[StableCreature] Entering main loop...")

    # Initialize event loop for async calls
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    last_decision = None
    
    try:
        while running:
            # 1. Robust Sensor Read
            readings = None
            for attempt in range(MAX_RETRIES):
                try:
                    readings = sensors.read()
                    break
                except Exception as e:
                    print(f"[StableCreature] Sensor read error (attempt {attempt+1}): {e}")
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_DELAY)
            
            if not readings:
                print("[StableCreature] Failed to read sensors after retries. Skipping loop.")
                time.sleep(UPDATE_INTERVAL)
                continue

            # 2. Update Anima State
            anima = sense_self(readings)

            # 3. Governance Check-in (if bridge available) - do BEFORE shared memory write
            # Use timeout to prevent blocking if UNITARES is slow/unreachable
            if bridge:
                try:
                    # Add timeout to prevent freezing if UNITARES is slow
                    is_available = loop.run_until_complete(
                        asyncio.wait_for(bridge.check_availability(), timeout=2.0)
                    )
                    if is_available or bridge._url is None: # local fallback works even if url is None
                        decision = loop.run_until_complete(
                            asyncio.wait_for(bridge.check_in(anima, readings), timeout=2.0)
                        )
                        last_decision = decision
                except asyncio.TimeoutError:
                    print(f"[StableCreature] Governance check-in timeout (UNITARES slow/unreachable) - continuing", file=sys.stderr, flush=True)
                except Exception as e:
                    print(f"[StableCreature] Governance check-in error: {e}", file=sys.stderr, flush=True)

            # 3b. Write to Shared Memory (Broker) - includes governance if available
            shm_data = {
                "timestamp": datetime.now().isoformat(),
                "readings": readings.to_dict(),
                "anima": anima.to_dict(),
                "identity": {
                    "creature_id": identity.creature_id,
                    "name": identity.name,
                    "awakenings": identity.total_awakenings
                }
            }
            if last_decision:
                shm_data["governance"] = last_decision
            shm_client.write(shm_data)

            # 4. Render Face
            face_state = derive_face_state(anima)
            ascii_face = face_to_ascii(face_state)
            
            # Clear screen (terminal) - use ANSI codes to prevent flicker
            # \033[2J = clear screen, \033[H = move cursor to top-left
            print("\033[2J\033[H", end="")
            
            # Print identity and mood
            print(f"Name: {identity.name or 'Anima'} | Mood: {anima.feeling()['mood']}")
            print(f"W: {anima.warmth:.2f} | C: {anima.clarity:.2f} | S: {anima.stability:.2f} | P: {anima.presence:.2f}")
            
            # Print face
            print(ascii_face)
            
            # Print governance if available
            if last_decision:
                action = last_decision.get("action", "UNKNOWN")
                reason = last_decision.get("reason", "")
                print(f"Governance: {action.upper()} - {reason}")
            
            # Record state for persistence
            store.record_state(
                anima.warmth, anima.clarity, anima.stability, anima.presence,
                readings.to_dict()
            )
            
            time.sleep(UPDATE_INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()
        store.sleep()
        store.close()
        shm_client.clear() # Clean up shared memory
        print("[StableCreature] Stopped.")

if __name__ == "__main__":
    run_creature()
