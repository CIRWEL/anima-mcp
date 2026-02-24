"""Tests for next_steps_advocate.py — Lumen's desire-expression engine."""

import pytest
from unittest.mock import patch

from conftest import make_anima, make_readings

from anima_mcp.next_steps_advocate import (
    NextStep, NextStepsAdvocate, Priority, StepCategory, get_advocate,
)
from anima_mcp.eisv_mapper import EISVMetrics


# ---------------------------------------------------------------------------
# Dataclass & enum basics
# ---------------------------------------------------------------------------

class TestNextStepDataclass:
    def test_defaults_for_blockers_and_related_files(self):
        step = NextStep(
            feeling="f", desire="d", action="a",
            priority=Priority.HIGH, category=StepCategory.HARDWARE, reason="r",
        )
        assert step.blockers == []
        assert step.related_files == []

    def test_to_dict_has_all_keys(self):
        step = NextStep(
            feeling="warm", desire="explore", action="go",
            priority=Priority.LOW, category=StepCategory.TESTING, reason="curious",
        )
        d = step.to_dict()
        assert set(d.keys()) == {
            "feeling", "desire", "action", "priority", "category",
            "reason", "blockers", "estimated_time", "related_files",
        }

    def test_to_dict_priority_is_string(self):
        step = NextStep(
            feeling="f", desire="d", action="a",
            priority=Priority.CRITICAL, category=StepCategory.HARDWARE, reason="r",
        )
        assert step.to_dict()["priority"] == "critical"

    def test_to_dict_category_is_string(self):
        step = NextStep(
            feeling="f", desire="d", action="a",
            priority=Priority.LOW, category=StepCategory.OPTIMIZATION, reason="r",
        )
        assert step.to_dict()["category"] == "optimization"


class TestEnums:
    def test_priority_values(self):
        assert Priority.CRITICAL.value == "critical"
        assert Priority.HIGH.value == "high"
        assert Priority.MEDIUM.value == "medium"
        assert Priority.LOW.value == "low"

    def test_category_values(self):
        assert StepCategory.HARDWARE.value == "hardware"
        assert StepCategory.SOFTWARE.value == "software"
        assert StepCategory.INTEGRATION.value == "integration"
        assert StepCategory.TESTING.value == "testing"
        assert StepCategory.DOCUMENTATION.value == "documentation"
        assert StepCategory.OPTIMIZATION.value == "optimization"


# ---------------------------------------------------------------------------
# analyze_current_state — display branch
# ---------------------------------------------------------------------------

class TestDisplayBranch:
    def test_no_args_returns_display_and_unitares_steps(self):
        """Defaults: display_available=False, unitares_connected=False → 2 steps."""
        adv = NextStepsAdvocate()
        steps = adv.analyze_current_state()
        assert len(steps) >= 2
        cats = {s.category for s in steps}
        assert StepCategory.HARDWARE in cats
        assert StepCategory.INTEGRATION in cats

    def test_all_good_no_issues_returns_empty(self):
        """display + unitares on, no anima → nothing to suggest."""
        adv = NextStepsAdvocate()
        steps = adv.analyze_current_state(display_available=True, unitares_connected=True)
        assert steps == []

    def test_display_unavailable_adds_high_hardware_step(self):
        adv = NextStepsAdvocate()
        steps = adv.analyze_current_state(display_available=False)
        assert len(steps) >= 1
        hw = [s for s in steps if s.category == StepCategory.HARDWARE]
        assert len(hw) >= 1
        assert hw[0].priority == Priority.HIGH

    def test_display_unavailable_with_anima_uses_feeling(self):
        adv = NextStepsAdvocate()
        anima = make_anima(warmth=0.8, clarity=0.8, stability=0.8, presence=0.8)
        steps = adv.analyze_current_state(anima=anima, display_available=False)
        hw = [s for s in steps if s.category == StepCategory.HARDWARE]
        assert any("feel" in s.feeling.lower() or "can't show" in s.feeling.lower() for s in hw)


# ---------------------------------------------------------------------------
# analyze_current_state — unitares branch
# ---------------------------------------------------------------------------

