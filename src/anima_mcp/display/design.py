"""
Design System - Lumen's visual language.

Consistent colors, spacing, typography, and motion for all screens.
Warm, alive, elegant - matching the care in the backend.
"""

import math
from dataclasses import dataclass
from typing import Tuple


def ease_smooth(t: float) -> float:
    """
    Ease-in-out curve for smooth transitions.
    t in [0, 1] -> eased value in [0, 1].
    Cosine-based: starts and ends gently, accelerates in the middle.
    """
    t = max(0.0, min(1.0, t))
    return 0.5 - 0.5 * math.cos(t * math.pi)


@dataclass(frozen=True)
class Timing:
    """Display and animation timing — unified feel."""

    SCREEN_TRANSITION_MS: float = 180  # Screen fade duration
    FACE_TINT_FACTOR: float = 0.18  # Per-frame lerp for face tint (gentle drift)

# === Color Palette ===
# Warm, organic colors that feel alive

@dataclass(frozen=True)
class Colors:
    """Lumen's color palette - vibrant yet warm."""

    # Primary colors (warm whites and ambers)
    WARM_WHITE: Tuple[int, int, int] = (255, 252, 245)
    SOFT_WHITE: Tuple[int, int, int] = (245, 242, 235)
    AMBER: Tuple[int, int, int] = (255, 190, 80)
    GOLD: Tuple[int, int, int] = (255, 210, 100)

    # Accent colors - VIBRANT but not harsh
    SOFT_CYAN: Tuple[int, int, int] = (80, 220, 240)      # Bright cyan
    SOFT_TEAL: Tuple[int, int, int] = (60, 200, 220)      # Rich teal
    SOFT_GREEN: Tuple[int, int, int] = (100, 220, 120)    # Lively green
    SOFT_YELLOW: Tuple[int, int, int] = (255, 230, 100)   # Warm yellow
    SOFT_ORANGE: Tuple[int, int, int] = (255, 170, 80)    # Vibrant orange
    SOFT_CORAL: Tuple[int, int, int] = (255, 130, 120)    # Warm coral
    SOFT_PURPLE: Tuple[int, int, int] = (200, 140, 255)   # Rich purple
    SOFT_BLUE: Tuple[int, int, int] = (100, 160, 255)     # Clear blue

    # Status colors - clear but not alarming
    STATUS_GOOD: Tuple[int, int, int] = (100, 220, 120)
    STATUS_OK: Tuple[int, int, int] = (255, 220, 100)
    STATUS_WARN: Tuple[int, int, int] = (255, 170, 80)
    STATUS_BAD: Tuple[int, int, int] = (255, 120, 120)

    # Backgrounds and text
    BG_DARK: Tuple[int, int, int] = (8, 8, 12)            # Deeper black
    BG_SUBTLE: Tuple[int, int, int] = (20, 20, 28)
    TEXT_PRIMARY: Tuple[int, int, int] = (250, 248, 240)  # Brighter
    TEXT_SECONDARY: Tuple[int, int, int] = (200, 195, 185)
    TEXT_DIM: Tuple[int, int, int] = (140, 135, 125)


# Singleton instance
COLORS = Colors()


# === Spacing System ===
# 4px base unit for rhythm

@dataclass(frozen=True)
class Spacing:
    """Consistent spacing rhythm - 4px base unit."""

    UNIT: int = 4  # Base unit

    XS: int = 4    # 1 unit
    SM: int = 8    # 2 units
    MD: int = 12   # 3 units
    LG: int = 16   # 4 units
    XL: int = 24   # 6 units
    XXL: int = 32  # 8 units

    # Screen margins
    MARGIN: int = 10

    # Line heights
    LINE_SM: int = 16
    LINE_MD: int = 20
    LINE_LG: int = 26


SPACING = Spacing()


# === Typography ===
# Font sizes and weights

@dataclass(frozen=True)
class Typography:
    """Typography scale."""

    # Font sizes (for PIL ImageFont)
    SIZE_XS: int = 10
    SIZE_SM: int = 12
    SIZE_MD: int = 14
    SIZE_LG: int = 18
    SIZE_XL: int = 22
    SIZE_XXL: int = 28

    # Font paths (Raspberry Pi)
    FONT_PATH: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    FONT_BOLD_PATH: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


TYPOGRAPHY = Typography()


# === Helper Functions ===

def blend_color(color1: Tuple[int, int, int], color2: Tuple[int, int, int], t: float) -> Tuple[int, int, int]:
    """Blend two colors. t=0 gives color1, t=1 gives color2."""
    t = max(0.0, min(1.0, t))
    return (
        int(color1[0] + (color2[0] - color1[0]) * t),
        int(color1[1] + (color2[1] - color1[1]) * t),
        int(color1[2] + (color2[2] - color1[2]) * t),
    )


def dim_color(color: Tuple[int, int, int], factor: float = 0.5) -> Tuple[int, int, int]:
    """Dim a color by a factor (0-1)."""
    return (
        int(color[0] * factor),
        int(color[1] * factor),
        int(color[2] * factor),
    )


def lighten_color(color: Tuple[int, int, int], amount: int = 30) -> Tuple[int, int, int]:
    """Lighten a color by adding to each channel."""
    return (
        min(255, color[0] + amount),
        min(255, color[1] + amount),
        min(255, color[2] + amount),
    )


