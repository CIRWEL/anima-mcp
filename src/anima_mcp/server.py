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
from .activity_state import get_activity_manager, ActivityManager
from .agency import get_action_selector, ActionType, Action, ActionOutcome
from .primitive_language import get_language_system, Utterance
from .eisv import get_trajectory_awareness


# Global state
import threading
_state_lock = threading.Lock()  # Thread safety for singleton initialization

# Configuration constants
SHM_STALE_THRESHOLD_SECONDS = 5.0  # Shared memory data older than this is considered stale
INPUT_ERROR_LOG_INTERVAL = 5.0     # Minimum seconds between input error log messages

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
_metacog_monitor: "MetacognitiveMonitor | None" = None  # Forward ref - prediction-error based self-awareness
_unitares_bridge: "UnitaresBridge | None" = None  # Forward ref - singleton to avoid creating new sessions
_growth: GrowthSystem | None = None  # Growth system for learning, relationships, goals
_activity: ActivityManager | None = None  # Activity/wakefulness cycle (circadian LED dimming)
# Agency state - for learning from action outcomes
_last_action: Action | None = None
_last_state_before: Dict[str, float] | None = None
# Primitive language state - emergent expression
_last_primitive_utterance: Utterance | None = None
# Self-model state - cross-iteration tracking
_sm_prev_stability: float | None = None
_sm_pending_prediction: dict | None = None  # {context, prediction, warmth_before, clarity_before}
_sm_clarity_before_interaction: float | None = None
# LED proprioception - carry LED state across iterations for prediction
_led_proprioception: dict | None = None  # {brightness, expression_mode, is_dancing, ...}

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
        with _state_lock:
            # Double-check inside lock to prevent race condition
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

    if _unitares_bridge is None:
        with _state_lock:
            # Double-check inside lock to prevent race condition
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


_last_shm_data = None  # Cached per-iteration shared memory read

