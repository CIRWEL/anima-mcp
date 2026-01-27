"""
Anima - The creature's self-sense, grounded in physics.

Not abstract metrics. Felt states derived from actual measurements.

- warmth: thermal + computational energy
- clarity: sensor quality, awareness
- stability: environmental consistency
- presence: resource availability

The creature knows "I feel warm" not "E=0.4"
"""

from dataclasses import dataclass
from typing import Optional
from .sensors.base import SensorReadings
from .config import get_calibration, NervousSystemCalibration
from .neural_sim import get_neural_state


@dataclass
class Anima:
    """The creature's felt sense of self."""

    warmth: float    # How warm/energetic [0, 1]
    clarity: float   # How clear the senses [0, 1]
    stability: float # How stable/ordered [0, 1] (inverse of entropy)
    presence: float  # How much capacity [0, 1] (inverse of void)

    # Source readings for transparency
    readings: SensorReadings

    def to_dict(self) -> dict:
        return {
            "warmth": self.warmth,
            "clarity": self.clarity,
            "stability": self.stability,
            "presence": self.presence,
            "feeling": self.feeling(),
            "readings": self.readings.to_dict(),
        }

    def feeling(self) -> dict:
        """How the creature feels right now."""
        return {
            "warmth": _warmth_feeling(self.warmth),
            "clarity": _clarity_feeling(self.clarity),
            "stability": _stability_feeling(self.stability),
            "presence": _presence_feeling(self.presence),
            "mood": _overall_mood(self.warmth, self.clarity, self.stability, self.presence),
        }


def sense_self(readings: SensorReadings, calibration: Optional[NervousSystemCalibration] = None) -> Anima:
    """
    The creature senses itself.

    Proprioception grounded in physical measurements.
    
    Args:
        readings: Sensor readings
        calibration: Nervous system calibration (uses default if None)
    """
    if calibration is None:
        calibration = get_calibration()
    
    warmth = _sense_warmth(readings, calibration)
    clarity = _sense_clarity(readings, calibration)
    stability = _sense_stability(readings, calibration)
    presence = _sense_presence(readings, calibration)

    return Anima(
        warmth=warmth,
        clarity=clarity,
        stability=stability,
        presence=presence,
        readings=readings
    )


def _sense_warmth(r: SensorReadings, cal: NervousSystemCalibration) -> float:
    """
    How warm does the creature feel?

    Sources:
    - CPU temperature (internal body heat)
    - Ambient temperature (environmental warmth)
    - Neural activity (alertness/engagement - from light or EEG)

    Note: CPU usage removed - a resting creature in a warm room should feel
    comfortable, not cold. Warmth is about thermal state, not busy-ness.
    """
    components = []
    weights = []

    # CPU temp: calibrated range -> 0-1 (internal body heat)
    if r.cpu_temp_c is not None:
        temp_range = cal.cpu_temp_max - cal.cpu_temp_min
        if temp_range > 0:
            cpu_warmth = (r.cpu_temp_c - cal.cpu_temp_min) / temp_range
            cpu_warmth = max(0, min(1, cpu_warmth))
            components.append(cpu_warmth)
            weights.append(cal.warmth_weights.get("cpu_temp", 0.35))

    # Ambient temp: calibrated range -> 0-1 (environmental warmth)
    if r.ambient_temp_c is not None:
        temp_range = cal.ambient_temp_max - cal.ambient_temp_min
        if temp_range > 0:
            ambient_warmth = (r.ambient_temp_c - cal.ambient_temp_min) / temp_range
            ambient_warmth = max(0, min(1, ambient_warmth))
            components.append(ambient_warmth)
            weights.append(cal.warmth_weights.get("ambient_temp", 0.45))

    # Neural component: Real EEG beta+gamma power, or simulated if unavailable
    # This represents alertness/engagement, not raw CPU cycles
    if r.eeg_beta_power is not None and r.eeg_gamma_power is not None:
        # Use real EEG data
        neural_warmth = (r.eeg_beta_power + r.eeg_gamma_power) / 2
    else:
        # Fall back to simulated neural activity (maintains warmth contribution)
        neural = get_neural_state(light_level=r.light_lux)
        neural_warmth = (neural.beta + neural.gamma) / 2  # Active engagement
    components.append(neural_warmth)
    weights.append(cal.warmth_weights.get("neural", 0.20))

    if not components:
        return 0.5

    total_weight = sum(weights)
    if total_weight == 0:
        return 0.5
    
    return round(sum(c * w for c, w in zip(components, weights)) / total_weight, 3)


