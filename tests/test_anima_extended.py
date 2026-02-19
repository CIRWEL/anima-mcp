"""
Tests for anima.py — filling gaps in feeling text mappings, overall mood,
and to_dict / feeling() structure.

Run with: pytest tests/test_anima_extended.py -v
"""

import pytest
from datetime import datetime

from anima_mcp.anima import (
    Anima,
    _warmth_feeling,
    _clarity_feeling,
    _stability_feeling,
    _presence_feeling,
    _overall_mood,
)
from anima_mcp.sensors.base import SensorReadings


def _readings(**overrides):
    """Create minimal SensorReadings."""
    defaults = dict(timestamp=datetime.now())
    defaults.update(overrides)
    return SensorReadings(**defaults)


def _anima(w=0.5, c=0.5, s=0.5, p=0.5, **sensor_overrides):
    """Create Anima with defaults."""
    return Anima(warmth=w, clarity=c, stability=s, presence=p,
                 readings=_readings(**sensor_overrides))


# ==================== Feeling Text Mappings ====================

class TestFeelingTextMappings:
    """Test private _*_feeling functions across threshold boundaries."""

    def test_warmth_cold(self):
        """warmth < 0.3 → 'cold, sluggish'."""
        assert _warmth_feeling(0.1) == "cold, sluggish"
        assert _warmth_feeling(0.29) == "cold, sluggish"

    def test_warmth_comfortable(self):
        """warmth in [0.3, 0.6) → 'comfortable'."""
        assert _warmth_feeling(0.3) == "comfortable"
        assert _warmth_feeling(0.59) == "comfortable"

    def test_warmth_warm(self):
        """warmth in [0.6, 0.8) → 'warm, active'."""
        assert _warmth_feeling(0.6) == "warm, active"
        assert _warmth_feeling(0.79) == "warm, active"

    def test_warmth_hot(self):
        """warmth >= 0.8 → 'hot, intense'."""
        assert _warmth_feeling(0.8) == "hot, intense"
        assert _warmth_feeling(1.0) == "hot, intense"

    def test_clarity_dim(self):
        """clarity < 0.3 → 'dim, uncertain'."""
        assert _clarity_feeling(0.1) == "dim, uncertain"

    def test_clarity_vivid(self):
        """clarity >= 0.8 → 'vivid, sharp'."""
        assert _clarity_feeling(0.9) == "vivid, sharp"

    def test_stability_chaotic(self):
        """stability < 0.3 → 'chaotic, stressed'."""
        assert _stability_feeling(0.1) == "chaotic, stressed"

    def test_stability_calm(self):
        """stability >= 0.8 → 'calm, ordered'."""
        assert _stability_feeling(0.9) == "calm, ordered"

    def test_presence_depleted(self):
        """presence < 0.3 → 'depleted, strained'."""
        assert _presence_feeling(0.1) == "depleted, strained"

    def test_presence_abundant(self):
        """presence >= 0.8 → 'abundant, strong'."""
        assert _presence_feeling(0.9) == "abundant, strong"


# ==================== Overall Mood ====================

class TestOverallMood:
    """Test _overall_mood logic across priority branches."""

    def test_stressed_low_stability(self):
        """Low stability (< 0.3) → 'stressed'."""
        assert _overall_mood(0.5, 0.5, 0.2, 0.5) == "stressed"

    def test_stressed_low_presence(self):
        """Low presence (< 0.3) → 'stressed'."""
        assert _overall_mood(0.5, 0.5, 0.5, 0.2) == "stressed"

    def test_overheated(self):
        """High warmth (> 0.8) with stable state → 'overheated'."""
        assert _overall_mood(0.85, 0.5, 0.5, 0.5) == "overheated"

    def test_sleepy(self):
        """Low warmth (< 0.25) + low clarity (< 0.4) → 'sleepy'."""
        assert _overall_mood(0.2, 0.3, 0.5, 0.5) == "sleepy"

    def test_content_balanced(self):
        """Balanced state in content range → 'content'."""
        mood = _overall_mood(0.5, 0.6, 0.6, 0.6)
        assert mood == "content"

    def test_alert_high_clarity(self):
        """High clarity (> 0.65) with moderate warmth → 'alert'."""
        # Must not match content (warmth outside 0.30-0.70 or other condition)
        assert _overall_mood(0.75, 0.7, 0.4, 0.4) == "alert"

    def test_neutral_low_wellness(self):
        """Low overall wellness → 'neutral'."""
        # stability + presence enough to not be stressed (>= 0.3)
        # warmth 0.3, clarity 0.3 → wellness = (0.3+0.3+0.3+0.3)/4 = 0.3 < 0.35
        assert _overall_mood(0.3, 0.3, 0.3, 0.3) == "neutral"

    def test_stressed_extreme_ambient_temp(self):
        """Extreme ambient temperature → 'stressed' regardless of anima values."""
        readings = _readings(ambient_temp_c=42.0)
        assert _overall_mood(0.5, 0.5, 0.5, 0.5, readings) == "stressed"

        cold_readings = _readings(ambient_temp_c=5.0)
        assert _overall_mood(0.5, 0.5, 0.5, 0.5, cold_readings) == "stressed"


# ==================== Anima.to_dict and feeling() ====================

class TestAnimaToDict:
    """Test to_dict() and feeling() return structure."""

    def test_to_dict_has_required_keys(self):
        """to_dict returns dict with warmth, clarity, stability, presence, feeling, readings."""
        a = _anima()
        d = a.to_dict()
        for key in ("warmth", "clarity", "stability", "presence", "feeling", "readings"):
            assert key in d, f"Missing key: {key}"

    def test_feeling_dict_has_mood(self):
        """feeling() returns dict with mood key."""
        a = _anima()
        f = a.feeling()
        assert "mood" in f
        for key in ("warmth", "clarity", "stability", "presence"):
            assert key in f
        # mood should be a string
        assert isinstance(f["mood"], str)
