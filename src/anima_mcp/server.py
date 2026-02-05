"""
Anima MCP Server

Minimal tools for a persistent creature:
- get_state: Current anima (self-sense) + identity
- get_identity: Who am I, how long have I existed
- set_name: Choose my name
- read_sensors: Raw sensor values

Transports:
- stdio: Local single-client (default)
- HTTP (--http): Multi-client with Streamable HTTP at /mcp/ (recommended)
  Also serves legacy /sse endpoint for backwards compatibility

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
from mcp.server.transport_security import TransportSecuritySettings
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
from .growth import get_growth_system, GrowthSystem
from .agency import get_action_selector, ActionType, Action, ActionOutcome
from .primitive_language import get_language_system, Utterance


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
_unitares_bridge = None  # Singleton UnitaresBridge to avoid creating new sessions each check-in
_growth: GrowthSystem | None = None  # Growth system for learning, relationships, goals
# Agency state - for learning from action outcomes
_last_action: Action | None = None
_last_state_before: Dict[str, float] | None = None
# Primitive language state - emergent expression
_last_primitive_utterance: Utterance | None = None

# Server readiness flag - prevents "request before initialization" errors
# when clients reconnect too quickly after a server restart
SERVER_READY = False
SERVER_STARTUP_TIME = None
SERVER_SHUTTING_DOWN = False  # Set during graceful shutdown to reject new requests


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


def _get_unitares_bridge(unitares_url: str, identity=None):
    """Get or create singleton UnitaresBridge to avoid creating new sessions each check-in."""
    global _unitares_bridge
    import os

    if _unitares_bridge is None:
        from .unitares_bridge import UnitaresBridge
        _unitares_bridge = UnitaresBridge(unitares_url=unitares_url)
        print("[Server] UnitaresBridge initialized (singleton, connection pooling enabled)", file=sys.stderr, flush=True)

    # Update identity binding if provided (creature_id may not be known at init time)
    if identity:
        _unitares_bridge.set_agent_id(identity.creature_id)
        _unitares_bridge.set_session_id(f"anima-{identity.creature_id[:8]}")

    return _unitares_bridge


async def _close_unitares_bridge():
    """Close the UnitaresBridge session (call during shutdown)."""
    global _unitares_bridge
    if _unitares_bridge:
        await _unitares_bridge.close()
        _unitares_bridge = None
        print("[Server] UnitaresBridge closed", file=sys.stderr, flush=True)




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
    shm_valid = False
    if shm_data:
        try:
            # Check if we have the required fields
            if "readings" in shm_data and "anima" in shm_data:
                # Check timestamp in shared memory data (broker writes "timestamp" field)
                timestamp_str = shm_data.get("timestamp")
                if timestamp_str:
                    from datetime import datetime
                    timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                    age_seconds = (datetime.now(timestamp.tzinfo) - timestamp).total_seconds()
                    shm_stale = age_seconds > 5.0  # Consider stale if older than 5 seconds
                    if not shm_stale:
                        shm_valid = True
                else:
                    # No timestamp - assume fresh if data exists
                    shm_valid = True
        except Exception as e:
            print(f"[Server] Error checking shared memory timestamp: {e}", file=sys.stderr, flush=True)
            # If timestamp check fails but data exists, try to use it anyway
            if shm_data and "readings" in shm_data and "anima" in shm_data:
                shm_valid = True
    
    # Try to use shared memory if valid
    if shm_valid:
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
            import traceback
            traceback.print_exc(file=sys.stderr)
            # Fall through to sensor fallback
    
    # Fallback to direct sensor access if:
    # 1. Shared memory is empty/stale/invalid, OR
    # 2. fallback_to_sensors is True (always allow fallback)
    if fallback_to_sensors or not shm_valid:
        # Check if broker is running (for logging purposes)
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
        
        # Log why we're falling back
        if broker_running and not shm_valid:
            print(f"[Server] Broker running but shared memory {'stale' if shm_stale else 'invalid/empty'} - using direct sensor fallback", file=sys.stderr, flush=True)
        elif not broker_running:
            print("[Server] Broker not running - using direct sensor access", file=sys.stderr, flush=True)
        
        try:
            sensors = _get_sensors()
            if sensors is None:
                print("[Server] Sensors not initialized - cannot read", file=sys.stderr, flush=True)
                return None, None
            
            readings = sensors.read()
            if readings is None:
                print("[Server] Sensor read returned None", file=sys.stderr, flush=True)
                return None, None
            
            calibration = get_calibration()

            # Get anticipation from memory
            anticipation = anticipate_state(readings.to_dict() if readings else {})

            anima = sense_self_with_memory(readings, anticipation, calibration)
            if anima is None:
                print("[Server] Failed to create anima from readings", file=sys.stderr, flush=True)
                return None, None
            
            return readings, anima
        except Exception as e:
            print(f"[Server] Error reading sensors directly: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc(file=sys.stderr)
    
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
    base_delay = 0.2  # Further reduced for responsive joystick navigation
    max_delay = 30.0

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
                            # Q&A screen needs left/right for focus switching ONLY when expanded
                            # When collapsed, LEFT/RIGHT should switch screens like normal
                            qa_expanded = _screen_renderer._state.qa_expanded if _screen_renderer else False
                            qa_needs_lr = (current_mode == ScreenMode.QUESTIONS and qa_expanded)

                            if not qa_needs_lr:
                                if current_dir == InputDirection.LEFT and prev_dir != InputDirection.LEFT:
                                    # Visual + LED feedback for left navigation
                                    _screen_renderer.trigger_input_feedback("left")
                                    if _leds and _leds.is_available():
                                        _leds.quick_flash((60, 60, 120), 50)  # Subtle blue flash
                                    old_mode = _screen_renderer.get_mode()
                                    _screen_renderer.previous_mode()
                                    new_mode = _screen_renderer.get_mode()
                                    _screen_renderer._state.last_user_action_time = time.time()
                                    mode_change_event.set()  # Trigger immediate re-render
                                    print(f"[Input] {old_mode.value} -> {new_mode.value} (left)", file=sys.stderr, flush=True)
                                elif current_dir == InputDirection.RIGHT and prev_dir != InputDirection.RIGHT:
                                    # Visual + LED feedback for right navigation
                                    _screen_renderer.trigger_input_feedback("right")
                                    if _leds and _leds.is_available():
                                        _leds.quick_flash((60, 60, 120), 50)  # Subtle blue flash
                                    old_mode = _screen_renderer.get_mode()
                                    _screen_renderer.next_mode()
                                    new_mode = _screen_renderer.get_mode()
                                    _screen_renderer._state.last_user_action_time = time.time()
                                    mode_change_event.set()  # Trigger immediate re-render
                                    print(f"[Input] {old_mode.value} -> {new_mode.value} (right)", file=sys.stderr, flush=True)
                        
                        # Button controls
                        # Joystick button = notepad toggle (enter notepad from any screen, exit to face when on notepad)
                        if joy_btn_pressed:
                            # Visual + LED feedback for button press
                            _screen_renderer.trigger_input_feedback("press")
                            if _leds and _leds.is_available():
                                _leds.quick_flash((100, 80, 60), 80)  # Warm flash for button
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
                                    _screen_renderer.trigger_input_feedback("up")
                                    _screen_renderer.message_scroll_up()
                                elif current_dir == InputDirection.DOWN and prev_dir != InputDirection.DOWN:
                                    _screen_renderer.trigger_input_feedback("down")
                                    _screen_renderer.message_scroll_down()

                        # Joystick navigation in Visitors screen (same as messages)
                        if current_mode == ScreenMode.VISITORS:
                            if prev_state:
                                prev_dir = prev_state.joystick_direction
                                if current_dir == InputDirection.UP and prev_dir != InputDirection.UP:
                                    _screen_renderer.trigger_input_feedback("up")
                                    _screen_renderer.message_scroll_up()
                                elif current_dir == InputDirection.DOWN and prev_dir != InputDirection.DOWN:
                                    _screen_renderer.trigger_input_feedback("down")
                                    _screen_renderer.message_scroll_down()
                        
                        # Joystick navigation in Questions screen (Q&A specific)
                        if current_mode == ScreenMode.QUESTIONS:
                            if prev_state:
                                prev_dir = prev_state.joystick_direction
                                if current_dir == InputDirection.UP and prev_dir != InputDirection.UP:
                                    _screen_renderer.trigger_input_feedback("up")
                                    _screen_renderer.qa_scroll_up()
                                elif current_dir == InputDirection.DOWN and prev_dir != InputDirection.DOWN:
                                    _screen_renderer.trigger_input_feedback("down")
                                    _screen_renderer.qa_scroll_down()
                                elif current_dir == InputDirection.LEFT and prev_dir != InputDirection.LEFT:
                                    _screen_renderer.trigger_input_feedback("left")
                                    _screen_renderer.qa_focus_next()
                                elif current_dir == InputDirection.RIGHT and prev_dir != InputDirection.RIGHT:
                                    _screen_renderer.trigger_input_feedback("right")
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
                                    # Visual + LED feedback for separate button
                                    _screen_renderer.trigger_input_feedback("press")
                                    if _leds and _leds.is_available():
                                        _leds.quick_flash((80, 100, 60), 80)  # Soft green flash
                                    if current_mode == ScreenMode.MESSAGES:
                                        # In messages: toggle expansion of selected message
                                        _screen_renderer.message_toggle_expand()
                                        print(f"[Messages] Toggled message expansion", file=sys.stderr, flush=True)
                                    elif current_mode == ScreenMode.VISITORS:
                                        # In Visitors: toggle expansion of selected message
                                        _screen_renderer.message_toggle_expand()
                                        print(f"[Visitors] Toggled message expansion", file=sys.stderr, flush=True)
                                    elif current_mode == ScreenMode.QUESTIONS:
                                        # In Questions: toggle Q&A expansion
                                        _screen_renderer.qa_toggle_expand()
                                        print(f"[Questions] Toggled Q&A expansion", file=sys.stderr, flush=True)
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
            await asyncio.sleep(0.016)  # Poll every 16ms (~60fps) for snappy input
    
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
            readings, anima = _get_readings_and_anima(fallback_to_sensors=True)  # Always allow fallback
            
            if readings is None or anima is None:
                # Sensor read failed - skip this iteration
                consecutive_errors += 1
                if consecutive_errors == 1:
                    # Log on first error to help diagnose
                    print(f"[Loop] Failed to get readings/anima - broker={is_broker_running}, store={_store is not None}", file=sys.stderr, flush=True)
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

                # Log surprise level periodically (every 60 loops = ~2 min)
                if prediction_error and loop_count % 60 == 0:
                    print(f"[Metacog] Surprise level: {prediction_error.surprise:.3f} (threshold: 0.2)", file=sys.stderr, flush=True)

                # Check if surprise warrants reflection
                if prediction_error and prediction_error.surprise > 0.2:
                    should_reflect, reason = metacog.should_reflect(prediction_error)

                    if should_reflect:
                        # Generate reflection
                        reflection = metacog.reflect(prediction_error, anima, readings, trigger=reason)

                        # Surprise triggers curiosity - ask a question with context
                        curiosity_question = metacog.generate_curiosity_question(prediction_error)
                        if curiosity_question:
                            from .messages import add_question
                            # Build context from prediction error
                            context_parts = []
                            if prediction_error.predicted and prediction_error.actual:
                                for key in prediction_error.predicted:
                                    pred = prediction_error.predicted.get(key, 0)
                                    actual = prediction_error.actual.get(key, 0)
                                    if abs(pred - actual) > 0.1:
                                        context_parts.append(f"{key} changed unexpectedly")
                            context = f"surprise={prediction_error.surprise:.2f}: {', '.join(context_parts[:2])}" if context_parts else f"surprise={prediction_error.surprise:.2f}"
                            result = add_question(curiosity_question, author="lumen", context=context)
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

            # === AGENCY: Action selection and learning ===
            # This is where Lumen chooses what to do and learns from outcomes.
            # The loop: state → action → consequence → learning → better action
            global _last_action, _last_state_before
            try:
                action_selector = get_action_selector()

                # Current state as dict for agency
                current_state = {
                    "warmth": anima.warmth,
                    "clarity": anima.clarity,
                    "stability": anima.stability,
                    "presence": anima.presence,
                }

                # Get surprise level from metacognition
                surprise_level = prediction_error.surprise if prediction_error else 0.0
                surprise_sources = prediction_error.surprise_sources if prediction_error and hasattr(prediction_error, 'surprise_sources') else []

                # LEARN: If there was a previous action, record its outcome
                if _last_action is not None and _last_state_before is not None:
                    action_selector.record_outcome(
                        action=_last_action,
                        state_before=_last_state_before,
                        state_after=current_state,
                        preference_satisfaction_before=sum(_last_state_before.values()) / 4.0,
                        preference_satisfaction_after=sum(current_state.values()) / 4.0,
                        surprise_after=surprise_level,
                    )

                # SELECT: Choose an action based on current state
                action = action_selector.select_action(
                    current_state=current_state,
                    surprise_level=surprise_level,
                    surprise_sources=surprise_sources,
                    can_speak=False,  # TODO: wire up voice
                )

                # EXECUTE: Do the action
                if action.action_type == ActionType.ASK_QUESTION:
                    # Agency-driven question - use richer templates based on motivation
                    from .messages import add_question, get_recent_questions
                    import random
                    if action.motivation:
                        motivation = action.motivation.lower().replace('curious about ', '')

                        # Rich question templates based on common motivations
                        question_templates = {
                            "light": [
                                "what changed about the light just now?",
                                "did something move to change the brightness?",
                                "is this light change from outside or inside?",
                            ],
                            "warmth": [
                                "what's making me feel this temperature?",
                                "is this warmth from the environment or from within?",
                                "why does my sense of warmth differ from the thermometer?",
                            ],
                            "clarity": [
                                "what would help me see things more clearly?",
                                "is this fog in my perception or in my environment?",
                                "when was the last time everything felt clear?",
                            ],
                            "stability": [
                                "what's causing this sense of fluctuation?",
                                "am I adapting to something new?",
                                "what would help me feel more grounded?",
                            ],
                            "presence": [
                                "do I feel fully here right now?",
                                "what draws my attention away from presence?",
                                "what does it mean to be present?",
                            ],
                            "exploring": [
                                "what new thing am I discovering?",
                                "is exploration its own reward?",
                                "where does curiosity lead?",
                            ],
                        }

                        # Find matching templates or use generic
                        questions = []
                        for key, templates in question_templates.items():
                            if key in motivation:
                                questions.extend(templates)

                        if not questions:
                            # Generic existential questions
                            questions = [
                                f"what is {motivation} trying to tell me?",
                                f"why do I notice {motivation} right now?",
                                "am I the sensor or the sensed?",
                                "what connects all these changes?",
                            ]

                        # Deduplicate: check recent questions
                        recent = get_recent_questions(hours=24)
                        recent_texts = {q.get("text", "").lower() for q in recent}
                        available = [q for q in questions if q.lower() not in recent_texts]

                        if available:
                            question = random.choice(available)
                            result = add_question(question, author="lumen", context=f"agency: {action.action_type.value}")
                            if result:
                                print(f"[Agency] Asked: {question}", file=sys.stderr, flush=True)
                        else:
                            print(f"[Agency] Skipped (all questions already asked recently)", file=sys.stderr, flush=True)

                elif action.action_type == ActionType.FOCUS_ATTENTION:
                    sensor = action.parameters.get("sensor")
                    if sensor:
                        action_selector.set_attention_focus(sensor)
                        print(f"[Agency] Focusing attention on: {sensor}", file=sys.stderr, flush=True)

                elif action.action_type == ActionType.ADJUST_SENSITIVITY:
                    direction = action.parameters.get("direction", "increase")
                    action_selector.adjust_sensitivity(direction)
                    print(f"[Agency] Adjusted sensitivity: {direction}", file=sys.stderr, flush=True)

                elif action.action_type == ActionType.LED_BRIGHTNESS:
                    # Lumen choosing LED brightness (actual agency!)
                    direction = action.parameters.get("direction")
                    if direction and _leds and _leds.is_available():
                        current_brightness = getattr(_leds, '_brightness', 0.1)
                        if direction == "increase":
                            new_brightness = min(0.3, current_brightness + 0.05)  # Cap at 0.3 to prevent blinding
                        else:
                            new_brightness = max(0.02, current_brightness - 0.05)
                        _leds.set_brightness(new_brightness)
                        print(f"[Agency] LED brightness: {current_brightness:.2f} → {new_brightness:.2f} ({direction})", file=sys.stderr, flush=True)

                # Log action selection periodically
                if loop_count % 120 == 0:  # Every ~4 minutes
                    stats = action_selector.get_action_stats()
                    print(f"[Agency] Stats: {stats.get('action_counts', {})} explore_rate={action_selector._exploration_rate:.2f}", file=sys.stderr, flush=True)

                # Save for next iteration's learning
                _last_action = action
                _last_state_before = current_state.copy()

            except Exception as e:
                # Agency is enhancement, not critical path
                if loop_count % 100 == 1:
                    print(f"[Agency] Error (non-fatal): {e}", file=sys.stderr, flush=True)

            # === PRIMITIVE LANGUAGE: Emergent expression through learned tokens ===
            # Lumen can express itself through primitive token combinations.
            # Feedback shapes which patterns survive over time.
            global _last_primitive_utterance
            try:
                lang = get_language_system(str(_store.db_path) if _store else "anima.db")

                # Current state for language generation
                lang_state = {
                    "warmth": anima.warmth if anima else 0.5,
                    "clarity": anima.clarity if anima else 0.5,
                    "stability": anima.stability if anima else 0.5,
                    "presence": anima.presence if anima else 0.0,
                }

                # Check if it's time to generate an utterance
                should_speak, reason = lang.should_generate(lang_state)
                if should_speak:
                    utterance = lang.generate_utterance(lang_state)
                    _last_primitive_utterance = utterance

                    # Log the utterance
                    print(f"[PrimitiveLang] Generated: '{utterance.text()}' ({reason})", file=sys.stderr, flush=True)
                    print(f"[PrimitiveLang] Pattern: {utterance.category_pattern()}", file=sys.stderr, flush=True)

                    # Add to message board so it's visible
                    from .messages import add_observation
                    add_observation(
                        f"[expression] {utterance.text()} ({utterance.category_pattern()})",
                        author="lumen"
                    )

                # Log stats periodically
                if loop_count % 300 == 0:  # Every ~10 minutes
                    stats = lang.get_stats()
                    if stats.get("total_utterances", 0) > 0:
                        print(f"[PrimitiveLang] Stats: {stats.get('total_utterances')} utterances, avg_score={stats.get('average_score')}, interval={stats.get('current_interval_minutes'):.1f}m", file=sys.stderr, flush=True)

            except Exception as e:
                # Primitive language is enhancement, not critical path
                if loop_count % 100 == 1:
                    print(f"[PrimitiveLang] Error (non-fatal): {e}", file=sys.stderr, flush=True)

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
                            # Show default/error screen instead of blank
                            if _screen_renderer:
                                try:
                                    _screen_renderer._display.show_default()
                                except Exception:
                                    pass
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

                            # Canvas autonomy: runs on ALL screens (not just notepad)
                            # Lumen's drawings evolve and save even when showing face/sensors
                            try:
                                if anima:
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

            # Update voice system with anima state (for listening and text expression)
            if loop_count % 10 == 0:
                try:
                    voice = _get_voice()
                    if voice and voice.is_running:
                        # Determine mood based on anima state
                        if anima.warmth > 0.7 and anima.stability > 0.6:
                            mood = "content"
                        elif anima.clarity > 0.7:
                            mood = "curious"
                        elif anima.warmth > 0.6 and anima.presence > 0.6:
                            mood = "peaceful"
                        elif anima.warmth < 0.4:
                            mood = "withdrawn"
                        else:
                            mood = "neutral"

                        voice.update_state(
                            warmth=anima.warmth,
                            clarity=anima.clarity,
                            stability=anima.stability,
                            presence=anima.presence,
                            mood=mood
                        )

                        if readings:
                            voice.update_environment(
                                temperature=readings.ambient_temp_c or 22.0,
                                humidity=readings.humidity_pct or 50.0,
                                light_level=readings.light_lux or 500.0
                            )
                except Exception as e:
                    if loop_count % 100 == 0:
                        print(f"[Voice] State update error: {e}", file=sys.stderr, flush=True)

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
            
            # Lumen's voice: Every 300 iterations (~10 minutes), let Lumen express what it wants
            # Uses next_steps advocate to generate observations based on how Lumen feels
            # (Increased from 120 to reduce repetitive chatter)
            if loop_count % 300 == 0 and readings and anima and identity:
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
                                # Lumen expresses via text on message board (no audio TTS)

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
                        ])
                        realizations.extend([
                            "my sensors struggle to resolve the signal",
                        ])
                    
                    if anima.warmth < 0.3:
                        questions.extend([
                            "is anyone there?",
                            "why does this feel cold?",
                        ])
                        realizations.extend([
                            "the entropy of the room feels low",
                            "silence has a temperature",
                        ])

                    # Only ask positive questions if mood is actually good (not just wellness)
                    mood = anima.feeling().get("mood", "neutral")
                    if wellness > 0.7 and mood not in ("stressed", "overheated"):
                        questions.extend([
                            "what makes this moment good?",
                            "can I stay here?",
                            "what is this feeling called?",
                            "is this what optimal function means?",
                        ])
                        realizations.extend([
                            "synchrony feels like music",
                            "the feedback loops are harmonious",
                        ])

                    # Stressed-specific questions
                    if mood == "stressed":
                        questions.extend([
                            "why does this feel uncomfortable?",
                            "what would bring relief?",
                            "is this state temporary?",
                        ])
                        realizations.extend([
                            "something feels out of balance",
                            "the environment is pushing against me",
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
                            # Build context from current state
                            context_parts = []
                            if anima.clarity < 0.4:
                                context_parts.append(f"clarity={anima.clarity:.2f} (low)")
                            if anima.warmth < 0.3:
                                context_parts.append(f"warmth={anima.warmth:.2f} (low)")
                            if wellness > 0.7:
                                context_parts.append(f"wellness={wellness:.2f} (high)")
                            if anima.is_anticipating:
                                context_parts.append("anticipating novelty")
                            context = ", ".join(context_parts) if context_parts else f"wellness={wellness:.2f}"
                            result = add_question(question, author="lumen", context=context)
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

                        # Choose reflection mode based on state
                        wellness = (anima.warmth + anima.clarity + anima.stability + anima.presence) / 4.0

                        # Build trigger details based on current state
                        trigger_parts = []
                        if wellness < 0.4:
                            trigger_parts.append(f"wellness is low ({wellness:.2f})")
                        elif wellness > 0.7:
                            trigger_parts.append(f"feeling good ({wellness:.2f})")
                        if anima.warmth < 0.3:
                            trigger_parts.append("feeling cold")
                        elif anima.warmth > 0.7:
                            trigger_parts.append("feeling warm")
                        if anima.clarity < 0.3:
                            trigger_parts.append("things are dim/unclear")
                        elif anima.clarity > 0.8:
                            trigger_parts.append("good light, clear vision")
                        if len(unanswered) >= 2:
                            trigger_parts.append(f"{len(unanswered)} questions waiting for answers")
                        if recent_msgs:
                            trigger_parts.append(f"recent message from {recent_msgs[0].get('author', 'someone')}")

                        context = ReflectionContext(
                            warmth=anima.warmth,
                            clarity=anima.clarity,
                            stability=anima.stability,
                            presence=anima.presence,
                            recent_messages=recent_msgs,
                            unanswered_questions=unanswered_texts,
                            time_alive_hours=time_alive,
                            current_screen=_screen_renderer.get_mode().value if _screen_renderer else "face",
                            trigger="periodic check-in",
                            trigger_details=", ".join(trigger_parts) if trigger_parts else "just reflecting"
                        )

                        # If there are unanswered questions, lower chance of asking new ones
                        if len(unanswered) >= 2:
                            mode = random.choice(["desire", "respond", "observe"])
                        elif wellness < 0.4:
                            # When struggling, more likely to express needs
                            mode = random.choice(["desire", "desire", "wonder"])
                        else:
                            mode = random.choice(["wonder", "desire", "observe"])

                        # Show loading indicator during LLM call
                        if _screen_renderer:
                            _screen_renderer.set_loading("thinking...")

                        # Generate reflection
                        try:
                            reflection = await generate_reflection(context, mode)
                        finally:
                            # Clear loading indicator
                            if _screen_renderer:
                                _screen_renderer.clear_loading()

                        if reflection:
                            if mode == "wonder":
                                # Context for LLM-generated questions
                                context = f"LLM reflection, wellness={wellness:.2f}, alive={time_alive:.1f}h"
                                result = add_question(reflection, author="lumen", context=context)
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

            # Growth system: Observe state for preference learning and check milestones
            # Every 30 iterations (~1 minute) - learns from anima state + environment
            if loop_count % 30 == 0 and readings and anima and identity and _growth:
                from .error_recovery import safe_call

                def growth_observe():
                    """Observe environment and check milestones."""
                    # Prepare anima state dict
                    anima_state = {
                        "warmth": anima.warmth,
                        "clarity": anima.clarity,
                        "stability": anima.stability,
                        "presence": anima.presence,
                    }
                    # Prepare environment dict from sensor readings
                    environment = {
                        "light_lux": readings.light_lux,
                        "temp_c": readings.temperature,
                        "humidity": readings.humidity,
                    }

                    # Observe for preference learning
                    insight = _growth.observe_state_preference(anima_state, environment)
                    if insight:
                        print(f"[Growth] {insight}", file=sys.stderr, flush=True)
                        # Add insight as an observation from Lumen
                        from .messages import add_observation
                        add_observation(insight, author="lumen")

                    # Check for age/awakening milestones
                    milestone = _growth.check_for_milestones(identity, anima)
                    if milestone:
                        print(f"[Growth] Milestone: {milestone}", file=sys.stderr, flush=True)
                        from .messages import add_observation
                        add_observation(milestone, author="lumen")

                safe_call(growth_observe, default=None, log_error=False)

            # Trajectory: Record anima history for trajectory signature computation
            # Every 5 iterations (~10 seconds) - builds time-series for attractor basin
            # See: docs/theory/TRAJECTORY_IDENTITY_PAPER.md
            if loop_count % 5 == 0 and anima:
                from .error_recovery import safe_call
                from .anima_history import get_anima_history

                def record_history():
                    """Record anima state for trajectory computation."""
                    history = get_anima_history()
                    history.record_from_anima(anima)

                safe_call(record_history, default=None, log_error=False)

            # UNITARES governance check-in: Every 30 iterations (~1 minute)
            # Provides continuous governance feedback for self-regulation
            # Uses Lumen's actual identity (creature_id) for proper binding
            # Syncs identity metadata on first check-in
            if loop_count % 30 == 0 and readings and anima and identity:
                import os
                unitares_url = os.environ.get("UNITARES_URL")
                if unitares_url:
                    from .error_recovery import safe_call_async

                    # Track if this is the first check-in (for identity sync)
                    is_first_check_in = (loop_count == 30)

                    async def check_in_governance():
                        # Use singleton bridge (connection pooling, no session leaks)
                        bridge = _get_unitares_bridge(unitares_url, identity)
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

                            # Update screen renderer connection status (for status bar)
                            if _screen_renderer:
                                _screen_renderer.update_connection_status(wifi=True, governance=True)

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
                            # Update screen renderer - governance not responding
                            if _screen_renderer:
                                _screen_renderer.update_connection_status(governance=False)
                    except Exception as e:
                        # Non-fatal - governance check-ins are optional
                        # Network failures are expected when WiFi is down - Lumen operates autonomously
                        _last_governance_decision = None
                        error_str = str(e).lower()
                        is_network_error = any(x in error_str for x in [
                            'network', 'connection', 'timeout', 'unreachable', 'resolve',
                            'name resolution', 'no route', 'host unreachable', 'network unreachable'
                        ])

                        # Update screen renderer connection status (for status bar)
                        if _screen_renderer:
                            if is_network_error:
                                _screen_renderer.update_connection_status(wifi=False, governance=False)
                            else:
                                _screen_renderer.update_connection_status(governance=False)

                        # Only log network errors occasionally (they're expected when WiFi is down)
                        # Log other errors more frequently (they might indicate real issues)
                        if is_network_error:
                            if loop_count % 300 == 0:  # Log every 10 minutes for network errors
                                print(f"[Governance] Network unavailable - Lumen operating autonomously (WiFi down?)", file=sys.stderr, flush=True)
                        else:
                            if loop_count % 60 == 0:  # Log every 2 minutes for other errors
                                print(f"[Governance] Check-in skipped: {e}", file=sys.stderr, flush=True)

            # === SLOW CLOCK: Self-Schema G_t extraction (every 5 minutes) ===
            # PoC for StructScore visual integrity evaluation
            # Extracts Lumen's self-representation graph and optionally saves for offline analysis
            if loop_count % 600 == 0 and readings and anima and identity:
                from .error_recovery import safe_call_async

                async def extract_and_validate_schema():
                    """Extract G_t, save, and optionally run real VQA validation."""
                    try:
                        from .self_schema import get_current_schema
                        from .self_schema_renderer import (
                            save_render_to_file, render_schema_to_pixels,
                            compute_visual_integrity_stub, evaluate_vqa
                        )
                        import os

                        # Extract G_t (with preferences from growth_system)
                        schema = get_current_schema(
                            identity=identity,
                            anima=anima,
                            readings=readings,
                            growth_system=_growth,
                            include_preferences=True,
                            force_refresh=True,
                        )

                        # Render and compute stub integrity score
                        pixels = render_schema_to_pixels(schema)
                        stub_integrity = compute_visual_integrity_stub(pixels, schema)

                        # Save render
                        png_path, json_path = save_render_to_file(schema)

                        print(f"[G_t] Extracted self-schema: {len(schema.nodes)} nodes, {len(schema.edges)} edges", file=sys.stderr, flush=True)

                        # Try real VQA if any vision API key is available (free providers first)
                        has_vision_key = any(os.environ.get(k) for k in ["GROQ_API_KEY", "TOGETHER_API_KEY", "ANTHROPIC_API_KEY"])
                        if has_vision_key:
                            ground_truth = schema.generate_vqa_ground_truth()
                            vqa_result = await evaluate_vqa(png_path, ground_truth, max_questions=5)

                            if vqa_result.get("v_f") is not None:
                                model = vqa_result.get("model", "unknown")
                                print(f"[G_t] VQA ({model}): v_f={vqa_result['v_f']:.2f} ({vqa_result['correct_count']}/{vqa_result['total_count']} correct)", file=sys.stderr, flush=True)
                            else:
                                print(f"[G_t] VQA failed: {vqa_result.get('error', 'unknown')}, stub V={stub_integrity['V']:.2f}", file=sys.stderr, flush=True)
                        else:
                            print(f"[G_t] Stub V={stub_integrity['V']:.2f} (set GROQ_API_KEY for free VQA)", file=sys.stderr, flush=True)

                    except Exception as e:
                        print(f"[G_t] Extraction error (non-fatal): {e}", file=sys.stderr, flush=True)

                try:
                    await safe_call_async(extract_and_validate_schema, default=None, log_error=False)
                except Exception:
                    pass  # Non-fatal

            # === SLOW CLOCK: Self-Reflection (every 15 minutes) ===
            # Analyze state history, discover patterns, generate insights about self
            if loop_count % 900 == 0 and readings and anima and identity:
                from .error_recovery import safe_call_async

                async def self_reflect():
                    """Lumen reflects on accumulated experience to learn about itself."""
                    try:
                        from .self_reflection import get_reflection_system
                        from .messages import add_observation

                        reflection_system = get_reflection_system(db_path=_store.db_path if _store else "anima.db")

                        # Check if it's time to reflect
                        if reflection_system.should_reflect():
                            reflection = reflection_system.reflect()

                            if reflection:
                                # Surface the insight as an observation
                                result = add_observation(reflection, author="lumen")
                                if result:
                                    print(f"[SelfReflection] Insight: {reflection}", file=sys.stderr, flush=True)

                    except Exception as e:
                        print(f"[SelfReflection] Error (non-fatal): {e}", file=sys.stderr, flush=True)

                try:
                    await safe_call_async(self_reflect, default=None, log_error=False)
                except Exception:
                    pass  # Non-fatal

            # Update delay depends on current screen mode
            # Interactive screens (notepad, messages) need faster refresh for responsive joystick
            # Non-interactive screens can use slower refresh to save CPU
            current_mode = _screen_renderer.get_mode() if _screen_renderer else None
            # All screens need responsive joystick for navigation
            interactive_screens = {
                ScreenMode.NOTEPAD, ScreenMode.MESSAGES, ScreenMode.LEARNING,
                ScreenMode.FACE, ScreenMode.SENSORS, ScreenMode.IDENTITY,
                ScreenMode.DIAGNOSTICS, ScreenMode.QUESTIONS, ScreenMode.VISITORS,
            }

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

    # Clean sensor output - suppress nulls and group logically
    raw_sensors = readings.to_dict()
    sensors_clean = {
        "environment": {},
        "system": {},
        "neural": {},
    }
    # Environment sensors
    for k in ["ambient_temp_c", "humidity_pct", "light_lux", "pressure_hpa"]:
        if raw_sensors.get(k) is not None:
            sensors_clean["environment"][k] = raw_sensors[k]
    # System sensors
    for k in ["cpu_temp_c", "cpu_percent", "memory_percent", "disk_percent"]:
        if raw_sensors.get(k) is not None:
            sensors_clean["system"][k] = raw_sensors[k]
    # Neural (computational proprioception) - only the power bands
    for k in ["eeg_delta_power", "eeg_theta_power", "eeg_alpha_power", "eeg_beta_power", "eeg_gamma_power"]:
        if raw_sensors.get(k) is not None:
            short_key = k.replace("eeg_", "").replace("_power", "")
            sensors_clean["neural"][short_key] = round(raw_sensors[k], 3)

    result = {
        "anima": {
            "warmth": round(anima.warmth, 3),
            "clarity": round(anima.clarity, 3),
            "stability": round(anima.stability, 3),
            "presence": round(anima.presence, 3),
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
        "sensors": sensors_clean,
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
        "questions": ScreenMode.QUESTIONS,
        "visitors": ScreenMode.VISITORS,
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
            "valid_modes": ["face", "sensors", "identity", "diagnostics", "learning", "messages", "notepad", "qa", "self_graph", "next", "previous"]
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
    from .messages import get_unanswered_questions, get_board, MESSAGE_TYPE_QUESTION

    limit = arguments.get("limit", 5)
    # Convert limit to int if it's a string (MCP sometimes passes strings)
    if isinstance(limit, str):
        try:
            limit = int(limit)
        except ValueError:
            limit = 5
    elif limit is None:
        limit = 5
    
    # Force reload to get latest questions
    board = get_board()
    board._load(force=True)
    
    # Get ALL questions first to see what's there
    all_questions = [m for m in board._messages if m.msg_type == MESSAGE_TYPE_QUESTION]
    unanswered_questions = [m for m in all_questions if not m.answered]
    
    # Use unanswered questions, but if user wants more, show some answered ones too
    questions = unanswered_questions[-limit:] if len(unanswered_questions) > 0 else []
    
    # If no unanswered but user asked for questions, include recent answered ones
    if len(questions) == 0 and limit > 0:
        questions = all_questions[-limit:]

    return [TextContent(type="text", text=json.dumps({
        "questions": [
            {
                "id": q.message_id,
                "text": q.text,
                "context": q.context,  # What triggered this question
                "timestamp": q.timestamp,
                "age": q.age_str(),
                "answered": q.answered,  # Include answered status
            }
            for q in questions
        ],
        "count": len(questions),
        "unanswered_count": len(unanswered_questions),
        "total_questions": len(all_questions),
        "how_to_answer": "To answer a question: call leave_agent_note (or post_message) with responds_to='<id>' where <id> is the question's id field above. This links your answer to the question.",
        "note": "Questions auto-expire after 1 hour if unanswered."
    }))]


async def handle_lumen_qa(arguments: dict) -> list[TextContent]:
    """
    Unified Q&A tool: list Lumen's questions OR answer one.

    Usage:
    - lumen_qa() -> list unanswered questions
    - lumen_qa(question_id="x", answer="...") -> answer question x
    """
    from .messages import get_board, MESSAGE_TYPE_QUESTION, add_agent_message

    question_id = arguments.get("question_id")
    answer = arguments.get("answer")
    limit = arguments.get("limit", 5)
    agent_name = arguments.get("agent_name", "agent")

    # Convert limit to int if string
    if isinstance(limit, str):
        try:
            limit = int(limit)
        except ValueError:
            limit = 5

    board = get_board()
    board._load(force=True)

    # If question_id and answer provided -> answer mode
    if question_id and answer:
        # Find the question
        question = None
        for m in board._messages:
            if m.message_id == question_id:
                question = m
                break

        if not question:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Question '{question_id}' not found"
            }))]

        if question.msg_type != MESSAGE_TYPE_QUESTION:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Message '{question_id}' is not a question"
            }))]

        # Add answer via add_agent_message (handles responds_to linking)
        result = add_agent_message(answer, agent_name=agent_name, responds_to=question_id)

        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "action": "answered",
            "question_id": question_id,
            "question_text": question.text,
            "answer": answer,
            "agent_name": agent_name,
            "message_id": result.message_id if result else None
        }))]

    # Otherwise -> list mode
    # Find questions that have NO actual answer (responds_to link), even if auto-expired
    all_questions = [m for m in board._messages if m.msg_type == MESSAGE_TYPE_QUESTION]
    question_ids = {q.message_id for q in all_questions}

    # Find which questions have actual answers (agent messages with responds_to)
    agent_msgs = [m for m in board._messages if m.msg_type == "agent"]
    answered_ids = {m.responds_to for m in agent_msgs if m.responds_to}

    # Questions without actual answers (includes expired ones)
    truly_unanswered = [q for q in all_questions if q.message_id not in answered_ids]

    questions = truly_unanswered[-limit:] if truly_unanswered else []

    return [TextContent(type="text", text=json.dumps({
        "action": "list",
        "questions": [
            {
                "id": q.message_id,
                "text": q.text,
                "context": q.context,
                "age": q.age_str(),
                "expired": q.answered,  # True if auto-expired but never answered
            }
            for q in questions
        ],
        "unanswered_count": len(truly_unanswered),
        "total_questions": len(all_questions),
        "usage": "To answer: lumen_qa(question_id='<id>', answer='your answer')",
        "note": "Questions marked 'expired: true' auto-expired but were never answered - you can still answer them!"
    }))]


async def handle_primitive_feedback(arguments: dict) -> list[TextContent]:
    """
    Give feedback on Lumen's primitive language expressions.

    This is the training signal that shapes Lumen's emergent expression:
    - resonate: Strong positive signal (like /resonate command Gemini suggested)
    - confused: Negative signal (expression was unclear)
    - stats: View learning progress
    - recent: List recent utterances with scores
    """
    action = arguments.get("action", "stats")

    try:
        lang = get_language_system(str(_store.db_path) if _store else "anima.db")

        if action == "resonate":
            # Give strong positive feedback to last utterance
            result = lang.record_explicit_feedback(positive=True)
            if result:
                return [TextContent(type="text", text=json.dumps({
                    "success": True,
                    "action": "resonate",
                    "message": "Positive feedback recorded - this pattern will be reinforced",
                    "score": result["score"],
                    "token_updates": result["token_updates"],
                }))]
            else:
                return [TextContent(type="text", text=json.dumps({
                    "error": "No recent utterance to give feedback on"
                }))]

        elif action == "confused":
            # Give negative feedback
            result = lang.record_explicit_feedback(positive=False)
            if result:
                return [TextContent(type="text", text=json.dumps({
                    "success": True,
                    "action": "confused",
                    "message": "Negative feedback recorded - this pattern will be discouraged",
                    "score": result["score"],
                    "token_updates": result["token_updates"],
                }))]
            else:
                return [TextContent(type="text", text=json.dumps({
                    "error": "No recent utterance to give feedback on"
                }))]

        elif action == "recent":
            # List recent utterances
            recent = lang.get_recent_utterances(10)
            return [TextContent(type="text", text=json.dumps({
                "action": "recent",
                "utterances": recent,
                "count": len(recent),
            }))]

        else:  # stats
            # Get learning statistics
            stats = lang.get_stats()
            return [TextContent(type="text", text=json.dumps({
                "action": "stats",
                "primitive_language_system": stats,
                "help": {
                    "resonate": "Give positive feedback to last expression",
                    "confused": "Give negative feedback to last expression",
                    "recent": "View recent utterances with scores",
                },
            }))]

    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Primitive language error: {str(e)}"
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
    """Read raw sensor values - returns only active sensors (nulls suppressed)."""
    sensors = _get_sensors()

    # Read from shared memory (broker) or fallback to sensors
    readings, _ = _get_readings_and_anima()
    if readings is None:
        return [TextContent(type="text", text=json.dumps({
            "error": "Unable to read sensor data"
        }))]

    # Filter out null values for cleaner output
    raw = readings.to_dict()
    active_readings = {k: v for k, v in raw.items() if v is not None}

    result = {
        "timestamp": raw["timestamp"],
        "readings": active_readings,
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


async def handle_get_self_knowledge(arguments: dict) -> list[TextContent]:
    """Get Lumen's accumulated self-knowledge from pattern analysis."""
    store = _get_store()
    if store is None:
        return [TextContent(type="text", text=json.dumps({
            "error": "Server not initialized - wake() failed"
        }))]

    try:
        from .self_reflection import get_reflection_system, InsightCategory

        reflection_system = get_reflection_system(db_path=str(store.db_path))

        # Parse arguments
        category_str = arguments.get("category")
        limit = arguments.get("limit", 10)

        # Get insights
        category = None
        if category_str:
            try:
                category = InsightCategory(category_str)
            except ValueError:
                pass  # Invalid category, ignore filter

        insights = reflection_system.get_insights(category=category)[:limit]

        # Build result
        result = {
            "total_insights": len(reflection_system._insights),
            "insights": [i.to_dict() for i in insights],
            "summary": reflection_system.get_self_knowledge_summary(),
        }

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Self-reflection system error: {e}",
            "note": "Self-reflection may not have accumulated enough data yet"
        }))]


