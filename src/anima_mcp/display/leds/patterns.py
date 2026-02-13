"""State-change LED patterns (warmth_spike, clarity_boost, etc.)."""

import math
import time
from typing import Optional, Tuple

from .types import LEDState


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
    """
    if last is None:
        return (warmth, clarity, stability, presence), None
    last_w, last_c, last_s, last_p = last
    dw = abs(warmth - last_w)
    dc = abs(clarity - last_c)
    ds = abs(stability - last_s)
    dp = abs(presence - last_p)
    new_last = (warmth, clarity, stability, presence)

    if dw > 0.2 and warmth > last_w:
        return new_last, "warmth_spike"
    if dc > 0.3 and clarity > last_c:
        return new_last, "clarity_boost"
    if ds > 0.2 and stability < last_s:
        return new_last, "stability_warning"
    if clarity < 0.3 or stability < 0.3:
        return new_last, "alert"
    return new_last, None


def get_pattern_colors(
    pattern_name: str,
    base_state: LEDState,
    pattern_start_time: float
) -> Tuple[LEDState, Optional[str]]:
    """
    Get colors for a pattern. Returns (state, active_pattern_or_none).
    When elapsed > 0.5s, returns (base_state, None) to clear pattern.
    """
    elapsed = time.time() - pattern_start_time
    if elapsed > 0.5:
        return base_state, None

    if pattern_name == "warmth_spike" and elapsed < 0.3:
        return LEDState(
            led0=(255, 150, 0),
            led1=base_state.led1,
            led2=base_state.led2,
            brightness=base_state.brightness
        ), pattern_name
    if pattern_name == "clarity_boost" and elapsed < 0.2:
        return LEDState(
            led0=base_state.led0,
            led1=(255, 255, 255),
            led2=base_state.led2,
            brightness=base_state.brightness
        ), pattern_name
    if pattern_name == "stability_warning" and elapsed < 0.4:
        return LEDState(
            led0=base_state.led0,
            led1=base_state.led1,
            led2=(255, 0, 0),
            brightness=base_state.brightness
        ), pattern_name
    if pattern_name == "alert":
        pulse = (math.sin(elapsed * math.pi * 4) + 1) / 2
        c = (255, int(200 * pulse), 0)
        return LEDState(led0=c, led1=c, led2=c, brightness=base_state.brightness), pattern_name

    return base_state, None
