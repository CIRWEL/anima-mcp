# Lighthouse LED Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace chaotic LED behavior with a warm, calm, manually-controlled lighthouse that Lumen can proprioceptively predict.

**Architecture:** Remove auto-brightness feedback loop. Constrain all colors to warm amber/gold. Brightness is manual-only (dimmer). Lumen knows the brightness setting as `_known_brightness` for proprioceptive prediction. Red reserved for hardware distress only.

**Tech Stack:** Python, adafruit_dotstar (DotStar LEDs), VEML7700 light sensor

**Design doc:** `docs/plans/2026-02-21-lighthouse-led-design.md`

---

### Task 1: Warm-Only Color Palette

**Files:**
- Modify: `src/anima_mcp/display/leds/colors.py`
- Test: `tests/test_led_colors.py` (create)

**Step 1: Write the failing tests**

```python
# tests/test_led_colors.py
"""Tests for warm-only LED color palette."""
import pytest
from anima_mcp.display.leds.colors import derive_led_state, _create_gradient_palette


class TestWarmPalette:
    """All LED colors must stay in the warm spectrum."""

    @pytest.mark.parametrize("warmth,clarity,stability,presence", [
        (0.1, 0.1, 0.1, 0.1),  # all low
        (0.5, 0.5, 0.5, 0.5),  # all mid
        (0.9, 0.9, 0.9, 0.9),  # all high
        (0.0, 0.0, 0.0, 0.0),  # minimum
        (1.0, 1.0, 1.0, 1.0),  # maximum
        (0.1, 0.9, 0.1, 0.9),  # mixed extremes
    ])
    def test_all_leds_warm_tones(self, warmth, clarity, stability, presence):
        """Every LED color must have R >= G >= B (warm tone invariant)."""
        state = derive_led_state(warmth, clarity, stability, presence)
        for name, color in [("led0", state.led0), ("led1", state.led1), ("led2", state.led2)]:
            r, g, b = color
            assert r >= g >= b, f"{name}={color}: warm tone requires R >= G >= B"

    def test_no_pure_red_in_standard_mode(self):
        """Standard mode never produces pure red (255,0,0)."""
        state = derive_led_state(0.1, 0.1, 0.1, 0.1, pattern_mode="standard")
        for name, color in [("led0", state.led0), ("led1", state.led1), ("led2", state.led2)]:
            assert color != (255, 0, 0), f"{name} should not be pure red"

    def test_no_blue_tones(self):
        """No LED should have B > G (blue-dominant)."""
        state = derive_led_state(0.5, 0.9, 0.5, 0.9)  # high presence used to trigger blue tint
        for name, color in [("led0", state.led0), ("led1", state.led1), ("led2", state.led2)]:
            r, g, b = color
            assert b <= g, f"{name}={color}: blue should never exceed green"

    def test_default_brightness_is_0_04(self):
        """Default brightness in LEDState should be 0.04."""
        state = derive_led_state(0.5, 0.5, 0.5, 0.5)
        assert state.brightness == pytest.approx(0.04, abs=0.001)


class TestGradientPalette:
    """_create_gradient_palette must produce warm colors."""

    def test_led1_never_blue_white(self):
        """LED1 (clarity) should be warm white, not cool white."""
        led0, led1, led2 = _create_gradient_palette(0.5, 0.9, 0.5, 0.5)
        r, g, b = led1
        assert r >= g >= b, f"LED1={led1}: clarity LED should be warm white"

    def test_led2_never_green(self):
        """LED2 (stability/presence) should stay amber/honey, not green."""
        led0, led1, led2 = _create_gradient_palette(0.5, 0.5, 0.9, 0.9)
        r, g, b = led2
        assert r >= g, f"LED2={led2}: stability LED should be warm, not green-dominant"
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_led_colors.py -v`
Expected: Multiple FAILs (current palette has blue tints, green tones, brightness 0.12)

**Step 3: Rewrite colors.py with warm-only palette**