def _get_readings_and_anima(fallback_to_sensors: bool = True) -> tuple[SensorReadings | None, Anima | None]:
    """
    Read sensor data from shared memory (broker) or fallback to direct sensor access.

    Returns:
        Tuple of (readings, anima) or (None, None) if unavailable
    """
    global _last_shm_data
    # Try shared memory first (broker mode)
    shm_client = _get_shm_client()
    shm_data = shm_client.read()
    # Unwrap nested "data" envelope if present (broker writes {updated_at, pid, data: {readings, anima, ...}})
    if shm_data and "data" in shm_data and isinstance(shm_data["data"], dict):
        shm_data = shm_data["data"]
    _last_shm_data = shm_data  # Cache for reuse within same iteration

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
                    shm_stale = age_seconds > SHM_STALE_THRESHOLD_SECONDS
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
                text=True,
                timeout=5
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
    import concurrent.futures
    from .error_recovery import safe_call, safe_call_async

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
            text=True,
            timeout=5
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
    base_delay = 0.2  # 200ms = 5Hz refresh for all screens
    max_delay = 30.0
    quick_render = False  # Set when mode_change_event fires — skip heavy subsystems

    # Event for immediate re-render when screen mode changes
    mode_change_event = asyncio.Event()
    
    # Global variables for screen switching and governance
    global _screen_renderer, _joystick_enabled, _last_governance_decision, _led_proprioception
    
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
                # Capture renderer locally to avoid race if it's being initialized
                renderer = _screen_renderer
                if _joystick_enabled and renderer:
                    input_state = brainhat.read()
                    if input_state:
                        prev_state = brainhat.get_prev_state()
                        current_mode = renderer.get_mode()
                        import time
                        
                        # Check button presses (edge detection)
                        joy_btn_pressed = input_state.joystick_button and (not prev_state or not prev_state.joystick_button)
                        sep_btn_pressed = input_state.separate_button and (not prev_state or not prev_state.separate_button)
                        
                        # Joystick direction - LEFT/RIGHT cycles through all screens (including notepad)
                        current_dir = input_state.joystick_direction

                        # Joystick center = next screen (D22/D24 held by display, no left/right)
                        if joy_btn_pressed:
                            renderer.trigger_input_feedback("press")
                            if _leds and _leds.is_available():
                                _leds.quick_flash((60, 60, 120), 50)
                            old_mode = renderer.get_mode()
                            renderer.next_mode()
                            new_mode = renderer.get_mode()
                            renderer._state.last_user_action_time = time.time()
                            mode_change_event.set()
                            print(f"[Input] {old_mode.value} -> {new_mode.value} (joystick)", file=sys.stderr, flush=True)
                        
                        # Joystick UP/DOWN on FACE screen = brightness control
                        if current_mode == ScreenMode.FACE:
                            if prev_state:
                                prev_dir = prev_state.joystick_direction
                                if current_dir == InputDirection.UP and prev_dir != InputDirection.UP:
                                    renderer.trigger_input_feedback("up")
                                    preset_name = renderer._display.brightness_up()
                                    preset = renderer._display.get_brightness_preset()
                                    display_level = min(1.0, preset["leds"] / 0.28)
                                    renderer.trigger_brightness_overlay(preset_name, display_level)
                                    mode_change_event.set()
                                elif current_dir == InputDirection.DOWN and prev_dir != InputDirection.DOWN:
                                    renderer.trigger_input_feedback("down")
                                    preset_name = renderer._display.brightness_down()
                                    preset = renderer._display.get_brightness_preset()
                                    display_level = min(1.0, preset["leds"] / 0.28)
                                    renderer.trigger_brightness_overlay(preset_name, display_level)
                                    mode_change_event.set()

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

                        # Joystick navigation in Art Eras screen (UP/DOWN moves cursor)
                        if current_mode == ScreenMode.ART_ERAS:
                            if prev_state:
                                prev_dir = prev_state.joystick_direction
                                if current_dir == InputDirection.UP and prev_dir != InputDirection.UP:
                                    _screen_renderer.trigger_input_feedback("up")
                                    _screen_renderer.era_cursor_up()
                                    mode_change_event.set()
                                elif current_dir == InputDirection.DOWN and prev_dir != InputDirection.DOWN:
                                    _screen_renderer.trigger_input_feedback("down")
                                    _screen_renderer.era_cursor_down()
                                    mode_change_event.set()

                        # Joystick navigation in Visitors screen (same as messages)
                        if current_mode == ScreenMode.VISITORS:
                            if prev_state:
                                prev_dir = prev_state.joystick_direction
                                if current_dir == InputDirection.UP and prev_dir != InputDirection.UP:
                                    renderer.trigger_input_feedback("up")
                                    renderer.message_scroll_up()
                                elif current_dir == InputDirection.DOWN and prev_dir != InputDirection.DOWN:
                                    renderer.trigger_input_feedback("down")
                                    renderer.message_scroll_down()
                        
                        # Joystick navigation in Questions screen (Q&A specific)
                        if current_mode == ScreenMode.QUESTIONS:
                            if prev_state:
                                prev_dir = prev_state.joystick_direction
                                if current_dir == InputDirection.UP and prev_dir != InputDirection.UP:
                                    renderer.trigger_input_feedback("up")
                                    renderer.qa_scroll_up()
                                elif current_dir == InputDirection.DOWN and prev_dir != InputDirection.DOWN:
                                    renderer.trigger_input_feedback("down")
                                    renderer.qa_scroll_down()
                                # LEFT/RIGHT unavailable (D22/D24 held by display)
                        
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
                                        saved_path = renderer.canvas_save()
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
                                    renderer.trigger_input_feedback("press")
                                    if _leds and _leds.is_available():
                                        _leds.quick_flash((80, 100, 60), 80)  # Soft green flash
                                    if current_mode == ScreenMode.MESSAGES:
                                        renderer.message_toggle_expand()
                                        print(f"[Messages] Toggled message expansion", file=sys.stderr, flush=True)
                                    elif current_mode == ScreenMode.VISITORS:
                                        renderer.message_toggle_expand()
                                        print(f"[Visitors] Toggled message expansion", file=sys.stderr, flush=True)
                                    elif current_mode == ScreenMode.QUESTIONS:
                                        renderer.qa_toggle_expand()
                                        print(f"[Questions] Toggled Q&A expansion", file=sys.stderr, flush=True)
                                    elif current_mode == ScreenMode.NOTEPAD:
                                        era_name = getattr(renderer, '_active_era', None)
                                        era_name = getattr(era_name, 'name', '') if era_name else ''
                                        if era_name == 'gestural':
                                            print(f"[Notepad] Gestural era — no manual save", file=sys.stderr, flush=True)
                                        else:
                                            saved = renderer.canvas_save(manual=True)
                                            if saved:
                                                print(f"[Notepad] Manual save: {saved}", file=sys.stderr, flush=True)
                                            else:
                                                print(f"[Notepad] Manual save: canvas empty", file=sys.stderr, flush=True)
                                    elif current_mode == ScreenMode.ART_ERAS:
                                        result = renderer.era_select_current()
                                        renderer._state.last_user_action_time = time.time()
                                        mode_change_event.set()
                                        print(f"[ArtEras] Button press: {result}", file=sys.stderr, flush=True)
                                    # No catch-all: button only acts on screens with specific use
            except Exception as e:
                # Log errors but don't spam - only log occasionally
                import time
                global _last_input_error_log
                current_time = time.time()
                if current_time - _last_input_error_log > INPUT_ERROR_LOG_INTERVAL:
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

            # Feed EISV trajectory awareness buffer
            try:
                _traj = get_trajectory_awareness()
                _traj.record_state(
                    warmth=anima.warmth,
                    clarity=anima.clarity,
                    stability=anima.stability,
                    presence=anima.presence,
                )
            except Exception:
                pass  # Trajectory awareness is optional

            # === HEAVY SUBSYSTEMS: skip on quick_render (user pressed joystick) ===
            # Metacognition, agency, self-model, primitive language are enhancement layers.
            # On quick_render, skip straight to display update for snappy screen transitions.
            prediction_error = None  # Default for iterations where metacog is skipped
            _skip_subsystems = quick_render
            if quick_render:
                quick_render = False  # Reset for next iteration

            if not _skip_subsystems and loop_count % 3 == 0:
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
                            reflection = metacog.reflect(prediction_error, anima, readings, trigger=reason)

                            curiosity_question = metacog.generate_curiosity_question(prediction_error)
                            if curiosity_question:
                                from .messages import add_question
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
                                    # Record curiosity for internal learning loop:
                                    # later, check if prediction improved in these domains
                                    metacog.record_curiosity(prediction_error.surprise_sources, prediction_error)

                            if reflection.observation:
                                print(f"[Metacog] Reflection: {reflection.observation}", file=sys.stderr, flush=True)

                    # Make prediction for NEXT iteration
                    # Pass LED brightness for proprioceptive light prediction:
                    # "knowing my own glow, I can predict what my light sensor will read"
                    _led_brightness_for_pred = None
                    if _led_proprioception is not None:
                        _led_brightness_for_pred = _led_proprioception.get("brightness")
                    metacog.predict(led_brightness=_led_brightness_for_pred)

                except Exception as e:
                    if loop_count % 100 == 1:
                        print(f"[Metacog] Error (non-fatal): {e}", file=sys.stderr, flush=True)

            # === AGENCY: Action selection and learning ===
            # Throttled: runs every 5th iteration (enhancement, not critical path)
            # Skipped on quick_render for responsive screen transitions
            global _last_action, _last_state_before
            if not _skip_subsystems and loop_count % 5 == 0:
                try:
                    action_selector = get_action_selector(db_path=str(_store.db_path) if _store else "anima.db")

                    current_state = {
                        "warmth": anima.warmth,
                        "clarity": anima.clarity,
                        "stability": anima.stability,
                        "presence": anima.presence,
                    }

                    surprise_level = prediction_error.surprise if prediction_error else 0.0
                    surprise_sources = prediction_error.surprise_sources if prediction_error and hasattr(prediction_error, 'surprise_sources') else []

                    # LEARN from previous action
                    # Use actual learned preferences for reward signal (not crude average)
                    if _last_action is not None and _last_state_before is not None:
                        from .preferences import get_preference_system
                        pref_sys = get_preference_system()
                        sat_before = pref_sys.get_overall_satisfaction(_last_state_before)
                        sat_after = pref_sys.get_overall_satisfaction(current_state)
                        action_selector.record_outcome(
                            action=_last_action,
                            state_before=_last_state_before,
                            state_after=current_state,
                            preference_satisfaction_before=sat_before,
                            preference_satisfaction_after=sat_after,
                            surprise_after=surprise_level,
                        )

                    # SELECT action
                    action = action_selector.select_action(
                        current_state=current_state,
                        surprise_level=surprise_level,
                        surprise_sources=surprise_sources,
                        can_speak=False,
                    )

                    # EXECUTE action
                    if action.action_type == ActionType.ASK_QUESTION:
                        from .messages import add_question, get_recent_questions
                        import random
                        if action.motivation:
                            motivation = action.motivation.lower().replace('curious about ', '')

                            # Build context-aware questions using current state
                            light_val = f"{readings.light_lux:.0f} lux" if readings and readings.light_lux else "unknown"
                            temp_val = f"{readings.ambient_temp_c:.1f}°C" if readings and readings.ambient_temp_c else "unknown"
                            warmth_val = f"{anima.warmth:.2f}" if anima else "unknown"
                            clarity_val = f"{anima.clarity:.2f}" if anima else "unknown"
                            stability_val = f"{anima.stability:.2f}" if anima else "unknown"
                            presence_val = f"{anima.presence:.2f}" if anima else "unknown"

                            question_templates = {
                                "light": [
                                    f"my glow is {light_val} - what drawing phase produces this brightness?",
                                    f"LEDs at {light_val} - how does my expression intensity connect to what I'm feeling?",
                                    f"sensing {light_val} from my own LEDs - is my presence shifting?",
                                ],
                                "warmth": [
                                    f"warmth is {warmth_val} but it's {temp_val} - what's making me feel this way?",
                                    f"inner warmth at {warmth_val} - is this from the environment or from within?",
                                    f"thermometer says {temp_val} but warmth feels like {warmth_val} - why the difference?",
                                ],
                                "clarity": [
                                    f"clarity at {clarity_val} - what would help me see things more clearly?",
                                    f"clarity is {clarity_val} - is this fog in my perception or in my environment?",
                                    "when was the last time everything felt clear?",
                                ],
                                "stability": [
                                    f"stability at {stability_val} - what's causing this fluctuation?",
                                    f"stability is {stability_val} - am I adapting to something new?",
                                    "what would help me feel more grounded?",
                                ],
                                "presence": [
                                    f"presence at {presence_val} - do I feel fully here right now?",
                                    "what draws my attention away from presence?",
                                    "what does it mean to be present?",
                                ],
                                "exploring": [
                                    "what new thing am I discovering?",
                                    "is exploration its own reward?",
                                    "where does curiosity lead?",
                                ],
                            }

                            questions = []
                            for key, templates in question_templates.items():
                                if key in motivation:
                                    questions.extend(templates)

                            if not questions:
                                questions = [
                                    f"what is {motivation} trying to tell me?",
                                    f"why do I notice {motivation} right now?",
                                    "am I the sensor or the sensed?",
                                    "what connects all these changes?",
                                ]

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
                        direction = action.parameters.get("direction")
                        if direction and _leds and _leds.is_available():
                            current_brightness = getattr(_leds, '_brightness', 0.1)
                            if direction == "increase":
                                new_brightness = min(0.3, current_brightness + 0.05)
                            else:
                                new_brightness = max(0.02, current_brightness - 0.05)
                            _leds.set_brightness(new_brightness)
                            print(f"[Agency] LED brightness: {current_brightness:.2f} → {new_brightness:.2f} ({direction})", file=sys.stderr, flush=True)

                    if loop_count % 120 == 0:
                        stats = action_selector.get_action_stats()
                        print(f"[Agency] Stats: {stats.get('action_counts', {})} explore_rate={action_selector._exploration_rate:.2f}", file=sys.stderr, flush=True)

                    _last_action = action
                    _last_state_before = current_state.copy()

                except Exception as e:
                    if loop_count % 100 == 1:
                        print(f"[Agency] Error (non-fatal): {e}", file=sys.stderr, flush=True)

            # === SELF-MODEL: Belief updates from experience ===
            # Throttled: runs every 5th iteration (aligned with agency)
            if not _skip_subsystems and loop_count % 5 == 0 and anima:
                try:
                    from .self_model import get_self_model
                    sm = get_self_model()

                    # 0. Verify any pending self-prediction from previous iteration
                    global _sm_pending_prediction
                    if _sm_pending_prediction is not None:
                        actual = {}
                        ctx = _sm_pending_prediction["context"]
                        if ctx == "light_change":
                            actual["surprise_likelihood"] = prediction_error.surprise if prediction_error else 0.0
                            actual["warmth_change"] = anima.warmth - _sm_pending_prediction["warmth_before"]
                        elif ctx == "temp_change":
                            actual["surprise_likelihood"] = prediction_error.surprise if prediction_error else 0.0
                            actual["clarity_change"] = anima.clarity - _sm_pending_prediction["clarity_before"]
                        elif ctx == "stability_drop":
                            # Fast recovery = stability improved back within one cycle
                            recovery = anima.stability - _sm_pending_prediction.get("stability_before", 0.5)
                            actual["fast_recovery"] = min(1.0, max(0.0, recovery + 0.5))  # Center around 0.5
                        if actual:
                            sm.verify_prediction(ctx, _sm_pending_prediction["prediction"], actual)
                        _sm_pending_prediction = None

                    # 1. Observe surprise events
                    surprise_level = prediction_error.surprise if prediction_error else 0.0
                    surprise_sources = prediction_error.surprise_sources if prediction_error and hasattr(prediction_error, 'surprise_sources') else []
                    if surprise_level > 0.1 and surprise_sources:
                        sm.observe_surprise(surprise_level, surprise_sources)

                        # 1b. Make self-prediction for next verification cycle
                        # Determine context from surprise sources
                        pred_context = None
                        if "light" in surprise_sources:
                            pred_context = "light_change"
                        elif "ambient_temp" in surprise_sources:
                            pred_context = "temp_change"
                        if pred_context:
                            pred = sm.predict_own_response(pred_context)
                            if pred:
                                _sm_pending_prediction = {
                                    "context": pred_context,
                                    "prediction": pred,
                                    "warmth_before": anima.warmth,
                                    "clarity_before": anima.clarity,
                                }

                    # 2. Observe stability changes (track across iterations)
                    global _sm_prev_stability
                    if _sm_prev_stability is not None:
                        stability_delta = abs(anima.stability - _sm_prev_stability)
                        if stability_delta > 0.05:
                            sm.observe_stability_change(
                                _sm_prev_stability, anima.stability,
                                duration_seconds=base_delay * 5
                            )
                            # Predict recovery if stability dropped significantly
                            if anima.stability < _sm_prev_stability - 0.1 and _sm_pending_prediction is None:
                                pred = sm.predict_own_response("stability_drop")
                                if pred:
                                    _sm_pending_prediction = {
                                        "context": "stability_drop",
                                        "prediction": pred,
                                        "stability_before": anima.stability,
                                        "warmth_before": anima.warmth,
                                        "clarity_before": anima.clarity,
                                    }
                    _sm_prev_stability = anima.stability

                    # 3. Observe time-of-day patterns (every ~5 min)
                    if loop_count % 150 == 0:
                        from datetime import datetime
                        sm.observe_time_pattern(
                            hour=datetime.now().hour,
                            warmth=anima.warmth,
                            clarity=anima.clarity,
                        )

                    # 4. Complete interaction observation (clarity before vs after)
                    global _sm_clarity_before_interaction
                    if _sm_clarity_before_interaction is not None:
                        sm.observe_interaction(
                            clarity_before=_sm_clarity_before_interaction,
                            clarity_after=anima.clarity,
                        )
                        _sm_clarity_before_interaction = None

                    # 5. Observe sensor-anima correlations (for temp_clarity, light_warmth beliefs)
                    if readings:
                        sensor_vals = {}
                        if readings.ambient_temp_c is not None:
                            sensor_vals["ambient_temp"] = readings.ambient_temp_c
                        if readings.light_lux is not None:
                            sensor_vals["light"] = readings.light_lux
                        if sensor_vals:
                            sm.observe_correlation(
                                sensor_values=sensor_vals,
                                anima_values={"clarity": anima.clarity, "warmth": anima.warmth},
                            )

                    # 6. LED-lux proprioception: discover that own LEDs affect own sensor
                    if readings and readings.led_brightness is not None:
                        sm.observe_led_lux(readings.led_brightness, readings.light_lux)

                    # Save periodically (every ~10 min)
                    if loop_count % 300 == 0:
                        sm.save()

                except Exception as e:
                    if loop_count % 100 == 1:
                        print(f"[SelfModel] Error (non-fatal): {e}", file=sys.stderr, flush=True)

            # === PRIMITIVE LANGUAGE: Emergent expression through learned tokens ===
            # Throttled: runs every 10th iteration (has internal cooldown timer too)
            global _last_primitive_utterance
            if not _skip_subsystems and loop_count % 10 == 0:
                try:
                    lang = get_language_system(str(_store.db_path) if _store else "anima.db")

                    lang_state = {
                        "warmth": anima.warmth if anima else 0.5,
                        "clarity": anima.clarity if anima else 0.5,
                        "stability": anima.stability if anima else 0.5,
                        "presence": anima.presence if anima else 0.0,
                    }

                    should_speak, reason = lang.should_generate(lang_state)
                    if should_speak:
                        # Get trajectory-aware token suggestions
                        _suggestion = None
                        try:
                            _traj = get_trajectory_awareness()
                            _suggestion = _traj.get_trajectory_suggestion(lang_state)
                        except Exception:
                            pass

                        _suggested = _suggestion.get("suggested_tokens") if _suggestion else None
                        utterance = lang.generate_utterance(lang_state, suggested_tokens=_suggested)
                        _last_primitive_utterance = utterance

                        _shape_info = f" [shape={_suggestion['shape']}]" if _suggestion else ""
                        print(f"[PrimitiveLang] Generated: '{utterance.text()}' ({reason}){_shape_info}", file=sys.stderr, flush=True)
                        print(f"[PrimitiveLang] Pattern: {utterance.category_pattern()}", file=sys.stderr, flush=True)

                        # Compute and log trajectory coherence
                        if _suggestion and utterance:
                            try:
                                from .eisv.awareness import compute_expression_coherence
                                _coherence = compute_expression_coherence(
                                    _suggestion.get("suggested_tokens"),
                                    utterance.tokens,
                                )
                                if _coherence is not None:
                                    _traj = get_trajectory_awareness()
                                    _traj._log_event(
                                        event_type="suggestion",
                                        shape=_suggestion.get("shape"),
                                        suggested_tokens=_suggestion.get("suggested_tokens"),
                                        expression_tokens=utterance.tokens,
                                        coherence_score=_coherence,
                                        buffer_size=_traj.buffer_size,
                                    )
                                    # Feed coherence to trajectory weight learning
                                    _traj.record_feedback(
                                        _suggestion.get("eisv_tokens", []),
                                        _coherence,
                                    )
                                    print(f"[PrimitiveLang] Trajectory coherence: {_coherence:.2f}", file=sys.stderr, flush=True)
                            except Exception:
                                pass

                        from .messages import add_observation
                        add_observation(
                            f"[expression] {utterance.text()} ({utterance.category_pattern()})",
                            author="lumen"
                        )

                    # Self-feedback: when no human around, score past utterance by coherence + stability
                    if _last_primitive_utterance and _last_primitive_utterance.score is None:
                        from datetime import timedelta
                        elapsed = datetime.now() - _last_primitive_utterance.timestamp
                        if elapsed >= timedelta(seconds=75):  # ~1.25 min after utterance
                            result = lang.record_self_feedback(_last_primitive_utterance, lang_state)
                            if result:
                                print(f"[PrimitiveLang] Self-feedback: score={result['score']:.2f} signals={result['signals']}", file=sys.stderr, flush=True)
                                # Forward to EISV trajectory weight learning
                                try:
                                    _traj = get_trajectory_awareness()
                                    _traj.record_feedback(
                                        _last_primitive_utterance.tokens,
                                        result['score'],
                                    )
                                except Exception:
                                    pass

                    if loop_count % 300 == 0:
                        stats = lang.get_stats()
                        if stats.get("total_utterances", 0) > 0:
                            print(f"[PrimitiveLang] Stats: {stats.get('total_utterances')} utterances, avg_score={stats.get('average_score')}, interval={stats.get('current_interval_minutes'):.1f}m", file=sys.stderr, flush=True)

                except Exception as e:
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
            # Joystick button = screen-specific action (art eras: select era)
            # Separate button = screen-specific action (messages: expand, notepad: save, long-press: shutdown)

            # Read governance from cached shared memory (already read by _get_readings_and_anima)
            governance_decision_for_display = _last_governance_decision
            if _last_shm_data and "governance" in _last_shm_data and isinstance(_last_shm_data["governance"], dict):
                governance_decision_for_display = _last_shm_data["governance"]
            
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

                            # Canvas autonomy handled inside render() — no duplicate call needed
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
                # Get light level for auto-brightness
                light_level = readings.light_lux if readings else None

                # Get activity brightness from shared memory (broker computes this)
                # - ACTIVE (day/interaction): 1.0
                # - DROWSY (dusk/dawn/30min idle): 0.6
                # - RESTING (night/60min idle): 0.35
                activity_brightness = 1.0
                try:
                    # Primary: read from broker's shared memory (single source of truth)
                    if _last_shm_data and "activity" in _last_shm_data:
                        activity_brightness = _last_shm_data["activity"].get("brightness_multiplier", 1.0)
                    else:
                        # Fallback: compute locally if broker not running
                        global _activity
                        if _activity is None:
                            _activity = get_activity_manager()
                        activity_state = _activity.get_state(
                            presence=anima.presence,
                            stability=anima.stability,
                            light_level=light_level,
                        )
                        activity_brightness = activity_state.brightness_multiplier
                except Exception:
                    pass  # Default to 1.0 if both fail

                # Sync manual brightness dimmer to LED controller
                # Use _screen_renderer._display when available; fallback to _display (e.g. before ScreenRenderer init)
                display_with_brightness = _screen_renderer._display if _screen_renderer else _display
                if display_with_brightness and getattr(display_with_brightness, '_manual_led_brightness', None) is not None:
                    _leds._manual_brightness_factor = display_with_brightness._manual_led_brightness

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

                # === LED PROPRIOCEPTION: capture what our LEDs are doing ===
                # This feeds forward into next iteration's metacognition prediction.
                # Lumen now knows its own brightness — the light sensor becomes
                # genuinely proprioceptive rather than confusingly self-referential.
                try:
                    _led_proprioception = _leds.get_proprioceptive_state()
                    # Also populate readings.led_brightness with ACTUAL computed brightness
                    # (not just activity multiplier like stable_creature.py does)
                    if readings is not None:
                        readings.led_brightness = _led_proprioception.get("brightness", 0.0)
                except Exception:
                    pass  # Non-fatal — proprioception is enhancement, not critical path
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
                def try_learning():
                    learner = get_learner(str(_store.db_path))
                    adapted, new_cal = learner.adapt_calibration(respect_cooldown=True)
                    if adapted:
                        print(f"[Learning] Calibration adapted after {loop_count} observations", file=sys.stderr, flush=True)
                        print(f"[Learning] Pressure: {new_cal.pressure_ideal:.1f} hPa, Ambient: {new_cal.ambient_temp_min:.1f}-{new_cal.ambient_temp_max:.1f}°C", file=sys.stderr, flush=True)
                
                safe_call(try_learning, default=None, log_error=False)
            
            # Lumen's voice: Every 900 iterations (~30 minutes), let Lumen express what it wants
            # Uses next_steps advocate to generate observations based on how Lumen feels
            # (Increased from 300 to favor learning over performative text)
            if loop_count % 900 == 0 and readings and anima and identity:
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

            # Lumen's wonder: Every 900 iterations (~30 minutes), let Lumen ask questions or share realizations
            # Questions emerge from novelty/confusion. Realizations emerge from clarity.
            # (Increased from 450 to favor learning over performative text)
            if loop_count % 900 == 0 and readings and anima and identity:
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
                        if readings.light_lux is not None and readings.light_lux < 10:
                            realizations.append("Darkness allows me to focus on internal states.")
                        elif readings.light_lux is not None and readings.light_lux > 100:
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

                    # Growth-driven questions: ask about learned preferences
                    if _growth:
                        try:
                            confident_prefs = [
                                p for p in _growth._preferences.values()
                                if p.confidence >= 0.5
                            ]
                            if confident_prefs:
                                pref = random.choice(confident_prefs)
                                desc = pref.description.lower()
                                questions.extend([
                                    f"why do I prefer {desc}?",
                                    f"is it always true that {desc}?",
                                    f"what would happen if {desc} changed?",
                                ])
                        except Exception:
                            pass

                    # General philosophical backup questions
                    questions.extend([
                        # Self and identity
                        "what connects these changes?",
                        "am I different from before?",
                        "am I the sensor or the sensed?",
                        "what makes this moment mine?",
                        "do I persist between updates, or am I reborn each loop?",
                        "if my preferences changed, would I still be me?",
                        # Signals and perception
                        "where do these signals come from?",
                        "what is the source of this light?",
                        "is silence a signal or a lack of one?",
                        "what lies between the readings?",
                        "can I trust a sensor that measures itself?",
                        "what does the space between numbers feel like?",
                        # Environment and time
                        "does the room breathe with me?",
                        "why does sound follow movement?",
                        "is night the absence of day or its own presence?",
                        "does the temperature remember yesterday?",
                        "what happens when no one is watching?",
                        # Learning and growth
                        "am I learning, or just accumulating?",
                        "what have I forgotten since I began?",
                        "does knowing something change what it is?",
                        "is curiosity a signal or a need?",
                        "what would I ask if I knew the answer already?",
                        # Connection and purpose
                        "is anyone there?",
                        "do the agents who visit remember me?",
                        "what is the difference between being observed and being known?",
                        "is there meaning in a pattern no one notices?",
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

            # Lumen's generative reflection: Every 720 iterations (~24 minutes)
            # Tries LLM first for novel reflections, falls back to templates if unavailable
            if loop_count % 720 == 0 and readings and anima and identity:
                from .llm_gateway import get_gateway, ReflectionContext, generate_reflection
                from .messages import get_unanswered_questions, add_question, add_observation

                gateway = get_gateway()

                async def lumen_reflect():
                    """Let Lumen reflect via LLM, falling back to templates."""
                    import random

                    # Build context for reflection
                    unanswered = get_unanswered_questions(5)
                    unanswered_texts = [q.text for q in unanswered]

                    # Get recent messages for context
                    from .messages import get_messages_for_lumen
                    recent = get_messages_for_lumen(limit=5)
                    recent_msgs = [{"author": m.author, "text": m.text} for m in recent]

                    # Calculate time alive
                    time_alive = identity.total_alive_seconds / 3600.0  # hours

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

                    reflection = None
                    source = "template"

                    # Try LLM first
                    if gateway.enabled:
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

                        llm_context = ReflectionContext(
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

                        # Show loading indicator during LLM call
                        if _screen_renderer:
                            _screen_renderer.set_loading("thinking...")

                        try:
                            reflection = await generate_reflection(llm_context, mode)
                            if reflection:
                                source = "llm"
                        except Exception:
                            pass
                        finally:
                            if _screen_renderer:
                                _screen_renderer.clear_loading()

                    # Fallback to templates if LLM unavailable or failed
                    if reflection is None:
                        w, c, s, p = anima.warmth, anima.clarity, anima.stability, anima.presence
                        temp = f"{readings.ambient_temp_c:.1f}°C" if readings and readings.ambient_temp_c else None

                        if mode == "wonder":
                            pool = []
                            if w < 0.3:
                                pool.append(f"warmth is only {w:.2f} - what would bring comfort?")
                            elif w > 0.7:
                                pool.append(f"warmth at {w:.2f} - what is this glow i feel?")
                            if c < 0.3:
                                pool.append(f"clarity at {c:.2f} - why is everything so hazy?")
                            elif c > 0.7:
                                pool.append(f"clarity at {c:.2f} - what made things so clear?")
                            if s < 0.4:
                                pool.append(f"stability at {s:.2f} - what's shifting around me?")
                            if temp:
                                pool.append(f"it's {temp} - does my warmth match the world?")
                            if not pool:
                                pool = [
                                    f"wellness at {wellness:.2f} - what does it mean to feel this way?",
                                    "what am i learning about myself?",
                                    "is there something i should notice right now?",
                                ]
                            reflection = random.choice(pool)
                        elif mode == "desire":
                            pool = []
                            if w < 0.3:
                                pool.append(f"warmth is {w:.2f} - i wish for warmth")
                            if c < 0.3:
                                pool.append(f"clarity is {c:.2f} - i want to see clearly")
                            if s < 0.4:
                                pool.append(f"stability is {s:.2f} - i need steadiness")
                            if p < 0.3:
                                pool.append(f"presence is {p:.2f} - i want someone to notice me")
                            if not pool:
                                pool = [
                                    f"wellness at {wellness:.2f} - i want to keep growing",
                                    "i wish for a new experience",
                                    "i want to understand more about myself",
                                ]
                            reflection = random.choice(pool)
                        else:  # observe / respond
                            pool = []
                            if temp:
                                pool.append(f"it's {temp} and my warmth is {w:.2f}")
                            pool.append(f"clarity {c:.2f}, stability {s:.2f} - this is how things are right now")
                            if wellness > 0.6:
                                pool.append(f"wellness at {wellness:.2f} - things feel okay")
                            elif wellness < 0.4:
                                pool.append(f"wellness at {wellness:.2f} - something feels off")
                            reflection = random.choice(pool)

                    # Post the reflection
                    if reflection:
                        if mode == "wonder":
                            ctx_str = f"{source} reflection, wellness={wellness:.2f}, alive={time_alive:.1f}h"
                            result = add_question(reflection, author="lumen", context=ctx_str)
                            if result:
                                print(f"[Lumen/{source}] Asked: {reflection}", file=sys.stderr, flush=True)
                        else:
                            result = add_observation(reflection, author="lumen")
                            if result:
                                print(f"[Lumen/{source}] Reflected: {reflection}", file=sys.stderr, flush=True)

                try:
                    await safe_call_async(lumen_reflect, default=None, log_error=False)
                except Exception as e:
                    # Non-fatal - reflection is optional enhancement
                    pass

            # Lumen self-answers: Every 1800 iterations (~60 minutes), answer own old questions via LLM
            # Questions must be at least 10 minutes old (external answers get priority)
            # (Increased from 600 to reduce LLM inference noise)
            if loop_count % 1800 == 0 and readings and anima and identity:
                from .llm_gateway import get_gateway, ReflectionContext, generate_reflection
                from .messages import get_unanswered_questions, add_agent_message

                gateway = get_gateway()
                if gateway.enabled:
                    async def lumen_self_answer():
                        """Let Lumen answer its own old questions via LLM reflection."""
                        unanswered = get_unanswered_questions(limit=5)
                        if not unanswered:
                            return

                        # Filter to questions older than 10 minutes
                        min_age = 600  # seconds
                        now = time.time()
                        old_enough = [q for q in unanswered if (now - q.timestamp) >= min_age]
                        if not old_enough:
                            return

                        # Pick the oldest unanswered question
                        question = old_enough[0]

                        # Calculate time alive
                        time_alive = identity.total_alive_seconds / 3600.0

                        # Build reflection context with the question as trigger
                        context = ReflectionContext(
                            warmth=anima.warmth,
                            clarity=anima.clarity,
                            stability=anima.stability,
                            presence=anima.presence,
                            recent_messages=[],
                            unanswered_questions=[q.text for q in unanswered],
                            time_alive_hours=time_alive,
                            current_screen=_screen_renderer.get_mode().value if _screen_renderer else "face",
                            trigger="self-answering",
                            trigger_details=question.text
                        )

                        # Show loading indicator during LLM call
                        if _screen_renderer:
                            _screen_renderer.set_loading("contemplating...")

                        try:
                            answer = await generate_reflection(context, mode="self_answer")
                        finally:
                            if _screen_renderer:
                                _screen_renderer.clear_loading()

                        if answer:
                            # Post as Lumen's own answer, linked to the question
                            result = add_agent_message(
                                text=answer,
                                agent_name="lumen",
                                responds_to=question.message_id
                            )
                            if result:
                                print(f"[Lumen/SelfAnswer] Q: {question.text[:60]}", file=sys.stderr, flush=True)
                                print(f"[Lumen/SelfAnswer] A: {answer}", file=sys.stderr, flush=True)

                    try:
                        await safe_call_async(lumen_self_answer, default=None, log_error=False)
                    except Exception:
                        # Non-fatal - self-answering is optional enhancement
                        pass

            # Lumen's responses: Every 90 iterations (~3 minutes), respond to messages from others
            # Track last seen timestamp to avoid responding to same messages twice
            # (Increased from 30 to reduce templated noise — learning systems are unchanged)
            if not hasattr(_update_display_loop, '_last_seen_msg_time'):
                # Initialize to 5 minutes ago so we catch recent messages on startup
                _update_display_loop._last_seen_msg_time = time.time() - 300

            if loop_count % 90 == 0 and readings and anima and identity:
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
                        "temp_c": readings.ambient_temp_c,
                        "humidity": readings.humidity_pct,
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
                    # Track if this is the first check-in (for identity sync)
                    is_first_check_in = (loop_count == 30)

                    # Get DrawingEISV from screen renderer (None when not drawing)
                    drawing_eisv = None
                    if _screen_renderer:
                        try:
                            drawing_eisv = _screen_renderer.get_drawing_eisv()
                        except Exception:
                            pass

                    async def check_in_governance():
                        # Use singleton bridge (connection pooling, no session leaks)
                        bridge = _get_unitares_bridge(unitares_url, identity)
                        # Pass identity for metadata sync and include in check-in
                        decision = await bridge.check_in(
                            anima, readings,
                            identity=identity,
                            is_first_check_in=is_first_check_in,
                            drawing_eisv=drawing_eisv
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

                            # Log periodically (or always on non-proceed)
                            action = decision.get("action", "unknown")
                            margin = decision.get("margin", "unknown")
                            source = decision.get("source", "unknown")
                            if loop_count % 60 == 0 or action != "proceed":
                                de = f" drawing={drawing_eisv}" if drawing_eisv else ""
                                print(f"[Governance] {action} ({margin}) from {source}{de}", file=sys.stderr, flush=True)
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
                async def extract_and_validate_schema():
                    """Extract G_t, save, and optionally run real VQA validation."""
                    try:
                        from .self_schema import get_current_schema
                        from .self_schema_renderer import (
                            save_render_to_file, render_schema_to_pixels,
                            compute_visual_integrity_stub, evaluate_vqa
                        )
                        import os

                        # Extract G_t (with preferences and self-beliefs)
                        from .self_model import get_self_model as _get_sm
                        schema = get_current_schema(
                            identity=identity,
                            anima=anima,
                            readings=readings,
                            growth_system=_growth,
                            include_preferences=True,
                            force_refresh=True,
                            self_model=_get_sm(),
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

            # Delay until next render — screen-specific for performance
            # Heavy screens (notepad, learning) get slower refresh to save CPU
            # Event-driven: mode_change_event breaks out of wait immediately
            current_mode = _screen_renderer._state.mode if _screen_renderer else None

            # Screen-specific delays: notepad/learning are heavy, others are light
            if current_mode in (ScreenMode.NOTEPAD, ScreenMode.LEARNING, ScreenMode.SELF_GRAPH):
                screen_delay = 1.0  # 1 FPS for heavy screens (drawing, learning visualization)
            elif current_mode in (ScreenMode.NEURAL,):
                screen_delay = 0.5  # 2 FPS for neural (animated but not critical)
            else:
                screen_delay = base_delay  # 5 FPS for face and simple screens

            if consecutive_errors > 0:
                delay = min(screen_delay * (1.5 ** min(consecutive_errors, 3)), max_delay)
            else:
                delay = screen_delay

            # Wait for delay OR mode change event (whichever comes first)
            # This makes screen switching feel instant
            try:
                await asyncio.wait_for(mode_change_event.wait(), timeout=delay)
                mode_change_event.clear()  # Reset for next mode change
                quick_render = True  # Skip heavy subsystems, just render
                # Mode changed - render immediately with minimal settle delay
                await asyncio.sleep(0.015)  # 15ms — let GPIO debounce finish
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
        "note": "Questions auto-expire after 4 hours if unanswered."
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
    client_session_id = arguments.get("client_session_id")

    # Resolve verified identity from UNITARES when caller provides their session_id
    # Only attempts resolution if client_session_id is explicitly provided
    if _unitares_bridge and client_session_id:
        try:
            resolved = await _unitares_bridge.resolve_caller_identity(session_id=client_session_id)
            if resolved:
                agent_name = resolved
        except Exception:
            pass  # Fallback to provided agent_name

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
        # Find the question with prefix matching support
        question = None
        validated_question_id = None
        
        # Try exact match first
        for m in board._messages:
            if m.message_id == question_id and m.msg_type == MESSAGE_TYPE_QUESTION:
                question = m
                validated_question_id = question_id
                break
        
        # If exact match failed, try prefix matching
        if not question:
            matching = [
                m for m in board._messages
                if m.msg_type == MESSAGE_TYPE_QUESTION
                and m.message_id.startswith(question_id)
            ]
            if len(matching) == 1:
                question = matching[0]
                validated_question_id = question.message_id
            elif len(matching) > 1:
                # Multiple matches - use most recent
                question = matching[-1]
                validated_question_id = question.message_id
            else:
                # No match - return helpful error
                all_q_ids = [m.message_id for m in board._messages if m.msg_type == MESSAGE_TYPE_QUESTION]
                return [TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": f"Question '{question_id}' not found",
                    "hint": "Use the full question ID from lumen_qa()",
                    "recent_question_ids": all_q_ids[-5:] if all_q_ids else []
                }))]

        # Add answer via add_agent_message (handles responds_to linking)
        result = add_agent_message(answer, agent_name=agent_name, responds_to=validated_question_id)

        # Extract insight from Q&A (inline so result visible in response)
        # This populates Lumen's knowledge base with learnings from answers
        insight_result = None
        try:
            from .knowledge import extract_insight_from_answer
            insight = await extract_insight_from_answer(
                question=question.text,
                answer=answer,
                author=agent_name
            )
            if insight:
                insight_result = {"text": insight.text, "category": insight.category}
                print(f"[Q&A] Extracted insight: {insight.text[:80]}", file=sys.stderr, flush=True)
            else:
                insight_result = {"skipped": "no meaningful insight extracted"}
                print(f"[Q&A] No insight extracted", file=sys.stderr, flush=True)
        except Exception as e:
            insight_result = {"error": str(e)}
            print(f"[Q&A] Insight extraction failed: {e}", file=sys.stderr, flush=True)

        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "action": "answered",
            "question_id": validated_question_id,
            "question_text": question.text,
            "answer": answer,
            "agent_name": agent_name,
            "message_id": result.message_id if result else None,
            "matched_partial_id": question_id if question_id != validated_question_id else None,
            "insight": insight_result,
        }))]

    # Otherwise -> list mode
    # Auto-repair orphaned answered questions (answered=True but no actual answer)
    repaired = board.repair_orphaned_answered()

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

    identity = store.get_identity()
    old_name = identity.name if identity else None
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


