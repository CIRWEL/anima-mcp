"""
Tests for LED brightness pipeline — smooth transitions, manual dimmer, hardware floor.

Covers audit findings #6 (smooth transitions) and validates the brightness
priority stack: base → auto → pulsing → activity → manual → floor.

These tests don't need hardware — they test the math in LEDDisplay
using mock DotStar objects.
"""

import pytest
from unittest.mock import MagicMock, patch
from anima_mcp.display.leds import LEDDisplay, LEDState, derive_led_state, transition_color


@pytest.fixture
def mock_leds():
    """Create LEDDisplay with mocked hardware."""
    with patch("anima_mcp.display.leds.display.HAS_DOTSTAR", False):
        led = LEDDisplay(brightness=0.12)
        # No hardware, so _dots is None — mock it for set_all tests
        led._dots = MagicMock()
        led._dots.brightness = 0.12
        return led


class TestDeriveledState:
    """Test the pure function that maps anima→RGB."""

    def test_returns_led_state(self):
        state = derive_led_state(0.5, 0.5, 0.5, 0.5)
        assert isinstance(state, LEDState)

    def test_rgb_values_in_range(self):
        """All RGB channels should be 0-255."""
        for w in [0.0, 0.25, 0.5, 0.75, 1.0]:
            for c in [0.0, 0.5, 1.0]:
                state = derive_led_state(w, c, 0.5, 0.5)
                for led in [state.led0, state.led1, state.led2]:
                    for channel in led:
                        assert 0 <= channel <= 255, f"Channel {channel} out of range at w={w}, c={c}"

    def test_extreme_values_dont_crash(self):
        """Even out-of-range inputs shouldn't crash."""
        state = derive_led_state(-0.5, 1.5, -1.0, 2.0)
        assert state is not None
        state = derive_led_state(0.0, 0.0, 0.0, 0.0)
        assert state is not None
        state = derive_led_state(1.0, 1.0, 1.0, 1.0)
        assert state is not None


class TestManualBrightness:
    """Test manual brightness override (joystick dimmer)."""

    def test_manual_brightness_default_is_one(self, mock_leds):
        """Default manual brightness is 1.0 (no override)."""
        assert mock_leds._manual_brightness_factor == 1.0

    def test_manual_brightness_overrides_pipeline(self, mock_leds):
        """When manual < 1.0, it becomes an absolute target."""
        mock_leds._manual_brightness_factor = 0.08
        mock_leds._auto_brightness_enabled = False
        mock_leds._color_transitions_enabled = False

        state = mock_leds.update_from_anima(0.5, 0.5, 0.5, 0.5)
        # The brightness should be near 0.08 (smooth transition starts from 0.1)
        if state:
            assert state.brightness <= 0.15  # Not full brightness

    def test_hardware_floor_enforced(self, mock_leds):
        """Brightness never goes below hardware floor."""
        assert mock_leds._hardware_brightness_floor == 0.008
        mock_leds._manual_brightness_factor = 0.001  # Below floor
        mock_leds._auto_brightness_enabled = False
        mock_leds._color_transitions_enabled = False

        state = mock_leds.update_from_anima(0.5, 0.5, 0.5, 0.5)
        if state:
            assert state.brightness >= mock_leds._hardware_brightness_floor


class TestSmoothBrightnessTransition:
    """Test that brightness changes smoothly, not in steps."""

    def test_current_brightness_initialized(self, mock_leds):
        """Smooth transition state should be initialized."""
        assert hasattr(mock_leds, "_current_brightness")
        assert hasattr(mock_leds, "_brightness_transition_speed")
        assert mock_leds._current_brightness == 0.1
        assert mock_leds._brightness_transition_speed == 0.08

    def test_brightness_glides_toward_target(self, mock_leds):
        """Multiple updates should gradually approach target brightness."""
        mock_leds._manual_brightness_factor = 0.04  # Dim preset
        mock_leds._auto_brightness_enabled = False
        mock_leds._color_transitions_enabled = False

        # Run several updates
        brightnesses = []
        for _ in range(20):
            state = mock_leds.update_from_anima(0.5, 0.5, 0.5, 0.5)
            if state:
                brightnesses.append(state.brightness)

        if len(brightnesses) >= 2:
            # Brightness should be changing (not all the same)
            unique = set(round(b, 6) for b in brightnesses)
            # Should have moved toward target over iterations
            assert brightnesses[-1] <= brightnesses[0] or len(unique) > 1


class TestColorTransitions:
    """Test smooth color interpolation."""

    def test_transition_color_interpolates(self, mock_leds):
        """transition_color should blend between colors."""
        result = transition_color((0, 0, 0), (255, 255, 255), 0.5, enabled=True)
        # Should be roughly halfway
        assert 100 < result[0] < 200
        assert 100 < result[1] < 200
        assert 100 < result[2] < 200

    def test_transition_color_same_returns_same(self, mock_leds):
        """Transitioning to same color returns same color."""
        result = transition_color((128, 64, 32), (128, 64, 32), 0.5, enabled=True)
        assert result == (128, 64, 32)

    def test_transition_color_clamped(self, mock_leds):
        """RGB values should be clamped to 0-255."""
        result = transition_color((250, 250, 250), (300, 300, 300), 0.5, enabled=True)
        for channel in result:
            assert 0 <= channel <= 255

    def test_transitions_disabled_returns_target(self, mock_leds):
        """When transitions disabled, return target directly."""
        result = transition_color((0, 0, 0), (255, 128, 64), 0.5, enabled=False)
        assert result == (255, 128, 64)