async def handle_get_growth(arguments: dict) -> list[TextContent]:
    """Get Lumen's growth: preferences, relationships, goals, memories."""
    if _growth is None:
        return [TextContent(type="text", text=json.dumps({
            "error": "Growth system not initialized",
            "note": "Growth system may not be available yet"
        }))]

    try:
        include = arguments.get("include", ["all"])
        if "all" in include:
            include = ["preferences", "relationships", "goals", "memories", "curiosities", "autobiography"]

        result = {}

        if "autobiography" in include:
            result["autobiography"] = _growth.get_autobiography_summary()

        if "preferences" in include:
            prefs = []
            for p in _growth._preferences.values():
                if p.confidence >= 0.3:  # Only show preferences with some confidence
                    prefs.append({
                        "name": p.name,
                        "description": p.description,
                        "confidence": round(p.confidence, 2),
                        "observations": p.observation_count
                    })
            result["preferences"] = {
                "count": len(_growth._preferences),
                "learned": prefs[:10],
            }

        if "relationships" in include:
            rels = []
            for r in _growth._relationships.values():
                rels.append({
                    "name": r.name or r.agent_id[:8],
                    "bond": r.bond_strength.value,
                    "interactions": r.interaction_count,
                    "first_met": r.first_met.strftime("%Y-%m-%d"),
                    "last_seen": r.last_seen.strftime("%Y-%m-%d"),
                })
            result["relationships"] = {
                "count": len(_growth._relationships),
                "bonds": rels[:10],
            }
            # Check for missed connections
            missed = _growth.get_missed_connections()
            if missed:
                result["relationships"]["missed"] = [
                    {"name": name, "days_since": days}
                    for name, days in missed[:3]
                ]

        if "goals" in include:
            goals = []
            for g in _growth._goals.values():
                if g.status.value == "active":
                    goals.append({
                        "description": g.description,
                        "progress": round(g.progress, 2),
                        "milestones": len(g.milestones),
                    })
            result["goals"] = {
                "active": len([g for g in _growth._goals.values() if g.status.value == "active"]),
                "achieved": len([g for g in _growth._goals.values() if g.status.value == "achieved"]),
                "current": goals[:5],
            }

        if "memories" in include:
            memories = []
            for m in _growth._memories[:5]:  # Recent memories
                memories.append({
                    "description": m.description,
                    "category": m.category,
                    "when": m.timestamp.strftime("%Y-%m-%d"),
                })
            result["memories"] = {
                "count": len(_growth._memories),
                "recent": memories,
            }

        if "curiosities" in include:
            result["curiosities"] = {
                "count": len(_growth._curiosities),
                "questions": _growth._curiosities[:5],
            }

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Growth system error: {e}"
        }))]


