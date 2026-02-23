# Computational Selfhood Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add three computational feedback loops — calibration drift, value tension detection, and preference meta-learning — so Lumen's perception, value conflicts, and preference weights evolve from accumulated experience.

**Architecture:** Three new modules (`calibration_drift.py`, `value_tension.py`) plus extensions to `preferences.py`, integrated into the main loop at specific points. All loops close through computation; LLM is narrator only.

**Tech Stack:** Python 3, SQLite (existing), dataclasses, no new dependencies.

**Design doc:** `docs/plans/2026-02-23-computational-selfhood-design.md`

---

### Task 1: CalibrationDrift Data Structures and Unit Tests

**Files:**
- Create: `src/anima_mcp/calibration_drift.py`
- Create: `tests/test_calibration_drift.py`

**Step 1: Write the failing tests**

```python
# tests/test_calibration_drift.py
import pytest
from anima_mcp.calibration_drift import DimensionDrift, CalibrationDrift


class TestDimensionDrift:
    def test_initial_midpoint_equals_default(self):
        d = DimensionDrift("warmth", hardware_default=0.5)
        assert d.current_midpoint == 0.5

    def test_inner_ema_tracks_signal(self):
        d = DimensionDrift("warmth", hardware_default=0.5)
        for _ in range(40):
            d.update_inner(0.6)
        assert abs(d.inner_ema - 0.6) < 0.01

    def test_outer_ema_is_slow(self):
        d = DimensionDrift("warmth", hardware_default=0.5)
        d.inner_ema = 0.6  # Simulate converged inner
        for _ in range(20):
            d.update_outer()
        # After 20 cycles at alpha=0.001, should barely move
        assert d.outer_ema < 0.51

    def test_midpoint_respects_upper_bound(self):
        d = DimensionDrift("warmth", hardware_default=0.5, bound_high=0.20)
        d.outer_ema = 0.8  # Way above default
        d.apply_drift()
        assert d.current_midpoint <= 0.5 * (1 + 0.20)

    def test_midpoint_respects_lower_bound(self):
        d = DimensionDrift("warmth", hardware_default=0.5, bound_low=0.10)
        d.outer_ema = 0.2  # Way below default
        d.apply_drift()
        assert d.current_midpoint >= 0.5 * (1 - 0.10)


class TestCalibrationDrift:
    def test_total_drift_budget_enforced(self):
        drift = CalibrationDrift()
        # Force all dimensions to max drift
        for dim in drift.dimensions.values():
            dim.outer_ema = dim.hardware_default + 1.0
            dim.apply_drift()
        drift.enforce_budget()
        total = sum(abs(d.current_midpoint - d.hardware_default) for d in drift.dimensions.values())
        assert total <= drift.total_drift_budget + 0.001

    def test_update_full_cycle(self):
        drift = CalibrationDrift()
        attractor = {"warmth": 0.6, "clarity": 0.7, "stability": 0.5, "presence": 0.6}
        drift.update(attractor)
        # Should not crash, midpoints should be valid
        for d in drift.dimensions.values():
            assert 0.0 <= d.current_midpoint <= 1.0

    def test_persistence_roundtrip(self, tmp_path):
        drift = CalibrationDrift()
        drift.dimensions["warmth"].outer_ema = 0.55
        drift.dimensions["warmth"].apply_drift()
        path = tmp_path / "calibration_drift.json"
        drift.save(str(path))
        drift2 = CalibrationDrift.load(str(path))
        assert abs(drift2.dimensions["warmth"].current_midpoint - drift.dimensions["warmth"].current_midpoint) < 0.001

    def test_restart_decay_toward_last_healthy(self, tmp_path):
        drift = CalibrationDrift()
        drift.dimensions["warmth"].outer_ema = 0.55
        drift.dimensions["warmth"].apply_drift()
        drift.dimensions["warmth"].last_healthy_midpoint = 0.5
        drift.apply_restart_decay(gap_hours=48)
        # After 48h gap, should decay toward last_healthy
        assert drift.dimensions["warmth"].current_midpoint < 0.55 * (1 + 0.20)

    def test_surprise_acceleration(self):
        drift = CalibrationDrift()
        d = drift.dimensions["warmth"]
        normal_alpha = d.outer_alpha
        # Simulate sustained deviation
        d.inner_ema = d.hardware_default + 0.3  # Large deviation
        d._deviation_count = 101
        d.check_surprise_acceleration()
        assert d.outer_alpha > normal_alpha
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_calibration_drift.py -v`
Expected: FAIL — module not found

**Step 3: Write CalibrationDrift implementation**

