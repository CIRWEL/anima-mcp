"""
Tests for config module - nervous system calibration, config round-trips, and adaptation.

Run with: pytest tests/test_config.py -v
"""

import pytest
import yaml
from pathlib import Path

from anima_mcp.config import (
    NervousSystemCalibration,
    AnimaConfig,
    DisplayConfig,
    ConfigManager,
)


# ---------------------------------------------------------------------------
# NervousSystemCalibration validation
# ---------------------------------------------------------------------------

class TestNervousSystemValidation:
    """Validation rules for nervous system calibration."""

    def test_defaults_are_valid(self):
        cal = NervousSystemCalibration()
        valid, error = cal.validate()
        assert valid is True, f"Default calibration should be valid: {error}"

    def test_cpu_temp_min_gte_max_invalid(self):
        cal = NervousSystemCalibration(cpu_temp_min=80.0, cpu_temp_max=80.0)
        valid, error = cal.validate()
        assert valid is False
        assert "cpu_temp" in error

    def test_ambient_temp_min_gte_max_invalid(self):
        cal = NervousSystemCalibration(ambient_temp_min=35.0, ambient_temp_max=15.0)
        valid, error = cal.validate()
        assert valid is False
        assert "ambient_temp" in error

    def test_light_min_gte_max_invalid(self):
        cal = NervousSystemCalibration(light_min_lux=1000.0, light_max_lux=1.0)
        valid, error = cal.validate()
        assert valid is False
        assert "light" in error

    def test_humidity_ideal_out_of_range_invalid(self):
        cal = NervousSystemCalibration(humidity_ideal=110.0)
        valid, error = cal.validate()
        assert valid is False
        assert "humidity" in error

    def test_negative_pressure_invalid(self):
        cal = NervousSystemCalibration(pressure_ideal=-5.0)
        valid, error = cal.validate()
        assert valid is False
        assert "pressure" in error

    def test_weight_out_of_range_invalid(self):
        cal = NervousSystemCalibration(neural_weight=1.5)
        valid, error = cal.validate()
        assert valid is False
        assert "weight" in error.lower()

    def test_weight_sum_too_low_invalid(self):
        cal = NervousSystemCalibration(
            warmth_weights={"cpu_temp": 0.1, "ambient_temp": 0.1, "neural": 0.1}
        )
        valid, error = cal.validate()
        assert valid is False
        assert "sum" in error.lower()

    def test_weight_sum_tolerance_boundary(self):
        """1.09 total is within 10% tolerance; 1.11 is not."""
        # 1.09 -- should pass
        cal_ok = NervousSystemCalibration(
            warmth_weights={"cpu_temp": 0.40, "ambient_temp": 0.40, "neural": 0.29}
        )
        valid_ok, _ = cal_ok.validate()
        assert valid_ok is True

        # 1.11 -- should fail
        cal_bad = NervousSystemCalibration(
            warmth_weights={"cpu_temp": 0.40, "ambient_temp": 0.40, "neural": 0.31}
        )
        valid_bad, error = cal_bad.validate()
        assert valid_bad is False
        assert "sum" in error.lower()


# ---------------------------------------------------------------------------
# NervousSystemCalibration round-trip
# ---------------------------------------------------------------------------

class TestNervousSystemRoundTrip:
    """Serialization round-trips for NervousSystemCalibration."""

    def test_to_dict_from_dict_identity(self):
        original = NervousSystemCalibration()
        restored = NervousSystemCalibration.from_dict(original.to_dict())
        assert original.to_dict() == restored.to_dict()

    def test_from_dict_missing_keys_uses_defaults(self):
        """Backwards compatibility: missing keys fall back to defaults."""
        partial = {"cpu_temp_min": 42.0}
        cal = NervousSystemCalibration.from_dict(partial)
        assert cal.cpu_temp_min == 42.0
        # Everything else should be default
        defaults = NervousSystemCalibration()
        assert cal.cpu_temp_max == defaults.cpu_temp_max
        assert cal.humidity_ideal == defaults.humidity_ideal


# ---------------------------------------------------------------------------
# AnimaConfig round-trip and validation
# ---------------------------------------------------------------------------

class TestAnimaConfigRoundTrip:
    """Round-trip and validation for the top-level AnimaConfig."""

    def test_full_round_trip_preserves_all_fields(self):
        original = AnimaConfig()
        original.metadata["calibration_update_count"] = 5
        restored = AnimaConfig.from_dict(original.to_dict())

        assert restored.nervous_system.to_dict() == original.nervous_system.to_dict()
        assert restored.display.led_brightness == original.display.led_brightness
        assert restored.metadata["calibration_update_count"] == 5

    def test_validate_catches_invalid_led_brightness(self):
        cfg = AnimaConfig()
        cfg.display.led_brightness = 2.0
        valid, error = cfg.validate()
        assert valid is False
        assert "led_brightness" in error

    def test_validate_catches_invalid_update_interval(self):
        cfg = AnimaConfig()
        cfg.display.update_interval = 0.0
        valid, error = cfg.validate()
        assert valid is False
        assert "update_interval" in error


