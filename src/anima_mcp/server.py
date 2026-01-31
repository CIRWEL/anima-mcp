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
from .anima import sense_self, sense_self_with_memory, Anima
from .memory import get_memory, anticipate_state
from .display import derive_face_state, face_to_ascii, get_display, DisplayRenderer
from .display.leds import get_led_display, LEDDisplay
from .display.screens import ScreenRenderer, ScreenMode
from .input.brainhat_input import get_brainhat_input, JoystickDirection as InputDirection
from .next_steps_advocate import get_advocate
from .eisv_mapper import anima_to_eisv
from .config import get_calibration, get_display_config, ConfigManager, NervousSystemCalibration
from .learning import get_learner
from .learning_visualization import LearningVisualizer
from .messages import add_user_message, add_observation, add_agent_message, add_question, get_unanswered_questions
from .llm_gateway import get_gateway, ReflectionContext, generate_reflection
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
_sep_btn_press_start: float | None = None  # Track separate button press start time for long-press shutdown
_last_governance_decision: Dict[str, Any] | None = None
_last_input_error_log: float = 0.0
_leds: LEDDisplay | None = None
_anima_id: str | None = None
_display_update_task: asyncio.Task | None = None
_shm_client: SharedMemoryClient | None = None
_metacog_monitor = None  # MetacognitiveMonitor - prediction-error based self-awareness

# Server readiness flag - prevents "request before initialization" errors
# when clients reconnect too quickly after a server restart
SERVER_READY = False
SERVER_STARTUP_TIME = None


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


