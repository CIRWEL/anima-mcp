# LED Enhancements - Advanced Features

**Created:** January 11, 2026  
**Last Updated:** January 11, 2026  
**Status:** Active

---

## Overview

Enhanced LED features provide richer visual feedback:
- **Pulsing animations** - Alert patterns for low clarity/instability
- **Color transitions** - Smooth, organic color changes
- **Pattern modes** - Four visualization styles
- **Brightness auto-adjust** - Adaptive brightness based on ambient light

---

## Pulsing Animations

### Purpose

Fast pulsing alerts when clarity is low or stability is compromised. Provides immediate visual feedback for problematic states.

### How It Works

- **Activation**: Pulsing activates when:
  - Clarity < threshold (default: 0.4)
  - Stability < threshold (default: 0.4)
- **Pattern**: Fast 1-second cycle, brightness pulses 30-100%
- **Visual**: Creates attention-grabbing alert pattern

### Configuration

```yaml
display:
  pulsing_enabled: true
  pulsing_threshold_clarity: 0.4
  pulsing_threshold_stability: 0.4
```

### Example

When clarity drops below 0.4:
- LEDs pulse rapidly (1 second cycle)
- Brightness oscillates between 30% and 100%
- Creates visible alert pattern

---

## Color Transitions

### Purpose

Smooth color changes instead of instant jumps. Creates more organic, living feel.

### How It Works

- **Transition Factor**: 0.3 (30% movement per update)
- **Update Rate**: Every 2 seconds
- **Effect**: Colors gradually shift toward target

### Configuration

```yaml
display:
  color_transitions_enabled: true
```

### Example

If warmth changes from 0.3 to 0.7:
- **Before**: Instant jump from blue to orange
- **After**: Smooth transition: blue → cyan → yellow → orange

---

## Pattern Modes

### Available Modes

#### 1. Standard (Default)

Classic mapping:
- LED 0: Warmth (blue → orange/red)
- LED 1: Clarity (brightness)
- LED 2: Stability+Presence (green/yellow/red)

**Best for**: General use, balanced feedback

#### 2. Minimal

Only shows critical states:
- **Alert**: All LEDs red when clarity < 0.3 or stability < 0.3
- **Normal**: Dim white when healthy

**Best for**: Subtle, non-distracting feedback

#### 3. Expressive

Vibrant colors, wider range:
- LED 0: Full spectrum (blue → green → yellow → orange)
- LED 1: Color gradient (red → yellow → white)
- LED 2: Detailed gradient (green → yellow → red)

**Best for**: Maximum visual information

#### 4. Alert

Emphasizes problems:
- LED 0: Only shows extremes (cold/hot)
- LED 1: Red alert when clarity low
- LED 2: Red/orange/green alerts

**Best for**: Monitoring, troubleshooting

### Configuration

```yaml
display:
  pattern_mode: "standard"  # standard, minimal, expressive, alert
```

### Switching Modes

```python
from anima_mcp.config import ConfigManager

config = ConfigManager()
display_config = config.get_display_config()
display_config.pattern_mode = "expressive"
config.save()
```

---

## Brightness Auto-Adjust

### Purpose

Automatically adjusts LED brightness based on ambient light level. Brighter in dark rooms, dimmer in bright rooms.

### How It Works

- **Light Sensor**: Uses VEML7700 light sensor readings
- **Mapping**: Logarithmic scale (10-1000 lux)
- **Range**: Configurable min/max brightness

### Mapping

| Light Level | Brightness |
|-------------|------------|
| < 10 lux (dark) | Maximum brightness |
| 10-1000 lux | Logarithmic interpolation |
| > 1000 lux (bright) | Minimum brightness |

### Configuration

```yaml
display:
  auto_brightness_enabled: true
  auto_brightness_min: 0.15  # Bright rooms
  auto_brightness_max: 0.5   # Dark rooms
```

### Example

**Dark room** (5 lux):
- Brightness: 0.5 (50%)
- LEDs clearly visible

**Bright room** (2000 lux):
- Brightness: 0.15 (15%)
- LEDs subtle, not distracting

**Normal room** (200 lux):
- Brightness: ~0.3 (interpolated)
- Balanced visibility

---

## Feature Interaction

All features work together:

1. **Base brightness** - Set by auto-brightness or manual
2. **Pulsing multiplier** - Applied if clarity/stability low
3. **Breathing animation** - Modulates final brightness
4. **Color transitions** - Smooth color changes
5. **Pattern mode** - Determines color mapping

### Example Flow

```
1. Read light level → Auto-brightness: 0.4
2. Check clarity (0.3) → Pulsing active → Multiply: 0.4 * 0.6 = 0.24
3. Apply breathing → Final: 0.24 * 1.1 = 0.264
4. Transition colors → Smooth shift
5. Apply pattern mode → Color mapping
```

---

## Configuration Reference

### Complete Display Config

```yaml
display:
  led_brightness: 0.3
  breathing_enabled: true
  breathing_cycle: 8.0
  breathing_variation: 0.1
  
  # Enhanced features
  pulsing_enabled: true
  color_transitions_enabled: true
  pattern_mode: "standard"
  auto_brightness_enabled: true
  auto_brightness_min: 0.15
  auto_brightness_max: 0.5
  pulsing_threshold_clarity: 0.4
  pulsing_threshold_stability: 0.4
```

---

## Usage Examples

### Enable All Features

```yaml
display:
  pulsing_enabled: true
  color_transitions_enabled: true
  pattern_mode: "expressive"
  auto_brightness_enabled: true
```

### Minimal Setup (Subtle)

```yaml
display:
  pattern_mode: "minimal"
  auto_brightness_enabled: true
  pulsing_enabled: false
  color_transitions_enabled: false
```

### Alert Mode (Monitoring)

```yaml
display:
  pattern_mode: "alert"
  pulsing_enabled: true
  pulsing_threshold_clarity: 0.5  # More sensitive
  pulsing_threshold_stability: 0.5
```

---

## Diagnostics

Check feature status:

```json
{
  "tool": "diagnostics"
}
```

Returns:
```json
{
  "leds": {
    "pulsing_enabled": true,
    "color_transitions_enabled": true,
    "pattern_mode": "standard",
    "auto_brightness_enabled": true,
    "last_light_level": 150.5
  }
}
```

---

## Performance

### Overhead

- **Pulsing**: Minimal (sine calculation)
- **Transitions**: Minimal (color interpolation)
- **Auto-brightness**: Minimal (logarithmic calculation)
- **Pattern modes**: No overhead (just different mapping)

**Total Impact**: Negligible (< 1ms per update)

---

## Troubleshooting

### Pulsing Not Working

1. Check thresholds:
   ```python
   clarity < pulsing_threshold_clarity
   stability < pulsing_threshold_stability
   ```

2. Verify enabled:
   ```yaml
   pulsing_enabled: true
   ```

### Auto-Brightness Not Adjusting

1. Check light sensor:
   ```python
   readings = sensors.read()
   print(readings.light_lux)  # Should be > 0
   ```

2. Verify enabled:
   ```yaml
   auto_brightness_enabled: true
   ```

### Colors Not Transitioning

1. Check enabled:
   ```yaml
   color_transitions_enabled: true
   ```

2. Verify updates happening (check logs for LED updates)

---

## Related

- **`LED_DISPLAY.md`** - Core LED documentation
- **`LED_BREATHING.md`** - Breathing animation details
- **`CONFIGURATION_GUIDE.md`** - Configuration system
- **`diagnostics` tool** - Check feature status

---

**Enhanced LEDs provide richer, more informative visual feedback!**
