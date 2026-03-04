"""Tests for traceable anima self-report (no LLM)."""

import pytest
from anima_mcp.anima_utterance import anima_to_self_report


class TestAnimaToSelfReport:
    """Test anima_to_self_report mapping."""

    def test_warm_returns_warm(self):
        """High warmth → i feel warm."""
        assert anima_to_self_report(0.75, 0.5, 0.5, 0.5) == "i feel warm"

    def test_cool_returns_cool(self):
        """Low warmth → i feel cool."""
        assert anima_to_self_report(0.25, 0.5, 0.5, 0.5) == "i feel cool"

    def test_clear_returns_clear(self):
        """High clarity → i feel clear."""
        assert anima_to_self_report(0.5, 0.75, 0.5, 0.5) == "i feel clear"

    def test_fuzzy_returns_fuzzy(self):
        """Low clarity → i feel fuzzy."""
        assert anima_to_self_report(0.5, 0.25, 0.5, 0.5) == "i feel fuzzy"

    def test_picks_most_salient(self):
        """When multiple dimensions deviate, picks most extreme."""
        # Warmth 0.3 (dev 0.2) vs clarity 0.4 (dev 0.1) → warmth wins
        assert anima_to_self_report(0.3, 0.4, 0.5, 0.5) == "i feel cool"

    def test_neutral_returns_none(self):
        """When no dimension is salient, returns None."""
        assert anima_to_self_report(0.5, 0.5, 0.5, 0.5) is None

    def test_near_neutral_returns_none(self):
        """Small deviations below threshold return None."""
        assert anima_to_self_report(0.55, 0.5, 0.5, 0.5) is None

    def test_stability_high(self):
        """High stability → i feel stable."""
        assert anima_to_self_report(0.5, 0.5, 0.75, 0.5) == "i feel stable"

    def test_presence_low(self):
        """Low presence → i feel distant."""
        assert anima_to_self_report(0.5, 0.5, 0.5, 0.25) == "i feel distant"