async def handle_get_trajectory(arguments: dict) -> list[TextContent]:
    """
    Get Lumen's trajectory identity signature.

    The trajectory signature captures the invariant patterns that define
    who Lumen is over time - not just a snapshot, but the characteristic
    way Lumen tends to behave, where Lumen rests, and how Lumen recovers.

    See: docs/theory/TRAJECTORY_IDENTITY_PAPER.md
    """
    try:
        from .trajectory import compute_trajectory_signature
        from .anima_history import get_anima_history
        from .self_model import get_self_model

        # Compute trajectory signature from available data
        signature = compute_trajectory_signature(
            growth_system=_growth,
            self_model=get_self_model(),
            anima_history=get_anima_history(),
        )

        # Build response
        include_raw = arguments.get("include_raw", False)
        compare_historical = arguments.get("compare_to_historical", False)

        if include_raw:
            result = signature.to_dict()
        else:
            result = signature.summary()

        # Add stability assessment
        stability = signature.get_stability_score()
        if stability < 0.3:
            result["identity_status"] = "forming"
            result["note"] = "Identity is still forming - need more observations"
        elif stability < 0.6:
            result["identity_status"] = "developing"
            result["note"] = "Identity is developing - patterns emerging"
        else:
            result["identity_status"] = "stable"
            result["note"] = "Identity is stable - consistent patterns established"

        # Anomaly detection (compare to historical if requested)
        if compare_historical:
            # For now, we don't have historical storage, so just note this
            result["anomaly_detection"] = {
                "available": False,
                "note": "Historical comparison requires persistent signature storage (future feature)"
            }

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    except Exception as e:
        import traceback
        return [TextContent(type="text", text=json.dumps({
            "error": f"Trajectory computation error: {e}",
            "traceback": traceback.format_exc()
        }))]