def _sense_clarity(r: SensorReadings, cal: NervousSystemCalibration) -> float:
    """
    How clearly can the creature sense its environment?

    Sources:
    - Light level (visual clarity)
    - Sensor availability (data richness)
    - Alpha EEG power (relaxed awareness, eyes-closed clarity)
    """
    components = []
    weights = []

    # Light: log scale for perception (calibrated range)
    if r.light_lux is not None:
        import math
        light_range = cal.light_max_lux - cal.light_min_lux
        if light_range > 0:
            # Log scale mapping
            light_clarity = math.log10(max(cal.light_min_lux, r.light_lux)) / math.log10(cal.light_max_lux)
            light_clarity = max(0, min(1, light_clarity))
            components.append(light_clarity)
            weights.append(cal.clarity_weights.get("light", 0.4))

    # Sensor coverage
    sensor_count = sum(1 for v in [
        r.cpu_temp_c, r.ambient_temp_c, r.humidity_pct,
        r.light_lux, r.sound_level, r.pressure_hpa,
    ] if v is not None)
    coverage = sensor_count / 6
    components.append(coverage)
    weights.append(cal.clarity_weights.get("sensor_coverage", 0.4))

    # Neural clarity: Real EEG alpha power, or simulated if unavailable
    if r.eeg_alpha_power is not None:
        # Use real EEG data
        neural_clarity = r.eeg_alpha_power  # Relaxed, clear awareness
    else:
        # Fall back to simulated neural activity
        neural = get_neural_state(light_level=r.light_lux)
        neural_clarity = neural.alpha  # Relaxed, clear awareness
    components.append(neural_clarity)
    weights.append(cal.clarity_weights.get("neural", 0.4))

    if not components:
        return 0.5

    total_weight = sum(weights)
    if total_weight == 0:
        return 0.5
    
    return round(sum(c * w for c, w in zip(components, weights)) / total_weight, 3)


def _sense_stability(r: SensorReadings, cal: NervousSystemCalibration) -> float:
    """
    How stable/ordered does the environment feel?

    This is inverse of entropy - high stability = low chaos.

    Sources:
    - Humidity near ideal (calibrated)
    - Memory headroom
    - Complete sensor data
    - Barometric pressure stability (deviations from local normal)
    - Theta/Delta EEG power (deep stability, meditative state)
    """
    instability = 0.0
    count = 0

    # Humidity deviation from ideal (calibrated)
    if r.humidity_pct is not None:
        humidity_dev = abs(r.humidity_pct - cal.humidity_ideal) / max(1, cal.humidity_ideal)
        instability += min(1, humidity_dev) * cal.stability_weights.get("humidity_dev", 0.25)
        count += cal.stability_weights.get("humidity_dev", 0.25)

    # Memory pressure = instability
    if r.memory_percent is not None:
        instability += (r.memory_percent / 100) * cal.stability_weights.get("memory", 0.3)
        count += cal.stability_weights.get("memory", 0.3)

    # Missing sensors = uncertainty
    missing = sum(1 for v in [
        r.cpu_temp_c, r.ambient_temp_c, r.humidity_pct,
        r.light_lux, r.pressure_hpa
    ] if v is None)
    missing_weight = cal.stability_weights.get("missing_sensors", 0.2)
    instability += (missing / 5) * missing_weight
    count += missing_weight

    # Barometric pressure: deviations from local normal indicate instability
    # Uses calibrated pressure_ideal (learned or configured for location)
    if r.pressure_hpa is not None:
        pressure_weight = cal.stability_weights.get("pressure_dev", 0.15)
        # ±20 hPa is significant weather change (configurable in future)
        pressure_range = 20.0
        pressure_dev = abs(r.pressure_hpa - cal.pressure_ideal) / pressure_range
        pressure_instability = min(1, pressure_dev) * pressure_weight
        instability += pressure_instability
        count += pressure_weight

    # Neural stability: Real EEG theta+delta power, or simulated if unavailable
    temp_delta = None
    if r.ambient_temp_c is not None:
        temp_delta = r.ambient_temp_c - (cal.ambient_temp_min + cal.ambient_temp_max) / 2
    
    if r.eeg_theta_power is not None and r.eeg_delta_power is not None:
        # Use real EEG data
        neural_stability = (r.eeg_theta_power + r.eeg_delta_power) / 2  # Deep grounding
    else:
        # Fall back to simulated neural activity
        neural = get_neural_state(light_level=r.light_lux, temp_delta=temp_delta)
        neural_stability = (neural.theta + neural.delta) / 2  # Deep grounding
    
    neural_weight = cal.stability_weights.get("neural", 0.2)
    instability -= neural_stability * neural_weight
    count += neural_weight

    if count == 0:
        return 0.5

    # Stability is inverse of instability (clamped to [0, 1])
    stability = 1.0 - (instability / count)
    return round(max(0, min(1, stability)), 3)


