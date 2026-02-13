"""Trajectory awareness for Lumen's primitive language.

Maintains an in-memory ring buffer of recent anima states,
computes EISV trajectory classification, and provides
suggested tokens for the primitive language system.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Dict, List, Optional

from .mapping import (
    anima_to_eisv,
    compute_trajectory_window,
    classify_trajectory,
)
from .expression import (
    ExpressionGenerator,
    translate_expression,
    shape_to_lumen_trigger,
)


class TrajectoryAwareness:
    """EISV trajectory awareness for primitive language.

    Maintains an in-memory ring buffer of recent anima states,
    computes trajectory shapes, and suggests tokens for expressions.
    """

    # Minimum states needed for meaningful classification
    MIN_STATES = 5

    # Minimum seconds between buffer recordings (subsampling)
    RECORD_INTERVAL = 2.0

    def __init__(
        self,
        buffer_size: int = 30,
        cache_seconds: float = 60.0,
        seed: Optional[int] = None,
    ):
        self._buffer: deque = deque(maxlen=buffer_size)
        self._cache_seconds = cache_seconds
        self._generator = ExpressionGenerator(seed=seed)

        # Cache
        self._cached_result: Optional[Dict[str, Any]] = None
        self._cache_time: float = 0.0
        self._cache_buffer_len: int = 0

        # Tracking
        self._last_record_time: float = 0.0
        self._current_shape: Optional[str] = None

    def record_state(
        self,
        warmth: float,
        clarity: float,
        stability: float,
        presence: float,
    ) -> None:
        """Record an anima state snapshot into the trajectory buffer.

        Only records if at least RECORD_INTERVAL seconds have elapsed
        since the last recording (subsampling to avoid overfilling buffer).
        """
        now = time.time()
        if now - self._last_record_time < self.RECORD_INTERVAL:
            return

        eisv = anima_to_eisv(warmth, clarity, stability, presence)
        eisv["t"] = now
        self._buffer.append(eisv)
        self._last_record_time = now

    def bootstrap_from_history(self, state_records: List[Dict]) -> int:
        """Pre-fill buffer from historical state_history records.

        Parameters
        ----------
        state_records:
            List of dicts with 'timestamp' (ISO string), 'warmth', 'clarity',
            'stability', 'presence' keys. Should be in chronological order.

        Returns number of records added to buffer.
        """
        from datetime import datetime, timezone

        added = 0
        for rec in state_records:
            ts_str = rec.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(ts_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                t = dt.timestamp()
            except (ValueError, TypeError):
                continue

            eisv = anima_to_eisv(
                warmth=rec.get("warmth", 0.5),
                clarity=rec.get("clarity", 0.5),
                stability=rec.get("stability", 0.5),
                presence=rec.get("presence", 0.0),
            )
            eisv["t"] = t
            self._buffer.append(eisv)
            added += 1

        if added > 0:
            self._last_record_time = time.time()
        return added

    def get_trajectory_suggestion(
        self,
        lang_state: Optional[Dict[str, float]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Get trajectory-aware token suggestions.

        Returns None if insufficient data or on error.
        Otherwise returns dict with:
            shape, suggested_tokens, eisv_tokens, trigger
        """
        if len(self._buffer) < self.MIN_STATES:
            return None

        # Check cache
        now = time.time()
        if (
            self._cached_result is not None
            and (now - self._cache_time) < self._cache_seconds
            and len(self._buffer) == self._cache_buffer_len
        ):
            return self._cached_result

        try:
            states = list(self._buffer)
            window = compute_trajectory_window(states)
            shape = classify_trajectory(window)
            self._current_shape = shape.value

            eisv_tokens = self._generator.generate(shape.value)
            lumen_tokens = translate_expression(eisv_tokens)
            trigger = shape_to_lumen_trigger(shape.value)

            result = {
                "shape": shape.value,
                "suggested_tokens": lumen_tokens,
                "eisv_tokens": eisv_tokens,
                "trigger": trigger,
            }

            self._cached_result = result
            self._cache_time = now
            self._cache_buffer_len = len(self._buffer)

            return result

        except Exception:
            return None

    def record_feedback(self, tokens: List[str], score: float) -> None:
        """Forward feedback to the expression generator's weight learning."""
        if self._current_shape is not None:
            try:
                self._generator.update_weights(self._current_shape, tokens, score)
            except Exception:
                pass

    @property
    def current_shape(self) -> Optional[str]:
        """Last classified trajectory shape, or None."""
        return self._current_shape

    @property
    def buffer_size(self) -> int:
        """Number of states currently in the buffer."""
        return len(self._buffer)


# Singleton
_awareness: Optional[TrajectoryAwareness] = None


def get_trajectory_awareness(**kwargs) -> TrajectoryAwareness:
    """Get or create the singleton TrajectoryAwareness instance."""
    global _awareness
    if _awareness is None:
        _awareness = TrajectoryAwareness(**kwargs)
    return _awareness
