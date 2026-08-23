"""
Computational Dynamics - Normalized Views of Lumen's Pi Substrate.

These are normalized views of the Pi's computational state, not EEG:
- CPU activity → Beta (sustained processing)
- Context switches + interrupts → Gamma (scheduler activity)
- Disk + network activity → Theta (I/O load)
- CPU idle fraction → Alpha (exactly 1 - beta; not an independent input)
- CPU variance + temp stability → Delta (deep system stability)

This is computational proprioception. The Greek labels are visualization
metaphors retained for continuity; they do not imply neural frequencies or a
biological measurement.
"""

import psutil
import time
from dataclasses import dataclass
from typing import Optional
from collections import deque


COMPUTATIONAL_NEURAL_PROVENANCE = {
    "schema": "anima.computational_dynamics.v1",
    "label": "Computational Dynamics",
    "kind": "computational_proprioception",
    "physical_eeg": False,
    "normalized_views": 5,
    "independent_views": 4,
    "memory_is_input": False,
    "caveat": (
        "Greek band names are display metaphors, not measured frequencies; "
        "alpha is the exact complement of beta."
    ),
    "bands": {
        "delta": {
            "source": "CPU range over the last 10 samples + temperature deviation",
            "formula": "0.7 × CPU stability + 0.3 × thermal stability",
            "independent": True,
        },
        "theta": {
            "source": "disk busy time + network throughput",
            "formula": "0.7 × max(disk, network) + 0.3 × min(disk, network), then EMA",
            "independent": True,
        },
        "alpha": {
            "source": "derived from beta",
            "formula": "1 − beta",
            "independent": False,
        },
        "beta": {
            "source": "CPU utilization",
            "formula": "cpu_percent ÷ 100",
            "independent": True,
        },
        "gamma": {
            "source": "context-switch and interrupt rates",
            "formula": "0.6 × ctx rate + 0.4 × interrupt rate, normalized then EMA",
            "independent": True,
        },
    },
}


def computational_neural_provenance() -> dict:
    """Return the stable, JSON-safe derivation contract for these displays."""
    return {
        **COMPUTATIONAL_NEURAL_PROVENANCE,
        "bands": {
            name: dict(metadata)
            for name, metadata in COMPUTATIONAL_NEURAL_PROVENANCE["bands"].items()
        },
    }


@dataclass
class ComputationalNeuralState:
    """Normalized views derived from Pi computational state."""
    delta: float   # 0-1: CPU variance stability + temp stability
    theta: float   # 0-1: I/O wait (integration - CPU blocked waiting for data)
    alpha: float   # 0-1: CPU idle fraction (inverse beta)
    beta: float    # 0-1: Active processing (CPU usage)
    gamma: float   # 0-1: Scheduler activity (context switches + interrupts)


