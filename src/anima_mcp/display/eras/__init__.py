"""
Art Era Registry — manages available drawing eras and era rotation.

Eras are pluggable modules that define Lumen's visual character per drawing session.
Each drawing belongs to one era. Eras rotate on canvas clear (new drawing).
"""

import random
from typing import Dict, List


# Registry of available eras
_ERAS: Dict[str, object] = {}


def register_era(era) -> None:
    """Register an era module."""
    _ERAS[era.name] = era


def get_era(name: str):
    """Get era by name. Falls back to 'gestural' if not found."""
    return _ERAS.get(name) or _ERAS.get("gestural")


def list_eras() -> List[str]:
    """List all registered era names."""
    return list(_ERAS.keys())


def choose_next_era(current: str, drawings_saved: int) -> str:
    """Choose era for next drawing. Weighted random, favoring variety.

    The current era gets lower weight to encourage rotation.
    Could later integrate with growth system preferences.
    """
    candidates = list(_ERAS.keys())
    if len(candidates) <= 1:
        return candidates[0] if candidates else "gestural"

    weights = [0.3 if name == current else 1.0 for name in candidates]
    return random.choices(candidates, weights=weights, k=1)[0]


# --- Register eras at import time ---
from .gestural import GesturalEra  # noqa: E402

register_era(GesturalEra())
