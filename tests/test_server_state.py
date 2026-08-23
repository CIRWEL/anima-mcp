"""Focused tests for process-state helpers."""

from datetime import datetime
from unittest.mock import patch

from anima_mcp.server_state import is_broker_running, readings_from_dict


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
