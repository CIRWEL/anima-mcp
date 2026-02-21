"""Tests for brightness simplification (Lighthouse LED plan Task 2)."""

import pytest

from anima_mcp.display.leds import brightness as brightness_mod
from anima_mcp.display.leds.types import LEDState


class TestRemovedFunctions:
    """Auto-brightness, pulsing-brightness, and gamma should no longer exist."""

    def test_get_auto_brightness_removed(self):
        assert not hasattr(brightness_mod, "get_auto_brightness"), (
            "get_auto_brightness should be removed"
        )

    def test_get_pulsing_brightness_removed(self):
        assert not hasattr(brightness_mod, "get_pulsing_brightness"), (
            "get_pulsing_brightness should be removed"
        )

    def test_apply_gamma_removed(self):
        assert not hasattr(brightness_mod, "apply_gamma"), (
            "apply_gamma should be removed"
        )


class TestGetPulse:
    """get_pulse should still exist and return 0-1."""

    def test_returns_float(self):
        result = brightness_mod.get_pulse()
        assert isinstance(result, float)

    def test_in_range(self):
        for _ in range(100):
            result = brightness_mod.get_pulse(pulse_cycle=4.0)
            assert 0.0 <= result <= 1.0, f"Pulse {result} out of [0, 1]"


class TestEstimateInstantaneousBrightness:
    """estimate_instantaneous_brightness should scale amplitude with brightness."""

    def test_returns_positive(self):
        result = brightness_mod.estimate_instantaneous_brightness(0.04)
        assert result > 0.0

    def test_low_brightness_small_amplitude(self):
        """At low brightness (0.04), pulse amplitude should be very small."""
        base = 0.04
        result = brightness_mod.estimate_instantaneous_brightness(base, pulse_amount=0.05)
        # Result should be close to base -- amplitude capped
        deviation = abs(result - base)
        assert deviation < 0.01, (
            f"Deviation {deviation} too large for base={base}"
        )

    def test_high_brightness_larger_amplitude(self):
        """At higher brightness, amplitude can be larger but still proportional."""
        base = 0.12
        result = brightness_mod.estimate_instantaneous_brightness(base, pulse_amount=0.05)
        assert result >= 0.008  # floor

    def test_floor_brightness(self):
        """Should never go below 0.008."""
        result = brightness_mod.estimate_instantaneous_brightness(0.001)
        assert result >= 0.008


class TestDefaultBrightnessInTypes:
    """LEDState default brightness should be 0.04."""

    def test_default_is_004(self):
        state = LEDState(led0=(0, 0, 0), led1=(0, 0, 0), led2=(0, 0, 0))
        assert state.brightness == 0.04, f"Expected 0.04, got {state.brightness}"


class TestNoLuxImport:
    """brightness.py should not import LED_LUX_PER_BRIGHTNESS or LED_LUX_AMBIENT_FLOOR."""

    def test_no_lux_constants_in_module(self):
        assert not hasattr(brightness_mod, "LED_LUX_PER_BRIGHTNESS"), (
            "LED_LUX_PER_BRIGHTNESS should not be imported in brightness.py"
        )
        assert not hasattr(brightness_mod, "LED_LUX_AMBIENT_FLOOR"), (
            "LED_LUX_AMBIENT_FLOOR should not be imported in brightness.py"
        )
