"""
Tests for adaptive_prediction module.

Validates learned pattern updates, feature extraction, prediction logic,
observation/surprise detection, and persistence round-trips.
"""

import math
import pytest
from datetime import datetime
from collections import deque

from anima_mcp.adaptive_prediction import (
    LearnedPattern,
    PatternFeatures,
    AdaptivePredictionModel,
)


# ---------------------------------------------------------------------------
# TestLearnedPatternUpdate
# ---------------------------------------------------------------------------


class TestLearnedPatternUpdate:
    """Test LearnedPattern.update() statistics."""

    def test_single_update_mean_equals_value(self):
        """After one update the mean equals the observed value."""
        p = LearnedPattern(pattern_key="k", variable="temp")
        p.update(42.0)
        assert p.mean == pytest.approx(42.0)

    def test_two_updates_mean_is_average(self):
        """After two updates the mean is the simple average."""
        p = LearnedPattern(pattern_key="k", variable="temp")
        p.update(10.0)
        p.update(20.0)
        assert p.mean == pytest.approx(15.0)

    def test_variance_increases_with_spread(self):
        """Widely spread values produce higher variance than tight ones."""
        tight = LearnedPattern(pattern_key="k", variable="v")
        for v in [10.0, 10.1, 9.9, 10.0, 10.05]:
            tight.update(v)

        spread = LearnedPattern(pattern_key="k", variable="v")
        for v in [0.0, 100.0, 0.0, 100.0, 50.0]:
            spread.update(v)

        assert spread.variance > tight.variance

    def test_variance_never_negative(self):
        """Variance must remain non-negative despite float arithmetic."""
        p = LearnedPattern(pattern_key="k", variable="v")
        # Feed identical values -- Welford delta*delta2 could theoretically go tiny-negative.
        for _ in range(20):
            p.update(7.777777777)
        assert p.variance >= 0.0

    def test_confidence_grows_with_samples(self):
        """Confidence should grow as sample count increases (constant value)."""
        p = LearnedPattern(pattern_key="k", variable="v")
        p.update(5.0)
        conf_1 = p.confidence
        for _ in range(9):
            p.update(5.0)
        conf_10 = p.confidence
        assert conf_10 > conf_1

    def test_confidence_penalised_by_high_variance(self):
        """High variance should reduce confidence compared to low variance."""
        low_var = LearnedPattern(pattern_key="k", variable="v")
        for _ in range(10):
            low_var.update(5.0)

        high_var = LearnedPattern(pattern_key="k", variable="v")
        for v in [0.0, 10.0, 0.0, 10.0, 0.0, 10.0, 0.0, 10.0, 0.0, 10.0]:
            high_var.update(v)

        assert low_var.confidence > high_var.confidence


# ---------------------------------------------------------------------------
# TestExtractFeatures
# ---------------------------------------------------------------------------


class TestExtractFeatures:
    """Test _extract_features bucketing and determinism."""

    def _model(self, tmp_path):
        return AdaptivePredictionModel(persistence_path=tmp_path / "patterns.json")

    def test_light_bucket_dark(self, tmp_path):
        """Light < 10 maps to 'dark'."""
        m = self._model(tmp_path)
        f = m._extract_features(datetime(2025, 1, 6, 12, 0), current_light=5.0)
        assert f.light_level == "dark"

    def test_light_bucket_dim(self, tmp_path):
        """Light in [10, 100) maps to 'dim'."""
        m = self._model(tmp_path)
        f = m._extract_features(datetime(2025, 1, 6, 12, 0), current_light=50.0)
        assert f.light_level == "dim"

    def test_light_bucket_bright(self, tmp_path):
        """Light in [100, 1000) maps to 'bright'."""
        m = self._model(tmp_path)
        f = m._extract_features(datetime(2025, 1, 6, 12, 0), current_light=500.0)
        assert f.light_level == "bright"

    def test_light_bucket_very_bright(self, tmp_path):
        """Light >= 1000 maps to 'very_bright'."""
        m = self._model(tmp_path)
        f = m._extract_features(datetime(2025, 1, 6, 12, 0), current_light=2000.0)
        assert f.light_level == "very_bright"

    def test_light_none_gives_unknown(self, tmp_path):
        """None light maps to 'unknown'."""
        m = self._model(tmp_path)
        f = m._extract_features(datetime(2025, 1, 6, 12, 0), current_light=None)
        assert f.light_level == "unknown"

    def test_temp_zone_cold(self, tmp_path):
        """Temp < 15 maps to 'cold'."""
        m = self._model(tmp_path)
        f = m._extract_features(datetime(2025, 1, 6, 12, 0), current_temp=10.0)
        assert f.temp_zone == "cold"

    def test_temp_zone_comfortable(self, tmp_path):
        """Temp in [20, 25) maps to 'comfortable'."""
        m = self._model(tmp_path)
        f = m._extract_features(datetime(2025, 1, 6, 12, 0), current_temp=22.0)
        assert f.temp_zone == "comfortable"

    def test_weekend_detection_saturday(self, tmp_path):
        """Saturday (weekday() == 5) is detected as weekend."""
        m = self._model(tmp_path)
        saturday = datetime(2025, 1, 4, 12, 0)  # 2025-01-04 is a Saturday
        f = m._extract_features(saturday)
        assert f.is_weekend is True

    def test_weekday_detection_monday(self, tmp_path):
        """Monday (weekday() == 0) is not weekend."""
        m = self._model(tmp_path)
        monday = datetime(2025, 1, 6, 12, 0)  # 2025-01-06 is a Monday
        f = m._extract_features(monday)
        assert f.is_weekend is False

    def test_to_key_deterministic(self, tmp_path):
        """to_key() returns the same string for the same inputs."""
        m = self._model(tmp_path)
        t = datetime(2025, 1, 6, 14, 35)
        f1 = m._extract_features(t, current_light=50.0, current_temp=22.0)
        f2 = m._extract_features(t, current_light=50.0, current_temp=22.0)
        assert f1.to_key() == f2.to_key()
        # Verify the key includes the expected components
        key = f1.to_key()
        assert key == "14:3:0:dim:comfortable"