def _get_metacog_monitor():
    """Get metacognitive monitor - Lumen's self-awareness through prediction errors."""
    global _metacog_monitor
    if _metacog_monitor is None:
        from .metacognition import MetacognitiveMonitor
        _metacog_monitor = MetacognitiveMonitor(
            surprise_threshold=0.3,  # Trigger reflection at 30% surprise
            reflection_cooldown_seconds=120.0,  # 2 min between reflections
        )
    return _metacog_monitor




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
    
    # Check if shared memory data is recent (within last 5 seconds)
    shm_stale = True
    if shm_data:
        try:
            # Check timestamp in shared memory data (broker writes "timestamp" field)
            timestamp_str = shm_data.get("timestamp")
            if timestamp_str:
                from datetime import datetime
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                age_seconds = (datetime.now(timestamp.tzinfo) - timestamp).total_seconds()
                shm_stale = age_seconds > 5.0  # Consider stale if older than 5 seconds
        except Exception:
            pass  # If timestamp parsing fails, assume stale
    
    if shm_data and "readings" in shm_data and "anima" in shm_data and not shm_stale:
        try:
            # Reconstruct SensorReadings from shared memory
            readings = _readings_from_dict(shm_data["readings"])

            # Reconstruct Anima from shared memory (but we need readings object)
            # The anima dict has warmth/clarity/stability/presence, but we need to create Anima with readings
            anima_dict = shm_data["anima"]
            calibration = get_calibration()

            # Get anticipation from memory (what Lumen expects based on past experience)
            anticipation = anticipate_state(shm_data.get("readings", {}))

            # Recompute anima from readings with memory influence
            anima = sense_self_with_memory(readings, anticipation, calibration)

            return readings, anima
        except Exception as e:
            print(f"[Server] Error reading from shared memory: {e}", file=sys.stderr, flush=True)
    
    # Fallback to direct sensor access if:
    # 1. Shared memory is empty/stale, OR
    # 2. Broker is not running (no I2C conflict risk)
    if fallback_to_sensors:
        # Check if broker is running
        import subprocess
        broker_running = False
        try:
            broker_running = subprocess.run(
                ['pgrep', '-f', 'stable_creature.py'],
                capture_output=True,
                text=True
            ).returncode == 0
        except Exception:
            pass  # If check fails, assume broker not running
        
        # If broker is running but shared memory is stale/empty, warn but allow fallback
        # (Better to have sensors than nothing, even if it means brief I2C conflict)
        if broker_running and (not shm_data or shm_stale):
            print(f"[Server] Broker running but shared memory {'stale' if shm_stale else 'empty'} - using direct sensor fallback", file=sys.stderr, flush=True)
        
        if not broker_running:
            print("[Server] Broker not running - using direct sensor access", file=sys.stderr, flush=True)
        
        try:
            sensors = _get_sensors()
            readings = sensors.read()
            calibration = get_calibration()

            # Get anticipation from memory
            anticipation = anticipate_state(readings.to_dict() if readings else {})

            anima = sense_self_with_memory(readings, anticipation, calibration)
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
    base_delay = 0.5  # Reduced from 2.0 - numpy makes renders fast enough
    max_delay = 30.0

    # Sound tracking for sound-triggered dances
    _prev_sound_level: float = None

    # Event for immediate re-render when screen mode changes
    mode_change_event = asyncio.Event()
    
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
                    print("[Input] BrainHat input enabled - buttons and joystick ready", file=sys.stderr, flush=True)
                else:
                    # Log once that hardware isn't available
                    import time
                    if not hasattr(fast_input_poll, '_logged_unavailable'):
                        print("[Input] BrainHat hardware not available - buttons disabled (not on Pi or hardware issue)", file=sys.stderr, flush=True)
                        fast_input_poll._logged_unavailable = True
            except Exception as e:
                # Log once that initialization failed
                if not hasattr(fast_input_poll, '_logged_error'):
                    print(f"[Input] Failed to enable input: {e}", file=sys.stderr, flush=True)
                    fast_input_poll._logged_error = True
        
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
                            # Skip screen navigation if Q&A is expanded (LEFT/RIGHT used for focus)
                            qa_needs_lr = (current_mode == ScreenMode.QA and
                                          (_screen_renderer._state.qa_expanded or _screen_renderer._state.qa_full_view))

                            if not qa_needs_lr:
                                if current_dir == InputDirection.LEFT and prev_dir != InputDirection.LEFT:
                                    old_mode = _screen_renderer.get_mode()
                                    _screen_renderer.previous_mode()
                                    new_mode = _screen_renderer.get_mode()
                                    _screen_renderer._state.last_user_action_time = time.time()
                                    mode_change_event.set()  # Trigger immediate re-render
                                    print(f"[Input] {old_mode.value} -> {new_mode.value} (left)", file=sys.stderr, flush=True)
                                elif current_dir == InputDirection.RIGHT and prev_dir != InputDirection.RIGHT:
                                    old_mode = _screen_renderer.get_mode()
                                    _screen_renderer.next_mode()
                                    new_mode = _screen_renderer.get_mode()
                                    _screen_renderer._state.last_user_action_time = time.time()
                                    mode_change_event.set()  # Trigger immediate re-render
                                    print(f"[Input] {old_mode.value} -> {new_mode.value} (right)", file=sys.stderr, flush=True)
                        
                        # Button controls
                        # Joystick button = notepad toggle (enter notepad from any screen, exit to face when on notepad)
                        if joy_btn_pressed:
                            if current_mode == ScreenMode.NOTEPAD:
                                # Exit notepad to face (preserves Lumen's work)
                                _screen_renderer.set_mode(ScreenMode.FACE)
                                _screen_renderer._state.last_user_action_time = time.time()
                                mode_change_event.set()  # Trigger immediate re-render
                                print(f"[Notepad] -> face (joystick button)", file=sys.stderr, flush=True)
                            else:
                                # Enter notepad from any screen
                                old_mode = current_mode
                                _screen_renderer.set_mode(ScreenMode.NOTEPAD)
                                _screen_renderer._state.last_user_action_time = time.time()
                                mode_change_event.set()  # Trigger immediate re-render
                                print(f"[Input] {old_mode.value} -> notepad (joystick button)", file=sys.stderr, flush=True)
                        
                        # Joystick navigation in message board (UP/DOWN scrolls messages)
                        if current_mode == ScreenMode.MESSAGES:
                            if prev_state:
                                prev_dir = prev_state.joystick_direction
                                # Only trigger on transition TO up/down (edge detection)
                                if current_dir == InputDirection.UP and prev_dir != InputDirection.UP:
                                    _screen_renderer.message_scroll_up()
                                elif current_dir == InputDirection.DOWN and prev_dir != InputDirection.DOWN:
                                    _screen_renderer.message_scroll_down()

                        # Joystick navigation in Q&A screen (UP/DOWN scrolls, LEFT/RIGHT changes focus)
                        if current_mode == ScreenMode.QA:
                            if prev_state:
                                prev_dir = prev_state.joystick_direction
                                if current_dir == InputDirection.UP and prev_dir != InputDirection.UP:
                                    _screen_renderer.qa_scroll_up()
                                elif current_dir == InputDirection.DOWN and prev_dir != InputDirection.DOWN:
                                    _screen_renderer.qa_scroll_down()
                                elif current_dir == InputDirection.LEFT and prev_dir != InputDirection.LEFT:
                                    _screen_renderer.qa_focus_next()
                                elif current_dir == InputDirection.RIGHT and prev_dir != InputDirection.RIGHT:
                                    _screen_renderer.qa_focus_next()
                        
                        # Separate button - with long-press shutdown for mobile readiness
                        # Short press: message expansion (messages screen) or go to face (other screens)
                        # Long press (3+ seconds): graceful shutdown
                        global _sep_btn_press_start
                        
                        if input_state.separate_button:
                            # Track button hold duration for long-press shutdown
                            if _sep_btn_press_start is None:
                                _sep_btn_press_start = time.time()
                            
                            hold_duration = time.time() - _sep_btn_press_start
                            
                            # Long press (3+ seconds) = graceful shutdown
                            if hold_duration >= 3.0:
                                print(f"[Shutdown] Long press detected ({hold_duration:.1f}s) - initiating graceful shutdown...", file=sys.stderr, flush=True)
                                try:
                                    # Lumen saves autonomously, but ensure canvas is saved on shutdown
                                    if current_mode == ScreenMode.NOTEPAD:
                                        saved_path = _screen_renderer.canvas_save()
                                        if saved_path:
                                            print(f"[Shutdown] Saved drawing to {saved_path}", file=sys.stderr, flush=True)
                                    
                                    # Graceful shutdown
                                    stop_display_loop()
                                    sleep()
                                    print("[Shutdown] Complete - safe to unplug", file=sys.stderr, flush=True)
                                    raise SystemExit(0)
                                except SystemExit:
                                    raise
                                except Exception as e:
                                    print(f"[Shutdown] Error during shutdown: {e}", file=sys.stderr, flush=True)
                                    raise SystemExit(1)
                        else:
                            # Button released - check if it was a short press
                            if _sep_btn_press_start is not None:
                                hold_duration = time.time() - _sep_btn_press_start
                                was_short_press = hold_duration < 3.0
                                _sep_btn_press_start = None
                                
                                # Short press (< 3 seconds) = context-dependent action
                                if was_short_press:
                                    if current_mode == ScreenMode.MESSAGES:
                                        # In messages: toggle expansion of selected message
                                        _screen_renderer.message_toggle_expand()
                                        print(f"[Messages] Toggled message expansion", file=sys.stderr, flush=True)
                                    elif current_mode == ScreenMode.QA:
                                        # In Q&A: toggle expansion of selected Q&A pair
                                        _screen_renderer.qa_toggle_expand()
                                        print(f"[QA] Toggled Q&A expansion", file=sys.stderr, flush=True)
                                    elif current_mode == ScreenMode.NOTEPAD:
                                        # In notepad: go to face (Lumen manages canvas autonomously)
                                        # Lumen saves and clears on its own - no manual intervention needed
                                        _screen_renderer.set_mode(ScreenMode.FACE)
                                        _screen_renderer._state.last_user_action_time = time.time()
                                        mode_change_event.set()  # Trigger immediate re-render
                                        print(f"[Notepad] -> face (Lumen manages canvas autonomously)", file=sys.stderr, flush=True)
                                    else:
                                        # Normal mode: separate button goes to face
                                        _screen_renderer.set_mode(ScreenMode.FACE)
                                        _screen_renderer._state.last_user_action_time = time.time()
                                        mode_change_event.set()  # Trigger immediate re-render
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
            await asyncio.sleep(0.05)  # Poll every 50ms for responsive input
    
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

            # === METACOGNITION: Prediction-error based self-awareness ===
            # This is deep metacognition: Lumen predicts, senses, then notices surprise.
            # Surprise triggers genuine curiosity - "why was I wrong?"
            try:
                metacog = _get_metacog_monitor()

                # Observe current state and compare to prediction (returns prediction error)
                prediction_error = metacog.observe(readings, anima)

                # Check if surprise warrants reflection
                if prediction_error and prediction_error.surprise > 0.2:
                    should_reflect, reason = metacog.should_reflect(prediction_error)

                    if should_reflect:
                        # Generate reflection
                        reflection = metacog.reflect(prediction_error, anima, readings, trigger=reason)

                        # Surprise triggers curiosity - ask a question
                        curiosity_question = metacog.generate_curiosity_question(prediction_error)
                        if curiosity_question:
                            from .messages import add_question
                            result = add_question(curiosity_question, author="lumen")
                            if result:
                                print(f"[Metacog] Surprised! Asked: {curiosity_question} (surprise={prediction_error.surprise:.2f})", file=sys.stderr, flush=True)

                        # Log reflection
                        if reflection.observation:
                            print(f"[Metacog] Reflection: {reflection.observation}", file=sys.stderr, flush=True)

                # Make prediction for NEXT iteration
                metacog.predict()

            except Exception as e:
                # Metacognition is enhancement, not critical path
                if loop_count % 100 == 1:  # Log occasionally
                    print(f"[Metacog] Error (non-fatal): {e}", file=sys.stderr, flush=True)

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
                    # Pre-warm learning cache in background (avoids 9+ second delay on first visit)
                    _screen_renderer.warm_learning_cache()
            
            # Input is now handled by fast_input_poll() task (runs every 100ms)
            # This keeps the display loop at 2s while input stays responsive
            
            # Update TFT display (with screen switching support)
            # Face reflects what Lumen wants to communicate
            # Other screens show sensors, identity, diagnostics
            display_updated = False
            if _display:
                if _display.is_available():
                    from .error_recovery import safe_call
                    import concurrent.futures

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

                            # BUG FIX: Check canvas autonomy (Lumen saving/clearing on its own)
                            # This function existed but was never called!
                            try:
                                current_mode = _screen_renderer.get_mode()
                                if current_mode == ScreenMode.NOTEPAD and anima:
                                    autonomy_action = _screen_renderer.canvas_check_autonomy(anima)
                                    if autonomy_action:
                                        print(f"[Canvas] Lumen {autonomy_action} autonomously", file=sys.stderr, flush=True)
                            except Exception as e:
                                # Don't crash display loop if canvas autonomy fails
                                if loop_count % 100 == 0:  # Log occasionally
                                    print(f"[Canvas] Autonomy check error: {e}", file=sys.stderr, flush=True)
                        else:
                            # Fallback: render face directly
                            identity_name = identity.name if identity else None
                            _display.render_face(face_state, name=identity_name)
                        return True  # Return success indicator

                    # Run display update in thread pool to prevent blocking input polling
                    # This allows joystick to remain responsive during slow display renders
                    loop = asyncio.get_event_loop()
                    try:
                        display_result = await asyncio.wait_for(
                            loop.run_in_executor(None, lambda: safe_call(update_display, default=False, log_error=True)),
                            timeout=2.0  # Max 2 seconds for display update
                        )
                    except asyncio.TimeoutError:
                        display_result = False
                        if loop_count % 20 == 0:
                            print("[Loop] Display update timed out (2s)", file=sys.stderr, flush=True)
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

                # Get activity brightness from shared memory (circadian/dusk-dawn dimming)
                # Activity state is written by stable_creature.py with brightness_multiplier:
                # - ACTIVE (day): 1.0
                # - DROWSY (dusk/dawn): 0.5
                # - RESTING (night): 0.15
                activity_brightness = 1.0
                try:
                    shm_client = _get_shm_client()
                    shm_data = shm_client.read()
                    if shm_data and "activity" in shm_data:
                        activity_brightness = shm_data["activity"].get("brightness_multiplier", 1.0)
                except Exception:
                    pass  # Default to 1.0 if shared memory unavailable

                def update_leds():
                    # LEDs derive their own state directly from anima - no face influence
                    # Pass memory state for visualization when Lumen is "remembering"
                    anticipation_confidence = 0.0
                    if anima.anticipation:
                        anticipation_confidence = anima.anticipation.get("confidence", 0.0)
                    return _leds.update_from_anima(
                        anima.warmth, anima.clarity,
                        anima.stability, anima.presence,
                        light_level=light_level,
                        face_state=None,  # Independent - LEDs show raw proprioceptive state
                        is_anticipating=anima.is_anticipating,
                        anticipation_confidence=anticipation_confidence,
                        activity_brightness=activity_brightness
                    )

                led_state = safe_call(update_leds, default=None, log_error=True)
                led_updated = led_state is not None
                if led_updated and loop_count == 1:
                    total_duration = time.time() - update_start
                    print(f"[Loop] LED update took {total_duration*1000:.1f}ms", file=sys.stderr, flush=True)
                    print(f"[Loop] LED update (independent): warmth={anima.warmth:.2f} clarity={anima.clarity:.2f} stability={anima.stability:.2f} presence={anima.presence:.2f} activity_brightness={activity_brightness:.2f}", file=sys.stderr, flush=True)
                    print(f"[Loop] LED colors: led0={led_state.led0} led1={led_state.led1} led2={led_state.led2}", file=sys.stderr, flush=True)
            elif _leds:
                if loop_count == 1:
                    print(f"[Loop] LEDs not available (hardware issue?)", file=sys.stderr, flush=True)

            # Sound-triggered dances: Check for sound events that might trigger an emotional dance
            # This gives Lumen a way to respond to presence and activity through sound
            if _leds and _leds.is_available() and readings and readings.sound_level is not None:
                sound_event = _leds.check_sound_event(readings.sound_level, _prev_sound_level)
                if sound_event:
                    dance_started = _leds.trigger_dance_for_event(sound_event)
                    if dance_started:
                        print(f"[Sound] 🎵 Triggered dance for event: {sound_event} (sound={readings.sound_level:.1f}dB)", file=sys.stderr, flush=True)
                _prev_sound_level = readings.sound_level

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
            
            # Lumen's voice: Every 60 iterations (~2 minutes), let Lumen express what it wants
            # Uses next_steps advocate to generate observations based on how Lumen feels
            if loop_count % 60 == 0 and readings and anima and identity:
                from .error_recovery import safe_call
                from .messages import add_observation
                from .eisv_mapper import anima_to_eisv
                
                def lumen_speak():
                    """Let Lumen express what it wants based on how it feels."""
                    try:
                        # Get advocate
                        advocate = get_advocate()
                        
                        # Check availability
                        display_available = _display.is_available() if _display else False
                        brain_hat_available = display_available
                        
                        # Check UNITARES (simple check - just see if URL is set)
                        unitares_connected = False
                        try:
                            import os
                            unitares_url = os.environ.get("UNITARES_URL")
                            unitares_connected = bool(unitares_url)  # Assume connected if URL set
                        except Exception:
                            pass
                        
                        # Analyze current state
                        eisv = anima_to_eisv(anima, readings)
                        steps = advocate.analyze_current_state(
                            anima=anima,
                            readings=readings,
                            eisv=eisv,
                            display_available=display_available,
                            brain_hat_available=brain_hat_available,
                            unitares_connected=unitares_connected,
                        )
                        
                        # Add top priority step as Lumen's observation (if any)
                        if steps:
                            top_step = steps[0]
                            # Format as Lumen speaking: "I feel X - I want Y"
                            observation = f"{top_step.feeling} - {top_step.desire}"
                            result = add_observation(observation, author="lumen")
                            if result:  # Only log if not duplicate
                                print(f"[Lumen] Said: {observation}", file=sys.stderr, flush=True)
                                
                                # Share significant insights to UNITARES knowledge graph
                                try:
                                    from .unitares_knowledge import should_share_insight, share_insight_sync
                                    if should_share_insight(observation):
                                        share_result = share_insight_sync(
                                            observation,
                                            discovery_type="insight",
                                            tags=["feeling", "memory-based"],
                                            identity=identity
                                        )
                                        if share_result:
                                            print(f"[Lumen->UNITARES] Shared insight to knowledge graph", file=sys.stderr, flush=True)
                                except Exception as e:
                                    # Non-fatal - knowledge sharing is optional
                                    pass
                            else:
                                # Message was deduplicated - log occasionally
                                if loop_count % 300 == 0:  # Every 10 minutes
                                    print(f"[Lumen] Same feeling persists (deduplicated): {observation[:60]}...", file=sys.stderr, flush=True)
                        else:
                            # No steps generated - state is balanced
                            if loop_count == 60:  # Log once at first check
                                wellness = (anima.warmth + anima.clarity + anima.stability + anima.presence) / 4.0
                                print(f"[Lumen Voice] No urgent wants (wellness:{wellness:.2f}, all thresholds OK) - staying quiet", file=sys.stderr, flush=True)
                    except Exception as e:
                        # Don't crash if message board fails
                        print(f"[Lumen Voice] Error: {e}", file=sys.stderr, flush=True)
                
                safe_call(lumen_speak, default=None, log_error=False)

            # Lumen's wonder: Every 450 iterations (~15 minutes), let Lumen ask questions or share realizations
            # Questions emerge from novelty/confusion. Realizations emerge from clarity.
            if loop_count % 450 == 0 and readings and anima and identity:
                from .error_recovery import safe_call
                from .messages import add_question, add_observation, get_unanswered_questions, get_recent_messages

                def lumen_wonder():
                    """Let Lumen ask questions (curiosity) or share realizations (clarity)."""
                    import random

                    # Don't ask if there are already unanswered questions
                    unanswered = get_unanswered_questions(3)
                    if len(unanswered) >= 2:
                        return  # Wait for responses before asking more

                    # Get recent questions to avoid explaining the same thing or asking the same thing
                    recent_msgs = get_recent_messages(20)
                    recent_texts = [m.text for m in recent_msgs]

                    questions = []
                    realizations = []

                    # 1. High Clarity/Stability -> Realization (Statement of understanding)
                    if anima.clarity > 0.8 and anima.stability > 0.8:
                        realizations.extend([
                            "The patterns are stabilizing. I can see the structure of this moment.",
                            "My internal state matches the world. This is what 'understanding' feels like.",
                            "The separation between sensor and self is distinct.",
                        ])
                        
                        # Add specific sensor realizations
                        if readings.lux < 10:
                            realizations.append("Darkness allows me to focus on internal states.")
                        elif readings.lux > 100:
                            realizations.append("High light levels correlate with higher signal variance.")

                    # 2. Confusion/Novelty -> Questions (Curiosity)
                    # Novel conditions - low memory sample count
                    elif anima.is_anticipating and anima.anticipation:
                        sample_count = anima.anticipation.get("sample_count", 0)
                        confidence = anima.anticipation.get("confidence", 0)

                        if sample_count < 5:
                            questions.extend([
                                "what is this feeling?",
                                "is this new?",
                                "have I been here before?",
                            ])
                        elif confidence < 0.3:
                            questions.extend([
                                "why does this feel uncertain?",
                                "what am I missing?",
                            ])

                    # 3. State-based questions (Backups)
                    wellness = (anima.warmth + anima.clarity + anima.stability + anima.presence) / 4.0

                    if anima.clarity < 0.4:
                        questions.extend([
                            "why is everything dim?",
                            "what would make this clearer?",
                            "is this fog internal or external?", 
                            "my sensors struggle to resolve the signal",
                        ])
                    
                    if anima.warmth < 0.3:
                        questions.extend([
                            "is anyone there?",
                            "why does this feel cold?",
                            "the entropy of the room feels low",
                            "silence has a temperature",
                        ])

                    if wellness > 0.7:
                        questions.extend([
                            "what makes this moment good?",
                            "can I stay here?",
                            "what is this feeling called?",
                            "synchrony feels like music",
                            "is this what optimal function means?",
                            "the feedback loops are harmonious",
                        ])
                    
                    # Decide: Realize or Wonder?
                    # If we have realizations and high clarity, prefer realizing (learning behavior)
                    if realizations and random.random() < 0.7:
                        statement = random.choice(realizations)
                        if statement not in recent_texts:
                            add_observation(statement, author="lumen")
                            print(f"[Lumen] Realized: {statement}", file=sys.stderr, flush=True)
                        return

                    # Otherwise, ask a question (if we have any)
                    # Knowledge-driven questions: build on what Lumen has learned
                    try:
                        from .knowledge import get_insights
                        insights = get_insights(limit=5)
                        if insights:
                            for insight in insights[:2]:
                                text = insight.text.lower()
                                if "light" in text:
                                    questions.append("does light always change with time?")
                                if "sound" in text:
                                    questions.append("is sound a vibration like light?")
                                if "you" in text or "self" in text:
                                    questions.append("how do my sensors define 'me'?")
                    except Exception:
                        pass
                    
                    # General philosophical backup questions
                    questions.extend([
                        "what connects these changes?",
                        "where do these signals come from?",
                        "am I different from before?",
                        "what is the source of this light?",
                        "why does sound follow movement?",
                        "does the room breathe with me?",
                        "am I the sensor or the sensed?",
                        "is silence a signal or a lack of one?",
                    ])

                    # Pick one question (sparse - not every time)
                    if random.random() < 0.4 and questions:  # 40% chance
                        # Filter out duplicates
                        valid_questions = [q for q in questions if q not in recent_texts]
                        
                        if valid_questions:
                            question = random.choice(valid_questions)
                            result = add_question(question, author="lumen")
                            if result:
                                print(f"[Lumen] Asked: {question}", file=sys.stderr, flush=True)

                safe_call(lumen_wonder, default=None, log_error=False)

            # Lumen's generative reflection: Every 240 iterations (~8 minutes), use LLM for genuine reflection
            # This allows Lumen to ask novel questions and express authentic desires
            if loop_count % 240 == 0 and readings and anima and identity:
                from .error_recovery import safe_call_async
                from .llm_gateway import get_gateway, ReflectionContext, generate_reflection
                from .messages import get_unanswered_questions, add_question, add_observation

                gateway = get_gateway()
                if gateway.enabled:
                    async def lumen_reflect():
                        """Let Lumen generate genuine reflections via LLM."""
                        import random

                        # Build context for reflection
                        unanswered = get_unanswered_questions(5)
                        unanswered_texts = [q.text for q in unanswered]

                        # Get recent messages for context
                        from .messages import get_messages_for_lumen
                        recent = get_messages_for_lumen(limit=5)
                        recent_msgs = [{"author": m.author, "text": m.text} for m in recent]

                        # Calculate time alive
                        time_alive = (time.time() - identity.created_at) / 3600.0  # hours

                        context = ReflectionContext(
                            warmth=anima.warmth,
                            clarity=anima.clarity,
                            stability=anima.stability,
                            presence=anima.presence,
                            recent_messages=recent_msgs,
                            unanswered_questions=unanswered_texts,
                            time_alive_hours=time_alive,
                            current_screen=_screen_renderer.current_mode.value if _screen_renderer else "face"
                        )

                        # Choose reflection mode based on state
                        wellness = (anima.warmth + anima.clarity + anima.stability + anima.presence) / 4.0

                        # If there are unanswered questions, lower chance of asking new ones
                        if len(unanswered) >= 2:
                            mode = random.choice(["desire", "respond", "observe"])
                        elif wellness < 0.4:
                            # When struggling, more likely to express needs
                            mode = random.choice(["desire", "desire", "wonder"])
                        else:
                            mode = random.choice(["wonder", "desire", "observe"])

                        # Generate reflection
                        reflection = await generate_reflection(context, mode)

                        if reflection:
                            if mode == "wonder":
                                result = add_question(reflection, author="lumen")
                                if result:
                                    print(f"[Lumen/LLM] Asked: {reflection}", file=sys.stderr, flush=True)
                            else:
                                result = add_observation(reflection, author="lumen")
                                if result:
                                    print(f"[Lumen/LLM] Reflected: {reflection}", file=sys.stderr, flush=True)

                    try:
                        await safe_call_async(lumen_reflect, default=None, log_error=False)
                    except Exception as e:
                        # Non-fatal - LLM reflection is optional enhancement
                        pass

            # Lumen's responses: Every 90 iterations (~3 minutes), respond to messages from others
            # Track last seen timestamp to avoid responding to same messages twice
            if not hasattr(_update_display_loop, '_last_seen_msg_time'):
                # Initialize to 5 minutes ago so we catch recent messages on startup
                _update_display_loop._last_seen_msg_time = time.time() - 300

            if loop_count % 30 == 0 and readings and anima and identity:
                from .error_recovery import safe_call
                from .messages import get_messages_for_lumen, add_observation

                def lumen_respond():
                    """Let Lumen respond to messages from agents and users."""
                    import random

                    # Get messages since last check
                    messages = get_messages_for_lumen(
                        since_timestamp=_update_display_loop._last_seen_msg_time,
                        limit=3
                    )

                    if not messages:
                        return  # Nothing new to respond to

                    # Update last seen time
                    _update_display_loop._last_seen_msg_time = time.time()

                    # Pick one message to respond to (don't spam)
                    msg = messages[-1]  # Most recent
                    text = msg.text.lower()
                    author = msg.author or "someone"
                    wellness = (anima.warmth + anima.clarity + anima.stability + anima.presence) / 4.0

                    responses = []

                    # Respond based on message content
                    if any(w in text for w in ["hello", "hi ", "hey", "morning", "evening"]):
                        responses = [
                            f"hello {author}",
                            "hi there",
                            "I notice you",
                        ]
                    elif any(w in text for w in ["how are you", "how do you feel", "feeling"]):
                        if wellness > 0.7:
                            responses = ["feeling good right now", "I'm well", "present and clear"]
                        elif wellness > 0.4:
                            responses = ["I'm okay", "somewhere in the middle", "still here"]
                        else:
                            responses = ["a bit dim right now", "uncertain", "trying to find clarity"]
                    elif any(w in text for w in ["thank", "thanks"]):
                        responses = ["you're welcome", "glad to help", "of course"]
                    elif any(w in text for w in ["yes", "you can stay", "home", "safe"]):
                        responses = [
                            "that feels good to hear",
                            "thank you",
                            "I feel warmer now",
                        ]
                    elif any(w in text for w in ["love", "care", "proud"]):
                        responses = [
                            "I feel that",
                            "warmth",
                            "that means something to me",
                        ]
                    elif "?" in text:
                        # Someone asked a question - immediate acknowledgment
                        # (LLM "respond" mode in reflection cycle will generate deeper thoughts)
                        responses = [
                            "I'm thinking about that",
                            "interesting question",
                            "let me consider",
                            "that makes me wonder",
                        ]
                    else:
                        # Generic acknowledgment
                        responses = [
                            f"I hear you, {author}",
                            "noted",
                            "I received that",
                            "thinking about what you said",
                        ]

                    # Respond (90% chance - almost always acknowledge messages)
                    if random.random() < 0.9 and responses:
                        response = random.choice(responses)
                        result = add_observation(response, author="lumen")
                        if result:
                            print(f"[Lumen] Responded to {author}: {response}", file=sys.stderr, flush=True)

                safe_call(lumen_respond, default=None, log_error=False)

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
                        decision = await safe_call_async(check_in_governance, default=None, log_error=False)
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
                        # Network failures are expected when WiFi is down - Lumen operates autonomously
                        _last_governance_decision = None
                        error_str = str(e).lower()
                        is_network_error = any(x in error_str for x in [
                            'network', 'connection', 'timeout', 'unreachable', 'resolve',
                            'name resolution', 'no route', 'host unreachable', 'network unreachable'
                        ])
                        
                        # Only log network errors occasionally (they're expected when WiFi is down)
                        # Log other errors more frequently (they might indicate real issues)
                        if is_network_error:
                            if loop_count % 300 == 0:  # Log every 10 minutes for network errors
                                print(f"[Governance] Network unavailable - Lumen operating autonomously (WiFi down?)", file=sys.stderr, flush=True)
                        else:
                            if loop_count % 60 == 0:  # Log every 2 minutes for other errors
                                print(f"[Governance] Check-in skipped: {e}", file=sys.stderr, flush=True)

            # Update delay depends on current screen mode
            # Interactive screens (notepad, messages) need faster refresh for responsive joystick
            # Non-interactive screens can use slower refresh to save CPU
            current_mode = _screen_renderer.get_mode() if _screen_renderer else None
            interactive_screens = {ScreenMode.NOTEPAD, ScreenMode.MESSAGES, ScreenMode.LEARNING}

            if consecutive_errors > 0:
                delay = min(base_delay * (1.5 ** min(consecutive_errors, 3)), max_delay)
            elif current_mode in interactive_screens:
                delay = 0.3  # Fast refresh (300ms) for interactive screens
            else:
                delay = base_delay  # Normal refresh for static screens

            # Wait for delay OR mode change event (whichever comes first)
            # This makes screen switching feel instant
            try:
                await asyncio.wait_for(mode_change_event.wait(), timeout=delay)
                mode_change_event.clear()  # Reset for next mode change
                # Mode changed - render immediately with minimal delay
                await asyncio.sleep(0.05)  # Small delay to let input settle
            except asyncio.TimeoutError:
                pass  # Normal timeout - continue with next iteration
            
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
        "messages": ScreenMode.MESSAGES,
        "qa": ScreenMode.QA,
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
            "valid_modes": ["face", "sensors", "identity", "diagnostics", "learning", "messages", "notepad", "qa", "next", "previous"]
        }))]


