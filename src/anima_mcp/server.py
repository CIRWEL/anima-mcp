"""
Anima MCP Server

Minimal tools for a persistent creature:
- get_state: Current anima (self-sense) + identity
- get_identity: Who am I, how long have I existed
- set_name: Choose my name
- read_sensors: Raw sensor values

Supports both stdio (local) and SSE (network) transports.

Agent Coordination:
- Active agents: Claude + Cursor/Composer
- See docs/AGENT_COORDINATION.md for coordination practices
- Always check docs/ before implementing changes
"""

import argparse
import asyncio
import json
import signal
import sys
import uuid
from datetime import datetime
from typing import Any, Dict

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .identity import IdentityStore
from .sensors import get_sensors, SensorBackend, SensorReadings
from .anima import sense_self, Anima
from .display import derive_face_state, face_to_ascii, get_display, DisplayRenderer
from .display.leds import get_led_display, LEDDisplay
from .display.screens import ScreenRenderer, ScreenMode
from .input.brainhat_input import get_brainhat_input, JoystickDirection as InputDirection
from .next_steps_advocate import get_advocate
from .eisv_mapper import anima_to_eisv
from .config import get_calibration, get_display_config, ConfigManager, NervousSystemCalibration
from .learning import get_learner
from .learning_visualization import LearningVisualizer
from .workflow_orchestrator import UnifiedWorkflowOrchestrator, get_orchestrator
from .workflow_templates import WorkflowTemplates
from .expression_moods import ExpressionMoodTracker
from .shared_memory import SharedMemoryClient


# Global state
_store: IdentityStore | None = None
_sensors: SensorBackend | None = None
_display: DisplayRenderer | None = None
_screen_renderer: ScreenRenderer | None = None
_joystick_enabled: bool = False
_last_governance_decision: Dict[str, Any] | None = None
_last_input_error_log: float = 0.0
_leds: LEDDisplay | None = None
_anima_id: str | None = None
_display_update_task: asyncio.Task | None = None
_shm_client: SharedMemoryClient | None = None


def _get_store() -> IdentityStore:
    """Get identity store - safe, returns None if not available instead of crashing."""
    global _store
    if _store is None:
        # Don't crash - return None and let handlers deal with it gracefully
        print("[Server] Warning: Store not initialized (wake() may have failed)", file=sys.stderr)
        return None
    return _store


def _get_sensors() -> SensorBackend:
    global _sensors
    if _sensors is None:
        _sensors = get_sensors()
    return _sensors


def _get_shm_client() -> SharedMemoryClient:
    """Get shared memory client for reading broker data."""
    global _shm_client
    if _shm_client is None:
        # Use file backend to match broker (Redis caused hangs)
        _shm_client = SharedMemoryClient(mode="read", backend="file")
    return _shm_client




def _readings_from_dict(data: dict) -> SensorReadings:
    """Reconstruct SensorReadings from dictionary."""
    from datetime import datetime
    
    # Parse timestamp
    timestamp_str = data.get("timestamp", "")
    if isinstance(timestamp_str, str):
        try:
            timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            timestamp = datetime.now()
    else:
        timestamp = datetime.now()
    
    return SensorReadings(
        timestamp=timestamp,
        cpu_temp_c=data.get("cpu_temp_c"),
        ambient_temp_c=data.get("ambient_temp_c"),
        humidity_pct=data.get("humidity_pct"),
        light_lux=data.get("light_lux"),
        sound_level=data.get("sound_level"),
        cpu_percent=data.get("cpu_percent"),
        memory_percent=data.get("memory_percent"),
        disk_percent=data.get("disk_percent"),
        power_watts=data.get("power_watts"),
        pressure_hpa=data.get("pressure_hpa"),
        pressure_temp_c=data.get("pressure_temp_c"),
        # EEG raw channels
        eeg_tp9=data.get("eeg_tp9"),
        eeg_af7=data.get("eeg_af7"),
        eeg_af8=data.get("eeg_af8"),
        eeg_tp10=data.get("eeg_tp10"),
        eeg_aux1=data.get("eeg_aux1"),
        eeg_aux2=data.get("eeg_aux2"),
        eeg_aux3=data.get("eeg_aux3"),
        eeg_aux4=data.get("eeg_aux4"),
        # EEG frequency band powers
        eeg_delta_power=data.get("eeg_delta_power"),
        eeg_theta_power=data.get("eeg_theta_power"),
        eeg_alpha_power=data.get("eeg_alpha_power"),
        eeg_beta_power=data.get("eeg_beta_power"),
        eeg_gamma_power=data.get("eeg_gamma_power"),
    )


def _get_readings_and_anima(fallback_to_sensors: bool = True) -> tuple[SensorReadings | None, Anima | None]:
    """
    Read sensor data from shared memory (broker) or fallback to direct sensor access.
    
    Returns:
        Tuple of (readings, anima) or (None, None) if unavailable
    """
    # Try shared memory first (broker mode)
    shm_client = _get_shm_client()
    shm_data = shm_client.read()
    
    if shm_data and "readings" in shm_data and "anima" in shm_data:
        try:
            # Reconstruct SensorReadings from shared memory
            readings = _readings_from_dict(shm_data["readings"])
            
            # Reconstruct Anima from shared memory (but we need readings object)
            # The anima dict has warmth/clarity/stability/presence, but we need to create Anima with readings
            anima_dict = shm_data["anima"]
            calibration = get_calibration()
            
            # Recompute anima from readings (ensures consistency)
            anima = sense_self(readings, calibration)
            
            return readings, anima
        except Exception as e:
            print(f"[Server] Error reading from shared memory: {e}", file=sys.stderr, flush=True)
    
    # Fallback to direct sensor access ONLY if broker is not running
    # If broker is running, don't access I2C directly (prevents hardware conflicts)
    if fallback_to_sensors:
        # Check if broker is running (if so, don't access I2C - wait for shared memory)
        import subprocess
        try:
            broker_running = subprocess.run(
                ['pgrep', '-f', 'stable_creature.py'],
                capture_output=True,
                text=True
            ).returncode == 0
            
            if broker_running:
                print("[Server] Broker is running - waiting for shared memory instead of accessing I2C directly", file=sys.stderr, flush=True)
                return None, None  # Don't access I2C if broker is running
        except Exception:
            pass  # If check fails, proceed with fallback
        
        try:
            sensors = _get_sensors()
            readings = sensors.read()
            calibration = get_calibration()
            anima = sense_self(readings, calibration)
            return readings, anima
        except Exception as e:
            print(f"[Server] Error reading sensors directly: {e}", file=sys.stderr, flush=True)
    
    return None, None


