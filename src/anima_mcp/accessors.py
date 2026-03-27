"""
State accessors for the anima-mcp server.

All _get_* functions live here. They provide thread-safe, None-safe access
to ServerContext subsystems with lazy initialization.

_ctx is set by server.py's wake() via set_ctx() and cleared by sleep().
Server flags (SERVER_READY, etc.) remain in server.py.
"""

import logging
import os
import sys
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .sensors import get_sensors, SensorBackend, SensorReadings
from .anima import sense_self_with_memory, Anima
from .memory import anticipate_state
from .display import get_display, DisplayRenderer
from .shared_memory import SharedMemoryClient
from .config import get_calibration
from .server_context import ServerContext
from .server_state import (
    SHM_STALE_THRESHOLD_SECONDS,
    is_broker_running as _is_broker_running,
    readings_from_dict as _readings_from_dict,
)

# SchemaHub, CalibrationDrift — imported for type hints / lazy init
from .schema_hub import SchemaHub
from .calibration_drift import CalibrationDrift

logger = logging.getLogger("anima.server")

# ============================================================
# Global State
# ============================================================

# Thread lock for lazy-init singletons (metacog, unitares bridge)
_state_lock = threading.Lock()

# Server context — mutable state container. Created in wake(), cleared in sleep().
# Before wake(), _ctx is None. All accessors handle None.
_ctx: ServerContext | None = None

# VOICE_MODE controls how Lumen speaks: "text" (message board), "audio" (TTS), "both"
VOICE_MODE = os.environ.get("LUMEN_VOICE_MODE", "text")  # Default: text only


def set_ctx(ctx: "ServerContext | None"):
    """Set the server context. Called by server.py wake() and sleep()."""
    global _ctx
    _ctx = ctx


# ============================================================
# Accessors — safe, lazy, None-tolerant
# ============================================================

def _get_store():
    """Get identity store - safe, returns None if not available instead of crashing."""
    if _ctx is None:
        print("[Server] Warning: Store not initialized (wake() may have failed)", file=sys.stderr)
        return None
    return _ctx.store


def _get_sensors() -> SensorBackend:
    if _ctx is None:
        return get_sensors()  # Fallback when not yet woken
    if _ctx.sensors is None:
        _ctx.sensors = get_sensors()
    return _ctx.sensors


def _get_shm_client() -> SharedMemoryClient:
    """Get shared memory client for reading broker data."""
    if _ctx is None:
        return SharedMemoryClient(mode="read", backend="file")
    if _ctx.shm_client is None:
        _ctx.shm_client = SharedMemoryClient(mode="read", backend="file")
    return _ctx.shm_client


def _get_server_bridge():
    """Lazy UNITARES bridge for server-side fallback check-in.

    Only used when the broker's SHM governance is stale/local for too long.
    The server's native async event loop avoids the broker's thread+loop issues.
    """
    bridge = _ctx.server_bridge if _ctx else None
    if bridge is not None:
        return bridge
    unitares_url = os.environ.get("UNITARES_URL")
    if not unitares_url:
        return None
    try:
        from .unitares_bridge import UnitaresBridge
        bridge = UnitaresBridge(unitares_url=unitares_url, timeout=8.0)
        store = _get_store()
        if store:
            identity = store.get_identity()
            if identity:
                bridge.set_agent_id(identity.creature_id)
                bridge.set_session_id(f"anima-server-{identity.creature_id[:8]}")
        if _ctx:
            _ctx.server_bridge = bridge
        return bridge
    except Exception as e:
        logger.debug("[Governance] Bridge init failed: %s", e)
        return None


def _get_schema_hub() -> SchemaHub:
    """Get or create the SchemaHub singleton for schema composition."""
    if _ctx is None:
        return SchemaHub()  # Transient when not woken
    if _ctx.schema_hub is None:
        _ctx.schema_hub = SchemaHub()
    return _ctx.schema_hub


