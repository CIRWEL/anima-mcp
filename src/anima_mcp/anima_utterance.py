"""
Traceable self-report from anima. No LLM.

When Lumen says "i feel warm," it should be a direct mapping from anima state,
not generated text. This module provides that mapping.
"""

from typing import Optional


# Salience threshold: dimension must deviate from 0.5 by at least this much
_SALIENCE = 0.18


def anima_to_self_report(
    warmth: float,
    clarity: float,
    stability: float,
    presence: float,
) -> Optional[str]:
    """
    Generate traceable self-report from anima dimensions.

    Picks the most salient dimension (furthest from 0.5) and returns
    a simple utterance. Returns None if no dimension is salient.

    Returns:
        Lowercase utterance like "i feel warm" or None
    """
    dims = [
        ("warmth", warmth, "warm", "cool"),
        ("clarity", clarity, "clear", "fuzzy"),
        ("stability", stability, "stable", "unsteady"),
        ("presence", presence, "present", "distant"),
    ]
    best = max(dims, key=lambda d: abs(d[1] - 0.5))
    _, val, high, low = best
    if abs(val - 0.5) < _SALIENCE:
        return None
    if val > 0.5 + _SALIENCE:
        return f"i feel {high}"
    return f"i feel {low}"