def _get_display() -> DisplayRenderer:
    global _display
    if _display is None:
        _display = get_display()
    return _display


async def _update_display_loop():
    """Background task to continuously update display and LEDs."""
    global _store, _sensors, _display, _leds
    import sys

    print("[Loop] Starting", file=sys.stderr, flush=True)

    # Check if we are in "Reader Mode" (Broker running)
    # If so, we should NOT initialize hardware sensors or display directly
    # The broker handles the hardware; we just read the state.
    is_broker_running = False
    try:
        import subprocess
        is_broker_running = subprocess.run(
            ['pgrep', '-f', 'stable_creature.py'],
            capture_output=True,
            text=True
        ).returncode == 0
    except Exception:
        pass

    if is_broker_running:
        print("[Loop] Broker detected - READER MODE (sensors from shared memory, display/LEDs active)", file=sys.stderr, flush=True)
        # Broker handles sensors - but WE handle display and LEDs (broker doesn't do display/LEDs)
        if _display is None:
            _display = get_display()
        if _leds is None:
            _leds = get_led_display()
    else:
        # Initialize all components on first run (Legacy/Standalone Mode)
        if _sensors is None:
            _sensors = get_sensors()
        if _display is None:
            _display = get_display()
        if _leds is None:
            _leds = get_led_display()

    print(f"[Loop] broker={is_broker_running} store={_store is not None} sensors={_sensors is not None} display={_display.is_available() if _display else False} leds={_leds.is_available() if _leds else False}", file=sys.stderr, flush=True)
    
    # Startup learning: Check if we can learn from existing observations
    # This handles power/network gaps - resume learning immediately on restart
    if _store:
        try:
            learner = get_learner(str(_store.db_path))
            
            # Detect gap since last observation
            gap = learner.detect_gap()
            if gap:
                gap_hours = gap.total_seconds() / 3600
                if gap_hours > 1:
                    print(f"[Learning] Gap detected: {gap_hours:.1f} hours since last observation", file=sys.stderr, flush=True)
            
            if learner.can_learn():
                obs_count = learner.get_observation_count()
                print(f"[Learning] Found {obs_count} existing observations, checking for adaptation...", file=sys.stderr, flush=True)
                # Don't respect cooldown on startup (after gap)
                adapted, new_cal = learner.adapt_calibration(respect_cooldown=False)
                if adapted:
                    print(f"[Learning] Startup adaptation successful!", file=sys.stderr, flush=True)
                    print(f"[Learning] Pressure: {new_cal.pressure_ideal:.1f} hPa, Ambient: {new_cal.ambient_temp_min:.1f}-{new_cal.ambient_temp_max:.1f}°C", file=sys.stderr, flush=True)
                else:
                    print(f"[Learning] No adaptation needed (calibration already optimal)", file=sys.stderr, flush=True)
            elif gap and gap.total_seconds() > 3600:
                print(f"[Learning] Gap detected but not enough observations yet (will learn as new data accumulates)", file=sys.stderr, flush=True)
        except Exception as e:
            # Don't crash on startup learning errors
            print(f"[Learning] Startup check error (non-fatal): {e}", file=sys.stderr, flush=True)

    loop_count = 0
    consecutive_errors = 0
    max_consecutive_errors = 10
    base_delay = 2.0
    max_delay = 30.0
    
    # Global variables for screen switching and governance
    global _screen_renderer, _joystick_enabled, _last_governance_decision
    
    # Start fast input polling task (runs every 100ms for responsive button detection)
    async def fast_input_poll():
        """Fast input polling - runs independently of display loop for responsive controls."""
        global _joystick_enabled, _screen_renderer, _last_input_error_log
        brainhat = get_brainhat_input()
        if not _joystick_enabled:
            try:
                brainhat.enable()
                if brainhat.is_available():
                    _joystick_enabled = True
                    print("[Input] Fast polling enabled", file=sys.stderr, flush=True)
            except Exception:
                pass
        
        while True:
            try:
                if _joystick_enabled and _screen_renderer:
                    input_state = brainhat.read()
                    if input_state:
                        prev_state = brainhat.get_prev_state()
                        current_mode = _screen_renderer.get_mode()
                        import time
                        
                        # Check button presses (edge detection)
                        joy_btn_pressed = input_state.joystick_button and (not prev_state or not prev_state.joystick_button)
                        sep_btn_pressed = input_state.separate_button and (not prev_state or not prev_state.separate_button)
                        
                        # Joystick direction - LEFT/RIGHT cycles through all screens (including notepad)
                        current_dir = input_state.joystick_direction
                        if prev_state:
                            prev_dir = prev_state.joystick_direction
                            # Only trigger on transition TO left/right (edge detection)
                            if current_dir == InputDirection.LEFT and prev_dir != InputDirection.LEFT:
                                old_mode = _screen_renderer.get_mode()
                                _screen_renderer.previous_mode()
                                new_mode = _screen_renderer.get_mode()
                                _screen_renderer._state.last_user_action_time = time.time()
                                print(f"[Input] {old_mode.value} -> {new_mode.value} (left)", file=sys.stderr, flush=True)
                            elif current_dir == InputDirection.RIGHT and prev_dir != InputDirection.RIGHT:
                                old_mode = _screen_renderer.get_mode()
                                _screen_renderer.next_mode()
                                new_mode = _screen_renderer.get_mode()
                                _screen_renderer._state.last_user_action_time = time.time()
                                print(f"[Input] {old_mode.value} -> {new_mode.value} (right)", file=sys.stderr, flush=True)
                        
                        # Button controls
                        # Joystick button = notepad toggle (enter notepad from any screen, exit to face when on notepad)
                        if joy_btn_pressed:
                            if current_mode == ScreenMode.NOTEPAD:
                                # Exit notepad to face (preserves Lumen's work)
                                _screen_renderer.set_mode(ScreenMode.FACE)
                                _screen_renderer._state.last_user_action_time = time.time()
                                print(f"[Notepad] -> face (joystick button)", file=sys.stderr, flush=True)
                            else:
                                # Enter notepad from any screen
                                old_mode = current_mode
                                _screen_renderer.set_mode(ScreenMode.NOTEPAD)
                                _screen_renderer._state.last_user_action_time = time.time()
                                print(f"[Input] {old_mode.value} -> notepad (joystick button)", file=sys.stderr, flush=True)
                        
                        # Separate button
                        if current_mode == ScreenMode.NOTEPAD:
                            # In notepad: separate button = clear canvas
                            if sep_btn_pressed:
                                _screen_renderer.canvas_clear()
                                print(f"[Notepad] Canvas cleared", file=sys.stderr, flush=True)
                        else:
                            # Normal mode: separate button goes to face
                            if sep_btn_pressed:
                                _screen_renderer.set_mode(ScreenMode.FACE)
                                _screen_renderer._state.last_user_action_time = time.time()
                                print(f"[Input] -> face (separate)", file=sys.stderr, flush=True)
            except Exception as e:
                # Log errors but don't spam - only log occasionally
                import time
                global _last_input_error_log
                current_time = time.time()
                if current_time - _last_input_error_log > 5.0:  # Log at most once per 5 seconds
                    print(f"[Input] Error in input polling: {e}", file=sys.stderr, flush=True)
                    import traceback
                    traceback.print_exc(file=sys.stderr)
                    _last_input_error_log = current_time
            await asyncio.sleep(0.1)  # Poll every 100ms for responsive input
    
    # Start fast input polling task
    input_task = None
    try:
        loop = asyncio.get_event_loop()
        input_task = loop.create_task(fast_input_poll())
    except Exception as e:
        print(f"[Input] Failed to start fast polling: {e}", file=sys.stderr, flush=True)
    
    while True:
        try:
            loop_count += 1
            
            # Read current state with error recovery
            # Read from shared memory (broker) or fallback to sensors
            readings, anima = _get_readings_and_anima(fallback_to_sensors=not is_broker_running)
            
            if readings is None or anima is None:
                # Sensor read failed - skip this iteration
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    print(f"[Loop] Too many consecutive errors ({consecutive_errors}), backing off", file=sys.stderr, flush=True)
                    await asyncio.sleep(min(base_delay * (2 ** min(consecutive_errors // 5, 4)), max_delay))
                else:
                    await asyncio.sleep(base_delay)
                continue
            
            consecutive_errors = 0  # Reset on success
            
            # Identity is fundamental - should always be available if wake() succeeded
            # If _store is None, that means wake() failed - log warning but continue
            identity = _store.get_identity() if _store else None
            if identity is None and _store is None:
                if loop_count == 1:
                    print(f"[Loop] WARNING: Identity store not initialized (wake() may have failed) - display will show face without identity info", file=sys.stderr, flush=True)
            
            # Update display and LEDs independently (even in broker mode - broker only handles sensors)
            # Face = what Lumen wants to communicate (conscious expression)
            # LEDs = raw proprioceptive state (unconscious body state)
            # Like a fragile baby: face might smile while LEDs show subtle fatigue
            import time
            update_start = time.time()
            
            # Check BrainCraft HAT input for screen switching
            # Joystick left/right = switch screens
            # Joystick button = cycle screens
            # Separate button = return to face screen

            # Read governance from shared memory (broker writes it there)
            # Fall back to _last_governance_decision if shared memory doesn't have it
            governance_decision_for_display = _last_governance_decision
            shm_client = _get_shm_client()
            shm_data = shm_client.read()
            if shm_data and "governance" in shm_data and isinstance(shm_data["governance"], dict):
                governance_decision_for_display = shm_data["governance"]
            
            # Initialize screen renderer if display is available
            if _display and _display.is_available():
                if _screen_renderer is None:
                    from .display.screens import ScreenRenderer
                    # Pass db_path if store is available
                    db_path = str(_store.db_path) if _store else "anima.db"
                    _screen_renderer = ScreenRenderer(_display, db_path=db_path, identity_store=_store)
                    print("[Display] Screen renderer initialized", file=sys.stderr, flush=True)
            
            # Input is now handled by fast_input_poll() task (runs every 100ms)
            # This keeps the display loop at 2s while input stays responsive
            
            # Update TFT display (with screen switching support)
            # Face reflects what Lumen wants to communicate
            # Other screens show sensors, identity, diagnostics
            display_updated = False
            if _display:
                if _display.is_available():
                    from .error_recovery import safe_call

                    def update_display():
                        # Derive face state independently - what Lumen wants to express
                        if anima is None:
                            return False
                        face_state = derive_face_state(anima)
                        
                        # Use screen renderer if available (supports multiple screens)
                        if _screen_renderer:
                            # governance_decision_for_display is set by governance check-in (runs every 30 iterations)
                            # It's None on most iterations, but will have value after governance check-ins
                            _screen_renderer.render(
                                face_state=face_state,
                                anima=anima,
                                readings=readings,
                                identity=identity,
                                governance=governance_decision_for_display
                            )
                        else:
                            # Fallback: render face directly
                            identity_name = identity.name if identity else None
                            _display.render_face(face_state, name=identity_name)
                        return True  # Return success indicator

                    display_result = safe_call(update_display, default=False, log_error=True)
                    display_updated = display_result is True
                    if display_updated:
                        display_duration = time.time() - update_start
                        if loop_count == 1:
                            print(f"[Loop] Display render successful - face showing", file=sys.stderr, flush=True)
                    elif loop_count == 1:
                        print(f"[Loop] Display available but render failed (check error logs)", file=sys.stderr, flush=True)
                else:
                    if loop_count == 1:
                        print(f"[Loop] Display initialized but hardware not available (not on Pi or hardware issue?)", file=sys.stderr, flush=True)
                        print(f"[Loop] Run diagnostics: python3 -m anima_mcp.display_diagnostics", file=sys.stderr, flush=True)
            else:
                if loop_count == 1:
                    print(f"[Loop] Display not initialized", file=sys.stderr, flush=True)

            # Update LEDs with raw anima state (independent from face)
            # LEDs reflect proprioceptive state directly - what Lumen actually feels
            led_updated = False
            if _leds and _leds.is_available():
                from .error_recovery import safe_call

                # Get light level for auto-brightness
                light_level = readings.light_lux if readings else None

                def update_leds():
                    # LEDs derive their own state directly from anima - no face influence
                    return _leds.update_from_anima(
                        anima.warmth, anima.clarity,
                        anima.stability, anima.presence,
                        light_level=light_level,
                        face_state=None  # Independent - LEDs show raw proprioceptive state
                    )

                led_state = safe_call(update_leds, default=None, log_error=True)
                led_updated = led_state is not None
                if led_updated and loop_count == 1:
                    total_duration = time.time() - update_start
                    print(f"[Loop] LED update took {total_duration*1000:.1f}ms", file=sys.stderr, flush=True)
                    print(f"[Loop] LED update (independent): warmth={anima.warmth:.2f} clarity={anima.clarity:.2f} stability={anima.stability:.2f} presence={anima.presence:.2f}", file=sys.stderr, flush=True)
                    print(f"[Loop] LED colors: led0={led_state.led0} led1={led_state.led1} led2={led_state.led2}", file=sys.stderr, flush=True)
            elif _leds:
                if loop_count == 1:
                    print(f"[Loop] LEDs not available (hardware issue?)", file=sys.stderr, flush=True)
            
            # Log update status every 20th iteration
            if loop_count % 20 == 1 and (display_updated or led_updated):
                update_duration = time.time() - update_start
                update_status = []
                if display_updated:
                    update_status.append("display")
                if led_updated:
                    update_status.append("LEDs")
                print(f"[Loop] Display/LED updates ({', '.join(update_status)}): {update_duration*1000:.1f}ms", file=sys.stderr, flush=True)
            
            # Log every 5th iteration with LED status and key metrics
            if loop_count % 5 == 1:
                led_status = "available" if (_leds and _leds.is_available()) else "unavailable"
            
            # Adaptive learning: Every 100 iterations (~3.3 minutes), check if calibration should adapt
            # Respects cooldown to avoid redundant adaptations during continuous operation
            if loop_count % 100 == 0 and _store:
                from .error_recovery import safe_call
                
                def try_learning():
                    learner = get_learner(str(_store.db_path))
                    adapted, new_cal = learner.adapt_calibration(respect_cooldown=True)
                    if adapted:
                        print(f"[Learning] Calibration adapted after {loop_count} observations", file=sys.stderr, flush=True)
                        print(f"[Learning] Pressure: {new_cal.pressure_ideal:.1f} hPa, Ambient: {new_cal.ambient_temp_min:.1f}-{new_cal.ambient_temp_max:.1f}°C", file=sys.stderr, flush=True)
                
                safe_call(try_learning, default=None, log_error=False)
            
            # UNITARES governance check-in: Every 30 iterations (~1 minute)
            # Provides continuous governance feedback for self-regulation
            # Uses Lumen's actual identity (creature_id) for proper binding
            # Syncs identity metadata on first check-in
            if loop_count % 30 == 0 and readings and anima and identity:
                import os
                unitares_url = os.environ.get("UNITARES_URL")
                if unitares_url:
                    from .error_recovery import safe_call_async
                    from .unitares_bridge import UnitaresBridge
                    
                    # Track if this is the first check-in (for identity sync)
                    is_first_check_in = (loop_count == 30)
                    
                    async def check_in_governance():
                        bridge = UnitaresBridge(unitares_url=unitares_url)
                        # Use Lumen's actual identity for proper UNITARES binding
                        bridge.set_agent_id(identity.creature_id)
                        bridge.set_session_id(f"anima-{identity.creature_id[:8]}")
                        # Pass identity for metadata sync and include in check-in
                        decision = await bridge.check_in(
                            anima, readings,
                            identity=identity,
                            is_first_check_in=is_first_check_in
                        )
                        return decision
                    
                    try:
                        decision = await safe_call_async(check_in_governance, default=None, log_error=True)
                        if decision:
                            # Store governance decision for potential expression feedback and diagnostics screen
                            # Future: Could influence face/LED expression based on governance state
                            _last_governance_decision = decision
                            
                            # Log periodically
                            if loop_count % 60 == 0:  # Log every 2 minutes
                                action = decision.get("action", "unknown")
                                margin = decision.get("margin", "unknown")
                                source = decision.get("source", "unknown")
                                print(f"[Governance] Check-in: {action} ({margin}) from {source}", file=sys.stderr, flush=True)
                            
                            # Future: Expression feedback loop
                            # If governance says "pause" or "tight margin", could subtly influence expression
                            # For now, just store the decision - expression remains independent
                        else:
                            _last_governance_decision = None
                    except Exception as e:
                        # Non-fatal - governance check-ins are optional
                        _last_governance_decision = None
                        if loop_count % 60 == 0:
                            print(f"[Governance] Check-in skipped: {e}", file=sys.stderr, flush=True)

            # Update every 2 seconds (with exponential backoff on errors)
            delay = base_delay if consecutive_errors == 0 else min(base_delay * (1.5 ** min(consecutive_errors, 3)), max_delay)
            await asyncio.sleep(delay)
            
        except KeyboardInterrupt:
            # Allow graceful shutdown
            raise
        except Exception as e:
            # Don't crash on display errors, just log and continue with exponential backoff
            consecutive_errors += 1
            error_type = type(e).__name__
            print(f"[Loop] Error ({error_type}): {e}", file=sys.stderr, flush=True)
            
            # Exponential backoff on errors
            delay = min(base_delay * (2 ** min(consecutive_errors // 3, 4)), max_delay)
            await asyncio.sleep(delay)


def start_display_loop():
    """Start continuous display update loop."""
    global _display_update_task
    try:
        if _display_update_task is None or _display_update_task.done():
            # Check if we're in an async context
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                # No event loop running - will be started later
                print("[Display] No event loop yet, will start when available", file=sys.stderr, flush=True)
                return
            
            _display_update_task = asyncio.create_task(_update_display_loop())
            print("[Display] Started continuous update loop", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"[Display] Error starting display loop: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)


def stop_display_loop():
    """Stop continuous display update loop."""
    global _display_update_task
    try:
        if _display_update_task and not _display_update_task.done():
            _display_update_task.cancel()
            try:
                print("[Display] Stopped continuous update loop", file=sys.stderr, flush=True)
            except (ValueError, OSError):
                # stdout/stderr might be closed - ignore
                pass
    except Exception as e:
        # Don't crash on shutdown errors
        try:
            print(f"[Display] Error stopping display loop: {e}", file=sys.stderr, flush=True)
        except (ValueError, OSError):
            pass


# ============================================================
# Tool Handlers
# ============================================================

async def handle_get_state(arguments: dict) -> list[TextContent]:
    """Get current state: anima (self-sense) + identity. Safe, never crashes."""
    store = _get_store()
    if store is None:
        return [TextContent(type="text", text=json.dumps({
            "error": "Server not initialized - wake() failed",
            "suggestion": "Check server logs for initialization errors"
        }))]
    
    sensors = _get_sensors()

    # Read from shared memory (broker) or fallback to sensors
    readings, anima = _get_readings_and_anima()
    if readings is None or anima is None:
        return [TextContent(type="text", text=json.dumps({
            "error": "Unable to read sensor data"
        }))]
    
    try:
        identity = store.get_identity()
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Error reading identity: {e}"
        }))]

    result = {
        "anima": {
            "warmth": anima.warmth,
            "clarity": anima.clarity,
            "stability": anima.stability,
            "presence": anima.presence,
        },
        "mood": anima.feeling()["mood"],
        "feeling": anima.feeling(),
        "identity": {
            "name": identity.name,
            "id": identity.creature_id[:8] + "...",
            "awakenings": identity.total_awakenings,
            "age_seconds": round(identity.age_seconds()),
            "alive_seconds": round(identity.total_alive_seconds + store.get_session_alive_seconds()),
            "alive_ratio": round(identity.alive_ratio(), 3),
        },
        "sensors": readings.to_dict(),
        "is_pi": sensors.is_pi(),
    }

    # Record state for history
    store.record_state(
        anima.warmth, anima.clarity, anima.stability, anima.presence,
        readings.to_dict()
    )

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def handle_get_identity(arguments: dict) -> list[TextContent]:
    """Get full identity: birth, awakenings, name history. Safe, never crashes."""
    store = _get_store()
    if store is None:
        return [TextContent(type="text", text=json.dumps({
            "error": "Server not initialized - wake() failed"
        }))]
    
    try:
        identity = store.get_identity()
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Error reading identity: {e}"
        }))]

    result = {
        "id": identity.creature_id,
        "name": identity.name,
        "born_at": identity.born_at.isoformat(),
        "total_awakenings": identity.total_awakenings,
        "current_awakening_at": identity.current_awakening_at.isoformat() if identity.current_awakening_at else None,
        "total_alive_seconds": round(identity.total_alive_seconds + store.get_session_alive_seconds()),
        "age_seconds": round(identity.age_seconds()),
        "alive_ratio": round(identity.alive_ratio(), 3),
        "name_history": identity.name_history,
        "session_alive_seconds": round(store.get_session_alive_seconds()),
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def handle_switch_screen(arguments: dict) -> list[TextContent]:
    """Switch display screen mode. Safe, never crashes."""
    global _screen_renderer
    
    if not _screen_renderer:
        return [TextContent(type="text", text=json.dumps({
            "error": "Screen renderer not initialized"
        }))]
    
    mode_str = arguments.get("mode", "").lower()
    
    # Map string to ScreenMode
    mode_map = {
        "face": ScreenMode.FACE,
        "sensors": ScreenMode.SENSORS,
        "identity": ScreenMode.IDENTITY,
        "diagnostics": ScreenMode.DIAGNOSTICS,
        "notepad": ScreenMode.NOTEPAD,
        "learning": ScreenMode.LEARNING,
    }
    
    if mode_str in mode_map:
        _screen_renderer.set_mode(mode_map[mode_str])
        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "mode": mode_str,
            "message": f"Switched to {mode_str} screen"
        }))]
    elif mode_str == "next":
        _screen_renderer.next_mode()
        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "mode": _screen_renderer.get_mode().value,
            "message": f"Switched to {_screen_renderer.get_mode().value} screen"
        }))]
    elif mode_str == "previous" or mode_str == "prev":
        _screen_renderer.previous_mode()
        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "mode": _screen_renderer.get_mode().value,
            "message": f"Switched to {_screen_renderer.get_mode().value} screen"
        }))]
    else:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Invalid mode: {mode_str}",
            "valid_modes": ["face", "sensors", "identity", "diagnostics", "learning", "notepad", "next", "previous"]
        }))]


