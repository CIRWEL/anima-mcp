"""Focused tests for process-state helpers."""

from unittest.mock import patch

from anima_mcp.server_state import is_broker_running


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