class ComputationalNeuralSensor:
    """
    Derives normalized, Greek-labelled views from Pi computational state.

    Four views have independently measured sources; alpha is derived:
    - Beta: CPU % (sustained processing load)
    - Gamma: Context switches + interrupts per second (scheduler activity)
    - Alpha: 1 - beta (CPU idle fraction; exactly dependent on beta)
    - Theta: Disk + network activity (I/O load)
    - Delta: CPU variance over history window + temperature stability
    """

    def __init__(self, window_size: int = 10):
        self.window_size = window_size
        self._cpu_history = deque(maxlen=window_size)
        self._temp_history = deque(maxlen=window_size)
        self._last_cpu_stats = None
        self._last_disk_io = None
        self._last_net_io = None
        self._last_sample_time: Optional[float] = None
        # EMA smoothing for theta and gamma (other bands are inherently smooth).
        # The constants are calibrated at a 2-second reference interval and
        # converted from elapsed wall time on each observation.
        self._ema_theta: Optional[float] = None
        self._ema_gamma: Optional[float] = None
        # Prime psutil cpu_percent so first real call returns meaningful data
        psutil.cpu_percent(interval=None)

    def get_neural_state(self, cpu_percent: Optional[float] = None,
                        memory_percent: Optional[float] = None,
                        cpu_temp: Optional[float] = None) -> ComputationalNeuralState:
        """
        Derive neural state from Pi's computational metrics.

        Args:
            cpu_percent: Current CPU usage (0-100)
            memory_percent: Deprecated compatibility input; deliberately ignored
            cpu_temp: CPU temperature (Celsius)

        Returns:
            ComputationalNeuralState with normalized computational views
        """
        now = time.monotonic()

        # Get current metrics
        if cpu_percent is None:
            cpu_percent = psutil.cpu_percent(interval=None)
        # RAM pressure is reported as its own system metric. It used to be
        # accepted here without affecting any band, which made the mapping API
        # imply a relationship that did not exist. Keep the keyword for caller
        # compatibility, but make the non-use part of the public provenance.
        _ = memory_percent

        # Update history
        self._cpu_history.append(cpu_percent)
        if cpu_temp is not None:
            self._temp_history.append(cpu_temp)

        # Time since last sample
        dt = now - self._last_sample_time if self._last_sample_time else 0.0
        self._last_sample_time = now

        # === BETA: Sustained CPU processing (0-100% → 0-1) ===
        beta = min(1.0, cpu_percent / 100.0)

        # === GAMMA: Scheduler activity (context switches + interrupts per second) ===
        # Context switches = how often the CPU jumps between tasks
        # Interrupts = hardware/software signals demanding attention
        # Together they form a scheduler-load view distinct from sustained CPU use.
        gamma = 0.0
        try:
            cpu_stats = psutil.cpu_stats()
            if self._last_cpu_stats is not None and dt > 0:
                ctx_delta = cpu_stats.ctx_switches - self._last_cpu_stats.ctx_switches
                int_delta = cpu_stats.interrupts - self._last_cpu_stats.interrupts
                # Rate per second
                ctx_rate = ctx_delta / dt
                int_rate = int_delta / dt
                # Pi Zero 2W typical: ~1000 ctx/s idle, ~3000 moderate, ~6000+ busy
                # Interrupts similar range. Normalize to Pi-appropriate values.
                ctx_norm = min(1.0, ctx_rate / 5000.0)
                int_norm = min(1.0, int_rate / 5000.0)
                gamma = ctx_norm * 0.6 + int_norm * 0.4
            self._last_cpu_stats = cpu_stats
        except (OSError, AttributeError):
            # Fallback: no stats available
            gamma = beta * 0.5  # degrade gracefully

        # === ALPHA: CPU idle fraction (exact inverse of beta) ===
        alpha = 1.0 - beta

        # === THETA: Disk + network activity ===
        # This is an I/O-load view (SHM writes, DB/log traffic, HTTP and
        # governance calls), not a measurement of cognitive integration.
        theta = 0.0
        try:
            disk_io = psutil.disk_io_counters()
            disk_signal = 0.0
            net_signal = 0.0

            if disk_io and self._last_disk_io is not None and dt > 0:
                # Primary: disk busy_time ratio (how much of wall time disk was active)
                # Pi Zero: ~0.05 idle writes, ~0.2 moderate, ~0.5 heavy
                if hasattr(disk_io, 'busy_time') and hasattr(self._last_disk_io, 'busy_time'):
                    busy_delta = disk_io.busy_time - self._last_disk_io.busy_time
                    # Pi Zero SD card saturates easily; double headroom so
                    # 50% wall-time busy ≈ theta 0.5 instead of 1.0
                    disk_signal = min(1.0, busy_delta / (dt * 2000))
                else:
                    # Fallback: throughput-based estimate
                    read_delta = disk_io.read_bytes - self._last_disk_io.read_bytes
                    write_delta = disk_io.write_bytes - self._last_disk_io.write_bytes
                    bytes_per_sec = (read_delta + write_delta) / dt
                    # Pi Zero: ~1.5 MB/s normal, ~5 MB/s heavy
                    disk_signal = min(1.0, bytes_per_sec / (10 * 1024 * 1024))
            if disk_io:
                self._last_disk_io = disk_io

            # Network I/O: HTTP requests, UNITARES calls, Groq API
            try:
                net_io = psutil.net_io_counters()
                if hasattr(self, '_last_net_io') and self._last_net_io is not None and dt > 0:
                    net_bytes = (
                        (net_io.bytes_sent - self._last_net_io.bytes_sent) +
                        (net_io.bytes_recv - self._last_net_io.bytes_recv)
                    ) / dt
                    # Pi Zero: ~10 KB/s idle, ~100 KB/s moderate, ~500 KB/s heavy
                    net_signal = min(1.0, net_bytes / (500 * 1024))
                self._last_net_io = net_io
            except (OSError, AttributeError):
                pass

            # Weighted blend: dominant source leads but doesn't ignore the other
            theta = 0.7 * max(disk_signal, net_signal) + 0.3 * min(disk_signal, net_signal)
        except (OSError, AttributeError):
            theta = 0.0

        # === DELTA: CPU variance stability + temperature stability ===
        # Steady load (even high) = stable. Jumping around = unstable.
        if len(self._cpu_history) >= 2:
            cpu_range = max(self._cpu_history) - min(self._cpu_history)
            cpu_stability = max(0.0, 1.0 - cpu_range / 40.0)
        else:
            cpu_stability = 1.0

        temp_stability = 1.0
        if cpu_temp is not None and len(self._temp_history) > 1:
            avg_temp = sum(self._temp_history) / len(self._temp_history)
            temp_variation = abs(cpu_temp - avg_temp)
            temp_stability = max(0.0, 1.0 - (temp_variation / 10.0))

        delta = (cpu_stability * 0.7 + temp_stability * 0.3)

        # EMA smoothing on theta and gamma — dampens transient spikes
        if self._ema_theta is None:
            self._ema_theta = theta
        else:
            theta_alpha = 1.0 - (1.0 - 0.3) ** (max(0.0, min(60.0, dt)) / 2.0)
            self._ema_theta = theta_alpha * theta + (1.0 - theta_alpha) * self._ema_theta
        theta = max(0.0, min(1.0, self._ema_theta))

        if self._ema_gamma is None:
            self._ema_gamma = gamma
        else:
            gamma_alpha = 1.0 - (1.0 - 0.2) ** (max(0.0, min(60.0, dt)) / 2.0)
            self._ema_gamma = gamma_alpha * gamma + (1.0 - gamma_alpha) * self._ema_gamma
        gamma = max(0.0, min(1.0, self._ema_gamma))

        return ComputationalNeuralState(
            delta=round(delta, 3),
            theta=round(theta, 3),
            alpha=round(alpha, 3),
            beta=round(beta, 3),
            gamma=round(gamma, 3),
        )


# Global sensor instance
_sensor: Optional[ComputationalNeuralSensor] = None


def get_computational_neural_sensor() -> ComputationalNeuralSensor:
    """Get or create the computational neural sensor."""
    global _sensor
    if _sensor is None:
        _sensor = ComputationalNeuralSensor()
    return _sensor


def get_computational_neural_state(cpu_percent: Optional[float] = None,
                                  memory_percent: Optional[float] = None,
                                  cpu_temp: Optional[float] = None) -> ComputationalNeuralState:
    """Convenience function to get current computational neural state."""
    return get_computational_neural_sensor().get_neural_state(
        cpu_percent=cpu_percent,
        memory_percent=memory_percent,
        cpu_temp=cpu_temp
    )