async def handle_set_name(arguments: dict) -> list[TextContent]:
    """Set or change name. Safe, never crashes."""
    store = _get_store()
    if store is None:
        return [TextContent(type="text", text=json.dumps({
            "error": "Server not initialized - wake() failed"
        }))]
    
    name = arguments.get("name")

    if not name:
        return [TextContent(type="text", text=json.dumps({
            "error": "name parameter required"
        }))]

    old_name = store.get_identity().name
    store.set_name(name)

    return [TextContent(type="text", text=json.dumps({
        "success": True,
        "old_name": old_name,
        "new_name": name,
        "message": f"I am now called {name}" if not old_name else f"I was {old_name}, now I am {name}",
    }))]


async def handle_read_sensors(arguments: dict) -> list[TextContent]:
    """Read raw sensor values."""
    sensors = _get_sensors()
    
    # Read from shared memory (broker) or fallback to sensors
    readings, _ = _get_readings_and_anima()
    if readings is None:
        return [TextContent(type="text", text=json.dumps({
            "error": "Unable to read sensor data"
        }))]

    result = {
        "readings": readings.to_dict(),
        "available_sensors": sensors.available_sensors(),
        "is_pi": sensors.is_pi(),
        "source": "shared_memory" if _shm_client and _shm_client.read() else "direct_sensors",
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def handle_show_face(arguments: dict) -> list[TextContent]:
    """Show face on display (or return ASCII art if no display). Safe, never crashes."""
    store = _get_store()
    sensors = _get_sensors()
    display = _get_display()

    # Read from shared memory (broker) or fallback to sensors
    readings, anima = _get_readings_and_anima()
    if readings is None or anima is None:
        return [TextContent(type="text", text=json.dumps({
            "error": "Unable to read sensor data"
        }))]
    
    if store is None:
        identity_name = None
        identity = None
    else:
        try:
            identity = store.get_identity()
            identity_name = identity.name if identity else None
        except Exception:
            identity_name = None
            identity = None
    face_state = derive_face_state(anima)

    # Try to render on hardware display
    if display.is_available():
        display.render_face(face_state, name=identity_name)
        result = {
            "rendered": True,
            "display": "hardware",
            "eyes": face_state.eyes.value,
            "mouth": face_state.mouth.value,
            "mood": anima.feeling()["mood"],
        }
    else:
        # Return ASCII art
        ascii_face = face_to_ascii(face_state)
        result = {
            "rendered": False,
            "display": "ascii",
            "face": ascii_face,
            "eyes": face_state.eyes.value,
            "mouth": face_state.mouth.value,
            "mood": anima.feeling()["mood"],
        }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def handle_diagnostics(arguments: dict) -> list[TextContent]:
    """Get system diagnostics including LED and display status."""
    global _leds, _display, _display_update_task
    
    sensors = _get_sensors()
    
    # LED diagnostics
    led_info = {}
    if _leds:
        led_info = _leds.get_diagnostics()
    else:
        led_info = {"available": False, "reason": "not initialized"}
    
    # Display diagnostics
    display_info = {
        "available": _display.is_available() if _display else False,
        "initialized": _display is not None,
    }
    
    # Update loop status
    loop_info = {
        "task_exists": _display_update_task is not None,
        "task_done": _display_update_task.done() if _display_update_task else None,
        "task_cancelled": _display_update_task.cancelled() if _display_update_task else None,
    }
    
    result = {
        "leds": led_info,
        "display": display_info,
        "update_loop": loop_info,
        "sensors": {
            "is_pi": sensors.is_pi(),
            "available": sensors.available_sensors(),
        },
    }
    
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def handle_test_leds(arguments: dict) -> list[TextContent]:
    """Run LED test sequence."""
    global _leds
    
    if _leds is None:
        _leds = get_led_display()
    
    if not _leds.is_available():
        return [TextContent(type="text", text=json.dumps({
            "success": False,
            "error": "LEDs not available",
            "diagnostics": _leds.get_diagnostics() if _leds else None,
        }))]
    
    success = _leds.test_sequence()
    
    return [TextContent(type="text", text=json.dumps({
        "success": success,
        "message": "Test sequence complete - check LEDs",
    }))]


async def handle_get_calibration(arguments: dict) -> list[TextContent]:
    """Get current nervous system calibration."""
    calibration = get_calibration()
    
    result = {
        "calibration": calibration.to_dict(),
        "config_file": str(ConfigManager().config_path),
        "config_exists": ConfigManager().config_path.exists(),
    }
    
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def handle_learning_visualization(arguments: dict) -> list[TextContent]:
    """Get learning visualization - shows why Lumen feels what it feels."""
    store = _get_store()
    if store is None:
        return [TextContent(type="text", text=json.dumps({
            "error": "Server not initialized - wake() failed"
        }))]
    
    # Get current state
    readings, anima = _get_readings_and_anima()
    if readings is None or anima is None:
        return [TextContent(type="text", text=json.dumps({
            "error": "Unable to read sensor data"
        }))]
    
    # Create visualizer
    visualizer = LearningVisualizer(db_path=str(store.db_path))
    
    # Get comprehensive learning summary
    summary = visualizer.get_learning_summary(readings=readings, anima=anima)
    
    return [TextContent(type="text", text=json.dumps(summary, indent=2))]


async def handle_get_expression_mood(arguments: dict) -> list[TextContent]:
    """Get Lumen's current expression mood - persistent drawing style preferences."""
    store = _get_store()
    if store is None:
        return [TextContent(type="text", text=json.dumps({
            "error": "Server not initialized - wake() failed"
        }))]
    
    mood_tracker = ExpressionMoodTracker(identity_store=store)
    mood_info = mood_tracker.get_mood_info()
    
    return [TextContent(type="text", text=json.dumps(mood_info, indent=2))]


async def handle_set_calibration(arguments: dict) -> list[TextContent]:
    """Update nervous system calibration (partial updates supported)."""
    calibration = get_calibration()
    config_manager = ConfigManager()
    
    # Allow partial updates
    updates = arguments.get("updates", {})
    if not updates:
        return [TextContent(type="text", text=json.dumps({
            "error": "updates parameter required",
            "example": {
                "updates": {
                    "ambient_temp_min": 10.0,
                    "ambient_temp_max": 30.0,
                    "pressure_ideal": 833.0
                }
            }
        }))]
    
    # Update calibration values
    cal_dict = calibration.to_dict()
    cal_dict.update(updates)
    
    try:
        updated_cal = NervousSystemCalibration.from_dict(cal_dict)
        
        # Validate
        valid, error = updated_cal.validate()
        if not valid:
            return [TextContent(type="text", text=json.dumps({
                "error": f"Invalid calibration: {error}",
                "current": calibration.to_dict(),
            }))]
        
        # Update config
        config = config_manager.load()
        config.nervous_system = updated_cal
        
        if config_manager.save(config):
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "message": "Calibration updated",
                "calibration": updated_cal.to_dict(),
            }))]
        else:
            return [TextContent(type="text", text=json.dumps({
                "error": "Failed to save calibration",
            }))]
            
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Error updating calibration: {e}",
        }))]