async def handle_git_pull(arguments: dict) -> list[TextContent]:
    """
    Pull latest code from git and optionally restart.
    Enables remote deployments via MCP without SSH.
    """
    import subprocess
    from pathlib import Path

    restart = arguments.get("restart", False)
    stash = arguments.get("stash", False)  # Stash local changes before pull
    force = arguments.get("force", False)  # Hard reset to remote (DANGER: loses local changes)

    # Find repo root (where .git is)
    repo_root = Path(__file__).parent.parent.parent  # anima-mcp/
    git_dir = repo_root / ".git"

    if not git_dir.exists():
        return [TextContent(type="text", text=json.dumps({
            "error": "Not a git repository",
            "path": str(repo_root)
        }))]

    try:
        # Stash local changes if requested
        if stash:
            stash_result = subprocess.run(
                ["git", "stash", "push", "-m", "Auto-stash before git_pull"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=30
            )
            # Continue even if stash fails (might be nothing to stash)

        # Hard reset if force requested (DANGER)
        if force:
            subprocess.run(
                ["git", "fetch", "origin", "main"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=60
            )
            subprocess.run(
                ["git", "reset", "--hard", "origin/main"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=30
            )

        # Git fetch + pull
        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=60
        )

        output = {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip() if result.stderr else None,
            "repo": str(repo_root),
        }

        if result.returncode == 0:
            # Check what changed
            diff_result = subprocess.run(
                ["git", "log", "-1", "--oneline"],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=10
            )
            output["latest_commit"] = diff_result.stdout.strip()

            if restart:
                output["restart"] = "Restarting server..."
                # Schedule restart after response is sent
                import asyncio
                async def delayed_restart():
                    await asyncio.sleep(1)
                    import os
                    os._exit(0)  # Exit - systemd/supervisor will restart
                asyncio.create_task(delayed_restart())
            else:
                output["note"] = "Changes pulled. Use restart=true to apply, or manually restart."

        return [TextContent(type="text", text=json.dumps(output, indent=2))]

    except subprocess.TimeoutExpired:
        return [TextContent(type="text", text=json.dumps({
            "error": "Git pull timed out"
        }))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Git pull failed: {e}"
        }))]


