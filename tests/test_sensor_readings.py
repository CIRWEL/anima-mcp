"""
Tests for SensorReadings — attribute access, throttle fields, serialization.

Catches bugs like readings.lux vs readings.light_lux (audit finding #1).
"""

import pytest
from datetime import datetime
from anima_mcp.sensors.base import SensorReadings


@pytest.fixture
def now():
    return datetime.now()


@pytest.fixture
def full_readings(now):
    """Readings with all fields populated."""
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


@pytest.fixture
def minimal_readings(now):
    """Readings with only required field (timestamp)."""
    return SensorReadings(timestamp=now)


class TestSensorReadingsAttributes:
    """Verify that SensorReadings has the correct attribute names.

    This catches the readings.lux vs readings.light_lux bug.
    """

    def test_light_attribute_is_light_lux(self, full_readings):
        """The light field is light_lux, NOT lux."""
        assert hasattr(full_readings, "light_lux")
        assert not hasattr(full_readings, "lux")
        assert full_readings.light_lux == 300.0

    def test_temp_attribute_is_ambient_temp_c(self, full_readings):
        """The ambient temp field is ambient_temp_c, NOT temperature."""
        assert hasattr(full_readings, "ambient_temp_c")
        assert not hasattr(full_readings, "temperature")
        assert full_readings.ambient_temp_c == 22.0

    def test_led_brightness_attribute(self, full_readings):
        """LED brightness is led_brightness, a float 0-1."""
        assert hasattr(full_readings, "led_brightness")
        assert full_readings.led_brightness == 0.12

    def test_all_fields_have_none_defaults(self, minimal_readings):
        """All sensor fields default to None except timestamp."""
        assert minimal_readings.timestamp is not None
        assert minimal_readings.cpu_temp_c is None
        assert minimal_readings.ambient_temp_c is None
        assert minimal_readings.humidity_pct is None
        assert minimal_readings.light_lux is None
        assert minimal_readings.cpu_percent is None
        assert minimal_readings.memory_percent is None
        assert minimal_readings.disk_percent is None
        assert minimal_readings.power_watts is None
        assert minimal_readings.led_brightness is None
        assert minimal_readings.pressure_hpa is None
        assert minimal_readings.pressure_temp_c is None


class TestSensorReadingsThrottle:
    """Verify throttle/voltage fields exist and serialize correctly."""

    def test_throttle_fields_exist(self, minimal_readings):
        """Throttle fields should exist and default to None."""
        assert hasattr(minimal_readings, "throttle_bits")
        assert hasattr(minimal_readings, "undervoltage_now")
        assert hasattr(minimal_readings, "throttled_now")
        assert hasattr(minimal_readings, "freq_capped_now")
        assert hasattr(minimal_readings, "undervoltage_occurred")
        assert minimal_readings.throttle_bits is None
        assert minimal_readings.undervoltage_now is None

    def test_throttle_fields_populated(self, now):
        """Throttle fields can be set and read back."""
        readings = SensorReadings(
            timestamp=now,
            throttle_bits=0x50005,
            undervoltage_now=True,
            throttled_now=False,
            freq_capped_now=True,
            undervoltage_occurred=True,
        )
        assert readings.throttle_bits == 0x50005
        assert readings.undervoltage_now is True
        assert readings.throttled_now is False
        assert readings.freq_capped_now is True
        assert readings.undervoltage_occurred is True


class TestSensorReadingsSerialization:
    """Verify to_dict() includes all fields."""

    def test_to_dict_includes_core_fields(self, full_readings):
        d = full_readings.to_dict()
        assert "light_lux" in d
        assert "ambient_temp_c" in d
        assert "cpu_temp_c" in d
        assert "led_brightness" in d
        assert "pressure_hpa" in d
        assert d["light_lux"] == 300.0

    def test_to_dict_no_lux_key(self, full_readings):
        """to_dict should NOT have a 'lux' key — it's 'light_lux'."""
        d = full_readings.to_dict()
        assert "lux" not in d

    def test_to_dict_includes_throttle(self, now):
        readings = SensorReadings(
            timestamp=now,
            throttle_bits=0x50005,
            undervoltage_now=True,
        )
        d = readings.to_dict()
        assert "throttle_bits" in d
        assert "undervoltage_now" in d
        assert d["throttle_bits"] == 0x50005

    def test_to_dict_none_values_included(self, minimal_readings):
        """Even None values should appear in dict (for consistent schema)."""
        d = minimal_readings.to_dict()
        assert "light_lux" in d
        assert d["light_lux"] is None
        assert "cpu_temp_c" in d
        assert d["cpu_temp_c"] is None
