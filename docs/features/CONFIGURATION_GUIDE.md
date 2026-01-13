# Configuration Guide - Lumen's Nervous System

**Created:** January 11, 2026  
**Last Updated:** January 11, 2026  
**Status:** Active

---

## Overview

Configuration values define **how Lumen interprets its senses** - they're the creature's nervous system calibration. Making these configurable lets Lumen adapt to different environments, hardware, and learn over time.

---

## Configuration File

Configuration is stored in `anima_config.yaml` (or `anima_config.json`).

**Location:** Same directory as `anima.db` (usually project root or current working directory)

**Default:** If no config file exists, sensible defaults are used (sea level, standard ranges).

---

## Nervous System Calibration

### Thermal Ranges

```yaml
nervous_system:
  cpu_temp_min: 40.0      # Below this = cold
  cpu_temp_max: 80.0      # Above this = hot
  
  ambient_temp_min: 15.0  # Below this = cold environment
  ambient_temp_max: 35.0  # Above this = hot environment
```

**Adaptation examples:**
- **Pi Zero**: Lower CPU temp range (30-70°C)
- **Pi 4**: Higher CPU temp range (40-85°C)
- **Summer**: Higher ambient range (20-40°C)
- **Winter**: Lower ambient range (5-25°C)

---

### Ideal Values

```yaml
  humidity_ideal: 45.0    # Ideal humidity (%)
  pressure_ideal: 833.0   # Local barometric pressure baseline (hPa)
```

**Adaptation examples:**
- **Colorado (~5400ft)**: `pressure_ideal: 833.0`
- **Sea level**: `pressure_ideal: 1013.25`
- **Dry climate**: `humidity_ideal: 30.0`
- **Humid climate**: `humidity_ideal: 60.0`

---

### Component Weights

Control how much each sensor contributes to anima dimensions:

```yaml
  warmth_weights:
    cpu_temp: 0.3
    cpu_usage: 0.25
    ambient_temp: 0.25
    neural: 0.2
```

**Adjusting weights:**
- Increase `neural` weight if Brain HAT is primary sensor
- Increase `ambient_temp` weight in outdoor deployments
- Adjust based on sensor reliability

---

## Display Configuration

```yaml
display:
  led_brightness: 0.3           # Base brightness (0-1)
  update_interval: 2.0          # Update frequency (seconds)
  breathing_enabled: true        # Enable breathing animation
  breathing_cycle: 8.0          # Breathing cycle (seconds)
  breathing_variation: 0.1       # Brightness variation (±10%)
```

---

## Usage

### Get Current Calibration

```json
{
  "tool": "get_calibration"
}
```

Returns:
- Current calibration values
- Config file path
- Whether config file exists

### Update Calibration

```json
{
  "tool": "set_calibration",
  "arguments": {
    "updates": {
      "ambient_temp_min": 10.0,
      "ambient_temp_max": 30.0,
      "pressure_ideal": 833.0
    }
  }
}
```

**Partial updates supported** - only specify values you want to change.

---

## Environment Adaptation

### Example: Colorado Altitude

```yaml
nervous_system:
  ambient_temp_min: 5.0   # Colder winters
  ambient_temp_max: 30.0  # Cooler summers
  pressure_ideal: 833.0   # ~5400ft elevation
  humidity_ideal: 35.0    # Dry climate
```

### Example: Sea Level

```yaml
nervous_system:
  ambient_temp_min: 15.0
  ambient_temp_max: 35.0
  pressure_ideal: 1013.25  # Sea level standard
  humidity_ideal: 50.0
```

### Example: Different Hardware

```yaml
nervous_system:
  cpu_temp_min: 30.0  # Pi Zero runs cooler
  cpu_temp_max: 70.0
```

---

## Adaptive Learning (Future)

The configuration system supports adaptive learning:

```python
from anima_mcp.config import ConfigManager

config = ConfigManager()

# Observe environment over time
observed_temps = [18, 20, 22, 19, 21]  # Recent ambient temps
observed_pressures = [833, 834, 832]    # Recent pressures

# Adapt calibration
adapted = config.adapt_to_environment(
    observed_temps, observed_pressures, []
)

# Save adapted calibration
config.save(AnimaConfig(nervous_system=adapted))
```

---

## Validation

Configuration is validated before use:

- **Ranges**: min < max
- **Values**: Within reasonable bounds
- **Weights**: Sum to ~1.0 (with tolerance)

Invalid config falls back to defaults with warning.

---

## File Format

**YAML** (recommended):
```yaml
nervous_system:
  cpu_temp_min: 40.0
  cpu_temp_max: 80.0
```

**JSON** (also supported):
```json
{
  "nervous_system": {
    "cpu_temp_min": 40.0,
    "cpu_temp_max": 80.0
  }
}
```

---

## Migration

**From hardcoded values:**
- Old code had ranges hardcoded in `anima.py`
- New code uses `anima_config.yaml`
- Defaults match old values (backward compatible)
- No migration needed - works out of the box

---

## Related

- **`CONFIGURATION_VISION.md`** - Design philosophy
- **`anima_config.yaml.example`** - Example config file
- **`get_calibration` tool** - View current calibration
- **`set_calibration` tool** - Update calibration

---

**Configuration is Lumen's nervous system - make it adapt to its environment!**