# ---------------------------------------------------------------------------
# TestPredict
# ---------------------------------------------------------------------------


class TestPredict:
    """Test predict() method across fallback tiers."""

    def test_empty_model_no_fallback(self, tmp_path):
        """Empty model with no fallback returns (None, 0.0)."""
        m = AdaptivePredictionModel(persistence_path=tmp_path / "p.json")
        val, conf = m.predict("temp", current_time=datetime(2025, 1, 6, 12, 0))
        assert val is None
        assert conf == pytest.approx(0.0)

    def test_empty_model_with_fallback(self, tmp_path):
        """Empty model with fallback returns the fallback at low confidence."""
        m = AdaptivePredictionModel(persistence_path=tmp_path / "p.json")
        val, conf = m.predict(
            "temp", current_time=datetime(2025, 1, 6, 12, 0), fallback=20.0
        )
        assert val == pytest.approx(20.0)
        assert conf == pytest.approx(0.1)

    def test_enough_observations_returns_near_mean(self, tmp_path):
        """After enough identical observations, predict returns near the mean."""
        m = AdaptivePredictionModel(persistence_path=tmp_path / "p.json")
        t = datetime(2025, 1, 6, 14, 5)
        for _ in range(10):
            m.observe({"temp": 22.0}, current_time=t, current_light=50.0, current_temp=22.0)

        val, conf = m.predict(
            "temp", current_time=t, current_light=50.0, current_temp=22.0
        )
        assert val == pytest.approx(22.0, abs=0.5)
        assert conf > 0.5

    def test_pattern_with_few_samples_falls_through(self, tmp_path):
        """A pattern with < 3 samples should not be used directly."""
        m = AdaptivePredictionModel(persistence_path=tmp_path / "p.json")
        t = datetime(2025, 1, 6, 14, 5)
        # Observe only 2 values -- below the min-3 threshold
        m.observe({"temp": 22.0}, current_time=t, current_light=50.0, current_temp=22.0)
        m.observe({"temp": 22.0}, current_time=t, current_light=50.0, current_temp=22.0)

        val, conf = m.predict(
            "temp", current_time=t, current_light=50.0, current_temp=22.0, fallback=99.0
        )
        # Should not return mean=22 with high confidence -- falls through
        # Could hit the hour-prefix search or fallback depending on state
        assert conf < 0.5 or val == pytest.approx(99.0, abs=1.0)

    def test_recent_trend_extrapolation(self, tmp_path):
        """With recent values and no learned pattern, trend extrapolation is used."""
        m = AdaptivePredictionModel(persistence_path=tmp_path / "p.json")
        val, conf = m.predict(
            "humidity",
            current_time=datetime(2025, 1, 6, 12, 0),
            recent_values=[40.0, 45.0],
        )
        # trend = 45 - 40 = 5; predicted = 45 + 5*0.3 = 46.5
        assert val == pytest.approx(46.5)
        assert conf == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# TestObserveAndSurprise
# ---------------------------------------------------------------------------