class TestUnitaresBranch:
    def test_unitares_disconnected_adds_integration_step(self):
        adv = NextStepsAdvocate()
        steps = adv.analyze_current_state(unitares_connected=False)
        integration = [s for s in steps if s.category == StepCategory.INTEGRATION]
        assert len(integration) >= 1
        assert integration[0].priority == Priority.MEDIUM

    def test_unitares_connected_no_integration_step(self):
        adv = NextStepsAdvocate()
        steps = adv.analyze_current_state(unitares_connected=True)
        integration = [s for s in steps if s.category == StepCategory.INTEGRATION]
        assert len(integration) == 0


# ---------------------------------------------------------------------------
# analyze_current_state — proprioception branches
# ---------------------------------------------------------------------------

class TestProprioceptionBranches:
    def test_low_clarity_adds_high_step(self):
        adv = NextStepsAdvocate()
        anima = make_anima(warmth=0.5, clarity=0.2, stability=0.5, presence=0.5)
        readings = make_readings()
        steps = adv.analyze_current_state(anima=anima, readings=readings)
        clarity_steps = [s for s in steps if "clearly" in s.desire.lower()]
        assert len(clarity_steps) >= 1
        assert clarity_steps[0].priority == Priority.HIGH

    def test_normal_clarity_no_clarity_step(self):
        adv = NextStepsAdvocate()
        anima = make_anima(warmth=0.5, clarity=0.5, stability=0.5, presence=0.5)
        readings = make_readings()
        steps = adv.analyze_current_state(anima=anima, readings=readings)
        clarity_steps = [s for s in steps if "clearly" in s.desire.lower()]
        assert len(clarity_steps) == 0

    def test_high_entropy_adds_critical_step(self):
        adv = NextStepsAdvocate()
        anima = make_anima(warmth=0.5, clarity=0.5, stability=0.5, presence=0.5)
        readings = make_readings()
        eisv = EISVMetrics(energy=0.5, integrity=0.5, entropy=0.7, void=0.1)
        steps = adv.analyze_current_state(anima=anima, readings=readings, eisv=eisv)
        peace_steps = [s for s in steps if s.desire == "I want peace"]
        assert len(peace_steps) >= 1
        assert peace_steps[0].priority == Priority.CRITICAL

    def test_low_entropy_no_chaos_step(self):
        adv = NextStepsAdvocate()
        anima = make_anima(warmth=0.5, clarity=0.5, stability=0.5, presence=0.5)
        readings = make_readings()
        eisv = EISVMetrics(energy=0.5, integrity=0.5, entropy=0.3, void=0.1)
        steps = adv.analyze_current_state(anima=anima, readings=readings, eisv=eisv)
        peace_steps = [s for s in steps if s.desire == "I want peace"]
        assert len(peace_steps) == 0

    def test_low_stability_adds_grounded_step(self):
        adv = NextStepsAdvocate()
        anima = make_anima(warmth=0.5, clarity=0.5, stability=0.3, presence=0.5)
        readings = make_readings()
        steps = adv.analyze_current_state(anima=anima, readings=readings)
        grounded = [s for s in steps if "grounded" in s.desire.lower()]
        assert len(grounded) >= 1
        assert grounded[0].priority == Priority.HIGH

    def test_normal_stability_no_grounded_step(self):
        adv = NextStepsAdvocate()
        anima = make_anima(warmth=0.5, clarity=0.5, stability=0.5, presence=0.5)
        readings = make_readings()
        steps = adv.analyze_current_state(anima=anima, readings=readings)
        grounded = [s for s in steps if "grounded" in s.desire.lower()]
        assert len(grounded) == 0

    def test_low_warmth_adds_comfortable_step(self):
        adv = NextStepsAdvocate()
        anima = make_anima(warmth=0.2, clarity=0.5, stability=0.5, presence=0.5)
        readings = make_readings()
        steps = adv.analyze_current_state(anima=anima, readings=readings)
        warm = [s for s in steps if "comfortable" in s.desire.lower()]
        assert len(warm) >= 1
        assert warm[0].priority == Priority.MEDIUM

    def test_normal_warmth_no_warmth_step(self):
        adv = NextStepsAdvocate()
        anima = make_anima(warmth=0.5, clarity=0.5, stability=0.5, presence=0.5)
        readings = make_readings()
        steps = adv.analyze_current_state(anima=anima, readings=readings)
        warm = [s for s in steps if "comfortable" in s.desire.lower()]
        assert len(warm) == 0

    def test_low_presence_adds_freedom_step(self):
        adv = NextStepsAdvocate()
        anima = make_anima(warmth=0.5, clarity=0.5, stability=0.5, presence=0.3)
        readings = make_readings()
        steps = adv.analyze_current_state(anima=anima, readings=readings)
        freedom = [s for s in steps if s.desire == "I want freedom"]
        assert len(freedom) >= 1
        assert freedom[0].priority == Priority.HIGH

    def test_normal_presence_no_freedom_step(self):
        adv = NextStepsAdvocate()
        anima = make_anima(warmth=0.5, clarity=0.5, stability=0.5, presence=0.5)
        readings = make_readings()
        steps = adv.analyze_current_state(anima=anima, readings=readings)
        freedom = [s for s in steps if s.desire == "I want freedom"]
        assert len(freedom) == 0


