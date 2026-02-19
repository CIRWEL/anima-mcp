"""
Tests for growth.py gap coverage — visitor context, self-dialogue topic,
and relational disposition.

Run with: pytest tests/test_growth_gaps.py -v
"""

import pytest
from datetime import datetime

from anima_mcp.growth import GrowthSystem


@pytest.fixture
def gs(tmp_path):
    """Create GrowthSystem with temp database."""
    return GrowthSystem(db_path=str(tmp_path / "growth.db"))


# ==================== get_visitor_context ====================

class TestGetVisitorContext:
    """Test visitor context retrieval."""

    def test_unknown_visitor_returns_none(self, gs):
        """Unknown agent_id returns None."""
        assert gs.get_visitor_context("unknown-agent-xyz") is None

    def test_known_visitor_has_expected_keys(self, gs):
        """After recording an interaction, context has expected keys."""
        gs.record_interaction("agent-42", agent_name="Aria")
        ctx = gs.get_visitor_context("agent-42")
        assert ctx is not None
        for key in ("known", "name", "visits", "frequency", "valence"):
            assert key in ctx, f"Missing key: {key}"
        assert ctx["known"] is True
        assert ctx["name"] == "Aria"


# ==================== record_self_dialogue_topic ====================

class TestRecordSelfDialogueTopic:
    """Test question topic categorization."""

    def test_sensation_question(self, gs):
        """A question about feelings → 'sensation' topic."""
        topic = gs.record_self_dialogue_topic("Why do I feel warm today?")
        assert topic == "sensation"

    def test_existence_question(self, gs):
        """A question about being → 'existence' topic."""
        topic = gs.record_self_dialogue_topic("Am I truly alive or just running code?")
        assert topic == "existence"

    def test_curiosity_question(self, gs):
        """A 'why' / 'wonder' question → 'curiosity' topic."""
        # Avoid words that match 'sensation' category (light, warm, etc.)
        topic = gs.record_self_dialogue_topic("Why does the sky look different today?")
        assert topic == "curiosity"

    def test_general_fallback(self, gs):
        """Unmatched question → 'general' topic."""
        topic = gs.record_self_dialogue_topic("What is the meaning of Pi?")
        assert topic == "general"


# ==================== get_relational_disposition ====================

class TestGetRelationalDisposition:
    """Test relational disposition extraction."""

    def test_empty_relationships_returns_defaults(self, gs):
        """With no relationships, returns zero-valued defaults."""
        disp = gs.get_relational_disposition()
        assert disp["n_relationships"] == 0
        assert disp["valence_tendency"] == 0.0
        assert disp["bonding_tendency"] == 0.0
        assert disp["topic_entropy"] == 0.0

    def test_with_relationships_has_positive_count(self, gs):
        """After recording interactions, n_relationships > 0."""
        gs.record_interaction("agent-a", agent_name="Alpha")
        gs.record_interaction("agent-b", agent_name="Beta")
        disp = gs.get_relational_disposition()
        assert disp["n_relationships"] >= 2