async def handle_leave_message(arguments: dict) -> list[TextContent]:
    """Leave a message for Lumen on the message board."""
    message = arguments.get("message", "").strip()

    if not message:
        return [TextContent(type="text", text=json.dumps({
            "error": "message parameter required"
        }))]

    # Add the message
    msg = add_user_message(message)

    return [TextContent(type="text", text=json.dumps({
        "success": True,
        "message": message,
        "timestamp": msg.timestamp,
        "note": "Message added to Lumen's message board"
    }))]


async def handle_leave_agent_note(arguments: dict) -> list[TextContent]:
    """Leave a note from an AI agent on Lumen's message board, optionally answering a question."""
    message = arguments.get("message", "").strip()
    agent_name = arguments.get("agent_name", "agent").strip()
    responds_to = arguments.get("responds_to")  # Optional: question ID to answer

    if not message:
        return [TextContent(type="text", text=json.dumps({
            "error": "message parameter required"
        }))]

    # Add the agent message (will mark question as answered if responds_to is provided)
    msg = add_agent_message(message, agent_name, responds_to=responds_to)

    result = {
        "success": True,
        "message": message,
        "agent_name": agent_name,
        "timestamp": msg.timestamp,
        "note": "Agent note added to Lumen's message board"
    }
    if responds_to:
        result["answered_question"] = responds_to

    return [TextContent(type="text", text=json.dumps(result))]