```python
# src/anima_mcp/calibration_drift.py
"""
Calibration Drift — the self becomes its own reference frame.

Double-EMA drives anima calibration midpoints based on trajectory history.
Inner EMA tracks operating state (~20 samples). Outer EMA drives actual
drift (~days). Midpoints bounded asymmetrically per dimension.
"""

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional


# Asymmetric bounds per dimension (fraction of hardware default)
DIMENSION_BOUNDS = {
    "warmth":    {"low": 0.10, "high": 0.20},
    "clarity":   {"low": 0.05, "high": 0.15},
    "stability": {"low": 0.15, "high": 0.15},
    "presence":  {"low": 0.10, "high": 0.10},
}

# Hardware defaults (midpoints of calibration ranges)
HARDWARE_DEFAULTS = {
    "warmth":    0.5,   # mid of (cpu_temp + ambient_temp + neural) range
    "clarity":   0.5,
    "stability": 0.5,
    "presence":  0.5,
}

INNER_ALPHA = 0.05       # Fast EMA — converges in ~20 samples
OUTER_ALPHA = 0.001      # Slow EMA — ~5% shift in 30 days
TOTAL_DRIFT_BUDGET = 0.4 # Sum of |offset| across all dimensions
SURPRISE_THRESHOLD_SIGMA = 3.0
SURPRISE_TRIGGER_COUNT = 100
SURPRISE_ACCELERATION = 10.0
SURPRISE_DECAY_RATE = 0.98  # Per cycle, back to normal in ~50 cycles
RESTART_DECAY_HALFLIFE_HOURS = 24.0


@dataclass
class DimensionDrift:
    dimension: str
    hardware_default: float
    current_midpoint: float = 0.0
    inner_ema: float = 0.0
    outer_ema: float = 0.0
    bound_low: float = 0.10
    bound_high: float = 0.20
    last_healthy_midpoint: float = 0.0
    outer_alpha: float = OUTER_ALPHA
    _deviation_count: int = 0
    _recent_inner_values: list = field(default_factory=list)

    def __post_init__(self):
        if self.current_midpoint == 0.0:
            self.current_midpoint = self.hardware_default
        if self.inner_ema == 0.0:
            self.inner_ema = self.hardware_default
        if self.outer_ema == 0.0:
            self.outer_ema = self.hardware_default
        if self.last_healthy_midpoint == 0.0:
            self.last_healthy_midpoint = self.hardware_default

    def update_inner(self, attractor_value: float):
        """Fast EMA tracking attractor center."""
        self.inner_ema += INNER_ALPHA * (attractor_value - self.inner_ema)
        self._recent_inner_values.append(self.inner_ema)
        if len(self._recent_inner_values) > 100:
            self._recent_inner_values = self._recent_inner_values[-100:]

    def update_outer(self):
        """Slow EMA driving actual drift."""
        self.outer_ema += self.outer_alpha * (self.inner_ema - self.outer_ema)
        # Decay acceleration back to normal
        if self.outer_alpha > OUTER_ALPHA:
            self.outer_alpha = max(OUTER_ALPHA, self.outer_alpha * SURPRISE_DECAY_RATE)

    def apply_drift(self):
        """Compute drifted midpoint from outer EMA, respecting bounds."""
        offset = self.outer_ema - self.hardware_default
        max_low = self.hardware_default * self.bound_low
        max_high = self.hardware_default * self.bound_high
        clamped = max(-max_low, min(max_high, offset))
        self.current_midpoint = self.hardware_default + clamped

    def check_surprise_acceleration(self):
        """Temporarily increase drift rate on sustained large deviation."""
        if len(self._recent_inner_values) < 20:
            return
        deviation = abs(self.inner_ema - self.current_midpoint)
        values = self._recent_inner_values[-50:]
        if len(values) < 10:
            return
        mean_val = sum(values) / len(values)
        variance = sum((v - mean_val) ** 2 for v in values) / len(values)
        std = math.sqrt(max(variance, 1e-10))
        if deviation > SURPRISE_THRESHOLD_SIGMA * std:
            self._deviation_count += 1
        else:
            self._deviation_count = max(0, self._deviation_count - 1)
        if self._deviation_count > SURPRISE_TRIGGER_COUNT:
            self.outer_alpha = OUTER_ALPHA * SURPRISE_ACCELERATION
            self._deviation_count = 0  # Reset counter

    def to_dict(self) -> dict:
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
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'DimensionDrift':
        return cls(
            dimension=data["dimension"],
            hardware_default=data["hardware_default"],
            current_midpoint=data.get("current_midpoint", data["hardware_default"]),
            inner_ema=data.get("inner_ema", data["hardware_default"]),
            outer_ema=data.get("outer_ema", data["hardware_default"]),
            bound_low=data.get("bound_low", 0.10),
            bound_high=data.get("bound_high", 0.20),
            last_healthy_midpoint=data.get("last_healthy_midpoint", data["hardware_default"]),
            outer_alpha=data.get("outer_alpha", OUTER_ALPHA),
        )


class CalibrationDrift:
    """Manages drift state for all four anima dimensions."""

    def __init__(self):
        self.dimensions: Dict[str, DimensionDrift] = {}
        self.total_drift_budget = TOTAL_DRIFT_BUDGET
        for dim, default in HARDWARE_DEFAULTS.items():
            bounds = DIMENSION_BOUNDS.get(dim, {"low": 0.10, "high": 0.10})
            self.dimensions[dim] = DimensionDrift(
                dimension=dim,
                hardware_default=default,
                bound_low=bounds["low"],
                bound_high=bounds["high"],
            )

    def update(self, attractor_center: Dict[str, float]):
        """Full drift cycle: inner EMA → outer EMA → apply drift → enforce budget."""
        for dim, value in attractor_center.items():
            if dim in self.dimensions:
                d = self.dimensions[dim]
                d.update_inner(value)
                d.check_surprise_acceleration()
                d.update_outer()
                d.apply_drift()
        self.enforce_budget()

    def enforce_budget(self):
        """Ensure total drift across all dimensions stays within budget."""
        total = sum(abs(d.current_midpoint - d.hardware_default) for d in self.dimensions.values())
        if total > self.total_drift_budget:
            scale = self.total_drift_budget / total
            for d in self.dimensions.values():
                offset = d.current_midpoint - d.hardware_default
                d.current_midpoint = d.hardware_default + offset * scale

    def get_midpoints(self) -> Dict[str, float]:
        """Get current drifted midpoints for anima computation."""
        return {dim: d.current_midpoint for dim, d in self.dimensions.items()}

    def get_offsets(self) -> Dict[str, float]:
        """Get drift offsets from hardware defaults (for schema nodes)."""
        return {dim: d.current_midpoint - d.hardware_default for dim, d in self.dimensions.items()}

    def record_healthy_state(self, trajectory_health: float):
        """If trajectory health is high, snapshot midpoints as last-known-good."""
        if trajectory_health > 0.7:
            for d in self.dimensions.values():
                d.last_healthy_midpoint = d.current_midpoint

    def apply_restart_decay(self, gap_hours: float):
        """After a gap, decay midpoints toward last healthy state."""
        if gap_hours < 1.0:
            return
        decay = 0.5 ** (gap_hours / RESTART_DECAY_HALFLIFE_HOURS)
        for d in self.dimensions.values():
            d.current_midpoint = d.last_healthy_midpoint + decay * (d.current_midpoint - d.last_healthy_midpoint)
            d.outer_ema = d.current_midpoint
            d.inner_ema = d.current_midpoint

    def save(self, path: str):
        """Persist drift state to JSON."""
        data = {dim: d.to_dict() for dim, d in self.dimensions.items()}
        Path(path).write_text(json.dumps(data, indent=2))

    @classmethod
    def load(cls, path: str) -> 'CalibrationDrift':
        """Load drift state from JSON."""
        drift = cls()
        p = Path(path)
        if p.exists():
            data = json.loads(p.read_text())
            for dim, d_data in data.items():
                if dim in drift.dimensions:
                    drift.dimensions[dim] = DimensionDrift.from_dict(d_data)
        return drift
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_calibration_drift.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/anima_mcp/calibration_drift.py tests/test_calibration_drift.py
git commit -m "feat: add CalibrationDrift with double-EMA, bounds, and persistence"
```

