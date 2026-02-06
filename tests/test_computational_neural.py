"""
Tests for computational neural sensor module.

Validates neural band derivation from system metrics.
"""

import pytest
from unittest.mock import patch, MagicMock

from anima_mcp.computational_neural import (
    ComputationalNeuralSensor,
    ComputationalNeuralState,
)


@pytest.fixture
def sensor():
    """Create a fresh sensor with no history."""
    return ComputationalNeuralSensor(window_size=10)


class TestBetaBand:
    """Test Beta band: CPU percent → active processing."""

    def test_zero_cpu_gives_zero_beta(self, sensor):
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            mock_ps.cpu_times.side_effect = AttributeError
            mock_ps.cpu_freq.return_value = None
            state = sensor.get_neural_state(cpu_percent=0.0, memory_percent=50.0)
        assert state.beta == 0.0

    def test_full_cpu_gives_max_beta(self, sensor):
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            mock_ps.cpu_times.side_effect = AttributeError
            mock_ps.cpu_freq.return_value = None
            state = sensor.get_neural_state(cpu_percent=100.0, memory_percent=50.0)
        assert state.beta == 1.0

    def test_half_cpu_gives_half_beta(self, sensor):
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            mock_ps.cpu_times.side_effect = AttributeError
            mock_ps.cpu_freq.return_value = None
            state = sensor.get_neural_state(cpu_percent=50.0, memory_percent=50.0)
        assert state.beta == 0.5


class TestAlphaBand:
    """Test Alpha band: memory headroom → relaxed awareness."""

    def test_low_memory_use_gives_high_alpha(self, sensor):
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            mock_ps.cpu_times.side_effect = AttributeError
            mock_ps.cpu_freq.return_value = None
            state = sensor.get_neural_state(cpu_percent=10.0, memory_percent=20.0)
        assert state.alpha == 0.8  # 80% headroom

    def test_high_memory_use_gives_low_alpha(self, sensor):
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            mock_ps.cpu_times.side_effect = AttributeError
            mock_ps.cpu_freq.return_value = None
            state = sensor.get_neural_state(cpu_percent=10.0, memory_percent=90.0)
        assert state.alpha == 0.1  # 10% headroom


class TestDeltaBand:
    """Test Delta band: system stability (low CPU + stable temp)."""

    def test_idle_system_high_delta(self, sensor):
        """Zero CPU → max CPU stability → high delta."""
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            mock_ps.cpu_times.side_effect = AttributeError
            mock_ps.cpu_freq.return_value = None
            state = sensor.get_neural_state(cpu_percent=0.0, memory_percent=50.0)
        # cpu_stability = 1.0 - 0/50 = 1.0, temp_stability = 1.0 (no temp)
        # delta = 1.0 * 0.7 + 1.0 * 0.3 = 1.0
        assert state.delta == 1.0

    def test_busy_system_low_delta(self, sensor):
        """High CPU → low stability → low delta."""
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            mock_ps.cpu_times.side_effect = AttributeError
            mock_ps.cpu_freq.return_value = None
            state = sensor.get_neural_state(cpu_percent=80.0, memory_percent=50.0)
        # cpu_stability = 1.0 - 80/50 = clamped to 0
        # delta = 0 * 0.7 + 1.0 * 0.3 = 0.3
        assert state.delta == pytest.approx(0.3, abs=0.01)

    def test_temp_variation_reduces_delta(self, sensor):
        """Temperature swings reduce delta (temp_stability decreases)."""
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            mock_ps.cpu_times.side_effect = AttributeError
            mock_ps.cpu_freq.return_value = None

            # Build up temp history at 45C
            for _ in range(5):
                sensor.get_neural_state(cpu_percent=0.0, memory_percent=50.0, cpu_temp=45.0)

            # Now spike to 55C (10 degree variation)
            state = sensor.get_neural_state(cpu_percent=0.0, memory_percent=50.0, cpu_temp=55.0)

        # Temp variation should reduce delta below 1.0
        assert state.delta < 1.0


class TestDrawingPhaseModulation:
    """Test that drawing phases modulate neural bands."""

    def _get_state(self, sensor, phase):
        sensor.drawing_phase = phase
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            mock_ps.cpu_times.side_effect = AttributeError
            mock_ps.cpu_freq.return_value = None
            return sensor.get_neural_state(cpu_percent=30.0, memory_percent=50.0)

    def test_exploring_boosts_theta(self, sensor):
        """Exploring phase should boost theta (creative wandering)."""
        baseline = self._get_state(ComputationalNeuralSensor(), None)
        exploring = self._get_state(sensor, "exploring")
        assert exploring.theta > baseline.theta

    def test_building_boosts_beta_gamma(self, sensor):
        """Building phase should boost beta and gamma."""
        baseline = self._get_state(ComputationalNeuralSensor(), None)
        building = self._get_state(sensor, "building")
        assert building.beta > baseline.beta
        assert building.gamma > baseline.gamma

    def test_reflecting_boosts_alpha(self, sensor):
        """Reflecting phase should boost alpha."""
        baseline = self._get_state(ComputationalNeuralSensor(), None)
        reflecting = self._get_state(sensor, "reflecting")
        assert reflecting.alpha > baseline.alpha

    def test_resting_has_high_delta(self, sensor):
        """Resting phase should have high delta (settled state)."""
        resting = self._get_state(sensor, "resting")
        # Delta should remain high during resting (creative weight pushes toward 0.5)
        assert resting.delta > 0.4

    def test_no_phase_no_modulation(self, sensor):
        """No drawing phase should give unmodulated values."""
        sensor.drawing_phase = None
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            mock_ps.cpu_times.side_effect = AttributeError
            mock_ps.cpu_freq.return_value = None
            state = sensor.get_neural_state(cpu_percent=50.0, memory_percent=50.0)
        assert state.beta == 0.5  # Direct map from CPU


class TestOutputRanges:
    """Test that all outputs are in valid [0, 1] range."""

    def test_extreme_inputs_stay_in_range(self, sensor):
        """Extreme system metrics should still produce [0,1] bands."""
        with patch("anima_mcp.computational_neural.psutil") as mock_ps:
            mock_ps.cpu_times.side_effect = AttributeError
            mock_ps.cpu_freq.return_value = None

            for cpu in [0, 50, 100, 200]:
                for mem in [0, 50, 100]:
                    state = sensor.get_neural_state(cpu_percent=cpu, memory_percent=mem)
                    for band in [state.delta, state.theta, state.alpha, state.beta, state.gamma]:
                        assert 0.0 <= band <= 1.0, f"Band out of range: {band} (cpu={cpu}, mem={mem})"