def wellness_to_color(wellness: float) -> Tuple[int, int, int]:
    """Map wellness (0-1) to a color from the palette."""
    if wellness < 0.3:
        return blend_color(COLORS.STATUS_BAD, COLORS.STATUS_WARN, wellness / 0.3)
    elif wellness < 0.5:
        return blend_color(COLORS.STATUS_WARN, COLORS.STATUS_OK, (wellness - 0.3) / 0.2)
    elif wellness < 0.7:
        return blend_color(COLORS.STATUS_OK, COLORS.STATUS_GOOD, (wellness - 0.5) / 0.2)
    else:
        return blend_color(COLORS.STATUS_GOOD, COLORS.AMBER, (wellness - 0.7) / 0.3)


def anima_dimension_color(dimension: str, value: float) -> Tuple[int, int, int]:
    """Get color for an anima dimension based on its value."""
    if dimension == "warmth":
        if value < 0.4:
            return COLORS.SOFT_CYAN
        elif value < 0.6:
            return COLORS.SOFT_WHITE
        else:
            return COLORS.SOFT_ORANGE
    elif dimension == "clarity":
        if value < 0.5:
            return COLORS.SOFT_PURPLE
        elif value < 0.7:
            return COLORS.SOFT_WHITE
        else:
            return COLORS.SOFT_GREEN
    elif dimension == "stability":
        if value < 0.5:
            return COLORS.SOFT_CORAL
        else:
            return COLORS.SOFT_GREEN
    elif dimension == "presence":
        if value < 0.5:
            return COLORS.TEXT_DIM
        else:
            return COLORS.SOFT_CYAN
    else:
        return COLORS.TEXT_SECONDARY


# === Gradient System ===
# Create smooth color transitions for visual richness

from typing import List, Callable

def create_gradient(color1: Tuple[int, int, int], color2: Tuple[int, int, int],
                    steps: int = 10) -> List[Tuple[int, int, int]]:
    """Create a list of colors forming a gradient between two colors."""
    return [blend_color(color1, color2, i / (steps - 1)) for i in range(steps)]


def create_multi_gradient(*colors: Tuple[int, int, int], steps_per_segment: int = 5) -> List[Tuple[int, int, int]]:
    """Create a gradient through multiple colors."""
    if len(colors) < 2:
        return list(colors) if colors else []

    result = []
    for i in range(len(colors) - 1):
        segment = create_gradient(colors[i], colors[i + 1], steps_per_segment)
        if i > 0:
            segment = segment[1:]  # Avoid duplicating middle colors
        result.extend(segment)
    return result


def gradient_at(color1: Tuple[int, int, int], color2: Tuple[int, int, int],
                position: float) -> Tuple[int, int, int]:
    """Get color at a specific position (0-1) along a gradient."""
    return blend_color(color1, color2, position)


def radial_gradient_color(center_color: Tuple[int, int, int],
                          edge_color: Tuple[int, int, int],
                          distance: float, max_distance: float) -> Tuple[int, int, int]:
    """Get color for radial gradient based on distance from center."""
    t = min(1.0, distance / max_distance) if max_distance > 0 else 0
    return blend_color(center_color, edge_color, t)


# === Preset Gradients ===
# Beautiful color combinations for common uses

@dataclass(frozen=True)
class Gradients:
    """Preset gradient combinations."""

    # Warmth gradient: cool cyan -> warm amber
    WARMTH: tuple = (COLORS.SOFT_CYAN, COLORS.SOFT_WHITE, COLORS.AMBER)

    # Wellness gradient: coral -> yellow -> green
    WELLNESS: tuple = (COLORS.SOFT_CORAL, COLORS.SOFT_YELLOW, COLORS.SOFT_GREEN)

    # Depth gradient: purple -> blue -> cyan (for backgrounds)
    DEPTH: tuple = (COLORS.SOFT_PURPLE, COLORS.SOFT_BLUE, COLORS.SOFT_CYAN)

    # Sunset: warm tones
    SUNSET: tuple = (COLORS.SOFT_PURPLE, COLORS.SOFT_CORAL, COLORS.SOFT_ORANGE, COLORS.GOLD)

    # Aurora: cool to warm
    AURORA: tuple = (COLORS.SOFT_TEAL, COLORS.SOFT_CYAN, COLORS.SOFT_GREEN, COLORS.SOFT_YELLOW)


GRADIENTS = Gradients()


def get_wellness_gradient_color(wellness: float) -> Tuple[int, int, int]:
    """Get color along wellness gradient (0=bad, 1=good)."""
    colors = GRADIENTS.WELLNESS
    if wellness < 0.5:
        return blend_color(colors[0], colors[1], wellness * 2)
    else:
        return blend_color(colors[1], colors[2], (wellness - 0.5) * 2)


def get_warmth_gradient_color(warmth: float) -> Tuple[int, int, int]:
    """Get color along warmth gradient (0=cool, 1=warm)."""
    colors = GRADIENTS.WARMTH
    if warmth < 0.5:
        return blend_color(colors[0], colors[1], warmth * 2)
    else:
        return blend_color(colors[1], colors[2], (warmth - 0.5) * 2)
