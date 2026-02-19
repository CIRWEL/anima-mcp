"""
Tests for anima_history module - AnimaSnapshot, AnimaHistory, attractor basins,
dimension stats, perturbation detection, void integral, and persistence.

Run with: pytest tests/test_anima_history.py -v
"""

import pytest
from datetime import datetime, timedelta

import anima_mcp.anima_history
from anima_mcp.anima_history import (
    AnimaSnapshot,
    AnimaHistory,
    reset_anima_history,
)


# =============================================================================
# Helpers
# =============================================================================

def _make_history(tmp_path, *, max_size=2000, auto_save_interval=100):
    """Create an AnimaHistory backed by a temp file."""
    return AnimaHistory(
        persistence_path=tmp_path / "history.json",
        max_size=max_size,
        auto_save_interval=auto_save_interval,
    )


def _fill_identical(history, n, *, w=0.5, c=0.6, s=0.7, p=0.8, t0=None, dt_seconds=2):
    """Append *n* identical records with incrementing timestamps."""
    t0 = t0 or datetime(2025, 1, 1, 12, 0, 0)
    for i in range(n):
        history.record(
            warmth=w, clarity=c, stability=s, presence=p,
            timestamp=t0 + timedelta(seconds=i * dt_seconds),
        )


# =============================================================================
# Test: AnimaSnapshot
# =============================================================================

class TestAnimaSnapshot:
    """Tests for the AnimaSnapshot dataclass."""

    def test_to_dict_has_expected_keys(self):
        """to_dict should return keys t, w, c, s, p."""
        snap = AnimaSnapshot(
            timestamp=datetime(2025, 6, 1, 12, 0, 0),
            warmth=0.5, clarity=0.6, stability=0.7, presence=0.8,
        )
        d = snap.to_dict()
        assert set(d.keys()) == {"t", "w", "c", "s", "p"}

    def test_from_dict_round_trip(self):
        """from_dict(to_dict()) should preserve all values."""
        original = AnimaSnapshot(
            timestamp=datetime(2025, 6, 1, 12, 0, 0),
            warmth=0.1234, clarity=0.5678, stability=0.9012, presence=0.3456,
        )
        restored = AnimaSnapshot.from_dict(original.to_dict())
        assert restored.timestamp == original.timestamp
        assert restored.warmth == pytest.approx(original.warmth, abs=1e-4)
        assert restored.clarity == pytest.approx(original.clarity, abs=1e-4)
        assert restored.stability == pytest.approx(original.stability, abs=1e-4)
        assert restored.presence == pytest.approx(original.presence, abs=1e-4)

    def test_to_vector_order(self):
        """to_vector should return [warmth, clarity, stability, presence]."""
        snap = AnimaSnapshot(
            timestamp=datetime(2025, 1, 1),
            warmth=0.1, clarity=0.2, stability=0.3, presence=0.4,
        )
        assert snap.to_vector() == [0.1, 0.2, 0.3, 0.4]


# =============================================================================
# Test: Record
# =============================================================================

