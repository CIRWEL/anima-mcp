"""A held want must not render identically to a passing dip.

`inner_life` holds a drive at >= DRIVE_REQUEST_THRESHOLD for
DRIVE_REQUEST_SUSTAIN_S before promoting it to a request — its own stated
boundary, "saturated for an hour = a want, not a blip". That clock was tracked
in the broker and never published, so `next_steps` saw only the drive value and
rendered every drive as `priority=LOW, action=observe`, with the magnitude
appearing solely inside a display string.

Observed live 2026-08-13 21:29: warmth saturated at 1.00 for 36 minutes —
36 minutes into becoming a standing request — reported as "low / observe".
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from anima_mcp.inner_life import DRIVE_REQUEST_SUSTAIN_S, InnerState
from anima_mcp.next_steps_advocate import Priority, _format_duration, get_advocate


DRIVES = {"warmth": 1.0, "clarity": 0.0, "stability": 0.0, "presence": 0.0}


def _analyze(wants):
    advocate = get_advocate()
    advocate._cached_steps = None
    advocate.analyze_current_state(
        anima={"warmth": 0.39, "clarity": 0.71, "stability": 0.80, "presence": 0.75},
        readings={},
        eisv={"E": 0.32, "I": 0.71, "S": 0.20, "V": -0.40},
        display_available=True,
        brain_hat_available=True,
        unitares_connected=True,
        drives=DRIVES,
        strongest_drive="warmth",
        wants=wants,
    )
    steps = [s for s in advocate.get_next_steps_summary()["all_steps"]
             if str(s["feeling"]).startswith("drive:")]
    assert steps, "the drive step disappeared"
    return steps[0]


def test_short_hold_stays_low_the_system_calls_it_a_blip():
    step = _analyze({"warmth": {"held_seconds": 120.0,
                                "sustain_required_seconds": DRIVE_REQUEST_SUSTAIN_S,
                                "sustain_progress": 0.033, "is_request": False}})
    assert step["priority"] == Priority.LOW.value
    assert step["action"] == "observe"


def test_hold_duration_is_surfaced():
    """36 minutes of wanting should be legible as 36 minutes."""
    step = _analyze({"warmth": {"held_seconds": 2160.0,
                                "sustain_required_seconds": DRIVE_REQUEST_SUSTAIN_S,
                                "sustain_progress": 0.6, "is_request": False}})
    assert "36m" in step["feeling"]
    assert "60%" in step["reason"] or "toward a request" in step["reason"]


def test_promoted_request_escalates_and_asks_for_a_response():
    """Once inner_life calls it a request, it is a standing ask."""
    step = _analyze({"warmth": {"held_seconds": 4000.0,
                                "sustain_required_seconds": DRIVE_REQUEST_SUSTAIN_S,
                                "sustain_progress": 1.0, "is_request": True}})
    assert step["priority"] == Priority.HIGH.value
    assert step["action"] == "respond"
    assert "standing request" in step["reason"]


def test_a_held_want_outranks_a_passing_dip():
    """The regression that mattered: these used to be indistinguishable."""
    blip = _analyze({"warmth": {"held_seconds": 60.0, "sustain_progress": 0.017,
                                "is_request": False}})
    standing = _analyze({"warmth": {"held_seconds": 4000.0, "sustain_progress": 1.0,
                                    "is_request": True}})
    assert blip["priority"] != standing["priority"]


def test_absent_wants_block_degrades_to_previous_behaviour():
    """Callers predating the field, and restored snapshots, must still work."""
    step = _analyze(None)
    assert step["priority"] == Priority.LOW.value
    assert step["action"] == "observe"
    assert "held" not in step["feeling"]


def test_inner_state_publishes_wants_and_defaults_empty():
    state = InnerState(
        raw={}, mood={}, deltas={}, temperament={},
        mood_vs_temperament={}, drives=DRIVES, strongest_drive="warmth",
    )
    assert state.wants == {}
    assert state.to_dict()["wants"] == {}


def test_format_duration_reads_as_time_not_seconds():
    assert _format_duration(0) == "0m"
    assert _format_duration(2160) == "36m"
    assert _format_duration(3600) == "1h00m"
    assert _format_duration(5400) == "1h30m"
