"""
CalibrationDrift — Endogenous midpoint drift via double-EMA.

Replaces fixed calibration midpoints with experience-derived ones.
"Normal warmth" becomes "what warmth has typically been" rather than
a fixed developer constant.

Architecture:
  - Inner EMA (fast, alpha=0.05): tracks the raw attractor signal, converging
    in ~20 samples. This is "what is happening now."
  - Outer EMA (slow, alpha=0.001): tracks the inner EMA, drifting ~5% over
    30 days of continuous operation. This is "what has been typical."
  - current_midpoint: the outer EMA clamped within asymmetric bounds around
    the hardware default. This replaces the fixed 0.5 midpoint.

Safety:
  - Per-dimension asymmetric bounds prevent runaway drift.
  - Global drift budget caps total displacement across all dimensions.
  - Restart decay pulls midpoints back toward last-healthy state after gaps.
  - Surprise acceleration temporarily speeds outer EMA when sustained deviation
    is detected, allowing faster adaptation to genuine environmental shifts.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INNER_ALPHA: float = 0.05       # Fast EMA — converges in ~20 samples
OUTER_ALPHA: float = 0.001      # Slow EMA — ~5% shift in 30 days
TOTAL_DRIFT_BUDGET: float = 0.4 # Max total absolute drift across all dims

# Per-dimension asymmetric bounds (fraction of hardware_default)
# Format: (bound_low, bound_high) — how far below/above default is allowed
DIMENSION_BOUNDS: Dict[str, tuple[float, float]] = {
    "warmth":    (0.10, 0.20),  # Can drift -10% to +20%
    "clarity":   (0.05, 0.15),  # Can drift -5% to +15%
    "stability": (0.15, 0.15),  # Can drift -15% to +15%
    "presence":  (0.10, 0.10),  # Can drift -10% to +10%
}

HARDWARE_DEFAULTS: Dict[str, float] = {
    "warmth":    0.5,
    "clarity":   0.5,
    "stability": 0.5,
    "presence":  0.5,
}

# Surprise acceleration — when inner EMA is sustained far from default
SURPRISE_THRESHOLD_SIGMA: float = 3.0
SURPRISE_TRIGGER_COUNT: int = 100
SURPRISE_ACCELERATION: float = 10.0
SURPRISE_DECAY_RATE: float = 0.98

# Restart decay
RESTART_DECAY_HALFLIFE_HOURS: float = 24.0


# ---------------------------------------------------------------------------
# DimensionDrift
# ---------------------------------------------------------------------------

@dataclass
class DimensionDrift:
    """
    Tracks endogenous midpoint drift for a single anima dimension.

    The double-EMA architecture ensures that transient spikes don't move the
    midpoint, but sustained environmental shifts do — slowly.
    """

    dimension: str
    hardware_default: float = 0.5

    # Current drifted midpoint (replaces fixed 0.5)
    current_midpoint: float = field(init=False)

    # Double-EMA state
    inner_ema: float = field(init=False)
    outer_ema: float = field(init=False)

    # Asymmetric bounds (fraction of hardware_default)
    bound_low: float = 0.10
    bound_high: float = 0.20

    # Last known healthy midpoint (for restart decay)
    last_healthy_midpoint: float = field(init=False)

    # Current outer alpha (may be accelerated by surprise)
    outer_alpha: float = field(init=False)

    # Surprise tracking (internal)
    _deviation_count: int = field(default=0, repr=False)
    _surprise_active: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        self.current_midpoint = self.hardware_default
        self.inner_ema = self.hardware_default
        self.outer_ema = self.hardware_default
        self.last_healthy_midpoint = self.hardware_default
        self.outer_alpha = OUTER_ALPHA

    # --- Core EMA updates ---

    def update_inner(self, value: float) -> None:
        """Update the fast (inner) EMA with a new attractor value."""
        self.inner_ema = INNER_ALPHA * value + (1.0 - INNER_ALPHA) * self.inner_ema

    def update_outer(self) -> None:
        """Update the slow (outer) EMA from the current inner EMA."""
        alpha = self.outer_alpha
        self.outer_ema = alpha * self.inner_ema + (1.0 - alpha) * self.outer_ema

    def apply_drift(self) -> None:
        """
        Set current_midpoint from outer_ema, clamped within asymmetric bounds
        around hardware_default.
        """
        low = self.hardware_default * (1.0 - self.bound_low)
        high = self.hardware_default * (1.0 + self.bound_high)
        self.current_midpoint = max(low, min(high, self.outer_ema))

    # --- Surprise acceleration ---

    def check_surprise_acceleration(self) -> None:
        """
        If inner EMA has been far from hardware_default for many consecutive
        samples, temporarily accelerate outer alpha to adapt faster.
        """
        deviation = abs(self.inner_ema - self.hardware_default)
        # Use a simple threshold: deviation > SURPRISE_THRESHOLD_SIGMA * 0.1
        # (0.1 is a rough "one sigma" for [0,1] signals)
        threshold = SURPRISE_THRESHOLD_SIGMA * 0.1

        if deviation >= threshold:
            self._deviation_count += 1
        else:
            self._deviation_count = max(0, self._deviation_count - 1)

        if self._deviation_count >= SURPRISE_TRIGGER_COUNT and not self._surprise_active:
            # Activate surprise acceleration
            self._surprise_active = True
            self.outer_alpha = OUTER_ALPHA * SURPRISE_ACCELERATION

        if self._surprise_active:
            # Decay acceleration back to normal
            excess = self.outer_alpha - OUTER_ALPHA
            excess *= SURPRISE_DECAY_RATE
            self.outer_alpha = OUTER_ALPHA + excess
            if self.outer_alpha < OUTER_ALPHA * 1.01:
                self.outer_alpha = OUTER_ALPHA
                self._surprise_active = False

    # --- Serialization ---

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-safe dictionary."""
        return {
            "dimension": self.dimension,
            "hardware_default": self.hardware_default,
            "current_midpoint": self.current_midpoint,
            "inner_ema": self.inner_ema,
            "outer_ema": self.outer_ema,
            "bound_low": self.bound_low,
            "bound_high": self.bound_high,
            "last_healthy_midpoint": self.last_healthy_midpoint,
            "outer_alpha": self.outer_alpha,
            "_deviation_count": self._deviation_count,
            "_surprise_active": self._surprise_active,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DimensionDrift:
        """Restore from a serialized dictionary."""
        d = cls(
            dimension=data["dimension"],
            hardware_default=data["hardware_default"],
            bound_low=data.get("bound_low", 0.10),
            bound_high=data.get("bound_high", 0.20),
        )
        d.current_midpoint = data["current_midpoint"]
        d.inner_ema = data["inner_ema"]
        d.outer_ema = data["outer_ema"]
        d.last_healthy_midpoint = data.get("last_healthy_midpoint", data["hardware_default"])
        d.outer_alpha = data.get("outer_alpha", OUTER_ALPHA)
        d._deviation_count = data.get("_deviation_count", 0)
        d._surprise_active = data.get("_surprise_active", False)
        return d


# ---------------------------------------------------------------------------
# CalibrationDrift
# ---------------------------------------------------------------------------

class CalibrationDrift:
    """
    Manages endogenous calibration drift across all four anima dimensions.

    Provides the full update cycle: inner EMA -> outer EMA -> apply drift ->
    enforce budget. Also handles persistence, restart decay, and health
    recording.
    """

    def __init__(self) -> None:
        self.total_drift_budget: float = TOTAL_DRIFT_BUDGET
        self.dimensions: Dict[str, DimensionDrift] = {}

        for dim_name, default in HARDWARE_DEFAULTS.items():
            bound_low, bound_high = DIMENSION_BOUNDS[dim_name]
            self.dimensions[dim_name] = DimensionDrift(
                dimension=dim_name,
                hardware_default=default,
                bound_low=bound_low,
                bound_high=bound_high,
            )

    def update(self, attractor_center: Dict[str, float]) -> None:
        """
        Run one full drift cycle for all dimensions.

        Args:
            attractor_center: Current attractor values, e.g.
                {"warmth": 0.6, "clarity": 0.7, "stability": 0.5, "presence": 0.6}
        """
        for dim_name, dim in self.dimensions.items():
            value = attractor_center.get(dim_name)
            if value is not None:
                dim.update_inner(value)
            dim.update_outer()
            dim.check_surprise_acceleration()
            dim.apply_drift()
        self.enforce_budget()

    def enforce_budget(self) -> None:
        """
        If total absolute drift exceeds the budget, scale all displacements
        down proportionally.
        """
        total = sum(
            abs(d.current_midpoint - d.hardware_default)
            for d in self.dimensions.values()
        )
        if total > self.total_drift_budget and total > 0:
            scale = self.total_drift_budget / total
            for d in self.dimensions.values():
                displacement = d.current_midpoint - d.hardware_default
                d.current_midpoint = d.hardware_default + displacement * scale

    def get_midpoints(self) -> Dict[str, float]:
        """Return current drifted midpoints for all dimensions."""
        return {
            dim_name: d.current_midpoint
            for dim_name, d in self.dimensions.items()
        }

    def get_offsets(self) -> Dict[str, float]:
        """Return drift offsets (midpoint - hardware_default) for all dimensions."""
        return {
            dim_name: d.current_midpoint - d.hardware_default
            for dim_name, d in self.dimensions.items()
        }

    def record_healthy_state(self, health: float) -> None:
        """
        If the system is healthy, record current midpoints as the
        last-known-good state for restart decay.

        Args:
            health: Overall health score [0, 1]. Only records if >= 0.5.
        """
        if health >= 0.5:
            for d in self.dimensions.values():
                d.last_healthy_midpoint = d.current_midpoint

    def apply_restart_decay(self, gap_hours: float) -> None:
        """
        After a restart with a gap, decay midpoints toward the last healthy
        state. Longer gaps produce more decay (exponential halflife).

        Args:
            gap_hours: Hours since last shutdown.
        """
        if gap_hours < 24.0:
            return

        # decay_factor: 0.5 at halflife, approaches 1.0 for very long gaps
        decay_factor = 1.0 - math.pow(0.5, gap_hours / RESTART_DECAY_HALFLIFE_HOURS)

        for d in self.dimensions.values():
            delta = d.last_healthy_midpoint - d.current_midpoint
            d.current_midpoint += delta * decay_factor
            # Also adjust outer_ema to match, so drift doesn't immediately undo the decay
            d.outer_ema += (d.last_healthy_midpoint - d.outer_ema) * decay_factor

    # --- Persistence ---

    def save(self, path: str) -> None:
        """Save drift state to a JSON file."""
        data = {
            "total_drift_budget": self.total_drift_budget,
            "dimensions": {
                name: d.to_dict() for name, d in self.dimensions.items()
            },
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls, path: str) -> CalibrationDrift:
        """Load drift state from a JSON file."""
        with open(path, "r") as f:
            data = json.load(f)

        drift = cls()
        drift.total_drift_budget = data.get("total_drift_budget", TOTAL_DRIFT_BUDGET)

        for name, dim_data in data.get("dimensions", {}).items():
            if name in drift.dimensions:
                drift.dimensions[name] = DimensionDrift.from_dict(dim_data)

        return drift