---

### Task 2: ValueTension Data Structures and Unit Tests

**Files:**
- Create: `src/anima_mcp/value_tension.py`
- Create: `tests/test_value_tension.py`

**Step 1: Write the failing tests**

```python
# tests/test_value_tension.py
import pytest
from datetime import datetime
from anima_mcp.value_tension import (
    ValueTensionTracker, ConflictEvent, detect_structural_conflicts
)


class TestStructuralConflicts:
    def test_detects_warmth_presence_cpu_conflict(self):
        conflicts = detect_structural_conflicts()
        pairs = [(c.dim_a, c.dim_b) for c in conflicts]
        assert ("warmth", "presence") in pairs or ("presence", "warmth") in pairs

    def test_structural_conflicts_are_permanent(self):
        c1 = detect_structural_conflicts()
        c2 = detect_structural_conflicts()
        assert len(c1) == len(c2)  # Same every time


class TestEnvironmentalConflicts:
    def test_detects_opposing_gradients(self):
        tracker = ValueTensionTracker()
        # Feed warmth rising, stability falling for several windows
        for i in range(20):
            raw = {"warmth": 0.5 + i * 0.02, "clarity": 0.5, "stability": 0.7 - i * 0.02, "presence": 0.5}
            tracker.observe(raw_anima=raw, action_taken=None)
        conflicts = tracker.get_active_conflicts()
        env = [c for c in conflicts if c.category == "environmental"]
        assert len(env) > 0
        dims = {(c.dim_a, c.dim_b) for c in env}
        assert ("warmth", "stability") in dims or ("stability", "warmth") in dims

    def test_ignores_noise_below_threshold(self):
        tracker = ValueTensionTracker()
        # Feed tiny random fluctuations
        import random
        random.seed(42)
        for _ in range(50):
            raw = {d: 0.5 + random.gauss(0, 0.001) for d in ["warmth", "clarity", "stability", "presence"]}
            tracker.observe(raw_anima=raw, action_taken=None)
        conflicts = tracker.get_active_conflicts()
        env = [c for c in conflicts if c.category == "environmental"]
        assert len(env) == 0


class TestVolitionalConflicts:
    def test_detects_action_caused_conflict(self):
        tracker = ValueTensionTracker()
        # Establish baseline
        for _ in range(20):
            tracker.observe({"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}, None)
        # Action causes warmth up, stability down
        tracker.observe({"warmth": 0.7, "clarity": 0.5, "stability": 0.3, "presence": 0.5}, "led_brightness")
        conflicts = tracker.get_volitional_conflicts()
        assert len(conflicts) > 0
        assert conflicts[0].action_type == "led_brightness"


class TestConflictRates:
    def test_conflict_rate_per_action(self):
        tracker = ValueTensionTracker()
        for _ in range(20):
            tracker.observe({"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}, None)
        # 3 actions that cause conflicts
        for _ in range(3):
            tracker.observe({"warmth": 0.7, "clarity": 0.5, "stability": 0.3, "presence": 0.5}, "led_brightness")
            tracker.observe({"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}, None)
        # 2 clean actions
        for _ in range(2):
            tracker.observe({"warmth": 0.55, "clarity": 0.5, "stability": 0.5, "presence": 0.5}, "led_brightness")
            tracker.observe({"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}, None)
        rate = tracker.get_conflict_rate("led_brightness")
        assert 0.0 < rate < 1.0  # Some but not all caused conflicts


class TestRingBuffer:
    def test_buffer_capacity(self):
        tracker = ValueTensionTracker(buffer_size=10)
        for i in range(20):
            tracker.observe({"warmth": 0.5 + i * 0.05, "clarity": 0.5, "stability": 0.7 - i * 0.05, "presence": 0.5}, None)
        assert len(tracker._conflict_buffer) <= 10
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_value_tension.py -v`
Expected: FAIL — module not found

**Step 3: Write ValueTensionTracker implementation**

