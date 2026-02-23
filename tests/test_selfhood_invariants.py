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
