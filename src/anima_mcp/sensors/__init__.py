"""Sensor abstraction - mock on Mac, real on Pi."""

from pathlib import Path
from .base import SensorReadings, SensorBackend
from .mock import MockSensors


def _is_raspberry_pi() -> bool:
    """Detect if running on actual Raspberry Pi hardware."""
    # Check for Pi-specific paths
    if Path("/sys/class/thermal/thermal_zone0/temp").exists():
        # Check /proc/cpuinfo for Pi
        try:
            cpuinfo = Path("/proc/cpuinfo").read_text()
            return "Raspberry Pi" in cpuinfo or "BCM" in cpuinfo
        except Exception:
            pass
    return False


# Only import Pi sensors if actually on Pi
PiSensors = None
if _is_raspberry_pi():
    try:
        from .pi import PiSensors
    except ImportError:
        pass

DEFAULT_BACKEND = "pi" if PiSensors else "mock"


def get_sensors(backend: str = "auto") -> SensorBackend:
    """Get sensor backend. Auto-detects Pi vs Mac."""
    if backend == "auto":
        backend = DEFAULT_BACKEND

    if backend == "pi" and PiSensors:
        return PiSensors()
    return MockSensors()


__all__ = ["SensorReadings", "SensorBackend", "MockSensors", "get_sensors"]