```python
# src/anima_mcp/value_tension.py
"""
Value Tension Detection — computational awareness of preference conflicts.

Three categories:
- Structural: permanent body-knowledge from weight matrices (e.g. CPU drives warmth up, presence down)
- Environmental: emergent opposing gradients in raw anima values
- Volitional: action-caused improvements in one dimension that worsen another

Operates on RAW anima values (pre-calibration) so calibration drift cannot mask tensions.
"""

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple


DIMENSIONS = ["warmth", "clarity", "stability", "presence"]
GRADIENT_WINDOW = 5          # Smooth gradients over this many observations
PERSISTENCE_THRESHOLD = 3    # Consecutive opposing windows to register conflict
VOLITIONAL_THRESHOLD = 0.08  # Min per-dimension delta to count as action-caused
BUFFER_SIZE = 200


@dataclass
class ConflictEvent:
    timestamp: datetime
    dim_a: str
    dim_b: str
    grad_a: float
    grad_b: float
    duration: int
    category: str              # "structural", "environmental", "volitional"
    action_type: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "dim_a": self.dim_a, "dim_b": self.dim_b,
            "grad_a": self.grad_a, "grad_b": self.grad_b,
            "duration": self.duration,
            "category": self.category,
            "action_type": self.action_type,
        }


def detect_structural_conflicts() -> List[ConflictEvent]:
    """Analyze weight matrices to find permanently coupled dimensions."""
    # CPU drives warmth up (weight 0.4) and presence down (cpu component inverted)
    # Neural alpha helps clarity (weight 0.25) but reduces stability groundedness (weight 0.1)
    now = datetime.now()
    return [
        ConflictEvent(now, "warmth", "presence", 0.0, 0.0, 0, "structural", None),
        ConflictEvent(now, "clarity", "stability", 0.0, 0.0, 0, "structural", None),
    ]


class ValueTensionTracker:
    """Tracks value tensions across all three categories."""

    def __init__(self, buffer_size: int = BUFFER_SIZE):
        self._raw_history: deque = deque(maxlen=GRADIENT_WINDOW + 1)
        self._conflict_buffer: deque = deque(maxlen=buffer_size)
        self._gradient_history: Dict[str, deque] = {
            d: deque(maxlen=100) for d in DIMENSIONS
        }
        self._opposing_counts: Dict[Tuple[str, str], int] = {}
        self._action_conflict_counts: Dict[str, int] = {}
        self._action_total_counts: Dict[str, int] = {}
        self._prev_raw: Optional[Dict[str, float]] = None

    def observe(self, raw_anima: Dict[str, float], action_taken: Optional[str]):
        """Observe raw anima values and optionally tag with action."""
        self._raw_history.append(raw_anima)

        # Check for volitional conflict (action-caused)
        if action_taken and self._prev_raw:
            self._action_total_counts[action_taken] = self._action_total_counts.get(action_taken, 0) + 1
            self._check_volitional(raw_anima, action_taken)

        # Compute smoothed gradients and check environmental conflicts
        if len(self._raw_history) >= 2:
            gradients = self._compute_gradients()
            for dim, grad in gradients.items():
                self._gradient_history[dim].append(grad)
            self._check_environmental(gradients)

        self._prev_raw = raw_anima.copy()

    def _compute_gradients(self) -> Dict[str, float]:
        """Compute smoothed gradient per dimension over recent window."""
        if len(self._raw_history) < 2:
            return {d: 0.0 for d in DIMENSIONS}
        recent = list(self._raw_history)
        n = len(recent)
        gradients = {}
        for dim in DIMENSIONS:
            if dim in recent[0] and dim in recent[-1]:
                gradients[dim] = (recent[-1][dim] - recent[0][dim]) / max(1, n - 1)
            else:
                gradients[dim] = 0.0
        return gradients

    def _get_noise_threshold(self, dim: str) -> float:
        """Adaptive threshold: 2 sigma of recent gradient values."""
        history = self._gradient_history.get(dim, deque())
        if len(history) < 10:
            return 0.01  # Default until enough data
        values = list(history)
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return 2.0 * math.sqrt(max(variance, 1e-10))

    def _check_environmental(self, gradients: Dict[str, float]):
        """Detect opposing gradients between dimension pairs."""
        dims = [d for d in DIMENSIONS if d in gradients]
        for i, a in enumerate(dims):
            for b in dims[i + 1:]:
                ga, gb = gradients[a], gradients[b]
                thresh_a = self._get_noise_threshold(a)
                thresh_b = self._get_noise_threshold(b)
                pair = (a, b)
                if (ga > thresh_a and gb < -thresh_b) or (ga < -thresh_a and gb > thresh_b):
                    self._opposing_counts[pair] = self._opposing_counts.get(pair, 0) + 1
                    if self._opposing_counts[pair] >= PERSISTENCE_THRESHOLD:
                        self._conflict_buffer.append(ConflictEvent(
                            timestamp=datetime.now(),
                            dim_a=a, dim_b=b,
                            grad_a=ga, grad_b=gb,
                            duration=self._opposing_counts[pair],
                            category="environmental",
                        ))
                        self._opposing_counts[pair] = 0  # Reset after recording
                else:
                    self._opposing_counts[pair] = max(0, self._opposing_counts.get(pair, 0) - 1)

    def _check_volitional(self, raw_anima: Dict[str, float], action_type: str):
        """Check if action caused opposing changes in dimensions."""
        if not self._prev_raw:
            return
        deltas = {}
        for dim in DIMENSIONS:
            if dim in raw_anima and dim in self._prev_raw:
                deltas[dim] = raw_anima[dim] - self._prev_raw[dim]
        # Find opposing pairs where both deltas exceed threshold
        dims = list(deltas.keys())
        for i, a in enumerate(dims):
            for b in dims[i + 1:]:
                if (abs(deltas[a]) > VOLITIONAL_THRESHOLD and
                    abs(deltas[b]) > VOLITIONAL_THRESHOLD and
                    deltas[a] * deltas[b] < 0):  # Opposite signs
                    self._conflict_buffer.append(ConflictEvent(
                        timestamp=datetime.now(),
                        dim_a=a, dim_b=b,
                        grad_a=deltas[a], grad_b=deltas[b],
                        duration=1,
                        category="volitional",
                        action_type=action_type,
                    ))
                    self._action_conflict_counts[action_type] = (
                        self._action_conflict_counts.get(action_type, 0) + 1
                    )

    def get_active_conflicts(self, last_n: int = 20) -> List[ConflictEvent]:
        """Get recent conflicts."""
        return list(self._conflict_buffer)[-last_n:]

    def get_volitional_conflicts(self, last_n: int = 20) -> List[ConflictEvent]:
        """Get recent volitional conflicts only."""
        return [c for c in list(self._conflict_buffer)[-last_n * 3:]
                if c.category == "volitional"][-last_n:]

    def get_conflict_rate(self, action_type: str) -> float:
        """Fraction of this action type's uses that caused volitional conflicts."""
        total = self._action_total_counts.get(action_type, 0)
        if total == 0:
            return 0.0
        conflicts = self._action_conflict_counts.get(action_type, 0)
        return conflicts / total
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_value_tension.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/anima_mcp/value_tension.py tests/test_value_tension.py
git commit -m "feat: add ValueTensionTracker with structural, environmental, volitional detection"
```

