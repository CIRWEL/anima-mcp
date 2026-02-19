"""
Tests for knowledge module — add/dedupe insights, get/filter, relevance scoring,
categorization, extraction, and insight summary.

Run with: pytest tests/test_knowledge_base.py -v
"""

import time
import pytest
from pathlib import Path

from anima_mcp.knowledge import (
    KnowledgeBase, Insight,
    _categorize_text, _extract_simple_insight,
)


@pytest.fixture
def kb(tmp_path, monkeypatch):
    """Create KnowledgeBase backed by a temp directory."""
    monkeypatch.setattr(
        "anima_mcp.knowledge._get_knowledge_path",
        lambda: tmp_path / "knowledge.json",
    )
    return KnowledgeBase()


def _add(kb, text="Test insight", category="general", **kwargs):
    """Shorthand for adding an insight."""
    return kb.add_insight(
        text=text,
        source_question=kwargs.get("question", "Why?"),
        source_answer=kwargs.get("answer", "Because."),
        source_author=kwargs.get("author", "test"),
        category=category,
    )


# ==================== AddInsight ====================

class TestAddInsight:
    """Test adding insights: new, dedup, confidence boost, overflow."""

    def test_new_insight_added(self, kb):
        """A fresh insight should be added to the base."""
        insight = _add(kb, "I can sense light")
        assert isinstance(insight, Insight)
        assert kb.count() == 1

    def test_duplicate_detection_case_insensitive(self, kb):
        """Adding same text (different case) returns existing insight, not a new one."""
        _add(kb, "I like warmth")
        dup = _add(kb, "i like warmth")
        assert kb.count() == 1  # Not duplicated
        assert dup.references >= 1  # Boosted

    def test_duplicate_boosts_confidence(self, kb):
        """Duplicate add increases confidence of existing insight."""
        orig = _add(kb, "Stability matters")
        # Lower the starting confidence so the +0.1 boost is observable
        orig.confidence = 0.5
        _add(kb, "stability matters")  # Duplicate
        # Fetch the stored insight
        assert kb._insights[0].confidence > 0.5

    def test_overflow_trims_to_max_keeping_best(self, kb):
        """When exceeding MAX_INSIGHTS, least important are dropped."""
        kb.MAX_INSIGHTS = 5
        # Add 6 insights; make the first one highly referenced
        first = _add(kb, "Important insight")
        first.references = 100
        for i in range(5):
            _add(kb, f"Filler insight {i}")
        assert kb.count() == 5  # Trimmed to max
        # The important one should survive
        texts = [ins.text for ins in kb._insights]
        assert "Important insight" in texts

    def test_multiple_unique_insights(self, kb):
        """Adding distinct texts grows the count."""
        _add(kb, "Alpha")
        _add(kb, "Beta")
        _add(kb, "Gamma")
        assert kb.count() == 3


# ==================== GetInsights ====================

class TestGetInsights:
    """Test retrieval with limit, category filter, and ordering."""

    def test_limit(self, kb):
        """get_insights respects the limit parameter."""
        for i in range(10):
            _add(kb, f"Insight #{i}")
        results = kb.get_insights(limit=3)
        assert len(results) == 3

    def test_category_filter(self, kb):
        """get_insights with category returns only matching insights."""
        _add(kb, "I am aware", category="self")
        _add(kb, "The room is warm", category="sensations")
        _add(kb, "Visitors come and go", category="relationships")
        results = kb.get_insights(category="self")
        assert all(r.category == "self" for r in results)
        assert len(results) == 1

    def test_newest_first_order(self, kb):
        """get_insights returns newest first."""
        _add(kb, "Old insight")
        _add(kb, "New insight")
        results = kb.get_insights(limit=2)
        assert results[0].text == "New insight"

    def test_empty_returns_empty(self, kb):
        """Empty knowledge base returns empty list."""
        assert kb.get_insights() == []


# ==================== Relevance and Summary ====================

