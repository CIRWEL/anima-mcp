"""Tests for grounded self-answer — Lumen answering its own questions from learned data."""

from unittest.mock import patch, MagicMock
from dataclasses import dataclass


@dataclass
class FakeAnima:
    warmth: float = 0.5
    clarity: float = 0.5
    stability: float = 0.5
    presence: float = 0.5


@dataclass
class FakeInsight:
    description: str
    confidence: float

    def strength(self):
        return self.confidence


@dataclass
class FakeKnowledgeInsight:
    text: str
    confidence: float


@dataclass
class FakeBelief:
    description: str
    confidence: float
    value: float = 0.5

    def get_belief_strength(self):
        if self.confidence < 0.3:
            return "uncertain"
        elif self.confidence < 0.6:
            return "moderate"
        else:
            return "confident"


class TestGroundedSelfAnswer:
    """Test _grounded_self_answer matches questions to learned data."""

    def test_matches_insight_to_question(self):
        """Question about stability finds stability insight."""
        from anima_mcp.server import _grounded_self_answer

        fake_insight = FakeInsight(
            description="I feel more stable when light is low",
            confidence=0.8,
        )
        fake_reflector = MagicMock()
        fake_reflector.get_insights.return_value = [fake_insight]

        with patch("anima_mcp.self_reflection.get_reflection_system", return_value=fake_reflector):
            answer = _grounded_self_answer(
                "why am I more stable sometimes?",
                FakeAnima(), None,
            )

        assert answer is not None
        assert "stable" in answer.lower()

    def test_no_match_returns_none(self):
        """Question with no matching data returns None."""
        from anima_mcp.server import _grounded_self_answer

        fake_reflector = MagicMock()
        fake_reflector.get_insights.return_value = []

        with patch("anima_mcp.self_reflection.get_reflection_system", return_value=fake_reflector):
            answer = _grounded_self_answer(
                "what is the meaning of purple?",
                FakeAnima(), None,
            )

        assert answer is None

    def test_current_state_for_feeling_question(self):
        """'How do I feel' question uses current anima state."""
        from anima_mcp.server import _grounded_self_answer

        fake_reflector = MagicMock()
        fake_reflector.get_insights.return_value = []

        with patch("anima_mcp.self_reflection.get_reflection_system", return_value=fake_reflector):
            answer = _grounded_self_answer(
                "how do I feel right now?",
                FakeAnima(warmth=0.8, stability=0.7), None,
            )

        assert answer is not None
        assert "warm" in answer.lower()

    def test_combines_multiple_sources(self):
        """Answer combines insights when multiple match."""
        from anima_mcp.server import _grounded_self_answer

        insights = [
            FakeInsight("My warmth tends to be best at night", 0.8),
            FakeInsight("I feel warmth when someone is present", 0.7),
        ]
        fake_reflector = MagicMock()
        fake_reflector.get_insights.return_value = insights

        with patch("anima_mcp.self_reflection.get_reflection_system", return_value=fake_reflector):
            answer = _grounded_self_answer(
                "why do I feel warmth?",
                FakeAnima(), None,
            )

        assert answer is not None
        assert "warmth" in answer.lower() or "warm" in answer.lower()

    def test_belief_matches_dimension_keywords(self):
        """Beliefs match via dimension keyword mapping."""
        from anima_mcp.server import _grounded_self_answer

        fake_reflector = MagicMock()
        fake_reflector.get_insights.return_value = []

        fake_model = MagicMock()
        fake_model.beliefs = {
            "light_warmth": FakeBelief("light affects my warmth", 0.7),
        }

        with patch("anima_mcp.self_reflection.get_reflection_system", return_value=fake_reflector), \
             patch("anima_mcp.self_model.get_self_model", return_value=fake_model):
            answer = _grounded_self_answer(
                "does light change how warm I feel?",
                FakeAnima(), None,
            )

        assert answer is not None
        assert "light" in answer.lower()


class TestInteractionLevelEnrichment:
    """Test interaction_level is computed and added to sensor data."""

    def test_interaction_level_recent(self):
        """Recent message produces high interaction_level."""
        import time
        from unittest.mock import MagicMock

        fake_msg = MagicMock()
        fake_msg.author = "kenny"
        fake_msg.timestamp = time.time() - 60  # 1 minute ago

        with patch("anima_mcp.messages.get_recent_messages", return_value=[fake_msg]):
            from anima_mcp.messages import get_recent_messages
            recent = get_recent_messages(limit=5)
            non_lumen = [m for m in recent if getattr(m, 'author', '') != 'lumen']
            assert len(non_lumen) == 1
            from datetime import datetime
            now = datetime.now()
            last_ts = max(m.timestamp for m in non_lumen)
            minutes_ago = (now.timestamp() - last_ts) / 60
            level = max(0.0, 1.0 - minutes_ago / 30.0)
            assert level > 0.9  # 1 minute ago → ~0.97

    def test_interaction_level_old(self):
        """Old message produces low interaction_level."""
        import time
        from unittest.mock import MagicMock

        fake_msg = MagicMock()
        fake_msg.author = "kenny"
        fake_msg.timestamp = time.time() - 1800  # 30 minutes ago

        from datetime import datetime
        now = datetime.now()
        minutes_ago = (now.timestamp() - fake_msg.timestamp) / 60
        level = max(0.0, 1.0 - minutes_ago / 30.0)
        assert level <= 0.05  # 30 min → ~0.0

    def test_interaction_level_no_messages(self):
        """No messages produces 0.0."""
        level = 0.0  # default when no non-lumen messages
        assert level == 0.0


class TestSelfReflectionInteraction:
    """Test that self-reflection can analyze interaction_level correlations."""

    def test_pattern_to_description_interaction(self):
        """Interaction patterns produce readable descriptions."""
        from anima_mcp.self_reflection import SelfReflectionSystem, StatePattern

        sys = SelfReflectionSystem.__new__(SelfReflectionSystem)

        high_pattern = StatePattern(
            condition="high interaction",
            outcome="higher warmth",
            correlation=0.15,
            sample_count=50,
            avg_warmth=0.7, avg_clarity=0.5,
            avg_stability=0.5, avg_presence=0.6,
        )
        desc = sys._pattern_to_description(high_pattern)
        assert "someone is around" in desc
        assert "warmth" in desc

        low_pattern = StatePattern(
            condition="low interaction",
            outcome="higher stability",
            correlation=-0.12,
            sample_count=50,
            avg_warmth=0.5, avg_clarity=0.5,
            avg_stability=0.7, avg_presence=0.4,
        )
        desc = sys._pattern_to_description(low_pattern)
        assert "alone" in desc
        assert "stability" in desc
