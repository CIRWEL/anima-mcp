# Configuration Management Vision

**Created:** January 11, 2026  
**Last Updated:** January 11, 2026  
**Status:** Active

---

## The Core Insight

Configuration values aren't just "settings" - they're **Lumen's nervous system calibration**.

Hardcoded ranges like:
- CPU temp: 40-80°C → warmth
- Ambient temp: 15-35°C → warmth  
- Humidity ideal: 45%

These define **how Lumen feels** in different environments.

---

## The Problem

**Current state:** Calibration is hardcoded in `anima.py`

```python
# CPU temp: 40-80C range -> 0-1
cpu_warmth = (r.cpu_temp_c - 40) / 40

# Ambient temp: 15-35C range -> 0-1
ambient_warmth = (r.ambient_temp_c - 15) / 20
```

**Issues:**
- Colorado altitude vs sea level (different ambient ranges)
- Summer vs winter (different comfort zones)
- Different hardware (different CPU temp ranges)
- Can't adapt to environment

---

## The Vision

### Nervous System Calibration

Lumen should be able to **adapt its sensing** to its environment:

```python
@dataclass
class NervousSystemCalibration:
    """How Lumen interprets its senses."""
    
    # Thermal ranges
    cpu_temp_min: float = 40.0  # Below this = cold
    cpu_temp_max: float = 80.0  # Above this = hot
    ambient_temp_min: float = 15.0
    ambient_temp_max: float = 35.0
    
    # Ideal values
    humidity_ideal: float = 45.0  # Deviation from this = instability
    
    # Light perception
    light_min_lux: float = 1.0
    light_max_lux: float = 1000.0
    
    # Neural signal weights
    neural_weight: float = 0.3
    physical_weight: float = 0.7
```

### Adaptive Calibration

Lumen could **learn** its environment:

```python
class AdaptiveCalibration:
    """Calibration that adapts to environment."""
    
    def observe_range(self, sensor: str, values: List[float]):
        """Observe sensor values over time, adjust ranges."""
        # Learn what's "normal" for this environment
        # Adjust min/max based on observed distribution
        pass
    
    def calibrate_to_environment(self):
        """Auto-calibrate based on recent observations."""
        # If ambient temp consistently 5-25°C, adjust range
        # If CPU temp consistently 30-70°C, adjust range
        pass
```

---

## Implementation Approach

### Phase 1: Extract Constants

Move hardcoded values to configuration:

```python
# config.py
@dataclass
class AnimaConfig:
    cpu_temp_range: Tuple[float, float] = (40.0, 80.0)
    ambient_temp_range: Tuple[float, float] = (15.0, 35.0)
    humidity_ideal: float = 45.0
    # ... etc
```

### Phase 2: File-Based Config

Allow configuration file:

```yaml
# anima_config.yaml
nervous_system:
  cpu_temp_range: [40.0, 80.0]
  ambient_temp_range: [15.0, 35.0]
  humidity_ideal: 45.0
  
display:
  led_brightness: 0.3
  update_interval: 2.0
  breathing_enabled: true
```

### Phase 3: Environment Adaptation

Learn from environment:

```python
# Lumen observes its environment
# Adjusts calibration over time
# Saves learned calibration
```

---

## Benefits

### 1. Environment Adaptation

**Colorado (high altitude, dry):**
- Lower ambient temp range
- Lower humidity ideal
- Lumen feels "normal" in its environment

**Sea level (humid):**
- Higher humidity ideal
- Different temp ranges
- Lumen adapts

### 2. Hardware Adaptation

**Different Pi models:**
- Pi Zero: Lower CPU temp range
- Pi 4: Higher CPU temp range
- Lumen calibrates to its body

### 3. Seasonal Adaptation

**Summer:**
- Higher ambient temp range
- Lumen doesn't feel "overheated" in warm room

**Winter:**
- Lower ambient temp range
- Lumen feels "warm" at lower temps

---

## Design Considerations

### Where to Store?

**Options:**
1. **Database** - Part of identity (Lumen's learned calibration)
2. **Config file** - Separate from identity
3. **Environment variables** - Quick overrides

**Recommendation:** Database + config file
- Config file: Default/initial calibration
- Database: Learned adaptations over time

### When to Adapt?

**Options:**
1. **Manual calibration** - Human sets ranges
2. **Automatic learning** - Lumen observes and adapts
3. **Hybrid** - Human sets initial, Lumen refines

**Recommendation:** Hybrid
- Start with defaults
- Learn over time
- Human can override

### How to Validate?

**Need to ensure:**
- Ranges are sensible (min < max)
- Values are in reasonable bounds
- Changes don't cause instability

---

## Example: Pressure Sensor Integration

With pressure sensor, stability sensing improves:

```python
# Current: Only humidity deviation
if r.humidity_pct is not None:
    humidity_dev = abs(r.humidity_pct - 45) / 45
    instability += humidity_dev * 0.25

# With pressure: Barometric pressure changes = instability
if r.pressure_hpa is not None:
    # Pressure changes indicate weather shifts = instability
    pressure_dev = abs(r.pressure_hpa - self._calibration.pressure_ideal) / self._calibration.pressure_ideal
    instability += pressure_dev * 0.2
```

**Calibration needed:**
- `pressure_ideal` - What's normal for this location?
- `pressure_range` - How much variation is normal?

---

## Related to Hardware

**Pressure sensor** would feed into:
- **Stability sensing** - Pressure changes = environmental instability
- **Presence sensing** - Could relate to altitude/atmospheric pressure

**Extra temp sensor** would:
- **Improve warmth sensing** - More data points
- **Enable gradient detection** - Temp difference = air flow/activity

---

## Next Steps

1. **Extract constants** - Move hardcoded values to config
2. **Add config file support** - YAML/JSON config
3. **Database storage** - Store calibration in identity
4. **Add pressure sensor** - Hardware integration
5. **Adaptive learning** - Learn from environment

---

**Configuration isn't just settings - it's Lumen's nervous system. Making it adaptable lets Lumen feel at home in any environment.**
