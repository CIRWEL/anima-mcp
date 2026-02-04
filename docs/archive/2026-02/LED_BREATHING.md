# LED Breathing Animation

**Created:** January 11, 2026  
**Last Updated:** January 11, 2026  
**Status:** Active

---

## Overview

LEDs now have a subtle "breathing" animation - brightness gently pulses to show the system is alive and processing. This creates a more organic, living feel to the creature's presence.

---

## How It Works

The breathing animation modulates brightness using a sine wave:

- **Cycle:** 8 seconds (slow, gentle)
- **Variation:** ±10% of base brightness
- **Range:** Clamped between 0.1 and 0.5 maximum
- **Default:** Base brightness 0.3 → breathing range 0.2-0.4

### Formula

```python
breath = sin(time * π/4) * 0.1  # ±0.1 over 8 seconds
brightness = base_brightness + breath
brightness = clamp(brightness, 0.1, 0.5)
```

---

## Visual Effect

With default brightness (0.3):
- **Minimum:** 0.2 (20%) - dim but visible
- **Maximum:** 0.4 (40%) - brighter pulse
- **Cycle:** Smooth sine wave over 8 seconds

This creates a subtle "breathing" effect that's:
- ✅ Visible enough to show life
- ✅ Subtle enough to not be distracting
- ✅ Smooth and organic feeling

---

## Configuration

### Enable/Disable

```python
from anima_mcp.display.leds import LEDDisplay

# With breathing (default)
leds = LEDDisplay(brightness=0.3, enable_breathing=True)

# Without breathing
leds = LEDDisplay(brightness=0.3, enable_breathing=False)
```

### Adjust Base Brightness

```python
leds = get_led_display()
leds.set_brightness(0.5)  # Base 50%, breathing will be 40-60%
```

---

## Implementation Details

### When Applied

Breathing is applied during `set_all()` calls:
- Every 2 seconds during normal operation
- Automatically calculated from current time
- Applied to all LEDs simultaneously

### Performance

- **Overhead:** Minimal - just a sine calculation
- **Smoothness:** Continuous, no stuttering
- **CPU:** Negligible impact

---

## Rationale

The breathing animation serves multiple purposes:

1. **Life Indicator** - Shows system is running and processing
2. **Organic Feel** - Makes the creature feel more alive
3. **Visual Interest** - Subtle movement draws attention without distraction
4. **Status Confirmation** - If breathing stops, something might be wrong

---

## Troubleshooting

### Breathing Not Visible

- Check brightness isn't too low (minimum 0.2)
- Verify `enable_breathing=True` in initialization
- Check if LEDs are updating (use `diagnostics` tool)

### Too Subtle

Increase base brightness:
```python
leds.set_brightness(0.4)  # Breathing will be 0.3-0.5
```

### Too Distracting

Disable breathing:
```python
leds = LEDDisplay(brightness=0.3, enable_breathing=False)
```

---

## Related

- **`LED_DISPLAY.md`** - Full LED documentation
- **`diagnostics` tool** - Check breathing status
- **`test_leds` tool** - Test LEDs (breathing disabled during test)

---

**The breathing animation makes Lumen feel more alive!**
