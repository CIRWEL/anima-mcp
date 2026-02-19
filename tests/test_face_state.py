"""
Tests for display/face.py — face expression mapping from anima state.

Covers:
  - Mouth priority branches (distress, cold, sleepy, overheated, curious, content, neutral)
  - Eye state coordination with mouth (WIDE only with OPEN, SQUINT on distress, etc.)
  - Color tint interpolation bands
  - Blink frequency and duration formulas
  - face_to_ascii fallback
"""

import pytest
from datetime import datetime

from anima_mcp.anima import Anima
from anima_mcp.sensors.base import SensorReadings
from anima_mcp.display.face import (
    derive_face_state, face_to_ascii, FaceState,
    EyeState, MouthState,
    WARMTH_FREEZING, WARMTH_COLD, WARMTH_COOL, WARMTH_COMFORTABLE, WARMTH_HOT,
    CLARITY_FOGGY, CLARITY_DROWSY, CLARITY_CLEAR, CLARITY_ALERT,
    STABILITY_DISTRESSED, STABILITY_UNSTABLE, STABILITY_STABLE, STABILITY_GROUNDED,
    WELLNESS_GOOD, WELLNESS_OK,
)


def make_anima(warmth=0.5, clarity=0.5, stability=0.5, presence=0.5, **kwargs):
    """Create Anima with defaults and optional sensor overrides."""
    readings = SensorReadings(timestamp=datetime.now(), **kwargs)
    return Anima(warmth=warmth, clarity=clarity,
                 stability=stability, presence=presence, readings=readings)


# ==================== Mouth Priority ====================

class TestMouthPriority:
    """Test mouth state priority branches."""

    def test_priority1_distress_low_stability(self):
        """Low stability → FROWN (Priority 1)."""
        face = derive_face_state(make_anima(stability=0.2, warmth=0.6, clarity=0.6, presence=0.6))
        assert face.mouth == MouthState.FROWN

    def test_priority1_distress_low_presence(self):
        """Low presence → FROWN (Priority 1)."""
        face = derive_face_state(make_anima(presence=0.2, warmth=0.6, clarity=0.6, stability=0.6))
        assert face.mouth == MouthState.FROWN

    def test_priority2_cold_low_wellness(self):
        """Cold warmth + low wellness → FLAT (Priority 2)."""
        face = derive_face_state(make_anima(warmth=0.2, clarity=0.3, stability=0.4, presence=0.4))
        # wellness = (0.2+0.3+0.4+0.4)/4 = 0.325 < WELLNESS_LOW (0.40)
        assert face.mouth == MouthState.FLAT

    def test_priority2_cold_ok_wellness(self):
        """Cold warmth + OK wellness → NEUTRAL (Priority 2)."""
        face = derive_face_state(make_anima(warmth=0.3, clarity=0.5, stability=0.6, presence=0.6))
        # wellness = (0.3+0.5+0.6+0.6)/4 = 0.5 >= WELLNESS_LOW
        assert face.mouth == MouthState.NEUTRAL

    def test_priority4_overheated(self):
        """Very high warmth → NEUTRAL (Priority 4, overheated)."""
        face = derive_face_state(make_anima(warmth=0.85, clarity=0.5, stability=0.5, presence=0.5))
        assert face.mouth == MouthState.NEUTRAL

    def test_priority5_curious(self):
        """High clarity + stable + warm enough → OPEN (Priority 5)."""
        face = derive_face_state(make_anima(
            warmth=0.5, clarity=0.7, stability=0.5, presence=0.5,
        ))
        assert face.mouth == MouthState.OPEN

    def test_priority6_content_smile(self):
        """High wellness + grounded + clear → SMILE (Priority 6)."""
        face = derive_face_state(make_anima(
            warmth=0.65, clarity=0.55, stability=0.6, presence=0.6,
        ))
        # wellness = (0.65+0.55+0.6+0.6)/4 = 0.6 > WELLNESS_GOOD
        # warmth > WARMTH_COOL, stability > STABILITY_GROUNDED, clarity > CLARITY_CLEAR
        assert face.mouth == MouthState.SMILE

    def test_priority7_neutral_fallthrough(self):
        """Moderate values not matching higher priorities → NEUTRAL."""
        face = derive_face_state(make_anima(
            warmth=0.42, clarity=0.42, stability=0.42, presence=0.42,
        ))
        # Not distressed, not cold, not sleepy, not overheated
        # clarity not alert, wellness ~0.42 not good enough for content
        assert face.mouth == MouthState.NEUTRAL


# ==================== Eye Coordination ====================