class TestRecord:
    """Tests for AnimaHistory.record() and record_from_anima()."""

    def test_record_appends_to_history(self, tmp_path):
        """Each call to record() should increase history length by one."""
        h = _make_history(tmp_path)
        assert len(h) == 0
        h.record(warmth=0.5, clarity=0.5, stability=0.5, presence=0.5)
        assert len(h) == 1
        h.record(warmth=0.6, clarity=0.6, stability=0.6, presence=0.6)
        assert len(h) == 2

    def test_default_timestamp_is_approximately_now(self, tmp_path):
        """When no timestamp is given, it should default to ~now."""
        h = _make_history(tmp_path)
        before = datetime.now()
        h.record(warmth=0.5, clarity=0.5, stability=0.5, presence=0.5)
        after = datetime.now()

        recorded_ts = h._history[0].timestamp
        assert before <= recorded_ts <= after

    def test_max_size_overflow(self, tmp_path):
        """History deque should not exceed max_size."""
        h = _make_history(tmp_path, max_size=10, auto_save_interval=9999)
        _fill_identical(h, 20)
        assert len(h) == 10

    def test_record_from_anima_duck_typed(self, tmp_path):
        """record_from_anima should work with any object that has the four attrs."""
        h = _make_history(tmp_path)

        class FakeAnima:
            warmth = 0.11
            clarity = 0.22
            stability = 0.33
            presence = 0.44

        h.record_from_anima(FakeAnima())
        assert len(h) == 1
        snap = h._history[0]
        assert snap.warmth == pytest.approx(0.11)
        assert snap.clarity == pytest.approx(0.22)
        assert snap.stability == pytest.approx(0.33)
        assert snap.presence == pytest.approx(0.44)

    def test_auto_save_triggers(self, tmp_path):
        """After auto_save_interval records, the persistence file should exist."""
        path = tmp_path / "history.json"
        h = AnimaHistory(
            persistence_path=path,
            auto_save_interval=5,
        )
        assert not path.exists()
        _fill_identical(h, 5)
        assert path.exists()


# =============================================================================
# Test: Attractor Basin
# =============================================================================

class TestAttractorBasin:
    """Tests for AnimaHistory.get_attractor_basin()."""

    def test_fewer_than_10_returns_none(self, tmp_path):
        """With fewer than 10 records, attractor basin should be None."""
        h = _make_history(tmp_path)
        _fill_identical(h, 9)
        assert h.get_attractor_basin() is None

    def test_identical_records_center_equals_value(self, tmp_path):
        """10 identical records should yield a center equal to that value."""
        h = _make_history(tmp_path)
        _fill_identical(h, 10, w=0.3, c=0.4, s=0.5, p=0.6)
        basin = h.get_attractor_basin()
        assert basin is not None
        assert basin["center"][0] == pytest.approx(0.3, abs=1e-3)
        assert basin["center"][1] == pytest.approx(0.4, abs=1e-3)
        assert basin["center"][2] == pytest.approx(0.5, abs=1e-3)
        assert basin["center"][3] == pytest.approx(0.6, abs=1e-3)

    def test_result_has_required_keys(self, tmp_path):
        """Result dict should contain center, n_observations, dimensions, etc."""
        h = _make_history(tmp_path)
        _fill_identical(h, 15)
        basin = h.get_attractor_basin()
        assert basin is not None
        assert "center" in basin
        assert "n_observations" in basin
        assert "time_span_seconds" in basin
        assert "dimensions" in basin
        assert basin["dimensions"] == ["warmth", "clarity", "stability", "presence"]

    def test_eigenvalues_non_negative_numpy_path(self, tmp_path):
        """When numpy is available, eigenvalues should all be >= 0."""
        if not anima_mcp.anima_history.HAS_NUMPY:
            pytest.skip("numpy not available")
        h = _make_history(tmp_path)
        _fill_identical(h, 20, w=0.5, c=0.6, s=0.7, p=0.8)
        basin = h.get_attractor_basin()
        assert basin is not None
        assert "eigenvalues" in basin
        for ev in basin["eigenvalues"]:
            assert ev >= 0

    def test_pure_python_fallback_has_variance(self, tmp_path, monkeypatch):
        """With HAS_NUMPY=False, result should contain 'variance' key."""
        monkeypatch.setattr(anima_mcp.anima_history, "HAS_NUMPY", False)
        h = _make_history(tmp_path)
        _fill_identical(h, 15)
        basin = h.get_attractor_basin()
        assert basin is not None
        assert "variance" in basin
        assert "covariance" not in basin
        assert "_note" in basin


# =============================================================================
# Test: Dimension Stats
# =============================================================================

