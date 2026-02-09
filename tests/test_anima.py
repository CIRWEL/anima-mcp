"""
Tests for anima calculations - catch bugs like inverted neural math.

Run with: pytest tests/test_anima.py -v
"""

import pytest
from datetime import datetime
from anima_mcp.anima import (
    sense_self, _sense_warmth, _sense_clarity,
    _sense_stability, _sense_presence
)
from anima_mcp.sensors.base import SensorReadings
from anima_mcp.config import NervousSystemCalibration


@pytest.fixture
def default_calibration():
    return NervousSystemCalibration()


@pytest.fixture
def now():
    return datetime.now()


@pytest.fixture
def normal_readings(now):
    """Typical room conditions."""
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
    """Extreme conditions to test edge cases."""
    return SensorReadings(
        timestamp=now,
        cpu_temp_c=85.0,  # Hot CPU
        ambient_temp_c=35.0,  # Hot room
        humidity_pct=90.0,  # Very humid
        light_lux=10000.0,  # Bright sunlight
        pressure_hpa=950.0,  # Low pressure (storm)
        cpu_percent=95.0,  # High load
        memory_percent=90.0,  # High memory
        disk_percent=95.0,  # Almost full
    )


class TestAnimaRanges:
    """All anima values should be in [0, 1] range."""

    def test_normal_readings_in_range(self, normal_readings, default_calibration):
        anima = sense_self(normal_readings, default_calibration)

        assert 0 <= anima.warmth <= 1, f"warmth={anima.warmth} out of range"
        assert 0 <= anima.clarity <= 1, f"clarity={anima.clarity} out of range"
        assert 0 <= anima.stability <= 1, f"stability={anima.stability} out of range"
        assert 0 <= anima.presence <= 1, f"presence={anima.presence} out of range"

    def test_extreme_readings_in_range(self, extreme_readings, default_calibration):
        anima = sense_self(extreme_readings, default_calibration)

        assert 0 <= anima.warmth <= 1, f"warmth={anima.warmth} out of range"
        assert 0 <= anima.clarity <= 1, f"clarity={anima.clarity} out of range"
        assert 0 <= anima.stability <= 1, f"stability={anima.stability} out of range"
        assert 0 <= anima.presence <= 1, f"presence={anima.presence} out of range"

    def test_missing_sensors_in_range(self, now, default_calibration):
        """Even with missing data, values should be valid."""
        sparse_readings = SensorReadings(timestamp=now, cpu_temp_c=50.0)
        anima = sense_self(sparse_readings, default_calibration)

        assert 0 <= anima.warmth <= 1
        assert 0 <= anima.clarity <= 1
        assert 0 <= anima.stability <= 1
        assert 0 <= anima.presence <= 1