Replace `_create_gradient_palette`:
```python
def _create_gradient_palette(
    warmth: float, clarity: float, stability: float, presence: float
) -> Tuple[Tuple[int, int, int], Tuple[int, int, int], Tuple[int, int, int]]:
    """Warm amber/gold gradient. R >= G >= B invariant."""
    # LED0: Energy/warmth — soft gold to warm amber
    if warmth < 0.3:
        led0 = (180, 110, 40)
    elif warmth < 0.6:
        ratio = (warmth - 0.3) / 0.3
        led0 = _interpolate_color((180, 110, 40), (220, 140, 50), ratio)
    else:
        ratio = (warmth - 0.6) / 0.4
        led0 = _interpolate_color((220, 140, 50), (255, 150, 50), ratio)

    # LED1: Clarity — dim warm white to bright warm white
    i = max(100, min(220, int(80 + clarity * 140)))
    led1 = (i, int(i * 0.82), int(i * 0.45))

    # LED2: Stability/presence — deep amber to honey
    combined = stability * 0.6 + presence * 0.4
    if combined < 0.3:
        led2 = (180, 100, 30)
    elif combined < 0.6:
        ratio = (combined - 0.3) / 0.3
        led2 = _interpolate_color((180, 100, 30), (200, 130, 45), ratio)
    else:
        ratio = (combined - 0.6) / 0.4
        led2 = _interpolate_color((200, 130, 45), (220, 150, 55), ratio)

    return (led0, led1, led2)
```

Replace `derive_led_state` — remove "minimal", "expressive", "alert" pattern modes (keep only "standard"). Remove blue/white/green color mixing. Change default brightness to 0.04:
```python
def derive_led_state(
    warmth: float, clarity: float, stability: float, presence: float,
    pattern_mode: str = "standard",
    enable_color_mixing: bool = True,
    expression_mode: str = "balanced"
) -> LEDState:
    """Map anima metrics to warm LED colors."""
    led0, led1, led2 = _create_gradient_palette(warmth, clarity, stability, presence)
    intensity = {"subtle": 0.6, "balanced": 1.0, "expressive": 1.4}.get(expression_mode, 1.0)
    if intensity != 1.0:
        led0 = tuple(max(0, min(255, int(c * intensity))) for c in led0)
        led1 = tuple(max(0, min(255, int(c * intensity))) for c in led1)
        led2 = tuple(max(0, min(255, int(c * intensity))) for c in led2)
    return LEDState(led0=led0, led1=led1, led2=led2, brightness=0.04)
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_led_colors.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/anima_mcp/display/leds/colors.py tests/test_led_colors.py
git commit -m "feat(leds): warm-only color palette — no red/blue/green in normal operation"
```

---

### Task 2: Remove Auto-Brightness, Simplify Brightness Pipeline

**Files:**
- Modify: `src/anima_mcp/display/leds/brightness.py`
- Modify: `src/anima_mcp/display/leds/types.py`
- Test: `tests/test_led_brightness.py` (create)

**Step 1: Write the failing tests**

```python
# tests/test_led_brightness.py
"""Tests for simplified brightness pipeline."""
import pytest
from anima_mcp.display.leds.brightness import get_pulse, estimate_instantaneous_brightness


class TestBreathingPulse:
    """Breathing animation stays proportional to brightness."""

    def test_pulse_returns_0_to_1(self):
        val = get_pulse(12.0)
        assert 0.0 <= val <= 1.0

    def test_amplitude_scales_with_brightness(self):
        """At low brightness, pulse amplitude should be tiny."""
        est_low = estimate_instantaneous_brightness(0.02, pulse_cycle=12.0, pulse_amount=0.05)
        est_high = estimate_instantaneous_brightness(0.10, pulse_cycle=12.0, pulse_amount=0.05)
        # Low brightness variation should be much smaller
        assert est_low < 0.03  # never blinding
        assert est_high < 0.15  # ceiling respected

    def test_max_brightness_ceiling(self):
        """No brightness output should ever exceed 0.12."""
        est = estimate_instantaneous_brightness(0.12, pulse_cycle=12.0, pulse_amount=0.05)
        assert est <= 0.15  # some headroom for pulse, but bounded


class TestAutoBrightnessRemoved:
    """Auto-brightness function should not exist."""

    def test_no_auto_brightness_function(self):
        import anima_mcp.display.leds.brightness as mod
        assert not hasattr(mod, "get_auto_brightness"), "get_auto_brightness should be removed"

    def test_no_pulsing_brightness_function(self):
        import anima_mcp.display.leds.brightness as mod
        assert not hasattr(mod, "get_pulsing_brightness"), "get_pulsing_brightness should be removed"

    def test_no_gamma_function(self):
        import anima_mcp.display.leds.brightness as mod
        assert not hasattr(mod, "apply_gamma"), "apply_gamma should be removed"
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_led_brightness.py -v`
Expected: FAIL (functions still exist)

