"""
Display - Render anima state on BrainCraft HAT TFT.

The creature's face: eyes, mouth, and sensor readouts.
"""

from .face import FaceState, EyeState, MouthState, derive_face_state, face_to_ascii
from .renderer import DisplayRenderer, get_display
from .design import COLORS, SPACING, TYPOGRAPHY, wellness_to_color, anima_dimension_color

__all__ = [
    "FaceState", "EyeState", "MouthState", "derive_face_state", "face_to_ascii",
    "DisplayRenderer", "get_display",
    "COLORS", "SPACING", "TYPOGRAPHY", "wellness_to_color", "anima_dimension_color",
]
