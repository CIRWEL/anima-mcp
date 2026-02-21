"""LED types and constants."""

from dataclasses import dataclass
from typing import Tuple


@dataclass
class LEDState:
    """State of all 3 LEDs."""
    led0: Tuple[int, int, int]  # RGB for warmth (physical left, DotStar index 2)
    led1: Tuple[int, int, int]  # RGB for clarity (physical center, DotStar index 1)
    led2: Tuple[int, int, int]  # RGB for stability/presence (physical right, DotStar index 0)
    brightness: float = 0.04  # Global brightness (0-1) - manual control only
