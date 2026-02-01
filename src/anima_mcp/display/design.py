"""
Design System - Lumen's visual language.

Consistent colors, spacing, and typography for all screens.
Warm, alive, elegant - matching the care in the backend.
"""

from dataclasses import dataclass
from typing import Tuple

# === Color Palette ===
# Warm, organic colors that feel alive

@dataclass(frozen=True)
class Colors:
    """Lumen's color palette - warm and elegant."""

    # Primary colors (warm whites and ambers)
    WARM_WHITE: Tuple[int, int, int] = (255, 252, 245)
    SOFT_WHITE: Tuple[int, int, int] = (240, 238, 230)
    AMBER: Tuple[int, int, int] = (255, 200, 120)
    GOLD: Tuple[int, int, int] = (255, 215, 140)

    # Accent colors (soft, not harsh)
    SOFT_CYAN: Tuple[int, int, int] = (140, 200, 210)
    SOFT_TEAL: Tuple[int, int, int] = (120, 180, 190)
    SOFT_GREEN: Tuple[int, int, int] = (140, 200, 140)
    SOFT_YELLOW: Tuple[int, int, int] = (240, 220, 140)
    SOFT_ORANGE: Tuple[int, int, int] = (240, 180, 120)
    SOFT_CORAL: Tuple[int, int, int] = (240, 160, 140)
    SOFT_PURPLE: Tuple[int, int, int] = (180, 150, 200)
    SOFT_BLUE: Tuple[int, int, int] = (140, 170, 210)

    # Status colors (muted, not alarming)
    STATUS_GOOD: Tuple[int, int, int] = (140, 200, 140)
    STATUS_OK: Tuple[int, int, int] = (220, 200, 120)
    STATUS_WARN: Tuple[int, int, int] = (220, 160, 100)
    STATUS_BAD: Tuple[int, int, int] = (200, 120, 120)

    # Backgrounds and text
    BG_DARK: Tuple[int, int, int] = (15, 15, 18)
    BG_SUBTLE: Tuple[int, int, int] = (25, 25, 30)
    TEXT_PRIMARY: Tuple[int, int, int] = (240, 238, 230)
    TEXT_SECONDARY: Tuple[int, int, int] = (180, 175, 165)
    TEXT_DIM: Tuple[int, int, int] = (120, 115, 110)


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
