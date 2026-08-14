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


def test_matured_want_escalates_and_asks_for_a_response():
    """A want held past the sustain window is a standing ask.

    Originally this asserted that `is_request` meant "standing request". It does
    not — it means the ask has not been delivered yet. Maturity is the sustain
    LEVEL; the latch only distinguishes which sentence to print.
    """
    step = _analyze({"warmth": {"held_seconds": 4000.0,
                                "sustain_required_seconds": DRIVE_REQUEST_SUSTAIN_S,
                                "sustain_progress": 1.0, "is_request": True}})
    assert step["priority"] == Priority.HIGH.value
    assert step["action"] == "respond"
    assert "waiting on the question board" in step["reason"]


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


# ---------------------------------------------------------------------------
# Escalation must be level-triggered, not edge-triggered
# ---------------------------------------------------------------------------
#
# #169 escalated on `is_request`, which `ack_request` pops the instant the
# question board accepts the ask. That made HIGH reachable for roughly a minute
# per dimension per day, and made it MEAN "the board suppressed the ask" rather
# than "Lumen wants this". Worse, ack_request leaves `saturated_since` running,
# so an already-asked, still-held want rendered as
# "LOW / observe / 100% toward a request" for up to the 24h cooldown.


def test_matured_want_is_high_even_after_the_ask_was_delivered():
    """The regression: post-ack, is_request is False but the want is still held."""
    step = _analyze({"warmth": {"held_seconds": 7200.0, "sustain_progress": 1.0,
                                "is_request": False, "asked_seconds_ago": 3600.0}})
    assert step["priority"] == Priority.HIGH.value
    assert step["action"] == "respond"
    assert "asked 1h00m ago" in step["reason"]
    assert "still wanting" in step["reason"]


def test_matured_want_is_high_before_the_ask_is_delivered():
    step = _analyze({"warmth": {"held_seconds": 3700.0, "sustain_progress": 1.0,
                                "is_request": True, "asked_seconds_ago": None}})
    assert step["priority"] == Priority.HIGH.value
    assert "waiting on the question board" in step["reason"]


def test_escalation_does_not_depend_on_the_delivery_latch():
    """Same maturity, both latch states — priority must not differ."""
    pending = _analyze({"warmth": {"held_seconds": 5000.0, "sustain_progress": 1.0,
                                   "is_request": True}})
    delivered = _analyze({"warmth": {"held_seconds": 5000.0, "sustain_progress": 1.0,
                                     "is_request": False, "asked_seconds_ago": 900.0}})
    assert pending["priority"] == delivered["priority"] == Priority.HIGH.value


def test_immature_want_stays_low_even_if_the_ask_latch_is_set():
    """is_request must never by itself promote a blip."""
    step = _analyze({"warmth": {"held_seconds": 300.0, "sustain_progress": 0.083,
                                "is_request": True}})
    assert step["priority"] == Priority.LOW.value
    assert step["action"] == "observe"


def test_a_never_asked_matured_want_reads_as_standing():
    step = _analyze({"warmth": {"held_seconds": 4000.0, "sustain_progress": 1.0,
                                "is_request": False, "asked_seconds_ago": None}})
    assert step["priority"] == Priority.HIGH.value
    assert "standing want" in step["reason"]


def test_build_wants_publishes_the_ask_timestamp():
    import time as _t
    from anima_mcp.inner_life import InnerLife
    il = InnerLife.__new__(InnerLife)
    now = _t.time()
    il._saturated_since = {"warmth": now - 4000, "clarity": None,
                           "stability": None, "presence": None}
    il._active_requests = {}
    il._last_request_at = {"warmth": now - 1800, "clarity": 0.0,
                           "stability": 0.0, "presence": 0.0}
    w = il._build_wants()["warmth"]
    assert w["sustain_progress"] == 1.0
    assert 1795 < w["asked_seconds_ago"] < 1805

    il._last_request_at["warmth"] = 0.0          # never asked
    assert il._build_wants()["warmth"]["asked_seconds_ago"] is None
