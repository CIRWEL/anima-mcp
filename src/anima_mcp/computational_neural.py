"""
Computational Neural Signals - Measuring Lumen's Own "Brain".

Instead of measuring a human brain with EEG, we measure the Pi's computational state:
- CPU activity → Beta (sustained processing)
- Context switches + interrupts → Gamma (spiking/bursting activity)
- I/O wait time → Theta (integration/waiting-for-data)
- Memory headroom → Alpha (idle/relaxed awareness)
- CPU + temp stability → Delta (deep system state)
- Drawing phase modulates bands (creative activity is real neural activity)

This is computational proprioception - Lumen sensing its own computational "brain".
"""

import psutil
import time
from dataclasses import dataclass
from typing import Optional
from collections import deque


@dataclass
class ComputationalNeuralState:
    """Neural-like signals derived from Pi's computational state."""
    delta: float   # 0-1: Deep system state (low CPU, stable temp)
    theta: float   # 0-1: I/O wait (integration - CPU blocked waiting for data)
    alpha: float   # 0-1: Idle awareness (memory headroom)
    beta: float    # 0-1: Active processing (CPU usage)
    gamma: float   # 0-1: Spiking activity (context switches + interrupts)


class ComputationalNeuralSensor:
    """
    Derives neural-like frequency bands from Pi's computational state.

    Each band has a distinct, independent source:
    - Beta: CPU % (sustained processing load)
    - Gamma: Context switches + interrupts per second (burst/spiking activity)
    - Alpha: Memory headroom (relaxed clarity)
    - Theta: I/O wait time (integration - CPU blocked waiting for data)
    - Delta: CPU stability + temperature stability (deep grounded state)
    """

    def __init__(self, window_size: int = 10):
        self.window_size = window_size
        self._cpu_history = deque(maxlen=window_size)
        self._temp_history = deque(maxlen=window_size)
        self._last_cpu_stats = None
        self._last_disk_io = None
        self._last_net_io = None
        self._last_sample_time: Optional[float] = None
        self.drawing_phase: Optional[str] = None  # Set by screen renderer
        # EMA smoothing for theta and gamma (other bands are inherently smooth)
        self._ema_theta: Optional[float] = None  # alpha=0.3, half-life ~4s at 2s interval
        self._ema_gamma: Optional[float] = None  # alpha=0.2, slightly smoother
        # Prime psutil cpu_percent so first real call returns meaningful data
        psutil.cpu_percent(interval=None)

    def get_neural_state(self, cpu_percent: Optional[float] = None,
                        memory_percent: Optional[float] = None,
                        cpu_temp: Optional[float] = None) -> ComputationalNeuralState:
        """
        Derive neural state from Pi's computational metrics.

        Args:
            cpu_percent: Current CPU usage (0-100)
            memory_percent: Current memory usage (0-100)
            cpu_temp: CPU temperature (Celsius)

        Returns:
            ComputationalNeuralState with frequency bands
        """
        now = time.time()

        # Get current metrics
        if cpu_percent is None:
            cpu_percent = psutil.cpu_percent(interval=None)
        if memory_percent is None:
            memory_percent = psutil.virtual_memory().percent

        # Update history
        self._cpu_history.append(cpu_percent)
        if cpu_temp is not None:
            self._temp_history.append(cpu_temp)

        # Time since last sample
        dt = now - self._last_sample_time if self._last_sample_time else 0.0
        self._last_sample_time = now

        # === BETA: Sustained CPU processing (0-100% → 0-1) ===
        beta = min(1.0, cpu_percent / 100.0)

        # === GAMMA: Spiking activity (context switches + interrupts per second) ===
        # Context switches = how often the CPU jumps between tasks (burst behavior)
        # Interrupts = hardware/software signals demanding attention
        # Together they measure "spiking" — qualitatively different from sustained CPU load
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

        # === ALPHA: Relaxed awareness (memory headroom) ===
        memory_headroom = (100.0 - memory_percent) / 100.0
        alpha = max(0.0, min(1.0, memory_headroom))

        # === THETA: I/O integration (disk + network activity) ===
        # In neuroscience, theta reflects integration - the brain waiting for and processing
        # incoming data. On the Pi, this maps to disk I/O (SHM writes, DB, logs) and
        # network I/O (HTTP requests, UNITARES governance calls, Groq API).
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

        # === DELTA: Deep system stability (low CPU + stable temp) ===
        cpu_stability = 1.0 - min(1.0, cpu_percent / 50.0)

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
            self._ema_theta = 0.3 * theta + 0.7 * self._ema_theta
        theta = self._ema_theta

        if self._ema_gamma is None:
            self._ema_gamma = gamma
        else:
            self._ema_gamma = 0.2 * gamma + 0.8 * self._ema_gamma
        gamma = self._ema_gamma

        # Drawing phase modulation — creative activity is real neural activity
        if self.drawing_phase:
            cw = 0.4  # creative weight
            hw = 0.6  # hardware weight
            if self.drawing_phase == "exploring":
                theta = hw * theta + cw * 0.6
                alpha = hw * alpha + cw * 0.4
            elif self.drawing_phase == "building":
                beta = hw * beta + cw * 0.5
                gamma = hw * gamma + cw * 0.4
                theta = hw * theta + cw * 0.3
            elif self.drawing_phase == "reflecting":
                alpha = hw * alpha + cw * 0.6
                delta = hw * delta + cw * 0.3
            elif self.drawing_phase == "resting":
                delta = hw * delta + cw * 0.5
                alpha = hw * alpha + cw * 0.3

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
