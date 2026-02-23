"""Tests for ValueTensionTracker integration with agency action selection."""

import pytest
from anima_mcp.value_tension import ValueTensionTracker


class TestTensionAgencyIntegration:
    def test_conflict_rate_discounts_action_value(self):
        tracker = ValueTensionTracker()
        # Establish baseline
        for _ in range(20):
            tracker.observe({"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}, None)
        # Actions that cause warmth-stability conflicts
        for _ in range(5):
            tracker.observe({"warmth": 0.7, "clarity": 0.5, "stability": 0.3, "presence": 0.5}, "led_brightness")
            tracker.observe({"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}, None)

        rate = tracker.get_conflict_rate("led_brightness")
        discount = 0.9 ** rate
        assert discount < 1.0  # Should reduce expected value

    def test_zero_conflict_rate_gives_no_discount(self):
        tracker = ValueTensionTracker()
        # Actions that cause no conflict (all dimensions move together)
        for _ in range(10):
            tracker.observe({"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}, None)
            tracker.observe({"warmth": 0.55, "clarity": 0.55, "stability": 0.55, "presence": 0.55}, "focus_attention")

        rate = tracker.get_conflict_rate("focus_attention")
        discount = 0.9 ** rate
        assert discount == 1.0  # No conflicts => no discount

    def test_unknown_action_gives_no_discount(self):
        tracker = ValueTensionTracker()
        rate = tracker.get_conflict_rate("never_seen_action")
        discount = 0.9 ** rate
        assert discount == 1.0  # Unknown action => rate 0.0 => discount 1.0

    def test_conflict_rates_dict_construction(self):
        """Test the pattern used in server.py to build conflict_rates dict."""
        tracker = ValueTensionTracker()
        # Establish baseline
        for _ in range(20):
            tracker.observe({"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}, None)
        # Create conflicts for one action but not another
        for _ in range(5):
            tracker.observe({"warmth": 0.7, "clarity": 0.5, "stability": 0.3, "presence": 0.5}, "led_brightness")
            tracker.observe({"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}, None)
        for _ in range(5):
            tracker.observe({"warmth": 0.55, "clarity": 0.55, "stability": 0.55, "presence": 0.55}, "focus_attention")
            tracker.observe({"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}, None)

        # Build conflict_rates as server.py would
        action_types = ["led_brightness", "focus_attention", "ask_question"]
        conflict_rates = {}
        for action_key in action_types:
            rate = tracker.get_conflict_rate(action_key)
            if rate > 0:
                conflict_rates[action_key] = rate

        assert "led_brightness" in conflict_rates
        assert conflict_rates["led_brightness"] > 0
        # focus_attention had no conflicts (all dims moved same direction)
        assert conflict_rates.get("focus_attention", 0) == 0
        # ask_question was never observed
        assert "ask_question" not in conflict_rates

    def test_discount_formula_correctness(self):
        """Verify the 0.9**rate discount formula used in agency."""
        # Rate of 0.0 => discount 1.0 (no change)
        assert 0.9 ** 0.0 == 1.0
        # Rate of 0.5 => discount ~0.9487
        assert 0.9 ** 0.5 == pytest.approx(0.9487, abs=0.001)
        # Rate of 1.0 => discount 0.9 (maximum single-conflict discount)
        assert 0.9 ** 1.0 == 0.9