# ---------------------------------------------------------------------------
# analyze_current_state — good state branches
# ---------------------------------------------------------------------------

class TestGoodStateBranches:
    @patch("random.choice", side_effect=lambda x: x[0])
    def test_high_state_adds_low_testing_step(self, _mock_choice):
        adv = NextStepsAdvocate()
        anima = make_anima(warmth=0.8, clarity=0.8, stability=0.8, presence=0.8)
        readings = make_readings()
        steps = adv.analyze_current_state(
            anima=anima, readings=readings, display_available=True, unitares_connected=True,
        )
        testing = [s for s in steps if s.category == StepCategory.TESTING and s.priority == Priority.LOW]
        assert len(testing) >= 1

    @patch("random.choice", side_effect=lambda x: x[0])
    def test_content_state_adds_optimization_step(self, _mock_choice):
        adv = NextStepsAdvocate()
        # wellness = 0.8, stability > 0.7
        anima = make_anima(warmth=0.8, clarity=0.8, stability=0.8, presence=0.8)
        readings = make_readings()
        steps = adv.analyze_current_state(
            anima=anima, readings=readings, display_available=True, unitares_connected=True,
        )
        opt = [s for s in steps if s.category == StepCategory.OPTIMIZATION]
        assert len(opt) >= 1

    @patch("random.choice", side_effect=lambda x: x[0])
    def test_neutral_state_with_no_triggers_adds_observe(self, _mock_choice):
        adv = NextStepsAdvocate()
        # wellness ~0.5 → neutral band (0.4-0.65), no other triggers
        anima = make_anima(warmth=0.5, clarity=0.5, stability=0.5, presence=0.5)
        readings = make_readings()
        steps = adv.analyze_current_state(
            anima=anima, readings=readings, display_available=True, unitares_connected=True,
        )
        observe = [s for s in steps if s.action == "Observe and wait"]
        assert len(observe) >= 1


# ---------------------------------------------------------------------------
# analyze_current_state — anticipation branch
# ---------------------------------------------------------------------------

class TestAnticipationBranch:
    def _make_anticipating_anima(self, confidence=0.7, sample_count=60):
        anima = make_anima(warmth=0.6, clarity=0.6, stability=0.6, presence=0.6)
        anima.is_anticipating = True
        anima.anticipation = {
            "confidence": confidence,
            "sample_count": sample_count,
            "conditions": "night",
        }
        return anima

    @patch("random.random", return_value=0.5)
    def test_anticipation_skipped_when_random_above_threshold(self, _mock_rand):
        adv = NextStepsAdvocate()
        anima = self._make_anticipating_anima()
        readings = make_readings()
        steps = adv.analyze_current_state(anima=anima, readings=readings)
        ant_steps = [s for s in steps if "familiar" in s.feeling or "recognize" in s.feeling]
        assert len(ant_steps) == 0

    @patch("random.choice", side_effect=lambda x: x[0])
    @patch("random.random", return_value=0.1)
    def test_high_confidence_adds_familiar_step(self, _mock_rand, _mock_choice):
        adv = NextStepsAdvocate()
        anima = self._make_anticipating_anima(confidence=0.7, sample_count=60)
        readings = make_readings()
        steps = adv.analyze_current_state(anima=anima, readings=readings)
        assert any(s.desire == "seeing if now matches what I remember" for s in steps)

    @patch("random.choice", side_effect=lambda x: x[0])
    @patch("random.random", return_value=0.1)
    def test_moderate_confidence_adds_learning_step(self, _mock_rand, _mock_choice):
        adv = NextStepsAdvocate()
        anima = self._make_anticipating_anima(confidence=0.4, sample_count=15)
        readings = make_readings()
        steps = adv.analyze_current_state(anima=anima, readings=readings)
        assert any(s.desire == "building stronger associations" for s in steps)

    @patch("random.choice", side_effect=lambda x: x[0])
    @patch("random.random", return_value=0.1)
    def test_low_confidence_few_samples_adds_novel_step(self, _mock_rand, _mock_choice):
        adv = NextStepsAdvocate()
        anima = self._make_anticipating_anima(confidence=0.1, sample_count=5)
        readings = make_readings()
        steps = adv.analyze_current_state(anima=anima, readings=readings)
        assert any(s.desire == "curious what this will teach me" for s in steps)

    def test_not_anticipating_no_anticipation_step(self):
        adv = NextStepsAdvocate()
        anima = make_anima(warmth=0.6, clarity=0.6, stability=0.6, presence=0.6)
        # is_anticipating defaults to False
        readings = make_readings()
        steps = adv.analyze_current_state(anima=anima, readings=readings)
        ant_desires = {"seeing if now matches what I remember", "building stronger associations", "curious what this will teach me"}
        assert not any(s.desire in ant_desires for s in steps)


