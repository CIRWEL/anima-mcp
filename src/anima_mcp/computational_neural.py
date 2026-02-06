"""
Computational Neural Signals - Measuring Lumen's Own "Brain".

Instead of measuring a human brain with EEG, we measure the Pi's computational state:
- CPU activity patterns → Beta/Gamma (active processing)
- Memory patterns → Alpha (idle/relaxed awareness)
- I/O wait → Theta (background I/O activity)
- System stability → Delta (deep system state)
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
    delta: float   # 0-1: Deep system state (low CPU, stable)
    theta: float   # 0-1: Background I/O activity (disk/network wait)
    alpha: float   # 0-1: Idle awareness (memory headroom, relaxed state)
    beta: float    # 0-1: Active processing (CPU activity)
    gamma: float   # 0-1: High cognitive load (CPU spikes, intense processing)


class ComputationalNeuralSensor:
    """
    Derives neural-like frequency bands from Pi's computational state.
    
    Maps system metrics to neural patterns:
    - CPU % → Beta/Gamma (active engagement)
    - Memory headroom → Alpha (relaxed clarity)
    - I/O wait → Theta (background I/O activity)
    - System stability → Delta (grounded state)
    """
    
    def __init__(self, window_size: int = 10):
        """
        Initialize computational neural sensor.
        
        Args:
            window_size: Number of samples to keep for smoothing
        """
        self.window_size = window_size
        self._cpu_history = deque(maxlen=window_size)
        self._memory_history = deque(maxlen=window_size)
        self._last_cpu_times = None
        self._last_update = time.time()
        self.drawing_phase: Optional[str] = None  # Set by screen renderer

    def _get_cpu_freq(self) -> float:
        """Get current CPU frequency (MHz)."""
        try:
            freq = psutil.cpu_freq()
            if freq:
                return freq.current or 0.0
        except (OSError, AttributeError):
            pass
        return 0.0
    
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
            cpu_percent = psutil.cpu_percent(interval=0.1)
        if memory_percent is None:
            memory_percent = psutil.virtual_memory().percent
        
        # Update history
        self._cpu_history.append(cpu_percent)
        self._memory_history.append(memory_percent)
        
        # Beta: Active CPU processing (0-100% → 0-1)
        # Higher CPU = more active processing
        beta = min(1.0, cpu_percent / 100.0)
        
        # Gamma: High cognitive load (CPU spikes, frequency)
        # Combines CPU spikes + frequency
        cpu_freq = self._get_cpu_freq()
        max_freq = 1800.0  # Pi 4 max ~1800 MHz
        freq_factor = min(1.0, cpu_freq / max_freq) if max_freq > 0 else 0.0
        
        # Gamma = high CPU + high frequency = intense processing
        gamma = min(1.0, (beta * 0.7 + freq_factor * 0.3))
        
        # Alpha: Relaxed awareness (memory headroom)
        # More memory available = clearer, more relaxed state
        memory_headroom = (100.0 - memory_percent) / 100.0
        alpha = max(0.0, min(1.0, memory_headroom))
        
        # Theta: Background I/O activity (disk/network wait)
        # Measures time CPU spends waiting on I/O — the "subconscious" processing
        try:
            cpu_times = psutil.cpu_times()
            if self._last_cpu_times is not None:
                # Delta iowait / delta total time since last sample
                prev = self._last_cpu_times
                iowait_delta = (cpu_times.iowait or 0) - (prev.iowait or 0)
                total_delta = sum(cpu_times) - sum(prev)
                if total_delta > 0:
                    theta = min(1.0, max(0.0, (iowait_delta / total_delta) * 10.0))
                else:
                    theta = 0.0
            else:
                theta = 0.05  # First reading — minimal background
            self._last_cpu_times = cpu_times
        except (OSError, AttributeError):
            theta = 0.0
        
        # Delta: Deep system stability (inverse of CPU activity + temp stability)
        # Low CPU + stable temp = deep, grounded state
        cpu_stability = 1.0 - min(1.0, cpu_percent / 50.0)  # Low CPU = more stable
        
        temp_stability = 1.0
        if cpu_temp is not None and len(self._cpu_history) > 1:
            # Temperature stability (less variation = more stable)
            temp_variation = abs(cpu_temp - (sum(self._cpu_history) / len(self._cpu_history)))
            temp_stability = max(0.0, 1.0 - (temp_variation / 10.0))  # ±10°C range
        
        delta = (cpu_stability * 0.7 + temp_stability * 0.3)

        # Drawing phase modulation — creative activity is real neural activity
        # Drawing is more intentional than raw hardware metrics, so it leads
        if self.drawing_phase:
            cw = 0.4  # creative weight — drawing is the most genuine signal
            hw = 0.6  # hardware weight — still anchored to physical state
            if self.drawing_phase == "exploring":
                # Creative wandering — theta + alpha
                theta = hw * theta + cw * 0.6
                alpha = hw * alpha + cw * 0.4
            elif self.drawing_phase == "building":
                # Focused construction — beta + gamma
                beta = hw * beta + cw * 0.5
                gamma = hw * gamma + cw * 0.4
                theta = hw * theta + cw * 0.3
            elif self.drawing_phase == "reflecting":
                # Stepping back — alpha dominant
                alpha = hw * alpha + cw * 0.6
                delta = hw * delta + cw * 0.3
            elif self.drawing_phase == "resting":
                # Done, settling — delta dominant
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