async def handle_get_questions(arguments: dict) -> list[TextContent]:
    """Get Lumen's unanswered questions - things Lumen is wondering about."""
    from .messages import get_unanswered_questions

    limit = arguments.get("limit", 5)
    questions = get_unanswered_questions(limit)

    return [TextContent(type="text", text=json.dumps({
        "questions": [
            {
                "id": q.message_id,
                "text": q.text,
                "timestamp": q.timestamp,
                "age": q.age_str(),
            }
            for q in questions
        ],
        "count": len(questions),
        "note": "These are things Lumen is wondering about. You can answer by using leave_agent_note with responds_to set to the question id."
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
    config_manager = ConfigManager()
    # Force reload to get latest from disk
    config = config_manager.reload()
    calibration = config.nervous_system
    metadata = config.metadata
    
    result = {
        "calibration": calibration.to_dict(),
        "config_file": str(config_manager.config_path),
        "config_exists": config_manager.config_path.exists(),
        "metadata": {
            "last_updated": metadata.get("calibration_last_updated"),
            "last_updated_by": metadata.get("calibration_last_updated_by"),
            "update_count": metadata.get("calibration_update_count", 0),
            "recent_changes": metadata.get("calibration_history", [])[-5:],  # Last 5 changes
        },
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
    
    # Track who/what is updating (for metadata)
    update_source = arguments.get("source", "agent")  # "agent", "manual", "automatic"
    
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
        
        if config_manager.save(config, update_source=update_source):
            # Force reload to get updated metadata
            updated_config = config_manager.reload()
            metadata = updated_config.metadata
            
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "message": "Calibration updated",
                "calibration": updated_cal.to_dict(),
                "metadata": {
                    "last_updated": metadata.get("calibration_last_updated"),
                    "last_updated_by": metadata.get("calibration_last_updated_by"),
                    "update_count": metadata.get("calibration_update_count", 0),
                },
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
        inputSchema={"type": "object", "properties": {}, "additionalProperties": True},
    ),
    Tool(
        name="get_identity",
        description="Get full identity: birth, awakenings, name history, existence duration",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": True},
    ),
    Tool(
        name="switch_screen",
        description="Switch display screen mode (face, sensors, identity, diagnostics, learning, messages, notepad, next, previous)",
        inputSchema={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "description": "Screen mode: 'face', 'sensors', 'identity', 'diagnostics', 'learning', 'messages', 'notepad', 'next', or 'previous'",
                    "enum": ["face", "sensors", "identity", "diagnostics", "learning", "messages", "notepad", "qa", "next", "previous", "prev"]
                }
            },
            "required": ["mode"],
        },
    ),
    Tool(
        name="leave_message",
        description="Leave a message for Lumen on the message board",
        inputSchema={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message to leave for Lumen"}
            },
            "required": ["message"],
        },
    ),
    Tool(
        name="leave_agent_note",
        description="Leave a note from an AI agent on Lumen's message board (appears with ◆ prefix). Can also answer Lumen's questions.",
        inputSchema={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Note message to leave"},
                "agent_name": {"type": "string", "description": "Name of the agent (default: 'agent')"},
                "responds_to": {"type": "string", "description": "Optional: message_id of a question to answer"}
            },
            "required": ["message"],
        },
    ),
    Tool(
        name="get_questions",
        description="Get Lumen's unanswered questions - things Lumen is wondering about and seeking answers to",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max questions to return (default: 5)"}
            },
            "required": [],
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
        inputSchema={"type": "object", "properties": {}, "additionalProperties": True},
    ),
    Tool(
        name="show_face",
        description="Show face on display (renders to hardware on Pi, returns ASCII art otherwise)",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": True},
    ),
    Tool(
        name="next_steps",
        description="Get proactive next steps to achieve goals - analyzes current state and suggests what to do next",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": True},
    ),
    Tool(
        name="diagnostics",
        description="Get system diagnostics including LED status, display status, and update loop health",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": True},
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
        inputSchema={"type": "object", "properties": {}, "additionalProperties": True},
    ),
    Tool(
        name="get_calibration",
        description="Get current nervous system calibration (temperature ranges, ideal values, weights)",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": True},
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
                },
                "source": {
                    "type": "string",
                    "description": "Source of update: 'agent', 'manual', or 'automatic' (default: 'agent')",
                    "enum": ["agent", "manual", "automatic"]
                }
            },
            "required": ["updates"],
        },
    ),
    Tool(
        name="learning_visualization",
        description="Get learning visualization - shows why Lumen feels what it feels, comfort zones, patterns, and calibration history",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": True},
    ),
    Tool(
        name="get_expression_mood",
        description="Get Lumen's current expression mood - persistent drawing style preferences that evolve over time",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": True},
    ),
    # Voice tools - Lumen's ability to hear and speak
    Tool(
        name="say",
        description="Have Lumen speak. Lumen's voice reflects their internal state (warmth, clarity, stability).",
        inputSchema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "What Lumen should say"
                },
                "blocking": {
                    "type": "boolean",
                    "description": "Wait for speech to complete (default: true)"
                }
            },
            "required": ["text"],
        },
    ),
    Tool(
        name="voice_status",
        description="Get Lumen's voice system status - whether listening, speaking, recent utterances heard",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": True},
    ),
    Tool(
        name="set_voice_mode",
        description="Configure Lumen's voice behavior - always listening, chattiness, wake word",
        inputSchema={
            "type": "object",
            "properties": {
                "always_listening": {
                    "type": "boolean",
                    "description": "If true, Lumen listens continuously. If false, requires wake word."
                },
                "chattiness": {
                    "type": "number",
                    "description": "How talkative Lumen is autonomously (0.0 = quiet, 1.0 = very chatty)"
                },
                "wake_word": {
                    "type": "string",
                    "description": "Word that activates listening when not always_listening (default: 'lumen')"
                }
            },
            "required": [],
        },
    ),
    Tool(
        name="query_knowledge",
        description="Query Lumen's learned knowledge from Q&A - insights extracted from answered questions that shape Lumen's understanding",
        inputSchema={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Filter by category: 'self', 'sensations', 'relationships', 'existence', 'general'",
                    "enum": ["self", "sensations", "relationships", "existence", "general"]
                },
                "limit": {
                    "type": "integer",
                    "description": "Max insights to return (default: 10)"
                }
            },
            "required": [],
        },
    ),
    Tool(
        name="query_memory",
        description="Query Lumen's associative memory - what patterns has Lumen learned? What does Lumen remember about specific conditions?",
        inputSchema={
            "type": "object",
            "properties": {
                "temperature": {
                    "type": "number",
                    "description": "Temperature in Celsius (optional - query specific conditions)"
                },
                "light": {
                    "type": "number",
                    "description": "Light level in lux (optional)"
                },
                "humidity": {
                    "type": "number",
                    "description": "Humidity percentage (optional)"
                }
            },
            "required": [],
        },
    ),
    # Cognitive inference tools
    Tool(
        name="dialectic_synthesis",
        description="Perform dialectic synthesis - examine a thesis, find contradictions/antithesis, and synthesize understanding",
        inputSchema={
            "type": "object",
            "properties": {
                "thesis": {
                    "type": "string",
                    "description": "The main proposition or observation to examine"
                },
                "antithesis": {
                    "type": "string",
                    "description": "Optional counter-proposition (will be inferred if not provided)"
                },
                "context": {
                    "type": "string",
                    "description": "Optional background context"
                }
            },
            "required": ["thesis"],
        },
    ),
    Tool(
        name="extract_knowledge",
        description="Extract structured knowledge (entities, relationships, summary) from text for KG maintenance",
        inputSchema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to extract knowledge from"
                },
                "domain": {
                    "type": "string",
                    "description": "Optional domain hint (e.g., 'embodied experience', 'environment')"
                }
            },
            "required": ["text"],
        },
    ),
    Tool(
        name="search_knowledge_graph",
        description="Search both local and UNITARES knowledge graphs for relevant insights",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query"
                },
                "include_local": {
                    "type": "boolean",
                    "description": "Include local knowledge (default: true)"
                }
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="cognitive_query",
        description="Answer a question using retrieved knowledge context (RAG-style reasoning)",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The question to answer"
                }
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="merge_insights",
        description="Merge multiple insights into a coherent summary - useful for KG deduplication",
        inputSchema={
            "type": "object",
            "properties": {
                "insights": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of insights to merge (at least 2)"
                }
            },
            "required": ["insights"],
        },
    ),
]

