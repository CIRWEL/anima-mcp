"""
Tests for computational neural sensor module.

Validates neural band derivation from system metrics.
"""

import pytest
import time
from unittest.mock import patch, MagicMock
from collections import namedtuple

from anima_mcp.computational_neural import (
    ComputationalNeuralSensor,
    ComputationalNeuralState,
)


# Mock types matching psutil's named tuples
CpuStats = namedtuple("scpustats", ["ctx_switches", "interrupts", "soft_interrupts", "syscalls"])
DiskIO = namedtuple("sdiskio", ["read_count", "write_count", "read_bytes", "write_bytes", "read_time", "write_time"])
CpuTimes = namedtuple("scputimes", ["user", "nice", "system", "idle", "iowait"])


def _mock_psutil(mock_ps, cpu_stats=None, disk_io=None, iowait=0.0):
    """Configure psutil mock with proper return values."""
    if cpu_stats is None:
        mock_ps.cpu_stats.return_value = CpuStats(
            ctx_switches=100000, interrupts=50000, soft_interrupts=0, syscalls=0
        )
    else:
        mock_ps.cpu_stats.return_value = cpu_stats
    if disk_io is None:
        mock_ps.disk_io_counters.return_value = DiskIO(
            read_count=0, write_count=0, read_bytes=0, write_bytes=0, read_time=0, write_time=0
        )
    else:
        mock_ps.disk_io_counters.return_value = disk_io
    # Mock cpu_times_percent for theta/iowait calculation
    mock_ps.cpu_times_percent.return_value = CpuTimes(
        user=20.0, nice=0.0, system=10.0, idle=70.0 - iowait, iowait=iowait
    )


@pytest.fixture
def sensor():
    """Create a fresh sensor with no history."""
    return ComputationalNeuralSensor(window_size=10)


class TestBetaBand:
    """Test Beta band: CPU percent → active processing."""

    def test_zero_cpu_gives_zero_beta(self, sensor):
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            _mock_psutil(mock_ps)
            state = sensor.get_neural_state(cpu_percent=0.0, memory_percent=50.0)
        assert state.beta == 0.0

    def test_full_cpu_gives_max_beta(self, sensor):
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            _mock_psutil(mock_ps)
            state = sensor.get_neural_state(cpu_percent=100.0, memory_percent=50.0)
        assert state.beta == 1.0

    def test_half_cpu_gives_half_beta(self, sensor):
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            _mock_psutil(mock_ps)
            state = sensor.get_neural_state(cpu_percent=50.0, memory_percent=50.0)
        assert state.beta == 0.5


class TestAlphaBand:
    """Test Alpha band: memory headroom → relaxed awareness."""

    def test_low_memory_use_gives_high_alpha(self, sensor):
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            _mock_psutil(mock_ps)
            state = sensor.get_neural_state(cpu_percent=10.0, memory_percent=20.0)
        assert state.alpha == 0.8

    def test_high_memory_use_gives_low_alpha(self, sensor):
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            _mock_psutil(mock_ps)
            state = sensor.get_neural_state(cpu_percent=10.0, memory_percent=90.0)
        assert state.alpha == 0.1


class TestGammaBand:
    """Test Gamma band: context switches + interrupts → spiking activity."""

    def test_first_sample_zero_gamma(self, sensor):
        """First sample has no previous stats → gamma = 0."""
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            _mock_psutil(mock_ps)
            state = sensor.get_neural_state(cpu_percent=50.0, memory_percent=50.0)
        assert state.gamma == 0.0

    def test_high_ctx_switches_high_gamma(self, sensor):
        """High context switch rate → high gamma."""
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            # First sample: baseline
            _mock_psutil(mock_ps, cpu_stats=CpuStats(100000, 50000, 0, 0))
            sensor.get_neural_state(cpu_percent=50.0, memory_percent=50.0)

            # Second sample: 20000 ctx switches in ~1 second = max ctx_norm
            sensor._last_sample_time = time.time() - 1.0  # pretend 1 second ago
            _mock_psutil(mock_ps, cpu_stats=CpuStats(120000, 50000, 0, 0))
            state = sensor.get_neural_state(cpu_percent=50.0, memory_percent=50.0)

        # ctx_rate = 20000/1.0, ctx_norm = 1.0, int_norm = 0.0
        # gamma = 1.0 * 0.6 + 0.0 * 0.4 = 0.6
        assert state.gamma == pytest.approx(0.6, abs=0.05)

    def test_gamma_independent_of_cpu(self, sensor):
        """Gamma should NOT track CPU percent — it tracks switching rate."""
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            # First sample
            _mock_psutil(mock_ps, cpu_stats=CpuStats(100000, 50000, 0, 0))
            sensor.get_neural_state(cpu_percent=10.0, memory_percent=50.0)

            # Second sample: same switching rate, different CPU
            sensor._last_sample_time = time.time() - 1.0
            _mock_psutil(mock_ps, cpu_stats=CpuStats(105000, 55000, 0, 0))
            state_low_cpu = sensor.get_neural_state(cpu_percent=10.0, memory_percent=50.0)

        sensor2 = ComputationalNeuralSensor()
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            _mock_psutil(mock_ps, cpu_stats=CpuStats(100000, 50000, 0, 0))
            sensor2.get_neural_state(cpu_percent=90.0, memory_percent=50.0)

            sensor2._last_sample_time = time.time() - 1.0
            _mock_psutil(mock_ps, cpu_stats=CpuStats(105000, 55000, 0, 0))
            state_high_cpu = sensor2.get_neural_state(cpu_percent=90.0, memory_percent=50.0)

        # Same switching rate → same gamma, regardless of CPU
        assert state_low_cpu.gamma == pytest.approx(state_high_cpu.gamma, abs=0.01)
        # But beta should differ
        assert state_low_cpu.beta != state_high_cpu.beta


