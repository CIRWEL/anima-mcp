"""Focused tests for process-state helpers."""

from datetime import datetime
from unittest.mock import patch

import pytest

from anima_mcp.messages import QUESTION_EXPIRY_SECONDS
from anima_mcp.server_state import (
    SELF_ANSWER_MIN_QUESTION_AGE_SECONDS,
    anima_from_dict,
    is_broker_running,
    readings_from_dict,
)


def test_broker_probe_matches_installed_console_entrypoint():
    """Production runs ``anima-creature``, not ``stable_creature.py``."""
    with patch("anima_mcp.server_state.subprocess.run") as run:
        run.return_value.returncode = 0

        assert is_broker_running() is True

    assert run.call_args.args[0] == [
        "pgrep",
        "-f",
        "anima-creature|anima_mcp.stable_creature",
    ]


def test_readings_round_trip_preserves_light_capture_provenance():
    observed_at = datetime(2026, 8, 22, 23, 37, 25)
    readings = readings_from_dict(
        {
            "timestamp": "2026-08-22T23:37:26",
            "light_lux": 136.1088,
            "light_observed_at": observed_at.isoformat(),
            "light_observed_precision_seconds": 1.0,
            "led_brightness": 0.08,
        }
    )

    assert readings.light_observed_at == observed_at
    assert readings.light_observed_precision_seconds == 1.0
    assert readings.led_brightness == 0.08


def test_readings_round_trip_preserves_hearing_and_power_diagnostics():
    readings = readings_from_dict(
        {
            "timestamp": "2026-08-23T19:43:07",
            "hearing_available": True,
            "sound_level": 0.17,
            "throttle_bits": 0x50005,
            "undervoltage_now": True,
            "throttled_now": False,
            "freq_capped_now": True,
            "undervoltage_occurred": True,
        }
    )

    assert readings.hearing_available is True
    assert readings.sound_level == 0.17
    assert readings.throttle_bits == 0x50005
    assert readings.undervoltage_now is True
    assert readings.throttled_now is False
    assert readings.freq_capped_now is True
    assert readings.undervoltage_occurred is True


def test_anima_round_trip_preserves_clarity_attribution():
    readings = readings_from_dict({"timestamp": "2026-08-24T00:00:00"})
    attribution = {
        "schema": "anima.clarity_attribution.v1",
        "components": {"sensor_coverage": {"value": 1.0}},
    }

    anima = anima_from_dict(
        {
            "warmth": 0.4,
            "clarity": 0.5,
            "stability": 0.6,
            "presence": 0.7,
            "clarity_attribution": attribution,
        },
        readings,
    )

    assert anima.clarity_attribution == attribution
    assert anima.clarity_attribution is not attribution


def test_anima_rejects_non_object_clarity_attribution():
    readings = readings_from_dict({"timestamp": "2026-08-24T00:00:00"})

    with pytest.raises(ValueError, match="clarity_attribution"):
        anima_from_dict(
            {
                "warmth": 0.4,
                "clarity": 0.5,
                "stability": 0.6,
                "presence": 0.7,
                "clarity_attribution": "opaque",
            },
            readings,
        )


def test_self_answer_gate_fires_before_the_expiry_stamp():
    """Ordering invariant, not a taste preference.

    At 21_600 (6h) against a 14_400 (4h) expiry, every question Lumen asked
    was stamped ``expired`` before it could self-answer — 6 of 6 on
    2026-08-24/25, each answered at ~6.0h — so the status carried no
    information for anyone reading the Q&A ledger.
    """
    assert SELF_ANSWER_MIN_QUESTION_AGE_SECONDS < QUESTION_EXPIRY_SECONDS


def test_self_answer_gate_still_leaves_a_settling_period():
    """Not zero: a question should rest before Lumen answers it."""
    assert SELF_ANSWER_MIN_QUESTION_AGE_SECONDS >= 3600
