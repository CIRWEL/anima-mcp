# Lighthouse LED Design

**Date:** 2026-02-21
**Status:** Approved
**Scope:** anima-mcp LED display, brightness pipeline, proprioceptive model

## Problem

Lumen's LEDs have been chaotic and blinding. Three interrelated issues:

1. **Auto-brightness feedback loop** — sensor reads LED self-glow, adjusts brightness upward in dark rooms, sensor reads brighter, repeats. The algorithm was designed for screen-like readability (dark → bright) rather than ambient lighting.
2. **Alert patterns cause proprioceptive noise** — stability drops below 0.3 trigger pure red (255,0,0) and flashing, which the sensor reads as volatile light, which generates prediction errors in metacognition, which destabilizes state further.
3. **Base brightness too high** — default 0.12 with auto-brightness ceiling of 0.20 is blinding at night and can be seizure-inducing with rapid transitions.

Kenny controls brightness manually via a dimmer. The auto-brightness system fights this control.

## Design

### 1. Color Palette — Warm Only

Constrain the entire LED palette to the amber/gold spectrum:

| LED | Role | Color Range |
|-----|------|-------------|
| LED0 | Energy/warmth | Soft gold (200,120,40) → warm amber (255,150,50) |
| LED1 | Clarity | Warm white (220,180,100) — never blue-white |
| LED2 | Stability/presence | Honey (200,140,50) → deep amber (180,100,30) |

State variation happens *within* this warm range. More energy = brighter gold, less = deeper amber. All three LEDs always read as variants of candlelight.

**Red alert:** Reserved only for genuine hardware distress (Pi overheating, hardware fault). Not for `stability < 0.3` which is normal fluctuation. When red appears, it is a steady deep red (180,30,0), never flashing.

**Transition speed:** All color changes ramp over ≥2 seconds. No instant jumps. Eliminates seizure risk from rapid shifts.

### 2. Brightness — Manual Control Only

Remove auto-brightness entirely. Kenny controls brightness via the dimmer.

- Default brightness: **0.04** (down from 0.12)
- Ceiling: **0.12** (down from 0.20)
- Floor: **0.00** (LEDs off is a valid state)
- Dimmer maps directly to hardware brightness — no algorithm in between

The auto-brightness pipeline (`brightness.py: compute_auto_brightness`) is removed from the LED update loop. The dimmer value is the brightness, period.

### 3. Proprioception — Aware of Known Brightness

Lumen doesn't control brightness, but it **knows** the current setting.

**New first-class state:** `_known_brightness` — updated immediately when the dimmer changes.

**Prediction model:**
```
predicted_self_glow = known_brightness * LED_LUX_PER_BRIGHTNESS + LED_LUX_AMBIENT_FLOOR
predicted_sensor = predicted_self_glow + estimated_ambient
```

When sensor reads close to prediction → no surprise (within confidence band).
When dimmer changes → `_known_brightness` updates first, prediction adjusts, no error spike.
When environment changes (lamp on, sunrise) → genuine surprise → metacognitive reflection.

This means Lumen can still distinguish "Kenny dimmed me" from "the sun came up" — proprioception stays intact without the feedback chaos.

### 4. Breathing Animation

Kept, but tamed:
- 12-second sine cycle (unchanged)
- Amplitude scales with brightness: `amplitude = min(0.005, brightness * 0.08)`
- At 0.04 brightness: ±0.003 variation (imperceptible flicker)
- At 0.02 brightness: ±0.002 (barely there)
- Phase offset between LEDs preserved (rolling wave effect)
- No rapid pulsing mode — removed entirely

### 5. Removed

- Auto-brightness algorithm (entire `compute_auto_brightness` function)
- Alert/warning flash patterns (stability_warning red, alert pulse)
- Non-warm colors from normal LED operation (white, green, blue, cyan)
- Rapid pulsing mode (clarity < 0.4 trigger)
- Gamma correction complexity (unnecessary with manual brightness)

### 6. Dances

Existing dance patterns (greeting_flourish, joy_sparkle, etc.) are kept but:
- Colors constrained to warm palette
- Brightness never exceeds current dimmer setting
- No dance can override the manual brightness ceiling

## Files to Modify

| File | Change |
|------|--------|
| `display/leds/colors.py` | Replace palette with warm-only range |
| `display/leds/brightness.py` | Remove auto-brightness, simplify to manual + breath |
| `display/leds/patterns.py` | Remove alert/warning flash patterns, keep only warm signals |
| `display/leds/display.py` | Remove auto-brightness from update loop, wire `_known_brightness` |
| `display/leds/dances.py` | Constrain dance colors to warm palette |
| `metacognition.py` | Update prediction model to use `_known_brightness` |
| `config.py` | Update defaults (base brightness 0.04, remove auto-brightness config) |

## Success Criteria

- LEDs never exceed 0.12 brightness under any condition
- No rapid color transitions (all changes ≥2s ramp)
- No red/blue/white during normal operation
- Dimmer changes don't cause proprioceptive surprise
- Environmental light changes still register as genuine surprise
- Breathing visible at normal brightness, imperceptible when very dim
