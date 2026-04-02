"""Tests for inner life drive system — mood relief dampening."""

from unittest.mock import MagicMock

from anima_mcp.inner_life import InnerLife


def _make_anima(warmth=0.5, clarity=0.5, stability=0.5, presence=0.5):
    a = MagicMock()
    a.warmth = warmth
    a.clarity = clarity
    a.stability = stability
    a.presence = presence
    return a


def test_drive_dampened_when_mood_above_comfort():
    """Drive accumulation slows when current mood exceeds comfort threshold."""
    il = InnerLife.__new__(InnerLife)
    il._temperament = {"warmth": 0.30, "clarity": 0.70, "stability": 0.70, "presence": 0.70}
    il._drives = {"warmth": 0.0, "clarity": 0.0, "stability": 0.0, "presence": 0.0}
    il._prev_drives = dict(il._drives)
    il._crossed_thresholds = {"warmth": 0.0, "clarity": 0.0, "stability": 0.0, "presence": 0.0}
    il._pending_events = []
    il._last_save = 0.0

    # Mood warmth well above comfort (0.40) — should dampen accumulation
    anima_high_mood = _make_anima(warmth=0.60)
    il.update(anima_high_mood, anima_high_mood)
    drive_dampened = il._drives["warmth"]

    # Reset and test without dampening (mood below comfort)
    il._drives = {"warmth": 0.0, "clarity": 0.0, "stability": 0.0, "presence": 0.0}
    il._temperament = {"warmth": 0.30, "clarity": 0.70, "stability": 0.70, "presence": 0.70}
    anima_low_mood = _make_anima(warmth=0.30)
    il.update(anima_low_mood, anima_low_mood)
    drive_undampened = il._drives["warmth"]

    assert drive_dampened < drive_undampened, (
        f"Dampened ({drive_dampened}) should be less than undampened ({drive_undampened})"
    )


def test_drive_still_accumulates_when_dampened():
    """Drive doesn't stop entirely — dampening floors at 10% rate."""
    il = InnerLife.__new__(InnerLife)
    il._temperament = {"warmth": 0.30, "clarity": 0.70, "stability": 0.70, "presence": 0.70}
    il._drives = {"warmth": 0.5, "clarity": 0.0, "stability": 0.0, "presence": 0.0}
    il._prev_drives = dict(il._drives)
    il._crossed_thresholds = {"warmth": 0.0, "clarity": 0.0, "stability": 0.0, "presence": 0.0}
    il._pending_events = []
    il._last_save = 0.0

    # Even with high mood, drive should still inch up (10% floor)
    anima = _make_anima(warmth=0.80)
    il.update(anima, anima)

    assert il._drives["warmth"] > 0.5, (
        f"Drive should still accumulate (got {il._drives['warmth']})"
    )


def test_no_dampening_when_mood_below_comfort():
    """Mood below comfort threshold — no dampening, full accumulation rate."""
    il = InnerLife.__new__(InnerLife)
    il._temperament = {"warmth": 0.30, "clarity": 0.70, "stability": 0.70, "presence": 0.70}
    il._drives = {"warmth": 0.0, "clarity": 0.0, "stability": 0.0, "presence": 0.0}
    il._prev_drives = dict(il._drives)
    il._crossed_thresholds = {"warmth": 0.0, "clarity": 0.0, "stability": 0.0, "presence": 0.0}
    il._pending_events = []
    il._last_save = 0.0

    # Mood at 0.35 — below comfort (0.40), no dampening
    anima = _make_anima(warmth=0.35)
    il.update(anima, anima)
    drive_after = il._drives["warmth"]

    # Full rate: 0.003 * (1 + 0.10*2) = 0.0036
    assert drive_after > 0.003, f"Expected full accumulation, got {drive_after}"


def test_saturated_drive_decays_when_mood_good():
    """A saturated drive (1.0) with mood above comfort should not keep climbing."""
    il = InnerLife.__new__(InnerLife)
    il._temperament = {"warmth": 0.35, "clarity": 0.70, "stability": 0.70, "presence": 0.70}
    il._drives = {"warmth": 1.0, "clarity": 0.0, "stability": 0.0, "presence": 0.0}
    il._prev_drives = dict(il._drives)
    il._crossed_thresholds = {"warmth": 0.5, "clarity": 0.0, "stability": 0.0, "presence": 0.0}
    il._pending_events = []
    il._last_save = 0.0

    # Run 50 ticks with high mood — temperament should rise, drive should eventually decay
    anima = _make_anima(warmth=0.60)
    for _ in range(50):
        il.update(anima, anima)

    assert il._drives["warmth"] < 1.0, (
        f"Drive should have started decaying after 50 ticks of good mood, got {il._drives['warmth']}"
    )
