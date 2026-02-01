"""
Display - Render anima state on BrainCraft HAT TFT.

The creature's face: eyes, mouth, and sensor readouts.
"""

from .face import FaceState, EyeState, MouthState, derive_face_state, face_to_ascii
from .renderer import DisplayRenderer, get_display
from .design import (
    COLORS, SPACING, TYPOGRAPHY, GRADIENTS,
    wellness_to_color, anima_dimension_color,
    blend_color, dim_color, lighten_color,
    create_gradient, create_multi_gradient, gradient_at, radial_gradient_color,
    get_wellness_gradient_color, get_warmth_gradient_color,
)

__all__ = [
    "FaceState", "EyeState", "MouthState", "derive_face_state", "face_to_ascii",
    "DisplayRenderer", "get_display",
    "COLORS", "SPACING", "TYPOGRAPHY", "GRADIENTS",
    "wellness_to_color", "anima_dimension_color",
    "blend_color", "dim_color", "lighten_color",
    "create_gradient", "create_multi_gradient", "gradient_at", "radial_gradient_color",
    "get_wellness_gradient_color", "get_warmth_gradient_color",
]
