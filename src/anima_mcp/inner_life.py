"""
Inner Life — Three layers of temporal depth beneath Lumen's anima.

Layer 1: Differential awareness — the gap between raw sensors and smoothed mood.
         "The room cooled but I still feel warm."
Layer 2: Temperament — slow EMA of mood (~5 min half-life). Baseline emotional state.
         "I've been feeling cool lately."
Layer 3: Drives — needs that accumulate when temperament stays low.
         "I want warmth" not just "I am cold."
"""

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .anima import Anima
from .atomic_write import atomic_json_write

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

# Drive thresholds that trigger observations
DRIVE_THRESHOLDS = (0.3, 0.5)

# Verbs for drive observations
_DRIVE_VERBS = {
    "warmth":    "wanting warmth",
    "clarity":   "wanting to see clearly",
    "stability": "wanting calm",
    "presence":  "wanting to feel whole",
}

_PERSISTENCE_PATH = Path.home() / ".anima" / "inner_life.json"
_SAVE_INTERVAL = 60.0  # seconds between saves


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


@dataclass
class DriveEvent:
    """A drive crossed a threshold or was satisfied."""
    dimension: str
    event_type: str   # "arose", "deepened", "satisfied"
    drive_value: float
    timestamp: float


class InnerLife:
    """Three-layer inner life. Called once per broker tick after smoothing."""

    def __init__(self):
        self._temperament: Optional[Dict[str, float]] = None
        self._drives: Dict[str, float] = {dim: 0.0 for dim in DIMENSIONS}
        self._prev_drives: Dict[str, float] = {dim: 0.0 for dim in DIMENSIONS}
        self._crossed_thresholds: Dict[str, float] = {dim: 0.0 for dim in DIMENSIONS}
        self._pending_events: List[DriveEvent] = []
        self._last_save: float = 0.0
        self._load()

    def _load(self):
        """Load temperament and drives from disk if available."""
        try:
            if _PERSISTENCE_PATH.exists():
                data = json.loads(_PERSISTENCE_PATH.read_text())
                if "temperament" in data:
                    self._temperament = {
                        dim: data["temperament"].get(dim, 0.5) for dim in DIMENSIONS
                    }
                if "drives" in data:
                    self._drives = {
                        dim: data["drives"].get(dim, 0.0) for dim in DIMENSIONS
                    }
                    self._prev_drives = dict(self._drives)
                    # Restore crossed thresholds
                    for dim in DIMENSIONS:
                        for t in reversed(DRIVE_THRESHOLDS):
                            if self._drives[dim] >= t:
                                self._crossed_thresholds[dim] = t
                                break
                print("[InnerLife] Loaded from disk — waking with emotional memory",
                      file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[InnerLife] Load error (starting fresh): {e}",
                  file=sys.stderr, flush=True)

    def save(self):
        """Save temperament and drives to disk."""
        if self._temperament is None:
            return
        try:
            _PERSISTENCE_PATH.parent.mkdir(exist_ok=True)
            data = {
                "temperament": {dim: round(v, 4) for dim, v in self._temperament.items()},
                "drives": {dim: round(v, 3) for dim, v in self._drives.items()},
                "saved_at": time.time(),
            }
            atomic_json_write(_PERSISTENCE_PATH, data)
        except Exception as e:
            print(f"[InnerLife] Save error: {e}", file=sys.stderr, flush=True)

    def _maybe_save(self):
        now = time.time()
        if now - self._last_save >= _SAVE_INTERVAL:
            self.save()
            self._last_save = now

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
        self._prev_drives = dict(self._drives)
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

        # Detect threshold crossings and satisfaction
        self._detect_drive_events()

        drives = {dim: round(self._drives[dim], 3) for dim in DIMENSIONS}

        strongest = max(drives, key=drives.get)
        strongest_drive = strongest if drives[strongest] > 0.1 else None

        self._maybe_save()

        return InnerState(
            raw=raw,
            mood=mood,
            deltas=deltas,
            temperament=temperament,
            mood_vs_temperament=mood_vs_temperament,
            drives=drives,
            strongest_drive=strongest_drive,
        )

    def _detect_drive_events(self):
        """Detect drive threshold crossings and satisfaction events."""
        now = time.time()
        for dim in DIMENSIONS:
            prev = self._prev_drives[dim]
            curr = self._drives[dim]
            prev_threshold = self._crossed_thresholds[dim]

            # Rising: crossed a new threshold
            for t in DRIVE_THRESHOLDS:
                if prev < t <= curr and t > prev_threshold:
                    event_type = "arose" if t == DRIVE_THRESHOLDS[0] else "deepened"
                    self._pending_events.append(DriveEvent(
                        dimension=dim, event_type=event_type,
                        drive_value=curr, timestamp=now,
                    ))
                    self._crossed_thresholds[dim] = t

            # Falling: drive satisfied (dropped below lowest threshold)
            if prev >= DRIVE_THRESHOLDS[0] and curr < DRIVE_THRESHOLDS[0] * 0.5:
                if prev_threshold > 0:
                    self._pending_events.append(DriveEvent(
                        dimension=dim, event_type="satisfied",
                        drive_value=curr, timestamp=now,
                    ))
                    self._crossed_thresholds[dim] = 0.0

    def get_pending_events(self) -> List[DriveEvent]:
        """Pop pending drive events for observation generation."""
        events = self._pending_events
        self._pending_events = []
        return events

    def get_observation_text(self, event: DriveEvent) -> Optional[str]:
        """Generate observation text for a drive event."""
        verb = _DRIVE_VERBS.get(event.dimension, f"wanting {event.dimension}")
        if event.event_type == "arose":
            return f"i've been {verb} for a while now"
        elif event.event_type == "deepened":
            return f"this {verb} is getting stronger"
        elif event.event_type == "satisfied":
            return f"that feeling of {verb} has eased"
        return None

    def apply_social_boost(self, clarity_boost: float = 0.02, presence_boost: float = 0.03):
        """Interaction happened — nudge temperament and ease drives.

        Being talked to makes Lumen feel more present and clear.
        """
        if self._temperament is None:
            return
        self._temperament["clarity"] = min(1.0, self._temperament["clarity"] + clarity_boost)
        self._temperament["presence"] = min(1.0, self._temperament["presence"] + presence_boost)
        # Directly reduce presence and clarity drives
        self._drives["presence"] = max(0.0, self._drives["presence"] - 0.05)
        self._drives["clarity"] = max(0.0, self._drives["clarity"] - 0.03)