---

### Task 3: Preference Meta-Learning and Unit Tests

**Files:**
- Modify: `src/anima_mcp/preferences.py` (add `influence_weight`, meta-learning cycle)
- Create: `tests/test_preference_meta.py`

**Step 1: Write the failing tests**

```python
# tests/test_preference_meta.py
import pytest
from anima_mcp.preferences import Preference, PreferenceSystem


class TestInfluenceWeight:
    def test_default_weight_is_one(self):
        p = Preference(dimension="warmth")
        assert p.influence_weight == 1.0

    def test_weight_floor_enforced(self):
        p = Preference(dimension="warmth", influence_weight=0.1)
        p.enforce_floor()
        assert p.influence_weight >= 0.3

    def test_weight_persists_in_json(self):
        p = Preference(dimension="warmth", influence_weight=0.8)
        d = p.to_dict()
        p2 = Preference.from_dict(d)
        assert abs(p2.influence_weight - 0.8) < 0.001


class TestConservation:
    def test_weights_sum_to_four(self):
        ps = PreferenceSystem.__new__(PreferenceSystem)
        ps._preferences = {
            "warmth": Preference("warmth", influence_weight=2.0),
            "clarity": Preference("clarity", influence_weight=1.5),
            "stability": Preference("stability", influence_weight=1.0),
            "presence": Preference("presence", influence_weight=0.5),
        }
        ps.enforce_weight_conservation()
        total = sum(p.influence_weight for p in ps._preferences.values())
        assert abs(total - 4.0) < 0.01

    def test_conservation_preserves_ratios(self):
        ps = PreferenceSystem.__new__(PreferenceSystem)
        ps._preferences = {
            "warmth": Preference("warmth", influence_weight=2.0),
            "clarity": Preference("clarity", influence_weight=2.0),
            "stability": Preference("stability", influence_weight=2.0),
            "presence": Preference("presence", influence_weight=2.0),
        }
        ps.enforce_weight_conservation()
        # All equal, should all be 1.0
        for p in ps._preferences.values():
            assert abs(p.influence_weight - 1.0) < 0.01


class TestTrajectoryHealth:
    def test_health_bounded_zero_one(self):
        from anima_mcp.preferences import compute_trajectory_health
        h = compute_trajectory_health(
            satisfaction_history=[0.5] * 20,
            action_efficacy=0.8,
            prediction_accuracy_trend=0.1,
        )
        assert 0.0 <= h <= 1.0

    def test_high_satisfaction_high_health(self):
        from anima_mcp.preferences import compute_trajectory_health
        h = compute_trajectory_health(
            satisfaction_history=[0.9] * 20,
            action_efficacy=0.9,
            prediction_accuracy_trend=0.1,
        )
        assert h > 0.7

    def test_high_variance_lowers_health(self):
        from anima_mcp.preferences import compute_trajectory_health
        h_stable = compute_trajectory_health(
            satisfaction_history=[0.6] * 20,
            action_efficacy=0.5,
            prediction_accuracy_trend=0.0,
        )
        h_volatile = compute_trajectory_health(
            satisfaction_history=[0.2, 0.9] * 10,
            action_efficacy=0.5,
            prediction_accuracy_trend=0.0,
        )
        assert h_stable > h_volatile


class TestMetaLearningCycle:
    def test_positive_correlation_boosts_weight(self):
        from anima_mcp.preferences import meta_learning_update
        weights = {"warmth": 1.0, "clarity": 1.0, "stability": 1.0, "presence": 1.0}
        # Warmth satisfaction positively correlated with future health
        correlations = {"warmth": 0.5, "clarity": 0.0, "stability": 0.0, "presence": 0.0}
        new_weights = meta_learning_update(weights, correlations, beta=0.005)
        assert new_weights["warmth"] > 1.0

    def test_negative_correlation_reduces_weight(self):
        from anima_mcp.preferences import meta_learning_update
        weights = {"warmth": 1.0, "clarity": 1.0, "stability": 1.0, "presence": 1.0}
        correlations = {"warmth": -0.5, "clarity": 0.0, "stability": 0.0, "presence": 0.0}
        new_weights = meta_learning_update(weights, correlations, beta=0.005)
        assert new_weights["warmth"] < 1.0

    def test_floor_preserved_after_update(self):
        from anima_mcp.preferences import meta_learning_update
        weights = {"warmth": 0.3, "clarity": 1.0, "stability": 1.0, "presence": 1.0}
        correlations = {"warmth": -1.0, "clarity": 0.0, "stability": 0.0, "presence": 0.0}
        new_weights = meta_learning_update(weights, correlations, beta=0.005)
        assert new_weights["warmth"] >= 0.3

    def test_conservation_after_update(self):
        from anima_mcp.preferences import meta_learning_update
        weights = {"warmth": 1.0, "clarity": 1.0, "stability": 1.0, "presence": 1.0}
        correlations = {"warmth": 0.8, "clarity": -0.3, "stability": 0.1, "presence": -0.1}
        new_weights = meta_learning_update(weights, correlations, beta=0.005)
        total = sum(new_weights.values())
        assert abs(total - 4.0) < 0.01
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_preference_meta.py -v`
Expected: FAIL — `influence_weight` not found on Preference

**Step 3: Add influence_weight to Preference and meta-learning functions**

Modify `src/anima_mcp/preferences.py`:

Add `influence_weight: float = 1.0` field to the Preference dataclass (after `experience_count`, ~line 57).

Add `enforce_floor()` method to Preference:
```python
def enforce_floor(self, floor: float = 0.3):
    self.influence_weight = max(floor, self.influence_weight)
```

Add to `to_dict()` and `from_dict()` to include `influence_weight`.