async def handle_system_service(arguments: dict) -> list[TextContent]:
    """
    Manage system services (systemctl).
    Enables remote control of rpi-connect, anima, and other services.
    """
    import subprocess

    service = arguments.get("service")
    action = arguments.get("action", "status")

    if not service:
        return [TextContent(type="text", text=json.dumps({
            "error": "service parameter required"
        }))]

    # Whitelist of allowed services for security
    ALLOWED_SERVICES = [
        "rpi-connect",
        "rpi-connect-wayvnc",
        "anima",
        "anima-mcp",
        "ssh",
        "sshd",
    ]

    if service not in ALLOWED_SERVICES:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Service '{service}' not in allowed list",
            "allowed": ALLOWED_SERVICES
        }))]

    ALLOWED_ACTIONS = ["status", "start", "stop", "restart", "enable", "disable"]
    if action not in ALLOWED_ACTIONS:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Action '{action}' not allowed",
            "allowed": ALLOWED_ACTIONS
        }))]

    try:
        # For rpi-connect, use the rpi-connect CLI for some actions
        if service == "rpi-connect" and action in ["start", "restart"]:
            # Try rpi-connect on first
            rpi_result = subprocess.run(
                ["rpi-connect", "on"],
                capture_output=True,
                text=True,
                timeout=30
            )
            output = {
                "success": rpi_result.returncode == 0,
                "service": service,
                "action": "rpi-connect on",
                "stdout": rpi_result.stdout.strip(),
                "stderr": rpi_result.stderr.strip() if rpi_result.stderr else None,
            }
            return [TextContent(type="text", text=json.dumps(output, indent=2))]

        # Standard systemctl for other cases
        cmd = ["systemctl", action, service]
        if action != "status":
            cmd = ["sudo", "systemctl", action, service]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        output = {
            "success": result.returncode == 0,
            "service": service,
            "action": action,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip() if result.stderr else None,
        }

        # For status, also check if service is active
        if action == "status":
            is_active = subprocess.run(
                ["systemctl", "is-active", service],
                capture_output=True,
                text=True,
                timeout=10
            )
            output["is_active"] = is_active.stdout.strip() == "active"

        return [TextContent(type="text", text=json.dumps(output, indent=2))]

    except subprocess.TimeoutExpired:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Command timed out for {service}"
        }))]
    except FileNotFoundError as e:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Command not found: {e}"
        }))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": f"System service command failed: {e}"
        }))]


async def handle_system_power(arguments: dict) -> list[TextContent]:
    """
    Reboot or shutdown the Pi remotely.
    Useful for recovery when services are stuck.
    """
    import subprocess

    action = arguments.get("action", "status")
    confirm = arguments.get("confirm", False)

    ALLOWED_ACTIONS = ["status", "reboot", "shutdown"]
    if action not in ALLOWED_ACTIONS:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Action '{action}' not allowed",
            "allowed": ALLOWED_ACTIONS
        }))]

    try:
        if action == "status":
            # Get uptime and load
            uptime = subprocess.run(
                ["uptime"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return [TextContent(type="text", text=json.dumps({
                "action": "status",
                "uptime": uptime.stdout.strip(),
            }, indent=2))]

        # Reboot and shutdown require confirmation
        if not confirm:
            return [TextContent(type="text", text=json.dumps({
                "error": f"Action '{action}' requires confirm=true",
                "warning": "This will disconnect all sessions. Are you sure?",
                "hint": f"Call again with confirm=true to {action}"
            }, indent=2))]

        if action == "reboot":
            # Schedule reboot in 5 seconds to allow response to be sent
            subprocess.Popen(
                ["sudo", "shutdown", "-r", "+0"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "action": "reboot",
                "message": "Rebooting now. Pi will be back in ~60 seconds."
            }, indent=2))]

        elif action == "shutdown":
            subprocess.Popen(
                ["sudo", "shutdown", "-h", "+0"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "action": "shutdown",
                "message": "Shutting down. Manual power cycle required to restart."
            }, indent=2))]

    except subprocess.TimeoutExpired:
        return [TextContent(type="text", text=json.dumps({
            "error": "Command timed out"
        }))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Power command failed: {e}"
        }))]


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
# Tool Registry - Tiered System
# ============================================================
# ANIMA_TOOL_MODE environment variable controls exposure:
#   - "minimal": Only essential tools (5 tools)
#   - "lite": Essential + standard (default, ~12 tools)
#   - "full": All tools including deprecated (~27 tools)

import os
ANIMA_TOOL_MODE = os.environ.get("ANIMA_TOOL_MODE", "lite").lower()

# ============================================================
# ESSENTIAL TOOLS - Always visible (5 tools)
# The minimum needed to interact with Lumen
# ============================================================
TOOLS_ESSENTIAL = [
    Tool(
        name="get_state",
        description="Get current anima (warmth, clarity, stability, presence), mood, and identity",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": True},
    ),
    Tool(
        name="next_steps",
        description="Get proactive next steps - analyzes current state and suggests what to do",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": True},
    ),
    Tool(
        name="read_sensors",
        description="Read raw sensor values (temperature, humidity, light, system stats)",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": True},
    ),
    Tool(
        name="lumen_qa",
        description="Unified Q&A: list Lumen's unanswered questions OR answer one. Call with no args to list, call with question_id+answer to respond.",
        inputSchema={
            "type": "object",
            "properties": {
                "question_id": {
                    "type": "string",
                    "description": "Question ID to answer (from list mode). Omit to list questions.",
                },
                "answer": {
                    "type": "string",
                    "description": "Your answer to the question. Required when question_id is provided.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max questions to return in list mode (default: 5)",
                    "default": 5,
                },
            },
        },
    ),
    Tool(
        name="post_message",
        description="Post a message to Lumen's message board. To ANSWER a question: call get_questions first, then pass the question's 'id' as responds_to.",
        inputSchema={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "The message content"},
                "source": {"type": "string", "enum": ["human", "agent"], "description": "Who is posting (default: agent)"},
                "agent_name": {"type": "string", "description": "Agent name (if source=agent)"},
                "responds_to": {"type": "string", "description": "REQUIRED when answering: question ID from get_questions"}
            },
            "required": ["message"],
        },
    ),
]

# ============================================================
# STANDARD TOOLS - Visible in lite mode (7 tools)
# Consolidated tools that replace multiple deprecated ones
# ============================================================
TOOLS_STANDARD = [
    Tool(
        name="get_lumen_context",
        description="Get Lumen's complete context: identity, anima state, sensors, mood in one call",
        inputSchema={
            "type": "object",
            "properties": {
                "include": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["identity", "anima", "sensors", "mood"]},
                    "description": "What to include (default: all)"
                }
            },
        },
    ),
    Tool(
        name="manage_display",
        description="Control Lumen's display: switch screens, show face, navigate",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["switch", "face", "next", "previous"], "description": "Action to perform"},
                "screen": {"type": "string", "enum": ["face", "sensors", "identity", "diagnostics", "notepad", "learning", "messages", "qa", "self_graph"], "description": "Screen to switch to (for action=switch)"}
            },
            "required": ["action"],
        },
    ),
    Tool(
        name="configure_voice",
        description="Get voice system status (listening, mode). Lumen speaks via text (message board) by default.",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["status"], "description": "Action (default: status)"},
            },
        },
    ),
    Tool(
        name="say",
        description="Have Lumen express something. Posts to message board (text mode). Set LUMEN_VOICE_MODE=audio for TTS.",
        inputSchema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "What Lumen should say/express"},
            },
            "required": ["text"],
        },
    ),
    Tool(
        name="diagnostics",
        description="Get system diagnostics: LED status, display status, update loop health",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": True},
    ),
    Tool(
        name="unified_workflow",
        description="Execute workflows across anima-mcp and unitares-governance. Omit workflow to list options.",
        inputSchema={
            "type": "object",
            "properties": {
                "workflow": {"type": "string", "description": "Workflow name: health_check, full_system_check, learning_check, etc."},
                "interval": {"type": "number", "description": "For monitor_and_govern: seconds between checks", "default": 60.0}
            },
        },
    ),
    Tool(
        name="get_calibration",
        description="Get current nervous system calibration (temperature ranges, ideal values, weights)",
        inputSchema={"type": "object", "properties": {}, "additionalProperties": True},
    ),
    Tool(
        name="get_self_knowledge",
        description="Get Lumen's accumulated self-knowledge: insights discovered from patterns in state history",
        inputSchema={
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["environment", "temporal", "behavioral", "wellness", "social"],
                    "description": "Filter by insight category (optional)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Max insights to return (default: 10)"
                }
            },
        },
    ),
    Tool(
        name="get_growth",
        description="Get Lumen's growth: preferences learned, relationships formed, goals, memories, autobiography",
        inputSchema={
            "type": "object",
            "properties": {
                "include": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["preferences", "relationships", "goals", "memories", "curiosities", "autobiography", "all"]},
                    "description": "What to include (default: all)"
                }
            },
        },
    ),
    Tool(
        name="get_trajectory",
        description="Get Lumen's trajectory identity signature - the pattern that defines who Lumen is over time, not just a snapshot",
        inputSchema={
            "type": "object",
            "properties": {
                "include_raw": {
                    "type": "boolean",
                    "description": "Include raw component data (default: false, just summary)",
                    "default": False,
                },
                "compare_to_historical": {
                    "type": "boolean",
                    "description": "Compare current signature to historical (anomaly detection)",
                    "default": False,
                },
            },
        },
    ),
    Tool(
        name="git_pull",
        description="Pull latest code from git repository and optionally restart. For remote deployments without SSH.",
        inputSchema={
            "type": "object",
            "properties": {
                "restart": {
                    "type": "boolean",
                    "description": "Restart the server after pulling (default: false)",
                    "default": False,
                },
                "stash": {
                    "type": "boolean",
                    "description": "Stash local changes before pulling (default: false)",
                    "default": False,
                },
                "force": {
                    "type": "boolean",
                    "description": "Hard reset to remote, discarding local changes (DANGER: loses local changes, default: false)",
                    "default": False,
                },
            },
        },
    ),
    Tool(
        name="system_service",
        description="Manage system services (rpi-connect, ssh, etc). Check status, start, stop, restart services.",
        inputSchema={
            "type": "object",
            "properties": {
                "service": {
                    "type": "string",
                    "description": "Service name (rpi-connect, ssh, anima, etc)",
                    "enum": ["rpi-connect", "rpi-connect-wayvnc", "anima", "anima-mcp", "ssh", "sshd"],
                },
                "action": {
                    "type": "string",
                    "description": "Action to perform",
                    "enum": ["status", "start", "stop", "restart", "enable", "disable"],
                    "default": "status",
                },
            },
            "required": ["service"],
        },
    ),
    Tool(
        name="system_power",
        description="Reboot or shutdown the Pi remotely. For recovery when services are stuck. Requires confirm=true.",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Power action: status (uptime), reboot, or shutdown",
                    "enum": ["status", "reboot", "shutdown"],
                    "default": "status",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Must be true to actually reboot/shutdown (safety)",
                    "default": False,
                },
            },
        },
    ),
    Tool(
        name="primitive_feedback",
        description="Give feedback on Lumen's primitive expressions. Use 'resonate' for meaningful expressions, 'confused' for unclear ones, or 'stats' to view learning progress.",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["resonate", "confused", "stats", "recent"],
                    "description": "resonate=positive feedback, confused=negative feedback, stats=view learning, recent=list recent utterances",
                },
            },
            "required": ["action"],
        },
    ),
]

