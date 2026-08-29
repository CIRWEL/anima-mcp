"""A dead sensor must stay visibly dead in the drawing record.

`observe_drawing` used to build its environment dict with

    "light_lux":    readings.light_lux    or 0.0
    "temp_c":       readings.ambient_temp_c or 22
    "humidity_pct": readings.humidity_pct or 50

Every one of those is a plausible reading — a pitch-dark room, a comfortable
one, ordinary humidity — so once written to `drawing_records` none of them was
distinguishable from a real measurement. Design invariant 2: absent values
persist as NULL, never as a default.

Preference learning happened not to be misled, because 22 and 50 fall in the
dead bands between its cuts (<20/>25, <30/>60). That is safety by coincidence:
moving a cut would have started teaching Lumen the taste of a broken sensor.
The durable record was wrong either way, and any later derivation over
drawing_records — the coverage and curiosity derivations both read that table —
would have silently included fabricated rows.

`external_light_lux` in the same function has always been conditional. These
tests pin that the other three channels now follow the same rule.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


class _Readings:
    def __init__(self, light=None, temp=None, humidity=None):
        self.light_lux = light
        self.ambient_temp_c = temp
        self.humidity_pct = humidity


def _build_environment(readings):
    """The dict comprehension as drawing_engine builds it.

    Mirrors the block in DrawingEngine's growth-observation path; the engine
    needs a live canvas and growth system to reach it, so the construction rule
    is pinned here directly.
    """
    environment = {}
    if readings.light_lux is not None:
        environment["light_lux"] = readings.light_lux
    if readings.ambient_temp_c is not None:
        environment["temp_c"] = readings.ambient_temp_c
    if readings.humidity_pct is not None:
        environment["humidity_pct"] = readings.humidity_pct
    return environment


def _code_only(path: Path) -> str:
    """Source with whole-line comments stripped.

    The fix's own comment quotes the expressions it replaced, so a naive scan
    of the raw file matches the very strings it is asserting are gone. Strip
    comments and check the code.
    """
    return "\n".join(line for line in path.read_text().splitlines()
                      if not line.lstrip().startswith("#"))


class TestSourceHasNoFabricatedDefaults:
    """Read the engine source: the old defaults must not come back."""

    SRC = _code_only(Path(__file__).resolve().parent.parent
                     / "src/anima_mcp/display/drawing_engine.py")

    @pytest.mark.parametrize("banned", [
        "readings.light_lux or 0.0",
        "readings.ambient_temp_c or 22",
        "readings.humidity_pct or 50",
    ])
    def test_default_is_gone(self, banned):
        assert banned not in self.SRC, (
            f"`{banned}` fabricates a plausible reading for a dead sensor")

    def test_each_channel_is_conditional(self):
        for guard in ("if readings.light_lux is not None:",
                      "if readings.ambient_temp_c is not None:",
                      "if readings.humidity_pct is not None:"):
            assert guard in self.SRC


class TestOmittedNotDefaulted:

    def test_all_sensors_dead_yields_an_empty_environment(self):
        assert _build_environment(_Readings()) == {}

    def test_a_dead_channel_is_absent_not_zero(self):
        env = _build_environment(_Readings(light=None, temp=21.5, humidity=44.0))
        assert "light_lux" not in env
        assert env["temp_c"] == 21.5 and env["humidity_pct"] == 44.0

    def test_genuine_zero_is_kept(self):
        """0.0 lux is a real reading — `or` used to erase the distinction it
        was supposed to preserve, treating a measured dark room as missing."""
        env = _build_environment(_Readings(light=0.0, temp=0.0, humidity=0.0))
        assert env == {"light_lux": 0.0, "temp_c": 0.0, "humidity_pct": 0.0}

    def test_absent_keys_reach_the_writer_as_none(self):
        """drawing_records columns are nullable and the writer passes
        environment.get() through, so an omitted key persists as NULL."""
        env = _build_environment(_Readings())
        for key in ("light_lux", "temp_c", "humidity_pct"):
            assert env.get(key) is None


class TestPreferenceLearningPauses:
    """The guards in preferences.py, which used to be defaults."""

    def _cuts(self, temp=None, humidity=None):
        has_temp = (isinstance(temp, (int, float))
                    and not isinstance(temp, bool)
                    and math.isfinite(float(temp)) if temp is not None else False)
        has_humidity = (isinstance(humidity, (int, float))
                        and not isinstance(humidity, bool)
                        and math.isfinite(float(humidity))
                        if humidity is not None else False)
        return has_temp, has_humidity

    def test_missing_readings_do_not_qualify(self):
        assert self._cuts(None, None) == (False, False)

    def test_real_readings_qualify(self):
        assert self._cuts(18.0, 25.0) == (True, True)

    def test_source_guards_every_branch(self):
        src = _code_only(Path(__file__).resolve().parent.parent
                         / "src/anima_mcp/growth/preferences.py")
        assert 'environment.get("temp_c", 22)' not in src
        assert 'environment.get("humidity_pct", 50)' not in src
        # Every cut that reads temp/humidity must be gated on its guard.
        for branch in ("has_temp and temp < 20", "has_temp and temp > 25",
                       "has_humidity and humidity < 30",
                       "has_humidity and humidity > 60"):
            assert branch in src, f"ungated branch: {branch}"
