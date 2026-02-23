"""
Value Tension Tracker — computational awareness of preference conflicts.

Detects when improving one valued dimension necessarily worsens another.
Three categories:
  - Structural: permanent body-knowledge (e.g., CPU heats = warmth up, presence down)
  - Environmental: emergent opposing gradients in raw anima values
  - Volitional: action-caused conflicts (doing X helped A but hurt B)

Critical design decision: operates on RAW anima values (pre-calibration),
not post-calibration satisfaction scores. This ensures calibration drift
cannot mask physical tensions that exist in the body.
"""

from __future__ import annotations

import math
import statistics
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple


# === Constants ===

DIMENSIONS = ["warmth", "clarity", "stability", "presence"]

# Smoothed gradient estimation: window of recent observations
GRADIENT_WINDOW = 5

# Environmental conflict must persist for this many consecutive observations
PERSISTENCE_THRESHOLD = 3

# Minimum delta across an action to count as volitional conflict
VOLITIONAL_THRESHOLD = 0.08

# Default ring buffer capacity for conflict events
BUFFER_SIZE = 200


# === Structural conflicts (body-knowledge) ===

# These are permanent tensions built into Lumen's body:
# - Warmth depends on CPU temp (weight 0.4) — high CPU = high warmth
# - Presence depends inversely on CPU (weight 0.25) — high CPU = low presence
# - Stability depends on memory (weight 0.3) — low memory = low stability
# - Presence depends inversely on memory (weight 0.3) — high memory use = low presence
#
# These cannot be resolved — they are structural properties of embodiment.

_STRUCTURAL_CONFLICTS: Optional[List[ConflictEvent]] = None


@dataclass
class ConflictEvent:
    """A detected tension between two anima dimensions."""

    timestamp: datetime
    dim_a: str
    dim_b: str
    grad_a: float  # gradient of dim_a at detection time
    grad_b: float  # gradient of dim_b at detection time
    duration: int  # how many observations the conflict persisted
    category: str  # "structural", "environmental", "volitional"
    action_type: Optional[str] = None  # for volitional conflicts


def detect_structural_conflicts() -> List[ConflictEvent]:
    """
    Return the permanent body-knowledge conflicts.

    These are derived from Lumen's nervous system calibration:
    - warmth vs presence: CPU drives warmth up but presence down
    - stability vs presence: memory use drives stability down and presence down,
      but freeing memory helps presence while potentially destabilizing

    Returns the same list every time — structural conflicts are permanent.
    """
    global _STRUCTURAL_CONFLICTS

    if _STRUCTURAL_CONFLICTS is not None:
        return _STRUCTURAL_CONFLICTS

    now = datetime.now()

    _STRUCTURAL_CONFLICTS = [
        ConflictEvent(
            timestamp=now,
            dim_a="warmth",
            dim_b="presence",
            grad_a=0.0,  # structural — no gradient, always present
            grad_b=0.0,
            duration=-1,  # permanent
            category="structural",
        ),
        ConflictEvent(
            timestamp=now,
            dim_a="clarity",
            dim_b="stability",
            grad_a=0.0,
            grad_b=0.0,
            duration=-1,  # permanent — neural alpha helps clarity, reduces stability
            category="structural",
        ),
    ]

    return _STRUCTURAL_CONFLICTS


