"""
Tests for drawing → anima feedback loop — record_drawing_completion,
get_draw_chance_modifier, and integration.

Run with: pytest tests/test_drawing_feedback.py -v
"""

import pytest
from anima_mcp.growth import GrowthSystem


@pytest.fixture
def gs(tmp_path):
    """Create GrowthSystem with temp database."""
    return GrowthSystem(db_path=str(tmp_path / "growth.db"))


# ==================== record_drawing_completion ====================

class TestRecordDrawingCompletion:
    """Test drawing completion feedback recording."""

    def test_creates_preference(self, gs):
        """First drawing completion creates drawing_satisfaction preference."""
        gs.record_drawing_completion(
            pixel_count=500, mark_count=10,
            coherence=0.7, satisfaction=0.8,
        )
        assert "drawing_satisfaction" in gs._preferences

    def test_high_satisfaction_records_memory(self, gs):
        """Satisfaction >0.7 records an autobiographical memory."""
        gs.record_drawing_completion(
            pixel_count=500, mark_count=10,
            coherence=0.8, satisfaction=0.85,
        )
        # Check memories for creative category
        creative_memories = [m for m in gs._memories if m.category == "creative"]
        assert len(creative_memories) >= 1
        assert "pleased" in creative_memories[0].description

    def test_low_satisfaction_no_memory(self, gs):
        """Satisfaction ≤0.7 does not record memory."""
        gs.record_drawing_completion(
            pixel_count=500, mark_count=10,
            coherence=0.3, satisfaction=0.4,
        )
        creative_memories = [m for m in gs._memories if m.category == "creative"]
        assert len(creative_memories) == 0

    def test_returns_insight_on_threshold_cross(self, gs):
        """Returns insight string when preference confidence crosses threshold."""
        # First call creates the preference
        result = gs.record_drawing_completion(
            pixel_count=500, mark_count=10,
            coherence=0.7, satisfaction=0.8,
        )
        assert result is not None  # "I'm noticing something"
        assert "noticing" in result.lower()

    def test_preference_value_updates(self, gs):
        """Multiple completions update the preference value."""
        gs.record_drawing_completion(
            pixel_count=500, mark_count=10,
            coherence=0.7, satisfaction=0.9,
        )
        val1 = gs._preferences["drawing_satisfaction"].value

        gs.record_drawing_completion(
            pixel_count=500, mark_count=10,
            coherence=0.5, satisfaction=0.2,
        )
        val2 = gs._preferences["drawing_satisfaction"].value

        # Value should have shifted toward low satisfaction
        assert val2 < val1


# ==================== get_draw_chance_modifier ====================

class TestGetDrawChanceModifier:
    """Test drawing chance modifier."""

    def test_returns_1_with_no_data(self, gs):
        """No drawing data → modifier is 1.0."""
        assert gs.get_draw_chance_modifier() == 1.0

    def test_returns_1_with_few_observations(self, gs):
        """Fewer than 3 observations → still 1.0."""
        gs.record_drawing_completion(500, 10, 0.7, 0.8)
        gs.record_drawing_completion(500, 10, 0.7, 0.8)
        assert gs.get_draw_chance_modifier() == 1.0

    def test_increases_with_high_satisfaction(self, gs):
        """High satisfaction over multiple draws → modifier >1.0."""
        for _ in range(5):
            gs.record_drawing_completion(500, 10, 0.8, 0.9)

        modifier = gs.get_draw_chance_modifier()
        assert modifier > 1.0

    def test_capped_at_reasonable_range(self, gs):
        """Modifier never exceeds 1.3."""
        for _ in range(20):
            gs.record_drawing_completion(500, 10, 0.9, 0.95)

        modifier = gs.get_draw_chance_modifier()
        assert 1.0 <= modifier <= 1.3


# ==================== Persistence ====================

class TestDrawingFeedbackPersistence:
    """Test that drawing feedback survives GrowthSystem reload."""

    def test_preference_persists(self, tmp_path):
        """drawing_satisfaction preference persists across instances."""
        gs1 = GrowthSystem(db_path=str(tmp_path / "growth.db"))
        for _ in range(5):
            gs1.record_drawing_completion(500, 10, 0.8, 0.85)

        gs2 = GrowthSystem(db_path=str(tmp_path / "growth.db"))
        assert "drawing_satisfaction" in gs2._preferences
        assert gs2._preferences["drawing_satisfaction"].observation_count >= 5