async def handle_next_steps(arguments: dict) -> list[TextContent]:
    """Get proactive next steps to achieve goals. Safe, never crashes."""
    store = _get_store()
    if store is None:
        return [TextContent(type="text", text=json.dumps({
            "error": "Server not initialized - wake() failed"
        }))]
    
    sensors = _get_sensors()
    display = _get_display()
    
    # Read from shared memory (broker) or fallback to sensors
    readings, anima = _get_readings_and_anima()
    if readings is None or anima is None:
        return [TextContent(type="text", text=json.dumps({
            "error": "Unable to read sensor data"
        }))]
    
    eisv = anima_to_eisv(anima, readings)
    
    # Check availability
    display_available = display.is_available()
    # BrainCraft HAT hardware (display + LEDs + sensors) is available if display is available
    # Note: No physical EEG hardware exists - neural signals come from computational proprioception
    brain_hat_hardware_available = display_available  # BrainCraft HAT = display hardware (not EEG)
    # Check UNITARES (try to import bridge)
    unitares_connected = False
    unitares_status = "not_configured"
    try:
        import os
        from .unitares_bridge import UnitaresBridge
        unitares_url = os.environ.get("UNITARES_URL")
        if unitares_url:
            bridge = UnitaresBridge(unitares_url=unitares_url)
            unitares_connected = await bridge.check_availability()
            unitares_status = "connected" if unitares_connected else "unavailable"
            if unitares_connected:
                print(f"[Diagnostics] UNITARES connected: {unitares_url}", file=sys.stderr, flush=True)
            else:
                print(f"[Diagnostics] UNITARES URL set but unavailable: {unitares_url}", file=sys.stderr, flush=True)
        else:
            unitares_status = "not_configured"
            print("[Diagnostics] UNITARES_URL not set", file=sys.stderr, flush=True)
    except Exception as e:
        unitares_status = f"error: {str(e)}"
        print(f"[Diagnostics] UNITARES check failed: {e}", file=sys.stderr, flush=True)
    
    # Get advocate recommendations
    advocate = get_advocate()
    steps = advocate.analyze_current_state(
        anima=anima,
        readings=readings,
        eisv=eisv,
        display_available=display_available,
        brain_hat_available=brain_hat_hardware_available,
        unitares_connected=unitares_connected,
    )
    
    summary = advocate.get_next_steps_summary()
    
    # Extract next action details for easier access
    next_action = summary.get("next_action", {})
    
    result = {
        "summary": {
            "priority": next_action.get("priority", "unknown") if next_action else "none",
            "feeling": next_action.get("feeling", "unknown") if next_action else "none",
            "desire": next_action.get("desire", "unknown") if next_action else "none",
            "action": next_action.get("action", "unknown") if next_action else "none",
            "total_steps": summary.get("total_steps", 0),
            "critical": summary.get("critical", 0),
            "high": summary.get("high", 0),
            "medium": summary.get("medium", 0),
            "low": summary.get("low", 0),
            "all_steps": summary.get("all_steps", []),
        },
        "current_state": {
            "display_available": display_available,
            "brain_hat_hardware_available": brain_hat_hardware_available,
            "unitares_connected": unitares_connected,
            "unitares_status": unitares_status,
            "anima": {
                "warmth": anima.warmth,
                "clarity": anima.clarity,
                "stability": anima.stability,
                "presence": anima.presence,
            },
            "eisv": eisv.to_dict(),
        },
    }
    
    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def handle_unified_workflow(arguments: dict) -> list[TextContent]:
    """Execute unified workflows across anima-mcp and unitares-governance. Safe, never crashes.
    
    Supports both original workflows and workflow templates.
    If workflow name matches a template, uses template. Otherwise uses original workflow logic.
    """
    import os
    from .workflow_orchestrator import get_orchestrator
    from .workflow_templates import WorkflowTemplates

    store = _get_store()
    if store is None:
        return [TextContent(type="text", text=json.dumps({
            "error": "Server not initialized - wake() failed"
        }))]
    
    sensors = _get_sensors()
    unitares_url = os.environ.get("UNITARES_URL")

    orchestrator = get_orchestrator(
        unitares_url=unitares_url,
        anima_store=store,
        anima_sensors=sensors
    )

    workflow = arguments.get("workflow")
    
    # If no workflow specified, return available options
    if not workflow:
        templates = WorkflowTemplates(orchestrator)
        template_list = templates.list_templates()
        return [TextContent(type="text", text=json.dumps({
            "available_workflows": ["check_state_and_governance", "monitor_and_govern"],
            "available_templates": [t["name"] for t in template_list],
            "usage": "Call with workflow=<name> to execute"
        }, indent=2))]

    interval = arguments.get("interval", 60.0)

    # Check if it's a template first
    templates = WorkflowTemplates(orchestrator)
    template = templates.get_template(workflow)
    
    if template:
        # It's a template - run it
        result_obj = await templates.run(workflow)
        result = {
            "status": result_obj.status.value,
            "summary": result_obj.summary,
            "steps": result_obj.steps,
            "errors": result_obj.errors,
            "template": workflow,
        }
    elif workflow == "check_state_and_governance":
        # Original workflow
        result = await orchestrator.workflow_check_state_and_governance()
    elif workflow == "monitor_and_govern":
        # Original workflow
        result = await orchestrator.workflow_check_state_and_governance()
        result["note"] = f"Single check performed. Use interval={interval}s for continuous monitoring."
    else:
        # Unknown - suggest alternatives
        template_list = templates.list_templates()
        result = {
            "error": f"Unknown workflow: {workflow}",
            "available_workflows": ["check_state_and_governance", "monitor_and_govern"],
            "available_templates": [t["name"] for t in template_list],
        }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