class TestDimensionStats:
    """Tests for AnimaHistory.get_dimension_stats()."""

    def test_fewer_than_5_returns_none(self, tmp_path):
        """With fewer than 5 records, dimension stats should be None."""
        h = _make_history(tmp_path)
        _fill_identical(h, 4)
        assert h.get_dimension_stats("warmth") is None

    def test_constant_values_std_approximately_zero(self, tmp_path):
        """Constant dimension values should yield std close to 0."""
        h = _make_history(tmp_path)
        _fill_identical(h, 10, w=0.5, c=0.5, s=0.5, p=0.5)
        stats = h.get_dimension_stats("warmth")
        assert stats is not None
        assert stats["std"] == pytest.approx(0.0, abs=1e-4)

    def test_correct_min_max_for_distinct_values(self, tmp_path):
        """min and max should reflect actual extremes in the data."""
        h = _make_history(tmp_path)
        t0 = datetime(2025, 1, 1, 12, 0, 0)
        values = [0.1, 0.3, 0.5, 0.7, 0.9]
        for i, v in enumerate(values):
            h.record(
                warmth=v, clarity=0.5, stability=0.5, presence=0.5,
                timestamp=t0 + timedelta(seconds=i),
            )
        stats = h.get_dimension_stats("warmth")
        assert stats is not None
        assert stats["min"] == pytest.approx(0.1, abs=1e-4)
        assert stats["max"] == pytest.approx(0.9, abs=1e-4)
        assert stats["n"] == 5


# =============================================================================
# Test: Perturbation and Void
# =============================================================================

class TestPerturbationAndVoid:
    """Tests for detect_perturbation() and compute_void_integral()."""

    def test_detect_perturbation_insufficient_data(self, tmp_path):
        """With < 20 records, detect_perturbation should return None."""
        h = _make_history(tmp_path)
        _fill_identical(h, 19)
        assert h.detect_perturbation() is None

    def test_state_near_center_not_detected(self, tmp_path):
        """When recent states are at the center, detected should be False."""
        h = _make_history(tmp_path)
        _fill_identical(h, 50, w=0.5, c=0.5, s=0.5, p=0.5)
        result = h.detect_perturbation()
        assert result is not None
        assert result["detected"] is False

    def test_extreme_outlier_detected(self, tmp_path):
        """A large outlier in the last 5 records should be detected."""
        h = _make_history(tmp_path)
        # Build a stable basin at (0.5, 0.5, 0.5, 0.5)
        _fill_identical(h, 50, w=0.5, c=0.5, s=0.5, p=0.5)
        # Now inject an extreme outlier
        h.record(
            warmth=0.99, clarity=0.99, stability=0.99, presence=0.99,
            timestamp=datetime(2025, 1, 1, 13, 0, 0),
        )
        result = h.detect_perturbation(threshold=0.15)
        assert result is not None
        assert result["detected"] is True
        assert result["distance"] > 0.15

    def test_compute_void_integral_has_required_keys(self, tmp_path):
        """compute_void_integral result should contain expected keys."""
        h = _make_history(tmp_path)
        _fill_identical(h, 30)
        result = h.compute_void_integral()
        assert result is not None
        for key in ("void_integral", "avg_deviation", "rate",
                     "max_deviation", "n_observations", "time_span_seconds", "center"):
            assert key in result, f"Missing key: {key}"


# =============================================================================
# Test: Persistence
# =============================================================================

class TestPersistence:
    """Tests for save/load round-trip and missing-file resilience."""

    def test_save_load_round_trip(self, tmp_path):
        """Saving then loading should preserve record count."""
        path = tmp_path / "history.json"
        h1 = AnimaHistory(persistence_path=path, auto_save_interval=9999)
        _fill_identical(h1, 25)
        h1.save()

        h2 = AnimaHistory(persistence_path=path, auto_save_interval=9999)
        assert len(h2) == 25

    def test_missing_file_empty_history_no_crash(self, tmp_path):
        """Loading from a non-existent file should yield empty history, not crash."""
        path = tmp_path / "does_not_exist.json"
        h = AnimaHistory(persistence_path=path)
        assert len(h) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
