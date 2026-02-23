"""
Tests for CalibrationDrift integration with anima sensing and schema hub.
"""

import pytest
from datetime import datetime
from anima_mcp.calibration_drift import CalibrationDrift
from anima_mcp.config import NervousSystemCalibration
from anima_mcp.sensors.base import SensorReadings


def _make_readings(**overrides) -> SensorReadings:
    """Create deterministic SensorReadings for testing."""
    defaults = dict(
        timestamp=datetime.now(),
        cpu_temp_c=55.0,
        ambient_temp_c=22.0,
        humidity_pct=45.0,
        light_lux=300.0,
        cpu_percent=30.0,
        memory_percent=50.0,
        disk_percent=40.0,
        pressure_hpa=1013.0,
        eeg_delta_power=0.5,
        eeg_theta_power=0.4,
        eeg_alpha_power=0.6,
        eeg_beta_power=0.3,
        eeg_gamma_power=0.2,
    )
    defaults.update(overrides)
    return SensorReadings(**defaults)


class TestDriftIntegration:
    def test_drifted_calibration_produces_different_anima(self):
        """Drifted midpoints should shift anima dimension values."""
        from anima_mcp.anima import sense_self

        readings = _make_readings()
        cal_default = NervousSystemCalibration()
        anima_default = sense_self(readings, cal_default)

        # Create calibration with shifted warmth midpoint
        cal_drifted = NervousSystemCalibration()
        cal_drifted.ambient_temp_min += 5.0
        cal_drifted.ambient_temp_max += 5.0
        anima_drifted = sense_self(readings, cal_drifted)

        assert anima_default.warmth != anima_drifted.warmth

    def test_drift_midpoints_to_calibration_conversion(self):
        """CalibrationDrift.get_midpoints() can modify a NervousSystemCalibration."""
        drift = CalibrationDrift()
        drift.dimensions["warmth"].outer_ema = 0.55
        drift.dimensions["warmth"].apply_drift()
        midpoints = drift.get_midpoints()
        assert midpoints["warmth"] != 0.5

    def test_sense_self_accepts_drift_midpoints(self):
        """sense_self() should accept and apply drift_midpoints parameter."""
        from anima_mcp.anima import sense_self

        readings = _make_readings()
        cal = NervousSystemCalibration()

        anima_default = sense_self(readings, cal)
        anima_drifted = sense_self(readings, cal, drift_midpoints={"warmth": 0.6})

        # Warmth midpoint shifted up -> temp ranges shift up -> warmth value changes
        assert anima_default.warmth != anima_drifted.warmth

    def test_apply_drift_to_calibration_shifts_temp_ranges(self):
        """_apply_drift_to_calibration should shift temperature ranges proportionally."""
        from anima_mcp.anima import _apply_drift_to_calibration

        cal = NervousSystemCalibration()
        original_min = cal.ambient_temp_min
        original_max = cal.ambient_temp_max

        drifted = _apply_drift_to_calibration(cal, {"warmth": 0.6})

        # Warmth midpoint 0.6 means offset of +0.1 from 0.5
        # Should shift temp ranges up
        assert drifted.ambient_temp_min > original_min
        assert drifted.ambient_temp_max > original_max

    def test_apply_drift_to_calibration_no_shift_at_default(self):
        """No drift at default midpoint (0.5)."""
        from anima_mcp.anima import _apply_drift_to_calibration

        cal = NervousSystemCalibration()
        drifted = _apply_drift_to_calibration(cal, {"warmth": 0.5})

        assert drifted.ambient_temp_min == cal.ambient_temp_min
        assert drifted.ambient_temp_max == cal.ambient_temp_max

    def test_sense_self_with_memory_passes_drift(self):
        """sense_self_with_memory() should accept and pass through drift_midpoints."""
        from anima_mcp.anima import sense_self_with_memory

        readings = _make_readings()
        cal = NervousSystemCalibration()

        anima_default = sense_self_with_memory(readings, calibration=cal)
        anima_drifted = sense_self_with_memory(
            readings, calibration=cal, drift_midpoints={"warmth": 0.6}
        )

        assert anima_default.warmth != anima_drifted.warmth

    def test_drift_offsets_in_schema(self):
        """Schema should include drift offset nodes when provided."""
        from anima_mcp.schema_hub import SchemaHub

        hub = SchemaHub()
        drift = CalibrationDrift()
        # Simulate some drift
        for _ in range(50):
            drift.update({"warmth": 0.6, "clarity": 0.55, "stability": 0.5, "presence": 0.5})
        offsets = drift.get_offsets()

        readings = _make_readings()
        from anima_mcp.anima import Anima
        anima = Anima(warmth=0.5, clarity=0.5, stability=0.5, presence=0.5, readings=readings)

        schema = hub.compose_schema(anima=anima, readings=readings, drift_offsets=offsets)

        # Find drift nodes
        drift_nodes = [n for n in schema.nodes if n.node_id.startswith("drift_")]
        assert len(drift_nodes) > 0, "Expected drift nodes in schema"

        # At least warmth should have a non-zero offset after 50 updates toward 0.6
        warmth_node = next((n for n in drift_nodes if n.node_id == "drift_warmth"), None)
        assert warmth_node is not None
        assert warmth_node.value != 0.0

    def test_full_drift_cycle(self):
        """End-to-end: drift updates -> midpoints -> sense_self produces shifted anima."""
        from anima_mcp.anima import sense_self

        readings = _make_readings()
        cal = NervousSystemCalibration()

        # Create drift and feed it warmth-high attractor values
        drift = CalibrationDrift()
        for _ in range(100):
            drift.update({"warmth": 0.7, "clarity": 0.5, "stability": 0.5, "presence": 0.5})

        midpoints = drift.get_midpoints()
        # Warmth midpoint should have drifted above 0.5
        assert midpoints["warmth"] > 0.5

        anima_default = sense_self(readings, cal)
        anima_drifted = sense_self(readings, cal, drift_midpoints=midpoints)

        # Drifted warmth midpoint shifts what "normal" means
        assert anima_default.warmth != anima_drifted.warmth
