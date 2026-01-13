"""
Neural Simulation - Environmental + Computational neural signals.

Derives neural-like frequency bands from BOTH:
- Environmental factors (light, temperature) - the original working approach
- Computational factors (CPU, memory) - supplementary

This maintains the original behavior where light and temperature affected
neural state, making warmth/clarity respond to the physical environment.
"""

import psutil
import math
from typing import Optional
from dataclasses import dataclass


@dataclass
class NeuralState:
    """Neural-like signals derived from environment and computation."""
    delta: float   # 0-1: Deep rest (darkness, cool, low activity)
    theta: float   # 0-1: Drowsy/meditative (dim, comfortable)
    alpha: float   # 0-1: Relaxed awareness (moderate light, comfortable temp)
    beta: float    # 0-1: Active engagement (bright, warm, active)
    gamma: float   # 0-1: High alertness (very bright, active processing)


def get_neural_state(light_level: Optional[float] = None,
                     temp_delta: Optional[float] = None,
                     cpu_percent: Optional[float] = None) -> NeuralState:
    """
    Derive neural state from environmental and computational factors.
    
    This is the ORIGINAL approach that worked - neural state responds to
    light and temperature, not just CPU activity.
    
    Args:
        light_level: Current light in lux (primary driver)
        temp_delta: Temperature deviation from ideal (secondary)
        cpu_percent: CPU usage for computational component (tertiary)
    
    Returns:
        NeuralState with all band values
    """
    
    # === LIGHT-BASED NEURAL STATE (primary) ===
    # This was the working approach - light drives alertness
    
    if light_level is None:
        light_level = 100.0  # Default moderate light
    
    # Normalize light (0-1000 lux range, log scale for natural perception)
    # Human perception is logarithmic
    if light_level <= 0:
        light_norm = 0.0
    else:
        # Log scale: 1 lux = 0, 10 lux = 0.33, 100 lux = 0.67, 1000 lux = 1.0
        light_norm = min(1.0, math.log10(max(1, light_level)) / 3.0)
    
    # === TEMPERATURE COMFORT (secondary) ===
    # Deviation from ideal affects neural comfort
    
    if temp_delta is None:
        temp_comfort = 1.0  # Assume comfortable if unknown
    else:
        # ±5°C from ideal = still comfortable, beyond that = less so
        temp_comfort = max(0.0, 1.0 - abs(temp_delta) / 10.0)
    
    # === COMPUTATIONAL ACTIVITY (tertiary) ===
    
    if cpu_percent is None:
        try:
            cpu_percent = psutil.cpu_percent(interval=0.05)
        except:
            cpu_percent = 10.0
    
    cpu_norm = min(1.0, cpu_percent / 100.0)
    
    # === DERIVE BANDS ===
    
    # Delta: Deep rest - darkness + cool + low activity
    # High in dark, quiet, cool conditions
    darkness = 1.0 - light_norm
    delta = darkness * 0.6 + (1.0 - cpu_norm) * 0.3 + temp_comfort * 0.1
    
    # Theta: Drowsy/meditative - dim light, comfortable
    # Peaks at low-moderate light
    dim_factor = 1.0 - abs(light_norm - 0.3) * 2  # Peak at ~30% light
    dim_factor = max(0.0, dim_factor)
    theta = dim_factor * 0.5 + temp_comfort * 0.3 + (1.0 - cpu_norm) * 0.2
    
    # Alpha: Relaxed awareness - moderate light, comfortable temp
    # Peaks at moderate conditions
    moderate_light = 1.0 - abs(light_norm - 0.5) * 2  # Peak at 50% light
    moderate_light = max(0.0, moderate_light)
    alpha = moderate_light * 0.5 + temp_comfort * 0.4 + (1.0 - cpu_norm * 0.5) * 0.1
    
    # Beta: Active engagement - bright light, warm, some activity
    # Increases with light and activity
    beta = light_norm * 0.5 + cpu_norm * 0.3 + temp_comfort * 0.2
    
    # Gamma: High alertness - very bright, high activity
    # Only high when both light and activity are high
    bright = max(0.0, (light_norm - 0.5) * 2)  # Only kicks in above 50% light
    gamma = bright * 0.4 + cpu_norm * 0.4 + (light_norm * cpu_norm) * 0.2
    
    return NeuralState(
        delta=round(max(0.0, min(1.0, delta)), 3),
        theta=round(max(0.0, min(1.0, theta)), 3),
        alpha=round(max(0.0, min(1.0, alpha)), 3),
        beta=round(max(0.0, min(1.0, beta)), 3),
        gamma=round(max(0.0, min(1.0, gamma)), 3),
    )


# Alias for compatibility
ComputationalNeuralState = NeuralState

def get_computational_neural_state(cpu_percent: Optional[float] = None,
                                   memory_percent: Optional[float] = None,
                                   cpu_temp: Optional[float] = None) -> NeuralState:
    """Compatibility wrapper - uses light-based approach."""
    return get_neural_state(cpu_percent=cpu_percent)
