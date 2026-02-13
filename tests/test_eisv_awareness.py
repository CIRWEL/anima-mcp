"""Tests for EISV trajectory awareness integration."""

import time
import pytest
from anima_mcp.eisv.mapping import (
    anima_to_eisv, compute_trajectory_window, classify_trajectory,
    TrajectoryShape, compute_derivatives, EISV_DIMS,
)
from anima_mcp.eisv.expression import (
    ExpressionGenerator, translate_expression, generate_lumen_expression,
    TOKEN_MAP, ALL_TOKENS, SHAPE_TOKEN_AFFINITY, LUMEN_TOKENS,
)
from anima_mcp.eisv.awareness import TrajectoryAwareness


class TestMapping:
    def test_anima_to_eisv_basic(self):
        result = anima_to_eisv(0.8, 0.7, 0.9, 0.5)
        assert result["E"] == 0.8
        assert result["I"] == 0.7
        assert abs(result["S"] - 0.1) < 1e-9
        assert abs(result["V"] - 0.15) < 1e-9

    def test_anima_to_eisv_clamping(self):
        result = anima_to_eisv(1.5, -0.5, 0.0, 2.0)
        assert result["E"] == 1.0
        assert result["I"] == 0.0
        assert result["S"] == 1.0
        assert result["V"] == 0.0

    def test_eisv_values_in_range(self):
        for w in [0.0, 0.5, 1.0]:
            for c in [0.0, 0.5, 1.0]:
                for s in [0.0, 0.5, 1.0]:
                    for p in [0.0, 0.5, 1.0]:
                        r = anima_to_eisv(w, c, s, p)
                        for k in ("E", "I", "S", "V"):
                            assert 0.0 <= r[k] <= 1.0


class TestDerivatives:
    def test_compute_derivatives_basic(self):
        states = [
            {"t": 0.0, "E": 0.5, "I": 0.5, "S": 0.3, "V": 0.1},
            {"t": 1.0, "E": 0.6, "I": 0.5, "S": 0.3, "V": 0.1},
            {"t": 2.0, "E": 0.7, "I": 0.5, "S": 0.3, "V": 0.1},
        ]
        derivs = compute_derivatives(states)
        assert len(derivs) == 2
        assert abs(derivs[0]["dE"] - 0.1) < 1e-9

    def test_trajectory_window_structure(self):
        states = [{"t": float(i), "E": 0.5, "I": 0.5, "S": 0.3, "V": 0.1} for i in range(5)]
        window = compute_trajectory_window(states)
        assert "states" in window
        assert "derivatives" in window
        assert "second_derivatives" in window


class TestShapeClassifier:
    def test_settled_presence(self):
        states = [{"t": float(i), "E": 0.7, "I": 0.7, "S": 0.2, "V": 0.1} for i in range(10)]
        window = compute_trajectory_window(states)
        assert classify_trajectory(window) == TrajectoryShape.SETTLED_PRESENCE

    def test_rising_entropy(self):
        states = [{"t": float(i), "E": 0.5, "I": 0.5, "S": 0.2 + i * 0.08, "V": 0.1} for i in range(10)]
        window = compute_trajectory_window(states)
        assert classify_trajectory(window) == TrajectoryShape.RISING_ENTROPY

    def test_basin_transition_down(self):
        states = [{"t": float(i), "E": 0.8 - i * 0.04, "I": 0.5, "S": 0.2, "V": 0.1} for i in range(10)]
        window = compute_trajectory_window(states)
        assert classify_trajectory(window) == TrajectoryShape.BASIN_TRANSITION_DOWN

    def test_convergence(self):
        # Small decaying oscillation
        states = []
        for i in range(10):
            amp = 0.01 * (0.8 ** i)
            states.append({"t": float(i), "E": 0.5 + amp, "I": 0.5 - amp, "S": 0.3, "V": 0.1})
        window = compute_trajectory_window(states)
        assert classify_trajectory(window) == TrajectoryShape.CONVERGENCE


class TestExpressionGenerator:
    def test_generates_valid_tokens(self):
        gen = ExpressionGenerator(seed=42)
        for shape in TrajectoryShape:
            tokens = gen.generate(shape.value)
            assert len(tokens) >= 1
            assert all(t in ALL_TOKENS for t in tokens)

    def test_deterministic_with_seed(self):
        gen1 = ExpressionGenerator(seed=42)
        gen2 = ExpressionGenerator(seed=42)
        for shape in TrajectoryShape:
            assert gen1.generate(shape.value) == gen2.generate(shape.value)

    def test_weight_update(self):
        gen = ExpressionGenerator(seed=42)
        before = gen.get_weights("settled_presence").copy()
        gen.update_weights("settled_presence", ["~stillness~"], 0.9)
        after = gen.get_weights("settled_presence")
        assert after["~stillness~"] > before["~stillness~"]


