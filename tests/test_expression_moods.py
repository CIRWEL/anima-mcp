"""
Tests for expression moods module.

Validates drawing style learning, mood evolution, and serialization.
"""

import pytest

from anima_mcp.expression_moods import ExpressionMood, ExpressionMoodTracker


class TestExpressionMood:
    """Test the ExpressionMood dataclass and its learning."""

    def test_defaults(self):
        """Test default mood has equal style preferences."""
        mood = ExpressionMood()
        assert mood.mood_name == "exploring"
        assert mood.total_drawings == 0
        for v in mood.style_preferences.values():
            assert v == 0.2

    def test_record_drawing_increments_count(self):
        """Test that recording a drawing increments total."""
        mood = ExpressionMood()
        mood.record_drawing("circle")
        assert mood.total_drawings == 1
        mood.record_drawing("spiral")
        assert mood.total_drawings == 2

    def test_record_drawing_increases_relative_preference(self):
        """Test that recording a style makes it relatively preferred."""
        mood = ExpressionMood()
        # Record circle many times to build up its preference
        for _ in range(10):
            mood.record_drawing("circle")
        # Circle should be the most preferred style
        circle_weight = mood.style_preferences["circle"]
        other_weights = [v for k, v in mood.style_preferences.items() if k != "circle"]
        assert circle_weight > max(other_weights)

    def test_preferences_normalize_to_one(self):
        """Test that style preferences normalize after update."""
        mood = ExpressionMood()
        # Record many of one style to trigger normalization
        for _ in range(20):
            mood.record_drawing("spiral")
        total = sum(mood.style_preferences.values())
        assert total == pytest.approx(1.0, abs=0.01)

    def test_dominant_style_changes_mood_name(self):
        """Test that dominant style updates the mood name."""
        mood = ExpressionMood()
        # Record enough spirals to become dominant
        for _ in range(30):
            mood.record_drawing("spiral")
        assert mood.mood_name == "flowing"  # spiral → "flowing"

    def test_hue_preference_added(self):
        """Test that new hue categories are added to preferences."""
        mood = ExpressionMood()
        mood.record_drawing("circle", hue_category="neon")
        assert "neon" in mood.preferred_hues

    def test_hue_preference_max_three(self):
        """Test that hue preferences cap at 3."""
        mood = ExpressionMood()
        mood.preferred_hues = []
        for hue in ["red", "blue", "green", "purple"]:
            mood.record_drawing("circle", hue_category=hue)
        assert len(mood.preferred_hues) <= 3

    def test_existing_hue_not_duplicated(self):
        """Test that existing hue doesn't get re-added."""
        mood = ExpressionMood()
        initial_len = len(mood.preferred_hues)
        mood.record_drawing("circle", hue_category="warm")
        assert len(mood.preferred_hues) == initial_len

    def test_get_style_weight(self):
        """Test style weight retrieval."""
        mood = ExpressionMood()
        assert mood.get_style_weight("circle") == 0.2
        assert mood.get_style_weight("nonexistent") == 0.2  # Default

    def test_prefers_hue(self):
        """Test hue preference check."""
        mood = ExpressionMood()
        assert mood.prefers_hue("warm") is True
        assert mood.prefers_hue("nonexistent") is False

    def test_last_updated_set(self):
        """Test that last_updated is set after recording."""
        mood = ExpressionMood()
        assert mood.last_updated is None
        mood.record_drawing("line")
        assert mood.last_updated is not None


class TestSerialization:
    """Test to_dict / from_dict round-trip."""

    def test_round_trip(self):
        """Test that serialization preserves data."""
        mood = ExpressionMood()
        mood.record_drawing("spiral")
        mood.record_drawing("spiral")

        data = mood.to_dict()
        restored = ExpressionMood.from_dict(data)

        assert restored.total_drawings == 2
        assert restored.style_preferences == mood.style_preferences
        assert restored.mood_name == mood.mood_name
        assert restored.preferred_hues == mood.preferred_hues

    def test_from_dict_handles_missing_fields(self):
        """Test that from_dict fills in defaults for missing fields."""
        restored = ExpressionMood.from_dict({})
        assert restored.mood_name == "exploring"
        assert restored.total_drawings == 0
        assert len(restored.style_preferences) == 8


class TestMoodTracker:
    """Test ExpressionMoodTracker (without identity store)."""

    def test_tracker_creates_default_mood(self):
        """Test tracker starts with default mood when no store."""
        tracker = ExpressionMoodTracker(identity_store=None)
        mood = tracker.get_mood()
        assert isinstance(mood, ExpressionMood)
        assert mood.total_drawings == 0

    def test_tracker_record_drawing(self):
        """Test tracker delegates to mood."""
        tracker = ExpressionMoodTracker(identity_store=None)
        tracker.record_drawing("circle", hue_category="warm")
        assert tracker.get_mood().total_drawings == 1

    def test_tracker_get_style_weights(self):
        """Test style weights dictionary."""
        tracker = ExpressionMoodTracker(identity_store=None)
        weights = tracker.get_style_weights()
        assert isinstance(weights, dict)
        assert "circle" in weights

    def test_tracker_get_mood_info(self):
        """Test mood info dictionary."""
        tracker = ExpressionMoodTracker(identity_store=None)
        info = tracker.get_mood_info()
        assert "mood_name" in info
        assert "total_drawings" in info
        assert "style_preferences" in info