Add `enforce_weight_conservation()` to PreferenceSystem:
```python
def enforce_weight_conservation(self, target: float = 4.0):
    dims = [p for p in self._preferences.values() if p.dimension in ("warmth", "clarity", "stability", "presence")]
    total = sum(p.influence_weight for p in dims)
    if total > 0:
        scale = target / total
        for p in dims:
            p.influence_weight *= scale
```

Add module-level functions:
```python
def compute_trajectory_health(
    satisfaction_history: list,
    action_efficacy: float,
    prediction_accuracy_trend: float,
) -> float:
    if not satisfaction_history:
        return 0.5
    mean_sat = sum(satisfaction_history) / len(satisfaction_history)
    variance = sum((s - mean_sat) ** 2 for s in satisfaction_history) / len(satisfaction_history)
    return (
        0.30 * mean_sat
        + 0.25 * (1.0 - min(1.0, variance * 4.0))
        + 0.25 * min(1.0, max(0.0, action_efficacy))
        + 0.20 * min(1.0, max(0.0, prediction_accuracy_trend + 0.5))
    )


def meta_learning_update(
    weights: dict, correlations: dict, beta: float = 0.005
) -> dict:
    new_weights = {}
    for dim, w in weights.items():
        corr = correlations.get(dim, 0.0)
        new_w = w * (1.0 + beta * corr)
        new_w = max(0.3, new_w)  # Floor
        new_weights[dim] = new_w
    # Conservation: normalize to sum=4.0
    total = sum(new_weights.values())
    if total > 0:
        scale = 4.0 / total
        new_weights = {d: w * scale for d, w in new_weights.items()}
    # Re-enforce floors after normalization
    for d in new_weights:
        new_weights[d] = max(0.3, new_weights[d])
    return new_weights
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_preference_meta.py -v`
Expected: All PASS

**Step 5: Run existing preference tests to check no regressions**

Run: `python3 -m pytest tests/ -x -q --tb=short`
Expected: All existing tests PASS

**Step 6: Commit**

```bash
git add src/anima_mcp/preferences.py tests/test_preference_meta.py
git commit -m "feat: add preference influence_weight, meta-learning cycle, trajectory health"
```

---

### Task 4: Integrate Calibration Drift into Anima Computation

**Files:**
- Modify: `src/anima_mcp/anima.py:86-124` (sense_self to accept drifted midpoints)
- Modify: `src/anima_mcp/server.py:303,341` (pass drift midpoints)
- Modify: `src/anima_mcp/schema_hub.py:73-123` (update drift after trajectory)
- Create: `tests/test_drift_integration.py`

**Step 1: Write integration test**

```python
# tests/test_drift_integration.py
import pytest
from anima_mcp.calibration_drift import CalibrationDrift
from anima_mcp.config import NervousSystemCalibration


class TestDriftIntegration:
    def test_drifted_calibration_produces_different_anima(self):
        """Drifted midpoints should shift anima dimension values."""
        from anima_mcp.anima import sense_self
        from anima_mcp.sensors.mock import MockSensorInterface

        sensors = MockSensorInterface()
        readings = sensors.read()
        cal_default = NervousSystemCalibration()
        anima_default = sense_self(readings, cal_default)

        # Create calibration with shifted warmth midpoint
        cal_drifted = NervousSystemCalibration()
        cal_drifted.ambient_temp_min += 5.0  # Shift warmth baseline up
        cal_drifted.ambient_temp_max += 5.0
        anima_drifted = sense_self(readings, cal_drifted)

        # Warmth should differ (drifted baseline changes normalization)
        assert anima_default.warmth != anima_drifted.warmth

    def test_drift_midpoints_to_calibration_conversion(self):
        """CalibrationDrift.get_midpoints() can modify a NervousSystemCalibration."""
        drift = CalibrationDrift()
        drift.dimensions["warmth"].outer_ema = 0.55
        drift.dimensions["warmth"].apply_drift()
        midpoints = drift.get_midpoints()
        assert midpoints["warmth"] != 0.5  # Has drifted
```

**Step 2: Run test, verify it passes with current code (sanity check)**

Run: `python3 -m pytest tests/test_drift_integration.py -v`

**Step 3: Modify anima.py to accept drift midpoints**

In `anima.py`, modify `sense_self()` (line ~86) to accept optional `drift_midpoints`:

```python
def sense_self(
    readings: SensorReadings,
    calibration: Optional[NervousSystemCalibration] = None,
    drift_midpoints: Optional[Dict[str, float]] = None,
) -> Anima:
```

When `drift_midpoints` is provided, adjust calibration ranges before computing dimensions. For example, if warmth midpoint drifted from 0.5 to 0.55, shift `ambient_temp_min` and `ambient_temp_max` to center on the new midpoint.

The conversion: `offset_fraction = (drift_midpoints["warmth"] - 0.5) / 0.5` then shift the temp range by `offset_fraction * half_range`.

Also modify `sense_self_with_memory()` to pass through `drift_midpoints`.

**Step 4: Modify server.py to create and update CalibrationDrift**

In `server.py`:
- Import CalibrationDrift at top
- In `wake()` (~line 2216): Load or create CalibrationDrift, store as global `_calibration_drift`
- At lines ~303, 341: Pass `drift_midpoints=_calibration_drift.get_midpoints()` to sense_self
- At line ~2004: After `compose_schema()`, call `_calibration_drift.update(attractor_center)` with the trajectory's attractor center
- In `sleep()`: Save drift state to `~/.anima/calibration_drift.json`

**Step 5: Modify schema_hub.py to expose drift as schema nodes**

After trajectory computation, inject drift offsets as schema nodes:
```python
offsets = calibration_drift.get_offsets()
for dim, offset in offsets.items():
    schema.add_node(f"drift_{dim}_offset", offset, "drift")
```

**Step 6: Run full test suite**

Run: `python3 -m pytest tests/ -x -q --tb=short`
Expected: All PASS

**Step 7: Commit**

