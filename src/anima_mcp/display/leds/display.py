"""LEDDisplay - hardware and orchestration."""

import math
import sys
import time
from typing import Optional, Tuple

from . import brightness as _brightness
from . import colors as _colors
from . import dances as _dances
from . import patterns as _patterns
from .colors import blend_colors
from .dances import Dance, DanceType, EVENT_TO_DANCE, render_dance
from .types import LEDState

try:
    import board
    import adafruit_dotstar
    HAS_DOTSTAR = True
except ImportError:
    HAS_DOTSTAR = False
    board = None
    adafruit_dotstar = None


_led_display: Optional["LEDDisplay"] = None


def get_led_display() -> "LEDDisplay":
    """Get or create LED display singleton."""
    global _led_display
    if _led_display is None:
        _led_display = LEDDisplay()
    return _led_display


class LEDDisplay:
    """Controls BrainCraft HAT's 3 DotStar LEDs."""

    NUM_LEDS = 3

    def __init__(
        self,
        brightness: Optional[float] = None,
        enable_breathing: Optional[bool] = None,
        enable_patterns: Optional[bool] = None,
        expression_mode: str = "balanced",
    ):
        try:
            from ...config import get_display_config
            cfg = get_display_config()
            self._base_brightness = brightness or cfg.led_brightness
            self._enable_breathing = enable_breathing if enable_breathing is not None else cfg.breathing_enabled
            self._pulsing_enabled = cfg.pulsing_enabled
            self._color_transitions_enabled = cfg.color_transitions_enabled
            self._pattern_mode = cfg.pattern_mode
            self._auto_brightness_enabled = cfg.auto_brightness_enabled
            self._auto_brightness_min = cfg.auto_brightness_min
            self._auto_brightness_max = cfg.auto_brightness_max
            self._pulsing_threshold_clarity = cfg.pulsing_threshold_clarity
            self._pulsing_threshold_stability = cfg.pulsing_threshold_stability
            self._enable_patterns = enable_patterns if enable_patterns is not None else True
        except ImportError:
            self._base_brightness = brightness or 0.12
            self._enable_breathing = enable_breathing if enable_breathing is not None else True
            self._pulsing_enabled = True
            self._color_transitions_enabled = True
            self._pattern_mode = "standard"
            self._auto_brightness_enabled = True
            self._auto_brightness_min = 0.04
            self._auto_brightness_max = 0.15
            self._pulsing_threshold_clarity = 0.4
            self._pulsing_threshold_stability = 0.4
            self._enable_patterns = True

        self._base_brightness = max(0.08, min(0.15, self._base_brightness))
        self._auto_brightness_min = max(0.04, self._auto_brightness_min)
        self._auto_brightness_max = min(0.18, max(0.10, self._auto_brightness_max))

        self._dots = None
        self._brightness = self._base_brightness
        self._hardware_brightness_floor = 0.008
        self._brightness_gamma = 1.8
        self._update_count = 0
        self._last_state: Optional[LEDState] = None
        self._last_colors = [None, None, None]
        self._last_light_level: Optional[float] = None
        self._last_state_values: Optional[Tuple[float, float, float, float]] = None
        self._pattern_active: Optional[str] = None
        self._pattern_start_time: float = 0.0
        self._last_anima_values: Optional[Tuple[float, float, float, float]] = None
        self._state_change_pulse_active = False
        self._state_change_pulse_start: Optional[float] = None
        self._expression_mode = expression_mode
        self._cached_anima_state = None
        self._cached_light_level = None
        self._cached_activity_brightness = None
        self._cached_manual_brightness = None
        self._cached_pipeline_brightness = None
        self._cached_state_change_threshold = 0.05
        self._current_dance: Optional[Dance] = None
        self._dance_cooldown_until = 0.0
        self._last_dance_trigger: Optional[str] = None
        self._spontaneous_dance_chance = 0.005
        self._manual_brightness_factor = 1.0
        self._current_brightness = 0.1
        self._brightness_transition_speed = 0.08
        self._pulse_cycle = 12.0
        self._pulse_amount = 0.05
        self._flash_until = 0.0
        self._flash_color = (100, 100, 100)
        self._init_leds()

    def _init_leds(self):
        if not HAS_DOTSTAR:
            print("[LEDs] DotStar library not available", file=sys.stderr, flush=True)
            return
        try:
            self._dots = adafruit_dotstar.DotStar(
                board.D6, board.D5, self.NUM_LEDS,
                brightness=self._brightness, auto_write=False
            )
            try:
                for i in range(3):
                    self._dots[i] = (10, 10, 10)
                self._dots.brightness = self._base_brightness
                self._dots.show()
            except Exception:
                pass
            print("[LEDs] DotStar LEDs initialized successfully", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[LEDs] Failed to initialize: {e}", file=sys.stderr, flush=True)
            self._dots = None

    def is_available(self) -> bool:
        return self._dots is not None

    def set_brightness(self, brightness: float):
        self._base_brightness = max(0, min(1, brightness))
        self._brightness = self._base_brightness
        if self._dots:
            self._dots.brightness = self._brightness
            self._dots.show()

    def clear(self):
        if self._dots:
            try:
                self._dots.fill((0, 0, 0))
                self._dots.show()
                print("[LEDs] Cleared", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[LEDs] Error clearing LEDs: {e}", file=sys.stderr, flush=True)
                self._dots = None

    def set_led(self, index: int, color: Tuple[int, int, int]):
        if self._dots and 0 <= index < self.NUM_LEDS:
            try:
                self._dots[index] = color
                self._dots.show()
            except Exception as e:
                print(f"[LEDs] Error setting LED {index}: {e}", file=sys.stderr, flush=True)
                self._dots = None

    def _apply_flash(self, state: LEDState) -> LEDState:
        if time.time() < self._flash_until:
            fb = min(0.1, max(state.brightness * 2, 0.03))
            return LEDState(led0=self._flash_color, led1=self._flash_color, led2=self._flash_color, brightness=fb)
        return state

    def set_all(self, state: LEDState):
        if not self._dots:
            if self._update_count % 100 == 0:
                print("[LEDs] set_all called but LEDs unavailable", file=sys.stderr, flush=True)
            return
        state = self._apply_flash(state)
        if self._last_state and self._last_state == state:
            return
        from ...error_recovery import safe_call_with_timeout

        def _set():
            self._dots[0] = state.led2
            self._dots[1] = state.led1
            self._dots[2] = state.led0
            pulse = 0.0 if state.brightness < 0.05 else (
                _brightness.get_pulse(self._pulse_cycle) * self._pulse_amount * min(1.0, max(0.15, state.brightness / 0.12))
            )
            raw = max(self._hardware_brightness_floor, min(0.5, state.brightness + pulse))
            perceptual = _brightness.apply_gamma(raw, self._brightness_gamma, self._hardware_brightness_floor, 0.5)
            self._dots.brightness = max(self._hardware_brightness_floor, perceptual)
            self._dots.show()
            return True

        success = safe_call_with_timeout(_set, timeout_seconds=0.3, default=False, log_error=False)
        if success:
            self._last_state = state
            self._update_count += 1
        elif self._update_count % 50 == 0:
            print("[LEDs] Update skipped (timeout/hardware issue)", file=sys.stderr, flush=True)

    def quick_flash(self, color: Tuple[int, int, int] = (100, 100, 100), duration_ms: int = 50):
        if self._dots:
            self._flash_until = time.time() + (duration_ms / 1000.0)
            self._flash_color = color

    def start_dance(self, dance_type: DanceType, duration: float = 2.0, intensity: float = 1.0) -> bool:
        now = time.time()
        if now < self._dance_cooldown_until:
            return False
        if self._current_dance and not self._current_dance.is_complete:
            return False
        self._current_dance = Dance(dance_type=dance_type, duration=duration, start_time=now, intensity=intensity)
        self._dance_cooldown_until = now + duration + 3.0
        self._last_dance_trigger = dance_type.value
        print(f"[LEDs] Starting dance: {dance_type.value}", file=sys.stderr, flush=True)
        return True

    def get_proprioceptive_state(self) -> dict:
        brightness = self._cached_pipeline_brightness or self._base_brightness
        return {
            "brightness": brightness,
            "expression_mode": self._expression_mode,
            "is_dancing": self._current_dance is not None and not self._current_dance.is_complete,
            "dance_type": self._current_dance.dance_type.value if self._current_dance and not self._current_dance.is_complete else None,
            "manual_dimmed": self._manual_brightness_factor < 1.0,
            "colors": [
                self._last_state.led0 if self._last_state else (0, 0, 0),
                self._last_state.led1 if self._last_state else (0, 0, 0),
                self._last_state.led2 if self._last_state else (0, 0, 0),
            ],
        }

    def get_diagnostics(self) -> dict:
        dance_info = None
        if self._current_dance:
            dance_info = {
                "type": self._current_dance.dance_type.value,
                "progress": self._current_dance.progress,
                "remaining": self._current_dance.duration - self._current_dance.elapsed,
            }
        return {
            "available": self.is_available(),
            "has_dotstar": HAS_DOTSTAR,
            "update_count": self._update_count,
            "base_brightness": self._base_brightness,
            "current_brightness": self._base_brightness + _brightness.get_pulse(self._pulse_cycle) * self._pulse_amount,
            "pulse_cycle": self._pulse_cycle,
            "pulse_amount": self._pulse_amount,
            "pulsing_enabled": self._pulsing_enabled,
            "color_transitions_enabled": self._color_transitions_enabled,
            "pattern_mode": self._pattern_mode,
            "auto_brightness_enabled": self._auto_brightness_enabled,
            "last_light_level": self._last_light_level,
            "current_dance": dance_info,
            "last_dance": self._last_dance_trigger,
            "spontaneous_dance_chance": self._spontaneous_dance_chance,
            "last_state": {
                "led0": self._last_state.led0 if self._last_state else None,
                "led1": self._last_state.led1 if self._last_state else None,
                "led2": self._last_state.led2 if self._last_state else None,
            } if self._last_state else None,
        }

    def test_sequence(self):
        if not self._dots:
            print("[LEDs] Cannot test - not available", file=sys.stderr, flush=True)
            return False
        print("[LEDs] Running test sequence...", file=sys.stderr, flush=True)
        colors = [
            ((255, 0, 0), (0, 0, 0), (0, 0, 0)),
            ((0, 0, 0), (0, 255, 0), (0, 0, 0)),
            ((0, 0, 0), (0, 0, 0), (0, 0, 255)),
            ((255, 255, 255),) * 3,
        ]
        for c0, c1, c2 in colors:
            self._dots[0], self._dots[1], self._dots[2] = c2, c1, c0
            self._dots.brightness = 0.3
            self._dots.show()
            time.sleep(0.5)
        self.clear()
        print("[LEDs] Test complete", file=sys.stderr, flush=True)
        return True

    def update_from_anima(
        self,
        warmth: float,
        clarity: float,
        stability: float,
        presence: float,
        light_level: Optional[float] = None,
        is_anticipating: bool = False,
        anticipation_confidence: float = 0.0,
        activity_brightness: float = 1.0,
    ) -> LEDState:
        update_start = time.time()
        state_changed = True
        if self._cached_anima_state is not None:
            lw, lc, ls, lp = self._cached_anima_state
            max_delta = max(abs(warmth - lw), abs(clarity - lc), abs(stability - ls), abs(presence - lp))
            light_changed = light_level is not None and self._cached_light_level is not None and abs(light_level - self._cached_light_level) > 50
            activity_changed = self._cached_activity_brightness is not None and abs(activity_brightness - self._cached_activity_brightness) > 0.01
            manual_changed = self._cached_manual_brightness is not None and abs(self._manual_brightness_factor - self._cached_manual_brightness) > 0.01
            if max_delta < self._cached_state_change_threshold and not light_changed and not activity_changed and not manual_changed:
                state_changed = False
                if self._last_state and self._dots and self._cached_pipeline_brightness is not None:
                    target = self._cached_pipeline_brightness
                    delta_b = target - self._current_brightness
                    if abs(delta_b) > 0.001:
                        self._current_brightness += delta_b * self._brightness_transition_speed
                    brightness = max(self._hardware_brightness_floor, self._current_brightness)
                    pulse = 0.0 if brightness < 0.05 else (_brightness.get_pulse(self._pulse_cycle) * self._pulse_amount * min(1.0, max(0.15, brightness / 0.12)))
                    raw = max(self._hardware_brightness_floor, min(0.5, brightness + pulse))
                    perceptual = _brightness.apply_gamma(raw, self._brightness_gamma, self._hardware_brightness_floor, 0.5)
                    self._dots.brightness = max(self._hardware_brightness_floor, perceptual)
                    self._dots.show()
                    return self._last_state

        self._cached_anima_state = (warmth, clarity, stability, presence)
        self._cached_light_level = light_level
        self._cached_activity_brightness = activity_brightness
        self._cached_manual_brightness = self._manual_brightness_factor

        self._last_state_values, pattern_trigger = _patterns.detect_state_change(
            warmth, clarity, stability, presence, self._last_state_values
        )
        if pattern_trigger:
            self._pattern_active = pattern_trigger
            self._pattern_start_time = time.time()

        state = _colors.derive_led_state(
            warmth, clarity, stability, presence,
            pattern_mode=self._pattern_mode,
            enable_color_mixing=self._color_transitions_enabled,
            expression_mode=self._expression_mode,
        )

        if self._pattern_active and self._enable_patterns:
            state, pattern_done = _patterns.get_pattern_colors(
                self._pattern_active, state, self._pattern_start_time
            )
            if pattern_done is None:
                self._pattern_active = None

        try:
            from ...eisv import get_trajectory_awareness
            dr, dg, db = _colors.get_shape_color_bias(get_trajectory_awareness().current_shape)
            if dr != 0 or dg != 0 or db != 0:
                state = LEDState(
                    led0=(max(0, min(255, state.led0[0] + dr)), max(0, min(255, state.led0[1] + dg)), max(0, min(255, state.led0[2] + db))),
                    led1=(max(0, min(255, state.led1[0] + dr)), max(0, min(255, state.led1[1] + dg)), max(0, min(255, state.led1[2] + db))),
                    led2=(max(0, min(255, state.led2[0] + dr)), max(0, min(255, state.led2[1] + dg)), max(0, min(255, state.led2[2] + db))),
                    brightness=state.brightness,
                )
        except Exception:
            pass

        state_change_detected = False
        if self._last_anima_values is not None:
            lw, lc, ls, lp = self._last_anima_values
            if abs(warmth - lw) > 0.15 or abs(clarity - lc) > 0.15 or abs(stability - ls) > 0.15 or abs(presence - lp) > 0.15:
                state_change_detected = True
                self._state_change_pulse_active = True
                self._state_change_pulse_start = time.time()
        self._last_anima_values = (warmth, clarity, stability, presence)

        if self._color_transitions_enabled and self._last_state and self._last_colors[0] is not None:
            tf = 0.15 if state_change_detected else 0.10
            state = LEDState(
                led0=_colors.transition_color(self._last_colors[0], state.led0, tf, self._color_transitions_enabled),
                led1=_colors.transition_color(self._last_colors[1], state.led1, tf, self._color_transitions_enabled),
                led2=_colors.transition_color(self._last_colors[2], state.led2, tf, self._color_transitions_enabled),
                brightness=state.brightness,
            )
        self._last_colors = [state.led0, state.led1, state.led2]

        if self._manual_brightness_factor < 1.0:
            state = LEDState(led0=state.led0, led1=state.led1, led2=state.led2, brightness=self._manual_brightness_factor)
        else:
            state = LEDState(led0=state.led0, led1=state.led1, led2=state.led2, brightness=self._base_brightness)
            if self._auto_brightness_enabled and light_level is not None:
                state = LEDState(
                    led0=state.led0, led1=state.led1, led2=state.led2,
                    brightness=_brightness.get_auto_brightness(
                        light_level, self._base_brightness,
                        self._auto_brightness_min, self._auto_brightness_max,
                        self._auto_brightness_enabled, self._brightness
                    ),
                )
        if self._manual_brightness_factor >= 1.0:
            pm = _brightness.get_pulsing_brightness(
                clarity, stability, self._pulsing_enabled,
                self._pulsing_threshold_clarity, self._pulsing_threshold_stability
            )
            if pm < 1.0:
                state = LEDState(led0=state.led0, led1=state.led1, led2=state.led2, brightness=state.brightness * pm)

        if self._manual_brightness_factor >= 1.0 and self._state_change_pulse_active and self._state_change_pulse_start:
            elapsed = time.time() - self._state_change_pulse_start
            if elapsed < 0.8:
                state = LEDState(led0=state.led0, led1=state.led1, led2=state.led2, brightness=state.brightness * (1.0 + 0.1 * (1.0 - elapsed / 0.8)))
            else:
                self._state_change_pulse_active = False
                self._state_change_pulse_start = None

        if self._manual_brightness_factor >= 1.0 and activity_brightness < 1.0:
            state = LEDState(led0=state.led0, led1=state.led1, led2=state.led2, brightness=state.brightness * activity_brightness)

        state = LEDState(led0=state.led0, led1=state.led1, led2=state.led2, brightness=max(self._hardware_brightness_floor, state.brightness))

        target_b = state.brightness
        delta = target_b - self._current_brightness
        if abs(delta) > 0.001:
            speed = self._brightness_transition_speed
            if abs(delta) > 0.05:
                speed = min(0.2, speed * 2)
            elif abs(delta) < 0.02:
                speed *= 0.5
            self._current_brightness += delta * speed
        else:
            self._current_brightness = target_b
        state = LEDState(led0=state.led0, led1=state.led1, led2=state.led2, brightness=max(self._hardware_brightness_floor, self._current_brightness))
        self._cached_pipeline_brightness = state.brightness

        if is_anticipating and anticipation_confidence > 0.1:
            memory_color = (255, 200, 100)
            blend_strength = min(0.25, anticipation_confidence * 0.3)
            state = LEDState(
                led0=blend_colors(state.led0, memory_color, blend_strength),
                led1=blend_colors(state.led1, memory_color, blend_strength),
                led2=blend_colors(state.led2, memory_color, blend_strength),
                brightness=state.brightness,
            )
            if anticipation_confidence > 0.5 and state.brightness >= 0.05:
                state = LEDState(led0=state.led0, led1=state.led1, led2=state.led2, brightness=state.brightness * (1.0 + (anticipation_confidence - 0.5) * 0.1))

        if self._manual_brightness_factor >= 0.05:
            spontaneous = _dances.maybe_spontaneous_dance(
                warmth, clarity, stability, presence,
                self._spontaneous_dance_chance, self._dance_cooldown_until
            )
            if spontaneous:
                self.start_dance(spontaneous, duration=2.0, intensity=0.8)

        if self._current_dance:
            if self._current_dance.is_complete:
                self._current_dance = None
            else:
                state = render_dance(self._current_dance, state)
                if self._manual_brightness_factor < 0.05 and state.brightness > self._manual_brightness_factor * 1.1:
                    state = LEDState(led0=state.led0, led1=state.led1, led2=state.led2, brightness=self._manual_brightness_factor)

        if self._enable_patterns and self._pattern_mode == "expressive":
            import math
            if clarity < 0.3 or stability < 0.3:
                speed, amp = 2.0, 0.4
            elif warmth > 0.6 and stability > 0.6:
                speed, amp = 0.125, 0.2
            elif clarity > 0.7:
                speed, amp = 1.0, 0.3
            else:
                speed, amp = 0.125, 0.15
            t = time.time()
            wave_colors = []
            for i, bc in enumerate([state.led0, state.led1, state.led2]):
                phase = (t * speed * math.pi * 2) + (i * math.pi / 3)
                wb = 0.5 + (amp * 0.5 * math.sin(phase))
                wave_colors.append(tuple(int(c * wb) for c in bc))
            state = LEDState(led0=wave_colors[0], led1=wave_colors[1], led2=wave_colors[2], brightness=state.brightness)

        try:
            self.set_all(state)
        except Exception as e:
            print(f"[LEDs] Error: {e}", file=sys.stderr, flush=True)
            if "hardware" in str(e).lower() or "io" in str(e).lower():
                self._dots = None

        if self._update_count % 10 == 1:
            features = []
            if not state_changed:
                features.append("cached")
            if self._state_change_pulse_active:
                features.append("pulse")
            if self._current_dance and not self._current_dance.is_complete:
                features.append(f"dance({self._current_dance.dance_type.value})")
            fs = f" [{', '.join(features)}]" if features else ""
            print(f"[LEDs] #{self._update_count} ({1000*(time.time()-update_start):.1f}ms): w={warmth:.2f} c={clarity:.2f} s={stability:.2f} p={presence:.2f}{fs}", file=sys.stderr, flush=True)

        return state
