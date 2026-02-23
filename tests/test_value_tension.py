import pytest
import random
from datetime import datetime
from anima_mcp.value_tension import (
    ValueTensionTracker, ConflictEvent, detect_structural_conflicts
)


class TestStructuralConflicts:
    def test_detects_warmth_presence_cpu_conflict(self):
        conflicts = detect_structural_conflicts()
        pairs = [(c.dim_a, c.dim_b) for c in conflicts]
        assert ("warmth", "presence") in pairs or ("presence", "warmth") in pairs

    def test_structural_conflicts_are_permanent(self):
        c1 = detect_structural_conflicts()
        c2 = detect_structural_conflicts()
        assert len(c1) == len(c2)


class TestEnvironmentalConflicts:
    def test_detects_opposing_gradients(self):
        tracker = ValueTensionTracker()
        for i in range(20):
            raw = {"warmth": 0.5 + i * 0.02, "clarity": 0.5, "stability": 0.7 - i * 0.02, "presence": 0.5}
            tracker.observe(raw_anima=raw, action_taken=None)
        conflicts = tracker.get_active_conflicts()
        env = [c for c in conflicts if c.category == "environmental"]
        assert len(env) > 0
        dims = {(c.dim_a, c.dim_b) for c in env}
        assert ("warmth", "stability") in dims or ("stability", "warmth") in dims

    def test_ignores_noise_below_threshold(self):
        tracker = ValueTensionTracker()
        random.seed(42)
        for _ in range(50):
            raw = {d: 0.5 + random.gauss(0, 0.001) for d in ["warmth", "clarity", "stability", "presence"]}
            tracker.observe(raw_anima=raw, action_taken=None)
        conflicts = tracker.get_active_conflicts()
        env = [c for c in conflicts if c.category == "environmental"]
        assert len(env) == 0


class TestVolitionalConflicts:
    def test_detects_action_caused_conflict(self):
        tracker = ValueTensionTracker()
        for _ in range(20):
            tracker.observe({"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}, None)
        tracker.observe({"warmth": 0.7, "clarity": 0.5, "stability": 0.3, "presence": 0.5}, "led_brightness")
        conflicts = tracker.get_volitional_conflicts()
        assert len(conflicts) > 0
        assert conflicts[0].action_type == "led_brightness"


class TestConflictRates:
    def test_conflict_rate_per_action(self):
        tracker = ValueTensionTracker()
        for _ in range(20):
            tracker.observe({"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}, None)
        for _ in range(3):
            tracker.observe({"warmth": 0.7, "clarity": 0.5, "stability": 0.3, "presence": 0.5}, "led_brightness")
            tracker.observe({"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}, None)
        for _ in range(2):
            tracker.observe({"warmth": 0.55, "clarity": 0.5, "stability": 0.5, "presence": 0.5}, "led_brightness")
            tracker.observe({"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}, None)
        rate = tracker.get_conflict_rate("led_brightness")
        assert 0.0 < rate < 1.0


class TestRingBuffer:
    def test_buffer_capacity(self):
        tracker = ValueTensionTracker(buffer_size=10)
        for i in range(20):
            tracker.observe({"warmth": 0.5 + i * 0.05, "clarity": 0.5, "stability": 0.7 - i * 0.05, "presence": 0.5}, None)
        assert len(tracker._conflict_buffer) <= 10