# ============================================================
# Tool Registry
# ============================================================

TOOLS = [
    Tool(
        name="get_state",
        description="Get current anima (warmth, clarity, stability, presence), mood, and identity",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="get_identity",
        description="Get full identity: birth, awakenings, name history, existence duration",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="switch_screen",
        description="Switch display screen mode (face, sensors, identity, diagnostics, learning, notepad, next, previous)",
        inputSchema={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "description": "Screen mode: 'face', 'sensors', 'identity', 'diagnostics', 'learning', 'notepad', 'next', or 'previous'",
                    "enum": ["face", "sensors", "identity", "diagnostics", "learning", "notepad", "next", "previous", "prev"]
                }
            },
            "required": ["mode"],
        },
    ),
    Tool(
        name="set_name",
        description="Set or change name",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The name to use"}
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="read_sensors",
        description="Read raw sensor values (temperature, humidity, light, system stats)",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="show_face",
        description="Show face on display (renders to hardware on Pi, returns ASCII art otherwise)",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="next_steps",
        description="Get proactive next steps to achieve goals - analyzes current state and suggests what to do next",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="diagnostics",
        description="Get system diagnostics including LED status, display status, and update loop health",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="unified_workflow",
        description="Execute workflows and templates across anima-mcp and unitares-governance. Call without 'workflow' to see available options. Supports: check_state_and_governance, monitor_and_govern, and workflow templates (health_check, full_system_check, learning_check, etc.)",
        inputSchema={
            "type": "object",
            "properties": {
                "workflow": {
                    "type": "string",
                    "description": "Workflow or template name. Original workflows: 'check_state_and_governance', 'monitor_and_govern'. Templates: 'health_check', 'full_system_check', 'learning_check', 'governance_check', 'identity_check', 'sensor_analysis'. Omit to list all options."
                },
                "interval": {
                    "type": "number",
                    "description": "For monitor_and_govern: seconds between checks (default: 60)",
                    "default": 60.0
                }
            },
            "required": []
        },
    ),
    Tool(
        name="test_leds",
        description="Run LED test sequence - cycles through colors to verify hardware works",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="get_calibration",
        description="Get current nervous system calibration (temperature ranges, ideal values, weights)",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="set_calibration",
        description="Update nervous system calibration - adapt Lumen to different environments",
        inputSchema={
            "type": "object",
            "properties": {
                "updates": {
                    "type": "object",
                    "description": "Partial calibration updates (e.g., {'ambient_temp_min': 10.0, 'pressure_ideal': 833.0})"
                }
            },
            "required": ["updates"],
        },
    ),
    Tool(
        name="learning_visualization",
        description="Get learning visualization - shows why Lumen feels what it feels, comfort zones, patterns, and calibration history",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="get_expression_mood",
        description="Get Lumen's current expression mood - persistent drawing style preferences that evolve over time",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
]

