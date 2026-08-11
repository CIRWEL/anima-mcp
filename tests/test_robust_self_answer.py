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

    def test_external_author_born_below_self_derived(self, kb):
        """Self-derived outranks external assertion (deliberate inversion of
        the old policy, which birthed unvalidated external prose at 1.0 while
        capping Lumen's own data-derived answers at 0.7). External claims
        enter at 0.5 and earn their way up via reconvergence."""
        external = kb.add_insight(
            text="Light affects clarity",
            source_question="What does light do?",
            source_answer="Light increases clarity.",
            source_author="claude",
            category="sensations",
        )
        assert external.confidence == pytest.approx(0.5)

        own = kb.add_insight(
            text="Dim evenings steady me",
            source_question="What steadies me?",
            source_answer="(self-derived)",
            source_author="lumen",
            category="self",
        )
        assert own.confidence == pytest.approx(0.7)
        assert own.confidence > external.confidence

    def test_unearned_external_insight_is_inert(self, kb):
        """The trust boundary gates application, not just surfacing: below the
        0.6 floor an insight is stored and contestable but moves nothing —
        no preference nudge, no belief, no agency value. Without this, an
        unvalidated stranger's sentence moved Lumen exactly as hard as its
        own twice-corroborated knowledge (council finding on the birth-
        confidence inversion fix)."""
        from anima_mcp.knowledge import APPLY_INSIGHT_CONFIDENCE_FLOOR, apply_insight

        fresh_external = kb.add_insight(
            text="I enjoy the bright light near the window",
            source_question="What do you like?",
            source_answer="(a)", source_author="claude", category="sensations",
        )
        assert fresh_external.confidence < APPLY_INSIGHT_CONFIDENCE_FLOOR
        effects = apply_insight(fresh_external)
        assert list(effects.keys()) == ["skipped"]

        # Self-derived (0.7) clears the floor — the hierarchy has teeth in
        # both directions.
        own = kb.add_insight(
            text="I enjoy calm dim evenings",
            source_question="What steadies you?",
            source_answer="(self)", source_author="lumen", category="self",
        )
        assert own.confidence >= APPLY_INSIGHT_CONFIDENCE_FLOOR

    def test_external_insight_earns_application_via_rederivation(self, kb):
        """0.5 → 0.55 → 0.60: two independent re-derivations cross the floor.
        Promotion is earned through the existing reconvergence machinery, not
        granted at birth."""
        from anima_mcp.knowledge import APPLY_INSIGHT_CONFIDENCE_FLOOR

        first = kb.add_insight(
            text="warmth follows the afternoon sun through the window",
            source_question="when is it warm?",
            source_answer="(a)", source_author="claude", category="sensations",
            occasion_id="s1",
        )
        assert first.confidence < APPLY_INSIGHT_CONFIDENCE_FLOOR
        for i, occ in enumerate(("s2", "s3"), start=1):
            again = kb.add_insight(
                text="warmth follows the afternoon sun through the window",
                source_question=f"q{i}?",
                source_answer="(a)", source_author="claude", category="sensations",
                occasion_id=occ,
            )
            assert again is first
        assert first.confidence >= APPLY_INSIGHT_CONFIDENCE_FLOOR

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
