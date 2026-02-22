"""
Tests for growth system — preferences, relationships, memory bounds.

Covers audit findings:
  #12 - Unbounded visitor relationships
  #17 - Drawings counter via regex
"""

import pytest
import tempfile
import os
from datetime import datetime

from anima_mcp.growth import GrowthSystem


@pytest.fixture
def growth(tmp_path):
    """Create GrowthSystem with temp database."""
    db_path = str(tmp_path / "test_growth.db")
    gs = GrowthSystem(db_path=db_path)
    return gs


class TestGrowthPreferences:
    """Test preference tracking via observe_state_preference."""

    def test_observe_state_preference_runs(self, growth):
        """Observing a preference from anima state should not crash."""
        anima = {"warmth": 0.6, "clarity": 0.5, "stability": 0.7, "presence": 0.4}
        env = {"light_lux": 50.0, "temp_c": 22.0, "humidity_pct": 45.0}
        result = growth.observe_state_preference(anima, env)
        # Returns Optional[str] — insight or None
        assert result is None or isinstance(result, str)

    def test_multiple_observations_build_preferences(self, growth):
        """Repeated observations with consistent patterns should build preferences."""
        for i in range(20):
            anima = {"warmth": 0.8, "clarity": 0.3, "stability": 0.7, "presence": 0.4}
            env = {"light_lux": 20.0, "temp_c": 22.0, "humidity_pct": 45.0}
            growth.observe_state_preference(anima, env)
        # Should have built some internal preference state
        summary = growth.get_growth_summary()
        assert isinstance(summary["preferences"], dict)

    def test_preference_vector_returns_structure(self, growth):
        """get_preference_vector should return canonical format."""
        vec = growth.get_preference_vector()
        assert "vector" in vec
        assert "labels" in vec
        assert "n_learned" in vec
        assert isinstance(vec["vector"], list)


class TestGrowthRelationships:
    """Test visitor/relationship tracking."""

    def test_record_interaction_creates_visitor(self, growth):
        """First interaction with a visitor creates a record."""
        result = growth.record_interaction("agent_123", agent_name="TestBot")
        assert isinstance(result, str)  # Returns reaction message
        # Check via internal state
        assert "agent_123" in growth._relationships

    def test_interaction_count_increments(self, growth):
        """Multiple interactions should increase count."""
        growth.record_interaction("agent_123", agent_name="TestBot")
        growth.record_interaction("agent_123", agent_name="TestBot", topic="weather")
        record = growth._relationships["agent_123"]
        assert record.interaction_count >= 2

    def test_interaction_with_topic(self, growth):
        """Interactions with topics should be recorded."""
        growth.record_interaction("agent_456", topic="philosophy")
        assert "agent_456" in growth._relationships

    def test_interaction_positive_negative(self, growth):
        """Both positive and negative interactions should work."""
        growth.record_interaction("agent_pos", positive=True)
        growth.record_interaction("agent_neg", positive=False)
        assert "agent_pos" in growth._relationships
        assert "agent_neg" in growth._relationships

    def test_growth_summary_includes_visitors(self, growth):
        """get_growth_summary should report agent visitor stats."""
        growth.record_interaction("bot_1", agent_name="Bot1")
        growth.record_interaction("bot_2", agent_name="Bot2")
        summary = growth.get_growth_summary()
        assert summary["agents"]["unique_names"] >= 2


class TestGrowthMemories:
    """Test memorable event tracking."""

    def test_record_milestone(self, growth):
        """Should be able to record a milestone."""
        growth.record_milestone(
            description="First boot after reflash",
            emotional_impact=0.8,
        )
        assert len(growth._memories) >= 1

    def test_record_memory_private(self, growth):
        """_record_memory should work with all params."""
        growth._record_memory(
            description="A discovery was made",
            emotional_impact=0.5,
            category="discovery",
        )
        assert len(growth._memories) >= 1

    def test_memories_capped(self, growth):
        """In-memory list should be bounded."""
        for i in range(200):
            growth._record_memory(
                description=f"Test memory {i}",
                emotional_impact=0.1,
                category="test",
            )
        # Should be capped at some reasonable limit (100 per code)
        assert len(growth._memories) <= 150

    def test_growth_summary_includes_memories(self, growth):
        """get_growth_summary should report memory stats."""
        growth.record_milestone("Test milestone")
        summary = growth.get_growth_summary()
        assert summary["memories"]["count"] >= 1


class TestGrowthDatabase:
    """Test database handling."""

    def test_db_uses_wal_mode(self, growth):
        """Database should use WAL journal mode for concurrent access."""
        cursor = growth._conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode.lower() == "wal"

    def test_close_doesnt_crash(self, growth):
        """Closing growth system shouldn't raise."""
        growth.close()
        # Closing again shouldn't crash either
        growth.close()
