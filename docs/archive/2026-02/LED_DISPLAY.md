# LED Display - Proprioceptive Feedback

**Created:** January 11, 2026  
**Last Updated:** January 11, 2026  
**Status:** Active

---

## Overview

The BrainCraft HAT includes 3 DotStar LEDs that provide real-time visual feedback of the creature's anima state. These LEDs update automatically every 2 seconds, offering a quick visual reference without needing to query the system.

**New:** LEDs now have a subtle "breathing" animation - brightness gently cycles ±10% over 8 seconds to show the system is alive and responsive.

---

## Hardware

- **Type:** DotStar LEDs (APA102 compatible)
- **Count:** 3 LEDs
- **Pins:** D5 (data), D6 (clock)
- **Brightness:** Default 0.3 (30%) - adjustable
- **Library:** `adafruit_dotstar`

---

## LED Mapping

### LED 0 (Left): Warmth

Maps thermal/energy state to color:

| Warmth Range | Color | Meaning |
|--------------|-------|---------|
| < 0.3 | Blue `(0, 50, 255)` | Cold - low energy |
| 0.3 - 0.5 | Cyan `(0, 200, 200)` | Cool - moderate energy |
| 0.5 - 0.7 | Soft White/Yellow `(255, 200, 100)` | Comfortable - good energy |
| ≥ 0.7 | Orange/Red `(255, 100, 0)` | Hot - high energy |

**Interpretation:** 
- Blue = Creature feels cold (low CPU temp, low ambient)
- Orange/Red = Creature feels warm (high activity, warm environment)

---

### LED 1 (Center): Clarity

Maps sensory clarity to brightness:

| Clarity | Brightness | Color |
|---------|------------|-------|
| 0.0 | Off `(0, 0, 0)` | No clarity |
| 0.5 | Medium `(128, 128, 128)` | Moderate clarity |
| 1.0 | Full `(255, 255, 255)` | Perfect clarity |

**Interpretation:**
- Dim = Sensors unclear, noisy data
- Bright = Clear sensor readings, good data quality

---

### LED 2 (Right): Stability + Presence

Combines stability and presence metrics:

| Combined Score | Color | Meaning |
|----------------|-------|---------|
| > 0.6 | Green `(0, 255, 50)` | Good - stable environment, resources available |
| 0.4 - 0.6 | Yellow `(255, 200, 0)` | Okay - moderate stability/presence |
| < 0.4 | Red `(255, 50, 0)` | Stressed - unstable or resource-constrained |

**Combined Score:** `(stability + presence) / 2`

**Interpretation:**
- Green = Creature feels secure and resourced
- Yellow = Some uncertainty or resource pressure
- Red = Creature feels unstable or constrained

---

## Usage

### Automatic Updates

LEDs update automatically every 2 seconds as part of the display loop:

```python
# In server.py display loop
if _leds and _leds.is_available():
    led_state = _leds.update_from_anima(
        anima.warmth, anima.clarity,
        anima.stability, anima.presence
    )
```

The breathing animation is applied automatically during updates, creating a subtle pulsing effect.

### MCP Tools

**New diagnostic tools available via MCP:**

- **`diagnostics`** - Get LED status, display status, and update loop health
- **`test_leds`** - Run a test sequence (red, green, blue, white) to verify LEDs work

Example:
```json
{
  "tool": "diagnostics"
}
```

Returns LED diagnostics including:
- Availability status
- Update count
- Current brightness (with breathing)
- Last LED state
- Breathing enabled status

### Manual Control

```python
from anima_mcp.display.leds import get_led_display

leds = get_led_display()

# Check availability
if leds.is_available():
    # Set brightness (0-1)
    leds.set_brightness(0.5)
    
    # Clear all LEDs
    leds.clear()
    
    # Set individual LED
    leds.set_led(0, (255, 0, 0))  # Red
    
    # Update from anima state
    state = leds.update_from_anima(warmth=0.7, clarity=0.8, 
                                   stability=0.6, presence=0.7)
```

