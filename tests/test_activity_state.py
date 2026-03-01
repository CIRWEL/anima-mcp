"""
Tests for activity state module.

Validates circadian rhythm, interaction override, and state transitions.
"""

import pytest
import time
from unittest.mock import patch

from anima_mcp.activity_state import (
    ActivityManager,
    ActivityLevel,
    ActivityState,
)


@pytest.fixture
def manager():
    """Create a fresh ActivityManager."""
    return ActivityManager()


class TestInteractionOverride:
    """Test that recent interaction overrides circadian sleep."""

    def test_recent_interaction_stays_active_at_night(self, manager):
        """Test: interaction within 10 min keeps Lumen active even at 2 AM."""
        # Simulate interaction just happened
        manager._last_interaction_time = time.time()

        # At 2 AM, circadian = 0.1 (strongly toward resting)
        with patch("anima_mcp.activity_state.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 2

            state = manager.get_state(presence=0.5, stability=0.5, light_level=0)

        assert state.level == ActivityLevel.ACTIVE
        assert "engaged" in state.reason

    def test_old_interaction_allows_sleep_at_night(self, manager):
        """Test: no interaction for 2 hours at night → resting."""
        # Simulate 2 hours of inactivity
        manager._last_interaction_time = time.time() - 7200

        with patch("anima_mcp.activity_state.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 2

            state = manager.get_state(presence=0.5, stability=0.5, light_level=0)

        assert state.level == ActivityLevel.RESTING

    def test_interaction_wakes_from_resting(self, manager):
        """Test: interaction triggers wake from resting state."""
        manager._current_level = ActivityLevel.RESTING
        manager.record_interaction()
        assert manager._current_level == ActivityLevel.ACTIVE

    def test_interaction_wakes_from_drowsy(self, manager):
        """Test: interaction triggers wake from drowsy state."""
        manager._current_level = ActivityLevel.DROWSY
        manager.record_interaction()
        assert manager._current_level == ActivityLevel.ACTIVE

    def test_interaction_when_already_active_no_transition(self, manager):
        """Test: interaction when already active doesn't re-transition."""
        manager._current_level = ActivityLevel.ACTIVE
        state_since = manager._state_since

        manager.record_interaction()

        # Should stay active, _state_since unchanged
        assert manager._current_level == ActivityLevel.ACTIVE
        assert manager._state_since == state_since


class TestScoreToLevel:
    """Test the _score_to_level logic directly."""

    def test_recently_engaged_overrides_low_score(self, manager):
        """Test: recent interaction overrides even a very low activity score."""
        inactivity = 5 * 60  # 5 minutes (< 10 min threshold)
        level, reason = manager._score_to_level(
            score=0.2,  # Would normally be RESTING
            circadian=0.1,  # Night
            inactivity=inactivity,
            light=0,
        )
        assert level == ActivityLevel.ACTIVE
        assert reason == "engaged"

    def test_not_engaged_night_long_inactivity_rests(self, manager):
        """Test: nighttime + long inactivity forces resting."""
        inactivity = 90 * 60  # 90 minutes (> resting threshold)
        level, reason = manager._score_to_level(
            score=0.5,  # Would normally be DROWSY
            circadian=0.1,  # Night
            inactivity=inactivity,
            light=None,
        )
        assert level == ActivityLevel.RESTING
        assert "night" in reason

    def test_not_engaged_dark_night_rests(self, manager):
        """Test: darkness + nighttime forces resting (even moderate inactivity)."""
        inactivity = 15 * 60  # 15 minutes (past recently_engaged but not resting threshold)
        level, reason = manager._score_to_level(
            score=0.5,
            circadian=0.2,  # Night (< 0.3)
            inactivity=inactivity,
            light=2,  # Very dark (< 5)
        )
        assert level == ActivityLevel.RESTING
        assert "darkness" in reason

    def test_recently_engaged_blocks_darkness_override(self, manager):
        """Test: darkness + night does NOT force rest when recently engaged."""
        inactivity = 5 * 60  # 5 minutes
        level, reason = manager._score_to_level(
            score=0.2,
            circadian=0.1,  # Night
            inactivity=inactivity,
            light=2,  # Very dark
        )
        assert level == ActivityLevel.ACTIVE
        assert reason == "engaged"

    def test_high_score_returns_active(self, manager):
        """Test: high activity score → active."""
        level, reason = manager._score_to_level(
            score=0.8,
            circadian=0.9,
            inactivity=20 * 60,  # Not recently engaged
            light=500,
        )
        assert level == ActivityLevel.ACTIVE
        assert "high activity score" in reason

    def test_moderate_score_returns_drowsy(self, manager):
        """Test: moderate activity score → drowsy."""
        level, reason = manager._score_to_level(
            score=0.5,
            circadian=0.5,
            inactivity=20 * 60,
            light=200,
        )
        assert level == ActivityLevel.DROWSY

    def test_low_score_returns_resting(self, manager):
        """Test: low activity score → resting."""
        level, reason = manager._score_to_level(
            score=0.2,
            circadian=0.5,  # Not night (so circadian override doesn't apply)
            inactivity=20 * 60,
            light=200,
        )
        assert level == ActivityLevel.RESTING


class TestActivityState:
    """Test ActivityState data and LED settings."""

    def test_active_state_settings(self, manager):
        """Test active state has full brightness and normal speed."""
        manager._last_interaction_time = time.time()  # Just interacted

        with patch("anima_mcp.activity_state.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 10  # Morning
            state = manager.get_state(presence=0.7, stability=0.7)

        assert state.level == ActivityLevel.ACTIVE
        assert state.brightness_multiplier == 1.0
        assert state.update_interval_multiplier == 1.0

    def test_led_settings_per_level(self, manager):
        """Test LED settings vary by activity level."""
        manager._current_level = ActivityLevel.ACTIVE
        active_leds = manager.get_led_settings()
        assert active_leds["brightness_override"] is None

        manager._current_level = ActivityLevel.DROWSY
        drowsy_leds = manager.get_led_settings()
        assert drowsy_leds["brightness_override"] == 0.6  # Matches brightness_mult

        manager._current_level = ActivityLevel.RESTING
        resting_leds = manager.get_led_settings()
        assert resting_leds["brightness_override"] == 0.35  # Matches brightness_mult

    def test_get_status_returns_dict(self, manager):
        """Test get_status returns expected keys."""
        status = manager.get_status()
        assert "level" in status
        assert "since" in status
        assert "duration_seconds" in status
        assert "last_interaction_seconds_ago" in status
        assert "settings" in status
