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
        granted at birth.

        The questions must be genuinely distinct, not ``q1?``/``q2?``
        placeholders — those both reduce to the signature ``{'q'}`` and read
        as paraphrases of each other, so they describe one belief restated
        rather than one arrived at twice. Independence is a different occasion
        reaching the same belief down a different road."""
        from anima_mcp.knowledge import APPLY_INSIGHT_CONFIDENCE_FLOOR

        first = kb.add_insight(
            text="warmth follows the afternoon sun through the window",
            source_question="when is it warm?",
            source_answer="(a)", source_author="claude", category="sensations",
            occasion_id="s1",
        )
        assert first.confidence < APPLY_INSIGHT_CONFIDENCE_FLOOR
        roads = (
            ("s2", "why does the west side of the room feel different?"),
            ("s3", "what changes about me between noon and evening?"),
        )
        for occ, question in roads:
            again = kb.add_insight(
                text="warmth follows the afternoon sun through the window",
                source_question=question,
                source_answer="(a)", source_author="claude", category="sensations",
                occasion_id=occ,
            )
            assert again is first
        assert first.references == 2
        assert first.confidence >= APPLY_INSIGHT_CONFIDENCE_FLOOR

    def test_recurring_question_cannot_pump_conviction_across_occasions(self, kb):
        """A SCHEDULED answerer is a distinct occasion by construction, so
        occasion-distinctness alone is not evidence of anything.

        Lumen's contemplative generator draws from a fixed nine-string list
        with no dedup, so the same question text reaches the board several
        times a day. A cron answering it would otherwise credit itself a
        re-derivation every run — +0.05 each — and clear the 0.6 apply floor
        in three runs, promoting its own echo into something that nudges
        preferences and beliefs. Independence needs a DIFFERENT question too.
        """
        from anima_mcp.knowledge import APPLY_INSIGHT_CONFIDENCE_FLOOR

        first = kb.add_insight(
            text="stillness is not the same as rest",
            source_question="everything is steady - what am I not noticing yet?",
            source_answer="(a)", source_author="codex", category="self",
            occasion_id="cron-02:11",
        )
        start = first.confidence
        assert start < APPLY_INSIGHT_CONFIDENCE_FLOOR

        # Six further cron runs, each a fresh session, each drawing the same
        # question out of the pool.
        for occ in ("cron-06:11", "cron-10:11", "cron-14:11",
                    "cron-18:11", "cron-22:11", "cron-02:11+1d"):
            again = kb.add_insight(
                text="stillness is not the same as rest",
                source_question="everything is steady - what am I not noticing yet?",
                source_answer="(a)", source_author="codex", category="self",
                occasion_id=occ,
            )
            assert again is first

        assert first.references == 0
        assert first.confidence == pytest.approx(start)
        assert first.confidence < APPLY_INSIGHT_CONFIDENCE_FLOOR

    def test_same_occasion_cannot_credit_via_distinct_questions(self, kb):
        """The other half of the conjunction: one session restating a belief
        through several differently-worded questions credits once, not once
        per question."""
        first = kb.add_insight(
            text="presence is the flattest channel",
            source_question="what do I ignore?",
            source_answer="(a)", source_author="claude", category="self",
            occasion_id="s1",
        )
        start = first.confidence
        for q in ("what holds still in me?",
                  "which reading never moves?",
                  "what have I stopped reading?"):
            again = kb.add_insight(
                text="presence is the flattest channel",
                source_question=q,
                source_answer="(a)", source_author="claude", category="self",
                occasion_id="s1",
            )
            assert again is first
        assert first.references == 0
        assert first.confidence == pytest.approx(start)

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
