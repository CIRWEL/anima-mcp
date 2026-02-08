"""
Tests for expression moods module.

Validates gesture preference learning, mood evolution, migration, and serialization.
"""

import pytest

from anima_mcp.expression_moods import ExpressionMood, ExpressionMoodTracker


class TestExpressionMood:
    """Test the ExpressionMood dataclass and its learning."""

    def test_defaults(self):
        """Test default mood has equal gesture preferences."""
        mood = ExpressionMood()
        assert mood.mood_name == "exploring"
        assert mood.total_drawings == 0
        assert set(mood.style_preferences.keys()) == {"dot", "stroke", "curve", "cluster", "drag"}
        for v in mood.style_preferences.values():
            assert v == 0.2

    def test_record_drawing_increments_count(self):
        """Test that recording a mark increments total."""
        mood = ExpressionMood()
        mood.record_drawing("dot")
        assert mood.total_drawings == 1
        mood.record_drawing("stroke")
        assert mood.total_drawings == 2

    def test_record_drawing_increases_relative_preference(self):
        """Test that recording a gesture makes it relatively preferred."""
        mood = ExpressionMood()
        for _ in range(10):
            mood.record_drawing("curve")
        curve_weight = mood.style_preferences["curve"]
        other_weights = [v for k, v in mood.style_preferences.items() if k != "curve"]
        assert curve_weight > max(other_weights)

    def test_preferences_normalize_to_one(self):
        """Test that gesture preferences normalize after update."""
        mood = ExpressionMood()
        for _ in range(20):
            mood.record_drawing("drag")
        total = sum(mood.style_preferences.values())
        assert total == pytest.approx(1.0, abs=0.01)

    def test_dominant_gesture_changes_mood_name(self):
        """Test that dominant gesture updates the mood name."""
        mood = ExpressionMood()
        for _ in range(30):
            mood.record_drawing("stroke")
        assert mood.mood_name == "gestural"

    def test_mood_names_mapping(self):
        """Test all gesture → mood name mappings."""
        mappings = {
            "dot": "pointillist",
            "stroke": "gestural",
            "curve": "flowing",
            "cluster": "textural",
            "drag": "bold",
        }
        for gesture, expected_mood in mappings.items():
            mood = ExpressionMood()
            for _ in range(30):
                mood.record_drawing(gesture)
            assert mood.mood_name == expected_mood, f"{gesture} should produce {expected_mood}"

    def test_hue_preference_added(self):
        """Test that new hue categories are added to preferences."""
        mood = ExpressionMood()
        mood.record_drawing("dot", hue_category="neon")
        assert "neon" in mood.preferred_hues

    def test_hue_preference_max_three(self):
        """Test that hue preferences cap at 3."""
        mood = ExpressionMood()
        mood.preferred_hues = []
        for hue in ["red", "blue", "green", "purple"]:
            mood.record_drawing("dot", hue_category=hue)
        assert len(mood.preferred_hues) <= 3

    def test_existing_hue_not_duplicated(self):
        """Test that existing hue doesn't get re-added."""
        mood = ExpressionMood()
        initial_len = len(mood.preferred_hues)
        mood.record_drawing("dot", hue_category="warm")
        assert len(mood.preferred_hues) == initial_len

    def test_get_style_weight(self):
        """Test gesture weight retrieval."""
        mood = ExpressionMood()
        assert mood.get_style_weight("dot") == 0.2
        assert mood.get_style_weight("nonexistent") == 0.2

    def test_prefers_hue(self):
        """Test hue preference check."""
        mood = ExpressionMood()
        assert mood.prefers_hue("warm") is True
        assert mood.prefers_hue("nonexistent") is False

    def test_last_updated_set(self):
        """Test that last_updated is set after recording."""
        mood = ExpressionMood()
        assert mood.last_updated is None
        mood.record_drawing("stroke")
        assert mood.last_updated is not None


class TestSerialization:
    """Test to_dict / from_dict round-trip."""

    def test_round_trip(self):
        """Test that serialization preserves data."""
        mood = ExpressionMood()
        mood.record_drawing("curve")
        mood.record_drawing("curve")

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
        assert len(restored.style_preferences) == 5

    def test_migration_from_old_style_keys(self):
        """Test that old shape keys are migrated to gesture defaults."""
        old_data = {
            "style_preferences": {
                "circle": 0.4, "line": 0.1, "curve": 0.2, "spiral": 0.1,
                "pattern": 0.05, "organic": 0.05, "gradient_circle": 0.05, "layered": 0.05,
            },
            "mood_name": "contemplative",
            "total_drawings": 500,
        }
        restored = ExpressionMood.from_dict(old_data)
        # Should have been reset to gesture defaults
        assert set(restored.style_preferences.keys()) == {"dot", "stroke", "curve", "cluster", "drag"}
        assert restored.mood_name == "exploring"
        # total_drawings preserved
        assert restored.total_drawings == 500


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
        tracker.record_drawing("dot", hue_category="warm")
        assert tracker.get_mood().total_drawings == 1

    def test_tracker_get_style_weights(self):
        """Test style weights dictionary."""
        tracker = ExpressionMoodTracker(identity_store=None)
        weights = tracker.get_style_weights()
        assert isinstance(weights, dict)
        assert "dot" in weights
        assert "stroke" in weights

    def test_tracker_get_mood_info(self):
        """Test mood info dictionary."""
        tracker = ExpressionMoodTracker(identity_store=None)
        info = tracker.get_mood_info()
        assert "mood_name" in info
        assert "total_drawings" in info
        assert "style_preferences" in info
