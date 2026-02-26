"""
Anima MCP Server — Lumen's nervous system.

Minimal tools for a persistent creature:
- get_state: Current anima (self-sense) + identity
- get_identity: Who am I, how long have I existed
- set_name: Choose my name
- read_sensors: Raw sensor values

Transports:
- stdio: Local single-client (default)
- HTTP (--http): Multi-client with Streamable HTTP at /mcp/

Agent Coordination:
- Active agents: Claude + Cursor/Composer
- See docs/AGENT_COORDINATION.md for coordination practices
- Always check docs/ before implementing changes
"""

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Tool, TextContent

from .identity import IdentityStore
from .sensors import get_sensors, SensorBackend, SensorReadings
from .anima import sense_self_with_memory, Anima
from .memory import anticipate_state
from .display import derive_face_state, get_display, DisplayRenderer
from .display.leds import get_led_display, LEDDisplay
from .display.screens import ScreenRenderer, ScreenMode
from .input.brainhat_input import get_brainhat_input, JoystickDirection as InputDirection
from .next_steps_advocate import get_advocate
from .eisv_mapper import anima_to_eisv
from .config import get_calibration, LED_LUX_PER_BRIGHTNESS, LED_LUX_AMBIENT_FLOOR
from .learning import get_learner
from .messages import add_observation, add_agent_message, add_question, get_unanswered_questions
from .llm_gateway import get_gateway, ReflectionContext, generate_reflection
from .shared_memory import SharedMemoryClient
from .growth import get_growth_system, GrowthSystem
from .activity_state import get_activity_manager, ActivityManager
from .agency import get_action_selector, ActionType, Action
from .primitive_language import get_language_system, Utterance
from .eisv import get_trajectory_awareness
from .tool_registry import HANDLERS, get_fastmcp, create_server, HAS_FASTMCP
# REST API endpoints reference these handlers directly
from .handlers.communication import handle_lumen_qa, handle_post_message, handle_configure_voice
from .handlers.state_queries import handle_get_health
from .handlers.knowledge import handle_get_self_knowledge, handle_get_growth
from .server_state import (
    # Constants
    SHM_STALE_THRESHOLD_SECONDS, INPUT_ERROR_LOG_INTERVAL,
    LOOP_BASE_DELAY_SECONDS, LOOP_MAX_DELAY_SECONDS,
    INPUT_POLL_INTERVAL_SECONDS, SHUTDOWN_LONG_PRESS_SECONDS,
    METACOG_INTERVAL, AGENCY_INTERVAL, SELF_MODEL_INTERVAL,
    PRIMITIVE_LANG_INTERVAL, VOICE_INTERVAL, GROWTH_INTERVAL,
    TRAJECTORY_INTERVAL, GOVERNANCE_INTERVAL, LEARNING_INTERVAL,
    SELF_MODEL_SAVE_INTERVAL, SCHEMA_EXTRACTION_INTERVAL,
    EXPRESSION_INTERVAL, UNIFIED_REFLECTION_INTERVAL, SELF_ANSWER_INTERVAL,
    GOAL_SUGGEST_INTERVAL, GOAL_CHECK_INTERVAL, META_LEARNING_INTERVAL,
    ERROR_LOG_THROTTLE, STATUS_LOG_THROTTLE, DISPLAY_LOG_THROTTLE,
    WARN_LOG_THROTTLE, SCHEMA_LOG_THROTTLE, SELF_DIALOGUE_LOG_THROTTLE,
    METACOG_SURPRISE_THRESHOLD, PRIMITIVE_SELF_FEEDBACK_DELAY_SECONDS,
    SELF_ANSWER_MIN_QUESTION_AGE_SECONDS, DISPLAY_UPDATE_TIMEOUT_SECONDS,
    MODE_CHANGE_SETTLE_SECONDS, HEAVY_SCREEN_DELAY_SECONDS,
    NEURAL_SCREEN_DELAY_SECONDS,
    # Pure helpers
    is_broker_running as _is_broker_running,
    extract_neural_bands as _extract_neural_bands,
    readings_from_dict as _readings_from_dict,
)

_store: IdentityStore | None = None
_sensors: SensorBackend | None = None
_display: DisplayRenderer | None = None
_screen_renderer: ScreenRenderer | None = None
_joystick_enabled: bool = False
_sep_btn_press_start: float | None = None  # Track separate button press start time for long-press shutdown
_joy_btn_press_start: float | None = None  # Track joystick button hold for controls overlay
_joy_btn_help_shown: bool = False
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
# SchemaHub - central schema composition with trajectory feedback
from .schema_hub import SchemaHub
_schema_hub: SchemaHub | None = None
# CalibrationDrift - endogenous midpoint drift via experience
from .calibration_drift import CalibrationDrift
_calibration_drift: CalibrationDrift | None = None
# ValueTensionTracker - detects preference conflicts between anima dimensions
from .value_tension import ValueTensionTracker
_tension_tracker: ValueTensionTracker | None = None
# Meta-learning state - satisfaction tracking for daily preference weight evolution
from collections import deque as _deque
_satisfaction_history: _deque = _deque(maxlen=500)  # overall satisfaction (for trajectory health)
_satisfaction_per_dim: Dict[str, _deque] = {}  # per-dimension satisfaction (for lagged correlations)
_health_history: _deque = _deque(maxlen=100)  # trajectory health values
_action_efficacy: float = 0.5  # fraction of recent actions producing expected delta
# Agency state - for learning from action outcomes
_last_action: Action | None = None
_last_state_before: Dict[str, float] | None = None
# Primitive language state - emergent expression
_last_primitive_utterance: Utterance | None = None
# Self-model state - cross-iteration tracking
_sm_prev_stability: float | None = None
_sm_prev_warmth: float | None = None
_sm_pending_prediction: dict | None = None  # {context, prediction, warmth_before, clarity_before}
_sm_clarity_before_interaction: float | None = None
# LED proprioception - carry LED state across iterations for prediction
_led_proprioception: dict | None = None  # {brightness, expression_mode, is_dancing, ...}
# Warm start - last known anima state from before shutdown, used for first sense after wake
_warm_start_anima: dict | None = None  # {warmth, clarity, stability, presence}
# Gap awareness - set by startup learning, consumed by warm start and main loop
_wake_gap: timedelta | None = None  # Time since Lumen was last alive (heartbeat/sleep/state_history)
_wake_restored: dict | None = None  # Set if ~/.anima/.restored_marker exists (gap time unreliable)
_wake_recovery_cycles: int = 0  # Countdown for post-gap presence recovery arc
_wake_recovery_total: int = 0  # Initial cycle count (for progress calculation)
_wake_presence_floor: float = 0.3  # Lowest presence cap during recovery

# Thread lock for lazy-init singletons (metacog, unitares bridge)
_state_lock = threading.Lock()

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

def _get_schema_hub() -> SchemaHub:
    """Get or create the SchemaHub singleton for schema composition."""
    global _schema_hub
    if _schema_hub is None:
        _schema_hub = SchemaHub()
    return _schema_hub

