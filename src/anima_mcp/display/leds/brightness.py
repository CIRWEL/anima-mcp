"""Brightness pipeline: auto, pulse, gamma, pulsing."""

import math
import time
from typing import Optional

from ...config import LED_LUX_PER_BRIGHTNESS, LED_LUX_AMBIENT_FLOOR

def get_pulse(pulse_cycle: float = 4.0) -> float:
    """Primary + secondary breath wave. Returns 0-1."""
    t = time.time()
    primary = (1.0 + math.sin(t * 2 * math.pi / pulse_cycle)) * 0.5
    breath = (1.0 + math.sin(t * 2 * math.pi / 18.0)) * 0.5
    return primary * (0.92 + 0.08 * breath)


def estimate_instantaneous_brightness(
    base_brightness: float,
    pulse_cycle: float = 12.0,
    pulse_amount: float = 0.05,
) -> float:
    """Estimate current LED brightness including breathing pulse.

    Mirrors the animation loop's pulse calculation so the sensor correction
    can track actual LED output at the moment of reading.
    """
    pulse = get_pulse(pulse_cycle)
    amplitude = pulse_amount * min(1.0, max(0.15, base_brightness / 0.12))
    return max(0.008, base_brightness + pulse * amplitude)


def get_auto_brightness(
    light_level: Optional[float],
    base_brightness: float,
    min_brightness: float,
    max_brightness: float,
    enabled: bool,
    current_brightness: float
) -> float:
    """Auto-adjust brightness from ambient light. Compensates for LED self-illumination."""
    if not enabled or light_level is None:
        return base_brightness
    estimated_led_lux = current_brightness * LED_LUX_PER_BRIGHTNESS + LED_LUX_AMBIENT_FLOOR
    corrected = max(0, light_level - estimated_led_lux)
    if corrected < 10:
        return max_brightness
    if corrected > 1000:
        return min_brightness
    log_min, log_max = math.log10(10), math.log10(1000)
    log_cur = math.log10(max(10, min(1000, corrected)))
    ratio = (log_cur - log_min) / (log_max - log_min)
    return max(min_brightness, min(max_brightness, max_brightness - ratio * (max_brightness - min_brightness)))


def get_pulsing_brightness(
    clarity: float,
    stability: float,
    enabled: bool,
    threshold_clarity: float = 0.4,
    threshold_stability: float = 0.4
) -> float:
    """Pulsing multiplier (0.3-1.0) when clarity/stability low."""
    if not enabled:
        return 1.0
    if clarity >= threshold_clarity and stability >= threshold_stability:
        return 1.0
    pulse = (math.sin(time.time() * math.pi * 2) + 1) / 2
    return 0.3 + (pulse * 0.7)


def apply_gamma(raw: float, gamma: float = 1.8, floor: float = 0.008, cap: float = 0.5) -> float:
    """Perceptual brightness. raw in [floor, cap] -> perceptual.

    At very low brightness (< 0.03), caps gamma inflation to 3x to prevent
    Night mode from being too bright (0.008 -> 0.068 uncapped).
    """
    raw = max(floor, min(cap, raw))
    corrected = raw ** (1.0 / gamma)
    if raw < 0.03:
        corrected = min(corrected, raw * 3)
    return max(floor, min(cap, corrected))