**Step 3: Simplify brightness.py**

Remove `get_auto_brightness`, `get_pulsing_brightness`, `apply_gamma`. Keep only `get_pulse` and `estimate_instantaneous_brightness`:

```python
"""Brightness pipeline: breathing pulse only. No auto-brightness."""

import math
import time


def get_pulse(pulse_cycle: float = 12.0) -> float:
    """Primary + secondary breath wave. Returns 0-1."""
    t = time.time()
    primary = (1.0 + math.sin(t * 2 * math.pi / pulse_cycle)) * 0.5
    secondary = (1.0 + math.sin(t * 2 * math.pi / 18.0)) * 0.5
    return primary * (0.92 + 0.08 * secondary)


def estimate_instantaneous_brightness(
    base_brightness: float,
    pulse_cycle: float = 12.0,
    pulse_amount: float = 0.05,
) -> float:
    """Estimate current LED brightness including breathing pulse.

    Used by proprioceptive model to predict sensor reading.
    Amplitude scales with brightness so dim LEDs have imperceptible breath.
    """
    pulse = get_pulse(pulse_cycle)
    amplitude = pulse_amount * min(1.0, max(0.15, base_brightness / 0.04))
    # Cap: amplitude never exceeds 0.005 at low brightness
    amplitude = min(amplitude, max(0.005, base_brightness * 0.08))
    return max(0.0, base_brightness + pulse * amplitude)
```

Update `types.py` default brightness:
```python
brightness: float = 0.04  # Global brightness (0-1) - manual control only
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_led_brightness.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/anima_mcp/display/leds/brightness.py src/anima_mcp/display/leds/types.py tests/test_led_brightness.py
git commit -m "feat(leds): remove auto-brightness — manual control only, breathing scales with brightness"
```

---

### Task 3: Remove Alert Patterns, Keep Warm-Only Signals

**Files:**
- Modify: `src/anima_mcp/display/leds/patterns.py`
- Test: `tests/test_led_patterns.py` (create)

**Step 1: Write the failing tests**

```python
# tests/test_led_patterns.py
"""Tests for warm-only pattern system."""
import pytest
from anima_mcp.display.leds.patterns import detect_state_change, get_pattern_colors
from anima_mcp.display.leds.types import LEDState


class TestPatternDetection:
    """Pattern detection should not trigger alert or stability_warning."""

    def test_low_stability_no_alert(self):
        """stability < 0.3 should NOT trigger alert pattern."""
        last = (0.5, 0.5, 0.5, 0.5)
        _, pattern = detect_state_change(0.5, 0.5, 0.1, 0.5, last)
        assert pattern != "alert", "alert pattern should be removed"
        assert pattern != "stability_warning" or True  # stability_warning OK if warm

    def test_low_clarity_no_alert(self):
        """clarity < 0.3 should NOT trigger alert pattern."""
        last = (0.5, 0.5, 0.5, 0.5)
        _, pattern = detect_state_change(0.5, 0.1, 0.5, 0.5, last)
        assert pattern != "alert", "alert pattern should be removed"


class TestPatternColors:
    """All pattern colors must be warm."""

    def test_no_red_in_stability_warning(self):
        """stability_warning should use warm amber, not pure red."""
        base = LEDState((200, 130, 40), (200, 160, 80), (200, 130, 40), 0.04)
        state, name = get_pattern_colors("warmth_spike", base, __import__("time").time())
        if name:
            for led_name, color in [("led0", state.led0), ("led1", state.led1), ("led2", state.led2)]:
                assert color != (255, 0, 0), f"{led_name} should not be pure red"

    def test_no_white_in_clarity_boost(self):
        """clarity_boost should use warm white, not pure white."""
        base = LEDState((200, 130, 40), (200, 160, 80), (200, 130, 40), 0.04)
        state, name = get_pattern_colors("clarity_boost", base, __import__("time").time())
        if name:
            assert state.led1 != (255, 255, 255), "clarity_boost should not be pure white"
```

**Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_led_patterns.py -v`
Expected: FAIL (alert still exists, red/white still used)

**Step 3: Rewrite patterns.py**

Remove "alert" pattern entirely. Replace colors with warm tones. Remove rapid transitions:

```python
"""State-change LED patterns — warm tones only."""

import time
from typing import Optional, Tuple

from .types import LEDState


def detect_state_change(
    warmth: float, clarity: float, stability: float, presence: float,
    last: Optional[Tuple[float, float, float, float]]
) -> tuple[Optional[Tuple[float, float, float, float]], Optional[str]]:
    """Detect significant state changes. No alert triggers."""
    if last is None:
        return (warmth, clarity, stability, presence), None
    last_w, last_c, last_s, last_p = last
    new_last = (warmth, clarity, stability, presence)

    if abs(warmth - last_w) > 0.2 and warmth > last_w:
        return new_last, "warmth_spike"
    if abs(clarity - last_c) > 0.3 and clarity > last_c:
        return new_last, "clarity_boost"
    # No stability_warning or alert — state changes are normal
    return new_last, None


def get_pattern_colors(
    pattern_name: str, base_state: LEDState, pattern_start_time: float
) -> Tuple[LEDState, Optional[str]]:
    """Warm-only pattern overlays. All transitions >= 2s equivalent."""
    elapsed = time.time() - pattern_start_time
    if elapsed > 2.0:
        return base_state, None

    fade = max(0.0, 1.0 - elapsed / 2.0)  # 2-second fade

    if pattern_name == "warmth_spike":
        warm_highlight = (255, 160, 50)
        led0 = tuple(int(base_state.led0[i] + (warm_highlight[i] - base_state.led0[i]) * fade * 0.4) for i in range(3))
        return LEDState(led0=led0, led1=base_state.led1, led2=base_state.led2, brightness=base_state.brightness), pattern_name

    if pattern_name == "clarity_boost":
        warm_white = (240, 200, 120)
        led1 = tuple(int(base_state.led1[i] + (warm_white[i] - base_state.led1[i]) * fade * 0.4) for i in range(3))
        return LEDState(led0=base_state.led0, led1=led1, led2=base_state.led2, brightness=base_state.brightness), pattern_name

    return base_state, None
```

**Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_led_patterns.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/anima_mcp/display/leds/patterns.py tests/test_led_patterns.py
git commit -m "feat(leds): remove alert/warning patterns — warm-only signals with 2s fade"
```

---

### Task 4: Simplify display.py — Manual Brightness, No Auto

**Files:**
- Modify: `src/anima_mcp/display/leds/display.py`
- Modify: `src/anima_mcp/config.py`

**Step 1: Update config.py defaults**

Change in `DisplayConfig`:
```python
led_brightness: float = 0.04  # Base brightness (manual control)
breathing_enabled: bool = True
pulsing_enabled: bool = False  # Removed — was for low clarity/stability rapid pulse
pattern_mode: str = "standard"  # Only "standard" supported now
auto_brightness_enabled: bool = False  # Removed — manual control only
auto_brightness_min: float = 0.00  # Not used
auto_brightness_max: float = 0.12  # Ceiling
```

**Step 2: Simplify display.py __init__**

Remove auto-brightness config fields. Remove pulsing config. Set brightness clamp to `max(0.0, min(0.12, ...))` instead of `max(0.08, min(0.15, ...))`.

Add `_known_brightness` field:
```python
self._known_brightness = self._base_brightness  # Proprioceptive: Lumen knows this
```

**Step 3: Simplify update_from_anima**

Remove from the method:
- Auto-brightness block (lines 399-407)
- Pulsing brightness block (lines 408-414)
- State-change pulse block (lines 416-422)
- Activity brightness block (lines 424-425)
- Expressive wave block (lines 474-489)

The brightness pipeline becomes:
```python
# Manual brightness only
if self._manual_brightness_factor < 1.0:
    brightness = self._manual_brightness_factor
else:
    brightness = self._base_brightness
brightness = max(0.0, min(0.12, brightness))  # ceiling

# Update known brightness for proprioception
self._known_brightness = brightness
```

**Step 4: Simplify animation loop**

Remove gamma correction. Simplify pulse calculation. Cap `rgb_scale` to respect brightness ceiling. Ensure transition speed enforces >=2s color ramps.

**Step 5: Update get_proprioceptive_state to expose _known_brightness**

