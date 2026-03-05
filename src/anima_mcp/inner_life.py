"""
Inner Life — Three layers of temporal depth beneath Lumen's anima.

Layer 1: Differential awareness — the gap between raw sensors and smoothed mood.
         "The room cooled but I still feel warm."
Layer 2: Temperament — slow EMA of mood (~5 min half-life). Baseline emotional state.
         "I've been feeling cool lately."
Layer 3: Drives — needs that accumulate when temperament stays low.
         "I want warmth" not just "I am cold."
"""

from dataclasses import dataclass
from typing import Dict, Optional

from .anima import Anima

DIMENSIONS = ("warmth", "clarity", "stability", "presence")

# Temperament EMA alphas (very slow).
# half_life = -ln(2) / ln(1 - alpha), at dt=2s intervals.
TEMPERAMENT_ALPHA = {
    "warmth":    0.005,   # ~4.6 min half-life — warmth lingers longest
    "clarity":   0.007,   # ~3.3 min half-life — clarity shifts a bit faster
    "stability": 0.005,   # ~4.6 min half-life — stability is slow-moving
    "presence":  0.010,   # ~2.3 min half-life — resources tracked faster
}

# Below these temperament thresholds, drives accumulate.
DRIVE_COMFORT = {
    "warmth":    0.40,
    "clarity":   0.45,
    "stability": 0.40,
    "presence":  0.35,
}

# Per-tick rates (2s interval).
# Accumulation: ~5.6 min from zero to 0.5 at base rate.
# Decay: ~2.7x faster — satisfaction is quicker than longing.
DRIVE_ACCUMULATION = 0.003
DRIVE_DECAY = 0.008


@dataclass
class InnerState:
    """Snapshot of Lumen's three-layer inner life."""

    raw: Dict[str, float]
    mood: Dict[str, float]
    deltas: Dict[str, float]
    temperament: Dict[str, float]
    mood_vs_temperament: Dict[str, float]
    drives: Dict[str, float]
    strongest_drive: Optional[str]

    def to_dict(self) -> dict:
        return {
            "raw": {k: round(v, 3) for k, v in self.raw.items()},
            "deltas": {k: round(v, 3) for k, v in self.deltas.items()},
            "temperament": {k: round(v, 3) for k, v in self.temperament.items()},
            "mood_vs_temperament": {k: round(v, 3) for k, v in self.mood_vs_temperament.items()},
            "drives": {k: round(v, 3) for k, v in self.drives.items()},
            "strongest_drive": self.strongest_drive,
        }


class InnerLife:
    """Three-layer inner life. Called once per broker tick after smoothing."""

    def __init__(self):
        self._temperament: Optional[Dict[str, float]] = None
        self._drives: Dict[str, float] = {dim: 0.0 for dim in DIMENSIONS}

    def update(self, raw_anima: Anima, smoothed_anima: Anima) -> InnerState:
        """Process one tick. Returns snapshot of all three layers."""

        raw = {dim: getattr(raw_anima, dim) for dim in DIMENSIONS}
        mood = {dim: getattr(smoothed_anima, dim) for dim in DIMENSIONS}

        # Layer 1: Differential awareness
        deltas = {dim: round(mood[dim] - raw[dim], 4) for dim in DIMENSIONS}

        # Layer 2: Temperament (slow EMA of mood)
        if self._temperament is None:
            self._temperament = {dim: mood[dim] for dim in DIMENSIONS}
        else:
            for dim in DIMENSIONS:
                a = TEMPERAMENT_ALPHA[dim]
                self._temperament[dim] = a * mood[dim] + (1 - a) * self._temperament[dim]

        temperament = {dim: round(self._temperament[dim], 4) for dim in DIMENSIONS}
        mood_vs_temperament = {
            dim: round(mood[dim] - temperament[dim], 4) for dim in DIMENSIONS
        }

        # Layer 3: Drives
        for dim in DIMENSIONS:
            threshold = DRIVE_COMFORT[dim]
            temp_val = self._temperament[dim]

            if temp_val < threshold:
                deficit = threshold - temp_val
                rate = DRIVE_ACCUMULATION * (1.0 + deficit * 2.0)
                self._drives[dim] = min(1.0, self._drives[dim] + rate)
            else:
                surplus = temp_val - threshold
                rate = DRIVE_DECAY * (1.0 + surplus * 2.0)
                self._drives[dim] = max(0.0, self._drives[dim] - rate)

        drives = {dim: round(self._drives[dim], 3) for dim in DIMENSIONS}

        strongest = max(drives, key=drives.get)
        strongest_drive = strongest if drives[strongest] > 0.1 else None

        return InnerState(
            raw=raw,
            mood=mood,
            deltas=deltas,
            temperament=temperament,
            mood_vs_temperament=mood_vs_temperament,
            drives=drives,
            strongest_drive=strongest_drive,
        )
