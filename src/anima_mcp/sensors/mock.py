"""
Mock sensors for development on Mac.

Simulates sensor readings with slight variation to feel alive.
Uses computational neural for EEG bands (same as Pi).
"""

import random
import sys
import psutil
from datetime import datetime
from .base import SensorBackend, SensorReadings


class MockSensors(SensorBackend):
    """Mock sensors using system stats + random variation."""

    def __init__(self):
        # Base values that drift slowly
        self._base_temp = 22.0
        self._base_humidity = 45.0
        self._base_light = 300.0
        # Prime psutil cpu_percent so first real call returns meaningful data
        psutil.cpu_percent(interval=None)

    def read(self) -> SensorReadings:
        """Read simulated sensors with realistic variation."""
        now = datetime.now()

        # Slow drift in base values
        self._base_temp += random.gauss(0, 0.1)
        self._base_temp = max(15, min(35, self._base_temp))

        self._base_humidity += random.gauss(0, 0.5)
        self._base_humidity = max(20, min(80, self._base_humidity))

        self._base_light += random.gauss(0, 10)
        self._base_light = max(0, min(1000, self._base_light))

        # Real system stats (these are actually from the Mac)
        cpu_percent = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        # CPU temp from Mac (if available)
        cpu_temp = None
        try:
            # macOS doesn't expose CPU temp easily, estimate from CPU usage
            cpu_temp = 40 + (cpu_percent * 0.4)  # Rough estimate
        except Exception:
            pass

        # Computational neural - same as Pi, derives EEG bands from system state
        eeg_bands = {}
        try:
            from ..computational_neural import get_computational_neural_state
            neural = get_computational_neural_state(
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                cpu_temp=cpu_temp
            )
            eeg_bands = {
                "delta": neural.delta,
                "theta": neural.theta,
                "alpha": neural.alpha,
                "beta": neural.beta,
                "gamma": neural.gamma,
            }
        except Exception as e:
            print(f"[MockSensors] Computational neural error: {e}", file=sys.stderr, flush=True)

        return SensorReadings(
            timestamp=now,
            cpu_temp_c=cpu_temp,
            ambient_temp_c=self._base_temp + random.gauss(0, 0.2),
            humidity_pct=self._base_humidity + random.gauss(0, 1),
            light_lux=self._base_light + random.gauss(0, 5),
            cpu_percent=cpu_percent,
            memory_percent=memory.percent,
            disk_percent=disk.percent,
            power_watts=None,  # Can't measure on Mac
            # Frequency bands from computational neural (same as Pi)
            eeg_delta_power=eeg_bands.get("delta"),
            eeg_theta_power=eeg_bands.get("theta"),
            eeg_alpha_power=eeg_bands.get("alpha"),
            eeg_beta_power=eeg_bands.get("beta"),
            eeg_gamma_power=eeg_bands.get("gamma"),
        )

    def available_sensors(self) -> list[str]:
        return [
            "cpu_temp_c (estimated)",
            "ambient_temp_c (simulated)",
            "humidity_pct (simulated)",
            "light_lux (simulated)",
            "cpu_percent (real)",
            "memory_percent (real)",
            "disk_percent (real)",
        ]

    def is_pi(self) -> bool:
        return False