HANDLERS = {
    "unified_workflow": handle_unified_workflow,
    "get_state": handle_get_state,
    "get_identity": handle_get_identity,
        "set_name": handle_set_name,
        "switch_screen": handle_switch_screen,
    "read_sensors": handle_read_sensors,
    "show_face": handle_show_face,
    "next_steps": handle_next_steps,
    "diagnostics": handle_diagnostics,
    "test_leds": handle_test_leds,
    "get_calibration": handle_get_calibration,
    "set_calibration": handle_set_calibration,
    "learning_visualization": handle_learning_visualization,
    "get_expression_mood": handle_get_expression_mood,
}


# ============================================================
# Server Setup
# ============================================================

def create_server() -> Server:
    """Create and configure the MCP server."""
    server = Server("anima-mcp")

    @server.list_tools()
    async def list_tools():
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None):
        handler = HANDLERS.get(name)
        if not handler:
            return [TextContent(type="text", text=json.dumps({
                "error": f"Unknown tool: {name}",
                "available": list(HANDLERS.keys()),
            }))]
        return await handler(arguments or {})

    return server


def wake(db_path: str = "anima.db", anima_id: str | None = None):
    """
    Wake up. Call before starting server. Safe, never crashes.

    Args:
        db_path: Path to SQLite database
        anima_id: UUID (generated if not provided)
    """
    global _store, _anima_id

    try:
        _anima_id = anima_id or str(uuid.uuid4())
        _store = IdentityStore(db_path)
        identity = _store.wake(_anima_id)

        # Identity (name + birthdate) is fundamental to Lumen's existence
        print(f"Awake: {identity.name or '(unnamed)'}")
        print(f"  ID: {identity.creature_id[:8]}...")
        print(f"  Awakening #{identity.total_awakenings}")
        print(f"  Born: {identity.born_at.isoformat()}")
        print(f"  Total alive: {identity.total_alive_seconds:.0f}s")
    except Exception as e:
        print(f"[Server] CRITICAL: Error during wake: {e}", file=sys.stderr)
        print(f"[Server] Identity store failed - creature cannot establish persistent identity", file=sys.stderr)
        print(f"[Server] Display will work but identity features unavailable", file=sys.stderr)
        # Continue anyway - store might be None but server can still run (display can show face without identity)
        _store = None


