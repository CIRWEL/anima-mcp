"""Tests for memory module — AssociativeMemory, bucket logic, anticipation."""

import pytest

from anima_mcp.memory import (
    AssociativeMemory, StateOutcome, Anticipation,
)


@pytest.fixture
def memory():
    """AssociativeMemory without any DB loading."""
    return AssociativeMemory(db_path=":memory:")


def _populated_memory(bucket_key=("comfortable", "dim", "moderate"), count=20,
                      warmth=0.7, clarity=0.6, stability=0.8, presence=0.5):
    """Create memory with a known bucket pre-populated."""
    m = AssociativeMemory(db_path=":memory:")
    outcome = StateOutcome()
    for _ in range(count):
        outcome.add(warmth, clarity, stability, presence)
    m._patterns_no_time[bucket_key] = outcome
    return m


# ==================== StateOutcome ====================

class TestStateOutcome:
    def test_empty_returns_neutral(self):
        o = StateOutcome()
        assert o.count == 0
        assert o.avg_warmth == 0.5  # default when empty
        assert o.avg_clarity == 0.5

    def test_single_observation(self):
        o = StateOutcome()
        o.add(0.8, 0.6, 0.7, 0.9)
        assert o.count == 1
        assert o.avg_warmth == pytest.approx(0.8)
        assert o.avg_clarity == pytest.approx(0.6)

    def test_multiple_observations_averaged(self):
        o = StateOutcome()
        o.add(1.0, 0.0, 1.0, 0.0)
        o.add(0.0, 1.0, 0.0, 1.0)
        assert o.count == 2
        assert o.avg_warmth == pytest.approx(0.5)
        assert o.avg_clarity == pytest.approx(0.5)
        assert o.avg_stability == pytest.approx(0.5)
        assert o.avg_presence == pytest.approx(0.5)


# ==================== Bucket Keys ====================

class TestBucketKeys:
    def test_comfortable_temp(self, memory):
        key = memory._get_bucket_key(24.0, 50.0, 45.0)
        assert key is not None
        assert key[0] == "comfortable"

    def test_cold_temp(self, memory):
        key = memory._get_bucket_key(10.0, 50.0, 45.0)
        assert key is not None
        assert key[0] == "cold"

    def test_hot_temp(self, memory):
        key = memory._get_bucket_key(35.0, 50.0, 45.0)
        assert key is not None
        assert key[0] == "hot"

    def test_dark_light(self, memory):
        key = memory._get_bucket_key(22.0, 5.0, 45.0)
        assert key[1] == "dark"

    def test_dim_light(self, memory):
        key = memory._get_bucket_key(22.0, 50.0, 45.0)
        assert key[1] == "dim"

    def test_bright_light(self, memory):
        key = memory._get_bucket_key(22.0, 1000.0, 45.0)
        assert key[1] == "bright"

    def test_very_bright_light(self, memory):
        key = memory._get_bucket_key(22.0, 5000.0, 45.0)
        assert key[1] == "very bright"

    def test_dry_humidity(self, memory):
        key = memory._get_bucket_key(22.0, 50.0, 10.0)
        assert key[2] == "dry"

    def test_out_of_range_returns_none(self, memory):
        """Values outside all buckets should return None."""
        key = memory._get_bucket_key(-50.0, 50.0, 45.0)
        assert key is None


# ==================== Time Buckets ====================

class TestTimeBuckets:
    def test_night(self, memory):
        assert memory._get_time_bucket(2) == "night"

    def test_early_morning(self, memory):
        assert memory._get_time_bucket(6) == "early_morning"

    def test_morning(self, memory):
        assert memory._get_time_bucket(9) == "morning"

    def test_midday(self, memory):
        assert memory._get_time_bucket(13) == "midday"

    def test_afternoon(self, memory):
        assert memory._get_time_bucket(15) == "afternoon"

    def test_evening(self, memory):
        assert memory._get_time_bucket(19) == "evening"

    def test_late_night(self, memory):
        assert memory._get_time_bucket(22) == "late_night"


# ==================== Anticipation ====================

