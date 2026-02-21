"""State-change LED patterns (warmth_spike, clarity_boost only).

No alert or stability_warning patterns. All colors warm amber/gold.
Patterns last 2.0s with smooth fade (no rapid flashing).
"""

import time
from typing import Optional, Tuple

from .types import LEDState
from .colors import blend_colors


def detect_state_change(
    warmth: float,
    clarity: float,
    stability: float,
    presence: float,
    last: Optional[Tuple[float, float, float, float]]
) -> tuple[Optional[Tuple[float, float, float, float]], Optional[str]]:
    """
    Detect significant state changes for pattern triggers.
    Returns (updated_last_values, pattern_name or None).

    Only warmth_spike and clarity_boost are supported.
    No alert or stability_warning triggers.
    """
    if last is None:
        return (warmth, clarity, stability, presence), None
    last_w, last_c, last_s, last_p = last
    dw = abs(warmth - last_w)
    dc = abs(clarity - last_c)
    new_last = (warmth, clarity, stability, presence)

    if dw > 0.2 and warmth > last_w:
        return new_last, "warmth_spike"
    if dc > 0.3 and clarity > last_c:
        return new_last, "clarity_boost"
    return new_last, None


# Warm pattern target colors
_WARMTH_SPIKE_COLOR = (255, 160, 50)   # warm highlight (not orange flash)
_CLARITY_BOOST_COLOR = (240, 200, 120)  # warm white (not pure white)

_PATTERN_DURATION = 2.0  # seconds
_BLEND_RATIO = 0.4       # max blend toward target color


def get_pattern_colors(
    pattern_name: str,
    base_state: LEDState,
    pattern_start_time: float
) -> Tuple[LEDState, Optional[str]]:
    """
    Get colors for a pattern. Returns (state, active_pattern_or_none).

    Patterns last 2.0s with smooth fade. Only warmth_spike and clarity_boost
    are recognized; any other pattern name returns (base_state, None).
    """
    elapsed = time.time() - pattern_start_time
    if elapsed > _PATTERN_DURATION:
        return base_state, None

    # Smooth fade: 1.0 at start, 0.0 at 2.0s
    fade = max(0.0, 1.0 - elapsed / _PATTERN_DURATION)
    blend = fade * _BLEND_RATIO

    if pattern_name == "warmth_spike":
        return LEDState(
            led0=blend_colors(base_state.led0, _WARMTH_SPIKE_COLOR, blend),
            led1=blend_colors(base_state.led1, _WARMTH_SPIKE_COLOR, blend * 0.3),
            led2=base_state.led2,
            brightness=base_state.brightness
        ), pattern_name

    if pattern_name == "clarity_boost":
        return LEDState(
            led0=base_state.led0,
            led1=blend_colors(base_state.led1, _CLARITY_BOOST_COLOR, blend),
            led2=blend_colors(base_state.led2, _CLARITY_BOOST_COLOR, blend * 0.3),
            brightness=base_state.brightness
        ), pattern_name

    # Unknown/removed patterns (alert, stability_warning) — return base, no active
    return base_state, None
