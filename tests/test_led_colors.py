"""Tests for warm-only LED color palette (Lighthouse LED plan Task 1)."""

import itertools
import pytest

from anima_mcp.display.leds.colors import derive_led_state, _create_gradient_palette
from anima_mcp.display.leds.types import LEDState


# --- Helper ---

def _all_leds(state: LEDState):
    """Yield all three LED colors from a state."""
    yield "led0", state.led0
    yield "led1", state.led1
    yield "led2", state.led2


PARAM_RANGE = [0.0, 0.2, 0.4, 0.5, 0.6, 0.8, 1.0]


class TestWarmColorInvariant:
    """R >= G >= B must hold across all parameter combinations."""

    @pytest.mark.parametrize(
        "warmth,clarity,stability,presence",
        list(itertools.product([0.0, 0.3, 0.5, 0.7, 1.0], repeat=4)),
    )
    def test_r_ge_g_ge_b_gradient_palette(self, warmth, clarity, stability, presence):
        led0, led1, led2 = _create_gradient_palette(warmth, clarity, stability, presence)
        for name, color in [("led0", led0), ("led1", led1), ("led2", led2)]:
            r, g, b = color
            assert r >= g, f"{name} R({r}) < G({g}) at w={warmth},c={clarity},s={stability},p={presence}"
            assert g >= b, f"{name} G({g}) < B({b}) at w={warmth},c={clarity},s={stability},p={presence}"

    @pytest.mark.parametrize(
        "warmth,clarity,stability,presence",
        list(itertools.product([0.0, 0.3, 0.5, 0.7, 1.0], repeat=4)),
    )
    def test_r_ge_g_ge_b_derive_led_state(self, warmth, clarity, stability, presence):
        state = derive_led_state(warmth, clarity, stability, presence)
        for name, color in _all_leds(state):
            r, g, b = color
            assert r >= g, f"{name} R({r}) < G({g}) at w={warmth},c={clarity},s={stability},p={presence}"
            assert g >= b, f"{name} G({g}) < B({b}) at w={warmth},c={clarity},s={stability},p={presence}"


class TestNoPureRedInStandard:
    """No pure red (255,0,0) should appear in standard mode."""

    @pytest.mark.parametrize(
        "warmth,clarity,stability,presence",
        list(itertools.product(PARAM_RANGE, repeat=4)),
    )
    def test_no_pure_red(self, warmth, clarity, stability, presence):
        state = derive_led_state(warmth, clarity, stability, presence)
        for name, color in _all_leds(state):
            assert color != (255, 0, 0), (
                f"{name} is pure red (255,0,0) at w={warmth},c={clarity},s={stability},p={presence}"
            )


class TestNoBlueDominant:
    """B should never exceed G in any LED color."""

    @pytest.mark.parametrize(
        "warmth,clarity,stability,presence",
        list(itertools.product([0.0, 0.3, 0.5, 0.7, 1.0], repeat=4)),
    )
    def test_no_blue_dominant(self, warmth, clarity, stability, presence):
        state = derive_led_state(warmth, clarity, stability, presence)
        for name, color in _all_leds(state):
            r, g, b = color
            assert b <= g, f"{name} B({b}) > G({g}) at w={warmth},c={clarity},s={stability},p={presence}"


class TestDefaultBrightness:
    """Default brightness should be 0.04."""

    def test_derive_default_brightness(self):
        state = derive_led_state(0.5, 0.5, 0.5, 0.5)
        assert state.brightness == 0.04, f"Expected 0.04, got {state.brightness}"

    def test_ledstate_default_brightness(self):
        # LEDState default is updated in types.py (Task 2).
        # Here we only verify derive_led_state explicitly sets 0.04.
        state = derive_led_state(0.0, 0.0, 0.0, 0.0)
        assert state.brightness == 0.04, f"Expected 0.04, got {state.brightness}"


class TestNoNonWarmModes:
    """'minimal', 'expressive', and 'alert' pattern modes should be removed."""

    def test_no_minimal_mode(self):
        # Should fall through to standard regardless
        state = derive_led_state(0.1, 0.1, 0.1, 0.1, pattern_mode="minimal")
        # Must NOT return pure red or grey (50,50,50)
        for name, color in _all_leds(state):
            assert color != (255, 0, 0), f"{name} returned pure red in 'minimal' mode"
            assert color != (50, 50, 50), f"{name} returned grey in 'minimal' mode"

    def test_no_expressive_mode(self):
        state = derive_led_state(0.1, 0.1, 0.8, 0.8, pattern_mode="expressive")
        for name, color in _all_leds(state):
            r, g, b = color
            assert r >= g >= b, f"{name} non-warm in 'expressive': {color}"

    def test_no_alert_mode(self):
        state = derive_led_state(0.1, 0.1, 0.1, 0.1, pattern_mode="alert")
        for name, color in _all_leds(state):
            assert color != (255, 0, 0), f"{name} is pure red in 'alert' mode"


class TestNoBlueCyanGlow:
    """No blue/cyan presence glow should exist."""

    def test_high_presence_no_cyan(self):
        state = derive_led_state(0.5, 0.5, 0.5, 1.0)
        r, g, b = state.led2
        assert b <= g, f"led2 has blue-dominant glow B({b}) > G({g}) at presence=1.0"
        assert r >= g, f"led2 has non-warm glow R({r}) < G({g}) at presence=1.0"


class TestNoWhiteBoost:
    """No pure-white clarity boost should exist."""

    def test_high_clarity_no_white(self):
        state = derive_led_state(0.5, 1.0, 0.5, 0.5)
        for name, color in _all_leds(state):
            r, g, b = color
            # If it were pure white boost, g and b would be close to r
            # We check R >= G >= B (warm)
            assert r >= g >= b, f"{name} not warm at clarity=1.0: {color}"