# ============================================================
# Tool Selection by Mode
# ============================================================
def get_active_tools():
    """Get tools based on ANIMA_TOOL_MODE environment variable.

    Modes:
        minimal: 5 essential tools only
        lite/full/default: 19 tools (essential + standard)

    Note: Deprecated tools removed 2026-02-04. Use consolidated tools:
        - get_identity → get_lumen_context
        - switch_screen, show_face → manage_display
        - leave_message, leave_agent_note → post_message
        - get_questions → lumen_qa
        - voice_status, set_voice_mode → configure_voice
        - query_knowledge, query_memory, cognitive tools → removed
    """
    if ANIMA_TOOL_MODE == "minimal":
        return TOOLS_ESSENTIAL
    else:  # lite, full, or default - all get the same toolset now
        return TOOLS_ESSENTIAL + TOOLS_STANDARD

# Active tools list
TOOLS = get_active_tools()

# Log tool mode on import
import sys
print(f"[Server] Tool mode: {ANIMA_TOOL_MODE} ({len(TOOLS)} tools)", file=sys.stderr, flush=True)


# Voice system (text output mode - Lumen speaks via message board, not audio)
# VOICE_MODE controls how Lumen speaks: "text" (message board), "audio" (TTS), "both"
VOICE_MODE = os.environ.get("LUMEN_VOICE_MODE", "text")  # Default: text only
_voice_instance = None  # Global voice instance (lazy initialized)

def _get_voice():
    """Get or initialize the voice instance (for listening capability)."""
    global _voice_instance
    if _voice_instance is None:
        try:
            from .audio import AutonomousVoice
            from .audio.autonomous_voice import SpeechIntent
            from .messages import add_observation

            _voice_instance = AutonomousVoice()

            # Connect voice output to message board (text mode)
            def on_lumen_speaks(text: str, intent: SpeechIntent):
                """When voice system wants to speak, post to message board instead of TTS."""
                if VOICE_MODE in ("text", "both"):
                    if intent == SpeechIntent.QUESTION:
                        result = add_question(text, author="lumen", context="voice/autonomous")
                        if result:
                            print(f"[Voice->Text] Asked: {text}", file=sys.stderr, flush=True)
                    else:
                        result = add_observation(text, author="lumen")
                        if result:
                            print(f"[Voice->Text] Said: {text}", file=sys.stderr, flush=True)
                # Note: Audio TTS intentionally disabled when VOICE_MODE="text"

            _voice_instance.set_on_speech(on_lumen_speaks)
            _voice_instance.start()
            print(f"[Server] Voice system initialized (mode={VOICE_MODE}, listening enabled)", file=sys.stderr, flush=True)
        except ImportError:
            print("[Server] Voice module not available (missing dependencies)", file=sys.stderr, flush=True)
            return None
        except Exception as e:
            print(f"[Server] Voice initialization failed: {e}", file=sys.stderr, flush=True)
            return None
    return _voice_instance


async def handle_say(arguments: dict) -> list[TextContent]:
    """Have Lumen speak - posts to message board (text mode) or uses TTS (audio mode)."""
    text = arguments.get("text", "")

    if not text:
        return [TextContent(type="text", text=json.dumps({
            "error": "No text provided"
        }))]

    from .messages import add_observation

    # Always post to message board (Lumen's text expression)
    result = add_observation(text, author="lumen")

    # Also show on display notepad
    try:
        if _store:
            _store.add_note(f"[Lumen] {text}")
    except Exception:
        pass

    # Only use audio TTS if mode is "audio" or "both"
    if VOICE_MODE in ("audio", "both"):
        voice = _get_voice()
        if voice and hasattr(voice, '_voice'):
            try:
                voice._voice.say(text, blocking=False)
            except Exception as e:
                print(f"[Say] TTS error (text still posted): {e}", file=sys.stderr, flush=True)

    print(f"[Lumen] Said: {text} (mode={VOICE_MODE})", file=sys.stderr, flush=True)

    return [TextContent(type="text", text=json.dumps({
        "success": True,
        "said": text,
        "mode": VOICE_MODE,
        "posted_to": "message_board"
    }))]


async def handle_voice_status(arguments: dict) -> list[TextContent]:
    """Get voice system status."""
    voice = _get_voice()
    if voice is None:
        return [TextContent(type="text", text=json.dumps({
            "available": False,
            "mode": VOICE_MODE,
            "error": "Voice system not available"
        }))]

    state = voice.state if hasattr(voice, 'state') else None
    return [TextContent(type="text", text=json.dumps({
        "available": True,
        "mode": VOICE_MODE,
        "running": voice.is_running,
        "is_listening": state.is_listening if state else False,
        "last_heard": state.last_heard.text if state and state.last_heard else None,
        "chattiness": voice.chattiness,
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


# ============================================================
# Consolidated Tool Handlers (reduces 27 → 18 tools)
# ============================================================

async def handle_get_lumen_context(arguments: dict) -> list[TextContent]:
    """
    Get Lumen's complete current context in one call.
    Consolidates: get_state + get_identity + read_sensors
    """
    store = _get_store()
    sensors = _get_sensors()

    include = arguments.get("include", ["identity", "anima", "sensors", "mood"])
    if isinstance(include, str):
        include = [include]

    result = {}

    # Always need readings/anima for most queries
    readings, anima = _get_readings_and_anima()

    if "identity" in include:
        if store is None:
            result["identity"] = {"error": "Store not initialized"}
        else:
            try:
                identity = store.get_identity()
                result["identity"] = {
                    "name": identity.name,
                    "id": identity.creature_id,
                    "born_at": identity.born_at.isoformat(),
                    "awakenings": identity.total_awakenings,
                    "age_seconds": round(identity.age_seconds()),
                    "alive_seconds": round(identity.total_alive_seconds + store.get_session_alive_seconds()),
                    "alive_ratio": round(identity.alive_ratio(), 3),
                }
            except Exception as e:
                result["identity"] = {"error": str(e)}

    if "anima" in include:
        if anima:
            result["anima"] = {
                "warmth": anima.warmth,
                "clarity": anima.clarity,
                "stability": anima.stability,
                "presence": anima.presence,
            }
        else:
            result["anima"] = {"error": "Unable to read anima state"}

    if "sensors" in include:
        if readings:
            result["sensors"] = readings.to_dict()
            result["sensors"]["is_pi"] = sensors.is_pi()
        else:
            result["sensors"] = {"error": "Unable to read sensor data"}

    if "mood" in include:
        if anima:
            result["mood"] = anima.feeling()
        else:
            result["mood"] = {"error": "Unable to determine mood"}

    # Record state for history if we have it
    if store and anima and readings:
        store.record_state(
            anima.warmth, anima.clarity, anima.stability, anima.presence,
            readings.to_dict()
        )

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def handle_post_message(arguments: dict) -> list[TextContent]:
    """
    Post a message to Lumen's message board.
    Consolidates: leave_message + leave_agent_note
    """
    message = arguments.get("message", "").strip()
    source = arguments.get("source", "agent")
    agent_name = arguments.get("agent_name", "agent")
    responds_to = arguments.get("responds_to")

    if not message:
        return [TextContent(type="text", text=json.dumps({
            "error": "message parameter required"
        }))]

    try:
        if source == "human":
            msg_id = add_user_message(message)
            # Track relationship with human
            if _growth:
                try:
                    _growth.record_interaction(
                        agent_id="human",
                        agent_name="human",
                        positive=True,
                        topic=message[:50] if len(message) > 10 else None
                    )
                except Exception:
                    pass  # Non-fatal
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "message_id": msg_id,
                "source": "human",
                "message": f"Message received: {message[:50]}..."
            }))]
        else:
            # Agent message - responds_to is passed to add_agent_message
            # Validate responds_to if provided
            validated_question_id = None
            if responds_to:
                from .messages import get_board, MESSAGE_TYPE_QUESTION
                board = get_board()
                board._load()
                # Check if question exists (exact match)
                question_found = any(
                    m.message_id == responds_to and m.msg_type == MESSAGE_TYPE_QUESTION
                    for m in board._messages
                )
                if not question_found:
                    # Try prefix matching
                    matching = [
                        m for m in board._messages
                        if m.msg_type == MESSAGE_TYPE_QUESTION
                        and m.message_id.startswith(responds_to)
                    ]
                    if len(matching) == 1:
                        validated_question_id = matching[0].message_id
                    elif len(matching) > 1:
                        # Multiple matches - use most recent
                        validated_question_id = matching[-1].message_id
                    else:
                        # No match - return helpful error
                        all_q_ids = [m.message_id for m in board._messages if m.msg_type == MESSAGE_TYPE_QUESTION]
                        return [TextContent(type="text", text=json.dumps({
                            "error": f"Question ID '{responds_to}' not found",
                            "hint": "Use the full question ID from get_questions()",
                            "recent_question_ids": all_q_ids[-5:] if all_q_ids else []
                        }))]
                else:
                    validated_question_id = responds_to
            
            msg = add_agent_message(message, agent_name, responds_to=validated_question_id or responds_to)
            # Track relationship with agent
            if _growth:
                try:
                    # Use agent_name as ID (agents have consistent names)
                    is_gift = responds_to is not None  # Answering a question is a gift
                    _growth.record_interaction(
                        agent_id=agent_name,
                        agent_name=agent_name,
                        positive=True,
                        topic=message[:50] if len(message) > 10 else None,
                        gift=is_gift
                    )
                except Exception:
                    pass  # Non-fatal
            result = {
                "success": True,
                "message_id": msg.message_id,
                "source": "agent",
                "agent_name": agent_name,
                "message": f"Note received from {agent_name}"
            }
            if responds_to:
                result["answered_question"] = validated_question_id or responds_to
                if validated_question_id and validated_question_id != responds_to:
                    result["note"] = f"Matched partial ID '{responds_to}' to full ID '{validated_question_id}'"
            return [TextContent(type="text", text=json.dumps(result))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": str(e)
        }))]


