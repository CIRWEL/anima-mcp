"""Tests for pattern changes — warm-only signals (Lighthouse LED plan Task 3)."""

import time
import pytest

from anima_mcp.display.leds.patterns import detect_state_change, get_pattern_colors
from anima_mcp.display.leds.types import LEDState


BASE_STATE = LEDState(
    led0=(200, 130, 45),
    led1=(180, 147, 81),
    led2=(200, 125, 42),
    brightness=0.04,
)


class TestDetectNoAlerts:
    """Low stability/clarity should NOT trigger alert or stability_warning."""

    def test_low_stability_no_alert(self):
        """stability=0.1 should not trigger 'alert'."""
        last = (0.5, 0.5, 0.5, 0.5)
        _, pattern = detect_state_change(0.5, 0.5, 0.1, 0.5, last)
        assert pattern != "alert", f"Got alert for low stability: {pattern}"
        assert pattern != "stability_warning", f"Got stability_warning: {pattern}"

    def test_low_clarity_no_alert(self):
        """clarity=0.1 should not trigger 'alert'."""
        last = (0.5, 0.5, 0.5, 0.5)
        _, pattern = detect_state_change(0.5, 0.1, 0.5, 0.5, last)
        assert pattern != "alert", f"Got alert for low clarity: {pattern}"

    def test_both_low_no_alert(self):
        """Both clarity=0.1, stability=0.1 — still no alert."""
        last = (0.5, 0.5, 0.5, 0.5)
        _, pattern = detect_state_change(0.5, 0.1, 0.1, 0.5, last)
        assert pattern != "alert", f"Got alert: {pattern}"
        assert pattern != "stability_warning", f"Got stability_warning: {pattern}"

    def test_no_stability_warning_pattern(self):
        """stability_warning should never be returned."""
        last = (0.5, 0.5, 0.8, 0.5)
        _, pattern = detect_state_change(0.5, 0.5, 0.2, 0.5, last)
        assert pattern != "stability_warning", f"Got stability_warning: {pattern}"


class TestWarmthSpikeWarm:
    """warmth_spike should use warm colors, not pure red."""

    def test_warmth_spike_triggered(self):
        last = (0.3, 0.5, 0.5, 0.5)
        _, pattern = detect_state_change(0.6, 0.5, 0.5, 0.5, last)
        assert pattern == "warmth_spike"

    def test_warmth_spike_no_pure_red(self):
        last = (0.3, 0.5, 0.5, 0.5)
        _, pattern = detect_state_change(0.6, 0.5, 0.5, 0.5, last)
        assert pattern == "warmth_spike"
        # Get pattern colors at the start
        state, active = get_pattern_colors(pattern, BASE_STATE, time.time())
        if active is not None:
            for name, color in [("led0", state.led0), ("led1", state.led1), ("led2", state.led2)]:
                assert color != (255, 0, 0), f"{name} is pure red in warmth_spike"

    def test_warmth_spike_warm_colors(self):
        """warmth_spike should blend toward warm highlight."""
        state, active = get_pattern_colors("warmth_spike", BASE_STATE, time.time())
        if active is not None:
            for name, color in [("led0", state.led0), ("led1", state.led1), ("led2", state.led2)]:
                r, g, b = color
                assert r >= g >= b, f"{name} not warm in warmth_spike: {color}"


class TestClarityBoostWarm:
    """clarity_boost should use warm white, not pure white."""

    def test_clarity_boost_triggered(self):
        last = (0.5, 0.3, 0.5, 0.5)
        _, pattern = detect_state_change(0.5, 0.7, 0.5, 0.5, last)
        assert pattern == "clarity_boost"

    def test_clarity_boost_no_pure_white(self):
        """clarity_boost should not produce (255,255,255)."""
        state, active = get_pattern_colors("clarity_boost", BASE_STATE, time.time())
        if active is not None:
            for name, color in [("led0", state.led0), ("led1", state.led1), ("led2", state.led2)]:
                assert color != (255, 255, 255), f"{name} is pure white in clarity_boost"

    def test_clarity_boost_warm_white(self):
        """clarity_boost colors should have R >= G >= B (warm white)."""
        state, active = get_pattern_colors("clarity_boost", BASE_STATE, time.time())
        if active is not None:
            for name, color in [("led0", state.led0), ("led1", state.led1), ("led2", state.led2)]:
                r, g, b = color
                assert r >= g >= b, f"{name} not warm in clarity_boost: {color}"


class TestPatternDuration:
    """Patterns should last 2.0s with smooth fade, not 0.5s."""

    def test_pattern_still_active_at_1s(self):
        """Pattern should still be active at 1.0s elapsed."""
        start = time.time() - 1.0
        state, active = get_pattern_colors("warmth_spike", BASE_STATE, start)
        assert active is not None, "Pattern ended too early (before 1.0s)"

    def test_pattern_still_active_at_1_5s(self):
        """Pattern should still be active at 1.5s elapsed."""
        start = time.time() - 1.5
        state, active = get_pattern_colors("clarity_boost", BASE_STATE, start)
        assert active is not None, "Pattern ended too early (before 1.5s)"

    def test_pattern_ends_after_2s(self):
        """Pattern should end after 2.0s."""
        start = time.time() - 2.1
        state, active = get_pattern_colors("warmth_spike", BASE_STATE, start)
        assert active is None, "Pattern still active after 2.0s"


class TestRemovedPatterns:
    """'stability_warning' and 'alert' patterns should not produce special colors."""

    def test_stability_warning_returns_base(self):
        """stability_warning pattern should return base_state."""
        state, active = get_pattern_colors("stability_warning", BASE_STATE, time.time())
        assert active is None, "stability_warning should not be an active pattern"

    def test_alert_returns_base(self):
        """alert pattern should return base_state."""
        state, active = get_pattern_colors("alert", BASE_STATE, time.time())
        assert active is None, "alert should not be an active pattern"
