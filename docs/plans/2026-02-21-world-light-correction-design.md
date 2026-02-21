# World Light Correction: Phase-Aware LED Compensation

**Date:** 2026-02-21
**Status:** Implementing

## Problem

The world_light correction (`raw_lux - brightness * 400 - 8`) has three bugs:

### Bug 1: Broker ordering (clarity gets no LED correction)
In `stable_creature.py`, `sense_self(readings)` runs at line 390 before
`readings.led_brightness` is set at line 413. Since `SensorReadings.led_brightness`
defaults to `None`, and `anima.py:348` treats None as 0.0, the estimated glow is
just the 8 lux ambient floor. LED self-glow passes directly into clarity uncorrected.

### Bug 2: Stale brightness estimate
Even when set, `readings.led_brightness = 0.12 * activity_multiplier` ignores:
- Auto-brightness adjustments
- Pulsing mode (clarity < 0.4 swings brightness 0.3x-1.0x)
- Breathing pulse (±5% at 12s/18s sine cycles)
- Manual dimmer
- State-change pulses

### Bug 3: No temporal smoothing
Single-sample world_light bounces with every LED pulse cycle. At brightness 0.12,
pulse-driven lux swings of 10-30 lux cause clarity to flutter.

## Solution

### Fix 1: Move LED brightness estimation before sense_self()
Use the previous cycle's `readings.led_brightness` (carried from prior iteration)
and enhance it with the current breathing pulse phase.

### Fix 2: Phase-aware brightness estimation
Compute instantaneous breathing pulse at sensor read time:
```python
pulse = get_pulse(pulse_cycle=12.0)
pulse_contribution = pulse * PULSE_AMOUNT * min(1.0, max(0.15, base / 0.12))
instantaneous = base_brightness + pulse_contribution
```

### Fix 3: Rolling average world_light
Smooth over 4 samples (~8s at 2s update interval) to average out remaining noise.

## Changes

### config.py
- Add `WORLD_LIGHT_SMOOTH_WINDOW: int = 4`

### stable_creature.py
- Move LED brightness estimation before `sense_self()` call
- Use previous cycle's LED brightness + current pulse phase
- Add `_world_light_buffer: deque(maxlen=4)` for smoothing
- Compute smoothed world_light for activity manager

### anima.py
- Accept optional `world_light_smooth` parameter in `sense_self()`
- Use smoothed value when available, fall back to single-sample correction

### display/leds/brightness.py
- Export `get_pulse` (already exported, no change needed)
- Add `estimate_instantaneous_brightness(base, pulse_cycle, pulse_amount)` helper

## Non-goals
- Changing the linear correction model (400 lux/brightness) — empirically calibrated
- Color-dependent correction — would need per-RGB lux calibration
- Sensor-LED synchronization — too disruptive (visible flicker)