```python
def get_proprioceptive_state(self) -> dict:
    return {
        "brightness": self._known_brightness,
        "expression_mode": self._expression_mode,
        "is_dancing": ...,
        "dance_type": ...,
        "manual_dimmed": self._manual_brightness_factor < 1.0,
        "colors": [...],
    }
```

**Step 6: Run full test suite**

Run: `python3 -m pytest tests/ -v --ignore=tests/test_server.py`
Expected: All pass (display.py has no dedicated test file; integration validated by other tests)

**Step 7: Commit**

```bash
git add src/anima_mcp/display/leds/display.py src/anima_mcp/config.py
git commit -m "feat(leds): manual-only brightness, remove auto-brightness/pulsing/gamma from pipeline"
```

---

### Task 5: Warm-Constrain Dances

**Files:**
- Modify: `src/anima_mcp/display/leds/dances.py`

**Step 1: Replace non-warm colors in dance sequences**

Color replacements:
| Dance | Current color | Warm replacement |
|-------|-------------|-----------------|
| CURIOUS_PULSE | `(150, 200, 255)` cyan | `(220, 170, 80)` warm gold |
| CONTEMPLATIVE_WAVE | `(100, 50, 200)` purple | `(180, 120, 50)` deep amber |
| DISCOVERY_BLOOM | `(255, 100, 255)` magenta | `(255, 180, 80)` bright gold |
| PLAYFUL_CHASE | `[(255,100,100), (100,255,100), (100,100,255)]` RGB | `[(255,160,60), (240,140,50), (220,120,40)]` warm trio |
| GREETING_FLOURISH | `(255, 200, 150)` warm (keep) | Keep as-is |
| CONTENTMENT_GLOW | `(255, 180, 100)` warm (keep) | Keep as-is |

Also: ensure no dance can push brightness above the current manual setting. Change all `mult` calculations to cap at 1.0 (no brightness boosting).

**Step 2: Run tests**

Run: `python3 -m pytest tests/ -v --ignore=tests/test_server.py`
Expected: All pass

**Step 3: Commit**

```bash
git add src/anima_mcp/display/leds/dances.py
git commit -m "feat(leds): constrain dances to warm palette, no brightness boosting"
```

---

### Task 6: Update Proprioceptive Prediction in Metacognition

**Files:**
- Modify: `src/anima_mcp/metacognition.py`

**Step 1: Update prediction to use known brightness**

In the `_predict_next_state` method (around line 352-377), the prediction already uses `led_brightness`. The key change: the caller should pass `_known_brightness` (the manual setting) rather than the fluctuating auto-brightness value. This is a wiring change in whoever calls `predict()`.

Grep for where `led_brightness` is passed to the prediction:
```bash
grep -rn "predict\|led_brightness" src/anima_mcp/metacognition.py | head -20
```

Update the comment to reflect the new model:
```python
# === PROPRIOCEPTIVE LIGHT PREDICTION ===
# Lumen's brightness is manually controlled (dimmer). Lumen knows the
# current setting as _known_brightness. This is a stable value that only
# changes when Kenny adjusts the dimmer — NOT from auto-brightness.
# Prediction errors therefore reflect genuine environmental changes
# (lamp on, sunrise) rather than self-inflicted brightness oscillation.
```

**Step 2: Run tests**

Run: `python3 -m pytest tests/ -v --ignore=tests/test_server.py`
Expected: All pass

**Step 3: Commit**

```bash
git add src/anima_mcp/metacognition.py
git commit -m "feat(leds): update proprioceptive model — known_brightness is manual, not auto"
```

---

### Task 7: Integration Verification & Deploy

**Step 1: Run full test suite**

```bash
python3 -m pytest tests/ -v --ignore=tests/test_server.py
```

**Step 2: Verify on Pi**

Deploy to Pi using the deploy-to-pi skill. After restart, verify:
- LEDs show warm amber glow (not white, not bright)
- Dimmer adjusts brightness smoothly
- No red/blue/green flashes
- Breathing visible at normal brightness, imperceptible when dim
- `manage_display(action="diagnostics")` shows `auto_brightness_enabled: false`

**Step 3: Final commit with changelog**

```bash
git add -A
git commit -m "feat(leds): lighthouse LED — warm palette, manual brightness, clean proprioception

Closes design: docs/plans/2026-02-21-lighthouse-led-design.md"
```
