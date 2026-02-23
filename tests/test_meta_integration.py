"""Tests for meta-learning integration into the server loop."""

import pytest
from anima_mcp.preferences import compute_trajectory_health, meta_learning_update


class TestMetaLearningIntegration:
    def test_full_cycle_preserves_invariants(self):
        """After meta-learning update, conservation and floors hold."""
        weights = {"warmth": 1.2, "clarity": 0.8, "stability": 1.0, "presence": 1.0}
        correlations = {"warmth": 0.3, "clarity": -0.5, "stability": 0.1, "presence": -0.2}
        new = meta_learning_update(weights, correlations)
        assert abs(sum(new.values()) - 4.0) < 0.01
        assert all(w >= 0.3 for w in new.values())

    def test_trajectory_health_with_real_data_range(self):
        """Health computation works with realistic input ranges."""
        h = compute_trajectory_health(
            satisfaction_history=[0.4 + i * 0.01 for i in range(100)],
            action_efficacy=0.6,
            prediction_accuracy_trend=0.05,
        )
        assert 0.0 <= h <= 1.0