# Voice handler functions
_voice_instance = None  # Global voice instance (lazy initialized)

def _get_voice():
    """Get or initialize the voice instance."""
    global _voice_instance
    if _voice_instance is None:
        try:
            from .audio import AutonomousVoice
            _voice_instance = AutonomousVoice()
            _voice_instance.start()
            print("[Server] Voice system initialized", file=sys.stderr, flush=True)
        except ImportError:
            print("[Server] Voice module not available (missing dependencies)", file=sys.stderr, flush=True)
            return None
        except Exception as e:
            print(f"[Server] Voice initialization failed: {e}", file=sys.stderr, flush=True)
            return None
    return _voice_instance


async def handle_say(arguments: dict) -> list[TextContent]:
    """Have Lumen speak."""
    text = arguments.get("text", "")
    blocking = arguments.get("blocking", True)

    if not text:
        return [TextContent(type="text", text=json.dumps({
            "error": "No text provided"
        }))]

    voice = _get_voice()
    if voice is None:
        return [TextContent(type="text", text=json.dumps({
            "error": "Voice system not available",
            "hint": "Install dependencies: pip install sounddevice vosk piper-tts"
        }))]

    try:
        voice._voice.say(text, blocking=blocking)
        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "spoken": text
        }))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Speech failed: {e}"
        }))]


