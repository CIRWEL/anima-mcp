"""
Art Era Registry — manages available drawing eras and era rotation.

Eras are pluggable modules that define Lumen's visual character per drawing session.
Each drawing belongs to one era. Eras rotate on canvas clear among the ACTIVE_ERAS pool.

All eras are registered (loadable via get_era), but only ACTIVE_ERAS participate
in automatic rotation. Archived eras (like geometric) can be activated manually
via manage_display(action="set_era", screen="geometric").
"""

import random
from typing import Dict, List


# Registry of all available eras
_ERAS: Dict[str, object] = {}

# Active pool — only these rotate between drawings.
# Edit this list to change which eras Lumen cycles through.
ACTIVE_ERAS: List[str] = ["gestural", "pointillist", "field"]


def register_era(era) -> None:
    """Register an era module."""
    _ERAS[era.name] = era


def get_era(name: str):
    """Get era by name. Falls back to 'gestural' if not found."""
    return _ERAS.get(name) or _ERAS.get("gestural")


def get_era_info(name: str) -> dict:
    """Get era metadata: name, description, whether it's in the active pool."""
    era = _ERAS.get(name)
    if not era:
        return {}
    return {
        "name": era.name,
        "description": era.description,
        "active": era.name in ACTIVE_ERAS,
    }


def list_eras() -> List[str]:
    """List all registered era names."""
    return list(_ERAS.keys())


def list_all_era_info() -> List[dict]:
    """List all eras with metadata."""
    return [get_era_info(name) for name in _ERAS]


def choose_next_era(current: str, drawings_saved: int) -> str:
    """Choose era for next drawing from the ACTIVE_ERAS pool.

    The current era gets lower weight to encourage rotation.
    Only eras in ACTIVE_ERAS are candidates.
    """
    candidates = [name for name in ACTIVE_ERAS if name in _ERAS]
    if len(candidates) <= 1:
        return candidates[0] if candidates else "gestural"

    weights = [0.3 if name == current else 1.0 for name in candidates]
    return random.choices(candidates, weights=weights, k=1)[0]


# --- Register eras at import time ---
from .gestural import GesturalEra  # noqa: E402
from .pointillist import PointillistEra  # noqa: E402
from .field import FieldEra  # noqa: E402
from .geometric import GeometricEra  # noqa: E402

register_era(GesturalEra())
register_era(PointillistEra())
register_era(FieldEra())
register_era(GeometricEra())