class TestBridge:
    def test_token_map_completeness(self):
        assert set(TOKEN_MAP.keys()) == set(ALL_TOKENS)
        for mapped in TOKEN_MAP.values():
            assert all(t in LUMEN_TOKENS for t in mapped)

    def test_translate_expression(self):
        result = translate_expression(["~warmth~", "~curiosity~"])
        assert len(result) <= 3
        assert all(t in LUMEN_TOKENS for t in result)

    def test_translate_empty(self):
        assert translate_expression([]) == []

    def test_translate_caps_at_3(self):
        result = translate_expression(["~warmth~", "~curiosity~", "~resonance~", "~stillness~"])
        assert len(result) <= 3

    def test_generate_lumen_expression_pipeline(self):
        result = generate_lumen_expression("settled_presence", {"E": 0.7, "I": 0.7, "S": 0.1, "V": 0.05})
        assert "shape" in result
        assert "suggested_tokens" not in result  # This is in awareness, not here
        assert "lumen_tokens" in result
        assert "eisv_tokens" in result
        assert all(t in LUMEN_TOKENS for t in result["lumen_tokens"])


class TestTrajectoryAwareness:
    def test_insufficient_data_returns_none(self):
        ta = TrajectoryAwareness(buffer_size=30)
        # Only 3 states, need 5
        for i in range(3):
            ta._buffer.append({"t": float(i), "E": 0.5, "I": 0.5, "S": 0.3, "V": 0.1})
        assert ta.get_trajectory_suggestion() is None

    def test_sufficient_data_returns_suggestion(self):
        ta = TrajectoryAwareness(buffer_size=30, seed=42)
        for i in range(10):
            ta._buffer.append({"t": float(i), "E": 0.7, "I": 0.7, "S": 0.2, "V": 0.1})
        result = ta.get_trajectory_suggestion()
        assert result is not None
        assert "shape" in result
        assert "suggested_tokens" in result
        assert "eisv_tokens" in result
        assert "trigger" in result
        assert result["shape"] == "settled_presence"

    def test_record_state_subsampling(self):
        ta = TrajectoryAwareness(buffer_size=30)
        ta._last_record_time = 0  # Reset
        ta.record_state(0.5, 0.5, 0.5, 0.5)
        assert len(ta._buffer) == 1
        # Immediately recording again should be subsampled away
        ta.record_state(0.6, 0.6, 0.6, 0.6)
        assert len(ta._buffer) == 1  # Still 1

    def test_caching(self):
        ta = TrajectoryAwareness(buffer_size=30, cache_seconds=60.0, seed=42)
        for i in range(10):
            ta._buffer.append({"t": float(i), "E": 0.7, "I": 0.7, "S": 0.2, "V": 0.1})
        r1 = ta.get_trajectory_suggestion()
        r2 = ta.get_trajectory_suggestion()
        assert r1 is r2  # Same object (cached)

    def test_current_shape_property(self):
        ta = TrajectoryAwareness(buffer_size=30, seed=42)
        assert ta.current_shape is None
        for i in range(10):
            ta._buffer.append({"t": float(i), "E": 0.7, "I": 0.7, "S": 0.2, "V": 0.1})
        ta.get_trajectory_suggestion()
        assert ta.current_shape == "settled_presence"

    def test_feedback_forwarding(self):
        ta = TrajectoryAwareness(buffer_size=30, seed=42)
        for i in range(10):
            ta._buffer.append({"t": float(i), "E": 0.7, "I": 0.7, "S": 0.2, "V": 0.1})
        ta.get_trajectory_suggestion()
        before = ta._generator.get_weights("settled_presence").copy()
        ta.record_feedback(["~stillness~"], 0.9)
        after = ta._generator.get_weights("settled_presence")
        assert after["~stillness~"] > before["~stillness~"]

    def test_bootstrap_from_history(self):
        ta = TrajectoryAwareness(buffer_size=30)
        records = [
            {"timestamp": f"2026-01-01T00:0{i}:00", "warmth": 0.7, "clarity": 0.7, "stability": 0.8, "presence": 0.5}
            for i in range(5)
        ]
        added = ta.bootstrap_from_history(records)
        assert added == 5
        assert ta.buffer_size == 5

    def test_graceful_failure(self):
        ta = TrajectoryAwareness(buffer_size=30)
        # Add corrupted data
        for i in range(10):
            ta._buffer.append({"t": float(i)})  # Missing E, I, S, V
        # Should return None, not raise
        assert ta.get_trajectory_suggestion() is None