def _get_calibration_drift() -> CalibrationDrift:
    """Get or create the CalibrationDrift singleton."""
    if _ctx is None:
        return CalibrationDrift()
    if _ctx.calibration_drift is None:
        drift_path = Path.home() / ".anima" / "calibration_drift.json"
        if drift_path.exists():
            try:
                _ctx.calibration_drift = CalibrationDrift.load(str(drift_path))
                print(f"[CalDrift] Loaded drift state from {drift_path}", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[CalDrift] Failed to load drift (using fresh): {e}", file=sys.stderr, flush=True)
                _ctx.calibration_drift = CalibrationDrift()
        else:
            _ctx.calibration_drift = CalibrationDrift()
    return _ctx.calibration_drift


def _get_selfhood_context() -> Dict[str, Any] | None:
    """Get read-only selfhood context for LLM narrator.

    Returns a dict with current state of drift, tensions, and preference
    weights — or None if no selfhood systems are active.  LLM output NEVER
    feeds back into drift rates, conflict thresholds, or preference weights.
    """
    context: Dict[str, Any] = {}
    drift = _get_calibration_drift() if _ctx else None
    if drift:
        context["drift_offsets"] = drift.get_offsets()
    tension = _ctx.tension_tracker if _ctx else None
    if tension:
        active = tension.get_active_conflicts(last_n=5)
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
    except Exception as e:
        logger.debug("[Selfhood] Preference weight read error: %s", e)

    return context if context else None


def _get_metacog_monitor():
    """Get metacognitive monitor - Lumen's self-awareness through prediction errors."""
    if _ctx is None:
        return None
    if _ctx.metacog_monitor is None:
        with _state_lock:
            if _ctx.metacog_monitor is None:
                from .metacognition import MetacognitiveMonitor
                _ctx.metacog_monitor = MetacognitiveMonitor(
                    surprise_threshold=0.3,  # Trigger reflection at 30% surprise
                    reflection_cooldown_seconds=120.0,  # 2 min between reflections
                )
    return _ctx.metacog_monitor


def _get_warm_start_anticipation():
    """Consume warm start state as a synthetic Anticipation (one-shot).

    On the first sense after wake, this blends last-known anima state
    with current sensor readings so Lumen doesn't start from scratch.
    After a gap, confidence is reduced so Lumen relies more on fresh sensors.
    """
    if not _ctx or _ctx.warm_start_anima is None:
        return None
    from .memory import Anticipation
    state = _ctx.warm_start_anima
    _ctx.warm_start_anima = None  # One-shot: only used for first sense

    # Scale confidence by staleness — longer gaps mean less trust in old state
    confidence = 0.6
    description = "warm start from last shutdown"
    if _ctx.wake_gap:
        gap_hours = _ctx.wake_gap.total_seconds() / 3600
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
    # Try shared memory first (broker mode)
    # SharedMemoryClient.read() already returns envelope["data"] (the inner dict)
    shm_client = _get_shm_client()
    shm_data = shm_client.read()
    if _ctx:
        _ctx.last_shm_data = shm_data  # Cache for reuse within same iteration

    # Check if shared memory data is recent
    shm_stale = True
    shm_valid = False
    if shm_data:
        try:
            # Check if we have the required fields
            if "readings" in shm_data and "anima" in shm_data:
                # Check timestamp in shared memory data (broker writes "timestamp" field)
                timestamp_str = shm_data.get("timestamp")
                if timestamp_str:
                    timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                    age_seconds = (datetime.now(timestamp.tzinfo) - timestamp).total_seconds()
                    shm_stale = age_seconds > SHM_STALE_THRESHOLD_SECONDS
                    if not shm_stale:
                        shm_valid = True
                else:
                    # No timestamp - assume fresh if data exists
                    shm_valid = True
        except Exception as e:
            logger.debug("[Server] Error checking shared memory timestamp: %s", e)
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
            logger.debug("[Server] Error reading from shared memory: %s", e)
            import traceback
            traceback.print_exc(file=sys.stderr)
            # Fall through to sensor fallback

    # Fallback to direct sensor access if:
    # 1. Shared memory is empty/stale/invalid, OR
    # 2. fallback_to_sensors is True (always allow fallback)
    if fallback_to_sensors or not shm_valid:
        # Check if broker is running (for logging purposes)
        broker_running = _is_broker_running()

        # Log why we're falling back (throttled to avoid spam)
        import time as _time
        _now = _time.time()
        if not hasattr(_get_readings_and_anima, '_last_fallback_log'):
            _get_readings_and_anima._last_fallback_log = 0.0
        if _now - _get_readings_and_anima._last_fallback_log > 30.0:
            _get_readings_and_anima._last_fallback_log = _now
            if broker_running and not shm_valid:
                logger.debug("[Server] Broker running but shared memory %s - using direct sensor fallback", 'stale' if shm_stale else 'invalid/empty')
            elif not broker_running:
                logger.debug("[Server] Broker not running - using direct sensor access")

        try:
            sensors = _get_sensors()
            if sensors is None:
                logger.warning("[Server] Sensors not initialized - cannot read")
                return None, None

            readings = sensors.read()
            if readings is None:
                logger.debug("[Server] Sensor read returned None")
                return None, None

            calibration = get_calibration()

            # Use warm start anticipation (first sense after wake) or memory
            anticipation = _get_warm_start_anticipation() or anticipate_state(readings.to_dict() if readings else {})

            drift = _get_calibration_drift()
            anima = sense_self_with_memory(readings, anticipation, calibration, drift_midpoints=drift.get_midpoints())
            if anima is None:
                logger.warning("[Server] Failed to create anima from readings")
                return None, None

            return readings, anima
        except Exception as e:
            logger.warning("[Server] Error reading sensors directly: %s", e)
            import traceback
            traceback.print_exc(file=sys.stderr)

    return None, None


def _get_display() -> DisplayRenderer:
    if _ctx is None:
        return get_display()
    if _ctx.display is None:
        _ctx.display = get_display()
    return _ctx.display


def _get_last_shm_data() -> dict | None:
    """Cached per-iteration shared memory read. Used by handlers and display loop."""
    return _ctx.last_shm_data if _ctx else None


def _get_screen_renderer():
    return _ctx.screen_renderer if _ctx else None


def _get_leds():
    return _ctx.leds if _ctx else None


def _get_growth():
    return _ctx.growth if _ctx else None


def _get_display_update_task():
    return _ctx.display_update_task if _ctx else None


def _get_activity():
    return _ctx.activity if _ctx else None


def _get_last_governance_decision() -> dict | None:
    """Last governance decision from broker SHM or server fallback."""
    return _ctx.last_governance_decision if _ctx else None


def _get_voice():
    """Get or initialize the voice instance (for listening capability)."""
    if _ctx is None:
        return None
    if _ctx.voice_instance is None:
        try:
            from .audio import AutonomousVoice

            _ctx.voice_instance = AutonomousVoice()

            # Autonomous voice canned phrases ("I'm curious about something", etc.)
            # are not posted to message board — primitives are more authentic.
            # Voice system still runs for listening capability.
            _ctx.voice_instance.start()
            print(f"[Server] Voice system initialized (mode={VOICE_MODE}, listening enabled)", file=sys.stderr, flush=True)
        except ImportError:
            print("[Server] Voice module not available (missing dependencies)", file=sys.stderr, flush=True)
            return None
        except Exception as e:
            print(f"[Server] Voice initialization failed: {e}", file=sys.stderr, flush=True)
            return None
    return _ctx.voice_instance
