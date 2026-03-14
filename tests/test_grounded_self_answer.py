"""Tests for grounded self-answer — Lumen answering its own questions from learned data."""

import pytest
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
