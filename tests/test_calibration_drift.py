"""
Tests for CalibrationDrift — endogenous midpoint drift via double-EMA.

Replaces fixed calibration midpoints with experience-derived ones.
"Normal warmth" becomes "what warmth has typically been" rather than
a fixed developer constant.
"""

import pytest
from anima_mcp.calibration_drift import DimensionDrift, CalibrationDrift


class TestDimensionDrift:
    def test_initial_midpoint_equals_default(self):
        d = DimensionDrift("warmth", hardware_default=0.5)
        assert d.current_midpoint == 0.5

    def test_inner_ema_tracks_signal(self):
        d = DimensionDrift("warmth", hardware_default=0.5)
        for _ in range(60):
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
        assert drift.dimensions["warmth"].current_midpoint < 0.55 * (1 + 0.20)

    def test_surprise_acceleration(self):
        drift = CalibrationDrift()
        d = drift.dimensions["warmth"]
        normal_alpha = d.outer_alpha
        d.inner_ema = d.hardware_default + 0.3
        d._deviation_count = 101
        d.check_surprise_acceleration()
        assert d.outer_alpha > normal_alpha