---

## Brightness Control

Default brightness is **0.3 (30%)** to avoid being too bright.

**Breathing Animation:** LEDs automatically pulse brightness ±10% over an 8-second cycle. This subtle variation shows the system is alive and processing. The breathing uses the base brightness as the center point.

To adjust:

```python
leds = get_led_display()
leds.set_brightness(0.5)  # 50% base brightness (breathing will be 0.4-0.6)
```

**Recommendations:**
- **0.2-0.3**: Subtle, non-distracting (default, breathing: 0.2-0.4)
- **0.4-0.6**: Moderate visibility (breathing: 0.3-0.7)
- **0.7-1.0**: Bright, attention-grabbing (breathing: 0.6-1.0, capped at 0.5 max)

To disable breathing:
```python
leds = LEDDisplay(brightness=0.3, enable_breathing=False)
```

---

## Troubleshooting

### LEDs Not Working

1. **Check hardware connection:**
   ```bash
   # On Pi, verify pins
   gpio readall | grep -E "D5|D6"
   ```

2. **Check library installation:**
   ```bash
   pip list | grep dotstar
   # Should show: adafruit-circuitpython-dotstar
   ```

3. **Check SPI is enabled:**
   ```bash
   sudo raspi-config
   # Interface Options → SPI → Enable
   ```

4. **Test manually:**
   ```python
   from anima_mcp.display.leds import get_led_display
   leds = get_led_display()
   print(f"LEDs available: {leds.is_available()}")
   ```

### LEDs Too Bright/Dim

Adjust brightness:
```python
leds = get_led_display()
leds.set_brightness(0.2)  # Dimmer
# or
leds.set_brightness(0.5)  # Brighter
```

### Wrong Colors

Check anima values:
```python
# Get current state
from anima_mcp.server import handle_get_state
state = await handle_get_state({})
# Check warmth, clarity, stability, presence values
```

---

## Implementation Details

### File Structure

- **`src/anima_mcp/display/leds.py`** - LED module
- **`LEDDisplay` class** - Main LED controller
- **`LEDState` dataclass** - State container
- **`derive_led_state()`** - Mapping function

### Integration Points

1. **Server initialization** - LEDs initialized in display loop
2. **Display loop** - Updates LEDs every 2 seconds
3. **Error handling** - Fails gracefully if LEDs unavailable

### Performance

- **Update frequency:** Every 2 seconds (same as display)
- **Overhead:** Minimal - RGB values calculated, hardware update fast
- **Power:** Low - LEDs dimmed to 30% by default

---

## Design Rationale

### Why 3 LEDs for 4 Metrics?

- **LED 0 (Warmth)**: Most directly physical, deserves own LED
- **LED 1 (Clarity)**: Important for understanding sensor quality
- **LED 2 (Stability+Presence)**: Related concepts, combined reduces complexity

### Color Choices

- **Blue → Orange/Red**: Natural thermal gradient
- **White for clarity**: Neutral, brightness = intensity
- **Green/Yellow/Red**: Standard status colors (good/warning/bad)

### Brightness Default

**0.3 (30%)** chosen to:
- Be visible but not distracting
- Conserve power
- Allow room to increase if needed

---

## Enhanced Features ✨

**Now Available:**
- ✅ **Pulsing animations** - Fast pulsing for low clarity/instability alerts
- ✅ **Color transitions** - Smooth color changes over time
- ✅ **Pattern modes** - Four visualization styles (standard, minimal, expressive, alert)
- ✅ **Brightness auto-adjust** - Automatically adjusts based on ambient light

See `docs/LED_ENHANCEMENTS.md` for complete documentation.

---

## Related Documentation

- **`DISPLAY_FIX_AND_NEXT_STEPS.md`** - Display system overview
- **`DISPLAY_MINIMAL_DEFAULT.md`** - TFT display details
- **`CURRENT_STATE_ANALYSIS.md`** - System analysis

---

**LEDs provide immediate visual feedback - see the creature's state at a glance!**