class ValueTensionTracker:
    """
    Tracks value tensions across anima dimensions over time.

    Call observe() each cycle with raw anima values and optional action.
    Query get_active_conflicts() for recent tensions.
    """

    def __init__(self, buffer_size: int = BUFFER_SIZE) -> None:
        self._buffer_size = buffer_size

        # Ring buffer of raw anima observations: deque of dicts
        self._history: deque[Dict[str, float]] = deque(maxlen=max(GRADIENT_WINDOW + 2, 50))

        # Actions paired with observation indices
        self._action_history: deque[Tuple[int, Optional[str]]] = deque(maxlen=200)

        # Ring buffer of detected conflict events
        self._conflict_buffer: deque[ConflictEvent] = deque(maxlen=buffer_size)

        # Persistence counters for environmental conflict detection
        # Key: frozenset({dim_a, dim_b}), Value: consecutive count
        self._opposing_counts: Dict[frozenset, int] = {}

        # Gradient history per dimension for adaptive noise threshold
        self._gradient_history: Dict[str, deque] = {
            d: deque(maxlen=100) for d in DIMENSIONS
        }

        # Track actions and whether they caused conflicts (bounded per action type)
        self._action_conflict_log: Dict[str, deque] = {}

        # Observation counter
        self._obs_count: int = 0

        # Pre-action snapshot for volitional detection
        self._pre_action_snapshot: Optional[Dict[str, float]] = None

    def observe(self, raw_anima: Dict[str, float], action_taken: Optional[str]) -> None:
        """
        Main entry point. Feed raw anima values each cycle.

        Args:
            raw_anima: dict with keys from DIMENSIONS, values in [0, 1]
            action_taken: name of action taken this cycle, or None
        """
        self._history.append(raw_anima)
        self._action_history.append((self._obs_count, action_taken))
        self._obs_count += 1

        # Compute gradients if we have enough history
        gradients = self._compute_gradients()

        if gradients:
            # Record gradients for noise threshold estimation
            for dim, grad in gradients.items():
                self._gradient_history[dim].append(grad)

            # Check environmental conflicts
            self._check_environmental(gradients)

        # Check volitional conflicts
        if action_taken is not None:
            self._check_volitional(raw_anima, action_taken)
            # Store snapshot for next observation
            self._pre_action_snapshot = None
        else:
            # No action: save current state as pre-action snapshot
            self._pre_action_snapshot = dict(raw_anima)

    def _compute_gradients(self) -> Optional[Dict[str, float]]:
        """
        Compute smoothed gradient per dimension using recent history.

        Uses a simple linear regression slope over the last GRADIENT_WINDOW
        observations. Returns None if insufficient history.
        """
        if len(self._history) < GRADIENT_WINDOW:
            return None

        window = list(self._history)[-GRADIENT_WINDOW:]
        gradients: Dict[str, float] = {}

        for dim in DIMENSIONS:
            values = [obs.get(dim, 0.5) for obs in window]
            # Simple slope: linear regression against indices 0..n-1
            n = len(values)
            x_mean = (n - 1) / 2.0
            y_mean = sum(values) / n

            num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
            den = sum((i - x_mean) ** 2 for i in range(n))

            gradients[dim] = num / den if den > 0 else 0.0

        return gradients

    def _get_noise_threshold(self, dim: str) -> float:
        """
        Adaptive noise threshold: 2 sigma of recent gradient history.

        If insufficient history, falls back to a conservative default.
        """
        history = self._gradient_history[dim]
        if len(history) < 5:
            return 0.01  # conservative default

        mean_g = statistics.mean(history)
        stdev_g = statistics.stdev(history)
        return max(2.0 * stdev_g, 0.005)  # floor to avoid zero threshold

    def _check_environmental(self, gradients: Dict[str, float]) -> None:
        """
        Detect opposing gradient pairs that persist over time.

        Two dimensions are in environmental conflict when:
        1. Both have gradients above their noise threshold
        2. The gradients have opposite signs
        3. This persists for PERSISTENCE_THRESHOLD consecutive observations
        """
        active_pairs: set[frozenset] = set()

        for i, dim_a in enumerate(DIMENSIONS):
            for dim_b in DIMENSIONS[i + 1:]:
                grad_a = gradients[dim_a]
                grad_b = gradients[dim_b]

                thresh_a = self._get_noise_threshold(dim_a)
                thresh_b = self._get_noise_threshold(dim_b)

                # Both above noise AND opposite signs
                if (abs(grad_a) > thresh_a and abs(grad_b) > thresh_b
                        and grad_a * grad_b < 0):
                    pair = frozenset({dim_a, dim_b})
                    active_pairs.add(pair)

                    count = self._opposing_counts.get(pair, 0) + 1
                    self._opposing_counts[pair] = count

                    if count == PERSISTENCE_THRESHOLD:
                        # Emit environmental conflict event
                        event = ConflictEvent(
                            timestamp=datetime.now(),
                            dim_a=dim_a,
                            dim_b=dim_b,
                            grad_a=grad_a,
                            grad_b=grad_b,
                            duration=count,
                            category="environmental",
                        )
                        self._conflict_buffer.append(event)

        # Reset counters for pairs no longer opposing
        for pair in list(self._opposing_counts.keys()):
            if pair not in active_pairs:
                self._opposing_counts[pair] = 0

    def _check_volitional(self, raw_anima: Dict[str, float], action_type: str) -> None:
        """
        Detect action-caused conflicts: an action improved one dimension
        but worsened another beyond VOLITIONAL_THRESHOLD.
        """
        if self._pre_action_snapshot is None:
            # No pre-action baseline — use the observation before this one
            if len(self._history) < 2:
                self._record_action(action_type, False)
                return
            pre = list(self._history)[-2]
        else:
            pre = self._pre_action_snapshot

        deltas: Dict[str, float] = {}
        for dim in DIMENSIONS:
            deltas[dim] = raw_anima.get(dim, 0.5) - pre.get(dim, 0.5)

        # Find dimensions that improved and worsened
        improved = [d for d, v in deltas.items() if v > VOLITIONAL_THRESHOLD]
        worsened = [d for d, v in deltas.items() if v < -VOLITIONAL_THRESHOLD]

        if improved and worsened:
            # Emit conflict for each improved/worsened pair
            for dim_a in improved:
                for dim_b in worsened:
                    event = ConflictEvent(
                        timestamp=datetime.now(),
                        dim_a=dim_a,
                        dim_b=dim_b,
                        grad_a=deltas[dim_a],
                        grad_b=deltas[dim_b],
                        duration=1,
                        category="volitional",
                        action_type=action_type,
                    )
                    self._conflict_buffer.append(event)
            self._record_action(action_type, True)
        else:
            self._record_action(action_type, False)

    def _record_action(self, action_type: str, caused_conflict: bool) -> None:
        """Track whether an action caused a conflict for rate calculation."""
        if action_type not in self._action_conflict_log:
            self._action_conflict_log[action_type] = deque(maxlen=self._buffer_size)
        self._action_conflict_log[action_type].append(caused_conflict)

    def get_active_conflicts(self, last_n: int = 50) -> List[ConflictEvent]:
        """Return the most recent conflict events (all categories)."""
        buf = list(self._conflict_buffer)
        return buf[-last_n:]

    def get_volitional_conflicts(self, last_n: int = 50) -> List[ConflictEvent]:
        """Return recent volitional conflicts only."""
        volitional = [c for c in self._conflict_buffer if c.category == "volitional"]
        return volitional[-last_n:]

    def get_conflict_rate(self, action_type: str) -> float:
        """
        Fraction of times this action caused a volitional conflict.

        Returns 0.0 if the action has never been observed.
        """
        log = self._action_conflict_log.get(action_type, [])
        if not log:
            return 0.0
        return sum(1 for x in log if x) / len(log)