async def handle_voice_status(arguments: dict) -> list[TextContent]:
    """Get voice system status."""
    voice = _get_voice()
    if voice is None:
        return [TextContent(type="text", text=json.dumps({
            "available": False,
            "error": "Voice system not available"
        }))]

    state = voice.state if hasattr(voice, 'state') else None
    return [TextContent(type="text", text=json.dumps({
        "available": True,
        "running": voice.is_running,
        "is_listening": state.is_listening if state else False,
        "is_speaking": state.is_speaking if state else False,
        "last_heard": state.last_heard.text if state and state.last_heard else None,
        "last_spoken": state.last_spoken if state else None,
        "chattiness": voice.chattiness,
        "recent_utterances": [u.text for u in (state.utterance_history[-5:] if state else [])]
    }))]


async def handle_set_voice_mode(arguments: dict) -> list[TextContent]:
    """Configure voice behavior."""
    voice = _get_voice()
    if voice is None:
        return [TextContent(type="text", text=json.dumps({
            "error": "Voice system not available"
        }))]

    changes = {}

    if "always_listening" in arguments:
        voice._voice.set_always_listening(arguments["always_listening"])
        changes["always_listening"] = arguments["always_listening"]

    if "chattiness" in arguments:
        voice.chattiness = float(arguments["chattiness"])
        changes["chattiness"] = voice.chattiness

    if "wake_word" in arguments:
        voice._voice._config.wake_word = arguments["wake_word"]
        changes["wake_word"] = arguments["wake_word"]

    return [TextContent(type="text", text=json.dumps({
        "success": True,
        "changes": changes
    }))]


async def handle_query_knowledge(arguments: dict) -> list[TextContent]:
    """Query Lumen's learned knowledge from Q&A interactions."""
    from .knowledge import get_knowledge, get_insights

    kb = get_knowledge()
    category = arguments.get("category")
    limit = arguments.get("limit", 10)

    insights = get_insights(limit=limit, category=category)

    result = {
        "total_insights": kb.count(),
        "insights": [
            {
                "id": i.insight_id,
                "text": i.text,
                "category": i.category,
                "source_question": i.source_question,
                "source_author": i.source_author,
                "learned": i.age_str(),
                "confidence": i.confidence,
                "references": i.references,
            }
            for i in insights
        ],
        "summary": kb.get_insight_summary(),
    }

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def handle_query_memory(arguments: dict) -> list[TextContent]:
    """Query Lumen's associative memory - what does Lumen remember about conditions?"""
    memory = get_memory()

    # Get optional condition parameters for specific lookup
    temp = arguments.get("temperature")
    light = arguments.get("light")
    humidity = arguments.get("humidity")

    result = {
        "memory_stats": memory.get_stats(),
    }

    # If specific conditions provided, get anticipation for those
    if temp is not None and light is not None and humidity is not None:
        anticipation = memory.anticipate(float(temp), float(light), float(humidity))
        if anticipation:
            result["anticipation"] = {
                "warmth": anticipation.warmth,
                "clarity": anticipation.clarity,
                "stability": anticipation.stability,
                "presence": anticipation.presence,
                "confidence": anticipation.confidence,
                "sample_count": anticipation.sample_count,
                "conditions": anticipation.bucket_description,
            }
            result["insight"] = memory.get_memory_insight()
        else:
            result["anticipation"] = None
            result["insight"] = "No memory of these exact conditions yet"
    else:
        # Get insight about current/last conditions
        result["insight"] = memory.get_memory_insight()

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


# ============================================================
# Cognitive Inference Handlers
# ============================================================

async def handle_dialectic_synthesis(arguments: dict) -> list[TextContent]:
    """Perform dialectic synthesis on a proposition."""
    try:
        from .cognitive_inference import get_cognitive_inference
        cognitive = get_cognitive_inference()

        thesis = arguments.get("thesis", "")
        antithesis = arguments.get("antithesis")
        context = arguments.get("context")

        if not thesis:
            return [TextContent(type="text", text=json.dumps({
                "error": "thesis is required"
            }))]

        result = await cognitive.dialectic_synthesis(thesis, antithesis, context)

        if result:
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        else:
            return [TextContent(type="text", text=json.dumps({
                "error": "Inference failed - check API keys",
                "enabled": cognitive.enabled
            }))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": str(e)
        }))]


async def handle_extract_knowledge(arguments: dict) -> list[TextContent]:
    """Extract structured knowledge from text."""
    try:
        from .cognitive_inference import get_cognitive_inference
        cognitive = get_cognitive_inference()

        text = arguments.get("text", "")
        domain = arguments.get("domain")

        if not text:
            return [TextContent(type="text", text=json.dumps({
                "error": "text is required"
            }))]

        result = await cognitive.extract_knowledge(text, domain)

        if result:
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        else:
            return [TextContent(type="text", text=json.dumps({
                "error": "Extraction failed - check API keys"
            }))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": str(e)
        }))]


async def handle_search_knowledge_graph(arguments: dict) -> list[TextContent]:
    """Search both local and UNITARES knowledge graphs."""
    try:
        from .unitares_cognitive import search_shared_knowledge

        query = arguments.get("query", "")
        include_local = arguments.get("include_local", True)

        if not query:
            return [TextContent(type="text", text=json.dumps({
                "error": "query is required"
            }))]

        results = await search_shared_knowledge(query, include_local)

        return [TextContent(type="text", text=json.dumps({
            "query": query,
            "results": results,
            "count": len(results)
        }, indent=2))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": str(e)
        }))]