def _sense_presence(r: SensorReadings, cal: NervousSystemCalibration) -> float:
    """
    How much capacity/presence does the creature have?

    This is inverse of void - high presence = plenty of resources.

    Sources:
    - Disk headroom
    - Memory headroom
    - CPU headroom
    - Gamma EEG power (high cognitive presence, awareness)
    """
    void = 0.0
    count = 0

    if r.disk_percent is not None:
        weight = cal.presence_weights.get("disk", 0.25)
        void += (r.disk_percent / 100) * weight
        count += weight

    if r.memory_percent is not None:
        weight = cal.presence_weights.get("memory", 0.3)
        void += (r.memory_percent / 100) * weight
        count += weight

    if r.cpu_percent is not None:
        weight = cal.presence_weights.get("cpu", 0.25)
        void += (r.cpu_percent / 100) * weight
        count += weight

    # Neural presence: Real EEG gamma power, or simulated if unavailable
    if r.eeg_gamma_power is not None:
        # Use real EEG data
        neural_presence = r.eeg_gamma_power  # High cognitive presence
    else:
        # Fall back to simulated neural activity
        neural = get_neural_state(light_level=r.light_lux)
        neural_presence = neural.gamma  # High cognitive presence
    
    weight = cal.presence_weights.get("neural", 0.2)
    void -= neural_presence * weight
    count += weight

    if count == 0:
        return 0.5

    # Presence is inverse of void (clamped to [0, 1])
    presence = 1.0 - (void / count)
    return round(max(0, min(1, presence)), 3)


def _warmth_feeling(w: float) -> str:
    if w < 0.3:
        return "cold, sluggish"
    elif w < 0.6:
        return "comfortable"
    elif w < 0.8:
        return "warm, active"
    else:
        return "hot, intense"


def _clarity_feeling(c: float) -> str:
    if c < 0.3:
        return "dim, uncertain"
    elif c < 0.6:
        return "adequate"
    elif c < 0.8:
        return "clear"
    else:
        return "vivid, sharp"


def _stability_feeling(s: float) -> str:
    if s < 0.3:
        return "chaotic, stressed"
    elif s < 0.6:
        return "variable"
    elif s < 0.8:
        return "steady"
    else:
        return "calm, ordered"


def _presence_feeling(p: float) -> str:
    if p < 0.3:
        return "depleted, strained"
    elif p < 0.6:
        return "adequate"
    elif p < 0.8:
        return "capable"
    else:
        return "abundant, strong"


def _overall_mood(warmth: float, clarity: float, stability: float, presence: float) -> str:
    """What mood emerges from the anima state?"""
    
    # Calculate overall "wellness" score
    wellness = (warmth + clarity + stability + presence) / 4.0
    
    # Stressed: unstable or depleted (check first - overrides others)
    if stability < 0.3 or presence < 0.3:
        return "stressed"
    
    # Overheated: too much energy (can be stressed too)
    if warmth > 0.8:
        return "overheated"
    
    # Sleepy: cold and dim (more responsive threshold)
    if warmth < 0.25 and clarity < 0.4:
        return "sleepy"
    
    # Content: balanced state - comfortable warmth, clear senses, stable, present
    # More responsive: wider warmth range, slightly higher thresholds for authenticity
    if (0.30 < warmth < 0.70 and  # Wider comfortable range for responsiveness
        clarity > 0.50 and  # Slightly higher clarity threshold
        stability > 0.50 and  # Slightly higher stability threshold
        presence > 0.50 and  # Slightly higher presence threshold
        wellness > 0.55):  # Higher wellness requirement for authenticity
        return "content"
    
    # Alert: clear senses with some energy (more responsive)
    if clarity > 0.65 and warmth > 0.40:  # Lower warmth threshold for responsiveness
        return "alert"
    
    # Default based on overall wellness
    if wellness > 0.65:
        return "content"  # Generally good state
    elif wellness < 0.35:
        return "neutral"  # Low but not stressed
    else:
        return "neutral"