# ---------------------------------------------------------------------------
# ConfigManager -- loading
# ---------------------------------------------------------------------------

class TestConfigManagerLoad:
    """Loading behaviour of ConfigManager."""

    def test_missing_file_returns_defaults(self, tmp_path):
        mgr = ConfigManager(config_path=tmp_path / "nonexistent.yaml")
        cfg = mgr.load()
        assert isinstance(cfg, AnimaConfig)
        defaults = AnimaConfig()
        assert cfg.nervous_system.cpu_temp_min == defaults.nervous_system.cpu_temp_min

    def test_valid_yaml_loads_correctly(self, tmp_path):
        path = tmp_path / "test_config.yaml"
        data = AnimaConfig()
        data.nervous_system.cpu_temp_min = 38.0
        with open(path, "w") as f:
            yaml.dump(data.to_dict(), f)

        mgr = ConfigManager(config_path=path)
        cfg = mgr.load()
        assert cfg.nervous_system.cpu_temp_min == pytest.approx(38.0)

    def test_invalid_yaml_falls_back_to_defaults(self, tmp_path):
        path = tmp_path / "bad_config.yaml"
        path.write_text("not: [valid: yaml: {{{{")

        mgr = ConfigManager(config_path=path)
        cfg = mgr.load()
        # Should silently fall back to defaults
        defaults = AnimaConfig()
        assert cfg.nervous_system.cpu_temp_min == defaults.nervous_system.cpu_temp_min

    def test_cache_returns_same_object(self, tmp_path):
        path = tmp_path / "test_config.yaml"
        data = AnimaConfig()
        with open(path, "w") as f:
            yaml.dump(data.to_dict(), f)

        mgr = ConfigManager(config_path=path)
        first = mgr.load()
        second = mgr.load()
        assert first is second, "Second load without force should return cached object"


# ---------------------------------------------------------------------------
# ConfigManager -- adapt_to_environment
# ---------------------------------------------------------------------------

class TestConfigManagerAdapt:
    """Environment adaptation logic."""

    def test_temperature_range_expansion(self, tmp_path):
        mgr = ConfigManager(config_path=tmp_path / "test_config.yaml")
        adapted = mgr.adapt_to_environment(
            observed_temps=[10.0, 30.0],
            observed_pressures=[],
            observed_humidity=[],
        )
        # range = 20, expansion = 4.0
        assert adapted.ambient_temp_min == pytest.approx(6.0)
        assert adapted.ambient_temp_max == pytest.approx(34.0)

    def test_pressure_averaging(self, tmp_path):
        mgr = ConfigManager(config_path=tmp_path / "test_config.yaml")
        adapted = mgr.adapt_to_environment(
            observed_temps=[],
            observed_pressures=[1000.0, 1020.0],
            observed_humidity=[],
        )
        assert adapted.pressure_ideal == pytest.approx(1010.0)

    def test_humidity_clamping(self, tmp_path):
        mgr = ConfigManager(config_path=tmp_path / "test_config.yaml")
        # Average would be 95, but should be clamped to 80
        adapted = mgr.adapt_to_environment(
            observed_temps=[],
            observed_pressures=[],
            observed_humidity=[90.0, 100.0],
        )
        assert adapted.humidity_ideal == pytest.approx(80.0)

        # Average would be 10, but should be clamped to 20
        adapted_low = mgr.adapt_to_environment(
            observed_temps=[],
            observed_pressures=[],
            observed_humidity=[5.0, 15.0],
        )
        assert adapted_low.humidity_ideal == pytest.approx(20.0)

    def test_empty_lists_no_change(self, tmp_path):
        mgr = ConfigManager(config_path=tmp_path / "test_config.yaml")
        defaults = NervousSystemCalibration()
        adapted = mgr.adapt_to_environment(
            observed_temps=[],
            observed_pressures=[],
            observed_humidity=[],
        )
        assert adapted.ambient_temp_min == pytest.approx(defaults.ambient_temp_min)
        assert adapted.ambient_temp_max == pytest.approx(defaults.ambient_temp_max)
        assert adapted.pressure_ideal == pytest.approx(defaults.pressure_ideal)
        assert adapted.humidity_ideal == pytest.approx(defaults.humidity_ideal)
