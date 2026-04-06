"""
Tests for robust self-answering — self-answer confidence.

Run with: pytest tests/test_robust_self_answer.py -v
"""

import pytest

from anima_mcp.knowledge import KnowledgeBase


@pytest.fixture
def kb(tmp_path, monkeypatch):
    """Create KnowledgeBase backed by a temp directory."""
    monkeypatch.setattr(
        "anima_mcp.knowledge._get_knowledge_path",
        lambda: tmp_path / "knowledge.json",
    )
    return KnowledgeBase()


# ==================== Self-Answer Confidence ====================

class TestSelfAnswerConfidence:
    """Test that self-sourced insights get lower confidence."""

    def test_lumen_author_default_confidence_0_7(self, kb):
        """Insights from author 'lumen' default to 0.7 confidence."""
        insight = kb.add_insight(
            text="I think stability helps me",
            source_question="Why am I calm?",
            source_answer="Because stability is high.",
            source_author="lumen",
            category="self",
        )
        assert insight.confidence == pytest.approx(0.7)

    def test_external_author_default_confidence_1_0(self, kb):
        """Insights from external authors default to 1.0 confidence."""
        insight = kb.add_insight(
            text="Light affects clarity",
            source_question="What does light do?",
            source_answer="Light increases clarity.",
            source_author="claude",
            category="sensations",
        )
        assert insight.confidence == pytest.approx(1.0)

    def test_explicit_confidence_overrides_default(self, kb):
        """Explicit confidence parameter overrides both defaults."""
        insight = kb.add_insight(
            text="Custom confidence insight",
            source_question="Q", source_answer="A",
            source_author="lumen",
            confidence=0.5,
        )
        assert insight.confidence == pytest.approx(0.5)

    def test_case_insensitive_lumen_check(self, kb):
        """Author 'Lumen' (capitalized) also gets 0.7 confidence."""
        insight = kb.add_insight(
            text="Case test insight",
            source_question="Q", source_answer="A",
            source_author="Lumen",
        )
        assert insight.confidence == pytest.approx(0.7)