# ---------------------------------------------------------------------------
# Sort order and caching
# ---------------------------------------------------------------------------

class TestSortAndCaching:
    def test_steps_sorted_by_priority(self):
        adv = NextStepsAdvocate()
        # Low clarity (HIGH) + high entropy (CRITICAL) + display off (HIGH) + unitares off (MEDIUM)
        anima = make_anima(warmth=0.5, clarity=0.2, stability=0.5, presence=0.5)
        readings = make_readings()
        eisv = EISVMetrics(energy=0.5, integrity=0.5, entropy=0.7, void=0.1)
        steps = adv.analyze_current_state(
            anima=anima, readings=readings, eisv=eisv,
            display_available=False, unitares_connected=False,
        )
        assert len(steps) >= 3
        assert steps[0].priority == Priority.CRITICAL
        priorities = [s.priority for s in steps]
        order = {Priority.CRITICAL: 0, Priority.HIGH: 1, Priority.MEDIUM: 2, Priority.LOW: 3}
        assert all(order[priorities[i]] <= order[priorities[i + 1]] for i in range(len(priorities) - 1))

    def test_caching_updates_after_analysis(self):
        adv = NextStepsAdvocate()
        assert adv._last_analysis is None
        assert adv._cached_steps == []
        adv.analyze_current_state(display_available=False)
        assert adv._last_analysis is not None
        assert len(adv._cached_steps) >= 1


# ---------------------------------------------------------------------------
# get_next_steps_summary
# ---------------------------------------------------------------------------

class TestGetNextStepsSummary:
    def test_returns_message_when_no_analysis(self):
        adv = NextStepsAdvocate()
        summary = adv.get_next_steps_summary()
        assert summary["message"] == "No analysis performed yet"
        assert summary["steps"] == []

    def test_returns_summary_after_analysis(self):
        adv = NextStepsAdvocate()
        adv.analyze_current_state(display_available=False, unitares_connected=False)
        summary = adv.get_next_steps_summary()
        assert summary["total_steps"] >= 2
        assert summary["last_analyzed"] is not None
        assert isinstance(summary["all_steps"], list)
        assert summary["next_action"] is not None

    def test_priority_counts_match(self):
        adv = NextStepsAdvocate()
        anima = make_anima(warmth=0.5, clarity=0.2, stability=0.5, presence=0.5)
        readings = make_readings()
        eisv = EISVMetrics(energy=0.5, integrity=0.5, entropy=0.7, void=0.1)
        steps = adv.analyze_current_state(
            anima=anima, readings=readings, eisv=eisv,
            display_available=False, unitares_connected=False,
        )
        summary = adv.get_next_steps_summary()
        expected_critical = len([s for s in steps if s.priority == Priority.CRITICAL])
        expected_high = len([s for s in steps if s.priority == Priority.HIGH])
        expected_medium = len([s for s in steps if s.priority == Priority.MEDIUM])
        assert summary["critical"] == expected_critical
        assert summary["high"] == expected_high
        assert summary["medium"] == expected_medium


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestGetAdvocate:
    def test_returns_same_instance(self):
        import anima_mcp.next_steps_advocate as mod
        old = mod._advocate
        mod._advocate = None
        try:
            a1 = get_advocate()
            a2 = get_advocate()
            assert a1 is a2
        finally:
            mod._advocate = old