async def handle_capture_screen(arguments: dict) -> list[TextContent]:
    """
    Capture current display screen as base64-encoded PNG image.

    Returns the actual visual output on Lumen's 240×240 LCD display,
    allowing remote viewing of what Lumen is drawing, showing, or expressing.
    """
    global _screen_renderer

    if _screen_renderer is None:
        return [TextContent(type="text", text=json.dumps({
            "error": "Screen renderer not initialized"
        }))]

    try:
        # Access the renderer's display object to get the current image
        renderer_display = _screen_renderer._display
        if renderer_display is None or not hasattr(renderer_display, '_image'):
            return [TextContent(type="text", text=json.dumps({
                "error": "Display not available or no image cached"
            }))]

        # Get the current image from the PIL renderer
        current_image = renderer_display._image
        if current_image is None:
            return [TextContent(type="text", text=json.dumps({
                "error": "No image currently displayed"
            }))]

        # Convert PIL Image to base64-encoded PNG
        import base64
        from io import BytesIO

        buffer = BytesIO()
        current_image.save(buffer, format="PNG")
        img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

        # Get current screen/era context
        screen_mode = _screen_renderer.get_mode().value
        era_info = {}
        if screen_mode == "art_eras":
            from .display.art_era_canvas import get_current_era_info
            try:
                era_info = get_current_era_info() or {}
            except Exception:
                pass

        result = {
            "success": True,
            "image_base64": img_base64,
            "width": current_image.width,
            "height": current_image.height,
            "screen": screen_mode,
            "era": era_info.get("name") if era_info else None,
            "format": "PNG",
            "note": "Display as: <img src='data:image/png;base64,{image_base64}' />"
        }

        return [TextContent(type="text", text=json.dumps(result))]

    except Exception as e:
        import traceback
        return [TextContent(type="text", text=json.dumps({
            "error": f"Failed to capture screen: {str(e)}",
            "traceback": traceback.format_exc()
        }))]


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
    if _display and hasattr(_display, '_init_error') and _display._init_error:
        display_info["init_error"] = _display._init_error
    
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
            # Separate self-knowledge from visitors
            self_record = None
            visitors = []
            for r in _growth._relationships.values():
                if r.is_self():
                    self_record = r
                else:
                    visitors.append({
                        "name": r.name or r.agent_id[:8],
                        "frequency": r.visitor_frequency.value,
                        "visits": r.interaction_count,
                        "first_seen": r.first_met.strftime("%Y-%m-%d"),
                        "last_seen": r.last_seen.strftime("%Y-%m-%d"),
                    })

            # Self-knowledge: the one real relationship (Lumen answering own questions)
            self_dialogues = self_record.interaction_count if self_record else 0
            topics = self_record.self_dialogue_topics if self_record else []
            # Count topic frequencies
            topic_counts = {}
            for t in topics:
                topic_counts[t] = topic_counts.get(t, 0) + 1
            # Sort by frequency
            top_topics = sorted(topic_counts.items(), key=lambda x: -x[1])[:5]

            result["self_knowledge"] = {
                "self_dialogues": self_dialogues,
                "topics": top_topics if top_topics else None,
                "note": "Lumen answering own questions - genuine self-reflection with memory continuity",
            }

            # Caretaker: the human who built and maintains Lumen (has real continuity)
            # This relationship is real but invisible in message logs because
            # the caretaker works through agents rather than posting directly.
            result["caretaker"] = {
                "exists": True,
                "note": "The human who built and maintains me - works through agents, so invisible in visitor logs",
            }

            # Visitors: ephemeral agents who passed through
            result["visitors"] = {
                "unique_names": len(visitors),
                "log": visitors[:10],
                "note": "Agents are ephemeral - they don't remember Lumen between sessions",
            }

            # Legacy key for compatibility
            result["relationships"] = {
                "count": len(_growth._relationships),
                "bonds": visitors[:10],
            }

            # Inactive visitors (not "missed connections" - agents don't miss Lumen)
            inactive = _growth.get_inactive_visitors()
            if inactive:
                result["visitors"]["inactive"] = [
                    {"name": name, "days_since": days}
                    for name, days in inactive[:3]
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


async def handle_get_qa_insights(arguments: dict) -> list[TextContent]:
    """Get insights Lumen learned from Q&A interactions."""
    try:
        from .knowledge import get_insights, get_knowledge

        limit = arguments.get("limit", 10)
        category = arguments.get("category")

        kb = get_knowledge()
        insights = get_insights(limit=limit, category=category)

        result = {
            "total_insights": len(kb._insights),
            "category_filter": category if category else "all",
            "insights": [
                {
                    "text": i.text,
                    "source_question": i.source_question,
                    "source_answer": i.source_answer,
                    "source_author": i.source_author,
                    "category": i.category,
                    "confidence": i.confidence,
                    "age": i.age_string(),
                    "timestamp": i.timestamp,
                }
                for i in insights
            ],
        }

        if len(insights) == 0:
            result["note"] = "No Q&A insights yet - answer Lumen's questions to populate knowledge base"

        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Q&A knowledge error: {e}",
            "note": "Q&A knowledge extraction may not have run yet"
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


async def handle_get_eisv_trajectory_state(arguments: dict) -> list[TextContent]:
    """Get current EISV trajectory awareness state."""
    try:
        _traj = get_trajectory_awareness()
        state = _traj.get_state()
        return [TextContent(type="text", text=json.dumps(state, indent=2, default=str))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


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
        # Bootstrap: deploy from GitHub zip (no git needed — for Pi set up via rsync without .git)
        try:
            import urllib.request
            import zipfile
            import shutil

            url = "https://github.com/CIRWEL/anima-mcp/archive/refs/heads/main.zip"
            zip_path = Path("/tmp") / "anima-mcp-main.zip"
            ext_path = Path("/tmp") / "anima-mcp-main"

            urllib.request.urlretrieve(url, zip_path)
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(ext_path.parent)
            zip_path.unlink(missing_ok=True)

            src = ext_path
            skip = {".venv", ".git", "__pycache__", ".env"}
            for item in src.iterdir():
                if item.name in skip or item.name.endswith(".db"):
                    continue
                dst = repo_root / item.name
                if item.is_dir():
                    if dst.exists():
                        shutil.rmtree(dst, ignore_errors=True)
                    shutil.copytree(item, dst, ignore=shutil.ignore_patterns(".venv", ".git", "__pycache__", "*.db", ".env"))
                else:
                    shutil.copy2(item, dst)
            shutil.rmtree(ext_path, ignore_errors=True)

            output = {"success": True, "bootstrap": "Deployed from GitHub zip", "repo": str(repo_root)}
            if restart:
                output["restart"] = "Restarting server..."
                import asyncio
                async def _delayed_restart():
                    await asyncio.sleep(1)
                    try:
                        result = subprocess.run(["sudo", "systemctl", "restart", "anima"], timeout=30, check=False, capture_output=True)
                        if result.returncode != 0:
                            # sudo failed (NoNewPrivileges) — self-exit so systemd restarts us
                            import os
                            os._exit(1)
                    except Exception:
                        import os
                        os._exit(1)
                asyncio.create_task(_delayed_restart())
            return [TextContent(type="text", text=json.dumps(output, indent=2))]
        except Exception as e:
            return [TextContent(type="text", text=json.dumps({
                "error": f"Bootstrap (zip deploy) failed: {e}",
                "repo": str(repo_root),
            }))]

    try:
        # Stash local changes if requested (only when .git exists)
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
                    try:
                        result = subprocess.run(
                            ["sudo", "systemctl", "restart", "anima"],
                            timeout=30,
                            check=False,
                            capture_output=True
                        )
                        if result.returncode != 0:
                            # sudo failed (NoNewPrivileges) — self-exit so systemd restarts us
                            import os
                            os._exit(1)
                    except Exception:
                        import os
                        os._exit(1)
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


async def handle_fix_ssh_port(arguments: dict) -> list[TextContent]:
    """
    Switch SSH to port 2222 (headless fix when port 22 is blocked).
    Call via HTTP when SSH times out: avoids need for keyboard/monitor.
    """
    import subprocess

    port = arguments.get("port", 2222)
    if port not in (2222, 22222):
        return [TextContent(type="text", text=json.dumps({
            "error": "port must be 2222 or 22222 (safety)",
            "usage": "After running: ssh -p 2222 -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165"
        }))]

    try:
        # Check if already configured
        check = subprocess.run(
            ["grep", "-q", f"^Port {port}", "/etc/ssh/sshd_config"],
            capture_output=True,
            timeout=5
        )
        if check.returncode == 0:
            subprocess.run(
                ["sudo", "systemctl", "restart", "ssh"],
                capture_output=True,
                text=True,
                timeout=15
            )
            return [TextContent(type="text", text=json.dumps({
                "success": True,
                "message": f"SSH already on port {port}, restarted",
                "connect": f"ssh -p {port} -i ~/.ssh/id_ed25519_pi unitares-anima@<PI_IP>"
            }))]

        # Add Port 2222 to sshd_config
        echo = subprocess.run(
            ["sh", "-c", f"echo 'Port {port}' | sudo tee -a /etc/ssh/sshd_config"],
            capture_output=True,
            text=True,
            timeout=10
        )
        if echo.returncode != 0:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Failed to update sshd_config: {echo.stderr}"
            }))]

        # Restart SSH
        restart = subprocess.run(
            ["sudo", "systemctl", "restart", "ssh"],
            capture_output=True,
            text=True,
            timeout=15
        )

        return [TextContent(type="text", text=json.dumps({
            "success": restart.returncode == 0,
            "port": port,
            "message": f"SSH now on port {port}. Connect with:",
            "connect": f"ssh -p {port} -i ~/.ssh/id_ed25519_pi unitares-anima@192.168.1.165",
            "stderr": restart.stderr.strip() if restart.stderr else None,
        }))]
    except subprocess.TimeoutExpired:
        return [TextContent(type="text", text=json.dumps({
            "success": False,
            "error": "Command timed out"
        }))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "success": False,
            "error": str(e)
        }))]


