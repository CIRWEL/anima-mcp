"""
Tests for growth.py gap coverage — visitor context, self-dialogue topic,
and relational disposition.

Run with: pytest tests/test_growth_gaps.py -v
"""

import re

import pytest

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


# ==================== autobiography agent recency ====================

class TestAutobiographyAgentRecency:
    """The autobiography must not name agents it also reports as inactive.

    visitor_frequency is a monotonic ratchet (FREQUENT at interaction_count
    >= 10, never demoted), so selecting on it alone names whoever was once
    busy, permanently. Live on 2026-07-30 that yielded "Various agents visit
    to help: agent, mac-governance." — last seen 138 and 154 days earlier,
    and listed under visitors.inactive in the very same payload.
    """

    @staticmethod
    def _named_helpers(summary):
        """The agents the summary presents as current helpers, parsed exactly.

        Substring checks are unsafe here: the stale record is literally named
        "agent", which matches the word "agents" in the clause itself.
        """
        m = re.search(r"Various agents visit to help: ([^.]+)\.", summary)
        return [n.strip() for n in m.group(1).split(",")] if m else []

    def _make_frequent(self, gs, agent_id, name, days_ago):
        from datetime import datetime, timedelta
        # The summary short-circuits on an empty memory list.
        if not gs._memories:
            gs._record_memory("woke up", 0.5, "milestone")
        for _ in range(10):  # cross the FREQUENT threshold
            gs.record_interaction(agent_id, agent_name=name)
        rec = gs._relationships[agent_id]
        rec.last_seen = datetime.now() - timedelta(days=days_ago)
        return rec

    def test_stale_frequent_agent_is_not_named(self, gs):
        self._make_frequent(gs, "agent", "agent", days_ago=138)

        summary = gs.get_autobiography_summary()

        assert self._named_helpers(summary) == []

    def test_recent_frequent_agent_is_still_named(self, gs):
        self._make_frequent(gs, "codex", "Codex", days_ago=0)

        summary = gs.get_autobiography_summary()

        assert self._named_helpers(summary) == ["Codex"]

    def test_recent_named_while_stale_excluded(self, gs):
        self._make_frequent(gs, "mac-governance", "mac-governance", days_ago=154)
        self._make_frequent(gs, "codex", "Codex", days_ago=0)

        summary = gs.get_autobiography_summary()

        assert self._named_helpers(summary) == ["Codex"]

    def test_never_contradicts_its_own_inactive_list(self, gs):
        """Whatever get_inactive_visitors reports must not appear as a helper."""
        self._make_frequent(gs, "agent", "agent", days_ago=138)
        self._make_frequent(gs, "codex", "Codex", days_ago=0)

        named = self._named_helpers(gs.get_autobiography_summary())
        inactive = {name for name, _ in gs.get_inactive_visitors()}

        assert inactive, "precondition: something should be reported inactive"
        assert not (inactive & set(named)), (
            f"named as helpers while reported inactive: {inactive & set(named)}"
        )