def sleep():
    """Go to sleep. Call on server shutdown."""
    global _store
    if _store:
        try:
            session_seconds = _store.sleep()
            try:
                print(f"Sleeping. Session: {session_seconds:.0f}s", file=sys.stderr, flush=True)
            except (ValueError, OSError):
                # stdout/stderr might be closed - ignore
                pass
            _store.close()
        except Exception as e:
            # Don't crash on shutdown errors
            try:
                print(f"[Sleep] Error during sleep: {e}", file=sys.stderr, flush=True)
            except (ValueError, OSError):
                pass
        finally:
            _store = None


async def run_stdio_server():
    """Run the MCP server over stdio (local)."""
    server = create_server()
    
    # Start display update loop
    start_display_loop()

    # Handle graceful shutdown
    def shutdown_handler(sig, frame):
        try:
            print("\nShutting down...", file=sys.stderr, flush=True)
        except (ValueError, OSError):
            pass  # stdout/stderr might be closed
        try:
            stop_display_loop()
            sleep()
        except Exception:
            pass  # Don't crash on shutdown errors
        raise SystemExit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    finally:
        stop_display_loop()


def run_sse_server(host: str, port: int):
    """Run the MCP server over SSE (network)."""
    try:
        from contextlib import asynccontextmanager
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.responses import Response
        from mcp.server.sse import SseServerTransport
        import uvicorn
    except ImportError:
        print("SSE dependencies not installed. Run: pip install anima-mcp[sse]")
        raise SystemExit(1)

    server = create_server()
    sse = SseServerTransport("/messages")

    async def handle_sse(request):
        try:
            async with sse.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await server.run(
                    streams[0], streams[1], server.create_initialization_options()
                )
        except Exception as e:
            print(f"[SSE] Error in SSE handler: {e}", file=sys.stderr, flush=True)
        # Return empty response to satisfy Starlette (actual response sent via ASGI)
        return Response(status_code=200)

    async def handle_messages(request):
        try:
            await sse.handle_post_message(request.scope, request.receive, request._send)
        except Exception as e:
            print(f"[SSE] Error in messages handler: {e}", file=sys.stderr, flush=True)
        # Return empty response to satisfy Starlette (actual response sent via ASGI)
        return Response(status_code=200)

    @asynccontextmanager
    async def lifespan(app):
        # Start display loop when event loop is running
        print("[Server] Starting display loop...", file=sys.stderr, flush=True)
        start_display_loop()
        print("[Server] Display loop started", file=sys.stderr, flush=True)
        yield
        # Stop on shutdown
        print("[Server] Stopping display loop...", file=sys.stderr, flush=True)
        stop_display_loop()

    async def handle_root(request):
        """Handle root and unknown paths - return simple status."""
        return Response(content="Lumen MCP Server", status_code=200)

    async def handle_health(request):
        """Health check endpoint."""
        return Response(content="ok", status_code=200)

    app = Starlette(
        routes=[
            Route("/", endpoint=handle_root),
            Route("/health", endpoint=handle_health),
            Route("/sse", endpoint=handle_sse),
            Route("/messages", endpoint=handle_messages, methods=["POST"]),
        ],
        lifespan=lifespan,
    )

    # Handle graceful shutdown
    def shutdown_handler(sig, frame):
        try:
            print("\nShutting down...", file=sys.stderr, flush=True)
        except (ValueError, OSError):
            pass  # stdout/stderr might be closed
        try:
            stop_display_loop()
            sleep()
        except Exception:
            pass  # Don't crash on shutdown errors
        raise SystemExit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    print(f"SSE server running at http://{host}:{port}")
    print(f"  Connect with: http://{host}:{port}/sse")
    
    try:
        uvicorn.run(app, host=host, port=port, log_level="warning")
    finally:
        # Display loop is stopped by lifespan context manager
        # Only stop here if lifespan didn't run (shouldn't happen, but be safe)
        try:
            stop_display_loop()
        except Exception:
            pass  # Don't crash on shutdown


def main():
    """Entry point."""
    import os

    parser = argparse.ArgumentParser(description="Anima MCP Server")
    parser.add_argument("--sse", action="store_true", help="Run SSE server (network)")
    parser.add_argument("--host", default="0.0.0.0", help="SSE host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8765, help="SSE port (default: 8765)")
    args = parser.parse_args()

    db_path = os.environ.get("ANIMA_DB", "anima.db")
    anima_id = os.environ.get("ANIMA_ID")

    wake(db_path, anima_id)

    try:
        if args.sse:
            run_sse_server(args.host, args.port)
        else:
            asyncio.run(run_stdio_server())
    except KeyboardInterrupt:
        try:
            print("\nInterrupted by user", file=sys.stderr, flush=True)
        except (ValueError, OSError):
            pass
    except Exception as e:
        try:
            print(f"[Server] Fatal error: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc(file=sys.stderr)
        except (ValueError, OSError):
            pass
    finally:
        try:
            sleep()
        except Exception:
            pass  # Don't crash on shutdown


if __name__ == "__main__":
    main()