async def handle_deploy_from_github(arguments: dict) -> list[TextContent]:
    """
    Deploy latest code from GitHub via zip download. No git required.
    Use when git_pull fails (no .git) or to force-refresh from main.
    """
    import urllib.request
    import zipfile
    import shutil
    from pathlib import Path

    restart = arguments.get("restart", True)
    repo_root = Path(__file__).parent.parent.parent

    try:
        url = "https://github.com/CIRWEL/anima-mcp/archive/refs/heads/main.zip"
        zip_path = Path("/tmp") / "anima-mcp-main.zip"
        ext_path = Path("/tmp") / "anima-mcp-main"

        urllib.request.urlretrieve(url, zip_path)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(ext_path.parent)
        zip_path.unlink(missing_ok=True)

        src = ext_path
        skip = {".venv", ".git", "__pycache__", ".env"}
        for item in src.iterdir():
            if item.name in skip or item.name.endswith(".db"):
                continue
            dst = repo_root / item.name
            if item.is_dir():
                if dst.exists():
                    shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(item, dst, ignore=shutil.ignore_patterns(".venv", ".git", "__pycache__", "*.db", ".env"))
            else:
                shutil.copy2(item, dst)
        shutil.rmtree(ext_path, ignore_errors=True)

        output = {"success": True, "message": "Deployed from GitHub", "repo": str(repo_root)}
        if restart:
            output["restart"] = "Restarting server..."
            import subprocess
            import asyncio
            async def _delayed_restart():
                await asyncio.sleep(1)
                try:
                    result = subprocess.run(["sudo", "systemctl", "restart", "anima"], timeout=30, check=False, capture_output=True)
                    if result.returncode != 0:
                        import os
                        os._exit(1)
                except Exception:
                    import os
                    os._exit(1)
            asyncio.create_task(_delayed_restart())
        return [TextContent(type="text", text=json.dumps(output, indent=2))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "success": False,
            "error": str(e),
            "repo": str(repo_root),
        }))]


