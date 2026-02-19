"""
Tests for circadian dream state — consolidation on rest entry,
wake-up summaries, dream prompt, and integration.

Run with: pytest tests/test_circadian_dream.py -v
"""

import time
import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from anima_mcp.activity_state import ActivityManager, ActivityLevel


@pytest.fixture
def mgr():
    """Create a fresh ActivityManager."""
    return ActivityManager()


def _populate_history(history, n=200):
    """Populate an AnimaHistory with test data."""
    import random
    random.seed(42)
    base_time = datetime(2025, 6, 15, 10, 0, 0)
    for i in range(n):
        history.record(
            warmth=0.5 + random.uniform(-0.05, 0.05),
            clarity=0.6 + random.uniform(-0.05, 0.05),
            stability=0.5 + random.uniform(-0.05, 0.05),
            presence=0.5 + random.uniform(-0.05, 0.05),
            timestamp=base_time + timedelta(seconds=i),
        )


# ==================== Consolidation on Rest Entry ====================

class TestConsolidationOnRestEntry:
    """Test that entering RESTING triggers memory consolidation."""

    def test_entering_resting_calls_consolidate(self, mgr, tmp_path):
        """Transitioning to RESTING calls consolidate on the history."""
        from anima_mcp.anima_history import AnimaHistory, reset_anima_history

        reset_anima_history()

        history = AnimaHistory(
            persistence_path=tmp_path / "anima_history.json",
            auto_save_interval=99999,
        )
        _populate_history(history, n=200)

        # Patch where the lazy import resolves
        with patch("anima_mcp.anima_history.get_anima_history", return_value=history):
            mgr._current_level = ActivityLevel.ACTIVE
            mgr._transition_to(ActivityLevel.RESTING, "test")

        summaries = history.get_day_summaries()
        assert len(summaries) >= 1

        reset_anima_history()

    def test_entering_resting_sets_rest_entry_time(self, mgr):
        """Entering RESTING sets _rest_entry_time."""
        mock_history = MagicMock()
        mock_history.consolidate.return_value = None

        with patch("anima_mcp.anima_history.get_anima_history", return_value=mock_history):
            mgr._current_level = ActivityLevel.ACTIVE
            mgr._transition_to(ActivityLevel.RESTING, "test")

        assert mgr._rest_entry_time is not None
        assert mgr._rest_entry_time > 0


# ==================== Wake-up Summary ====================

class TestWakeupSummary:
    """Test wake-up summary generation and one-shot behavior."""

    def test_short_rest_no_summary(self, mgr):
        """Rest <30min produces no wake-up summary."""
        mock_history = MagicMock()
        mock_history.consolidate.return_value = None

        with patch("anima_mcp.anima_history.get_anima_history", return_value=mock_history):
            mgr._current_level = ActivityLevel.ACTIVE
            mgr._transition_to(ActivityLevel.RESTING, "test")
            mgr._last_sleep_start = datetime.now() - timedelta(minutes=5)
            mgr._transition_to(ActivityLevel.ACTIVE, "interaction")

        assert mgr._wakeup_summary is None

    def test_long_rest_generates_summary(self, mgr, tmp_path):
        """Rest >30min generates a wake-up summary string."""
        from anima_mcp.anima_history import AnimaHistory

        history = AnimaHistory(
            persistence_path=tmp_path / "anima_history.json",
            auto_save_interval=99999,
        )
        _populate_history(history, n=200)
        history.consolidate()

        with patch("anima_mcp.anima_history.get_anima_history", return_value=history):
            mgr._current_level = ActivityLevel.ACTIVE
            mgr._transition_to(ActivityLevel.RESTING, "test")
            mgr._last_sleep_start = datetime.now() - timedelta(hours=2)
            mgr._transition_to(ActivityLevel.ACTIVE, "interaction")

        assert mgr._wakeup_summary is not None
        assert "rested" in mgr._wakeup_summary

    def test_get_wakeup_summary_one_shot(self, mgr):
        """get_wakeup_summary() returns then clears."""
        mgr._wakeup_summary = "i rested for 2.0 hours."

        first = mgr.get_wakeup_summary()
        second = mgr.get_wakeup_summary()

        assert first == "i rested for 2.0 hours."
        assert second is None

    def test_get_wakeup_summary_none_when_empty(self, mgr):
        """get_wakeup_summary() returns None when no summary."""
        assert mgr.get_wakeup_summary() is None

    def test_wakeup_summary_format(self, mgr, tmp_path):
        """Wake-up summary includes state center and observation count."""
        from anima_mcp.anima_history import AnimaHistory

        history = AnimaHistory(
            persistence_path=tmp_path / "anima_history.json",
            auto_save_interval=99999,
        )
        _populate_history(history, n=200)
        history.consolidate()

        with patch("anima_mcp.anima_history.get_anima_history", return_value=history):
            summary = mgr._generate_wakeup_summary(3600 * 2)

        assert "2.0 hours" in summary
        assert "200 moments" in summary
        assert "warmth" in summary


# ==================== Rest Duration ====================

class TestRestDuration:
    """Test get_rest_duration()."""

    def test_zero_when_not_resting(self, mgr):
        """Returns 0 when not in rest."""
        assert mgr.get_rest_duration() == 0.0

    def test_positive_when_resting(self, mgr):
        """Returns positive value when resting."""
        mgr._rest_entry_time = time.time() - 100
        assert mgr.get_rest_duration() >= 99.0


# ==================== Dream Prompt ====================

class TestDreamPrompt:
    """Test dream mode prompt in LLM gateway."""

    def test_dream_prompt_builds(self):
        """Dream prompt builds without errors."""
        from anima_mcp.llm_gateway import LLMGateway, ReflectionContext

        gw = LLMGateway()
        ctx = ReflectionContext(
            warmth=0.5, clarity=0.5, stability=0.5, presence=0.5,
            recent_messages=[], unanswered_questions=[],
            time_alive_hours=10.0, current_screen="face",
        )
        prompt = gw._build_prompt(ctx, mode="dream")

        assert "resting" in prompt.lower()
        assert "connections" in prompt.lower() or "quiet" in prompt.lower()

    def test_dream_prompt_includes_memories(self, tmp_path, monkeypatch):
        """Dream prompt includes day summary memories when available."""
        from anima_mcp.llm_gateway import LLMGateway, ReflectionContext
        from anima_mcp.anima_history import AnimaHistory, reset_anima_history
        import anima_mcp.anima_history as ah_module

        reset_anima_history()

        history = AnimaHistory(
            persistence_path=tmp_path / "anima_history.json",
            auto_save_interval=99999,
        )
        _populate_history(history, n=200)
        history.consolidate()

        # Point the singleton at our test history
        monkeypatch.setattr(ah_module, "_history", history)

        gw = LLMGateway()
        ctx = ReflectionContext(
            warmth=0.5, clarity=0.5, stability=0.5, presence=0.5,
            recent_messages=[], unanswered_questions=[],
            time_alive_hours=10.0, current_screen="face",
        )

        prompt = gw._build_prompt(ctx, mode="dream")

        assert "memories" in prompt.lower() or "moments" in prompt.lower()

        reset_anima_history()
