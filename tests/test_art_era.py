"""Tests for display/art_era.py — EraState dataclass and ArtEra protocol."""

from anima_mcp.display.art_era import EraState


class TestEraStateDefaults:
    def test_default_gesture(self):
        state = EraState()
        assert state.gesture == "dot"

    def test_default_gesture_remaining(self):
        state = EraState()
        assert state.gesture_remaining == 0

    def test_custom_fields(self):
        state = EraState(gesture="stroke", gesture_remaining=15)
        assert state.gesture == "stroke"
        assert state.gesture_remaining == 15


class TestEraStateIntentionality:
    def test_baseline_no_remaining(self):
        state = EraState(gesture_remaining=0)
        assert state.intentionality() == 0.1

    def test_small_remaining(self):
        state = EraState(gesture_remaining=5)
        result = state.intentionality()
        expected = 0.1 + (5 / 20.0 * 0.3)  # 0.1 + 0.075 = 0.175
        assert abs(result - expected) < 1e-9

    def test_exactly_20_remaining(self):
        state = EraState(gesture_remaining=20)
        result = state.intentionality()
        expected = 0.1 + min(0.3, 20 / 20.0 * 0.3)  # 0.1 + 0.3 = 0.4
        assert abs(result - expected) < 1e-9

    def test_large_remaining_capped(self):
        state = EraState(gesture_remaining=100)
        result = state.intentionality()
        # min(0.3, 100/20*0.3) = min(0.3, 1.5) = 0.3 → total 0.4
        assert abs(result - 0.4) < 1e-9

    def test_very_large_remaining_total_capped(self):
        # Even with huge remaining, min(1.0, I) caps at 1.0
        state = EraState(gesture_remaining=1000)
        result = state.intentionality()
        assert result <= 1.0

    def test_negative_remaining_treated_as_zero(self):
        state = EraState(gesture_remaining=-5)
        result = state.intentionality()
        assert result == 0.1  # -5 > 0 is False, so no contribution


class TestEraStateGestures:
    def test_default_gestures(self):
        state = EraState()
        assert state.gestures() == ["dot"]
