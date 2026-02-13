"""LED color mapping: anima state → RGB."""

from typing import Optional, Tuple

from ..design import ease_smooth
from .types import LEDState


def transition_color(
    current: Optional[Tuple[int, int, int]],
    target: Tuple[int, int, int],
    factor: float,
    enabled: bool = True
) -> Tuple[int, int, int]:
    """Smooth color transition. Adaptive: faster when far, gentler when close."""
    if not enabled or current is None:
        return target
    dr, dg, db = abs(target[0] - current[0]), abs(target[1] - current[1]), abs(target[2] - current[2])
    dist = (dr + dg + db) / (3 * 255)
    dist_norm = min(1.0, dist / 0.25)
    adaptive = 0.6 + 0.4 * ease_smooth(dist_norm)
    f = factor * adaptive
    r = int(current[0] + (target[0] - current[0]) * f)
    g = int(current[1] + (target[1] - current[1]) * f)
    b = int(current[2] + (target[2] - current[2]) * f)
    return (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))


def blend_colors(
    color1: Tuple[int, int, int],
    color2: Tuple[int, int, int],
    ratio: float
) -> Tuple[int, int, int]:
    """Blend two RGB colors. ratio 0=color1, 1=color2."""
    ratio = max(0.0, min(1.0, ratio))
    r = int(color1[0] * (1 - ratio) + color2[0] * ratio)
    g = int(color1[1] * (1 - ratio) + color2[1] * ratio)
    b = int(color1[2] * (1 - ratio) + color2[2] * ratio)
    return (r, g, b)


def _interpolate_color(
    color1: Tuple[int, int, int],
    color2: Tuple[int, int, int],
    ratio: float
) -> Tuple[int, int, int]:
    """Interpolate between two colors."""
    ratio = max(0.0, min(1.0, ratio))
    return tuple(int(color1[i] * (1 - ratio) + color2[i] * ratio) for i in range(3))


def _create_gradient_palette(
    warmth: float,
    clarity: float,
    stability: float,
    presence: float
) -> Tuple[Tuple[int, int, int], Tuple[int, int, int], Tuple[int, int, int]]:
    """Create subtle gradient palette. Constrained warm amber/gold family."""
    if warmth < 0.3:
        led0 = (180, 120, 60)
    elif warmth < 0.5:
        ratio = (warmth - 0.3) / 0.2
        led0 = _interpolate_color((180, 120, 60), (220, 160, 50), ratio)
    elif warmth < 0.7:
        ratio = (warmth - 0.5) / 0.2
        led0 = _interpolate_color((220, 160, 50), (240, 140, 40), ratio)
    else:
        ratio = (warmth - 0.7) / 0.3
        led0 = _interpolate_color((240, 140, 40), (255, 120, 30), ratio)

    i = max(120, min(220, int(80 + clarity * 140)))
    if clarity < 0.4:
        led1 = (i, int(i * 0.7), int(i * 0.2))
    elif clarity < 0.7:
        ratio = (clarity - 0.4) / 0.3
        led1 = _interpolate_color(
            (i, int(i * 0.7), int(i * 0.2)),
            (i, i, int(i * 0.5)), ratio
        )
    else:
        ratio = (clarity - 0.7) / 0.3
        led1 = _interpolate_color(
            (i, i, int(i * 0.5)),
            (i, i, int(i * 0.7)), ratio
        )

    combined = (stability * 0.6 + presence * 0.4)
    if combined < 0.3:
        led2 = (200, 160, 40)
    elif combined < 0.5:
        ratio = (combined - 0.3) / 0.2
        led2 = _interpolate_color((200, 160, 40), (160, 200, 60), ratio)
    elif combined < 0.7:
        ratio = (combined - 0.5) / 0.2
        led2 = _interpolate_color((160, 200, 60), (100, 200, 80), ratio)
    else:
        ratio = (combined - 0.7) / 0.3
        led2 = _interpolate_color((100, 200, 80), (80, 180, 120), ratio)

    if presence > 0.8:
        tint = (presence - 0.8) * 0.3
        led2 = blend_colors(led2, (60, 180, 140), ratio=tint)

    return (led0, led1, led2)