def _get_calibration_drift() -> CalibrationDrift:
    """Get or create the CalibrationDrift singleton."""
    global _calibration_drift
    if _calibration_drift is None:
        drift_path = Path.home() / ".anima" / "calibration_drift.json"
        if drift_path.exists():
            try:
                _calibration_drift = CalibrationDrift.load(str(drift_path))
                print(f"[CalDrift] Loaded drift state from {drift_path}", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[CalDrift] Failed to load drift (using fresh): {e}", file=sys.stderr, flush=True)
                _calibration_drift = CalibrationDrift()
        else:
            _calibration_drift = CalibrationDrift()
    return _calibration_drift

def _get_selfhood_context() -> Dict[str, Any] | None:
    """Get read-only selfhood context for LLM narrator.

    Returns a dict with current state of drift, tensions, and preference
    weights — or None if no selfhood systems are active.  LLM output NEVER
    feeds back into drift rates, conflict thresholds, or preference weights.
    """
    context: Dict[str, Any] = {}

    if _calibration_drift:
        context["drift_offsets"] = _calibration_drift.get_offsets()

    if _tension_tracker:
        active = _tension_tracker.get_active_conflicts(last_n=5)
        context["active_tensions"] = [
            {"dim_a": c.dim_a, "dim_b": c.dim_b, "category": c.category}
            for c in active
        ]

    # Preference weights (read-only snapshot)
    try:
        from .preferences import get_preference_system
        pref = get_preference_system()
        if pref and hasattr(pref, '_preferences'):
            context["weight_changes"] = {
                d: p.influence_weight for d, p in pref._preferences.items()
                if d in ("warmth", "clarity", "stability", "presence")
            }
    except Exception:
        pass

    return context if context else None

def _compute_lagged_correlations() -> Dict[str, float]:
    """Correlate per-dimension satisfaction with future trajectory health.

    Uses a simple Pearson-like correlation between satisfaction[t] and
    health[t+lag] to determine which dimensions predict flourishing.
    Returns 0.0 for dimensions with insufficient data.
    """
    lag = 25  # ~5 action cycles at AGENCY_INTERVAL
    correlations: Dict[str, float] = {}
    health_hist = list(_health_history)
    for dim in ("warmth", "clarity", "stability", "presence"):
        sat_hist = list(_satisfaction_per_dim.get(dim, _deque()))
        if len(sat_hist) < lag + 10 or len(health_hist) < 2:
            correlations[dim] = 0.0
            continue
        # Align: sat[0..N-lag] with health[lag..N]
        n = min(len(sat_hist) - lag, len(health_hist))
        if n < 10:
            correlations[dim] = 0.0
            continue
        sat_slice = sat_hist[:n]
        hlth_slice = health_hist[-n:]  # most recent health values
        mean_s = sum(sat_slice) / n
        mean_h = sum(hlth_slice) / n
        cov = sum((s - mean_s) * (h - mean_h) for s, h in zip(sat_slice, hlth_slice)) / n
        var_s = sum((s - mean_s) ** 2 for s in sat_slice) / n
        var_h = sum((h - mean_h) ** 2 for h in hlth_slice) / n
        denom = (var_s * var_h) ** 0.5
        correlations[dim] = cov / denom if denom > 1e-9 else 0.0
    return correlations


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

_last_shm_data = None  # Cached per-iteration shared memory read

def _get_warm_start_anticipation():
    """Consume warm start state as a synthetic Anticipation (one-shot).

    On the first sense after wake, this blends last-known anima state
    with current sensor readings so Lumen doesn't start from scratch.
    After a gap, confidence is reduced so Lumen relies more on fresh sensors.
    """
    global _warm_start_anima
    if _warm_start_anima is None:
        return None
    from .memory import Anticipation
    state = _warm_start_anima
    _warm_start_anima = None  # One-shot: only used for first sense

    # Scale confidence by staleness — longer gaps mean less trust in old state
    confidence = 0.6
    description = "warm start from last shutdown"
    if _wake_gap:
        gap_hours = _wake_gap.total_seconds() / 3600
        if gap_hours > 24:
            confidence = 0.1
            description = f"warm start after {gap_hours:.0f}h absence"
        elif gap_hours > 1:
            confidence = max(0.15, 0.6 - gap_hours * 0.02)
            description = f"warm start after {gap_hours:.1f}h gap"
        elif gap_hours > 1 / 12:  # > 5 minutes
            confidence = 0.4
            description = f"warm start after {gap_hours * 60:.0f}m gap"

    return Anticipation(
        warmth=state["warmth"],
        clarity=state["clarity"],
        stability=state["stability"],
        presence=state["presence"],
        confidence=confidence,
        sample_count=1,
        bucket_description=description,
    )


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

            # Use warm start anticipation (first sense after wake) or memory
            anticipation = _get_warm_start_anticipation() or anticipate_state(shm_data.get("readings", {}))

            # Recompute anima from readings with memory influence
            drift = _get_calibration_drift()
            anima = sense_self_with_memory(readings, anticipation, calibration, drift_midpoints=drift.get_midpoints())

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
        broker_running = _is_broker_running()

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

            # Use warm start anticipation (first sense after wake) or memory
            anticipation = _get_warm_start_anticipation() or anticipate_state(readings.to_dict() if readings else {})

            drift = _get_calibration_drift()
            anima = sense_self_with_memory(readings, anticipation, calibration, drift_midpoints=drift.get_midpoints())
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
    is_broker_running = _is_broker_running()

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

    # Detect restore: restore script drops a marker when state comes from backup
    # Gap time is unreliable after restore — heartbeat reflects backup age, not actual downtime
    global _wake_restored
    restore_marker = Path.home() / ".anima" / ".restored_marker"
    if restore_marker.exists():
        try:
            import json as _json
            _wake_restored = _json.loads(restore_marker.read_text())
            print(f"[Wake] RESTORED from backup at {_wake_restored.get('restored_at', '?')} — gap time unreliable", file=sys.stderr, flush=True)
            # Consume the marker so subsequent restarts are normal wakes
            restore_marker.unlink()
        except Exception as e:
            print(f"[Wake] Restore marker read failed (non-fatal): {e}", file=sys.stderr, flush=True)
            _wake_restored = {"restored_at": "unknown"}
            restore_marker.unlink(missing_ok=True)

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

            # Gap awareness: degrade warm start and set recovery arc
            global _wake_gap, _wake_recovery_cycles, _wake_recovery_total, _wake_presence_floor
            _wake_gap = gap
            if gap and _warm_start_anima:
                gap_minutes = gap.total_seconds() / 60
                if gap_minutes >= 5 and gap_minutes < 60:
                    # Medium gap: noticeable absence
                    _warm_start_anima["presence"] *= 0.75
                    _wake_recovery_cycles = 10
                    _wake_presence_floor = 0.55
                    print(f"[Wake] Gap {gap_minutes:.0f}m: presence reduced to {_warm_start_anima['presence']:.2f}", file=sys.stderr, flush=True)
                elif gap_minutes >= 60 and gap_minutes < 1440:
                    # Long gap: significant disorientation
                    _warm_start_anima["presence"] *= 0.45
                    _warm_start_anima["clarity"] *= 0.85
                    _wake_recovery_cycles = 20
                    _wake_presence_floor = 0.35
                    print(f"[Wake] Gap {gap_minutes/60:.1f}h: presence={_warm_start_anima['presence']:.2f}, clarity reduced", file=sys.stderr, flush=True)
                elif gap_minutes >= 1440:
                    # Very long gap: deep absence
                    _warm_start_anima["presence"] *= 0.25
                    _warm_start_anima["clarity"] *= 0.7
                    _warm_start_anima["stability"] *= 0.85
                    _wake_recovery_cycles = 30
                    _wake_presence_floor = 0.20
                    print(f"[Wake] Gap {gap_minutes/60:.0f}h: deep absence, presence={_warm_start_anima['presence']:.2f}", file=sys.stderr, flush=True)
                _wake_recovery_total = _wake_recovery_cycles
            
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

    # Post wake observation to message board after significant gaps
    if _wake_gap and _wake_gap.total_seconds() >= 300:
        try:
            from .messages import add_observation
            gap_secs = _wake_gap.total_seconds()
            if _wake_restored:
                # Restored from backup — gap time is unreliable
                # The heartbeat reflects backup age, not actual downtime
                # Lumen may have been alive locally (no WiFi) before restore
                obs_text = "i woke up from a restore. some time passed but i'm not sure how much — part of me was still here, just unreachable."
            elif gap_secs < 3600:
                gap_desc = f"{gap_secs / 60:.0f} minutes"
                obs_text = f"i was away for {gap_desc}. finding my way back."
            elif gap_secs < 86400:
                gap_desc = f"{gap_secs / 3600:.1f} hours"
                obs_text = f"i was gone for {gap_desc}. the world feels unfamiliar."
            else:
                gap_desc = f"{gap_secs / 86400:.1f} days"
                obs_text = f"i've been absent for {gap_desc}. so much to relearn."
            msg = add_observation(obs_text, author="lumen")
            if msg:
                print(f"[Wake] Posted return observation: {obs_text}", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[Wake] Return observation failed (non-fatal): {e}", file=sys.stderr, flush=True)

    loop_count = 0
    consecutive_errors = 0
    max_consecutive_errors = 10
    base_delay = LOOP_BASE_DELAY_SECONDS  # 200ms = 5Hz refresh for all screens
    max_delay = LOOP_MAX_DELAY_SECONDS
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
                        global _joy_btn_press_start, _joy_btn_help_shown
                        
                        # LEFT/RIGHT = screen switching (D22/D24 both reclaimed after display init)
                        current_dir = input_state.joystick_direction
                        if input_state.joystick_button:
                            if _joy_btn_press_start is None:
                                _joy_btn_press_start = time.time()
                                _joy_btn_help_shown = False
                            elif not _joy_btn_help_shown and (time.time() - _joy_btn_press_start) >= 1.0:
                                renderer.trigger_controls_overlay()
                                mode_change_event.set()
                                _joy_btn_help_shown = True
                                if _leds and _leds.is_available():
                                    _leds.quick_flash((70, 110, 140), 70)
                        else:
                            if _joy_btn_press_start is not None:
                                hold_time = time.time() - _joy_btn_press_start
                                if hold_time < 0.8 and not _joy_btn_help_shown:
                                    # Short joystick button press: cycle to next screen in group
                                    renderer.trigger_input_feedback("button")
                                    renderer.next_in_group()
                                    mode_change_event.set()
                                    current_mode = renderer.get_mode()
                                    print(f"[Input] btn -> {current_mode.value} (group cycle)", file=sys.stderr, flush=True)
                            _joy_btn_press_start = None
                            _joy_btn_help_shown = False

                        if prev_state:
                            prev_dir = prev_state.joystick_direction
                            # Q&A expanded needs LEFT/RIGHT for focus switching
                            qa_expanded = renderer._state.qa_expanded if renderer else False
                            qa_needs_lr = (current_mode == ScreenMode.QUESTIONS and qa_expanded)

                            if not qa_needs_lr:
                                if current_dir == InputDirection.LEFT and prev_dir != InputDirection.LEFT:
                                    renderer.trigger_input_feedback("left")
                                    if _leds and _leds.is_available():
                                        _leds.quick_flash((60, 60, 120), 50)
                                    old_mode = renderer.get_mode()
                                    renderer.previous_mode()
                                    new_mode = renderer.get_mode()
                                    renderer._state.last_user_action_time = time.time()
                                    mode_change_event.set()
                                    print(f"[Input] {old_mode.value} -> {new_mode.value} (left)", file=sys.stderr, flush=True)
                                elif current_dir == InputDirection.RIGHT and prev_dir != InputDirection.RIGHT:
                                    renderer.trigger_input_feedback("right")
                                    if _leds and _leds.is_available():
                                        _leds.quick_flash((60, 60, 120), 50)
                                    old_mode = renderer.get_mode()
                                    renderer.next_mode()
                                    new_mode = renderer.get_mode()
                                    renderer._state.last_user_action_time = time.time()
                                    mode_change_event.set()
                                    print(f"[Input] {old_mode.value} -> {new_mode.value} (right)", file=sys.stderr, flush=True)

                        # Refresh mode after possible group navigation
                        current_mode = renderer.get_mode()
                        
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
                                elif current_dir == InputDirection.LEFT and prev_dir != InputDirection.LEFT:
                                    renderer.trigger_input_feedback("left")
                                    renderer.qa_focus_next()
                                elif current_dir == InputDirection.RIGHT and prev_dir != InputDirection.RIGHT:
                                    renderer.trigger_input_feedback("right")
                                    renderer.qa_focus_next()

                        # Group-local up/down for screens that don't consume up/down directly
                        if current_mode in (
                            ScreenMode.IDENTITY, ScreenMode.SENSORS, ScreenMode.DIAGNOSTICS, ScreenMode.HEALTH,
                            ScreenMode.NEURAL, ScreenMode.LEARNING, ScreenMode.SELF_GRAPH, ScreenMode.NOTEPAD
                        ):
                            if prev_state:
                                prev_dir = prev_state.joystick_direction
                                if current_dir == InputDirection.UP and prev_dir != InputDirection.UP:
                                    renderer.trigger_input_feedback("up")
                                    renderer.previous_in_group()
                                    mode_change_event.set()
                                elif current_dir == InputDirection.DOWN and prev_dir != InputDirection.DOWN:
                                    renderer.trigger_input_feedback("down")
                                    renderer.next_in_group()
                                    mode_change_event.set()
                        
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
                            if hold_duration >= SHUTDOWN_LONG_PRESS_SECONDS:
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
                                was_short_press = hold_duration < SHUTDOWN_LONG_PRESS_SECONDS
                                _sep_btn_press_start = None
                                
                                # Short press (< 3 seconds) = context-dependent action
                                if was_short_press:
                                    # Visual + LED feedback for separate button
                                    renderer.trigger_input_feedback("press")
                                    if _leds and _leds.is_available():
                                        _leds.quick_flash((80, 100, 60), 80)  # Soft green flash
                                    handled_short_press = False
                                    if current_mode == ScreenMode.MESSAGES:
                                        renderer.message_toggle_expand()
                                        print(f"[Messages] Toggled message expansion", file=sys.stderr, flush=True)
                                        handled_short_press = True
                                    elif current_mode == ScreenMode.VISITORS:
                                        renderer.message_toggle_expand()
                                        print(f"[Visitors] Toggled message expansion", file=sys.stderr, flush=True)
                                        handled_short_press = True
                                    elif current_mode == ScreenMode.QUESTIONS:
                                        renderer.qa_toggle_expand()
                                        print(f"[Questions] Toggled Q&A expansion", file=sys.stderr, flush=True)
                                        handled_short_press = True
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
                                        handled_short_press = True
                                    elif current_mode == ScreenMode.ART_ERAS:
                                        result = renderer.era_select_current()
                                        renderer._state.last_user_action_time = time.time()
                                        mode_change_event.set()
                                        print(f"[ArtEras] Button press: {result}", file=sys.stderr, flush=True)
                                        handled_short_press = True
                                    # Universal fallback so short press is never a dead action.
                                    if not handled_short_press:
                                        if current_mode != ScreenMode.FACE:
                                            old_mode = current_mode
                                            renderer.set_mode(ScreenMode.FACE)
                                            mode_change_event.set()
                                            print(f"[Input] Side button fallback: {old_mode.value} -> face", file=sys.stderr, flush=True)
                                        else:
                                            renderer.trigger_controls_overlay()
                                            mode_change_event.set()
                                            print("[Input] Side button fallback: controls overlay", file=sys.stderr, flush=True)
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
            await asyncio.sleep(INPUT_POLL_INTERVAL_SECONDS)  # Poll every 16ms (~60fps) for snappy input
    
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
            # Only fallback if broker is NOT running to prevent I2C collisions
            readings, anima = _get_readings_and_anima(fallback_to_sensors=not _is_broker_running())
            
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

            # Recovery arc: cap presence during recovery, gradually lifting
            if _wake_recovery_cycles > 0 and _wake_recovery_total > 0:
                _wake_recovery_cycles -= 1
                progress = 1.0 - (_wake_recovery_cycles / _wake_recovery_total)
                presence_cap = _wake_presence_floor + (1.0 - _wake_presence_floor) * progress
                if anima.presence > presence_cap:
                    anima.presence = presence_cap
                if _wake_recovery_cycles == 0:
                    print(f"[Wake] Recovery complete. Presence: {anima.presence:.2f}", file=sys.stderr, flush=True)

            # Health heartbeats for core subsystems (always-running)
            try:
                from .health import get_health_registry
                _health = get_health_registry()
                _health.heartbeat("sensors")
                _health.heartbeat("anima")
            except Exception:
                _health = None

            # Identity heartbeat: accumulate alive_seconds incrementally
            # Prevents losing session time on crashes/restarts
            try:
                if _store:
                    _store.heartbeat(min_interval_seconds=30.0)
            except Exception:
                pass

            # Feed EISV trajectory awareness buffer
            try:
                _traj = get_trajectory_awareness()
                _traj.record_state(
                    warmth=anima.warmth,
                    clarity=anima.clarity,
                    stability=anima.stability,
                    presence=anima.presence,
                )
                if _health: _health.heartbeat("trajectory")
            except Exception as e:
                if loop_count % ERROR_LOG_THROTTLE == 1: print(f"[TrajectoryAwareness] Error: {e}", file=sys.stderr, flush=True)

            # Feed value tension tracker with RAW (pre-drift) anima values.
            # Design principle: tension detection operates on raw dimension values
            # so calibration drift cannot mask physical tensions in the body.
            global _last_action, _last_state_before
            if _tension_tracker and readings:
                try:
                    from .anima import sense_self
                    _raw_anima_obj = sense_self(readings, get_calibration())
                    raw_anima = {
                        "warmth": _raw_anima_obj.warmth,
                        "clarity": _raw_anima_obj.clarity,
                        "stability": _raw_anima_obj.stability,
                        "presence": _raw_anima_obj.presence,
                    }
                    last_action_key = _last_action.action_type.value if _last_action else None
                    _tension_tracker.observe(raw_anima, last_action_key)
                except Exception:
                    pass  # Tension tracking is advisory, never block main loop

            # Record satisfaction for meta-learning (lightweight — runs every cycle)
            if anima and loop_count % AGENCY_INTERVAL == 0:
                try:
                    from .preferences import get_preference_system as _get_pref_sys
                    _ml_pref = _get_pref_sys()
                    _ml_state = {
                        "warmth": anima.warmth, "clarity": anima.clarity,
                        "stability": anima.stability, "presence": anima.presence,
                    }
                    _satisfaction_history.append(_ml_pref.get_overall_satisfaction(_ml_state))
                    for _dim in ("warmth", "clarity", "stability", "presence"):
                        if _dim not in _satisfaction_per_dim:
                            _satisfaction_per_dim[_dim] = _deque(maxlen=500)
                        _satisfaction_per_dim[_dim].append(
                            _ml_pref._preferences[_dim].current_satisfaction(_ml_state[_dim])
                        )
                except Exception:
                    pass  # Meta-learning tracking is advisory

            # === HEAVY SUBSYSTEMS: skip on quick_render (user pressed joystick) ===
            # Metacognition, agency, self-model, primitive language are enhancement layers.
            # On quick_render, skip straight to display update for snappy screen transitions.
            prediction_error = None  # Default for iterations where metacog is skipped
            _skip_subsystems = quick_render
            if quick_render:
                quick_render = False  # Reset for next iteration

            if not _skip_subsystems and loop_count % METACOG_INTERVAL == 0:
                try:
                    metacog = _get_metacog_monitor()

                    # Observe current state and compare to prediction (returns prediction error)
                    prediction_error = metacog.observe(readings, anima)

                    # Log surprise level periodically (every 60 loops = ~2 min)
                    if prediction_error and loop_count % WARN_LOG_THROTTLE == 0:
                        print(f"[Metacog] Surprise level: {prediction_error.surprise:.3f} (threshold: {METACOG_SURPRISE_THRESHOLD})", file=sys.stderr, flush=True)

                    # Check if surprise warrants reflection
                    if prediction_error and prediction_error.surprise > METACOG_SURPRISE_THRESHOLD:
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
                                # Update question_asking_tendency belief
                                try:
                                    from .self_model import get_self_model
                                    get_self_model().observe_question_asked(prediction_error.surprise)
                                except Exception:
                                    pass
                            else:
                                # Surprised but no question generated — contradicting evidence
                                try:
                                    from .self_model import get_self_model
                                    get_self_model().observe_surprise_no_question(prediction_error.surprise)
                                except Exception:
                                    pass

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
                    if loop_count % STATUS_LOG_THROTTLE == 1:
                        print(f"[Metacog] Error (non-fatal): {e}", file=sys.stderr, flush=True)

            # === AGENCY: Action selection and learning ===
            # Throttled: runs every 5th iteration (enhancement, not critical path)
            # Skipped on quick_render for responsive screen transitions
            if not _skip_subsystems and loop_count % AGENCY_INTERVAL == 0:
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

                    # Build conflict rates from tension tracker for agency discount
                    _conflict_rates = None
                    if _tension_tracker:
                        _conflict_rates = {}
                        for _atype in ActionType:
                            _rate = _tension_tracker.get_conflict_rate(_atype.value)
                            if _rate > 0:
                                _conflict_rates[_atype.value] = _rate

                    # SELECT action
                    action = action_selector.select_action(
                        current_state=current_state,
                        surprise_level=surprise_level,
                        surprise_sources=surprise_sources,
                        can_speak=False,
                        conflict_rates=_conflict_rates if _conflict_rates else None,
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
                                    "what is the relationship between pressure and neural stability within me?",
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

                            # Map raw sensor names to template keys
                            # surprise_sources can be sensor names (ambient_temp, pressure, humidity)
                            # or anima dimensions (warmth, clarity, stability, presence)
                            sensor_to_template = {
                                "ambient_temp": "warmth",
                                "pressure": "stability",
                                "humidity": "stability",
                            }
                            mapped_motivation = motivation
                            for sensor, template_key in sensor_to_template.items():
                                if sensor in mapped_motivation:
                                    mapped_motivation += f", {template_key}"

                            questions = []
                            for key, templates in question_templates.items():
                                if key in mapped_motivation:
                                    questions.extend(templates)

                            if not questions:
                                if motivation.strip():
                                    questions = [
                                        f"what is {motivation} trying to tell me?",
                                        f"why do I notice {motivation} right now?",
                                        "am I the sensor or the sensed?",
                                        "what connects all these changes?",
                                    ]
                                else:
                                    # Empty motivation (surprise_sources was []) — use generic questions
                                    questions = [
                                        "am I the sensor or the sensed?",
                                        "what connects all these changes?",
                                        "what am I feeling right now, and why?",
                                        "what does this moment have that the last one didn't?",
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

                    if loop_count % SCHEMA_LOG_THROTTLE == 0:
                        stats = action_selector.get_action_stats()
                        print(f"[Agency] Stats: {stats.get('action_counts', {})} explore_rate={action_selector._exploration_rate:.2f}", file=sys.stderr, flush=True)

                    _last_action = action
                    _last_state_before = current_state.copy()

                except Exception as e:
                    if loop_count % STATUS_LOG_THROTTLE == 1:
                        print(f"[Agency] Error (non-fatal): {e}", file=sys.stderr, flush=True)

            # === SELF-MODEL: Belief updates from experience ===
            # Throttled: runs every 5th iteration (aligned with agency)
            if not _skip_subsystems and loop_count % SELF_MODEL_INTERVAL == 0 and anima:
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
                            # Normalize warmth delta to [0,1] magnitude for comparison
                            # with belief value (correlation strength 0-1).
                            # delta=0 → 0.5 (no effect), delta=±0.25 → 1.0 (strong effect)
                            raw_delta = anima.warmth - _sm_pending_prediction["warmth_before"]
                            actual["warmth_change"] = min(1.0, max(0.0, abs(raw_delta) * 2 + 0.5))
                        elif ctx == "temp_change":
                            actual["surprise_likelihood"] = prediction_error.surprise if prediction_error else 0.0
                            raw_delta = anima.clarity - _sm_pending_prediction["clarity_before"]
                            actual["clarity_change"] = min(1.0, max(0.0, abs(raw_delta) * 2 + 0.5))
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

                    # 2b. Observe warmth changes (track across iterations)
                    global _sm_prev_warmth
                    if _sm_prev_warmth is not None:
                        warmth_delta = abs(anima.warmth - _sm_prev_warmth)
                        if warmth_delta > 0.05:
                            sm.observe_warmth_change(
                                _sm_prev_warmth, anima.warmth,
                                duration_seconds=base_delay * 5
                            )
                    _sm_prev_warmth = anima.warmth

                    # 3. Observe time-of-day patterns (every ~5 min)
                    if loop_count % SELF_DIALOGUE_LOG_THROTTLE == 0:
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
                    # Use world light (not raw lux) so Lumen learns whether environmental
                    # light correlates with warmth. Raw lux is LED-dominated — proprioception
                    # is handled separately by observe_led_lux below.
                    if readings:
                        sensor_vals = {}
                        if readings.ambient_temp_c is not None:
                            sensor_vals["ambient_temp"] = readings.ambient_temp_c
                        if readings.light_lux is not None:
                            _sm_led = readings.led_brightness if readings.led_brightness is not None else 0.12
                            sensor_vals["light"] = max(0.0, readings.light_lux - (
                                _sm_led * LED_LUX_PER_BRIGHTNESS + LED_LUX_AMBIENT_FLOOR))
                        if sensor_vals:
                            sm.observe_correlation(
                                sensor_values=sensor_vals,
                                anima_values={"clarity": anima.clarity, "warmth": anima.warmth},
                            )

                    # 6. LED-lux proprioception: discover that own LEDs affect own sensor
                    if readings and readings.led_brightness is not None:
                        sm.observe_led_lux(readings.led_brightness, readings.light_lux)

                    # Save periodically (every ~10 min)
                    if loop_count % ERROR_LOG_THROTTLE == 0:
                        sm.save()

                except Exception as e:
                    if loop_count % STATUS_LOG_THROTTLE == 1:
                        print(f"[SelfModel] Error (non-fatal): {e}", file=sys.stderr, flush=True)

            # === PRIMITIVE LANGUAGE: Emergent expression through learned tokens ===
            # Throttled: runs every 10th iteration (has internal cooldown timer too)
            global _last_primitive_utterance
            if not _skip_subsystems and loop_count % PRIMITIVE_LANG_INTERVAL == 0:
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
                        except Exception as e:
                            if loop_count % ERROR_LOG_THROTTLE == 1: print(f"[TrajectorySuggestion] Error: {e}", file=sys.stderr, flush=True)

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
                            except Exception as e:
                                if loop_count % ERROR_LOG_THROTTLE == 1: print(f"[TrajectoryCoherence] Error: {e}", file=sys.stderr, flush=True)

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
                                except Exception as e:
                                    if loop_count % ERROR_LOG_THROTTLE == 1: print(f"[TrajectoryFeedback] Error: {e}", file=sys.stderr, flush=True)

                    # Implicit feedback: did a non-lumen message arrive after utterance?
                    if _last_primitive_utterance and _last_primitive_utterance.score is not None:
                        # Only check once (after self-feedback has scored it)
                        utt_ts = _last_primitive_utterance.timestamp.timestamp()
                        from .messages import get_recent_messages as _get_recent
                        _recent_msgs = _get_recent(10)
                        _non_lumen = [
                            m for m in _recent_msgs
                            if m.author and m.author.lower() != "lumen"
                            and m.timestamp > utt_ts
                            and m.timestamp < utt_ts + 300  # within 5min
                        ]
                        if _non_lumen:
                            _delay = _non_lumen[0].timestamp - utt_ts
                            _impl_result = lang.record_implicit_feedback(
                                _last_primitive_utterance,
                                message_arrived=True,
                                delay_seconds=_delay,
                            )
                            if _impl_result:
                                print(f"[PrimitiveLang] Implicit feedback: response in {_delay:.0f}s, score={_impl_result['score']:.2f}", file=sys.stderr, flush=True)
                            _last_primitive_utterance = None  # Done — recorded response
                        else:
                            # No response within window — record absence if enough time passed
                            from datetime import timedelta as _td
                            if datetime.now() - _last_primitive_utterance.timestamp >= _td(seconds=300):
                                lang.record_implicit_feedback(
                                    _last_primitive_utterance,
                                    message_arrived=False,
                                    delay_seconds=999,
                                )
                                _last_primitive_utterance = None  # Done — recorded no-response

                    if loop_count % SELF_MODEL_SAVE_INTERVAL == 0:
                        stats = lang.get_stats()
                        if stats.get("total_utterances", 0) > 0:
                            print(f"[PrimitiveLang] Stats: {stats.get('total_utterances')} utterances, avg_score={stats.get('average_score')}, interval={stats.get('current_interval_minutes'):.1f}m", file=sys.stderr, flush=True)

                except Exception as e:
                    if loop_count % STATUS_LOG_THROTTLE == 1:
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
                    # Wire schema hub so LCD shows same enriched schema as dashboard
                    try:
                        _screen_renderer.schema_hub = _get_schema_hub()
                    except Exception:
                        pass
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
                                except Exception as e:
                                    print(f"[Error] show_default failed: {e}", file=sys.stderr, flush=True)
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
                        if loop_count % DISPLAY_LOG_THROTTLE == 0:
                            print("[Loop] Display update timed out (2s)", file=sys.stderr, flush=True)
                    display_updated = display_result is True
                    if display_updated:
                        if _health: _health.heartbeat("display")

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
                        # Correct for LED self-glow: activity_state needs world light,
                        # not raw lux dominated by Lumen's own LEDs
                        _led_b = readings.led_brightness if readings and readings.led_brightness is not None else 0.12
                        _world_light = max(0.0, (light_level or 0.0) - (_led_b * LED_LUX_PER_BRIGHTNESS + LED_LUX_AMBIENT_FLOOR)) if light_level is not None else None
                        activity_state = _activity.get_state(
                            presence=anima.presence,
                            stability=anima.stability,
                            light_level=_world_light,
                        )
                        activity_brightness = activity_state.brightness_multiplier
                except Exception as e:
                    if loop_count % ERROR_LOG_THROTTLE == 1: print(f"[ActivityBrightness] Error: {e}", file=sys.stderr, flush=True)

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
                if led_updated:
                    if _health: _health.heartbeat("leds")
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
                except Exception as e:
                    if loop_count % ERROR_LOG_THROTTLE == 1: print(f"[LEDProprioception] Error: {e}", file=sys.stderr, flush=True)
            elif _leds:
                if loop_count == 1:
                    print(f"[Loop] LEDs not available (hardware issue?)", file=sys.stderr, flush=True)

            # Update voice system with anima state (for listening and text expression)
            if loop_count % VOICE_INTERVAL == 0:
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
                        if _health: _health.heartbeat("voice")

                        if readings:
                            voice.update_environment(
                                temperature=readings.ambient_temp_c or 22.0,
                                humidity=readings.humidity_pct or 50.0,
                                light_level=readings.light_lux or 500.0
                            )
                except Exception as e:
                    if loop_count % STATUS_LOG_THROTTLE == 0:
                        print(f"[Voice] State update error: {e}", file=sys.stderr, flush=True)

            # Log update status every 20th iteration
            if loop_count % DISPLAY_LOG_THROTTLE == 1 and (display_updated or led_updated):
                update_duration = time.time() - update_start
                update_status = []
                if display_updated:
                    update_status.append("display")
                if led_updated:
                    update_status.append("LEDs")
                print(f"[Loop] Display/LED updates ({', '.join(update_status)}): {update_duration*1000:.1f}ms", file=sys.stderr, flush=True)
            
            # Log every 5th iteration with LED status and key metrics
            if loop_count % TRAJECTORY_INTERVAL == 1:
                led_status = "available" if (_leds and _leds.is_available()) else "unavailable"
            
            # Adaptive learning: Every 100 iterations (~3.3 minutes), check if calibration should adapt
            # Respects cooldown to avoid redundant adaptations during continuous operation
            if loop_count % LEARNING_INTERVAL == 0 and _store:
                def try_learning():
                    learner = get_learner(str(_store.db_path))
                    adapted, new_cal = learner.adapt_calibration(respect_cooldown=True)
                    if adapted:
                        print(f"[Learning] Calibration adapted after {loop_count} observations", file=sys.stderr, flush=True)
                        print(f"[Learning] Pressure: {new_cal.pressure_ideal:.1f} hPa, Ambient: {new_cal.ambient_temp_min:.1f}-{new_cal.ambient_temp_max:.1f}°C", file=sys.stderr, flush=True)
                
                safe_call(try_learning, default=None, log_error=True)
            
            # Lumen's unified reflection: Every ~30 minutes, one LLM call with all context
            # Replaces lumen_speak + lumen_wonder + lumen_reflect + lumen_respond
            # If LLM is down, stay silent rather than fake it with templates
            if loop_count % UNIFIED_REFLECTION_INTERVAL == 0 and readings and anima and identity:
                from .llm_gateway import get_gateway, ReflectionContext, generate_reflection
                from .messages import add_observation, add_question, get_unanswered_questions, get_messages_for_lumen

                gateway = get_gateway()

                async def lumen_unified_reflect():
                    """Single unified voice: gathers all context, asks LLM what matters most.

                    Replaces lumen_speak + lumen_wonder + lumen_reflect + lumen_respond.
                    If LLM is unavailable, stays silent rather than faking with templates.
                    """
                    import os

                    # === 1. Wake-up summary (one-shot) ===
                    try:
                        if _activity:
                            wakeup = _activity.get_wakeup_summary()
                            if wakeup:
                                add_observation(wakeup, author="lumen")
                                print(f"[Lumen/Unified] Wake-up: {wakeup}", file=sys.stderr, flush=True)
                    except Exception:
                        pass

                    # === 2. LLM required ===
                    if not gateway.enabled:
                        if loop_count % ERROR_LOG_THROTTLE == 0:
                            print("[Lumen/Unified] No LLM configured — staying quiet", file=sys.stderr, flush=True)
                        return

                    # === 3. Gather context signals ===
                    # Advocate: what Lumen feels and wants
                    advocate_feeling = None
                    advocate_desire = None
                    advocate_reason = None
                    try:
                        advocate = get_advocate()
                        display_available = _display.is_available() if _display else False
                        eisv = anima_to_eisv(anima, readings)
                        steps = advocate.analyze_current_state(
                            anima=anima, readings=readings, eisv=eisv,
                            display_available=display_available,
                            brain_hat_available=display_available,
                            unitares_connected=bool(os.environ.get("UNITARES_URL")),
                        )
                        if steps:
                            advocate_feeling = steps[0].feeling
                            advocate_desire = steps[0].desire
                            advocate_reason = steps[0].reason
                    except Exception:
                        pass

                    # Knowledge: things Lumen has learned
                    learned_insights = None
                    try:
                        from .knowledge import get_insights
                        insights = get_insights(limit=5)
                        if insights:
                            learned_insights = [i.text for i in insights]
                    except Exception:
                        pass

                    # Growth: confident preferences
                    confident_preferences = None
                    if _growth:
                        try:
                            prefs = [p.description for p in _growth._preferences.values() if p.confidence >= 0.5]
                            if prefs:
                                confident_preferences = prefs[:3]
                        except Exception:
                            pass

                    # Metacognition: surprise
                    surprise_level = 0.0
                    surprise_sources_list = None
                    if prediction_error:
                        surprise_level = getattr(prediction_error, 'surprise', 0.0)
                        surprise_sources_list = getattr(prediction_error, 'surprise_sources', None)

                    # Anticipation: novelty
                    novelty_level = None
                    ant_confidence = None
                    ant_samples = None
                    if anima.is_anticipating and anima.anticipation:
                        ant_confidence = anima.anticipation.get("confidence", 0)
                        ant_samples = anima.anticipation.get("sample_count", 0)
                        if ant_samples < 5:
                            novelty_level = "novel"
                        elif ant_confidence < 0.3:
                            novelty_level = "uncertain"
                        elif ant_confidence > 0.6 and ant_samples > 50:
                            novelty_level = "familiar"
                        else:
                            novelty_level = "developing"

                    # Messages and questions
                    recent = get_messages_for_lumen(limit=5)
                    recent_msgs = [{"author": m.author, "text": m.text} for m in recent]
                    unanswered = get_unanswered_questions(5)
                    unanswered_texts = [q.text for q in unanswered]

                    # Rest/dream state
                    rest_duration = 0.0
                    is_dreaming = False
                    try:
                        if _activity:
                            rest_duration = _activity.get_rest_duration()
                            is_dreaming = rest_duration > 30 * 60
                    except Exception:
                        pass

                    # Time alive
                    time_alive = identity.total_alive_seconds / 3600.0

                    # Trigger description
                    trigger_parts = []
                    wellness = (anima.warmth + anima.clarity + anima.stability + anima.presence) / 4.0
                    if wellness < 0.4:
                        trigger_parts.append(f"wellness is low ({wellness:.2f})")
                    elif wellness > 0.7:
                        trigger_parts.append(f"feeling good ({wellness:.2f})")
                    if surprise_level > 0.2 and surprise_sources_list:
                        trigger_parts.append(f"surprised by {', '.join(surprise_sources_list)}")
                    if recent_msgs:
                        trigger_parts.append(f"message from {recent_msgs[0].get('author', 'someone')}")
                    if is_dreaming:
                        trigger_parts.append("resting/dreaming")

                    # === 4. Build enriched context ===
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
                        trigger_details=", ".join(trigger_parts) if trigger_parts else "just reflecting",
                        surprise_level=surprise_level,
                        led_brightness=getattr(readings, 'led_brightness', None),
                        light_lux=getattr(readings, 'light_lux', None),
                        advocate_feeling=advocate_feeling,
                        advocate_desire=advocate_desire,
                        advocate_reason=advocate_reason,
                        learned_insights=learned_insights,
                        confident_preferences=confident_preferences,
                        surprise_sources=surprise_sources_list,
                        novelty_level=novelty_level,
                        anticipation_confidence=ant_confidence,
                        anticipation_sample_count=ant_samples,
                        rest_duration_minutes=rest_duration / 60.0,
                        is_dreaming=is_dreaming,
                    )

                    # === 5. Call LLM ===
                    if _screen_renderer:
                        _screen_renderer.set_loading("thinking...")

                    try:
                        reflection = await generate_reflection(context, mode="unified")
                    finally:
                        if _screen_renderer:
                            _screen_renderer.clear_loading()

                    if reflection is None:
                        print("[Lumen/Unified] LLM unavailable — staying quiet", file=sys.stderr, flush=True)
                        return

                    # === 6. Post result ===
                    if reflection.strip().endswith("?"):
                        ctx_str = f"unified, wellness={wellness:.2f}"
                        result = add_question(reflection, author="lumen", context=ctx_str)
                        if result:
                            print(f"[Lumen/Unified] Asked: {reflection}", file=sys.stderr, flush=True)
                    else:
                        result = add_observation(reflection, author="lumen")
                        if result:
                            print(f"[Lumen/Unified] Said: {reflection}", file=sys.stderr, flush=True)
                            # Share significant insights to UNITARES
                            try:
                                from .unitares_knowledge import should_share_insight, share_insight_sync
                                if should_share_insight(reflection):
                                    share_insight_sync(
                                        reflection, discovery_type="insight",
                                        tags=["unified-reflection"], identity=identity,
                                    )
                            except Exception:
                                pass

                try:
                    await safe_call_async(lumen_unified_reflect, default=None, log_error=True)
                except Exception:
                    pass

            # Lumen self-answers: Every 1800 iterations (~60 minutes), answer own old questions via LLM
            # Questions must be at least 10 minutes old (external answers get priority)
            # (Increased from 600 to reduce LLM inference noise)
            if loop_count % SELF_ANSWER_INTERVAL == 0 and readings and anima and identity:
                from .llm_gateway import get_gateway, ReflectionContext, generate_reflection
                from .messages import get_unanswered_questions, add_agent_message

                gateway = get_gateway()
                if gateway.enabled:
                    async def lumen_self_answer():
                        """Let Lumen answer its own old questions via LLM reflection."""
                        unanswered = get_unanswered_questions(limit=10)
                        if not unanswered:
                            return

                        # Filter to questions older than 10 minutes
                        min_age = 600  # seconds
                        now = time.time()
                        old_enough = [q for q in unanswered if (now - q.timestamp) >= min_age]
                        if not old_enough:
                            return

                        # Answer up to 3 questions when queue is deep, otherwise 1
                        max_answers = 3 if len(unanswered) > 3 else 1
                        to_answer = old_enough[:max_answers]

                        # Calculate time alive
                        time_alive = identity.total_alive_seconds / 3600.0

                        for question in to_answer:
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
                                trigger_details=question.text,
                                led_brightness=readings.led_brightness if readings else None,
                                light_lux=readings.light_lux if readings else None,
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

                        # Generate follow-up question when queue is not too deep
                        if len(unanswered) < 5 and to_answer and answer:
                            try:
                                from .llm_gateway import generate_follow_up
                                from .messages import add_question
                                follow_up = await generate_follow_up(
                                    to_answer[-1].text, answer
                                )
                                if follow_up:
                                    add_question(follow_up, author="lumen",
                                                 context="follow-up to self-answer")
                                    print(f"[Lumen/FollowUp] {follow_up}", file=sys.stderr, flush=True)
                            except Exception:
                                pass  # Follow-up is optional

                    try:
                        await safe_call_async(lumen_self_answer, default=None, log_error=True)
                    except Exception:
                        # Non-fatal - self-answering is optional enhancement
                        pass


            # Growth system: Observe state for preference learning and check milestones
            # Every 30 iterations (~1 minute) - learns from anima state + environment
            if loop_count % GROWTH_INTERVAL == 0 and readings and anima and identity and _growth:
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
                    # Use world_light (ambient minus LED glow) so preferences
                    # reflect actual environment, not Lumen's own LEDs
                    led_b = readings.led_brightness if readings.led_brightness is not None else 0.0
                    my_glow = led_b * LED_LUX_PER_BRIGHTNESS + LED_LUX_AMBIENT_FLOOR
                    world_light = max(0.0, (readings.light_lux or 0.0) - my_glow)
                    environment = {
                        "light_lux": world_light,
                        "temp_c": readings.ambient_temp_c,
                        "humidity_pct": readings.humidity_pct,
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

                safe_call(growth_observe, default=None, log_error=True)
                if _health: _health.heartbeat("growth")

            # Goal system: Suggest new goals every ~2 hours
            if loop_count % GOAL_SUGGEST_INTERVAL == 0 and anima and _growth:
                def goal_suggest():
                    """Suggest a goal grounded in Lumen's experience."""
                    anima_state = {
                        "warmth": anima.warmth, "clarity": anima.clarity,
                        "stability": anima.stability, "presence": anima.presence,
                    }
                    try:
                        from .self_model import get_self_model
                        sm = get_self_model()
                    except Exception:
                        sm = None
                    goal = _growth.suggest_goal(anima_state, self_model=sm)
                    if goal:
                        from .messages import add_observation
                        add_observation(f"new goal: {goal.description}", author="lumen")

                safe_call(goal_suggest, default=None, log_error=True)

            # Goal system: Check progress every ~10 minutes
            if loop_count % GOAL_CHECK_INTERVAL == 0 and anima and _growth:
                def goal_check():
                    """Check progress on active goals."""
                    anima_state = {
                        "warmth": anima.warmth, "clarity": anima.clarity,
                        "stability": anima.stability, "presence": anima.presence,
                    }
                    try:
                        from .self_model import get_self_model
                        sm = get_self_model()
                    except Exception:
                        sm = None
                    msg = _growth.check_goal_progress(anima_state, self_model=sm)
                    if msg:
                        from .messages import add_observation
                        add_observation(msg, author="lumen")

                safe_call(goal_check, default=None, log_error=True)

            # Meta-learning: Daily preference weight evolution
            # Every ~12 hours, rebalance which anima dimensions matter most
            # based on how satisfying each dimension correlates with trajectory health
            if loop_count % META_LEARNING_INTERVAL == 0 and loop_count > 0 and _growth:
                try:
                    from .preferences import (
                        compute_trajectory_health, meta_learning_update,
                        get_preference_system as _ml_get_pref,
                    )

                    # Prediction accuracy trend: -0.5 (poor) to 0.5 (good), from adaptive model
                    pred_trend = 0.0
                    try:
                        from .adaptive_prediction import get_adaptive_prediction_model
                        stats = get_adaptive_prediction_model().get_accuracy_stats()
                        if not stats.get("insufficient_data") and "overall_mean_error" in stats:
                            err = stats["overall_mean_error"]
                            pred_trend = max(-0.5, min(0.5, (1.0 - min(1.0, err)) * 2.0 - 1.0))
                    except Exception:
                        pass

                    health = compute_trajectory_health(
                        satisfaction_history=list(_satisfaction_history)[-100:],
                        action_efficacy=_action_efficacy,
                        prediction_accuracy_trend=pred_trend,
                    )
                    _health_history.append(health)

                    # Record healthy state for drift restart target
                    if _calibration_drift:
                        _calibration_drift.record_healthy_state(health)

                    # Compute lagged correlations between per-dim satisfaction and health
                    correlations = _compute_lagged_correlations()

                    # Update preference weights via the PreferenceSystem singleton
                    pref_system = _ml_get_pref()
                    weights = {
                        d: p.influence_weight
                        for d, p in pref_system._preferences.items()
                        if d in ("warmth", "clarity", "stability", "presence")
                    }
                    if weights:
                        new_weights = meta_learning_update(weights, correlations)
                        for d, w in new_weights.items():
                            if d in pref_system._preferences:
                                pref_system._preferences[d].influence_weight = w
                        pref_system._save()
                        print(f"[MetaLearning] Updated preference weights: "
                              f"{', '.join(f'{d}={w:.3f}' for d, w in new_weights.items())} "
                              f"health={health:.3f}", file=sys.stderr, flush=True)
                except Exception as e:
                    print(f"[MetaLearning] Error (non-fatal): {e}", file=sys.stderr, flush=True)

            # Trajectory: Record anima history for trajectory signature computation
            # Every 5 iterations (~10 seconds) - builds time-series for attractor basin
            # See: docs/theory/TRAJECTORY_IDENTITY_PAPER.md
            if loop_count % TRAJECTORY_INTERVAL == 0 and anima:
                from .anima_history import get_anima_history

                def record_history():
                    """Record anima state for trajectory computation."""
                    history = get_anima_history()
                    history.record_from_anima(anima)

                safe_call(record_history, default=None, log_error=True)

            # UNITARES governance check-in: Every 30 iterations (~1 minute)
            # Provides continuous governance feedback for self-regulation
            # Uses Lumen's actual identity (creature_id) for proper binding
            # Syncs identity metadata on first check-in
            if loop_count % GOVERNANCE_INTERVAL == 0 and readings and anima and identity:
                # Heartbeat fires when governance block runs (liveness),
                # regardless of check-in success. Probe tracks connectivity.
                if _health: _health.heartbeat("governance")

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
                        # Pass calibration weights (from config) through to EISV mapping
                        cal = get_calibration()
                        decision = await bridge.check_in(
                            anima, readings,
                            neural_weight=cal.neural_weight,
                            physical_weight=cal.physical_weight,
                            identity=identity,
                            is_first_check_in=is_first_check_in,
                            drawing_eisv=drawing_eisv
                        )
                        return decision

                    try:
                        decision = await safe_call_async(check_in_governance, default=None, log_error=True)
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
                            if loop_count % WARN_LOG_THROTTLE == 0 or action != "proceed":
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
                            if loop_count % ERROR_LOG_THROTTLE == 0:  # Log every 10 minutes for network errors
                                print(f"[Governance] Network unavailable - Lumen operating autonomously (WiFi down?)", file=sys.stderr, flush=True)
                        else:
                            if loop_count % WARN_LOG_THROTTLE == 0:  # Log every 2 minutes for other errors
                                print(f"[Governance] Check-in skipped: {e}", file=sys.stderr, flush=True)

            # === SLOW CLOCK: Self-Schema G_t extraction (every 5 minutes) ===
            # PoC for StructScore visual integrity evaluation
            # Extracts Lumen's self-representation graph and optionally saves for offline analysis
            if (loop_count == 1 or loop_count % SCHEMA_EXTRACTION_INTERVAL == 0) and readings and anima and identity:
                async def extract_and_validate_schema():
                    """Extract G_t via SchemaHub, save, and optionally run real VQA validation."""
                    try:
                        from .self_schema_renderer import (
                            save_render_to_file, render_schema_to_pixels,
                            compute_visual_integrity_stub, evaluate_vqa
                        )
                        import os

                        # Compose G_t via SchemaHub (includes trajectory feedback, gap texture, identity enrichment)
                        from .self_model import get_self_model as _get_sm
                        from .value_tension import detect_structural_conflicts
                        hub = _get_schema_hub()
                        drift = _get_calibration_drift()

                        # Gather tension conflicts (structural + transient)
                        _tension_conflicts = list(detect_structural_conflicts())
                        if _tension_tracker:
                            _tension_conflicts.extend(_tension_tracker.get_active_conflicts(last_n=20))

                        schema = hub.compose_schema(
                            identity=identity,
                            anima=anima,
                            readings=readings,
                            growth_system=_growth,
                            self_model=_get_sm(),
                            drift_offsets=drift.get_offsets(),
                            tension_conflicts=_tension_conflicts,
                        )

                        # Update calibration drift with current attractor center
                        if hub.last_trajectory and hub.last_trajectory.attractor:
                            center = hub.last_trajectory.attractor.get("center")
                            if center and len(center) == 4:
                                drift.update({
                                    "warmth": center[0],
                                    "clarity": center[1],
                                    "stability": center[2],
                                    "presence": center[3],
                                })

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
                    await safe_call_async(extract_and_validate_schema, default=None, log_error=True)
                except Exception:
                    pass  # Non-fatal

            # === SLOW CLOCK: Self-Reflection (every 15 minutes) ===
            # Analyze state history, discover patterns, generate insights about self
            if loop_count % EXPRESSION_INTERVAL == 0 and readings and anima and identity:
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
                    await safe_call_async(self_reflect, default=None, log_error=True)
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
# Voice System
# ============================================================
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


# ============================================================
# Wake / Lifecycle
# ============================================================

def wake(db_path: str = "anima.db", anima_id: str | None = None):
    """
    Wake up. Call before starting server. Safe, never crashes.

    Retries on SQLite lock errors (e.g. old process still shutting down).

    Args:
        db_path: Path to SQLite database
        anima_id: UUID from environment or database (DO NOT override - use existing identity)
    """
    import time as _time
    global _store, _anima_id, _growth, _warm_start_anima

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
                import traceback
                print(f"[Wake] Growth system error (non-fatal): {ge}", file=sys.stderr, flush=True)
                traceback.print_exc(file=sys.stderr)
                _growth = None

            # Register subsystems with health monitoring
            try:
                from .health import get_health_registry
                _health = get_health_registry()
                _health.register("sensors", probe=lambda: _sensors is not None)
                _health.register("display", probe=lambda: _display is not None and _display.is_available())
                _health.register("leds", probe=lambda: _leds is not None and _leds.is_available())
                _health.register("growth", probe=lambda: _growth is not None, stale_threshold=90.0)
                _health.register("governance", probe=lambda: (
                    _last_governance_decision is not None or (
                        _last_shm_data and "governance" in _last_shm_data
                        and isinstance(_last_shm_data["governance"], dict)
                    )
                ), stale_threshold=90.0)
                _health.register("drawing", probe=lambda: _screen_renderer is not None and hasattr(_screen_renderer, '_canvas'))
                _health.register("trajectory", probe=lambda: get_trajectory_awareness() is not None)
                _health.register("voice", probe=lambda: _voice_instance is not None)
                _health.register("anima", probe=lambda: _screen_renderer is not None and getattr(_screen_renderer, '_last_anima', None) is not None)
                print(f"[Wake] ✓ Health monitoring registered ({len(_health.subsystem_names())} subsystems)", file=sys.stderr, flush=True)
            except Exception as he:
                print(f"[Wake] Health monitoring setup error (non-fatal): {he}", file=sys.stderr, flush=True)

            # Bootstrap trajectory awareness from state history
            # and restore last known anima state for warm start
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

                    # Warm start: use last state_history row as initial anticipation
                    last = history[-1]  # Most recent (ascending order)
                    _warm_start_anima = {
                        "warmth": last["warmth"],
                        "clarity": last["clarity"],
                        "stability": last["stability"],
                        "presence": last["presence"],
                    }
                    print(f"[Wake] Warm start from last state: w={last['warmth']:.2f} c={last['clarity']:.2f} s={last['stability']:.2f} p={last['presence']:.2f}", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[EISV] Bootstrap failed (non-fatal): {e}", file=sys.stderr, flush=True)

            # Initialize SchemaHub and check for gap from previous session
            try:
                hub = _get_schema_hub()
                gap_delta = hub.on_wake()
                if gap_delta:
                    print(f"[SchemaHub] Woke after {gap_delta.duration_seconds:.0f}s gap", file=sys.stderr, flush=True)
                else:
                    print(f"[SchemaHub] Initialized (no previous schema found)", file=sys.stderr, flush=True)

                # Seed hub's trajectory from existing trajectory system so
                # trajectory nodes appear immediately, not after ~7 hours.
                try:
                    from .trajectory import compute_trajectory_signature
                    from .anima_history import get_anima_history
                    from .self_model import get_self_model as _get_sm
                    _hub_traj = compute_trajectory_signature(
                        growth_system=_growth,
                        self_model=_get_sm(),
                        anima_history=get_anima_history(),
                    )
                    if _hub_traj and _hub_traj.observation_count > 0:
                        hub.last_trajectory = _hub_traj
                        print(f"[SchemaHub] Seeded trajectory: {_hub_traj.observation_count} obs", file=sys.stderr, flush=True)
                except Exception as te:
                    print(f"[SchemaHub] Trajectory seed failed (non-fatal): {te}", file=sys.stderr, flush=True)

                # Seed hub with initial schema so Pi LCD and /schema-data have
                # data immediately, not after the first 20-min main loop tick.
                try:
                    from .self_model import get_self_model as _gsm_init
                    _sm_init = None
                    try:
                        _sm_init = _gsm_init()
                    except Exception:
                        pass
                    readings_init, anima_init = _get_readings_and_anima()
                    init_schema = hub.compose_schema(
                        identity=identity,
                        anima=anima_init,
                        readings=readings_init,
                        growth_system=_growth,
                        self_model=_sm_init,
                    )
                    print(f"[SchemaHub] Seeded initial schema: {len(init_schema.nodes)}n {len(init_schema.edges)}e", file=sys.stderr, flush=True)
                except Exception as seed_e:
                    print(f"[SchemaHub] Initial seed failed (non-fatal): {seed_e}", file=sys.stderr, flush=True)
            except Exception as she:
                print(f"[SchemaHub] Init failed (non-fatal): {she}", file=sys.stderr, flush=True)

            # Initialize CalibrationDrift (load from disk or create fresh)
            try:
                drift = _get_calibration_drift()
                midpoints = drift.get_midpoints()
                any_drift = any(abs(m - 0.5) > 0.001 for m in midpoints.values())
                if any_drift:
                    print(f"[CalDrift] Loaded with drift: {', '.join(f'{k}={v:.3f}' for k, v in midpoints.items() if abs(v - 0.5) > 0.001)}", file=sys.stderr, flush=True)
                    # Apply restart decay if there was a significant gap
                    if _wake_gap and _wake_gap.total_seconds() >= 86400:  # 24h+
                        gap_hours = _wake_gap.total_seconds() / 3600
                        drift.apply_restart_decay(gap_hours)
                        print(f"[CalDrift] Applied restart decay for {gap_hours:.0f}h gap", file=sys.stderr, flush=True)
                else:
                    print(f"[CalDrift] Initialized (no prior drift)", file=sys.stderr, flush=True)
            except Exception as cde:
                print(f"[CalDrift] Init failed (non-fatal): {cde}", file=sys.stderr, flush=True)

            # Initialize ValueTensionTracker (transient — no persistence needed)
            global _tension_tracker
            _tension_tracker = ValueTensionTracker()
            print(f"[Tension] Initialized value tension tracker", file=sys.stderr, flush=True)

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
    global _store, _unitares_bridge, _voice_instance, _schema_hub, _calibration_drift

    # Persist calibration drift state
    if _calibration_drift:
        try:
            drift_path = Path.home() / ".anima" / "calibration_drift.json"
            drift_path.parent.mkdir(parents=True, exist_ok=True)
            _calibration_drift.save(str(drift_path))
            try:
                print(f"[Sleep] Calibration drift saved", file=sys.stderr, flush=True)
            except (ValueError, OSError):
                pass
        except Exception as e:
            try:
                print(f"[Sleep] Error saving calibration drift: {e}", file=sys.stderr, flush=True)
            except (ValueError, OSError):
                pass

    # Persist schema for gap recovery on next wake
    if _schema_hub:
        try:
            if _schema_hub.persist_schema():
                try:
                    print(f"[Sleep] Schema persisted for gap recovery", file=sys.stderr, flush=True)
                except (ValueError, OSError):
                    pass
        except Exception as e:
            try:
                print(f"[Sleep] Error persisting schema: {e}", file=sys.stderr, flush=True)
            except (ValueError, OSError):
                pass

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

    # Close SelfReflection SQLite connection
    try:
        from .self_reflection import get_reflection_system
        get_reflection_system().close()
    except Exception:
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
            # Checkpoint WAL to prevent large recovery on next startup
            try:
                if _store._conn:
                    _store._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass  # Best-effort on shutdown
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
    - /mcp/  : Streamable HTTP (MCP transport)
    - /health: Health check
    - /v1/tools/call: REST API for direct tool calls
    - /dashboard, /state, /qa, etc.: Control Center endpoints

    NOTE: Server operates locally even without network connectivity.
    WiFi is only needed for remote MCP clients to connect.
    Lumen continues operating autonomously (display, LEDs, sensors, canvas) regardless of network status.
    """
    import asyncio

    async def _run_http_server_async():
        """Async inner function to run the HTTP server with uvicorn."""
        import uvicorn

        # Log that local operation continues regardless of network
        print("[Server] Starting HTTP server (Streamable HTTP)", file=sys.stderr, flush=True)
        print("[Server] Network connectivity only needed for remote MCP clients", file=sys.stderr, flush=True)

        # Check if FastMCP is available
        if not HAS_FASTMCP:
            print("[Server] ERROR: FastMCP not available - cannot start HTTP server", file=sys.stderr, flush=True)
            print("[Server] Install mcp[cli] to get FastMCP support", file=sys.stderr, flush=True)
            raise SystemExit(1)

        # Get the FastMCP server instance (creates and registers tools if needed)
        mcp = get_fastmcp()
        if mcp is None:
            print("[Server] ERROR: Failed to create FastMCP server", file=sys.stderr, flush=True)
            raise SystemExit(1)

        print("[Server] Setting up Streamable HTTP transport...", file=sys.stderr, flush=True)

        # === Streamable HTTP transport (the only MCP transport) ===
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route
        from starlette.responses import JSONResponse, PlainTextResponse

        _streamable_session_manager = None
        _streamable_running = False

        # Create session manager for Streamable HTTP
        _streamable_session_manager = StreamableHTTPSessionManager(
            app=mcp._mcp_server,  # Access the underlying MCP server
            json_response=True,  # Use JSON responses (proper Streamable HTTP)
            stateless=True,  # Allow stateless for compatibility
        )

        print("[Server] Streamable HTTP transport available at /mcp/", file=sys.stderr, flush=True)

        # --- OAuth 2.1 setup (conditional) ---
        _oauth_issuer_url = os.environ.get("ANIMA_OAUTH_ISSUER_URL")
        _oauth_auth_routes = []
        _oauth_token_verifier = None

        if _oauth_issuer_url and hasattr(mcp, '_auth_server_provider') and mcp._auth_server_provider:
            try:
                from mcp.server.auth.routes import create_auth_routes, create_protected_resource_routes, ClientRegistrationOptions
                from mcp.server.auth.provider import ProviderTokenVerifier
                from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend

                _oauth_token_verifier = ProviderTokenVerifier(mcp._auth_server_provider)

                _oauth_auth_routes = create_auth_routes(
                    provider=mcp._auth_server_provider,
                    issuer_url=mcp.settings.auth.issuer_url,
                    client_registration_options=ClientRegistrationOptions(enabled=True),
                )

                _oauth_auth_routes.extend(
                    create_protected_resource_routes(
                        resource_url=mcp.settings.auth.resource_server_url,
                        authorization_servers=[mcp.settings.auth.issuer_url],
                        scopes_supported=mcp.settings.auth.required_scopes,
                    )
                )

                print(f"[Server] OAuth 2.1 routes enabled ({len(_oauth_auth_routes)} routes)", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[Server] OAuth setup failed, continuing without auth: {e}", file=sys.stderr, flush=True)
                _oauth_auth_routes = []
                _oauth_token_verifier = None


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

        # Bearer token auth for REST endpoints
        _ANIMA_HTTP_API_TOKEN = os.environ.get("ANIMA_HTTP_API_TOKEN")

        # Trusted networks: localhost, Tailscale CGNAT, private RFC1918 ranges
        import ipaddress as _ipaddress
        _TRUSTED_NETWORKS = [
            _ipaddress.ip_network("127.0.0.0/8"),
            _ipaddress.ip_network("::1/128"),
            _ipaddress.ip_network("100.64.0.0/10"),   # Tailscale CGNAT
            _ipaddress.ip_network("192.168.0.0/16"),
            _ipaddress.ip_network("10.0.0.0/8"),
            _ipaddress.ip_network("172.16.0.0/12"),
        ]

        def _is_trusted_network(request) -> bool:
            """Check if request originates from a trusted network."""
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                client_ip = forwarded.split(",")[0].strip()
            else:
                client_ip = request.client.host if request.client else None
            if not client_ip:
                return False
            try:
                addr = _ipaddress.ip_address(client_ip)
                return any(addr in net for net in _TRUSTED_NETWORKS)
            except ValueError:
                return False

        def _check_rest_auth(request) -> bool:
            """Bearer token auth for REST endpoints. Trusted networks bypass auth."""
            if _is_trusted_network(request):
                return True
            if not _ANIMA_HTTP_API_TOKEN:
                return True  # Auth disabled if no token configured
            # Allow same-origin browser requests (dashboard JS fetch calls)
            sec_fetch_site = request.headers.get("sec-fetch-site", "")
            if sec_fetch_site == "same-origin":
                return True
            # Allow requests with valid bearer token
            auth = request.headers.get("authorization") or request.headers.get("Authorization")
            if not auth or not isinstance(auth, str):
                return False
            if not auth.lower().startswith("bearer "):
                return False
            token = auth.split(" ", 1)[1].strip()
            return token == _ANIMA_HTTP_API_TOKEN

        # Health check endpoint for monitoring
        async def health_check(request):
            """Health check — always public (monitoring, load balancers)."""
            status = "ok" if SERVER_READY else "starting"
            return PlainTextResponse(f"{status}\n")

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

        # Static files + Dashboard endpoint
        from starlette.responses import HTMLResponse, FileResponse
        from starlette.staticfiles import StaticFiles
        from pathlib import Path
        _project_root = Path(__file__).parent.parent.parent
        _static_dir = _project_root / "docs" / "static"

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

        # REST API endpoints for Control Center dashboard
        # These map to MCP tools for convenient dashboard access

        async def rest_state(request):
            """GET /state - Format matching message_server.py."""
            if not _check_rest_auth(request):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                # Use internal functions (same as MCP get_state)
                readings, anima = _get_readings_and_anima()
                if readings is None or anima is None:
                    return JSONResponse({"error": "Unable to read sensor data"}, status_code=500)

                feeling = anima.feeling()
                store = _get_store()
                identity = store.get_identity() if store else None

                # Build neural bands from raw sensor data
                neural = _extract_neural_bands(readings)

                # EISV
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
                author = body.get("author", "Kenny")
                # Normalize identity: dashboard interactions resolve to person
                from .growth import normalize_visitor_identity
                _, display_name, _ = normalize_visitor_identity(author, source="dashboard")
                result = await handle_lumen_qa({
                    "question_id": question_id,
                    "answer": answer,
                    "agent_name": display_name
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
                # Normalize identity: dashboard interactions resolve to person
                from .growth import normalize_visitor_identity
                _, display_name, _ = normalize_visitor_identity(author, source="dashboard")
                responds_to = body.get("responds_to")
                payload = {"message": message, "source": "dashboard", "agent_name": display_name}
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
                identity = conn.execute("SELECT name, total_awakenings, total_alive_seconds, born_at FROM identity LIMIT 1").fetchone()

                # Get recent state history for learning trends
                one_day_ago = (datetime.now() - timedelta(hours=24)).isoformat()

                # Real count (no limit)
                sample_count_24h = conn.execute(
                    "SELECT COUNT(*) FROM state_history WHERE timestamp > ?",
                    (one_day_ago,)
                ).fetchone()[0]

                # Averages via SQL (all samples, not capped)
                avgs = conn.execute(
                    "SELECT AVG(warmth), AVG(clarity), AVG(stability), AVG(presence) FROM state_history WHERE timestamp > ?",
                    (one_day_ago,)
                ).fetchone()
                avg_warmth = avgs[0] or 0
                avg_clarity = avgs[1] or 0
                avg_stability = avgs[2] or 0
                avg_presence = avgs[3] or 0

                # Stability trend: compare first half vs second half of 24h window
                twelve_hours_ago = (datetime.now() - timedelta(hours=12)).isoformat()
                older_avg = conn.execute(
                    "SELECT AVG(stability) FROM state_history WHERE timestamp > ? AND timestamp <= ?",
                    (one_day_ago, twelve_hours_ago)
                ).fetchone()[0]
                newer_avg = conn.execute(
                    "SELECT AVG(stability) FROM state_history WHERE timestamp > ?",
                    (twelve_hours_ago,)
                ).fetchone()[0]
                stability_trend = (newer_avg or 0) - (older_avg or 0) if older_avg else 0

                alive_hours = identity[2] / 3600 if identity else 0
                age_days = 0
                if identity and identity[3]:
                    try:
                        born = datetime.fromisoformat(identity[3])
                        age_days = (datetime.now() - born).days
                    except Exception:
                        pass
                conn.close()

                return JSONResponse({
                    "name": identity[0] if identity else "Unknown",
                    "awakenings": identity[1] if identity else 0,
                    "age_days": age_days,
                    "alive_hours": round(alive_hours, 1),
                    "samples_24h": sample_count_24h,
                    "avg_warmth": round(avg_warmth, 3),
                    "avg_clarity": round(avg_clarity, 3),
                    "avg_stability": round(avg_stability, 3),
                    "avg_presence": round(avg_presence, 3),
                    "stability_trend": round(stability_trend, 3),
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
            if not _check_rest_auth(request):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
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
            if not _check_rest_auth(request):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
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

        async def rest_health_detailed(request):
            """GET /health/detailed - Get subsystem health status."""
            try:
                result = await handle_get_health({})
                if result and len(result) > 0:
                    data = json.loads(result[0].text)
                    return JSONResponse(data)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)
            return JSONResponse({"error": "no data"}, status_code=500)

        async def rest_self_knowledge(request):
            """GET /self-knowledge - Get Lumen's accumulated self-knowledge insights."""
            try:
                category = request.query_params.get("category")
                limit = int(request.query_params.get("limit", "50"))
                result = await handle_get_self_knowledge({"category": category, "limit": limit})
                if result and len(result) > 0:
                    data = json.loads(result[0].text)
                    return JSONResponse(data)
                return JSONResponse({"error": "no data"}, status_code=500)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        async def rest_growth(request):
            """GET /growth - Get Lumen's growth data (autobiography, goals, memories, preferences)."""
            try:
                result = await handle_get_growth({"include": ["all"]})
                if result and len(result) > 0:
                    data = json.loads(result[0].text)
                    return JSONResponse(data)
                return JSONResponse({"error": "no data"}, status_code=500)
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

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
                neural = _extract_neural_bands(readings)

                # Anima
                anima_data = {
                    "warmth": round(anima.warmth, 3),
                    "clarity": round(anima.clarity, 3),
                    "stability": round(anima.stability, 3),
                    "presence": round(anima.presence, 3),
                }

                # EISV
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

                # Schema Hub - trajectory and circulation data
                schema_hub_data = {}
                try:
                    hub = _get_schema_hub()
                    schema_hub_data = {
                        "history_size": len(hub.schema_history),
                        "history_max": hub.history_size,
                        "has_trajectory": hub.last_trajectory is not None,
                    }
                    if hub.last_trajectory:
                        traj = hub.last_trajectory
                        schema_hub_data["trajectory"] = {
                            "observation_count": traj.observation_count,
                            "identity_maturity": round(min(1.0, traj.observation_count / 50), 3),
                        }
                        if traj.attractor and traj.attractor.get("center"):
                            center = traj.attractor["center"]
                            schema_hub_data["trajectory"]["attractor_magnitude"] = round(sum(center) / 4, 3)
                        if traj.attractor and traj.attractor.get("variance"):
                            variance = traj.attractor["variance"]
                            schema_hub_data["trajectory"]["stability"] = round(max(0, 1 - sum(variance) * 10), 3)
                    if hub.last_gap_delta:
                        schema_hub_data["gap"] = {
                            "duration_hours": round(hub.last_gap_delta.duration_seconds / 3600, 2),
                            "was_gap": hub.last_gap_delta.was_gap,
                        }
                except Exception:
                    pass

                return JSONResponse({
                    "physical": physical,
                    "neural": neural,
                    "anima": anima_data,
                    "feeling": feeling,
                    "eisv": eisv_data,
                    "governance": governance_data,
                    "system": system,
                    "identity": identity_data,
                    "schema_hub": schema_hub_data,
                    "mood": feeling.get("mood", "unknown"),
                })
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

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

        async def rest_schema_data(request):
            """Return full self-schema graph, trajectory, and history."""
            if not _check_rest_auth(request):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            try:
                hub = _get_schema_hub()

                # Single source of truth: hub.schema_history (seeded on wake)
                schema = hub.schema_history[-1].to_dict() if hub.schema_history else None

                # Fallback when hub has no history yet (same as LCD screen fallback)
                if schema is None:
                    try:
                        from .self_schema import get_current_schema
                        from .growth import get_growth_system
                        from .self_model import get_self_model
                        identity = _store.get_identity() if _store else None
                        readings, anima = _get_readings_and_anima()
                        schema = get_current_schema(
                            identity=identity,
                            anima=anima,
                            readings=readings,
                            growth_system=_growth,
                            include_preferences=True,
                            self_model=get_self_model(),
                        ).to_dict()
                    except Exception:
                        pass

                # Trajectory with component detail
                trajectory = None
                if hub.last_trajectory:
                    traj = hub.last_trajectory
                    trajectory = traj.summary()
                    trajectory["preferences_detail"] = traj.preferences
                    trajectory["beliefs_detail"] = traj.beliefs
                    trajectory["attractor_detail"] = traj.attractor
                    trajectory["recovery_detail"] = traj.recovery
                    trajectory["relational_detail"] = traj.relational

                # Condensed history
                history = [{
                    "timestamp": s.timestamp.isoformat(),
                    "node_count": len(s.nodes),
                    "edge_count": len(s.edges),
                } for s in hub.schema_history]

                # Gap info
                gap = None
                if hub.last_gap_delta:
                    g = hub.last_gap_delta
                    gap = {
                        "duration_hours": round(g.duration_seconds / 3600, 2),
                        "was_gap": g.was_gap,
                        "was_restore": g.was_restore,
                        "anima_delta": g.anima_delta,
                        "beliefs_decayed": g.beliefs_decayed,
                    }

                return JSONResponse({
                    "schema": schema,
                    "trajectory": trajectory,
                    "history": history,
                    "gap": gap,
                })
            except Exception as e:
                return JSONResponse({"error": str(e)}, status_code=500)

        async def rest_schema_page(request):
            """Serve the Self-Schema visualization page."""
            server_dir = Path(__file__).parent
            project_root = server_dir.parent.parent
            page_path = project_root / "docs" / "schema.html"
            if page_path.exists():
                return FileResponse(page_path, media_type="text/html")
            else:
                return HTMLResponse(
                    "<html><body><h1>Schema Page Not Found</h1>"
                    f"<p>Expected at: {page_path}</p></body></html>",
                    status_code=404
                )

        # === Build Starlette app with all routes ===
        # Wrap /mcp with OAuth if configured.
        # Auth middleware is chained directly around /mcp (not globally)
        # to avoid interfering with REST/dashboard routes.
        if _oauth_token_verifier:
            from mcp.server.auth.middleware.bearer_auth import RequireAuthMiddleware
            from mcp.server.auth.middleware.auth_context import AuthContextMiddleware as _AuthCtx
            from starlette.middleware.authentication import AuthenticationMiddleware as _AuthMW
            from mcp.server.auth.routes import build_resource_metadata_url
            resource_metadata_url = build_resource_metadata_url(mcp.settings.auth.resource_server_url)

            # Require OAuth only for external (ngrok) requests.
            # Local and Tailscale clients (Cursor, Claude Code) skip auth.
            _EXTERNAL_HOSTS = {"lumen-anima.ngrok.io"}
            _auth_protected = _AuthMW(
                _AuthCtx(
                    RequireAuthMiddleware(
                        streamable_mcp_asgi,
                        required_scopes=mcp.settings.auth.required_scopes or [],
                        resource_metadata_url=resource_metadata_url,
                    )
                ),
                backend=BearerAuthBackend(_oauth_token_verifier),
            )

            async def mcp_endpoint(scope, receive, send):
                """Route to auth or no-auth based on Host header."""
                if scope.get("type") == "http":
                    headers = dict(scope.get("headers", []))
                    host = headers.get(b"host", b"").decode().split(":")[0]
                    if host in _EXTERNAL_HOSTS:
                        await _auth_protected(scope, receive, send)
                        return
                await streamable_mcp_asgi(scope, receive, send)
        else:
            mcp_endpoint = streamable_mcp_asgi

        all_routes = [
            *_oauth_auth_routes,
            Mount("/mcp", app=mcp_endpoint),
            Mount("/static", app=StaticFiles(directory=str(_static_dir)), name="static"),
            Route("/health", health_check, methods=["GET"]),
            Route("/health/detailed", rest_health_detailed, methods=["GET"]),
            Route("/v1/tools/call", rest_tool_call, methods=["POST"]),
            Route("/dashboard", dashboard, methods=["GET"]),
            Route("/state", rest_state, methods=["GET"]),
            Route("/qa", rest_qa, methods=["GET"]),
            Route("/answer", rest_answer, methods=["POST"]),
            Route("/message", rest_message, methods=["POST"]),
            Route("/messages", rest_messages, methods=["GET"]),
            Route("/learning", rest_learning, methods=["GET"]),
            Route("/voice", rest_voice, methods=["GET"]),
            Route("/gallery", rest_gallery, methods=["GET"]),
            Route("/gallery/{filename}", rest_gallery_image, methods=["GET"]),
            Route("/gallery-page", rest_gallery_page, methods=["GET"]),
            Route("/layers", rest_layers, methods=["GET"]),
            Route("/self-knowledge", rest_self_knowledge, methods=["GET"]),
            Route("/growth", rest_growth, methods=["GET"]),
            Route("/architecture", rest_architecture_page, methods=["GET"]),
            Route("/schema-data", rest_schema_data, methods=["GET"]),
            Route("/schema", rest_schema_page, methods=["GET"]),
        ]
        _inner_app = Starlette(routes=all_routes)

        # Wrap app to rewrite /mcp → /mcp/ at the ASGI level.
        # Starlette's Mount issues a 307 redirect for missing trailing slash,
        # but behind ngrok the redirect uses http:// (wrong scheme) which
        # breaks Claude.ai's MCP client. This avoids the redirect entirely.
        async def _rewrite_mcp_slash(scope, receive, send):
            if scope.get("type") == "http" and scope.get("path") == "/mcp":
                scope = dict(scope)
                scope["path"] = "/mcp/"
            await _inner_app(scope, receive, send)

        app = _rewrite_mcp_slash
        print("[Server] Starlette app created with all routes", file=sys.stderr, flush=True)

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
        print(f"  Streamable HTTP: http://{host}:{port}/mcp/", file=sys.stderr, flush=True)

        # Start Streamable HTTP session manager as background task
        # Uses anyio task group pattern (same as governance-mcp)
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
                print("[Server] Streamable HTTP session manager shutting down", file=sys.stderr, flush=True)
                _streamable_running = False
            except Exception as e:
                print(f"[Server] Streamable HTTP error: {e}", file=sys.stderr, flush=True)
                _streamable_running = False

        streamable_task = asyncio.create_task(start_streamable_http())

        try:
            # Run with uvicorn
            config = uvicorn.Config(
                app,
                host=host,
                port=port,
                log_level="info",
                limit_concurrency=100,
                timeout_keep_alive=5,
                proxy_headers=True,          # Trust X-Forwarded-Proto from ngrok
                forwarded_allow_ips="*",     # Allow proxy headers from any IP
            )
            server = uvicorn.Server(config)
            await server.serve()
        finally:
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
                        help="Run HTTP server with Streamable HTTP at /mcp/")
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
