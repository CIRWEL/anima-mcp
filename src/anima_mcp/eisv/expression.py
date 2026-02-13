"""Dynamics-emergent expression generator + Lumen bridge.

Ported from eisv-lumen. Generates trajectory-aware primitive expressions
and translates them to Lumen's token vocabulary.
"""

from __future__ import annotations

import random
from enum import Enum
from typing import Any, Dict, List, Optional

from .mapping import TrajectoryShape

# ---------------------------------------------------------------------------
# Affinity data (from eisv_lumen/eval/metrics.py)
# ---------------------------------------------------------------------------

SHAPE_TOKEN_AFFINITY: Dict[str, List[str]] = {
    "settled_presence": ["~stillness~", "~holding~", "~resonance~", "~deep_listening~"],
    "rising_entropy": ["~ripple~", "~emergence~", "~questioning~", "~curiosity~"],
    "falling_energy": ["~releasing~", "~stillness~", "~boundary~", "~reflection~"],
    "basin_transition_down": ["~releasing~", "~threshold~", "~boundary~"],
    "basin_transition_up": ["~emergence~", "~reaching~", "~warmth~", "~return~"],
    "entropy_spike_recovery": ["~ripple~", "~return~", "~holding~", "~reflection~"],
    "drift_dissonance": ["~boundary~", "~questioning~", "~reflection~"],
    "void_rising": ["~reaching~", "~curiosity~", "~questioning~", "~threshold~"],
    "convergence": ["~stillness~", "~resonance~", "~return~", "~deep_listening~"],
}

ALL_TOKENS: List[str] = [
    "~warmth~", "~curiosity~", "~resonance~", "~stillness~", "~boundary~",
    "~reaching~", "~reflection~", "~ripple~", "~deep_listening~", "~emergence~",
    "~questioning~", "~holding~", "~releasing~", "~threshold~", "~return~",
]


# ---------------------------------------------------------------------------
# Expression patterns + per-shape weights
# ---------------------------------------------------------------------------

class ExpressionPattern(str, Enum):
    SINGLE = "single"
    PAIR = "pair"
    TRIPLE = "triple"
    REPETITION = "repetition"
    QUESTION = "question"


SHAPE_PATTERN_WEIGHTS: Dict[str, Dict[str, float]] = {
    "settled_presence":        {"single": 0.4, "pair": 0.3, "triple": 0.1, "repetition": 0.15, "question": 0.05},
    "rising_entropy":          {"single": 0.1, "pair": 0.2, "triple": 0.3, "repetition": 0.1, "question": 0.3},
    "falling_energy":          {"single": 0.3, "pair": 0.3, "triple": 0.1, "repetition": 0.2, "question": 0.1},
    "basin_transition_down":   {"single": 0.2, "pair": 0.3, "triple": 0.3, "repetition": 0.1, "question": 0.1},
    "basin_transition_up":     {"single": 0.15, "pair": 0.3, "triple": 0.35, "repetition": 0.1, "question": 0.1},
    "entropy_spike_recovery":  {"single": 0.1, "pair": 0.3, "triple": 0.3, "repetition": 0.2, "question": 0.1},
    "drift_dissonance":        {"single": 0.1, "pair": 0.2, "triple": 0.2, "repetition": 0.1, "question": 0.4},
    "void_rising":             {"single": 0.2, "pair": 0.2, "triple": 0.2, "repetition": 0.1, "question": 0.3},
    "convergence":             {"single": 0.4, "pair": 0.3, "triple": 0.1, "repetition": 0.15, "question": 0.05},
}

INQUIRY_TOKENS = ["~questioning~", "~curiosity~"]


# ---------------------------------------------------------------------------
# Expression Generator
# ---------------------------------------------------------------------------