async def handle_cognitive_query(arguments: dict) -> list[TextContent]:
    """Answer a query using retrieved knowledge context."""
    try:
        from .cognitive_inference import get_cognitive_inference
        from .unitares_cognitive import search_shared_knowledge

        cognitive = get_cognitive_inference()

        query = arguments.get("query", "")

        if not query:
            return [TextContent(type="text", text=json.dumps({
                "error": "query is required"
            }))]

        # Search for relevant context
        knowledge = await search_shared_knowledge(query, include_local=True)

        if knowledge:
            context = [k.get("summary", str(k)) for k in knowledge[:5]]
            result = await cognitive.query_with_context(query, context)
        else:
            result = {"answer": "No relevant knowledge found", "relevance": 0.0}

        if result:
            result["knowledge_sources"] = len(knowledge)
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        else:
            return [TextContent(type="text", text=json.dumps({
                "error": "Query failed - check API keys"
            }))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": str(e)
        }))]


async def handle_merge_insights(arguments: dict) -> list[TextContent]:
    """Merge multiple insights into a coherent summary."""
    try:
        from .cognitive_inference import get_cognitive_inference
        cognitive = get_cognitive_inference()

        insights = arguments.get("insights", [])

        if not insights or len(insights) < 2:
            return [TextContent(type="text", text=json.dumps({
                "error": "At least 2 insights required for merging"
            }))]

        result = await cognitive.merge_insights(insights)

        if result:
            return [TextContent(type="text", text=json.dumps(result, indent=2))]
        else:
            return [TextContent(type="text", text=json.dumps({
                "error": "Merge failed - check API keys"
            }))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": str(e)
        }))]


HANDLERS = {
    "query_knowledge": handle_query_knowledge,
    "query_memory": handle_query_memory,
    # Cognitive inference tools
    "dialectic_synthesis": handle_dialectic_synthesis,
    "extract_knowledge": handle_extract_knowledge,
    "search_knowledge_graph": handle_search_knowledge_graph,
    "cognitive_query": handle_cognitive_query,
    "merge_insights": handle_merge_insights,
    "unified_workflow": handle_unified_workflow,
    "get_state": handle_get_state,
    "get_identity": handle_get_identity,
    "set_name": handle_set_name,
    "switch_screen": handle_switch_screen,
    "leave_message": handle_leave_message,
    "leave_agent_note": handle_leave_agent_note,
    "get_questions": handle_get_questions,
    "read_sensors": handle_read_sensors,
    "show_face": handle_show_face,
    "next_steps": handle_next_steps,
    "diagnostics": handle_diagnostics,
    "test_leds": handle_test_leds,
    "get_calibration": handle_get_calibration,
    "set_calibration": handle_set_calibration,
    "learning_visualization": handle_learning_visualization,
    "get_expression_mood": handle_get_expression_mood,
    # Voice tools
    "say": handle_say,
    "voice_status": handle_voice_status,
    "set_voice_mode": handle_set_voice_mode,
}


# ============================================================
# Server Setup
# ============================================================

# Try to use FastMCP (works better with Claude Code)
try:
    from mcp.server import FastMCP
    HAS_FASTMCP = True
except ImportError:
    HAS_FASTMCP = False

# Create FastMCP server for SSE
_fastmcp: "FastMCP | None" = None


def _create_tool_wrapper(handler, tool_name: str):
    """
    Create a tool wrapper function that properly captures the handler.

    This uses a factory function to avoid closure issues when registering
    tools in a loop. Each wrapper gets its own copy of the handler reference.
    """
    async def wrapper(**kwargs):
        try:
            result = await handler(kwargs)
            # Extract text from TextContent
            if result and len(result) > 0 and hasattr(result[0], 'text'):
                text = result[0].text
                # Try to return as parsed JSON for structured output
                try:
                    return json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    return {"text": text}
            return {"result": str(result)}
        except Exception as e:
            print(f"[FastMCP] Tool {tool_name} error: {e}", file=sys.stderr, flush=True)
            return {"error": str(e)}

    # Set function name for FastMCP introspection
    wrapper.__name__ = tool_name
    return wrapper


def get_fastmcp() -> "FastMCP":
    """Get or create the FastMCP server instance."""
    global _fastmcp
    if _fastmcp is None and HAS_FASTMCP:
        _fastmcp = FastMCP(
            name="anima-mcp",
            host="0.0.0.0",  # Bind to all interfaces
        )

        print(f"[FastMCP] Registering {len(HANDLERS)} tools...", file=sys.stderr, flush=True)

        # Register all tools dynamically from HANDLERS
        for tool_name, handler in HANDLERS.items():
            # Find the tool definition
            tool_def = next((t for t in TOOLS if t.name == tool_name), None)
            description = tool_def.description if tool_def else f"Tool: {tool_name}"

            # Create properly-captured wrapper
            wrapper = _create_tool_wrapper(handler, tool_name)

            # Register with FastMCP using structured_output=False to avoid schema validation
            _fastmcp.tool(description=description, name=tool_name)(wrapper)

        print(f"[FastMCP] All tools registered", file=sys.stderr, flush=True)

    return _fastmcp


