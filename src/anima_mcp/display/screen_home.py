"""
Display Screens - Home screen mixin.

Renders the face/home screen (default view).
"""

import sys
from typing import Optional

from .face import FaceState
from ..identity.store import CreatureIdentity


class HomeMixin:
    """Mixin for the home/face screen."""

    def _render_face(self, face_state: Optional[FaceState], identity: Optional[CreatureIdentity]):
        """Render face screen (default)."""
        if face_state:
            name = identity.name if identity else None
            self._display.render_face(face_state, name=name)
        else:
            # Defensive: show minimal face if face_state is None
            # This prevents blank screen during state transitions
            print("[Screen] Warning: face_state is None, showing default", file=sys.stderr, flush=True)
            self._display.show_default()