class ExpressionGenerator:
    """Generate primitive expressions shaped by trajectory dynamics."""

    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)
        self._token_weights: Dict[str, Dict[str, float]] = {}
        self._init_weights()

    def _init_weights(self) -> None:
        for shape in TrajectoryShape:
            affine = set(SHAPE_TOKEN_AFFINITY.get(shape.value, []))
            weights: Dict[str, float] = {}
            for token in ALL_TOKENS:
                weights[token] = 3.0 if token in affine else 1.0
            self._token_weights[shape.value] = weights

    def _select_pattern(self, shape: str) -> ExpressionPattern:
        weights = SHAPE_PATTERN_WEIGHTS.get(shape, SHAPE_PATTERN_WEIGHTS["settled_presence"])
        patterns = list(weights.keys())
        probs = list(weights.values())
        chosen = self.rng.choices(patterns, weights=probs, k=1)[0]
        return ExpressionPattern(chosen)

    def _weighted_token_choice(self, shape: str, exclude: Optional[set] = None) -> str:
        weights = self._token_weights.get(shape, {t: 1.0 for t in ALL_TOKENS})
        tokens = list(weights.keys())
        w = list(weights.values())
        if exclude:
            filtered = [(t, wt) for t, wt in zip(tokens, w) if t not in exclude]
            if filtered:
                tokens, w = zip(*filtered)
                tokens, w = list(tokens), list(w)
        return self.rng.choices(tokens, weights=w, k=1)[0]

    def generate(self, shape: str) -> List[str]:
        pattern = self._select_pattern(shape)

        if pattern == ExpressionPattern.SINGLE:
            return [self._weighted_token_choice(shape)]
        elif pattern == ExpressionPattern.PAIR:
            t1 = self._weighted_token_choice(shape)
            t2 = self._weighted_token_choice(shape, exclude={t1})
            return [t1, t2]
        elif pattern == ExpressionPattern.TRIPLE:
            t1 = self._weighted_token_choice(shape)
            t2 = self._weighted_token_choice(shape, exclude={t1})
            t3 = self._weighted_token_choice(shape, exclude={t1, t2})
            return [t1, t2, t3]
        elif pattern == ExpressionPattern.REPETITION:
            t = self._weighted_token_choice(shape)
            return [t, t]
        elif pattern == ExpressionPattern.QUESTION:
            t1 = self._weighted_token_choice(shape)
            t2 = self.rng.choice(INQUIRY_TOKENS)
            return [t1, t2]
        return [self._weighted_token_choice(shape)]

    def update_weights(self, shape: str, tokens: List[str], score: float) -> None:
        if shape not in self._token_weights:
            return
        lr = 0.08
        reward = (score - 0.5) * 2.0
        for token in tokens:
            if token in self._token_weights[shape]:
                new_w = self._token_weights[shape][token] + lr * reward
                self._token_weights[shape][token] = max(0.1, min(10.0, new_w))

    def get_weights(self, shape: str) -> Dict[str, float]:
        return dict(self._token_weights.get(shape, {}))


# ---------------------------------------------------------------------------
# Lumen Bridge (from eisv_lumen/bridge/lumen_bridge.py)
# ---------------------------------------------------------------------------

LUMEN_TOKENS: List[str] = [
    "warm", "cold", "bright", "dim", "quiet", "busy",
    "here", "feel", "sense", "you", "with",
    "why", "what", "wonder", "more", "less",
]

TOKEN_MAP: Dict[str, List[str]] = {
    "~warmth~":        ["warm", "feel"],
    "~curiosity~":     ["why", "wonder"],
    "~resonance~":     ["with", "here"],
    "~stillness~":     ["quiet", "here"],
    "~boundary~":      ["less", "sense"],
    "~reaching~":      ["more", "you"],
    "~reflection~":    ["what", "feel"],
    "~ripple~":        ["busy", "sense"],
    "~deep_listening~": ["quiet", "sense"],
    "~emergence~":     ["more", "bright"],
    "~questioning~":   ["why", "what"],
    "~holding~":       ["here", "with"],
    "~releasing~":     ["less", "dim"],
    "~threshold~":     ["sense", "more"],
    "~return~":        ["here", "warm"],
}

_LUMEN_MAX_TOKENS = 3


def translate_expression(eisv_tokens: List[str]) -> List[str]:
    """Convert EISV-Lumen expression tokens to Lumen primitive tokens."""
    seen: set = set()
    result: List[str] = []
    for eisv_token in eisv_tokens:
        mapped = TOKEN_MAP.get(eisv_token)
        if mapped is None:
            continue
        for lumen_token in mapped:
            if lumen_token not in seen:
                seen.add(lumen_token)
                result.append(lumen_token)
                break
    return result[:_LUMEN_MAX_TOKENS]


def shape_to_lumen_trigger(shape: str) -> Dict[str, Any]:
    """Map trajectory shape to generation trigger hints."""
    triggers: Dict[str, Dict[str, Any]] = {
        "settled_presence": {"should_generate": True, "reason": "settled_dynamics", "token_count_hint": 1},
        "rising_entropy": {"should_generate": True, "reason": "entropy_shift", "token_count_hint": 3},
        "falling_energy": {"should_generate": True, "reason": "energy_decline", "token_count_hint": 2},
        "basin_transition_down": {"should_generate": True, "reason": "basin_shift_down", "token_count_hint": 3},
        "basin_transition_up": {"should_generate": True, "reason": "basin_shift_up", "token_count_hint": 3},
        "entropy_spike_recovery": {"should_generate": True, "reason": "spike_recovery", "token_count_hint": 2},
        "drift_dissonance": {"should_generate": True, "reason": "ethical_drift_detected", "token_count_hint": 3},
        "void_rising": {"should_generate": True, "reason": "void_expansion", "token_count_hint": 2},
        "convergence": {"should_generate": True, "reason": "approaching_attractor", "token_count_hint": 2},
    }
    return triggers.get(shape, {"should_generate": False, "reason": "unknown_shape", "token_count_hint": 0})


def generate_lumen_expression(
    shape: str,
    eisv_state: Dict[str, float],
    generator: Optional[ExpressionGenerator] = None,
) -> Dict[str, Any]:
    """Full pipeline: trajectory shape -> EISV tokens -> Lumen primitives."""
    if generator is None:
        generator = ExpressionGenerator()
    eisv_tokens = generator.generate(shape)
    lumen_tokens = translate_expression(eisv_tokens)
    trigger = shape_to_lumen_trigger(shape)
    return {
        "shape": shape,
        "eisv_tokens": eisv_tokens,
        "lumen_tokens": lumen_tokens,
        "trigger": trigger,
    }