class TestEyeCoordination:
    """Test eye state coordination with mouth."""

    def test_wide_eyes_only_with_open_mouth(self):
        """WIDE eyes require OPEN mouth (curiosity)."""
        face = derive_face_state(make_anima(
            warmth=0.5, clarity=0.75, stability=0.55, presence=0.6,
        ))
        # This should trigger Priority 5 (curious) → OPEN mouth
        assert face.mouth == MouthState.OPEN
        # With high clarity → high eye_openness → WIDE eyes
        assert face.eyes == EyeState.WIDE

    def test_no_wide_eyes_with_smile(self):
        """Content creature → NORMAL eyes, not WIDE, even with high clarity."""
        face = derive_face_state(make_anima(
            warmth=0.7, clarity=0.55, stability=0.7, presence=0.7,
        ))
        # SMILE mouth (content), not OPEN
        assert face.mouth == MouthState.SMILE
        assert face.eyes != EyeState.WIDE
        assert face.eyes == EyeState.NORMAL

    def test_squint_on_extreme_distress(self):
        """Very low stability → SQUINT eyes."""
        face = derive_face_state(make_anima(
            stability=0.15, warmth=0.5, clarity=0.5, presence=0.5,
        ))
        assert face.eyes == EyeState.SQUINT

    def test_closed_on_freezing(self):
        """Very low warmth → CLOSED eyes."""
        face = derive_face_state(make_anima(
            warmth=0.1, clarity=0.5, stability=0.5, presence=0.5,
        ))
        assert face.eyes == EyeState.CLOSED
        assert face.eye_openness == pytest.approx(0.1)

    def test_droopy_on_cold(self):
        """Cold warmth (below WARMTH_COLD) → DROOPY eyes."""
        face = derive_face_state(make_anima(
            warmth=0.3, clarity=0.4, stability=0.5, presence=0.5,
        ))
        assert face.eyes == EyeState.DROOPY


# ==================== Color Tint ====================

class TestColorTint:
    """Test color tint interpolation bands."""

    def test_cool_range(self):
        """Low warmth → cool teal tint."""
        face = derive_face_state(make_anima(warmth=0.15, stability=0.5, presence=0.5))
        r, g, b = face.tint
        assert b > r  # Blue/teal dominant

    def test_warm_range(self):
        """High warmth → warm coral/peach tint."""
        face = derive_face_state(make_anima(warmth=0.85, stability=0.5, presence=0.5))
        r, g, b = face.tint
        assert r == 255  # Red maxed
        assert b < 130

    def test_tint_is_valid_rgb(self):
        """Tint is always a valid RGB triplet."""
        for warmth in [0.0, 0.1, 0.3, 0.45, 0.6, 0.75, 0.9, 1.0]:
            face = derive_face_state(make_anima(warmth=warmth, stability=0.5, presence=0.5))
            r, g, b = face.tint
            assert 0 <= r <= 255
            assert 0 <= g <= 255
            assert 0 <= b <= 255


# ==================== Blink Formula ====================

class TestBlinkFormula:
    """Test blink frequency and duration."""

    def test_drowsy_longer_intervals(self):
        """Low clarity → longer blink intervals (drowsy rhythm)."""
        drowsy = derive_face_state(make_anima(clarity=0.2, stability=0.5, warmth=0.5, presence=0.5))
        alert = derive_face_state(make_anima(clarity=0.7, stability=0.5, warmth=0.5, presence=0.5))
        assert drowsy.blink_frequency > alert.blink_frequency

    def test_blink_frequency_clamped(self):
        """Blink frequency stays within [2.0, 6.0] at extremes."""
        for clarity in [0.0, 0.5, 1.0]:
            for stability in [0.0, 0.5, 1.0]:
                face = derive_face_state(make_anima(
                    clarity=clarity, stability=stability, warmth=0.5, presence=0.5
                ))
                assert 2.0 <= face.blink_frequency <= 6.0


# ==================== face_to_ascii ====================

class TestFaceToAscii:
    """Test ASCII face lookup."""

    def test_known_key_returns_art(self):
        """Known eye/mouth combo returns ASCII art."""
        state = FaceState(
            eyes=EyeState.NORMAL, mouth=MouthState.SMILE,
            tint=(255, 200, 150), eye_openness=0.6,
        )
        art = face_to_ascii(state)
        assert "◯" in art  # Normal eyes

    def test_unknown_key_falls_back(self):
        """Unknown combo falls back to normal/neutral."""
        state = FaceState(
            eyes=EyeState.DROOPY, mouth=MouthState.SMILE,
            tint=(255, 200, 150), eye_openness=0.5,
        )
        art = face_to_ascii(state)
        assert isinstance(art, str)
        assert len(art) > 0