def get_shape_color_bias(shape) -> Tuple[int, int, int]:
    """Subtle RGB bias for trajectory shape. Returns (dr, dg, db)."""
    if shape is None:
        return (0, 0, 0)
    SHAPE_BIASES = {
        "settled_presence": (8, 4, -4),
        "convergence": (-4, 2, 8),
        "rising_entropy": (10, 5, -2),
        "falling_energy": (-6, -2, 4),
        "basin_transition_down": (-8, -2, 6),
        "basin_transition_up": (10, 4, -2),
        "entropy_spike_recovery": (4, 6, 4),
        "drift_dissonance": (-4, -4, -4),
        "void_rising": (6, 8, 6),
    }
    return SHAPE_BIASES.get(str(shape), (0, 0, 0))


def derive_led_state(
    warmth: float,
    clarity: float,
    stability: float,
    presence: float,
    pattern_mode: str = "standard",
    enable_color_mixing: bool = True,
    expression_mode: str = "balanced"
) -> LEDState:
    """Map anima metrics to LED colors."""
    intensity = {"subtle": 0.6, "balanced": 1.0, "expressive": 1.4, "dramatic": 2.0}.get(
        expression_mode, 1.0
    )

    if pattern_mode == "minimal":
        if clarity < 0.3 or stability < 0.3:
            c = (255, 0, 0)
        else:
            c = (50, 50, 50)
        return LEDState(led0=c, led1=c, led2=c, brightness=0.12)

    if pattern_mode == "expressive":
        if warmth < 0.25:
            led0 = (0, 0, 255)
        elif warmth < 0.4:
            led0 = (0, 150, 255)
        elif warmth < 0.6:
            led0 = (100, 255, 100)
        elif warmth < 0.75:
            led0 = (255, 200, 0)
        else:
            led0 = (255, 50, 0)
        cb = int(clarity * 255)
        if clarity < 0.3:
            led1 = (cb, 0, 0)
        elif clarity < 0.7:
            led1 = (cb, cb, 0)
        else:
            led1 = (cb, cb, cb)
        comb = (stability + presence) / 2
        if comb > 0.7:
            led2 = (0, 255, 0)
        elif comb > 0.5:
            led2 = (100, 255, 100)
        elif comb > 0.3:
            led2 = (255, 200, 0)
        else:
            led2 = (255, 0, 0)
        return LEDState(led0=led0, led1=led1, led2=led2, brightness=0.12)

    if pattern_mode == "alert":
        led0 = (0, 100, 255) if warmth < 0.3 else (255, 50, 0) if warmth > 0.7 else (50, 50, 50)
        led1 = (255, 0, 0) if clarity < 0.4 else (int(clarity * 255),) * 3
        comb = (stability + presence) / 2
        if comb < 0.4:
            led2 = (255, 0, 0)
        elif comb < 0.6:
            led2 = (255, 150, 0)
        else:
            led2 = (0, 255, 50)
        return LEDState(led0=led0, led1=led1, led2=led2, brightness=0.12)

    # standard
    led0, led1, led2 = _create_gradient_palette(warmth, clarity, stability, presence)
    if intensity != 1.0:
        led0 = tuple(max(0, min(255, int(c * intensity))) for c in led0)
        led1 = tuple(max(0, min(255, int(c * intensity))) for c in led1)
        led2 = tuple(max(0, min(255, int(c * intensity))) for c in led2)
    if enable_color_mixing and clarity > 0.5:
        boost = (clarity - 0.5) * 0.4
        white = (int(255 * boost),) * 3
        led0 = blend_colors(led0, white, ratio=boost * 0.3)
    if enable_color_mixing and presence > 0.5:
        glow = (presence - 0.5) * 0.5
        glow_color = (0, int(150 * glow), int(255 * glow))
        led2 = blend_colors(led2, glow_color, ratio=glow)
    return LEDState(led0=led0, led1=led1, led2=led2, brightness=0.12)
