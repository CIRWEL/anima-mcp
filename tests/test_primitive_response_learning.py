"""
Tests for primitive language response learning — implicit feedback from
whether messages arrive after utterances.

Run with: pytest tests/test_primitive_response_learning.py -v
"""

import pytest
from datetime import datetime, timedelta

from anima_mcp.primitive_language import (
    PrimitiveLanguageSystem,
    Utterance,
)


@pytest.fixture
def pls(tmp_path):
    """Create PrimitiveLanguageSystem with temp database."""
    system = PrimitiveLanguageSystem(db_path=str(tmp_path / "prim.db"))
    system._connect()
    return system


def _make_utterance(tokens=None, timestamp=None):
    """Create an Utterance for testing."""
    return Utterance(
        tokens=tokens or ["warm", "feel"],
        timestamp=timestamp or datetime.now(),
        warmth=0.6, brightness=0.5, stability=0.5, presence=0.5,
    )


# ==================== record_implicit_feedback ====================

class TestRecordImplicitFeedback:
    """Test implicit feedback recording."""

    def test_no_message_returns_none(self, pls):
        """No message arrived → returns None."""
        utt = _make_utterance()
        result = pls.record_implicit_feedback(utt, message_arrived=False, delay_seconds=999)
        assert result is None

    def test_quick_response_scores_0_7(self, pls):
        """Message within 2min → score 0.7."""
        utt = _make_utterance()
        result = pls.record_implicit_feedback(utt, message_arrived=True, delay_seconds=60)
        assert result is not None
        assert result["score"] == pytest.approx(0.7)

    def test_delayed_response_scores_0_6(self, pls):
        """Message within 2-5min → score 0.6."""
        utt = _make_utterance()
        result = pls.record_implicit_feedback(utt, message_arrived=True, delay_seconds=180)
        assert result is not None
        assert result["score"] == pytest.approx(0.6)

    def test_too_late_returns_none(self, pls):
        """Message >5min → returns None (no signal)."""
        utt = _make_utterance()
        result = pls.record_implicit_feedback(utt, message_arrived=True, delay_seconds=400)
        assert result is None

    def test_learning_rate_is_0_04(self, pls):
        """Implicit feedback uses gentler learning rate than self-feedback."""
        utt = _make_utterance(tokens=["warm"])

        # Record initial weight
        old_weight = pls._token_weights.get("warm", 1.0)

        # Apply implicit feedback with score 0.7
        pls.record_implicit_feedback(utt, message_arrived=True, delay_seconds=60)

        new_weight = pls._token_weights.get("warm", 1.0)

        # With learning_rate=0.04, score=0.7:
        # reward = (0.7 - 0.5) * 2 = 0.4
        # delta = 0.04 * 0.4 = 0.016
        expected_delta = 0.04 * (0.7 - 0.5) * 2
        actual_delta = new_weight - old_weight
        assert actual_delta == pytest.approx(expected_delta, abs=0.001)

    def test_signals_include_implicit_response(self, pls):
        """Feedback signals include 'implicit_response'."""
        utt = _make_utterance()
        result = pls.record_implicit_feedback(utt, message_arrived=True, delay_seconds=60)
        assert "implicit_response" in result["signals"]

    def test_quick_response_signals_include_quick(self, pls):
        """Quick response (<2min) signals include 'quick_response'."""
        utt = _make_utterance()
        result = pls.record_implicit_feedback(utt, message_arrived=True, delay_seconds=30)
        assert "quick_response" in result["signals"]

    def test_delayed_response_no_quick_signal(self, pls):
        """Delayed response (2-5min) does NOT include 'quick_response'."""
        utt = _make_utterance()
        result = pls.record_implicit_feedback(utt, message_arrived=True, delay_seconds=200)
        assert "quick_response" not in result["signals"]


# ==================== got_response column ====================

class TestGotResponseTracking:
    """Test got_response column in primitive_history."""

    def test_got_response_set_to_1_on_response(self, pls):
        """got_response is set to 1 when message arrived."""
        utt = _make_utterance()
        # First save the utterance to history
        pls._save_utterance(utt)

        pls.record_implicit_feedback(utt, message_arrived=True, delay_seconds=60)

        conn = pls._connect()
        row = conn.execute(
            "SELECT got_response FROM primitive_history WHERE timestamp = ?",
            (utt.timestamp.isoformat(),)
        ).fetchone()
        assert row is not None
        assert row["got_response"] == 1

    def test_got_response_set_to_0_on_no_response(self, pls):
        """got_response is set to 0 when no message arrived."""
        utt = _make_utterance()
        pls._save_utterance(utt)

        pls.record_implicit_feedback(utt, message_arrived=False, delay_seconds=999)

        conn = pls._connect()
        row = conn.execute(
            "SELECT got_response FROM primitive_history WHERE timestamp = ?",
            (utt.timestamp.isoformat(),)
        ).fetchone()
        assert row is not None
        assert row["got_response"] == 0


# ==================== Stats response_rate ====================

class TestStatsResponseRate:
    """Test that get_stats includes response_rate."""

    def test_response_rate_none_with_no_tracking(self, pls):
        """No implicit feedback → response_rate is None."""
        stats = pls.get_stats()
        assert stats["response_rate"] is None

    def test_response_rate_computed(self, pls):
        """response_rate reflects ratio of got_response=1 to tracked total."""
        # Save 3 utterances, give 2 responses and 1 no-response
        for i in range(3):
            utt = _make_utterance(timestamp=datetime.now() + timedelta(seconds=i))
            pls._save_utterance(utt)
            if i < 2:
                pls.record_implicit_feedback(utt, message_arrived=True, delay_seconds=60)
            else:
                pls.record_implicit_feedback(utt, message_arrived=False, delay_seconds=999)

        stats = pls.get_stats()
        # 2 responded out of 3 tracked → 0.667
        assert stats["response_rate"] == pytest.approx(2 / 3, abs=0.01)


# ==================== No weight update when no message ====================

class TestNoWeightUpdateOnNoMessage:
    """Test that weights don't change when there's no response signal."""

    def test_weights_unchanged_on_no_response(self, pls):
        """No message → token weights stay the same."""
        utt = _make_utterance(tokens=["warm"])
        old_weight = pls._token_weights.get("warm", 1.0)

        pls.record_implicit_feedback(utt, message_arrived=False, delay_seconds=999)

        new_weight = pls._token_weights.get("warm", 1.0)
        assert new_weight == pytest.approx(old_weight)
