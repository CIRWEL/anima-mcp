"""
LED Display - Maps anima state to BrainCraft HAT's 3 DotStar LEDs.

Refactored into submodules:
- types: LEDState
- colors: derive_led_state, get_shape_color_bias, blend_colors, transition_color
- dances: DanceType, Dance, render_dance, EVENT_TO_DANCE
- patterns: detect_state_change, get_pattern_colors
- brightness: get_pulse, get_auto_brightness, get_pulsing_brightness, apply_gamma
- display: LEDDisplay
"""

from .types import LEDState
from .colors import (
    blend_colors,
    derive_led_state,
    get_shape_color_bias,
    transition_color,
)
from .dances import Dance, DanceType, EVENT_TO_DANCE, render_dance
from .display import HAS_DOTSTAR, LEDDisplay, get_led_display

__all__ = [
    "LEDDisplay",
    "LEDState",
    "Dance",
    "DanceType",
    "blend_colors",
    "derive_led_state",
    "get_shape_color_bias",
    "get_led_display",
    "HAS_DOTSTAR",
]
