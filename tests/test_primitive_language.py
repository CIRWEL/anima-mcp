"""
Tests for primitive_language.py — token weight learning, probabilistic selection,
utterance generation, feedback (self + explicit), weight decay, and persistence.

Covers:
  - Token weight computation from state affinities
  - Probabilistic token selection (count, categories, exploration)
  - Utterance generation and text rendering
  - should_generate timing gate
  - record_feedback and record_explicit_feedback (weight changes)
  - record_self_feedback (state coherence, stability)
  - Weight decay toward baseline
  - Persistence (save/load round-trip via SQLite)
  - Statistics and recent utterances
"""

import pytest
from datetime import datetime, timedelta

from anima_mcp.primitive_language import (
    PrimitiveLanguageSystem, PRIMITIVES, TokenCategory,
    PrimitiveToken, Utterance,
)


@pytest.fixture
def pls(tmp_path):
    """Create PrimitiveLanguageSystem with temp database."""
    system = PrimitiveLanguageSystem(db_path=str(tmp_path / "prim.db"))
    # Force connection initialization
    system._connect()
    return system


def default_state(**overrides):
    """Create a default state dict."""
    state = {"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.0}
    state.update(overrides)
    return state


# ==================== Token Weight Computation ====================

class TestComputeTokenWeight:
    """Test compute_token_weight with state affinities."""

    def test_unknown_token_returns_zero(self, pls):
        """Unknown token name returns 0.0."""
        assert pls.compute_token_weight("nonexistent", default_state()) == 0.0

    def test_neutral_state_returns_near_base(self, pls):
        """At neutral state (0.5 each), weight ≈ base_weight."""
        weight = pls.compute_token_weight("warm", default_state())
        base = PRIMITIVES["warm"].base_weight
        # Neutral state → affinity_multiplier ≈ 1.0
        assert abs(weight - base) < 0.3

    def test_warm_token_high_warmth(self, pls):
        """'warm' token weight increases when warmth is high."""
        low = pls.compute_token_weight("warm", default_state(warmth=0.1))
        high = pls.compute_token_weight("warm", default_state(warmth=0.9))
        assert high > low

    def test_cold_token_low_warmth(self, pls):
        """'cold' token weight increases when warmth is low."""
        low_warmth = pls.compute_token_weight("cold", default_state(warmth=0.1))
        high_warmth = pls.compute_token_weight("cold", default_state(warmth=0.9))
        assert low_warmth > high_warmth

    def test_minimum_weight_floor(self, pls):
        """All tokens have minimum weight > 0 (never fully disabled)."""
        state = default_state(warmth=0.0, clarity=0.0, stability=0.0, presence=-1.0)
        for name in PRIMITIVES:
            w = pls.compute_token_weight(name, state)
            assert w >= 0.1


# ==================== Token Selection ====================

class TestSelectTokens:
    """Test probabilistic token selection."""

    def test_returns_correct_count(self, pls):
        """select_tokens with explicit count returns that many tokens."""
        tokens = pls.select_tokens(default_state(), count=2)
        assert len(tokens) == 2

    def test_no_duplicate_tokens(self, pls):
        """Selected tokens should not repeat."""
        tokens = pls.select_tokens(default_state(), count=3)
        assert len(tokens) == len(set(tokens))

    def test_all_tokens_are_valid(self, pls):
        """All selected tokens are from PRIMITIVES."""
        tokens = pls.select_tokens(default_state(), count=3)
        for t in tokens:
            assert t in PRIMITIVES

    def test_stability_affects_count(self, pls):
        """High stability tends toward longer utterances (2-3 tokens)."""
        # Run many times and check average count
        counts = []
        for _ in range(100):
            tokens = pls.select_tokens(default_state(stability=0.9))
            counts.append(len(tokens))
        avg = sum(counts) / len(counts)
        assert avg > 1.5  # Should average above 1.5 with high stability

    def test_suggested_tokens_boosted(self, pls):
        """Suggested tokens appear more frequently."""
        # Run many selections with "warm" suggested
        warm_count = 0
        trials = 200
        for _ in range(trials):
            tokens = pls.select_tokens(
                default_state(), count=2, suggested_tokens=["warm"]
            )
            if "warm" in tokens:
                warm_count += 1
        # With 2x boost + 2 picks from 15, expected rate is well above 2/15 (~13%)
        # Using 15% threshold for robustness against randomness
        assert warm_count / trials > 0.15


# ==================== Utterance Generation ====================

class TestGenerateUtterance:
    """Test utterance generation."""

    def test_returns_utterance(self, pls):
        """generate_utterance returns Utterance with tokens and state."""
        utt = pls.generate_utterance(default_state())
        assert isinstance(utt, Utterance)
        assert len(utt.tokens) >= 1
        assert utt.warmth == 0.5

    def test_text_rendering(self, pls):
        """Utterance.text() joins tokens with spaces."""
        utt = Utterance(tokens=["feel", "warm", "here"])
        assert utt.text() == "feel warm here"

    def test_category_pattern(self, pls):
        """category_pattern() returns dash-separated category values."""
        utt = Utterance(tokens=["feel", "warm"])
        pattern = utt.category_pattern()
        assert pattern == "presence-state"

    def test_updates_history(self, pls):
        """Generation adds to _recent and increments counters."""
        before = len(pls._recent)
        pls.generate_utterance(default_state())
        assert len(pls._recent) == before + 1
        assert pls._total_utterances == 1

    def test_sets_last_utterance_time(self, pls):
        """Generation sets _last_utterance timestamp."""
        assert pls._last_utterance is None
        pls.generate_utterance(default_state())
        assert pls._last_utterance is not None


# ==================== should_generate ====================

class TestShouldGenerate:
    """Test utterance timing gate."""

    def test_first_utterance_always_true(self, pls):
        """With no prior utterance, should_generate returns True."""
        should, reason = pls.should_generate(default_state())
        assert should is True
        assert reason == "first_utterance"

    def test_too_soon_after_last(self, pls):
        """Within min_interval, returns False."""
        pls._last_utterance = datetime.now()
        should, reason = pls.should_generate(default_state())
        assert should is False
        assert reason == "too_soon"

    def test_interval_reached(self, pls):
        """After current_interval, returns True."""
        pls._last_utterance = datetime.now() - timedelta(minutes=30)
        should, reason = pls.should_generate(default_state())
        assert should is True
        assert reason == "interval_reached"


# ==================== Feedback ====================

class TestRecordFeedback:
    """Test external feedback (from human responses)."""

    def test_positive_feedback_increases_weights(self, pls):
        """Explicit positive feedback increases token weights."""
        utt = pls.generate_utterance(default_state())
        old_weights = {t: pls._token_weights.get(t, 1.0) for t in utt.tokens}

        pls.record_feedback(
            utt, response="this really resonates with me!",
            explicit_positive=True,
        )

        for t in utt.tokens:
            assert pls._token_weights[t] > old_weights[t]

    def test_negative_feedback_decreases_weights(self, pls):
        """Explicit negative feedback decreases token weights."""
        utt = pls.generate_utterance(default_state())
        old_weights = {t: pls._token_weights.get(t, 1.0) for t in utt.tokens}

        pls.record_feedback(
            utt, response="confused",
            explicit_negative=True,
        )

        for t in utt.tokens:
            assert pls._token_weights[t] < old_weights[t]

    def test_success_shortens_interval(self, pls):
        """Successful feedback reduces current_interval."""
        before = pls._current_interval
        utt = pls.generate_utterance(default_state())
        pls.record_feedback(utt, response="wonderful", explicit_positive=True)
        assert pls._current_interval < before

    def test_failure_lengthens_interval(self, pls):
        """Failed feedback increases current_interval."""
        before = pls._current_interval
        utt = pls.generate_utterance(default_state())
        pls.record_feedback(utt, response="?", explicit_negative=True)
        assert pls._current_interval > before

    def test_feedback_updates_score(self, pls):
        """Feedback sets score on the utterance."""
        utt = pls.generate_utterance(default_state())
        assert utt.score is None
        pls.record_feedback(utt, response="nice", explicit_positive=True)
        assert utt.score is not None
        assert utt.score > 0.5


class TestRecordExplicitFeedback:
    """Test /resonate and /confused explicit feedback."""

    def test_resonate_increases_weights(self, pls):
        """record_explicit_feedback(positive=True) increases weights."""
        utt = pls.generate_utterance(default_state())
        old_weights = {t: pls._token_weights.get(t, 1.0) for t in utt.tokens}

        result = pls.record_explicit_feedback(positive=True)
        assert result is not None
        assert result["success"] is True

        for t in utt.tokens:
            assert pls._token_weights[t] >= old_weights[t]

    def test_confused_decreases_weights(self, pls):
        """record_explicit_feedback(positive=False) decreases weights."""
        utt = pls.generate_utterance(default_state())
        old_weights = {t: pls._token_weights.get(t, 1.0) for t in utt.tokens}

        result = pls.record_explicit_feedback(positive=False)
        assert result is not None

        for t in utt.tokens:
            assert pls._token_weights[t] <= old_weights[t]

    def test_no_recent_returns_none(self, pls):
        """With no recent utterances, explicit feedback returns None."""
        result = pls.record_explicit_feedback(positive=True)
        assert result is None


class TestSelfFeedback:
    """Test automatic self-feedback (state coherence)."""

    def test_coherent_expression_positive(self, pls):
        """Tokens matching state get positive self-feedback."""
        # Generate in warm state — should produce "warm"-type tokens
        warm_state = default_state(warmth=0.9)
        utt = Utterance(
            tokens=["warm", "here"],
            warmth=0.9, brightness=0.5, stability=0.5, presence=0.0,
        )
        pls._recent.append(utt)

        result = pls.record_self_feedback(utt, warm_state)
        assert result is not None
        assert result["score"] >= 0.5  # Should be at least neutral

    def test_stability_maintained_bonus(self, pls):
        """Stable state after utterance gives bonus."""
        utt = Utterance(
            tokens=["quiet", "here"],
            warmth=0.5, brightness=0.5, stability=0.6, presence=0.0,
        )
        pls._recent.append(utt)

        # Same or better stability after utterance
        result = pls.record_self_feedback(utt, default_state(stability=0.7))
        assert result is not None
        assert "stability_maintained" in result["signals"]


# ==================== Weight Decay ====================

class TestWeightDecay:
    """Test weight decay toward baseline."""

    def test_decay_pulls_toward_base(self, pls):
        """Inflated weights decay toward base_weight over time."""
        pls._token_weights["warm"] = 2.0  # Inflated above base (1.0)
        pls._apply_weight_decay()
        assert pls._token_weights["warm"] < 2.0
        assert pls._token_weights["warm"] > 1.0  # Not fully decayed in one step

    def test_decay_pulls_deflated_up(self, pls):
        """Deflated weights are pulled back up toward base."""
        pls._token_weights["warm"] = 0.5  # Below base (1.0)
        pls._apply_weight_decay()
        assert pls._token_weights["warm"] > 0.5

    def test_decay_respects_bounds(self, pls):
        """Weights stay within [0.3, 2.5] after decay."""
        pls._token_weights["warm"] = 0.3
        pls._apply_weight_decay()
        assert pls._token_weights["warm"] >= 0.3

        pls._token_weights["warm"] = 2.5
        pls._apply_weight_decay()
        assert pls._token_weights["warm"] <= 2.5

    def test_zero_decay_rate_no_change(self, pls):
        """With decay_rate=0, weights don't change."""
        pls._decay_rate = 0.0
        pls._token_weights["warm"] = 2.0
        pls._apply_weight_decay()
        assert pls._token_weights["warm"] == 2.0


# ==================== Persistence ====================

class TestPersistence:
    """Test token weight save/load round-trip."""

    def test_weights_survive_reload(self, tmp_path):
        """Token weights persist across PrimitiveLanguageSystem instances."""
        db = str(tmp_path / "persist.db")
        pls1 = PrimitiveLanguageSystem(db_path=db)
        pls1._connect()

        # Modify a weight
        pls1._token_weights["warm"] = 1.8
        pls1._save_token_weight("warm", 1.8)

        # Reload from same DB
        pls2 = PrimitiveLanguageSystem(db_path=db)
        pls2._connect()
        assert pls2._token_weights["warm"] == pytest.approx(1.8)

    def test_combo_weights_survive_reload(self, tmp_path):
        """Combo pattern weights persist."""
        db = str(tmp_path / "persist2.db")
        pls1 = PrimitiveLanguageSystem(db_path=db)
        pls1._connect()

        pls1._combo_weights["state-inquiry"] = 1.5
        pls1._save_combo_weight("state-inquiry", 1.5, 0.7)

        pls2 = PrimitiveLanguageSystem(db_path=db)
        pls2._connect()
        assert pls2._combo_weights["state-inquiry"] == pytest.approx(1.5)

    def test_utterance_history_persisted(self, pls):
        """Generated utterances are saved to DB."""
        pls.generate_utterance(default_state())
        conn = pls._connect()
        count = conn.execute("SELECT COUNT(*) FROM primitive_history").fetchone()[0]
        assert count == 1


# ==================== Stats ====================

class TestStats:
    """Test statistics and recent utterances."""

    def test_stats_empty(self, pls):
        """Stats on fresh system return valid dict."""
        stats = pls.get_stats()
        assert stats["total_utterances"] == 0
        assert stats["recent_count"] == 0
        assert "token_weights" in stats

    def test_stats_after_generation(self, pls):
        """Stats reflect generated utterances."""
        pls.generate_utterance(default_state())
        pls.generate_utterance(default_state())
        stats = pls.get_stats()
        assert stats["total_utterances"] == 2
        assert stats["recent_count"] == 2

    def test_recent_utterances(self, pls):
        """get_recent_utterances returns last N utterances."""
        for _ in range(3):
            pls.generate_utterance(default_state())
        recent = pls.get_recent_utterances(count=2)
        assert len(recent) == 2
        assert "text" in recent[0]
        assert "tokens" in recent[0]