```bash
git add src/anima_mcp/anima.py src/anima_mcp/server.py src/anima_mcp/schema_hub.py tests/test_drift_integration.py
git commit -m "feat: integrate calibration drift into anima sensing and schema hub"
```

---

### Task 5: Integrate Value Tension into Agency

**Files:**
- Modify: `src/anima_mcp/agency.py:362-371` (discount by conflict rate)
- Modify: `src/anima_mcp/server.py:882-897` (pass raw anima to tension tracker)
- Create: `tests/test_tension_integration.py`

**Step 1: Write integration test**

```python
# tests/test_tension_integration.py
import pytest
from anima_mcp.value_tension import ValueTensionTracker
from anima_mcp.agency import ActionSelector


class TestTensionAgencyIntegration:
    def test_conflict_rate_discounts_action_value(self):
        tracker = ValueTensionTracker()
        selector = ActionSelector()

        # Simulate led_brightness causing warmth-stability conflicts
        for _ in range(20):
            tracker.observe({"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}, None)
        for _ in range(5):
            tracker.observe({"warmth": 0.7, "clarity": 0.5, "stability": 0.3, "presence": 0.5}, "led_brightness")
            tracker.observe({"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}, None)

        rate = tracker.get_conflict_rate("led_brightness")
        discount = 0.9 ** rate
        assert discount < 1.0  # Should reduce expected value
```

**Step 2: Modify agency.py _get_action_value to accept conflict rates**

Add optional `conflict_rates` parameter to `select_action()`. When provided, apply discount:

```python
# In _get_action_value or select_action, after computing base value:
if conflict_rates:
    rate = conflict_rates.get(action_key, 0.0)
    value *= (0.9 ** rate)
```

**Step 3: Modify server.py main loop**

- Import ValueTensionTracker
- In `wake()`: Create tracker, store as global `_tension_tracker`
- At agency section (~line 882-897): Before `select_action()`, call `_tension_tracker.observe(raw_anima, action_type)`. Pass `conflict_rates` dict to `select_action()`.

**Step 4: Run full test suite**

Run: `python3 -m pytest tests/ -x -q --tb=short`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/anima_mcp/agency.py src/anima_mcp/server.py tests/test_tension_integration.py
git commit -m "feat: integrate value tension into agency action selection with conflict discount"
```

---

### Task 6: Integrate Meta-Learning Cycle into Server Loop

**Files:**
- Modify: `src/anima_mcp/server.py` (add daily meta-learning cycle)
- Modify: `src/anima_mcp/server_state.py` (add META_LEARNING_INTERVAL constant)
- Create: `tests/test_meta_integration.py`

**Step 1: Add interval constant**

In `server_state.py`, add:
```python
META_LEARNING_INTERVAL = 21600  # ~720 iterations * 30 = daily at ~2s/iter
```

**Step 2: Write integration test**

```python
# tests/test_meta_integration.py
import pytest
from anima_mcp.preferences import (
    compute_trajectory_health, meta_learning_update
)


class TestMetaLearningIntegration:
    def test_full_cycle_preserves_invariants(self):
        """After meta-learning update, conservation and floors hold."""
        weights = {"warmth": 1.2, "clarity": 0.8, "stability": 1.0, "presence": 1.0}
        correlations = {"warmth": 0.3, "clarity": -0.5, "stability": 0.1, "presence": -0.2}
        new = meta_learning_update(weights, correlations)
        assert abs(sum(new.values()) - 4.0) < 0.01
        assert all(w >= 0.3 for w in new.values())

    def test_trajectory_health_with_real_data_range(self):
        """Health computation works with realistic input ranges."""
        h = compute_trajectory_health(
            satisfaction_history=[0.4 + i * 0.01 for i in range(100)],
            action_efficacy=0.6,
            prediction_accuracy_trend=0.05,
        )
        assert 0.0 <= h <= 1.0
```

**Step 3: Add meta-learning cycle to server.py main loop**

After the reflection section (~line 2045), add a new block gated by `META_LEARNING_INTERVAL`:

```python
if loop_count % META_LEARNING_INTERVAL == 0 and _growth:
    # Compute trajectory health
    health = compute_trajectory_health(
        satisfaction_history=_satisfaction_history[-100:],
        action_efficacy=_action_efficacy,
        prediction_accuracy_trend=_prediction_trend,
    )
    # Record healthy state for drift restart target
    if _calibration_drift:
        _calibration_drift.record_healthy_state(health)
    # Compute lagged correlations and update preference weights
    # (implementation detail: correlate per-dimension satisfaction with health)
    if _pref_system:
        correlations = _compute_lagged_correlations(_satisfaction_per_dim, _health_history)
        weights = {d: p.influence_weight for d, p in _pref_system._preferences.items()
                   if d in ("warmth", "clarity", "stability", "presence")}
        new_weights = meta_learning_update(weights, correlations)
        for d, w in new_weights.items():
            if d in _pref_system._preferences:
                _pref_system._preferences[d].influence_weight = w
```

This also requires tracking `_satisfaction_history`, `_satisfaction_per_dim`, `_health_history` as rolling deques in the main loop.

**Step 4: Run full test suite**

Run: `python3 -m pytest tests/ -x -q --tb=short`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/anima_mcp/server.py src/anima_mcp/server_state.py tests/test_meta_integration.py
git commit -m "feat: integrate daily meta-learning cycle for preference weight evolution"
```

---

### Task 7: LLM Narrator Read-Only Access

**Files:**
- Modify: `src/anima_mcp/llm_gateway.py:430-446` (add drift/tension/weight context)

**Step 1: Add read-only context to _build_state_description()**

In `llm_gateway.py`, within `_build_state_description()` (after the self-reflection insights block ~line 446):

