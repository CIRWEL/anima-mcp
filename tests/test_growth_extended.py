"""Extended tests for growth.py dataclasses and pure functions."""

import pytest
from datetime import datetime

from anima_mcp.growth import (
    VisitorFrequency,
    Goal,
    GoalStatus,
    MemorableEvent,
    Preference,
    PreferenceCategory,
)


# ---------------------------------------------------------------------------
# VisitorFrequency.from_legacy
# ---------------------------------------------------------------------------

class TestVisitorFrequencyFromLegacy:
    def test_stranger_maps_to_new(self):
        assert VisitorFrequency.from_legacy("stranger") == VisitorFrequency.NEW

    def test_acquaintance_maps_to_returning(self):
        assert VisitorFrequency.from_legacy("acquaintance") == VisitorFrequency.RETURNING

    def test_familiar_maps_to_regular(self):
        assert VisitorFrequency.from_legacy("familiar") == VisitorFrequency.REGULAR

    def test_close_maps_to_frequent(self):
        assert VisitorFrequency.from_legacy("close") == VisitorFrequency.FREQUENT

    def test_cherished_maps_to_frequent(self):
        assert VisitorFrequency.from_legacy("cherished") == VisitorFrequency.FREQUENT

    def test_unknown_maps_to_new(self):
        assert VisitorFrequency.from_legacy("xyz_garbage") == VisitorFrequency.NEW

    def test_empty_string_maps_to_new(self):
        assert VisitorFrequency.from_legacy("") == VisitorFrequency.NEW


# ---------------------------------------------------------------------------
# Goal.to_dict
# ---------------------------------------------------------------------------

class TestGoalToDict:
    @pytest.fixture
    def goal_no_dates(self):
        return Goal(
            goal_id="test-1",
            description="Test goal",
            motivation="Testing",
            status=GoalStatus.ACTIVE,
            created_at=datetime(2026, 2, 1, 12, 0, 0),
            target_date=None,
            progress=0.5,
            milestones=["step1"],
            last_worked_on=None,
        )

    @pytest.fixture
    def goal_with_dates(self):
        return Goal(
            goal_id="test-2",
            description="Dated goal",
            motivation="Deadlines",
            status=GoalStatus.ACHIEVED,
            created_at=datetime(2026, 2, 1, 12, 0, 0),
            target_date=datetime(2026, 3, 1, 12, 0, 0),
            progress=1.0,
            milestones=["step1", "step2"],
            last_worked_on=datetime(2026, 2, 15, 8, 0, 0),
        )

    def test_all_keys_present(self, goal_no_dates):
        d = goal_no_dates.to_dict()
        expected_keys = {
            "goal_id", "description", "motivation", "status",
            "created_at", "target_date", "progress", "milestones",
            "last_worked_on",
        }
        assert expected_keys == set(d.keys())

    def test_target_date_none(self, goal_no_dates):
        d = goal_no_dates.to_dict()
        assert d["target_date"] is None
        assert d["last_worked_on"] is None

    def test_target_date_set(self, goal_with_dates):
        d = goal_with_dates.to_dict()
        assert d["target_date"] is not None
        # Should be ISO format string
        datetime.fromisoformat(d["target_date"])

    def test_status_is_string(self, goal_no_dates):
        d = goal_no_dates.to_dict()
        assert d["status"] == "active"

    def test_created_at_is_isoformat(self, goal_no_dates):
        d = goal_no_dates.to_dict()
        datetime.fromisoformat(d["created_at"])

    def test_milestones_preserved(self, goal_no_dates):
        d = goal_no_dates.to_dict()
        assert d["milestones"] == ["step1"]

    def test_progress_value(self, goal_no_dates):
        d = goal_no_dates.to_dict()
        assert d["progress"] == 0.5

    def test_last_worked_on_set(self, goal_with_dates):
        d = goal_with_dates.to_dict()
        assert d["last_worked_on"] is not None
        datetime.fromisoformat(d["last_worked_on"])


# ---------------------------------------------------------------------------
# MemorableEvent.to_dict
# ---------------------------------------------------------------------------

class TestMemorableEventToDict:
    @pytest.fixture
    def event(self):
        return MemorableEvent(
            event_id="ev-1",
            timestamp=datetime(2026, 2, 10, 15, 30, 0),
            description="Something happened",
            emotional_impact=0.7,
            category="milestone",
            related_agents=["agent1"],
            lessons_learned=["learned something"],
        )

    def test_all_keys_present(self, event):
        d = event.to_dict()
        expected_keys = {
            "event_id", "timestamp", "description",
            "emotional_impact", "category", "related_agents",
            "lessons_learned",
        }
        assert expected_keys == set(d.keys())

    def test_timestamp_is_isoformat(self, event):
        d = event.to_dict()
        datetime.fromisoformat(d["timestamp"])

    def test_values_match(self, event):
        d = event.to_dict()
        assert d["event_id"] == "ev-1"
        assert d["description"] == "Something happened"
        assert d["emotional_impact"] == 0.7
        assert d["category"] == "milestone"
        assert d["related_agents"] == ["agent1"]
        assert d["lessons_learned"] == ["learned something"]


# ---------------------------------------------------------------------------
# Preference.to_dict
# ---------------------------------------------------------------------------

class TestPreferenceToDict:
    @pytest.fixture
    def pref(self):
        return Preference(
            category=PreferenceCategory.ENVIRONMENT,
            name="dim_light",
            description="I feel calmer when it's dim",
            value=0.8,
            confidence=0.6,
            observation_count=42,
            first_noticed=datetime(2026, 1, 15, 10, 0, 0),
            last_confirmed=datetime(2026, 2, 20, 18, 30, 0),
        )

    def test_all_keys_present(self, pref):
        d = pref.to_dict()
        expected_keys = {
            "category", "name", "description", "value",
            "confidence", "observation_count",
            "first_noticed", "last_confirmed",
        }
        assert expected_keys == set(d.keys())

    def test_category_is_string(self, pref):
        d = pref.to_dict()
        assert d["category"] == "environment"

    def test_datetime_fields_are_isoformat(self, pref):
        d = pref.to_dict()
        datetime.fromisoformat(d["first_noticed"])
        datetime.fromisoformat(d["last_confirmed"])

    def test_values_match(self, pref):
        d = pref.to_dict()
        assert d["name"] == "dim_light"
        assert d["description"] == "I feel calmer when it's dim"
        assert d["value"] == 0.8
        assert d["confidence"] == 0.6
        assert d["observation_count"] == 42
