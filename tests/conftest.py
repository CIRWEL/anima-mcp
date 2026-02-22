"""
Shared test fixtures for anima-mcp test suite.

These fixtures provide common test objects that many test files need.
Local fixtures in individual test files override these (pytest convention),
so existing tests continue to work unchanged.
"""

import pytest
from datetime import datetime

from anima_mcp.sensors.base import SensorReadings
from anima_mcp.config import NervousSystemCalibration
from anima_mcp.anima import Anima


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

@pytest.fixture
def now():
    """Current datetime — used by many sensor/anima tests."""
    return datetime.now()


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

@pytest.fixture
def default_calibration():
    """Default NervousSystemCalibration with stock values."""
    return NervousSystemCalibration()


# ---------------------------------------------------------------------------
# SensorReadings factories
# ---------------------------------------------------------------------------

@pytest.fixture
def normal_readings(now):
    """Typical room conditions — moderate everything."""
    return SensorReadings(
        timestamp=now,
        cpu_temp_c=55.0,
        ambient_temp_c=25.0,
        humidity_pct=40.0,
        light_lux=300.0,
        pressure_hpa=1013.0,
        cpu_percent=10.0,
        memory_percent=30.0,
        disk_percent=50.0,
    )


@pytest.fixture
def extreme_readings(now):
    """Extreme conditions to test edge cases and clamping."""
    return SensorReadings(
        timestamp=now,
        cpu_temp_c=85.0,
        ambient_temp_c=35.0,
        humidity_pct=90.0,
        light_lux=10000.0,
        pressure_hpa=950.0,
        cpu_percent=95.0,
        memory_percent=90.0,
        disk_percent=95.0,
    )


@pytest.fixture
def minimal_readings(now):
    """Readings with only the required timestamp — all sensors None."""
    return SensorReadings(timestamp=now)


@pytest.fixture
def full_readings(now):
    """Readings with all common fields populated (including pressure, LED)."""
    return SensorReadings(
        timestamp=now,
        cpu_temp_c=55.0,
        ambient_temp_c=22.0,
        humidity_pct=40.0,
        light_lux=300.0,
        cpu_percent=15.0,
        memory_percent=35.0,
        disk_percent=50.0,
        pressure_hpa=827.0,
        pressure_temp_c=23.0,
        led_brightness=0.12,
    )


def make_readings(**kwargs) -> SensorReadings:
    """
    Create SensorReadings with sensible defaults.

    This is a plain function (not a fixture) so tests can call it inline
    with arbitrary overrides.  Importable as:

        from conftest import make_readings
    """
    defaults = dict(
        timestamp=datetime.now(),
        ambient_temp_c=22.0,
        humidity_pct=45.0,
        light_lux=100.0,
        pressure_hpa=1013.0,
        cpu_temp_c=50.0,
    )
    defaults.update(kwargs)
    return SensorReadings(**defaults)


# ---------------------------------------------------------------------------
# Anima factories
# ---------------------------------------------------------------------------

def make_anima(
    warmth: float = 0.5,
    clarity: float = 0.5,
    stability: float = 0.5,
    presence: float = 0.5,
    **reading_overrides,
) -> Anima:
    """
    Create an Anima with defaults.

    Plain function (not a fixture) for inline use with overrides.
    Importable as:

        from conftest import make_anima
    """
    readings = make_readings(**reading_overrides)
    return Anima(
        warmth=warmth,
        clarity=clarity,
        stability=stability,
        presence=presence,
        readings=readings,
    )


@pytest.fixture
def default_anima():
    """Anima at midpoint values — the 'neutral' state."""
    return make_anima()


# ---------------------------------------------------------------------------
# Growth system
# ---------------------------------------------------------------------------

@pytest.fixture
def growth(tmp_path):
    """GrowthSystem backed by a temporary SQLite database."""
    from anima_mcp.growth import GrowthSystem
    db_path = str(tmp_path / "test_growth.db")
    return GrowthSystem(db_path=db_path)


# ---------------------------------------------------------------------------
# Self-model
# ---------------------------------------------------------------------------

@pytest.fixture
def self_model(tmp_path):
    """SelfModel with temporary persistence path."""
    from anima_mcp.self_model import SelfModel
    return SelfModel(persistence_path=tmp_path / "self_model.json")


# ---------------------------------------------------------------------------
# Identity store
# ---------------------------------------------------------------------------

@pytest.fixture
def identity_store(tmp_path):
    """IdentityStore backed by a temporary SQLite database."""
    from anima_mcp.identity.store import IdentityStore
    db_path = str(tmp_path / "identity_test.db")
    return IdentityStore(db_path=db_path)


# ---------------------------------------------------------------------------
# State directory helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def state_dir(tmp_path):
    """
    A temporary directory that mimics ~/.anima/ structure.

    Creates the directory and returns its path. Tests can write
    state files (calibration.json, self_model.json, etc.) here.
    """
    d = tmp_path / "anima_state"
    d.mkdir()
    return d