class TestObserveAndSurprise:
    """Test observe() side-effects and get_surprising_deviation()."""

    def test_observe_creates_pattern(self, tmp_path):
        """observe() should create an entry in _patterns."""
        m = AdaptivePredictionModel(persistence_path=tmp_path / "p.json")
        t = datetime(2025, 1, 6, 14, 5)
        m.observe({"light": 300.0}, current_time=t, current_light=300.0)
        assert "light" in m._patterns
        assert len(m._patterns["light"]) > 0

    def test_observe_appends_to_history(self, tmp_path):
        """observe() should append an entry to the internal history deque."""
        m = AdaptivePredictionModel(persistence_path=tmp_path / "p.json")
        assert len(m._history) == 0
        t = datetime(2025, 1, 6, 14, 5)
        m.observe({"light": 300.0}, current_time=t)
        assert len(m._history) == 1

    def test_surprising_deviation_no_prior_pattern(self, tmp_path):
        """With no learned pattern, get_surprising_deviation returns is_surprising=True."""
        m = AdaptivePredictionModel(persistence_path=tmp_path / "p.json")
        dev, is_surprising = m.get_surprising_deviation(
            "temp", 22.0, current_time=datetime(2025, 1, 6, 12, 0)
        )
        assert is_surprising is True

    def test_stable_pattern_within_2_stddev_not_surprising(self, tmp_path):
        """A value within 2 stddevs of a well-learned pattern is not surprising."""
        m = AdaptivePredictionModel(persistence_path=tmp_path / "p.json")
        t = datetime(2025, 1, 6, 14, 5)
        # Build a stable pattern with small variance
        for _ in range(15):
            m.observe(
                {"warmth": 0.5}, current_time=t, current_light=50.0, current_temp=22.0
            )

        # Value close to mean (within 2 stddev of near-zero variance)
        dev, is_surprising = m.get_surprising_deviation(
            "warmth", 0.5, current_time=t, current_light=50.0, current_temp=22.0
        )
        assert is_surprising is False

    def test_log_scale_light_normalization(self, tmp_path):
        """Light deviation uses log-scale normalization."""
        m = AdaptivePredictionModel(persistence_path=tmp_path / "p.json")
        t = datetime(2025, 1, 6, 14, 5)
        # Build pattern around 100 lux
        for _ in range(15):
            m.observe(
                {"light": 100.0}, current_time=t, current_light=100.0, current_temp=22.0
            )

        # Deviation at 1000 lux (1 order of magnitude)
        dev, _ = m.get_surprising_deviation(
            "light", 1000.0, current_time=t, current_light=100.0, current_temp=22.0
        )
        # log10(1000) - log10(100) = 1.0; normalised by /3 => ~0.333
        assert dev == pytest.approx(1.0 / 3.0, abs=0.05)


# ---------------------------------------------------------------------------
# TestPersistence
# ---------------------------------------------------------------------------


class TestPersistence:
    """Test save/load round-trip and accuracy stats."""

    def test_save_load_roundtrip(self, tmp_path):
        """Patterns survive a save/load cycle."""
        path = tmp_path / "patterns.json"
        m = AdaptivePredictionModel(persistence_path=path)
        t = datetime(2025, 1, 6, 14, 5)
        for _ in range(5):
            m.observe({"temp": 22.0}, current_time=t, current_light=50.0, current_temp=22.0)
        m._save_patterns()

        m2 = AdaptivePredictionModel(persistence_path=path)
        assert "temp" in m2._patterns
        # Find the pattern with 5 samples
        found = False
        for key, pat in m2._patterns["temp"].items():
            if pat.sample_count == 5:
                assert pat.mean == pytest.approx(22.0, abs=0.1)
                found = True
        assert found, "Expected to find a pattern with sample_count=5"

    def test_missing_file_gives_empty_patterns(self, tmp_path):
        """Loading from a missing file should not crash and yields empty patterns."""
        path = tmp_path / "nonexistent" / "patterns.json"
        m = AdaptivePredictionModel(persistence_path=path)
        assert len(m._patterns) == 0

    def test_accuracy_stats_no_errors(self, tmp_path):
        """With no recorded errors, get_accuracy_stats returns insufficient_data."""
        m = AdaptivePredictionModel(persistence_path=tmp_path / "p.json")
        stats = m.get_accuracy_stats()
        assert stats.get("insufficient_data") is True

    def test_accuracy_stats_after_recording_errors(self, tmp_path):
        """After recording errors, get_accuracy_stats returns correct means."""
        m = AdaptivePredictionModel(persistence_path=tmp_path / "p.json")
        m.record_prediction_error("temp", predicted=20.0, actual=22.0)
        m.record_prediction_error("temp", predicted=21.0, actual=22.0)
        m.record_prediction_error("humidity", predicted=50.0, actual=55.0)

        stats = m.get_accuracy_stats()
        assert stats.get("insufficient_data") is not True
        assert stats["total_errors"] == 3
        # temp errors: |20-22|=2, |21-22|=1 => mean 1.5
        assert stats["temp_mean_error"] == pytest.approx(1.5)
        assert stats["temp_sample_count"] == 2
        # humidity errors: |50-55|=5 => mean 5.0
        assert stats["humidity_mean_error"] == pytest.approx(5.0)
        assert stats["humidity_sample_count"] == 1
        # overall mean: (2+1+5)/3 = 2.666...
        assert stats["overall_mean_error"] == pytest.approx(8.0 / 3.0)
