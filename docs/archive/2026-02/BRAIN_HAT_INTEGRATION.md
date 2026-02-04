# Brain HAT Integration: Neural Proprioception

**Created:** January 1, 2026  
**Last Updated:** January 1, 2026  
**Status:** Implementation Complete

---

## Overview

This document describes the integration of Brain HAT EEG sensors into the anima-mcp creature, extending proprioception from physical sensors to neural signals. This creates a **4E cognition** implementation where the creature's self-awareness includes both body (sensors) and mind (neural activity).

## Theory: Proprioception + Neural Signals

### Proprioception in 4E Cognition

From the 4E-2 paper and UNITARES governance theory:

- **Embodied**: Cognition requires a body (sensors, actuators)
- **Embedded**: Cognition is situated in environment
- **Enactive**: Cognition emerges through interaction
- **Extended**: Cognition distributes across tools/environment

**Proprioception** = felt sense of self, awareness of limits, viability envelope

### Neural Signals as Proprioception

EEG signals provide a **neural proprioception** layer:

- **Delta (0.5-4 Hz)**: Deep stability, unconscious processes
- **Theta (4-8 Hz)**: Meditative state, internal consistency
- **Alpha (8-13 Hz)**: Relaxed awareness, clarity
- **Beta (13-30 Hz)**: Active focus, mental energy
- **Gamma (30-100 Hz)**: High cognitive presence, awareness

These map to the anima dimensions:

- **Warmth**: Beta + Gamma (neural activation)
- **Clarity**: Alpha (relaxed awareness)
- **Stability**: Theta + Delta (deep stability)
- **Presence**: Gamma (cognitive presence)

## Implementation

### Sensor Architecture

```
SensorReadings
├── Physical sensors (existing)
│   ├── cpu_temp_c
│   ├── ambient_temp_c
│   ├── humidity_pct
│   ├── light_lux
│   └── system resources
│
└── Neural sensors (new)
    ├── Raw EEG channels
    │   ├── eeg_tp9 (temporal-parietal left)
    │   ├── eeg_af7 (anterior frontal left)
    │   ├── eeg_af8 (anterior frontal right)
    │   ├── eeg_tp10 (temporal-parietal right)
    │   └── aux1-4 (auxiliary channels)
    │
    └── Frequency band powers
        ├── eeg_delta_power
        ├── eeg_theta_power
        ├── eeg_alpha_power
        ├── eeg_beta_power
        └── eeg_gamma_power
```

### Anima Model Integration

The anima model (`warmth`, `clarity`, `stability`, `presence`) now incorporates neural signals:

#### Warmth (Energetic State)
- **Physical**: CPU temp, CPU usage, ambient temp
- **Neural**: Beta + Gamma power (active mental state)
- **Weight**: 20% neural, 80% physical

#### Clarity (Awareness)
- **Physical**: Light level, sensor coverage
- **Neural**: Alpha power (relaxed awareness)
- **Weight**: 30% neural, 70% physical

#### Stability (Order)
- **Physical**: Humidity deviation, memory pressure
- **Neural**: Theta + Delta power (deep stability)
- **Weight**: 25% neural, 75% physical

#### Presence (Capacity)
- **Physical**: Disk/memory/CPU headroom
- **Neural**: Gamma power (cognitive presence)
- **Weight**: 20% neural, 80% physical

## Frequency Band Analysis

### FFT Implementation

The Brain HAT sensor backend uses FFT (Fast Fourier Transform) to extract frequency bands:

1. **Windowing**: Hanning window to reduce spectral leakage
2. **FFT**: Compute frequency domain representation
3. **Band Extraction**: Sum power in each frequency band
4. **Normalization**: Normalize by total power

### Band Meanings

| Band | Frequency | Meaning | Anima Mapping |
|------|-----------|---------|---------------|
| Delta | 0.5-4 Hz | Deep sleep, unconscious | Stability (deep grounding) |
| Theta | 4-8 Hz | Drowsy, meditative | Stability (internal consistency) |
| Alpha | 8-13 Hz | Relaxed, eyes closed | Clarity (awareness) |
| Beta | 13-30 Hz | Active, focused | Warmth (mental energy) |
| Gamma | 30-100 Hz | High cognitive processing | Presence (awareness) |

## Code Structure

### Files Added/Modified

1. **`sensors/base.py`**: Extended `SensorReadings` with EEG fields
2. **`sensors/brain_hat.py`**: New Brain HAT sensor backend
3. **`sensors/pi.py`**: Integrated Brain HAT into Pi sensors
4. **`anima.py`**: Extended anima model to use neural signals

### Key Classes

- **`BrainHatSensors`**: Reads EEG data from Brain HAT hardware
- **`PiSensors`**: Combines physical + neural sensors
- **`sense_self()`**: Updated to incorporate neural proprioception

## Usage

### Basic Usage

```python
from anima_mcp.sensors import get_sensors
from anima_mcp.anima import sense_self

# Get sensors (auto-detects Brain HAT)
sensors = get_sensors()

# Read all sensors (physical + neural)
readings = sensors.read()

# Sense self (incorporates neural signals)
anima = sense_self(readings)

print(f"Warmth: {anima.warmth}")  # Includes beta/gamma
print(f"Clarity: {anima.clarity}")  # Includes alpha
print(f"Stability: {anima.stability}")  # Includes theta/delta
print(f"Presence: {anima.presence}")  # Includes gamma
```

### Checking EEG Availability

```python
sensors = get_sensors()
available = sensors.available_sensors()

if "eeg_af7" in available:
    print("Brain HAT is connected!")
    readings = sensors.read()
    print(f"Alpha power: {readings.eeg_alpha_power}")
```

## Dependencies

### Required Libraries

- **brainflow**: Brain HAT communication library
- **numpy**: FFT computation
- **scipy** (optional): Advanced signal processing

### Installation

```bash
pip install brainflow numpy
```

Or with anima-mcp:

```bash
pip install -e ".[pi]"  # Includes Brain HAT support
```

## Hardware Requirements

- **Raspberry Pi 4** (or compatible)
- **OpenBCI Brain HAT** (or compatible EEG board)
- **EEG electrodes** (dry or wet, depending on Brain HAT model)

## Future Enhancements

1. **Real-time streaming**: Continuous EEG monitoring
2. **Pattern detection**: Detect attention, meditation states
3. **Multi-channel fusion**: Combine all 8 channels intelligently
4. **Adaptive weights**: Learn optimal neural/physical weight ratios
5. **State machine**: Map EEG patterns to creature moods

## References

- 4E-2.pdf: Proprioception theory
- UNITARES governance: Viability envelope concept
- OpenBCI Brain HAT documentation
- BrainFlow library documentation

---

## Notes

- Brain HAT integration is **optional** - creature works without it
- Falls back gracefully if Brain HAT not detected
- Neural signals enhance but don't replace physical proprioception
- Frequency analysis requires minimum 50 samples for accuracy