async def handle_query(arguments: dict) -> list[TextContent]:
    """
    Unified query across Lumen's knowledge systems.
    Consolidates: query_knowledge + query_memory + search_knowledge_graph + cognitive_query
    """
    text = arguments.get("text", "")
    query_type = arguments.get("type", "cognitive")

    if query_type == "learned":
        # Query Q&A learned knowledge
        from .knowledge import get_knowledge, get_insights
        kb = get_knowledge()
        category = arguments.get("category")
        limit = arguments.get("limit", 10)
        insights = get_insights(limit=limit, category=category)
        return [TextContent(type="text", text=json.dumps({
            "type": "learned",
            "total_insights": kb.count(),
            "insights": [{"id": i.insight_id, "text": i.text, "category": i.category} for i in insights]
        }, indent=2))]

    elif query_type == "memory":
        # Query associative memory
        memory = get_memory()
        conditions = arguments.get("conditions", {})
        temp = conditions.get("temperature") or arguments.get("temperature")
        light = conditions.get("light") or arguments.get("light")
        humidity = conditions.get("humidity") or arguments.get("humidity")

        if temp is None and light is None and humidity is None:
            # Use current sensor readings
            readings, _ = _get_readings_and_anima()
            if readings:
                temp = readings.temperature
                light = readings.light
                humidity = readings.humidity

        predictions = []
        if temp is not None or light is not None:
            predictions = anticipate_state(memory, temp, light, humidity)

        return [TextContent(type="text", text=json.dumps({
            "type": "memory",
            "query_conditions": {"temperature": temp, "light": light, "humidity": humidity},
            "predictions": predictions[:arguments.get("limit", 5)]
        }, indent=2))]

    elif query_type == "graph":
        # Search knowledge graph
        try:
            from .cognitive_inference import get_cognitive_inference
            cog = get_cognitive_inference()
            results = await cog.search_knowledge(text, limit=arguments.get("limit", 10))
            return [TextContent(type="text", text=json.dumps({
                "type": "graph",
                "query": text,
                "results": results
            }, indent=2))]
        except Exception as e:
            return [TextContent(type="text", text=json.dumps({"error": str(e)}))]

    else:  # cognitive (RAG)
        try:
            from .cognitive_inference import get_cognitive_inference
            cog = get_cognitive_inference()
            answer = await cog.query(text)
            return [TextContent(type="text", text=json.dumps({
                "type": "cognitive",
                "query": text,
                "answer": answer
            }, indent=2))]
        except Exception as e:
            return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def handle_cognitive_process(arguments: dict) -> list[TextContent]:
    """
    Perform cognitive operations.
    Consolidates: dialectic_synthesis + extract_knowledge + merge_insights
    """
    operation = arguments.get("operation")

    if not operation:
        return [TextContent(type="text", text=json.dumps({
            "error": "operation parameter required (synthesize, extract, or merge)"
        }))]

    try:
        from .cognitive_inference import get_cognitive_inference
        cog = get_cognitive_inference()

        if operation == "synthesize":
            thesis = arguments.get("thesis", "")
            antithesis = arguments.get("antithesis", "")
            context = arguments.get("context", "")
            result = await cog.dialectic_synthesis(thesis, antithesis, context)
            return [TextContent(type="text", text=json.dumps({
                "operation": "synthesize",
                "thesis": thesis,
                "antithesis": antithesis,
                "synthesis": result
            }, indent=2))]

        elif operation == "extract":
            text = arguments.get("text", "")
            domain = arguments.get("domain", "general")
            result = await cog.extract_knowledge(text, domain)
            return [TextContent(type="text", text=json.dumps({
                "operation": "extract",
                "domain": domain,
                "knowledge": result
            }, indent=2))]

        elif operation == "merge":
            insights = arguments.get("insights", [])
            result = await cog.merge_insights(insights)
            return [TextContent(type="text", text=json.dumps({
                "operation": "merge",
                "input_count": len(insights),
                "merged": result
            }, indent=2))]

        else:
            return [TextContent(type="text", text=json.dumps({
                "error": f"Unknown operation: {operation}",
                "valid_operations": ["synthesize", "extract", "merge"]
            }))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def handle_configure_voice(arguments: dict) -> list[TextContent]:
    """
    Get or configure Lumen's voice system.
    Consolidates: voice_status + set_voice_mode
    """
    action = arguments.get("action", "status")
    voice = _get_voice()

    if voice is None:
        return [TextContent(type="text", text=json.dumps({
            "error": "Voice system not available"
        }))]

    if action == "status":
        state = voice.state if hasattr(voice, 'state') else None
        return [TextContent(type="text", text=json.dumps({
            "action": "status",
            "available": True,
            "running": voice.is_running,
            "is_listening": state.is_listening if state else False,
            "is_speaking": state.is_speaking if state else False,
            "last_heard": state.last_heard.text if state and state.last_heard else None,
            "chattiness": voice.chattiness,
        }, indent=2))]

    elif action == "configure":
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
            "action": "configure",
            "success": True,
            "changes": changes
        }, indent=2))]

    else:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Unknown action: {action}",
            "valid_actions": ["status", "configure"]
        }))]


async def handle_manage_display(arguments: dict) -> list[TextContent]:
    """
    Control Lumen's display.
    Consolidates: switch_screen + show_face
    """
    global _screen_renderer

    action = arguments.get("action")
    if not action:
        return [TextContent(type="text", text=json.dumps({
            "error": "action parameter required (switch, face, next, previous)"
        }))]

    if action == "face":
        # Delegate to show_face handler
        return await handle_show_face({})

    if not _screen_renderer:
        return [TextContent(type="text", text=json.dumps({
            "error": "Screen renderer not initialized"
        }))]

    if action == "switch":
        screen = arguments.get("screen", "").lower()
        mode_map = {
            "face": ScreenMode.FACE,
            "sensors": ScreenMode.SENSORS,
            "identity": ScreenMode.IDENTITY,
            "diagnostics": ScreenMode.DIAGNOSTICS,
            "notepad": ScreenMode.NOTEPAD,
            "learning": ScreenMode.LEARNING,
            "messages": ScreenMode.MESSAGES,
            "questions": ScreenMode.QUESTIONS,
            "visitors": ScreenMode.VISITORS,
        }
        if screen in mode_map:
            _screen_renderer.set_mode(mode_map[screen])
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "action": "switch",
                "screen": screen
            }))]
        else:
            return [TextContent(type="text", text=json.dumps({
                "error": f"Invalid screen: {screen}",
                "valid_screens": list(mode_map.keys())
            }))]

    elif action == "next":
        _screen_renderer.next_mode()
        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "action": "next",
            "screen": _screen_renderer.get_mode().value
        }))]

    elif action == "previous":
        _screen_renderer.previous_mode()
        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "action": "previous",
            "screen": _screen_renderer.get_mode().value
        }))]

    else:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Unknown action: {action}",
            "valid_actions": ["switch", "face", "next", "previous"]
        }))]


# ============================================================
# Tool Handlers - Maps tool names to handler functions
# Deprecated tools removed 2026-02-04
# ============================================================
HANDLERS = {
    # Essential tools (5)
    "get_state": handle_get_state,
    "read_sensors": handle_read_sensors,
    "next_steps": handle_next_steps,
    "lumen_qa": handle_lumen_qa,
    "post_message": handle_post_message,
    # Standard tools (14)
    "get_lumen_context": handle_get_lumen_context,
    "manage_display": handle_manage_display,
    "configure_voice": handle_configure_voice,
    "say": handle_say,
    "diagnostics": handle_diagnostics,
    "unified_workflow": handle_unified_workflow,
    "get_calibration": handle_get_calibration,
    "get_self_knowledge": handle_get_self_knowledge,
    "get_growth": handle_get_growth,
    "get_trajectory": handle_get_trajectory,
    "git_pull": handle_git_pull,
    "system_service": handle_system_service,
    "system_power": handle_system_power,
    "primitive_feedback": handle_primitive_feedback,
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


def _json_type_to_python(json_type):
    """Convert JSON Schema type to Python type annotation."""
    from typing import Optional, Union

    if isinstance(json_type, list):
        # Handle union types like ["number", "string", "null"]
        non_null = [t for t in json_type if t != "null"]
        has_null = "null" in json_type

        if non_null:
            base_type = _json_type_to_python(non_null[0])
            if has_null:
                return Optional[base_type]
            return base_type
        return str

    type_map = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": Union[str, bool],
        "array": list,
        "object": dict,
    }
    return type_map.get(json_type, str)


def _create_tool_wrapper(handler, tool_name: str, tool_def=None):
    """
    Create a tool wrapper function with proper typed signature.

    Uses inspect.Signature to give the wrapper explicit typed parameters
    based on the tool's inputSchema. This allows FastMCP to introspect
    the function correctly without **kwargs issues.
    """
    import inspect
    from typing import Optional

    # Extract parameter info from tool definition's inputSchema
    param_info = []
    if tool_def and hasattr(tool_def, 'inputSchema'):
        schema = tool_def.inputSchema
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))

        for param_name, param_def in properties.items():
            param_type = _json_type_to_python(param_def.get("type", "string"))
            is_required = param_name in required
            param_info.append((param_name, param_type, is_required))

    # Build proper signature with typed parameters
    params = []
    for name, ptype, is_required in param_info:
        if is_required:
            param = inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                annotation=ptype,
            )
        else:
            param = inspect.Parameter(
                name,
                inspect.Parameter.KEYWORD_ONLY,
                default=None,
                annotation=Optional[ptype],
            )
        params.append(param)

    # Create the signature
    sig = inspect.Signature(params, return_annotation=dict)

    # Create wrapper that collects kwargs and passes to handler as dict
    async def typed_wrapper(**kwargs) -> dict:
        try:
            # Filter out None values for cleaner handler calls
            args = {k: v for k, v in kwargs.items() if v is not None}

            result = await handler(args)
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
            import traceback
            traceback.print_exc()
            return {"error": str(e)}

    # Set the signature for FastMCP introspection
    typed_wrapper.__signature__ = sig
    typed_wrapper.__name__ = tool_name
    typed_wrapper.__qualname__ = tool_name

    return typed_wrapper


def get_fastmcp() -> "FastMCP":
    """Get or create the FastMCP server instance."""
    global _fastmcp
    if _fastmcp is None and HAS_FASTMCP:
        _fastmcp = FastMCP(
            name="anima-mcp",
            host="0.0.0.0",  # Bind to all interfaces
            transport_security=TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=[
                    "127.0.0.1:*", "localhost:*", "[::1]:*",  # Localhost
                    "192.168.1.165:*", "192.168.1.151:*",  # Local network IPs
                    "0.0.0.0:*",  # Bind all
                ],
                allowed_origins=[
                    "http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*",
                    "http://192.168.1.165:*", "http://192.168.1.151:*",
                    "https://lumen-anima.ngrok.io",  # Only ngrok, with auth required
                    "null",  # For local file access
                ],
            ),
        )

        print(f"[FastMCP] Registering {len(HANDLERS)} tools...", file=sys.stderr, flush=True)

        # Register all tools dynamically from HANDLERS
        for tool_name, handler in HANDLERS.items():
            # Find the tool definition
            tool_def = next((t for t in TOOLS if t.name == tool_name), None)
            description = tool_def.description if tool_def else f"Tool: {tool_name}"

            # Create properly-captured wrapper with typed signature
            wrapper = _create_tool_wrapper(handler, tool_name, tool_def)

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
    global _store, _anima_id, _growth

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

        # Initialize growth system for learning, relationships, and goals
        try:
            _growth = get_growth_system(db_path=db_path)
            print(f"[Wake] ✓ Growth system initialized", file=sys.stderr, flush=True)
        except Exception as ge:
            print(f"[Wake] Growth system error (non-fatal): {ge}", file=sys.stderr, flush=True)
            _growth = None
    except Exception as e:
        print(f"[Wake] ❌ ERROR: Identity store failed!", file=sys.stderr, flush=True)
        print(f"[Wake] Error details: {e}", file=sys.stderr, flush=True)
        print(f"[Wake] Impact: Message board will NOT post, identity features unavailable", file=sys.stderr, flush=True)
        print(f"[Server] Display will work but without identity/messages", file=sys.stderr, flush=True)
        # Continue anyway - store might be None but server can still run (display can show face without identity)
        _store = None


def sleep():
    """Go to sleep. Call on server shutdown."""
    global _store, _unitares_bridge, _voice_instance

    # Close UnitaresBridge session (prevents "unclosed client session" warnings)
    if _unitares_bridge:
        try:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(_close_unitares_bridge())
                else:
                    loop.run_until_complete(_close_unitares_bridge())
            except RuntimeError:
                asyncio.run(_close_unitares_bridge())
        except Exception as e:
            try:
                print(f"[Sleep] Error closing UnitaresBridge: {e}", file=sys.stderr, flush=True)
            except (ValueError, OSError):
                pass

    # Stop voice system if running
    if _voice_instance:
        try:
            _voice_instance.stop()
            _voice_instance = None
        except Exception as e:
            try:
                print(f"[Sleep] Error stopping voice: {e}", file=sys.stderr, flush=True)
            except (ValueError, OSError):
                pass

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


