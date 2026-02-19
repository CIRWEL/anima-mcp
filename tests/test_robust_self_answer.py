"""
Tests for robust self-answering — queue depth logic, self-answer confidence,
follow-up generation, and enriched self_answer prompt.

Run with: pytest tests/test_robust_self_answer.py -v
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from anima_mcp.knowledge import KnowledgeBase, Insight


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


# ==================== Follow-Up Generation ====================

class TestFollowUpGeneration:
    """Test follow-up question prompt building."""

    def test_build_follow_up_prompt_format(self):
        """build_follow_up_prompt returns proper prompt string."""
        from anima_mcp.llm_gateway import build_follow_up_prompt

        prompt = build_follow_up_prompt(
            question="Why do I feel warm?",
            answer="Because the temperature is high."
        )

        assert "Why do I feel warm?" in prompt
        assert "temperature is high" in prompt
        assert "follow-up" in prompt.lower()

    def test_build_follow_up_prompt_contains_both_qa(self):
        """Follow-up prompt contains both question and answer."""
        from anima_mcp.llm_gateway import build_follow_up_prompt

        prompt = build_follow_up_prompt("Q1?", "A1.")
        assert "Q1?" in prompt
        assert "A1." in prompt


# ==================== Self-Answer Prompt Enrichment ====================

class TestSelfAnswerPromptEnrichment:
    """Test that self_answer mode includes reflection insights and day summaries."""

    def test_self_answer_prompt_includes_reflection_insights(self, tmp_path, monkeypatch):
        """self_answer prompt includes strongest self-reflection insights."""
        from anima_mcp.llm_gateway import LLMGateway, ReflectionContext
        from anima_mcp.self_reflection import SelfReflectionSystem
        import anima_mcp.self_reflection as sr_module
        import sqlite3

        # Create a reflection system with an insight
        db_path = str(tmp_path / "test.db")
        conn = sqlite3.connect(db_path)
        conn.execute("""CREATE TABLE IF NOT EXISTS state_history (
            timestamp TEXT, warmth REAL, clarity REAL,
            stability REAL, presence REAL, sensors TEXT)""")
        conn.commit()
        conn.close()

        rs = SelfReflectionSystem(db_path=db_path)
        from anima_mcp.self_reflection import Insight as SRInsight, InsightCategory
        from datetime import datetime

        test_insight = SRInsight(
            id="test_insight",
            category=InsightCategory.WELLNESS,
            description="my clarity improves after rest",
            confidence=0.9,
            sample_count=50,
            discovered_at=datetime.now(),
            last_validated=datetime.now(),
            validation_count=10,
            contradiction_count=0,
        )
        rs._save_insight(test_insight)

        # Point the singleton at our test system
        monkeypatch.setattr(sr_module, "_reflection_system", rs)

        gw = LLMGateway()
        ctx = ReflectionContext(
            warmth=0.5, clarity=0.5, stability=0.5, presence=0.5,
            recent_messages=[], unanswered_questions=[],
            time_alive_hours=10.0, current_screen="face",
            trigger="self-answering",
            trigger_details="Why am I calm?",
        )

        prompt = gw._build_prompt(ctx, mode="self_answer")

        # The reflection insights appear in the common state_desc AND
        # in the self_answer-specific "Things I know about myself" section
        assert "clarity improves after rest" in prompt

        monkeypatch.setattr(sr_module, "_reflection_system", None)

    def test_self_answer_prompt_includes_day_summaries(self, tmp_path, monkeypatch):
        """self_answer prompt includes recent day summary data."""
        from anima_mcp.llm_gateway import LLMGateway, ReflectionContext
        from anima_mcp.anima_history import AnimaHistory, reset_anima_history
        import anima_mcp.anima_history as ah_module

        reset_anima_history()

        history = AnimaHistory(
            persistence_path=tmp_path / "anima_history.json",
            auto_save_interval=99999,
        )

        # Populate and consolidate to create day summaries
        import random
        random.seed(42)
        from datetime import timedelta
        base_time = __import__("datetime").datetime(2025, 6, 15, 10, 0, 0)
        for i in range(200):
            history.record(
                warmth=0.6 + random.uniform(-0.05, 0.05),
                clarity=0.7 + random.uniform(-0.05, 0.05),
                stability=0.5 + random.uniform(-0.05, 0.05),
                presence=0.5 + random.uniform(-0.05, 0.05),
                timestamp=base_time + timedelta(seconds=i),
            )
        history.consolidate()

        monkeypatch.setattr(ah_module, "_history", history)

        gw = LLMGateway()
        ctx = ReflectionContext(
            warmth=0.5, clarity=0.5, stability=0.5, presence=0.5,
            recent_messages=[], unanswered_questions=[],
            time_alive_hours=10.0, current_screen="face",
            trigger="self-answering",
            trigger_details="What patterns do I notice?",
        )

        prompt = gw._build_prompt(ctx, mode="self_answer")

        # Should contain day summary center values
        assert "w=" in prompt or "0.6" in prompt

        reset_anima_history()