class TestAnticipate:
    def test_returns_none_with_no_patterns(self, memory):
        result = memory.anticipate(22.0, 50.0, 45.0, hour=10)
        assert result is None

    def test_returns_anticipation_with_data(self):
        m = _populated_memory(count=20)
        result = m.anticipate(24.0, 50.0, 45.0, hour=10)
        assert result is not None
        assert isinstance(result, Anticipation)
        assert result.warmth == pytest.approx(0.7)
        assert result.clarity == pytest.approx(0.6)

    def test_insufficient_samples_returns_none(self, memory):
        """Less than 5 samples should return None."""
        outcome = StateOutcome()
        for _ in range(3):
            outcome.add(0.5, 0.5, 0.5, 0.5)
        memory._patterns_no_time[("comfortable", "dim", "moderate")] = outcome
        result = memory.anticipate(24.0, 50.0, 45.0, hour=10)
        assert result is None

    def test_exactly_five_samples_returns_result(self):
        m = _populated_memory(count=5)
        result = m.anticipate(24.0, 50.0, 45.0, hour=10)
        assert result is not None

    def test_confidence_increases_with_samples(self):
        m_low = _populated_memory(count=10)
        m_high = _populated_memory(count=80)
        r_low = m_low.anticipate(24.0, 50.0, 45.0, hour=10)
        r_high = m_high.anticipate(24.0, 50.0, 45.0, hour=10)
        assert r_low is not None and r_high is not None
        assert r_high.confidence > r_low.confidence

    def test_confidence_caps_at_one(self):
        m = _populated_memory(count=200)
        result = m.anticipate(24.0, 50.0, 45.0, hour=10)
        assert result.confidence <= 1.0

    def test_no_matching_bucket(self, memory):
        """Conditions that don't match any populated bucket → None."""
        outcome = StateOutcome()
        for _ in range(20):
            outcome.add(0.5, 0.5, 0.5, 0.5)
        memory._patterns_no_time[("cold", "dark", "dry")] = outcome
        # Query for different conditions
        result = memory.anticipate(24.0, 50.0, 45.0, hour=10)  # comfortable, dim, moderate
        assert result is None


class TestAnticipateFromSensors:
    def test_with_valid_sensors(self):
        m = _populated_memory()
        result = m.anticipate_from_sensors({
            "ambient_temp_c": 24.0,
            "light_lux": 50.0,
            "humidity_pct": 45.0,
        })
        assert result is not None

    def test_missing_temp_returns_none(self, memory):
        result = memory.anticipate_from_sensors({"light_lux": 50.0})
        assert result is None

    def test_falls_back_to_cpu_temp(self):
        m = _populated_memory()
        result = m.anticipate_from_sensors({
            "cpu_temp_c": 24.0,  # No ambient_temp_c
            "light_lux": 50.0,
            "humidity_pct": 45.0,
        })
        assert result is not None


class TestAnticipationBlend:
    def test_blend_with_current_state(self):
        a = Anticipation(warmth=0.8, clarity=0.6, stability=0.7, presence=0.5,
                        confidence=1.0, sample_count=100, bucket_description="test")
        blended = a.blend_with(0.5, 0.5, 0.5, 0.5, blend_factor=0.5)
        # With confidence=1.0 and blend=0.5, result should be midpoint
        assert blended[0] == pytest.approx(0.65)  # (0.5 * 0.5) + (0.8 * 0.5)
        assert all(0.0 <= v <= 1.0 for v in blended)

    def test_zero_confidence_keeps_current(self):
        a = Anticipation(warmth=1.0, clarity=1.0, stability=1.0, presence=1.0,
                        confidence=0.0, sample_count=1, bucket_description="test")
        blended = a.blend_with(0.5, 0.5, 0.5, 0.5, blend_factor=0.5)
        # Zero confidence means effective_blend=0, so current state unchanged
        assert blended[0] == pytest.approx(0.5)


class TestLoadPatterns:
    def test_empty_db_returns_false(self, tmp_path):
        """No state_history table → graceful failure."""
        m = AssociativeMemory(db_path=str(tmp_path / "empty.db"))
        result = m.load_patterns()
        assert result is False

    def test_nonexistent_db_returns_false(self):
        m = AssociativeMemory(db_path="/nonexistent/path.db")
        result = m.load_patterns()
        assert result is False