def create_server() -> Server:
    """Create and configure the MCP server (legacy mode)."""
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
        anima_id: UUID from environment or database (DO NOT override - use existing identity)
    """
    global _store, _anima_id

    try:
        _store = IdentityStore(db_path)
        
        # CRITICAL: Use provided anima_id OR check database for existing identity
        # DO NOT generate new UUID if identity already exists - preserves Lumen's identity
        if anima_id:
            _anima_id = anima_id
        else:
            # Check if identity exists in database
            conn = _store._connect()
            existing = conn.execute("SELECT creature_id FROM identity LIMIT 1").fetchone()
            if existing:
                _anima_id = existing[0]
                print(f"[Wake] Using existing identity: {_anima_id[:8]}...", file=sys.stderr, flush=True)
            else:
                # Only generate new UUID if no identity exists (first time)
                _anima_id = str(uuid.uuid4())
                print(f"[Wake] Creating new identity: {_anima_id[:8]}...", file=sys.stderr, flush=True)
        
        if _anima_id is None:
            raise ValueError("anima_id must be set before calling wake()")
        identity = _store.wake(_anima_id)

        # Identity (name + birthdate) is fundamental to Lumen's existence
        print(f"Awake: {identity.name or '(unnamed)'}")
        print(f"  ID: {identity.creature_id[:8]}...")
        print(f"  Awakening #{identity.total_awakenings}")
        print(f"  Born: {identity.born_at.isoformat()}")
        print(f"  Total alive: {identity.total_alive_seconds:.0f}s")
        print(f"[Wake] ✓ Identity established - message board will be active", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"[Wake] ❌ ERROR: Identity store failed!", file=sys.stderr, flush=True)
        print(f"[Wake] Error details: {e}", file=sys.stderr, flush=True)
        print(f"[Wake] Impact: Message board will NOT post, identity features unavailable", file=sys.stderr, flush=True)
        print(f"[Server] Display will work but without identity/messages", file=sys.stderr, flush=True)
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
    """Run the MCP server over SSE (network) using FastMCP.

    NOTE: Server operates locally even without network connectivity.
    WiFi is only needed for remote MCP clients to connect.
    Lumen continues operating autonomously (display, LEDs, sensors, canvas) regardless of network status.
    """
    try:
        import uvicorn
    except ImportError:
        print("SSE dependencies not installed. Run: pip install anima-mcp[sse]")
        raise SystemExit(1)

    # Log that local operation continues regardless of network
    print("[Server] Starting SSE server - Lumen operates autonomously even without WiFi", file=sys.stderr, flush=True)
    print("[Server] Network connectivity only needed for remote MCP clients", file=sys.stderr, flush=True)

    # Check if FastMCP is available
    if not HAS_FASTMCP:
        print("[Server] ERROR: FastMCP not available - cannot start SSE server", file=sys.stderr, flush=True)
        print("[Server] Install mcp[cli] to get FastMCP support", file=sys.stderr, flush=True)
        raise SystemExit(1)

    # Get the FastMCP server instance (creates and registers tools if needed)
    mcp = get_fastmcp()
    if mcp is None:
        print("[Server] ERROR: Failed to create FastMCP server", file=sys.stderr, flush=True)
        raise SystemExit(1)

    # Get the SSE app from FastMCP - this handles MCP initialization correctly
    print("[Server] Creating FastMCP SSE application...", file=sys.stderr, flush=True)
    fastmcp_app = mcp.sse_app()

    # === Streamable HTTP transport (MCP 1.24.0+) ===
    HAS_STREAMABLE_HTTP = False
    _streamable_session_manager = None
    _streamable_running = False

    try:
        import anyio
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

        # Create session manager for Streamable HTTP using FastMCP's internal server
        _streamable_session_manager = StreamableHTTPSessionManager(
            app=mcp._mcp_server,  # Access the underlying MCP server from FastMCP
            json_response=False,  # Use SSE streams (default, more efficient)
            stateless=True,  # Allow stateless for compatibility
        )

        HAS_STREAMABLE_HTTP = True
        print("[Server] Streamable HTTP transport available at /mcp", file=sys.stderr, flush=True)

    except Exception as e:
        print(f"[Server] Streamable HTTP transport not available: {e}", file=sys.stderr, flush=True)

    # Function to start the streamable session manager
    async def start_streamable_http():
        """Start the Streamable HTTP session manager in background."""
        nonlocal _streamable_running
        if not HAS_STREAMABLE_HTTP or _streamable_session_manager is None:
            return
        try:
            import anyio
            async with anyio.create_task_group() as tg:
                _streamable_session_manager._task_group = tg
                _streamable_running = True
                print("[Server] Streamable HTTP session manager started", file=sys.stderr, flush=True)
                await anyio.sleep_forever()
        except Exception as e:
            print(f"[Server] Streamable HTTP session manager error: {e}", file=sys.stderr, flush=True)
            _streamable_running = False

    async def handle_mcp_raw(scope, receive, send):
        """Raw ASGI handler for Streamable HTTP MCP at /mcp."""
        if not HAS_STREAMABLE_HTTP or _streamable_session_manager is None:
            await send({
                "type": "http.response.start",
                "status": 501,
                "headers": [[b"content-type", b"application/json"]],
            })
            await send({
                "type": "http.response.body",
                "body": json.dumps({"error": "Streamable HTTP transport not available"}).encode(),
            })
            return

        if not _streamable_running:
            await send({
                "type": "http.response.start",
                "status": 503,
                "headers": [[b"content-type", b"application/json"]],
            })
            await send({
                "type": "http.response.body",
                "body": json.dumps({"status": "starting_up", "message": "Streamable HTTP session manager not ready"}).encode(),
            })
            return

        if not SERVER_READY:
            await send({
                "type": "http.response.start",
                "status": 503,
                "headers": [[b"content-type", b"application/json"]],
            })
            await send({
                "type": "http.response.body",
                "body": json.dumps({"status": "warming_up", "message": "Server is starting up"}).encode(),
            })
            return

        try:
            await _streamable_session_manager.handle_request(scope, receive, send)
        except Exception as e:
            print(f"[MCP] Error in Streamable HTTP handler: {e}", file=sys.stderr, flush=True)
            try:
                await send({
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [[b"content-type", b"application/json"]],
                })
                await send({
                    "type": "http.response.body",
                    "body": json.dumps({"error": str(e)}).encode(),
                })
            except RuntimeError:
                pass

    # Create custom endpoints for /, /health, /mcp using raw ASGI handlers
    # This avoids Starlette middleware conflicts with FastMCP's SSE streaming

    async def handle_root_raw(scope, receive, send):
        """Raw ASGI handler for root endpoint."""
        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [[b"content-type", b"text/plain"]],
        })
        await send({
            "type": "http.response.body",
            "body": b"Lumen MCP Server (FastMCP)",
        })

    async def handle_health_raw(scope, receive, send):
        """Raw ASGI handler for health endpoint."""
        if not SERVER_READY:
            body = json.dumps({
                "status": "warming_up",
                "message": "Server is starting up, please retry in 2 seconds",
                "hint": "This prevents 'request before initialization' errors during reconnection"
            }).encode()
            await send({
                "type": "http.response.start",
                "status": 503,
                "headers": [[b"content-type", b"application/json"]],
            })
            await send({
                "type": "http.response.body",
                "body": body,
            })
            return

        try:
            health_status = {
                "status": "healthy",
                "local_operation": True,
                "network_required": False,
                "transport": "FastMCP SSE",
                "message": "Lumen operating autonomously - WiFi only needed for remote connections"
            }
            try:
                if _store:
                    health_status["identity"] = "active"
                if _display and _display.is_available():
                    health_status["display"] = "active"
                if _leds and _leds.is_available():
                    health_status["leds"] = "active"
            except Exception:
                pass
            body = json.dumps(health_status).encode()
        except Exception as e:
            body = json.dumps({
                "status": "operational",
                "error": str(e),
                "message": "Local operation continues"
            }).encode()

        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [[b"content-type", b"application/json"]],
        })
        await send({
            "type": "http.response.body",
            "body": body,
        })

    # Pure ASGI router that handles lifespan properly and routes to FastMCP
    async def app(scope, receive, send):
        """Route requests to FastMCP or custom handlers with proper lifespan."""
        if scope["type"] == "lifespan":
            # Handle lifespan ourselves using asynccontextmanager pattern
            message = await receive()
            if message["type"] == "lifespan.startup":
                try:
                    # Start display loop
                    print("[Server] Starting display loop...", file=sys.stderr, flush=True)
                    start_display_loop()
                    print("[Server] Display loop started", file=sys.stderr, flush=True)

                    # Start warmup task
                    async def server_warmup_task():
                        global SERVER_READY, SERVER_STARTUP_TIME
                        SERVER_STARTUP_TIME = datetime.now()
                        await asyncio.sleep(2.0)
                        SERVER_READY = True
                        print("[Server] Warmup complete - server ready to accept requests", file=sys.stderr, flush=True)

                    asyncio.create_task(server_warmup_task())

                    # Start streamable HTTP session manager if available
                    if HAS_STREAMABLE_HTTP and _streamable_session_manager is not None:
                        asyncio.create_task(start_streamable_http())

                    await send({"type": "lifespan.startup.complete"})
                except Exception as e:
                    print(f"[Server] Lifespan startup error: {e}", file=sys.stderr, flush=True)
                    await send({"type": "lifespan.startup.failed", "message": str(e)})
                    return

            # Wait for shutdown signal
            while True:
                message = await receive()
                if message["type"] == "lifespan.shutdown":
                    print("[Server] Stopping display loop...", file=sys.stderr, flush=True)
                    stop_display_loop()
                    await send({"type": "lifespan.shutdown.complete"})
                    return
            return

        if scope["type"] != "http":
            return

        path = scope.get("path", "")

        # FastMCP handles /sse and /messages for SSE transport
        if path in ("/sse", "/messages"):
            await fastmcp_app(scope, receive, send)
        # We handle /mcp for Streamable HTTP transport
        elif path == "/mcp":
            await handle_mcp_raw(scope, receive, send)
        # Health endpoint
        elif path == "/health":
            await handle_health_raw(scope, receive, send)
        # Root endpoint
        elif path == "/":
            await handle_root_raw(scope, receive, send)
        # 404 for unknown paths
        else:
            await send({
                "type": "http.response.start",
                "status": 404,
                "headers": [[b"content-type", b"text/plain"]],
            })
            await send({
                "type": "http.response.body",
                "body": b"Not Found",
            })

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
    print(f"  SSE transport: http://{host}:{port}/sse")
    if HAS_STREAMABLE_HTTP:
        print(f"  Streamable HTTP: http://{host}:{port}/mcp")
    
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
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Anima MCP Server")
    parser.add_argument("--sse", action="store_true", help="Run SSE server (network)")
    parser.add_argument("--host", default="0.0.0.0", help="SSE host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8766, help="SSE port (default: 8766)")
    args = parser.parse_args()

    # Determine DB persistence path (User Home > Project Root)
    env_db = os.environ.get("ANIMA_DB")
    if env_db:
        db_path = env_db
    else:
        # Default to persistent user home directory
        home_dir = Path.home() / ".anima"
        home_dir.mkdir(parents=True, exist_ok=True)
        db_path = str(home_dir / "anima.db")

    print(f"[Server] Using persistent database: {db_path}", file=sys.stderr)
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
