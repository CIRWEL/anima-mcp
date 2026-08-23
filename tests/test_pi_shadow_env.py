"""PiSensors shadow-env mode (Phase-1 Elixir broker cutover).

With ANIMA_ENV_SENSORS_FROM_SHM set, PiSensors never opens I2C — the Elixir
broker owns the AHT20/VEML7700/BMP280 and publishes their channels to a shadow
SHM file. That also makes PiSensors constructible off-Pi, so these tests run
on any host.
"""
import json
from datetime import datetime, timedelta

import pytest

from anima_mcp.sensors.pi import PiSensors


ENV = {
    "ambient_temp_c": 24.5,
    "humidity_pct": 23.1,
    "light_lux": 60.0,
    "pressure_hpa": 819.9,
    "pressure_temp_c": 29.8,
}


@pytest.fixture
def shadow_file(tmp_path, monkeypatch):
    """Returns a writer(readings, age_seconds=0) that (re)writes the shadow
    envelope in the Elixir broker's format and points the env var at it."""
    path = tmp_path / "anima_state.shadow.json"
    monkeypatch.setenv("ANIMA_ENV_SENSORS_FROM_SHM", str(path))

    def write(readings, *, age_seconds=0.0, include_light_provenance=True):
        readings = dict(readings)
        if include_light_provenance and readings.get("light_lux") is not None:
            completed_at = datetime.now() - timedelta(seconds=age_seconds)
            readings.setdefault(
                "light_observed_at",
                (completed_at - timedelta(seconds=0.52)).isoformat(),
            )
            readings.setdefault("light_observed_precision_seconds", 0.52)
        envelope = {
            "updated_at": (
                datetime.now() - timedelta(seconds=age_seconds)
            ).isoformat(),
            "pid": "test",
            "data": {"readings": readings},
        }
        path.write_text(json.dumps(envelope))
        return path

    return write


def test_shadow_mode_never_opens_i2c(shadow_file):
    shadow_file(ENV)
    s = PiSensors()
    assert s._i2c is None
    assert s._aht is None
    assert s._light_sensor is None
    assert s._bmp280 is None


def test_shadow_mode_reads_env_channels(shadow_file):
    shadow_file(ENV)
    s = PiSensors()
    r = s.read()
    assert r.ambient_temp_c == 24.5
    assert r.humidity_pct == 23.1
    assert r.light_lux == 60.0  # first read seeds the EMA
    assert r.light_observed_at is not None
    assert r.light_observed_precision_seconds == 0.52
    assert r.pressure_hpa == 819.9
    assert r.pressure_temp_c == 29.8


def test_shadow_lux_ema_matches_i2c_path(shadow_file):
    shadow_file(ENV)
    s = PiSensors()
    s.read()
    shadow_file({**ENV, "light_lux": 100.0})
    r = s.read()
    assert r.light_lux == pytest.approx(0.8 * 60.0 + 0.2 * 100.0)


def test_shadow_lux_ema_advances_once_per_physical_capture(shadow_file):
    shadow_file(ENV)
    sensors = PiSensors()
    assert sensors.read().light_lux == 60.0

    # A new capture advances the EMA once. Re-reading the same SHM envelope
    # must return the same measurement rather than smoothing it a second time.
    shadow_file({**ENV, "light_lux": 100.0})
    first = sensors.read()
    replay = sensors.read()

    assert first.light_lux == pytest.approx(68.0)
    assert replay.light_lux == pytest.approx(first.light_lux)
    assert replay.light_observed_at == first.light_observed_at


def test_shadow_uses_sensor_capture_window_not_envelope_flush(shadow_file):
    path = shadow_file(ENV)
    envelope = json.loads(path.read_text())
    window_start = datetime.now() - timedelta(seconds=0.52)
    envelope["updated_at"] = (window_start + timedelta(seconds=1.7)).isoformat()
    envelope["data"]["readings"]["light_observed_at"] = window_start.isoformat()
    envelope["data"]["readings"]["light_observed_precision_seconds"] = 0.52
    path.write_text(json.dumps(envelope))

    readings = PiSensors().read()
    assert readings.light_observed_at == window_start
    assert readings.light_observed_precision_seconds == 0.52


def test_shadow_without_sensor_capture_provenance_cannot_train_residual(shadow_file):
    shadow_file(ENV, include_light_provenance=False)

    readings = PiSensors().read()

    assert readings.light_lux == 60.0
    assert readings.light_observed_at is None
    assert readings.light_observed_precision_seconds is None


def test_stale_sensor_capture_provenance_cannot_train_fresh_envelope(shadow_file):
    path = shadow_file(ENV)
    envelope = json.loads(path.read_text())
    envelope["data"]["readings"]["light_observed_at"] = (
        datetime.now() - timedelta(seconds=120.52)
    ).isoformat()
    path.write_text(json.dumps(envelope))

    readings = PiSensors().read()

    assert readings.light_lux == 60.0
    assert readings.light_observed_at is None
    assert readings.light_observed_precision_seconds is None


def test_stale_shadow_degrades_to_none(shadow_file):
    shadow_file(ENV, age_seconds=120.0)
    s = PiSensors()
    r = s.read()
    assert r.ambient_temp_c is None
    assert r.humidity_pct is None
    assert r.light_lux is None
    assert r.pressure_hpa is None
    assert r.pressure_temp_c is None


def test_missing_shadow_file_degrades_to_none(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "ANIMA_ENV_SENSORS_FROM_SHM", str(tmp_path / "does_not_exist.json")
    )
    s = PiSensors()
    r = s.read()
    assert r.ambient_temp_c is None
    assert r.humidity_pct is None


def test_shadow_mode_never_attempts_reinit(shadow_file):
    """_record_failure must be a no-op: a re-init would re-open the I2C bus
    the Elixir broker now owns (the contention class Phase 1 eliminates)."""
    shadow_file(ENV)
    s = PiSensors()
    s._record_failure("aht20")
    assert s._failure_counts["aht20"] == 0
    assert s._reinit_attempts["aht20"] == 0


def test_available_sensors_reports_shadow_channels(shadow_file):
    shadow_file(ENV)
    s = PiSensors()
    avail = s.available_sensors()
    for key in ENV:
        assert key in avail


def test_available_sensors_omits_stale_shadow_channels(shadow_file):
    shadow_file(ENV, age_seconds=120.0)
    s = PiSensors()
    avail = s.available_sensors()
    for key in ENV:
        assert key not in avail