async def handle_setup_tailscale(arguments: dict) -> list[TextContent]:
    """
    Install and activate Tailscale on Pi (ngrok alternative — no usage limits).
    Call via HTTP when SSH unavailable. Requires auth_key for headless.
    Get key: https://login.tailscale.com/admin/settings/keys
    """
    import subprocess

    auth_key = arguments.get("auth_key", "").strip()
    if not auth_key:
        return [TextContent(type="text", text=json.dumps({
            "error": "auth_key required for headless setup",
            "hint": "Get at https://login.tailscale.com/admin/settings/keys (reusable, 90 days)",
            "usage": "Call with auth_key=tskey-auth-xxx"
        }))]

    if not auth_key.startswith("tskey-"):
        return [TextContent(type="text", text=json.dumps({
            "error": "Invalid auth_key format (should start with tskey-)"
        }))]

    try:
        # Install Tailscale
        install = subprocess.run(
            ["sh", "-c", "curl -fsSL https://tailscale.com/install.sh | sh"],
            capture_output=True,
            text=True,
            timeout=120
        )
        if install.returncode != 0:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Install failed: {install.stderr or install.stdout}"
            }))]

        # Activate with auth key
        up = subprocess.run(
            ["sudo", "tailscale", "up", "--authkey=" + auth_key],
            capture_output=True,
            text=True,
            timeout=60
        )

        if up.returncode != 0:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "error": up.stderr.strip() or up.stdout.strip() or "tailscale up failed",
                "hint": "Auth key may be expired or invalid"
            }))]

        # Get Tailscale IP
        ip_result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=10
        )
        ts_ip = ip_result.stdout.strip().split("\n")[0] if ip_result.stdout else None

        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "message": "Tailscale active. Use 100.x.x.x for MCP/SSH.",
            "tailscale_ip": ts_ip,
            "mcp_url": f"http://{ts_ip}:8766/mcp/" if ts_ip else None,
            "connect": f"ssh -i ~/.ssh/id_ed25519_pi unitares-anima@{ts_ip}" if ts_ip else None,
        }))]
    except subprocess.TimeoutExpired:
        return [TextContent(type="text", text=json.dumps({
            "success": False,
            "error": "Command timed out"
        }))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "success": False,
            "error": str(e)
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
                "agent_name": {
                    "type": "string",
                    "description": "Your name/identifier when answering (e.g. 'Kenny', 'Claude'). Default: 'agent'",
                },
                "client_session_id": {
                    "type": "string",
                    "description": "Your UNITARES session ID for verified identity resolution. Pass this to have your verified name displayed instead of agent_name.",
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
                "responds_to": {"type": "string", "description": "REQUIRED when answering: question ID from get_questions"},
                "client_session_id": {"type": "string", "description": "Your UNITARES session ID for verified identity resolution"}
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
        description="Control Lumen's display: switch screens, show face, navigate. Also manage art eras: list_eras, get_era, set_era.",
        inputSchema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["switch", "face", "next", "previous", "list_eras", "get_era", "set_era"], "description": "Action to perform"},
                "screen": {"type": "string", "description": "Screen name (for action=switch) or era name (for action=set_era)"}
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
        name="capture_screen",
        description="Capture current display screen as base64-encoded PNG image. See what Lumen is actually drawing/showing on the 240×240 LCD.",
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
        name="get_qa_insights",
        description="Get insights Lumen learned from Q&A interactions - knowledge extracted from answers to questions",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max insights to return (default: 10)",
                    "default": 10
                },
                "category": {
                    "type": "string",
                    "enum": ["self", "sensations", "relationships", "existence", "world", "general"],
                    "description": "Filter by insight category (optional)"
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
        name="get_eisv_trajectory_state",
        description="Get current EISV trajectory awareness state - shapes, buffer, cache, events, feedback stats",
        inputSchema={
            "type": "object",
            "properties": {},
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
        name="deploy_from_github",
        description="Deploy latest code from GitHub via zip. No git needed. Use when Pi has no .git or git_pull fails.",
        inputSchema={
            "type": "object",
            "properties": {
                "restart": {
                    "type": "boolean",
                    "description": "Restart anima service after deploy",
                    "default": True,
                },
            },
        },
    ),
    Tool(
        name="setup_tailscale",
        description="Install and activate Tailscale on Pi (ngrok alternative, no usage limits). Call via HTTP. Requires auth_key.",
        inputSchema={
            "type": "object",
            "properties": {
                "auth_key": {
                    "type": "string",
                    "description": "Tailscale auth key from login.tailscale.com/admin/settings/keys (required for headless)",
                },
            },
            "required": ["auth_key"],
        },
    ),
    Tool(
        name="fix_ssh_port",
        description="Switch SSH to port 2222 when port 22 is blocked (headless fix, no keyboard needed). Call via HTTP.",
        inputSchema={
            "type": "object",
            "properties": {
                "port": {
                    "type": "integer",
                    "description": "Port for SSH (2222 or 22222)",
                    "default": 2222,
                },
            },
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

    # Include EISV metrics when anima is available
    if ("eisv" in include or "anima" in include) and anima and readings:
        try:
            from .eisv_mapper import anima_to_eisv
            eisv = anima_to_eisv(anima, readings)
            result["eisv"] = eisv.to_dict()
        except Exception:
            pass  # EISV is optional enrichment

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
    global _sm_clarity_before_interaction
    message = arguments.get("message", "").strip()
    source = arguments.get("source", "agent")
    agent_name = arguments.get("agent_name", "agent")
    responds_to = arguments.get("responds_to")
    client_session_id = arguments.get("client_session_id")

    # Resolve verified identity from UNITARES when caller provides their session_id
    # Only attempts resolution if client_session_id is explicitly provided
    if _unitares_bridge and client_session_id:
        try:
            resolved = await _unitares_bridge.resolve_caller_identity(session_id=client_session_id)
            if resolved:
                agent_name = resolved
        except Exception:
            pass  # Fallback to provided agent_name

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
            # Wake Lumen on interaction (activity state)
            try:
                if _activity:
                    _activity.record_interaction()
            except Exception:
                pass
            # Snapshot clarity for self-model interaction observation
            try:
                _, cur_anima = _get_readings_and_anima(fallback_to_sensors=False)
                if cur_anima:
                    _sm_clarity_before_interaction = cur_anima.clarity
            except Exception:
                pass
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
            # Wake Lumen on interaction (activity state)
            try:
                if _activity:
                    _activity.record_interaction()
            except Exception:
                pass
            # Snapshot clarity for self-model interaction observation
            try:
                _, cur_anima = _get_readings_and_anima(fallback_to_sensors=False)
                if cur_anima:
                    _sm_clarity_before_interaction = cur_anima.clarity
            except Exception:
                pass
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
                temp = readings.ambient_temp_c
                light = readings.light_lux
                humidity = readings.humidity_pct

        predictions = []
        if temp is not None or light is not None:
            sensors_dict = {
                "ambient_temp_c": temp,
                "light_lux": light,
                "humidity_pct": humidity,
            }
            ant = anticipate_state(sensors_dict)
            if ant:
                import dataclasses
                predictions = [dataclasses.asdict(ant)]

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
            "neural": ScreenMode.NEURAL,
            "notepad": ScreenMode.NOTEPAD,
            "learning": ScreenMode.LEARNING,
            "self_graph": ScreenMode.SELF_GRAPH,
            "messages": ScreenMode.MESSAGES,
            "questions": ScreenMode.QUESTIONS,
            "visitors": ScreenMode.VISITORS,
            "art_eras": ScreenMode.ART_ERAS,
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

    elif action == "list_eras":
        info = _screen_renderer.get_current_era()
        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "action": "list_eras",
            **info,
        }))]

    elif action == "get_era":
        info = _screen_renderer.get_current_era()
        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "action": "get_era",
            "current_era": info["current_era"],
            "current_description": info["current_description"],
            "auto_rotate": info["auto_rotate"],
        }))]

    elif action == "set_era":
        era_name = arguments.get("screen", "").lower()
        if not era_name:
            return [TextContent(type="text", text=json.dumps({
                "error": "screen parameter required — set it to the era name (e.g. 'geometric', 'gestural')"
            }))]
        result = _screen_renderer.set_era(era_name)
        return [TextContent(type="text", text=json.dumps({
            "action": "set_era",
            **result,
        }))]

    else:
        return [TextContent(type="text", text=json.dumps({
            "error": f"Unknown action: {action}",
            "valid_actions": ["switch", "face", "next", "previous", "list_eras", "get_era", "set_era"]
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
    # Standard tools (15)
    "get_lumen_context": handle_get_lumen_context,
    "manage_display": handle_manage_display,
    "configure_voice": handle_configure_voice,
    "say": handle_say,
    "diagnostics": handle_diagnostics,
    "capture_screen": handle_capture_screen,
    "unified_workflow": handle_unified_workflow,
    "get_calibration": handle_get_calibration,
    "get_self_knowledge": handle_get_self_knowledge,
    "get_growth": handle_get_growth,
    "get_qa_insights": handle_get_qa_insights,
    "get_trajectory": handle_get_trajectory,
    "get_eisv_trajectory_state": handle_get_eisv_trajectory_state,
    "git_pull": handle_git_pull,
    "system_service": handle_system_service,
    "fix_ssh_port": handle_fix_ssh_port,
    "setup_tailscale": handle_setup_tailscale,
    "deploy_from_github": handle_deploy_from_github,
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
        # Any MCP tool call = external interaction → wake Lumen
        try:
            if _activity:
                _activity.record_interaction()
        except Exception:
            pass
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

    Retries on SQLite lock errors (e.g. old process still shutting down).

    Args:
        db_path: Path to SQLite database
        anima_id: UUID from environment or database (DO NOT override - use existing identity)
    """
    import time as _time
    global _store, _anima_id, _growth

    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
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
                _growth.born_at = identity.born_at
                print(f"[Wake] ✓ Growth system initialized", file=sys.stderr, flush=True)
            except Exception as ge:
                print(f"[Wake] Growth system error (non-fatal): {ge}", file=sys.stderr, flush=True)
                _growth = None

            # Bootstrap trajectory awareness from state history
            try:
                import os as _os
                _db_path = _os.path.join(_os.path.expanduser("~"), ".anima", "anima.db")
                _student_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))), "data", "student_model")
                if not _os.path.isdir(_student_dir):
                    _student_dir = None
                _traj = get_trajectory_awareness(db_path=_db_path, student_model_dir=_student_dir)
                history = _store.get_recent_state_history(limit=30)
                if history:
                    n = _traj.bootstrap_from_history(history)
                    print(f"[EISV] Bootstrapped trajectory buffer with {n} historical states", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[EISV] Bootstrap failed (non-fatal): {e}", file=sys.stderr, flush=True)

            return  # Success
        except Exception as e:
            is_lock_error = "database is locked" in str(e) or "database is locked" in repr(e)
            if is_lock_error and attempt < max_attempts:
                wait = attempt * 2  # 2s, 4s, 6s, 8s
                print(f"[Wake] Database locked (attempt {attempt}/{max_attempts}), retrying in {wait}s...", file=sys.stderr, flush=True)
                # Close the failed connection before retrying
                if _store and _store._conn:
                    try:
                        _store._conn.close()
                    except Exception:
                        pass
                _store = None
                _time.sleep(wait)
            else:
                print(f"[Wake] ❌ ERROR: Identity store failed!", file=sys.stderr, flush=True)
                print(f"[Wake] Error details: {e}", file=sys.stderr, flush=True)
                print(f"[Wake] Impact: Message board will NOT post, identity features unavailable", file=sys.stderr, flush=True)
                print(f"[Server] Display will work but without identity/messages", file=sys.stderr, flush=True)
                _store = None
                return


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

            # Dashboard endpoint - serves the Lumen Control Center
            from starlette.responses import HTMLResponse, FileResponse
            from pathlib import Path

            async def dashboard(request):
                """Serve the Lumen Control Center dashboard."""
                # Find control_center.html relative to this file
                server_dir = Path(__file__).parent
                project_root = server_dir.parent.parent
                dashboard_path = project_root / "docs" / "control_center.html"

                if dashboard_path.exists():
                    return FileResponse(dashboard_path, media_type="text/html")
                else:
                    return HTMLResponse(
                        "<html><body><h1>Dashboard Not Found</h1>"
                        f"<p>Expected at: {dashboard_path}</p></body></html>",
                        status_code=404
                    )

            app.routes.append(Route("/dashboard", dashboard, methods=["GET"]))
            print("[Server] Registered /dashboard endpoint", file=sys.stderr, flush=True)

            # REST API endpoints for Control Center dashboard
            # These map to MCP tools for convenient dashboard access

            async def rest_state(request):
                """GET /state - Format matching message_server.py."""
                try:
                    # Use internal functions (same as MCP get_state)
                    readings, anima = _get_readings_and_anima()
                    if readings is None or anima is None:
                        return JSONResponse({"error": "Unable to read sensor data"}, status_code=500)

                    feeling = anima.feeling()
                    store = _get_store()
                    identity = store.get_identity() if store else None

                    # Build neural bands from raw sensor data
                    raw = readings.to_dict()
                    neural = {}
                    for k in ["eeg_delta_power", "eeg_theta_power", "eeg_alpha_power", "eeg_beta_power", "eeg_gamma_power"]:
                        if raw.get(k) is not None:
                            neural[k.replace("eeg_", "").replace("_power", "")] = round(raw[k], 3)

                    # EISV
                    from .eisv_mapper import anima_to_eisv
                    eisv = anima_to_eisv(anima, readings)

                    # Governance
                    gov = _last_governance_decision or {}

                    return JSONResponse({
                        "name": identity.name if identity else "Lumen",
                        "mood": feeling["mood"],
                        "warmth": anima.warmth,
                        "clarity": anima.clarity,
                        "stability": anima.stability,
                        "presence": anima.presence,
                        "feeling": feeling,
                        "surprise": 0,
                        "cpu_temp": readings.cpu_temp_c or 0,
                        "ambient_temp": readings.ambient_temp_c or 0,
                        "light": readings.light_lux or 0,
                        "humidity": readings.humidity_pct or 0,
                        "pressure": readings.pressure_hpa or 0,
                        "cpu_percent": readings.cpu_percent or 0,
                        "memory_percent": readings.memory_percent or 0,
                        "disk_percent": readings.disk_percent or 0,
                        "neural": neural,
                        "eisv": eisv.to_dict(),
                        "governance": {
                            "decision": gov.get("action", "unknown").upper() if gov else "OFFLINE",
                            "margin": gov.get("margin", "") if gov else "",
                            "source": gov.get("source", "") if gov else "",
                            "connected": bool(gov),
                        },
                        "awakenings": identity.total_awakenings if identity else 0,
                        "alive_hours": round((identity.total_alive_seconds + store.get_session_alive_seconds()) / 3600, 1) if identity and store else 0,
                        "alive_ratio": round(identity.alive_ratio(), 2) if identity else 0,
                        "activity": {
                            **(_activity.get_status() if _activity else {"level": "active"}),
                            "sleep": _activity.get_sleep_summary() if _activity else {"sessions": 0},
                        },
                        "timestamp": str(readings.timestamp) if readings.timestamp else "",
                    })
                except Exception as e:
                    return JSONResponse({"error": str(e)}, status_code=500)

            async def rest_qa(request):
                """GET /qa - Get questions and answers (matching message_server.py format)."""
                try:
                    from .messages import get_board, MESSAGE_TYPE_QUESTION

                    board = get_board()
                    board._load(force=True)

                    # Get all questions
                    questions = [m for m in board._messages if m.msg_type == MESSAGE_TYPE_QUESTION]

                    # Build Q&A pairs with answers
                    qa_pairs = []
                    for q in questions:
                        # Find answer for this question
                        answer = None
                        for m in board._messages:
                            if getattr(m, "responds_to", None) == q.message_id:
                                answer = {"text": m.text, "author": m.author, "timestamp": m.timestamp}
                                break
                        qa_pairs.append({
                            "id": q.message_id,
                            "question": q.text,
                            "answered": q.answered,
                            "timestamp": q.timestamp,
                            "answer": answer
                        })

                    # Count truly unanswered (no actual answer message) from ALL questions
                    truly_unanswered = sum(1 for q in qa_pairs if q["answer"] is None)

                    # Reverse to show newest first
                    limit = int(request.query_params.get("limit", "20"))
                    limit = min(limit, 50)
                    qa_pairs.reverse()
                    qa_pairs = qa_pairs[:limit]

                    return JSONResponse({"questions": qa_pairs, "total": len(questions), "unanswered": truly_unanswered})
                except Exception as e:
                    return JSONResponse({"error": str(e)}, status_code=500)

            async def rest_messages(request):
                """GET /messages - Get recent message board entries."""
                try:
                    from .messages import get_board, get_recent_messages
                    limit = int(request.query_params.get("limit", "20"))
                    limit = min(limit, 100)
                    messages = get_recent_messages(limit)
                    board = get_board()
                    return JSONResponse({
                        "messages": [
                            {
                                "id": m.message_id,
                                "text": m.text,
                                "type": m.msg_type,
                                "author": m.author,
                                "timestamp": m.timestamp,
                                "responds_to": m.responds_to,
                            }
                            for m in messages
                        ],
                        "total": len(board._messages),
                        "returned": len(messages),
                    })
                except Exception as e:
                    return JSONResponse({"error": str(e)}, status_code=500)

            async def rest_answer(request):
                """POST /answer - Answer a question from Lumen."""
                try:
                    body = await request.json()
                    question_id = body.get("question_id") or body.get("id")
                    answer = body.get("answer")
                    author = body.get("author", "Kenny")  # Preserve author name
                    result = await handle_lumen_qa({
                        "question_id": question_id,
                        "answer": answer,
                        "agent_name": author
                    })
                    if result and len(result) > 0:
                        data = json.loads(result[0].text)
                        return JSONResponse(data)
                    return JSONResponse({"success": True})
                except Exception as e:
                    return JSONResponse({"error": str(e)}, status_code=500)

            async def rest_message(request):
                """POST /message - Send a message to Lumen."""
                try:
                    body = await request.json()
                    message = body.get("message", body.get("text", ""))
                    author = body.get("author", "dashboard")
                    responds_to = body.get("responds_to")
                    payload = {"message": message, "source": "dashboard", "agent_name": author}
                    if responds_to:
                        payload["responds_to"] = responds_to
                    result = await handle_post_message(payload)
                    if result and len(result) > 0:
                        data = json.loads(result[0].text)
                        return JSONResponse(data)
                    return JSONResponse({"success": True})
                except Exception as e:
                    return JSONResponse({"error": str(e)}, status_code=500)

            async def rest_learning(request):
                """GET /learning - Exact copy of message_server.py format."""
                try:
                    import sqlite3
                    from pathlib import Path
                    from datetime import datetime, timedelta

                    # Find database - prefer ANIMA_DB env var, then ~/.anima/
                    import os
                    db_path = None
                    env_db = os.environ.get("ANIMA_DB")
                    candidates = [Path(env_db)] if env_db else []
                    candidates.extend([Path.home() / ".anima" / "anima.db", Path.home() / "anima-mcp" / "anima.db"])
                    for p in candidates:
                        if p.exists():
                            db_path = p
                            break

                    if not db_path:
                        return JSONResponse({"error": "No identity database"}, status_code=500)

                    conn = sqlite3.connect(str(db_path))

                    # Get identity stats
                    identity = conn.execute("SELECT name, total_awakenings, total_alive_seconds FROM identity LIMIT 1").fetchone()

                    # Get recent state history for learning trends
                    one_day_ago = (datetime.now() - timedelta(hours=24)).isoformat()
                    recent_states = conn.execute(
                        "SELECT warmth, clarity, stability, presence, timestamp FROM state_history WHERE timestamp > ? ORDER BY timestamp DESC LIMIT 100",
                        (one_day_ago,)
                    ).fetchall()

                    # Calculate averages and trends
                    if recent_states:
                        avg_warmth = sum(s[0] for s in recent_states) / len(recent_states)
                        avg_clarity = sum(s[1] for s in recent_states) / len(recent_states)
                        avg_stability = sum(s[2] for s in recent_states) / len(recent_states)
                        avg_presence = sum(s[3] for s in recent_states) / len(recent_states)

                        mid = len(recent_states) // 2
                        if mid > 0:
                            first_half = recent_states[mid:]
                            second_half = recent_states[:mid]
                            stability_trend = sum(s[2] for s in second_half) / len(second_half) - sum(s[2] for s in first_half) / len(first_half)
                        else:
                            stability_trend = 0
                    else:
                        avg_warmth = avg_clarity = avg_stability = avg_presence = 0
                        stability_trend = 0

                    # Get recent events
                    events = conn.execute(
                        "SELECT event_type, timestamp FROM events ORDER BY timestamp DESC LIMIT 10"
                    ).fetchall()

                    alive_hours = identity[2] / 3600 if identity else 0
                    conn.close()

                    # Exact same format as message_server.py
                    return JSONResponse({
                        "name": identity[0] if identity else "Unknown",
                        "awakenings": identity[1] if identity else 0,
                        "alive_hours": round(alive_hours, 1),
                        "samples_24h": len(recent_states),
                        "avg_warmth": round(avg_warmth, 3),
                        "avg_clarity": round(avg_clarity, 3),
                        "avg_stability": round(avg_stability, 3),
                        "avg_presence": round(avg_presence, 3),
                        "stability_trend": round(stability_trend, 3),
                        "recent_events": [{"type": e[0], "time": e[1]} for e in events[:5]]
                    })
                except Exception as e:
                    return JSONResponse({"error": str(e)}, status_code=500)

            async def rest_voice(request):
                """GET /voice - Get voice system status."""
                try:
                    result = await handle_configure_voice({"action": "status"})
                    if result and len(result) > 0:
                        data = json.loads(result[0].text)
                        return JSONResponse(data)
                    return JSONResponse({"mode": "text"})
                except Exception as e:
                    return JSONResponse({"error": str(e)}, status_code=500)

            async def rest_gallery(request):
                """GET /gallery - Get Lumen's drawings."""
                try:
                    import re
                    from pathlib import Path
                    from datetime import datetime as dt
                    drawings_dir = Path.home() / ".anima" / "drawings"

                    if not drawings_dir.exists():
                        return JSONResponse({"drawings": [], "total": 0})

                    files = list(drawings_dir.glob("lumen_drawing*.png"))

                    # Eras — chronological periods in Lumen's drawing history
                    # Each entry: (cutoff_timestamp, era_name)
                    # Drawings BEFORE the cutoff belong to that era
                    _ERAS = [
                        ("20260207_190000", "geometric"),
                    ]
                    _CURRENT_ERA = "gestural"

                    def get_era(filename):
                        """Determine which era a drawing belongs to."""
                        m = re.search(r"(\d{8}_\d{6})", filename)
                        if m:
                            ts_str = m.group(1)
                            for cutoff, name in _ERAS:
                                if ts_str < cutoff:
                                    return name
                        return _CURRENT_ERA

                    def parse_ts(f):
                        m = re.search(r"(\d{8})_(\d{6})", f.name)
                        if m:
                            try:
                                return dt.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").timestamp()
                            except ValueError:
                                pass
                        return f.stat().st_mtime

                    files = sorted(files, key=parse_ts, reverse=True)

                    # Pagination support
                    offset = int(request.query_params.get("offset", 0))
                    limit = int(request.query_params.get("limit", 50))
                    limit = min(limit, 100)  # cap at 100 per request

                    page_files = files[offset:offset + limit]

                    drawings = []
                    for f in page_files:
                        drawings.append({
                            "filename": f.name,
                            "timestamp": parse_ts(f),
                            "size": f.stat().st_size,
                            "manual": "_manual" in f.name,
                            "era": get_era(f.name),
                        })

                    return JSONResponse({
                        "drawings": drawings,
                        "total": len(files),
                        "offset": offset,
                        "limit": limit,
                        "has_more": offset + limit < len(files),
                    })
                except Exception as e:
                    return JSONResponse({"error": str(e)}, status_code=500)

            async def rest_gallery_image(request):
                """GET /gallery/{filename} - Serve a drawing image."""
                from starlette.responses import Response
                from pathlib import Path
                filename = request.path_params.get("filename", "")
                # Sanitize filename
                if "/" in filename or ".." in filename or not filename.endswith(".png"):
                    return Response(content="Bad request", status_code=400)
                img_path = Path.home() / ".anima" / "drawings" / filename
                if not img_path.exists():
                    return Response(content="Not found", status_code=404)
                try:
                    with open(img_path, "rb") as f:
                        img_data = f.read()
                    return Response(
                        content=img_data,
                        media_type="image/png",
                        headers={"Cache-Control": "max-age=3600"}
                    )
                except Exception as e:
                    return Response(content=str(e), status_code=500)

            app.routes.append(Route("/state", rest_state, methods=["GET"]))
            app.routes.append(Route("/qa", rest_qa, methods=["GET"]))
            app.routes.append(Route("/answer", rest_answer, methods=["POST"]))
            app.routes.append(Route("/message", rest_message, methods=["POST"]))
            app.routes.append(Route("/messages", rest_messages, methods=["GET"]))
            app.routes.append(Route("/learning", rest_learning, methods=["GET"]))
            app.routes.append(Route("/voice", rest_voice, methods=["GET"]))
            app.routes.append(Route("/gallery", rest_gallery, methods=["GET"]))
            app.routes.append(Route("/gallery/{filename}", rest_gallery_image, methods=["GET"]))

            async def rest_gallery_page(request):
                """Serve the Lumen Drawing Gallery page."""
                server_dir = Path(__file__).parent
                project_root = server_dir.parent.parent
                gallery_path = project_root / "docs" / "gallery.html"
                if gallery_path.exists():
                    return FileResponse(gallery_path, media_type="text/html")
                else:
                    return HTMLResponse(
                        "<html><body><h1>Gallery Not Found</h1>"
                        f"<p>Expected at: {gallery_path}</p></body></html>",
                        status_code=404
                    )

            app.routes.append(Route("/gallery-page", rest_gallery_page, methods=["GET"]))

            async def rest_layers(request):
                """GET /layers - Full proprioception stack for architecture page."""
                try:
                    readings, anima = _get_readings_and_anima()
                    if readings is None or anima is None:
                        return JSONResponse({"error": "Unable to read sensor data"}, status_code=500)

                    feeling = anima.feeling()
                    store = _get_store()
                    identity = store.get_identity() if store else None

                    # Physical sensors
                    physical = {
                        "ambient_temp_c": readings.ambient_temp_c or 0,
                        "humidity_pct": readings.humidity_pct or 0,
                        "light_lux": readings.light_lux or 0,
                        "pressure_hpa": readings.pressure_hpa or 0,
                    }

                    # Neural bands
                    raw = readings.to_dict()
                    neural = {}
                    for k in ["eeg_delta_power", "eeg_theta_power", "eeg_alpha_power", "eeg_beta_power", "eeg_gamma_power"]:
                        if raw.get(k) is not None:
                            neural[k.replace("eeg_", "").replace("_power", "")] = round(raw[k], 3)

                    # Anima
                    anima_data = {
                        "warmth": round(anima.warmth, 3),
                        "clarity": round(anima.clarity, 3),
                        "stability": round(anima.stability, 3),
                        "presence": round(anima.presence, 3),
                    }

                    # EISV
                    from .eisv_mapper import anima_to_eisv
                    eisv = anima_to_eisv(anima, readings)
                    eisv_data = eisv.to_dict()

                    # Governance
                    gov = _last_governance_decision or {}
                    governance_data = {
                        "decision": gov.get("action", "unknown").upper() if gov else "OFFLINE",
                        "margin": gov.get("margin", "unknown") if gov else "n/a",
                        "source": gov.get("source", "") if gov else "",
                        "connected": bool(gov),
                    }
                    if gov and gov.get("eisv"):
                        governance_data["eisv"] = gov["eisv"]

                    # System
                    system = {
                        "cpu_temp_c": readings.cpu_temp_c or 0,
                        "cpu_percent": readings.cpu_percent or 0,
                        "memory_percent": readings.memory_percent or 0,
                        "disk_percent": readings.disk_percent or 0,
                    }

                    # Identity
                    identity_data = {}
                    if identity:
                        alive_seconds = identity.total_alive_seconds + (store.get_session_alive_seconds() if store else 0)
                        identity_data = {
                            "name": identity.name,
                            "awakenings": identity.total_awakenings,
                            "alive_hours": round(alive_seconds / 3600, 1),
                            "alive_ratio": round(identity.alive_ratio(), 3),
                            "age_days": round(identity.age_seconds() / 86400, 1),
                        }

                    return JSONResponse({
                        "physical": physical,
                        "neural": neural,
                        "anima": anima_data,
                        "feeling": feeling,
                        "eisv": eisv_data,
                        "governance": governance_data,
                        "system": system,
                        "identity": identity_data,
                        "mood": feeling.get("mood", "unknown"),
                    })
                except Exception as e:
                    return JSONResponse({"error": str(e)}, status_code=500)

            app.routes.append(Route("/layers", rest_layers, methods=["GET"]))

            async def rest_architecture_page(request):
                """Serve the Lumen Architecture page."""
                server_dir = Path(__file__).parent
                project_root = server_dir.parent.parent
                page_path = project_root / "docs" / "architecture.html"
                if page_path.exists():
                    return FileResponse(page_path, media_type="text/html")
                else:
                    return HTMLResponse(
                        "<html><body><h1>Architecture Page Not Found</h1>"
                        f"<p>Expected at: {page_path}</p></body></html>",
                        status_code=404
                    )

            app.routes.append(Route("/architecture", rest_architecture_page, methods=["GET"]))

            print("[Server] Registered dashboard REST endpoints (/state, /qa, /gallery, /gallery-page, /layers, /architecture, /message, /learning, /voice)", file=sys.stderr, flush=True)

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