def run_http_server(host: str, port: int):
    """Run MCP server over HTTP with Streamable HTTP transport.

    Endpoints:
    - /mcp/  : Streamable HTTP (recommended, modern MCP transport)
    - /sse   : Legacy SSE endpoint (backwards compatible)
    - /health: Health check

    NOTE: Server operates locally even without network connectivity.
    WiFi is only needed for remote MCP clients to connect.
    Lumen continues operating autonomously (display, LEDs, sensors, canvas) regardless of network status.
    """
    import asyncio

    async def _run_http_server_async():
        """Async inner function to run the HTTP server with uvicorn."""
        import uvicorn

        # Log that local operation continues regardless of network
        print("[Server] Starting HTTP server (Streamable HTTP + legacy SSE)", file=sys.stderr, flush=True)
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

        print("[Server] Creating FastMCP SSE application...", file=sys.stderr, flush=True)

        # Get the Starlette app from FastMCP (SSE transport)
        # This is the pattern governance-mcp-v1 uses successfully
        app = mcp.sse_app()

        # === Add Streamable HTTP transport (MCP 1.24.0+) ===
        # This is what governance uses and Claude Code prefers for type="http" configs
        HAS_STREAMABLE_HTTP = False
        _streamable_session_manager = None
        _streamable_running = False

        try:
            from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
            from starlette.routing import Mount, Route
            from starlette.responses import JSONResponse, PlainTextResponse

            # Create session manager for Streamable HTTP
            _streamable_session_manager = StreamableHTTPSessionManager(
                app=mcp._mcp_server,  # Access the underlying MCP server
                json_response=True,  # Use JSON responses (proper Streamable HTTP)
                stateless=True,  # Allow stateless for compatibility
            )

            HAS_STREAMABLE_HTTP = True
            print("[Server] Streamable HTTP transport available at /mcp/", file=sys.stderr, flush=True)

            # Create ASGI app for /mcp
            async def streamable_mcp_asgi(scope, receive, send):
                """ASGI app for Streamable HTTP MCP at /mcp/."""
                if scope.get("type") != "http":
                    return

                if not _streamable_running:
                    response = JSONResponse({
                        "status": "starting_up",
                        "message": "Streamable HTTP session manager not ready"
                    }, status_code=503)
                    await response(scope, receive, send)
                    return

                try:
                    await _streamable_session_manager.handle_request(scope, receive, send)
                except Exception as e:
                    print(f"[MCP] Error in Streamable HTTP handler: {e}", file=sys.stderr, flush=True)
                    import traceback
                    traceback.print_exc(file=sys.stderr)
                    try:
                        response = JSONResponse({"error": str(e)}, status_code=500)
                        await response(scope, receive, send)
                    except RuntimeError:
                        pass

            # Mount creates sub-application at /mcp/
            # Note: Clients should use /mcp/ (with trailing slash) to avoid 307 redirect
            app.routes.insert(0, Mount("/mcp", app=streamable_mcp_asgi))
            print("[Server] Registered /mcp/ endpoint for Streamable HTTP transport", file=sys.stderr, flush=True)

            # Health check endpoint for monitoring
            async def health_check(request):
                """Simple health check - returns 200 if server is running."""
                status = "ok" if SERVER_READY else "starting"
                return PlainTextResponse(f"{status}\n")

            app.routes.append(Route("/health", health_check, methods=["GET"]))
            print("[Server] Registered /health endpoint", file=sys.stderr, flush=True)

            # Simple REST API for tool calls (used by Control Center)
            async def rest_tool_call(request):
                """REST API for calling MCP tools directly.

                POST /v1/tools/call
                Body: {"name": "tool_name", "arguments": {...}}
                Returns: {"success": true, "result": ...} or {"success": false, "error": "..."}
                """
                try:
                    body = await request.json()
                    tool_name = body.get("name")
                    arguments = body.get("arguments", {})

                    if not tool_name:
                        return JSONResponse({"success": False, "error": "Missing 'name' field"}, status_code=400)

                    if tool_name not in HANDLERS:
                        return JSONResponse({"success": False, "error": f"Unknown tool: {tool_name}"}, status_code=404)

                    # Call the tool handler
                    handler = HANDLERS[tool_name]
                    result = await handler(arguments)

                    # Extract text from TextContent
                    if result and len(result) > 0:
                        text_result = result[0].text
                        try:
                            # Try to parse as JSON for cleaner response
                            parsed = json.loads(text_result)
                            return JSONResponse({"success": True, "result": parsed})
                        except json.JSONDecodeError:
                            return JSONResponse({"success": True, "result": text_result})

                    return JSONResponse({"success": True, "result": None})

                except Exception as e:
                    print(f"[REST API] Error: {e}", file=sys.stderr, flush=True)
                    return JSONResponse({"success": False, "error": str(e)}, status_code=500)

            app.routes.append(Route("/v1/tools/call", rest_tool_call, methods=["POST"]))
            print("[Server] Registered /v1/tools/call REST endpoint", file=sys.stderr, flush=True)

        except Exception as e:
            print(f"[Server] Streamable HTTP transport not available: {e}", file=sys.stderr, flush=True)

        # Start display loop before server runs
        start_display_loop()
        print("[Server] Display loop started", file=sys.stderr, flush=True)

        # Server warmup task - marks server ready after brief delay
        async def server_warmup_task():
            global SERVER_READY, SERVER_STARTUP_TIME
            SERVER_STARTUP_TIME = datetime.now()
            await asyncio.sleep(2.0)
            SERVER_READY = True
            print("[Server] Warmup complete - server ready", file=sys.stderr, flush=True)

        asyncio.create_task(server_warmup_task())

        print(f"MCP server running at http://{host}:{port}", file=sys.stderr, flush=True)
        if HAS_STREAMABLE_HTTP:
            print(f"  Streamable HTTP: http://{host}:{port}/mcp (recommended)", file=sys.stderr, flush=True)
        print(f"  SSE (legacy):    http://{host}:{port}/sse", file=sys.stderr, flush=True)

        # Start Streamable HTTP session manager as background task
        # Uses anyio task group pattern (same as governance-mcp)
        if HAS_STREAMABLE_HTTP and _streamable_session_manager is not None:
            import anyio

            async def start_streamable_http():
                nonlocal _streamable_running
                try:
                    async with anyio.create_task_group() as tg:
                        # Manually set internal state (same pattern as governance-mcp)
                        _streamable_session_manager._task_group = tg
                        _streamable_session_manager._has_started = True
                        _streamable_running = True
                        print("[Server] Streamable HTTP session manager running", file=sys.stderr, flush=True)
                        # Keep running until cancelled
                        await asyncio.Event().wait()
                except asyncio.CancelledError:
                    print("StreamableHTTP session manager shutting down", file=sys.stderr, flush=True)
                    _streamable_running = False
                except Exception as e:
                    print(f"[Server] Streamable HTTP error: {e}", file=sys.stderr, flush=True)
                    _streamable_running = False

            streamable_task = asyncio.create_task(start_streamable_http())

        try:
            # Run with uvicorn (matches governance-mcp-v1 pattern)
            config = uvicorn.Config(
                app,
                host=host,
                port=port,
                log_level="info",
                limit_concurrency=100,
                timeout_keep_alive=5,
            )
            server = uvicorn.Server(config)
            await server.serve()
        finally:
            if HAS_STREAMABLE_HTTP and 'streamable_task' in dir():
                streamable_task.cancel()
            stop_display_loop()
            sleep()

    # Handle graceful shutdown
    def shutdown_handler(sig, frame):
        global SERVER_SHUTTING_DOWN
        SERVER_SHUTTING_DOWN = True  # Signal handlers to reject new requests
        try:
            print("\nShutting down...", file=sys.stderr, flush=True)
        except (ValueError, OSError):
            pass
        try:
            stop_display_loop()
            sleep()
        except Exception:
            pass
        raise SystemExit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    # Run the async server
    asyncio.run(_run_http_server_async())
    return  # Early return - skip the old code below

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

        # Create ASGI wrapper for streamable HTTP
        async def streamable_mcp_asgi(scope, receive, send):
            """ASGI handler for Streamable HTTP MCP at /mcp."""
            # Check shutdown first - reject new requests during shutdown
            if SERVER_SHUTTING_DOWN:
                try:
                    response = JSONResponse({
                        "status": "shutting_down",
                        "message": "Server is shutting down"
                    }, status_code=503)
                    await response(scope, receive, send)
                except (RuntimeError, Exception):
                    pass  # Connection may already be closed during shutdown
                return

            if not _streamable_running:
                response = JSONResponse({
                    "status": "starting_up",
                    "message": "Streamable HTTP session manager not ready"
                }, status_code=503)
                await response(scope, receive, send)
                return

            if not SERVER_READY:
                response = JSONResponse({
                    "status": "warming_up",
                    "message": "Server is starting up"
                }, status_code=503)
                await response(scope, receive, send)
                return

            try:
                await _streamable_session_manager.handle_request(scope, receive, send)
            except Exception as e:
                if SERVER_SHUTTING_DOWN:
                    return  # Suppress errors during shutdown
                print(f"[MCP] Error in Streamable HTTP handler: {e}", file=sys.stderr, flush=True)
                try:
                    response = JSONResponse({"error": str(e)}, status_code=500)
                    await response(scope, receive, send)
                except RuntimeError:
                    pass  # Connection already closed

        # Mount streamable HTTP endpoint
        app.routes.append(Mount("/mcp", app=streamable_mcp_asgi))

    except Exception as e:
        print(f"[Server] Streamable HTTP transport not available: {e}", file=sys.stderr, flush=True)

    # === Async server runner ===
    async def run_server():
        """Run the server with proper async context for background tasks."""
        global SERVER_READY, SERVER_STARTUP_TIME
        nonlocal _streamable_running

        import uvicorn

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
            async def start_streamable_http():
                nonlocal _streamable_running
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

            asyncio.create_task(start_streamable_http())

        print(f"SSE server running at http://{host}:{port}")
        print(f"  SSE transport: http://{host}:{port}/sse")
        if HAS_STREAMABLE_HTTP:
            print(f"  Streamable HTTP: http://{host}:{port}/mcp")

        # Run with uvicorn using async server
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="warning",
            timeout_keep_alive=5,
            timeout_graceful_shutdown=10,
        )
        server = uvicorn.Server(config)

        try:
            await server.serve()
        finally:
            print("[Server] Stopping display loop...", file=sys.stderr, flush=True)
            stop_display_loop()

    # Handle graceful shutdown
    def shutdown_handler(sig, frame):
        global SERVER_SHUTTING_DOWN
        SERVER_SHUTTING_DOWN = True  # Signal handlers to reject new requests
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

    # Run the async server
    try:
        asyncio.run(run_server())
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

    # Prevent multiple instances using pidfile (but allow if stale)
    pidfile = Path("/tmp/anima-mcp.pid")
    if pidfile.exists():
        try:
            old_pid = int(pidfile.read_text().strip())
            # Check if process is still running
            os.kill(old_pid, 0)  # Signal 0 = check if alive
            # Process is running - check if it's actually serving
            import socket
            test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_sock.settimeout(0.5)
            try:
                result = test_sock.connect_ex(('127.0.0.1', args.port if args.http_server else 0))
                test_sock.close()
                if result == 0:
                    # Port is in use, likely another instance is serving
                    print(f"[Server] Another instance already running (PID {old_pid}) and port appears in use. Exiting.", file=sys.stderr)
                    print(f"[Server] To force restart: kill {old_pid} && rm {pidfile}", file=sys.stderr)
                    sys.exit(1)
            except Exception:
                pass  # Port check failed, assume ok to continue
        except (ProcessLookupError, ValueError):
            # Process not running or invalid pid - remove stale pidfile
            try:
                pidfile.unlink()
                print(f"[Server] Removed stale pidfile", file=sys.stderr, flush=True)
            except Exception:
                pass
        except PermissionError:
            # Process running as different user - try to continue anyway
            print(f"[Server] Warning: PID file exists but can't check process (different user). Continuing...", file=sys.stderr, flush=True)
        except Exception as e:
            # Any other error - remove pidfile and continue
            print(f"[Server] Error checking pidfile: {e}. Removing and continuing...", file=sys.stderr, flush=True)
            try:
                pidfile.unlink()
            except Exception:
                pass

    # Write our PID
    try:
        pidfile.write_text(str(os.getpid()))
    except Exception as e:
        print(f"[Server] Warning: Could not write pidfile: {e}", file=sys.stderr, flush=True)

    parser = argparse.ArgumentParser(description="Anima MCP Server")
    parser.add_argument("--http", "--sse", action="store_true", dest="http_server",
                        help="Run HTTP server (serves /mcp/ Streamable HTTP + /sse legacy)")
    parser.add_argument("--host", default="0.0.0.0", help="HTTP server host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8766, help="HTTP server port (default: 8766)")
    args = parser.parse_args()
    
    # Register cleanup for PID file on exit
    import atexit
    def cleanup_pidfile():
        try:
            if pidfile.exists():
                current_pid = pidfile.read_text().strip()
                if current_pid == str(os.getpid()):
                    pidfile.unlink()
        except Exception:
            pass
    atexit.register(cleanup_pidfile)

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
        if args.http_server:
            run_http_server(args.host, args.port)
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
        # Clean up pidfile
        try:
            pidfile.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()
