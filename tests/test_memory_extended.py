"""Extended tests for AssociativeMemory - pure logic, no DB loading."""

import pytest

from anima_mcp.memory import (
    AssociativeMemory,
    Anticipation,
    ConditionBucket,
    ExplorationOutcome,
    ExplorationMode,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mem():
    """AssociativeMemory with in-memory DB (no data loaded)."""
    return AssociativeMemory(db_path=":memory:")


@pytest.fixture
def mem_with_anticipation(mem):
    """Memory with a pre-set last anticipation."""
    mem._last_anticipation = Anticipation(
        warmth=0.5,
        clarity=0.5,
        stability=0.5,
        presence=0.5,
        confidence=0.8,
        sample_count=50,
        bucket_description="test conditions",
    )
    return mem


# ---------------------------------------------------------------------------
# ExplorationOutcome dataclass
# ---------------------------------------------------------------------------

class TestExplorationOutcome:
    def test_instantiation(self):
        outcome = ExplorationOutcome(
            exploration_delta=(0.1, -0.1, 0.05, -0.05),
            result_novelty=0.3,
            emotional_valence=0.2,
        )
        assert outcome.exploration_delta == (0.1, -0.1, 0.05, -0.05)
        assert outcome.result_novelty == 0.3
        assert outcome.emotional_valence == 0.2
        assert isinstance(outcome.timestamp, float)
        assert outcome.timestamp > 0


# ---------------------------------------------------------------------------
# ConditionBucket
# ---------------------------------------------------------------------------

class TestConditionBucket:
    def test_matches_within_bounds(self):
        bucket = ConditionBucket(
            temp_range=(18.0, 26.0),
            light_range=(100.0, 500.0),
            humidity_range=(30.0, 60.0),
        )
        assert bucket.matches(22.0, 300.0, 45.0) is True

    def test_no_match_outside_temp(self):
        bucket = ConditionBucket(
            temp_range=(18.0, 26.0),
            light_range=(100.0, 500.0),
            humidity_range=(30.0, 60.0),
        )
        assert bucket.matches(30.0, 300.0, 45.0) is False

    def test_no_match_outside_light(self):
        bucket = ConditionBucket(
            temp_range=(18.0, 26.0),
            light_range=(100.0, 500.0),
            humidity_range=(30.0, 60.0),
        )
        assert bucket.matches(22.0, 50.0, 45.0) is False

    def test_no_match_outside_humidity(self):
        bucket = ConditionBucket(
            temp_range=(18.0, 26.0),
            light_range=(100.0, 500.0),
            humidity_range=(30.0, 60.0),
        )
        assert bucket.matches(22.0, 300.0, 80.0) is False

    def test_boundary_values_match(self):
        bucket = ConditionBucket(
            temp_range=(18.0, 26.0),
            light_range=(100.0, 500.0),
            humidity_range=(30.0, 60.0),
        )
        assert bucket.matches(18.0, 100.0, 30.0) is True
        assert bucket.matches(26.0, 500.0, 60.0) is True

    def test_hashable(self):
        bucket = ConditionBucket(
            temp_range=(18.0, 26.0),
            light_range=(100.0, 500.0),
            humidity_range=(30.0, 60.0),
        )
        assert isinstance(hash(bucket), int)

    def test_same_inputs_same_hash(self):
        a = ConditionBucket(
            temp_range=(18.0, 26.0),
            light_range=(100.0, 500.0),
            humidity_range=(30.0, 60.0),
        )
        b = ConditionBucket(
            temp_range=(18.0, 26.0),
            light_range=(100.0, 500.0),
            humidity_range=(30.0, 60.0),
        )
        assert hash(a) == hash(b)

    def test_usable_as_dict_key(self):
        bucket = ConditionBucket(
            temp_range=(18.0, 26.0),
            light_range=(100.0, 500.0),
            humidity_range=(30.0, 60.0),
        )
        d = {bucket: "value"}
        assert d[bucket] == "value"


# ---------------------------------------------------------------------------
# get_memory_insight
# ---------------------------------------------------------------------------

class TestGetMemoryInsight:
    def test_no_anticipation(self, mem):
        assert "no clear memories" in mem.get_memory_insight()

    def test_high_warmth_and_clarity(self, mem):
        mem._last_anticipation = Anticipation(
            warmth=0.7, clarity=0.7, stability=0.5, presence=0.5,
            confidence=0.6, sample_count=20, bucket_description="warm bright moderate",
        )
        insight = mem.get_memory_insight()
        assert "good and clear" in insight

    def test_low_warmth_and_clarity(self, mem):
        mem._last_anticipation = Anticipation(
            warmth=0.3, clarity=0.3, stability=0.5, presence=0.5,
            confidence=0.6, sample_count=20, bucket_description="cold dark moderate",
        )
        insight = mem.get_memory_insight()
        assert "cold and foggy" in insight

    def test_warm_only(self, mem):
        mem._last_anticipation = Anticipation(
            warmth=0.7, clarity=0.5, stability=0.5, presence=0.5,
            confidence=0.6, sample_count=20, bucket_description="warm moderate moderate",
        )
        assert "warm" in mem.get_memory_insight()

    def test_cold_only(self, mem):
        mem._last_anticipation = Anticipation(
            warmth=0.3, clarity=0.5, stability=0.5, presence=0.5,
            confidence=0.6, sample_count=20, bucket_description="cold moderate moderate",
        )
        assert "cold" in mem.get_memory_insight()

    def test_clear_only(self, mem):
        mem._last_anticipation = Anticipation(
            warmth=0.5, clarity=0.7, stability=0.5, presence=0.5,
            confidence=0.6, sample_count=20, bucket_description="comfortable bright moderate",
        )
        assert "clear" in mem.get_memory_insight()

    def test_unclear_only(self, mem):
        mem._last_anticipation = Anticipation(
            warmth=0.5, clarity=0.3, stability=0.5, presence=0.5,
            confidence=0.6, sample_count=20, bucket_description="comfortable dim moderate",
        )
        assert "unclear" in mem.get_memory_insight()

    def test_balanced(self, mem):
        mem._last_anticipation = Anticipation(
            warmth=0.5, clarity=0.5, stability=0.5, presence=0.5,
            confidence=0.6, sample_count=20, bucket_description="comfortable moderate moderate",
        )
        assert "balanced" in mem.get_memory_insight()

    def test_high_confidence_says_often(self, mem):
        mem._last_anticipation = Anticipation(
            warmth=0.7, clarity=0.7, stability=0.5, presence=0.5,
            confidence=0.8, sample_count=80, bucket_description="warm bright moderate",
        )
        assert "often" in mem.get_memory_insight()

    def test_low_confidence_says_sometimes(self, mem):
        mem._last_anticipation = Anticipation(
            warmth=0.7, clarity=0.7, stability=0.5, presence=0.5,
            confidence=0.3, sample_count=10, bucket_description="warm bright moderate",
        )
        assert "sometimes" in mem.get_memory_insight()


# ---------------------------------------------------------------------------
# get_adaptive_blend_factor
# ---------------------------------------------------------------------------

class TestGetAdaptiveBlendFactor:
    def test_returns_float(self, mem):
        result = mem.get_adaptive_blend_factor()
        assert isinstance(result, float)

    def test_default_value(self, mem):
        assert mem.get_adaptive_blend_factor() == 0.15


# ---------------------------------------------------------------------------
# get_accuracy_stats
# ---------------------------------------------------------------------------

class TestGetAccuracyStats:
    def test_no_samples(self, mem):
        stats = mem.get_accuracy_stats()
        assert stats["samples"] == 0
        assert stats["average_accuracy"] is None
        assert "message" in stats

    def test_with_samples(self, mem_with_anticipation):
        # Record an outcome to create accuracy data
        mem_with_anticipation.record_actual_outcome(0.5, 0.5, 0.5, 0.5)
        stats = mem_with_anticipation.get_accuracy_stats()
        assert stats["samples"] == 1
        assert isinstance(stats["average_accuracy"], float)
        assert stats["average_accuracy"] > 0


# ---------------------------------------------------------------------------
# should_explore
# ---------------------------------------------------------------------------

class TestShouldExplore:
    def test_rate_one_always_true(self, mem):
        mem._exploration_rate = 1.0
        # With rate=1.0, random.random() < 1.0 is always True
        results = [mem.should_explore() for _ in range(20)]
        assert all(results)

    def test_rate_zero_always_false(self, mem):
        mem._exploration_rate = 0.0
        results = [mem.should_explore() for _ in range(20)]
        assert not any(results)


# ---------------------------------------------------------------------------
# trigger_curiosity_mode
# ---------------------------------------------------------------------------

class TestTriggerCuriosityMode:
    def test_changes_mode_to_curious(self, mem):
        assert mem._current_mode == ExplorationMode.EXPLOIT
        mem.trigger_curiosity_mode()
        assert mem._current_mode == ExplorationMode.CURIOUS

    def test_sets_exploration_rate_to_max(self, mem):
        mem.trigger_curiosity_mode()
        assert mem._exploration_rate == mem._exploration_rate_max

    def test_sets_exploring_since(self, mem):
        assert mem._exploring_since is None
        mem.trigger_curiosity_mode()
        assert mem._exploring_since is not None


# ---------------------------------------------------------------------------
# set_exploration_rate
# ---------------------------------------------------------------------------

class TestSetExplorationRate:
    def test_set_rate(self, mem):
        mem.set_exploration_rate(0.10)
        assert mem._exploration_rate == 0.10

    def test_clamped_at_min(self, mem):
        mem.set_exploration_rate(0.0)
        assert mem._exploration_rate == mem._exploration_rate_min

    def test_clamped_at_max(self, mem):
        mem.set_exploration_rate(1.0)
        assert mem._exploration_rate == mem._exploration_rate_max


# ---------------------------------------------------------------------------
# record_actual_outcome
# ---------------------------------------------------------------------------

class TestRecordActualOutcome:
    def test_no_anticipation_returns_none(self, mem):
        assert mem.record_actual_outcome(0.5, 0.5, 0.5, 0.5) is None

    def test_with_anticipation_returns_accuracy_dict(self, mem_with_anticipation):
        result = mem_with_anticipation.record_actual_outcome(0.5, 0.5, 0.5, 0.5)
        assert result is not None
        assert "accuracy" in result
        assert "anticipated" in result
        assert "actual" in result
        assert "error" in result
        assert "confidence" in result
        assert "adaptive_blend" in result

    def test_perfect_prediction(self, mem_with_anticipation):
        # Anticipation is (0.5, 0.5, 0.5, 0.5), actual same -> perfect
        result = mem_with_anticipation.record_actual_outcome(0.5, 0.5, 0.5, 0.5)
        assert result["accuracy"] == 1.0
        assert result["error"]["average"] == 0.0

    def test_imperfect_prediction(self, mem_with_anticipation):
        result = mem_with_anticipation.record_actual_outcome(0.8, 0.2, 0.9, 0.1)
        assert result["accuracy"] < 1.0
        assert result["error"]["average"] > 0.0

    def test_increments_accuracy_samples(self, mem_with_anticipation):
        assert mem_with_anticipation._accuracy_samples == 0
        mem_with_anticipation.record_actual_outcome(0.5, 0.5, 0.5, 0.5)
        assert mem_with_anticipation._accuracy_samples == 1