```python
# Add computational selfhood context (read-only, narrator only)
try:
    from .calibration_drift import CalibrationDrift
    from .value_tension import ValueTensionTracker
    drift_desc = ""
    tension_desc = ""
    weight_desc = ""
    # These are populated from server globals via a getter function
    # Implementation: add get_selfhood_context() to server.py that returns dict
    selfhood = _get_selfhood_context()
    if selfhood:
        if selfhood.get("drift_offsets"):
            offsets = selfhood["drift_offsets"]
            notable = [(d, o) for d, o in offsets.items() if abs(o) > 0.02]
            if notable:
                drift_desc = "\n\nHow my baseline has shifted: " + ", ".join(
                    f"{d} {'up' if o > 0 else 'down'} {abs(o):.0%}" for d, o in notable
                )
        if selfhood.get("active_tensions"):
            tensions = selfhood["active_tensions"]
            if tensions:
                tension_desc = "\n\nTensions I'm experiencing: " + ", ".join(
                    f"{t['dim_a']} vs {t['dim_b']}" for t in tensions[:3]
                )
        if selfhood.get("weight_changes"):
            changes = selfhood["weight_changes"]
            notable = [(d, c) for d, c in changes.items() if abs(c - 1.0) > 0.05]
            if notable:
                weight_desc = "\n\nHow my values have shifted: " + ", ".join(
                    f"I care {'more' if c > 1.0 else 'less'} about {d}" for d, c in notable
                )
        state_desc += drift_desc + tension_desc + weight_desc
except Exception:
    pass
```

**Step 2: Run full test suite (no new tests needed — this is read-only)**

Run: `python3 -m pytest tests/ -x -q --tb=short`
Expected: All PASS

**Step 3: Commit**

```bash
git add src/anima_mcp/llm_gateway.py
git commit -m "feat: add read-only selfhood context to LLM narrator prompts"
```

---

### Task 8: Property Tests and Invariant Verification

**Files:**
- Create: `tests/test_selfhood_invariants.py`

**Step 1: Write property tests**

```python
# tests/test_selfhood_invariants.py
"""Property tests: invariants that must hold after ANY sequence of operations."""
import pytest
import random
from anima_mcp.calibration_drift import CalibrationDrift
from anima_mcp.preferences import meta_learning_update
from anima_mcp.value_tension import ValueTensionTracker


class TestDriftInvariants:
    @pytest.mark.parametrize("seed", range(10))
    def test_midpoints_always_bounded(self, seed):
        random.seed(seed)
        drift = CalibrationDrift()
        for _ in range(1000):
            attractor = {d: random.uniform(0, 1) for d in ["warmth", "clarity", "stability", "presence"]}
            drift.update(attractor)
        for d in drift.dimensions.values():
            assert d.hardware_default * (1 - d.bound_low) <= d.current_midpoint <= d.hardware_default * (1 + d.bound_high) + 0.001

    @pytest.mark.parametrize("seed", range(10))
    def test_total_drift_budget_always_held(self, seed):
        random.seed(seed)
        drift = CalibrationDrift()
        for _ in range(1000):
            attractor = {d: random.uniform(0, 1) for d in ["warmth", "clarity", "stability", "presence"]}
            drift.update(attractor)
        total = sum(abs(d.current_midpoint - d.hardware_default) for d in drift.dimensions.values())
        assert total <= drift.total_drift_budget + 0.001


class TestPreferenceInvariants:
    @pytest.mark.parametrize("seed", range(10))
    def test_weights_always_sum_to_four(self, seed):
        random.seed(seed)
        weights = {"warmth": 1.0, "clarity": 1.0, "stability": 1.0, "presence": 1.0}
        for _ in range(100):
            correlations = {d: random.uniform(-1, 1) for d in weights}
            weights = meta_learning_update(weights, correlations)
        total = sum(weights.values())
        assert abs(total - 4.0) < 0.01

    @pytest.mark.parametrize("seed", range(10))
    def test_no_weight_below_floor(self, seed):
        random.seed(seed)
        weights = {"warmth": 1.0, "clarity": 1.0, "stability": 1.0, "presence": 1.0}
        for _ in range(100):
            correlations = {d: random.uniform(-1, 1) for d in weights}
            weights = meta_learning_update(weights, correlations)
        assert all(w >= 0.3 for w in weights.values())


class TestTensionInvariants:
    def test_buffer_never_exceeds_capacity(self):
        tracker = ValueTensionTracker(buffer_size=50)
        for i in range(200):
            raw = {"warmth": 0.3 + (i % 10) * 0.05, "clarity": 0.5, "stability": 0.7 - (i % 10) * 0.05, "presence": 0.5}
            tracker.observe(raw, "test_action" if i % 3 == 0 else None)
        assert len(tracker._conflict_buffer) <= 50

    def test_conflict_rate_bounded_zero_one(self):
        tracker = ValueTensionTracker()
        for _ in range(50):
            tracker.observe({"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}, "test")
        rate = tracker.get_conflict_rate("test")
        assert 0.0 <= rate <= 1.0
        rate_unknown = tracker.get_conflict_rate("nonexistent")
        assert rate_unknown == 0.0
```

**Step 2: Run all tests**

Run: `python3 -m pytest tests/ -x -q --tb=short`
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/test_selfhood_invariants.py
git commit -m "test: add property tests for selfhood invariants (bounds, conservation, capacity)"
```

---

### Task 9: Deploy to Pi and Verify

**Step 1: Push to remote**

```bash
git push
```

**Step 2: Deploy via MCP**

```bash
mcp__anima__git_pull(restart=true)
```

**Step 3: Verify no errors on startup**

```bash
ssh unitares-anima@lumen.local "journalctl -u anima --since '2 min ago' --no-pager" | grep -i 'error\|drift\|tension\|meta'
```

**Step 4: Verify drift state file created**

```bash
ssh unitares-anima@lumen.local "cat ~/.anima/calibration_drift.json 2>/dev/null | python3 -m json.tool | head -20"
```

**Step 5: Monitor first schema cycle for drift nodes**

```bash
ssh unitares-anima@lumen.local "journalctl -u anima -f" | grep -i 'drift\|tension\|conflict'
```