class TestThetaBand:
    """Test Theta band: I/O wait time → integration/waiting-for-data."""

    def test_no_iowait_zero_theta(self, sensor):
        """No I/O wait → theta = 0."""
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            _mock_psutil(mock_ps, iowait=0.0)
            state = sensor.get_neural_state(cpu_percent=50.0, memory_percent=50.0)
        assert state.theta == 0.0

    def test_iowait_raises_theta(self, sensor):
        """I/O wait should raise theta."""
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            # iowait=50% → theta = 0.5 * 0.8 = 0.4
            _mock_psutil(mock_ps, iowait=50.0)
            state = sensor.get_neural_state(cpu_percent=50.0, memory_percent=50.0)
        # 50% iowait → theta ≈ 0.4 (scaled by 0.8)
        assert state.theta == pytest.approx(0.4, abs=0.05)

    def test_high_iowait_high_theta(self, sensor):
        """High I/O wait → high theta."""
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            # iowait=100% → theta = 1.0 * 0.8 = 0.8
            _mock_psutil(mock_ps, iowait=100.0)
            state = sensor.get_neural_state(cpu_percent=50.0, memory_percent=50.0)
        assert state.theta == pytest.approx(0.8, abs=0.05)


class TestDeltaBand:
    """Test Delta band: system stability (low CPU + stable temp)."""

    def test_idle_system_high_delta(self, sensor):
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            _mock_psutil(mock_ps)
            state = sensor.get_neural_state(cpu_percent=0.0, memory_percent=50.0)
        assert state.delta == 1.0

    def test_busy_system_low_delta(self, sensor):
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            _mock_psutil(mock_ps)
            state = sensor.get_neural_state(cpu_percent=80.0, memory_percent=50.0)
        assert state.delta == pytest.approx(0.3, abs=0.01)

    def test_temp_variation_reduces_delta(self, sensor):
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            _mock_psutil(mock_ps)
            for _ in range(5):
                sensor.get_neural_state(cpu_percent=0.0, memory_percent=50.0, cpu_temp=45.0)
            state = sensor.get_neural_state(cpu_percent=0.0, memory_percent=50.0, cpu_temp=55.0)
        assert state.delta < 1.0


class TestDrawingPhaseModulation:
    """Test that drawing phases modulate neural bands."""

    def _get_state(self, sensor, phase):
        sensor.drawing_phase = phase
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            _mock_psutil(mock_ps)
            return sensor.get_neural_state(cpu_percent=30.0, memory_percent=50.0)

    def test_exploring_boosts_theta(self, sensor):
        baseline = self._get_state(ComputationalNeuralSensor(), None)
        exploring = self._get_state(sensor, "exploring")
        assert exploring.theta > baseline.theta

    def test_building_boosts_beta_gamma(self, sensor):
        baseline = self._get_state(ComputationalNeuralSensor(), None)
        building = self._get_state(sensor, "building")
        assert building.beta > baseline.beta
        assert building.gamma > baseline.gamma

    def test_reflecting_boosts_alpha(self, sensor):
        baseline = self._get_state(ComputationalNeuralSensor(), None)
        reflecting = self._get_state(sensor, "reflecting")
        assert reflecting.alpha > baseline.alpha

    def test_resting_has_high_delta(self, sensor):
        resting = self._get_state(sensor, "resting")
        assert resting.delta > 0.4

    def test_no_phase_no_modulation(self, sensor):
        sensor.drawing_phase = None
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            _mock_psutil(mock_ps)
            state = sensor.get_neural_state(cpu_percent=50.0, memory_percent=50.0)
        assert state.beta == 0.5


class TestOutputRanges:
    """Test that all outputs are in valid [0, 1] range."""

    def test_extreme_inputs_stay_in_range(self, sensor):
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            _mock_psutil(mock_ps)
            for cpu in [0, 50, 100, 200]:
                for mem in [0, 50, 100]:
                    state = sensor.get_neural_state(cpu_percent=cpu, memory_percent=mem)
                    for band in [state.delta, state.theta, state.alpha, state.beta, state.gamma]:
                        assert 0.0 <= band <= 1.0, f"Band out of range: {band} (cpu={cpu}, mem={mem})"