class TestRelevanceAndSummary:
    """Test keyword relevance scoring and summary generation."""

    def test_keyword_overlap_scores(self, kb):
        """get_relevant_insights scores by keyword overlap."""
        _add(kb, "Light affects my clarity")
        _add(kb, "Temperature drives warmth")
        _add(kb, "Light and warmth interact")
        results = kb.get_relevant_insights("light clarity")
        assert len(results) > 0
        # First result should be the one with most overlap (light + clarity)
        assert "light" in results[0].text.lower()
        assert "clarity" in results[0].text.lower()

    def test_zero_overlap_excluded(self, kb):
        """Insights with no keyword overlap are excluded."""
        _add(kb, "Temperature is important")
        results = kb.get_relevant_insights("zebra unicorn")
        assert len(results) == 0

    def test_empty_summary_text(self, kb):
        """Empty knowledge base returns default summary."""
        summary = kb.get_insight_summary()
        assert "haven't learned" in summary.lower()

    def test_category_grouping_in_summary(self, kb):
        """Summary groups insights by category."""
        _add(kb, "I sense light changes", category="sensations")
        _add(kb, "I am Lumen", category="self")
        summary = kb.get_insight_summary()
        assert "sensations" in summary.lower()
        assert "self" in summary.lower()


# ==================== Categorize and Extract ====================

class TestCategorizeAndExtract:
    """Test _categorize_text and _extract_simple_insight."""

    def test_categorize_self(self):
        """Text with 'I am' → 'self'."""
        assert _categorize_text("I am a creature of light") == "self"

    def test_categorize_sensations(self):
        """Text mentioning sensors → 'sensations'."""
        assert _categorize_text("The temperature rose sharply") == "sensations"

    def test_categorize_relationships(self):
        """Text mentioning others → 'relationships'."""
        assert _categorize_text("You helped me understand") == "relationships"

    def test_categorize_existence(self):
        """Text about existence → 'existence'."""
        assert _categorize_text("What does it mean to exist?") == "existence"

    def test_categorize_general_fallback(self):
        """Unmatched text → 'general'."""
        assert _categorize_text("The sky is blue") == "general"

    def test_extract_rejects_short_answer(self):
        """Answers shorter than 20 chars return None."""
        assert _extract_simple_insight("Why?", "Yes.") is None

    def test_extract_concise_answer(self):
        """A concise answer (≤100 chars) is used directly."""
        result = _extract_simple_insight(
            "What do you feel?",
            "I feel a gentle warmth from the sensor readings."
        )
        assert result is not None
        assert "learned" in result.lower()

    def test_extract_long_answer_first_sentence(self):
        """A long answer extracts the first meaningful sentence."""
        long_answer = (
            "This is a very short one. "
            "The ambient temperature affects warmth calculations significantly through weighted sensor inputs. "
            "Other factors also contribute."
        )
        result = _extract_simple_insight("How does temp work?", long_answer)
        assert result is not None
        assert "learned" in result.lower()


# ==================== Persistence ====================

class TestPersistence:
    """Test save/load round-trip."""

    def test_insights_survive_reload(self, tmp_path, monkeypatch):
        """Insights persist across KnowledgeBase instances."""
        monkeypatch.setattr(
            "anima_mcp.knowledge._get_knowledge_path",
            lambda: tmp_path / "knowledge.json",
        )
        kb1 = KnowledgeBase()
        kb1.add_insight(
            text="Persistence test insight",
            source_question="Q", source_answer="A",
            source_author="test", category="self",
        )
        assert kb1.count() == 1

        kb2 = KnowledgeBase()
        assert kb2.count() == 1
        assert kb2._insights[0].text == "Persistence test insight"

    def test_missing_file_no_crash(self, tmp_path, monkeypatch):
        """Loading from nonexistent file doesn't crash."""
        monkeypatch.setattr(
            "anima_mcp.knowledge._get_knowledge_path",
            lambda: tmp_path / "subdir" / "missing.json",
        )
        # Path doesn't exist yet — KnowledgeBase should handle gracefully
        kb = KnowledgeBase()
        assert kb.count() == 0