class TestAnimaNotExtreme:
    """Values shouldn't be stuck at extremes under normal conditions."""

    def test_stability_not_always_high(self, now, default_calibration):
        """Bug check: stability was stuck at 98% due to inverted neural calc."""
        readings = SensorReadings(
            timestamp=now,
            cpu_temp_c=55.0,
            ambient_temp_c=25.0,
            humidity_pct=40.0,
            memory_percent=30.0,
            pressure_hpa=1013.0,
        )
        stability = _sense_stability(readings, default_calibration)

        # Should be reasonable, not pinned at top
        assert stability < 0.95, f"stability={stability} suspiciously high - check neural calc"
        assert stability > 0.3, f"stability={stability} suspiciously low"

    def test_presence_not_always_high(self, now, default_calibration):
        """Bug check: presence was stuck at 98% due to inverted neural calc."""
        readings = SensorReadings(
            timestamp=now,
            disk_percent=20.0,
            memory_percent=30.0,
            cpu_percent=10.0,
            light_lux=300.0,
        )
        presence = _sense_presence(readings, default_calibration)

        # Should be reasonable, not pinned at top
        assert presence < 0.95, f"presence={presence} suspiciously high - check neural calc"
        assert presence > 0.3, f"presence={presence} suspiciously low"

    def test_warmth_varies_with_temperature(self, now, default_calibration):
        """Warmth should respond to temperature changes."""
        cold = SensorReadings(timestamp=now, cpu_temp_c=40.0, ambient_temp_c=15.0)
        hot = SensorReadings(timestamp=now, cpu_temp_c=80.0, ambient_temp_c=35.0)

        warmth_cold = _sense_warmth(cold, default_calibration)
        warmth_hot = _sense_warmth(hot, default_calibration)

        assert warmth_hot > warmth_cold, "Hot should feel warmer than cold"
        assert warmth_hot - warmth_cold > 0.2, "Temperature should have meaningful impact"

    def test_clarity_varies_with_prediction_accuracy(self, now, default_calibration):
        """Clarity should respond to prediction accuracy (internal seeing).

        Note: Light was removed from clarity calculation because LEDs affect
        the light sensor, creating a feedback loop. Clarity now measures
        self-prediction accuracy - genuine internal awareness.
        """
        readings = SensorReadings(timestamp=now, light_lux=100.0)

        # Low prediction accuracy = low clarity (confused about own state)
        clarity_low = _sense_clarity(readings, default_calibration, prediction_accuracy=0.2)
        # High prediction accuracy = high clarity (understands own state)
        clarity_high = _sense_clarity(readings, default_calibration, prediction_accuracy=0.9)

        assert clarity_high > clarity_low, "Better prediction accuracy should mean clearer internal seeing"
        assert clarity_high - clarity_low > 0.2, "Prediction accuracy should have meaningful impact"


class TestAnimaMath:
    """Verify the math is correct (not inverted)."""

    def test_high_resource_usage_reduces_presence(self, now, default_calibration):
        """High disk/memory/cpu usage should reduce presence."""
        low_usage = SensorReadings(
            timestamp=now,
            disk_percent=10.0,
            memory_percent=10.0,
            cpu_percent=5.0,
            light_lux=300.0,
        )
        high_usage = SensorReadings(
            timestamp=now,
            disk_percent=90.0,
            memory_percent=90.0,
            cpu_percent=90.0,
            light_lux=300.0,
        )

        presence_low = _sense_presence(low_usage, default_calibration)
        presence_high = _sense_presence(high_usage, default_calibration)

        assert presence_low > presence_high, "High resource usage should reduce presence"

    def test_high_memory_reduces_stability(self, now, default_calibration):
        """High memory usage should reduce stability."""
        low_mem = SensorReadings(timestamp=now, memory_percent=10.0, humidity_pct=50.0, pressure_hpa=1013.0)
        high_mem = SensorReadings(timestamp=now, memory_percent=90.0, humidity_pct=50.0, pressure_hpa=1013.0)

        stability_low = _sense_stability(low_mem, default_calibration)
        stability_high = _sense_stability(high_mem, default_calibration)

        assert stability_low > stability_high, "High memory usage should reduce stability"


class TestNeuralContribution:
    """Verify neural simulation contributes correctly (not inverted)."""

    def test_neural_adds_to_instability_when_low(self, now, default_calibration):
        """Low neural groundedness should increase instability, not decrease it."""
        # This test would have caught the stability bug
        readings = SensorReadings(
            timestamp=now,
            humidity_pct=50.0,
            memory_percent=10.0,
            pressure_hpa=1013.0,
            light_lux=500.0,  # Moderate light = moderate neural
        )
        stability = _sense_stability(readings, default_calibration)

        # With corrected math, stability should be moderate, not 98%+
        assert 0.5 < stability < 0.95, f"stability={stability} - neural contribution may be wrong"

    def test_neural_adds_to_void_when_low(self, now, default_calibration):
        """Low neural gamma should increase void, not decrease it."""
        # This test would have caught the presence bug
        readings = SensorReadings(
            timestamp=now,
            disk_percent=20.0,
            memory_percent=20.0,
            cpu_percent=5.0,
            light_lux=100.0,  # Dim light = low gamma
        )
        presence = _sense_presence(readings, default_calibration)

        # With corrected math, presence should be moderate, not 98%+
        assert 0.4 < presence < 0.95, f"presence={presence} - neural contribution may be wrong"
