"""
Map anima state (physical + neural) to EISV metrics for UNITARES governance.

Creates bridge between anima-mcp creature and unitares-governance system.

This module implements the mapping from anima proprioception (warmth, clarity,
stability, presence) to EISV metrics (Energy, Integrity, Entropy, Void) used
by UNITARES governance framework.
"""

from dataclasses import dataclass
from typing import Optional
from .anima import Anima
from .sensors.base import SensorReadings


@dataclass
class EISVMetrics:
    """EISV metrics compatible with UNITARES governance."""
    
    energy: float      # E: 0-1, activation level
    integrity: float   # I: 0-1, information quality
    entropy: float     # S: 0-1, disorder/chaos
    void: float        # V: 0-1, accumulated strain
    
    def to_dict(self) -> dict:
        """Convert to dictionary for MCP/JSON serialization."""
        return {
            "E": self.energy,
            "I": self.integrity,
            "S": self.entropy,
            "V": self.void,
        }
    
    def __repr__(self) -> str:
        return f"EISV(E={self.energy:.2f}, I={self.integrity:.2f}, S={self.entropy:.2f}, V={self.void:.2f})"


def anima_to_eisv(
    anima: Anima,
    readings: SensorReadings,
    neural_weight: float = 0.3,
    physical_weight: float = 0.7
) -> EISVMetrics:
    """
    Map anima state to EISV metrics.
    
    Mapping strategy:
    - Energy (E): Warmth + Beta/Gamma power (activation)
    - Integrity (I): Clarity + Alpha power (awareness)
    - Entropy (S): Inverse of Stability (chaos)
    - Void (V): Inverse of Presence (strain)
    
    Args:
        anima: Anima state (warmth, clarity, stability, presence)
        readings: Sensor readings (physical + neural)
        neural_weight: Weight for neural signals (0-1)
        physical_weight: Weight for physical signals (0-1)
                      Should sum to 1.0 with neural_weight
    
    Returns:
        EISVMetrics with values in [0, 1] range
    """
    # Normalize weights
    total_weight = neural_weight + physical_weight
    if total_weight > 0:
        neural_weight = neural_weight / total_weight
        physical_weight = physical_weight / total_weight
    else:
        neural_weight = 0.0
        physical_weight = 1.0
    
    # Energy (E): Derived from warmth (neural component already in anima)
    E = anima.warmth

    # Integrity (I): Derived from clarity (neural component already in anima)
    I = anima.clarity
    
    # Entropy (S): Inverse of Stability (high stability = low entropy)
    # Stability incorporates Theta/Delta (deep stability)
    S = 1.0 - anima.stability
    
    # Void (V): Inverse of Presence (high presence = low void)
    # Presence incorporates Gamma (cognitive presence)
    V = 1.0 - anima.presence
    
    # Clamp to [0, 1] range
    return EISVMetrics(
        energy=max(0.0, min(1.0, E)),
        integrity=max(0.0, min(1.0, I)),
        entropy=max(0.0, min(1.0, S)),
        void=max(0.0, min(1.0, V))
    )


def estimate_complexity(
    anima: Anima,
    readings: Optional[SensorReadings] = None
) -> float:
    """
    Estimate task complexity from current anima state.
    
    Complexity increases with:
    - Low clarity (uncertainty)
    - Low stability (chaos)
    - High entropy (disorder)
    
    Args:
        anima: Anima state
        readings: Optional sensor readings (for neural complexity)
    
    Returns:
        Complexity estimate in [0, 1] range
    """
    # Base complexity from anima state
    clarity_complexity = (1.0 - anima.clarity) * 0.4
    stability_complexity = (1.0 - anima.stability) * 0.4
    entropy_complexity = (1.0 - anima.stability) * 0.2  # Entropy = inverse stability
    
    complexity = clarity_complexity + stability_complexity + entropy_complexity

    return max(0.0, min(1.0, complexity))


def generate_status_text(
    anima: Anima,
    readings: Optional[SensorReadings] = None,
    eisv: Optional[EISVMetrics] = None
) -> str:
    """
    Generate human-readable status text for governance system.
    
    Args:
        anima: Anima state
        readings: Optional sensor readings
        eisv: Optional EISV metrics (will compute if not provided)
    
    Returns:
        Status text string
    """
    feeling = anima.feeling()
    mood = feeling.get("mood", "neutral")
    
    # Build status text
    status_parts = [
        f"Anima state: {mood}",
        f"Warmth: {anima.warmth:.2f}",
        f"Clarity: {anima.clarity:.2f}",
        f"Stability: {anima.stability:.2f}",
        f"Presence: {anima.presence:.2f}",
    ]
    
    # Add EISV if provided
    if eisv:
        status_parts.append(f"EISV: E={eisv.energy:.2f}, I={eisv.integrity:.2f}, S={eisv.entropy:.2f}, V={eisv.void:.2f}")
    
    return ". ".join(status_parts) + "."


# Convenience function for common use case
def compute_eisv_from_readings(
    readings: SensorReadings,
    neural_weight: float = 0.3,
    physical_weight: float = 0.7
) -> EISVMetrics:
    """
    Compute EISV metrics directly from sensor readings.
    
    Convenience function that creates anima state and maps to EISV in one call.
    
    Args:
        readings: Sensor readings (physical + neural)
        neural_weight: Weight for neural signals
        physical_weight: Weight for physical signals
    
    Returns:
        EISVMetrics
    """
    from .anima import sense_self
    
    anima = sense_self(readings)
    return anima_to_eisv(anima, readings, neural_weight, physical_weight)

