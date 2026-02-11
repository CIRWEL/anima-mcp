"""
LED Display - Maps anima state to BrainCraft HAT's 3 DotStar LEDs.

3 LEDs for 4 metrics:
Physical order on BrainCraft HAT (DotStar array indices):
- LED 0 / left:   Warmth     — violet (cold) → gold (comfortable) → orange-red (hot)
- LED 1 / center: Clarity    — dim amber (foggy) → yellow → cool white (crisp)
- LED 2 / right:  Stability+Presence — red (warning) → emerald (stable) → teal (present)

Note: DotStar array index 0 is physically rightmost, index 2 is leftmost.
(led0 in code = warmth = physical left, led2 in code = stability = physical right)

Brightness controlled by user via joystick on face screen (LEDs only, screen stays full).
Simple sine pulse as "I'm alive" signal — always on unless night mode
(ACTIVE=fast ~1.8s, DROWSY=moderate ~3.5s, RESTING=slow ~6s).
"""

import sys
import time
import math
import random
from dataclasses import dataclass, field
from typing import Tuple, Optional, Any, List
from enum import Enum


class DanceType(Enum):
    """Types of emotional dances Lumen can perform."""
    JOY_SPARKLE = "joy_sparkle"           # Quick bright sparkles - delight
    CURIOUS_PULSE = "curious_pulse"       # Rhythmic pulsing - investigation
    CONTEMPLATIVE_WAVE = "contemplative"  # Slow flowing wave - thinking
    GREETING_FLOURISH = "greeting"        # Welcoming pattern - hello
    DISCOVERY_BLOOM = "discovery"         # Colors blooming outward - found something!
    CONTENTMENT_GLOW = "contentment"      # Warm steady glow - satisfied
    PLAYFUL_CHASE = "playful"             # Colors chasing each other - fun


@dataclass
class Dance:
    """A choreographed LED dance sequence."""
    dance_type: DanceType
    duration: float  # Total duration in seconds
    start_time: float = field(default_factory=time.time)
    intensity: float = 1.0  # 0-1, how pronounced the dance is

    @property
    def elapsed(self) -> float:
        return time.time() - self.start_time

    @property
    def progress(self) -> float:
        """Progress through dance 0-1."""
        return min(1.0, self.elapsed / self.duration)

    @property
    def is_complete(self) -> bool:
        return self.elapsed >= self.duration

# Try to import DotStar library
try:
    import board
    import adafruit_dotstar
    HAS_DOTSTAR = True
except ImportError:
    HAS_DOTSTAR = False


@dataclass
class LEDState:
    """State of all 3 LEDs."""
    led0: Tuple[int, int, int]  # RGB for warmth (physical left, DotStar index 2)
    led1: Tuple[int, int, int]  # RGB for clarity (physical center, DotStar index 1)
    led2: Tuple[int, int, int]  # RGB for stability/presence (physical right, DotStar index 0)
    brightness: float = 0.12  # Global brightness (0-1) - auto-brightness overrides this


class LEDDisplay:
    """Controls BrainCraft HAT's 3 DotStar LEDs with enhanced features."""
    
    NUM_LEDS = 3
    
    def __init__(self, brightness: Optional[float] = None, enable_breathing: Optional[bool] = None, 
                 enable_patterns: Optional[bool] = None, expression_mode: str = "balanced"):
        """
        Initialize LED display.
        
        Args:
            brightness: Global brightness 0-1 (uses config default if None)
            enable_breathing: Add subtle brightness variation (uses config default if None)
        """
        # Import here to avoid circular dependency
        try:
            from ..config import get_display_config
            display_config = get_display_config()
            self._base_brightness = brightness if brightness is not None else display_config.led_brightness
            self._enable_breathing = enable_breathing if enable_breathing is not None else display_config.breathing_enabled
            self._pulsing_enabled = display_config.pulsing_enabled
            self._color_transitions_enabled = display_config.color_transitions_enabled
            self._pattern_mode = display_config.pattern_mode
            self._auto_brightness_enabled = display_config.auto_brightness_enabled
            self._auto_brightness_min = display_config.auto_brightness_min
            self._auto_brightness_max = display_config.auto_brightness_max
            self._pulsing_threshold_clarity = display_config.pulsing_threshold_clarity
            self._pulsing_threshold_stability = display_config.pulsing_threshold_stability
            self._enable_patterns = enable_patterns if enable_patterns is not None else True
            self._pattern_active = None
            self._pattern_start_time = None
            self._last_state_values = None
            self._expression_mode = expression_mode
            # Enforce sane range regardless of config (config may be stale)
            # Wider range to make manual dimmer noticeable, but still constrained
            self._base_brightness = max(0.08, min(0.15, self._base_brightness))
            self._auto_brightness_min = max(0.04, self._auto_brightness_min)
            self._auto_brightness_max = min(0.18, max(0.10, self._auto_brightness_max))
        except ImportError:
            # Fallback if config not available
            # NOTE: These should match anima_config.yaml defaults
            self._base_brightness = brightness if brightness is not None else 0.12
            self._enable_breathing = enable_breathing if enable_breathing is not None else True
            self._pulsing_enabled = True
            self._color_transitions_enabled = True
            self._pattern_mode = "standard"
            self._auto_brightness_enabled = True
            self._auto_brightness_min = 0.04
            self._auto_brightness_max = 0.15
            self._pulsing_threshold_clarity = 0.4
            self._pulsing_threshold_stability = 0.4
        
        self._dots = None
        self._brightness = self._base_brightness
        # Hardware floor: absolute minimum brightness (separate from auto-brightness range).
        # Activity state (RESTING=0.15x) can push below auto_brightness_min but not below this.
        # Low enough for dimmer to work, high enough to stay visible
        self._hardware_brightness_floor = 0.025
        self._update_count = 0
        self._last_state: Optional[LEDState] = None
        self._last_colors = [None, None, None]  # For color transitions
        self._last_light_level: Optional[float] = None  # For auto-brightness
        self._last_state_values = None  # Track state changes for patterns
        self._pattern_active = None
        self._pattern_start_time = None
        self._last_anima_values = None  # Track anima state for change detection
        self._state_change_pulse_active = False  # Track if pulsing for state change
        self._state_change_pulse_start = None  # When state change pulse started
        self._expression_mode = expression_mode
        # Cache for optimization: skip expensive calculations if state unchanged
        self._cached_anima_state = None  # (warmth, clarity, stability, presence)
        self._cached_light_level = None
        self._cached_activity_brightness = None  # Track activity transitions
        self._cached_manual_brightness = None  # Track manual dimmer changes
        self._cached_pipeline_brightness = None  # Last fully-computed brightness (before pulse)
        self._cached_state_change_threshold = 0.05  # Only recalculate if change > 5%
        # Emotional dance state
        self._current_dance: Optional[Dance] = None
        self._dance_cooldown_until: float = 0.0  # Prevent dance spam
        self._last_dance_trigger: Optional[str] = None
        self._spontaneous_dance_chance: float = 0.001  # ~0.1% per update - less frequent to avoid lux chaos
        self._manual_brightness_factor: float = 1.0  # User dimmer multiplier (set from server.py)
        self._current_brightness: float = 0.1  # Actual current brightness (for smooth transitions)
        self._brightness_transition_speed: float = 0.08  # How fast brightness changes (0-1, per update)
        # Pulse animation ("I'm alive" signal) - SUBTLE to avoid lux sensor chaos
        self._pulse_cycle: float = 4.0  # Seconds per cycle (slower = calmer)
        self._pulse_amount: float = 0.015  # Absolute brightness added at peak (halved for subtlety)
        self._init_leds()
    
    def _init_leds(self):
        """Initialize DotStar LEDs if available."""
        if not HAS_DOTSTAR:
            print("[LEDs] DotStar library not available", file=sys.stderr, flush=True)
            return
            
        try:
            # BrainCraft HAT DotStars are on D5 (data) and D6 (clock)
            self._dots = adafruit_dotstar.DotStar(
                board.D6,     # Clock
                board.D5,     # Data
                self.NUM_LEDS,
                brightness=self._brightness,
                auto_write=False  # Manual update for efficiency
            )
            # Initialize LEDs to a safe default state (not cleared/off)
            # Set a minimal default so LEDs are visible even if update fails
            try:
                self._dots[0] = (10, 10, 10)  # Very dim white
                self._dots[1] = (10, 10, 10)
                self._dots[2] = (10, 10, 10)
                self._dots.brightness = self._base_brightness  # Use configured brightness
                self._dots.show()
            except Exception:
                pass  # If this fails, clear() as fallback
            print("[LEDs] DotStar LEDs initialized successfully", file=sys.stderr, flush=True)
        except Exception as e:
            print(f"[LEDs] Failed to initialize: {e}", file=sys.stderr, flush=True)
            self._dots = None
    
    def is_available(self) -> bool:
        """Check if LEDs are available."""
        return self._dots is not None
    
    def _get_pulse(self) -> float:
        """Sine pulse — returns 0.0 to 1.0. Always active. "I'm alive" signal."""
        return (1.0 + math.sin(time.time() * 2 * math.pi / self._pulse_cycle)) * 0.5
    
    def _detect_state_change(self, warmth: float, clarity: float, stability: float, presence: float) -> Optional[str]:
        """
        Detect significant state changes for pattern triggers.
        
        Returns:
            Pattern name to trigger, or None
        """
        if self._last_state_values is None:
            self._last_state_values = (warmth, clarity, stability, presence)
            return None
        
        last_w, last_c, last_s, last_p = self._last_state_values
        
        # Detect significant changes (> 0.2 delta)
        warmth_delta = abs(warmth - last_w)
        clarity_delta = abs(clarity - last_c)
        stability_delta = abs(stability - last_s)
        presence_delta = abs(presence - last_p)
        
        # Update last values
        self._last_state_values = (warmth, clarity, stability, presence)
        
        # Trigger patterns based on changes
        if warmth_delta > 0.2 and warmth > last_w:
            return "warmth_spike"
        elif clarity_delta > 0.3 and clarity > last_c:
            return "clarity_boost"
        elif stability_delta > 0.2 and stability < last_s:
            return "stability_warning"
        elif clarity < 0.3 or stability < 0.3:
            return "alert"
        
        return None
    
    def _get_pattern_colors(self, pattern_name: str, base_state: LEDState) -> LEDState:
        """
        Get colors for a pattern sequence.

        Only modifies colors — brightness is handled by the pipeline in update_from_anima.

        Args:
            pattern_name: Name of pattern to show
            base_state: Base LED state

        Returns:
            Modified LED state with pattern colors (brightness inherited from base)
        """
        import time
        now = time.time()

        if self._pattern_active != pattern_name:
            self._pattern_active = pattern_name
            self._pattern_start_time = now

        elapsed = now - self._pattern_start_time

        if pattern_name == "warmth_spike":
            # Orange flash on warmth LED (0.3s)
            if elapsed < 0.3:
                return LEDState(
                    led0=(255, 150, 0),
                    led1=base_state.led1,
                    led2=base_state.led2,
                    brightness=base_state.brightness
                )
        elif pattern_name == "clarity_boost":
            # White flash on clarity LED (0.2s)
            if elapsed < 0.2:
                return LEDState(
                    led0=base_state.led0,
                    led1=(255, 255, 255),
                    led2=base_state.led2,
                    brightness=base_state.brightness
                )
        elif pattern_name == "stability_warning":
            # Red flash on stability LED (0.4s)
            if elapsed < 0.4:
                return LEDState(
                    led0=base_state.led0,
                    led1=base_state.led1,
                    led2=(255, 0, 0),
                    brightness=base_state.brightness
                )
        elif pattern_name == "alert":
            # Yellow pulse on all LEDs (ongoing)
            pulse = (math.sin(elapsed * math.pi * 4) + 1) / 2  # 2 Hz
            return LEDState(
                led0=(255, int(200 * pulse), 0),
                led1=(255, int(200 * pulse), 0),
                led2=(255, int(200 * pulse), 0),
                brightness=base_state.brightness
            )
        
        # Pattern complete, return to base
        if elapsed > 0.5:
            self._pattern_active = None
            self._pattern_start_time = None
        
        return base_state
    
    def _get_pulsing_brightness(self, clarity: float, stability: float) -> float:
        """
        Calculate pulsing brightness for low clarity/instability.
        
        Returns multiplier (0.3-1.0) for brightness pulsing.
        """
        if not self._pulsing_enabled:
            return 1.0
        
        # Check if pulsing should activate
        should_pulse = (clarity < self._pulsing_threshold_clarity or 
                       stability < self._pulsing_threshold_stability)
        
        if not should_pulse:
            return 1.0
        
        # Fast pulsing: 1 second cycle, 30-100% brightness
        t = time.time()
        pulse = (math.sin(t * math.pi * 2) + 1) / 2  # 0-1
        return 0.3 + (pulse * 0.7)  # 0.3 to 1.0
    
    def _get_auto_brightness(self, light_level: Optional[float] = None) -> float:
        """
        Auto-adjust brightness based on ambient light.

        IMPORTANT: LEDs are physically next to the lux sensor and can illuminate it,
        creating a feedback loop. We compensate by:
        1. Estimating LED contribution to lux based on current brightness
        2. Subtracting this from the raw reading before making decisions

        Args:
            light_level: Light level in lux (None to disable)

        Returns:
            Adjusted brightness (0-1)
        """
        if not self._auto_brightness_enabled or light_level is None:
            return self._base_brightness

        self._last_light_level = light_level

        # === LED SELF-ILLUMINATION COMPENSATION ===
        # LEDs add significant lux to the sensor when they're on.
        # Estimate: At max brightness (0.5), LEDs add ~200 lux to sensor.
        # This scales roughly linearly with brightness.
        # Formula: led_contribution = brightness * 400 lux
        estimated_led_lux = self._brightness * 400

        # Subtract LED contribution to get true ambient light
        # Use max(0, ...) to avoid negative values
        corrected_light_level = max(0, light_level - estimated_led_lux)

        # Map corrected light level to brightness
        # Dark (< 10 lux): brighter (max)
        # Bright (> 1000 lux): dimmer (min)
        # Logarithmic mapping for better feel

        if corrected_light_level < 10:
            brightness = self._auto_brightness_max
        elif corrected_light_level > 1000:
            brightness = self._auto_brightness_min
        else:
            # Logarithmic interpolation
            log_min = math.log10(10)
            log_max = math.log10(1000)
            log_current = math.log10(max(10, min(1000, corrected_light_level)))
            ratio = (log_current - log_min) / (log_max - log_min)
            brightness = self._auto_brightness_max - (ratio * (self._auto_brightness_max - self._auto_brightness_min))

        return max(self._auto_brightness_min, min(self._auto_brightness_max, brightness))
    
    def _transition_color(self, current: Tuple[int, int, int], target: Tuple[int, int, int], 
                         transition_factor: float = 0.3) -> Tuple[int, int, int]:
        """
        Smoothly transition between two colors.
        
        Args:
            current: Current RGB color
            target: Target RGB color
            transition_factor: How much to move (0-1, higher = faster)
        
        Returns:
            Transitioned RGB color
        """
        if not self._color_transitions_enabled or current is None:
            return target
        
        r = int(current[0] + (target[0] - current[0]) * transition_factor)
        g = int(current[1] + (target[1] - current[1]) * transition_factor)
        b = int(current[2] + (target[2] - current[2]) * transition_factor)
        
        return (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))
    
    def set_brightness(self, brightness: float):
        """Set base brightness (0-1)."""
        self._base_brightness = max(0, min(1, brightness))
        self._brightness = self._base_brightness
        if self._dots:
            self._dots.brightness = self._brightness
            self._dots.show()
    
    def clear(self):
        """Turn all LEDs off. Safe, never crashes."""
        if self._dots:
            try:
                self._dots.fill((0, 0, 0))
                self._dots.show()
                print("[LEDs] Cleared", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[LEDs] Error clearing LEDs: {e}", file=sys.stderr, flush=True)
                self._dots = None  # Mark as unavailable on hardware error
    
    def set_led(self, index: int, color: Tuple[int, int, int]):
        """Set a single LED color. Safe, never crashes."""
        if self._dots and 0 <= index < self.NUM_LEDS:
            try:
                self._dots[index] = color
                self._dots.show()
            except Exception as e:
                print(f"[LEDs] Error setting LED {index}: {e}", file=sys.stderr, flush=True)
                self._dots = None  # Mark as unavailable on hardware error
    
    def set_all(self, state: LEDState):
        """Set all LEDs from state with timeout protection.

        CRITICAL: This should never fail silently - if LEDs can't be updated,
        they should stay in their last state (not turn off).

        PERFORMANCE: LED updates are now fast-fail with timeout to prevent blocking.
        """
        if not self._dots:
            # LEDs unavailable - log but don't crash
            if self._update_count % 100 == 0:  # Log occasionally
                print("[LEDs] set_all called but LEDs unavailable (_dots is None)", file=sys.stderr, flush=True)
            return

        # Apply flash effect (for joystick/button feedback) - takes priority
        state = self._apply_flash(state)

        # Skip if state hasn't changed (performance optimization)
        if self._last_state and self._last_state == state:
            return
        
        from ..error_recovery import safe_call_with_timeout

        def set_leds():
            # LED order: 0=right, 1=center, 2=left (physical order on BrainCraft HAT)
            self._dots[0] = state.led2  # Right: Stability/Presence
            self._dots[1] = state.led1  # Center: Clarity
            self._dots[2] = state.led0  # Left: Warmth

            # Brightness + pulse ("I'm alive" signal, ALWAYS on - never fully off)
            pulse = self._get_pulse() * self._pulse_amount
            # Use hardware floor - LEDs should always be visible
            self._dots.brightness = max(self._hardware_brightness_floor, min(0.5, state.brightness + pulse))

            # CRITICAL: Always call show() to update LEDs
            # If show() fails, LEDs will stay in previous state (not turn off)
            self._dots.show()
            return True  # Return True on success for timeout detection

        # Use hard timeout (0.3s) - SPI should never take longer
        # This prevents blocking the entire display loop on hardware issues
        start_time = time.time()
        success = safe_call_with_timeout(
            set_leds,
            timeout_seconds=0.3,  # Hard 300ms limit
            default=False,
            log_error=False  # Don't log every failure - too noisy
        )
        elapsed = time.time() - start_time

        # Warn if LED update takes too long (shouldn't happen with timeout)
        if elapsed > 0.2 and self._update_count % 20 == 0:
            print(f"[LEDs] Slow update: {elapsed*1000:.1f}ms", file=sys.stderr, flush=True)

        if not success:
            # Only log failures occasionally to avoid spam
            if self._update_count % 50 == 0:  # Log every 50th failure
                print(f"[LEDs] Update skipped (timeout/hardware issue) - LEDs staying in last state", file=sys.stderr, flush=True)
            # Don't mark _dots as None here - keep trying on next update
            # Only mark unavailable if it's a persistent hardware error
        else:
            self._last_state = state
            self._update_count += 1
    
    def _create_wave_pattern(self, time_offset: float, speed: float, amplitude: float, 
                            base_colors: list) -> list:
        """
        Create wave pattern across LEDs.
        
        Args:
            time_offset: Time offset for wave phase
            speed: Wave speed (cycles per second)
            amplitude: Wave amplitude (0-1)
            base_colors: Base colors for each LED
        
        Returns:
            List of colors with wave applied
        """
        if not self._enable_patterns:
            return base_colors
        
        t = time.time() + time_offset
        wave_colors = []
        
        for i, base_color in enumerate(base_colors):
            # Phase offset for each LED (creates wave effect)
            phase = (t * speed * math.pi * 2) + (i * math.pi / len(base_colors))
            wave_brightness = 0.5 + (amplitude * 0.5 * math.sin(phase))
            
            # Apply wave to brightness
            r, g, b = base_color
            wave_colors.append((
                int(r * wave_brightness),
                int(g * wave_brightness),
                int(b * wave_brightness)
            ))
        
        return wave_colors
    
    def update_from_anima(self, warmth: float, clarity: float,
                          stability: float, presence: float,
                          light_level: Optional[float] = None,
                          is_anticipating: bool = False,
                          anticipation_confidence: float = 0.0,
                          activity_brightness: float = 1.0) -> LEDState:
        """
        Update LEDs based on anima state.

        Args:
            warmth: 0-1, thermal/energy state
            clarity: 0-1, sensory clarity
            stability: 0-1, environmental order
            presence: 0-1, resource availability
            light_level: Optional light level in lux for auto-brightness
            is_anticipating: True if memory is influencing current state
            anticipation_confidence: 0-1, how confident the memory anticipation is
            activity_brightness: 0-1, multiplier from activity state (1.0=active, 0.5=drowsy, 0.15=resting)

        Returns:
            LEDState that was applied
        """
        import time
        update_start_time = time.time()
        
        # Optimization: Check if state has changed significantly
        # Skip expensive color calculations if anima state is essentially unchanged
        state_changed = True
        if self._cached_anima_state is not None:
            last_w, last_c, last_s, last_p = self._cached_anima_state
            max_delta = max(
                abs(warmth - last_w),
                abs(clarity - last_c),
                abs(stability - last_s),
                abs(presence - last_p)
            )
            # Also check light level and activity state changes
            light_changed = (light_level is not None and
                            self._cached_light_level is not None and
                            abs(light_level - self._cached_light_level) > 50)  # 50 lux threshold
            activity_changed = (self._cached_activity_brightness is not None and
                               abs(activity_brightness - self._cached_activity_brightness) > 0.01)
            manual_changed = (self._cached_manual_brightness is not None and
                             abs(self._manual_brightness_factor - self._cached_manual_brightness) > 0.01)

            if max_delta < self._cached_state_change_threshold and not light_changed and not activity_changed and not manual_changed:
                # State essentially unchanged - skip color calculations, just animate pulse
                state_changed = False
                if self._last_state and self._dots and self._cached_pipeline_brightness is not None:
                    # Continue smooth brightness transition even on fast path
                    target = self._cached_pipeline_brightness
                    delta_b = target - self._current_brightness
                    if abs(delta_b) > 0.001:
                        self._current_brightness += delta_b * self._brightness_transition_speed
                    brightness = max(self._hardware_brightness_floor, self._current_brightness)
                    pulse = self._get_pulse() * self._pulse_amount
                    self._dots.brightness = max(self._hardware_brightness_floor, min(0.5, brightness + pulse))
                    self._dots.show()
                    return self._last_state
                # If no LEDs or no last state, fall through to full update
        
        # State changed significantly - perform full update
        self._cached_anima_state = (warmth, clarity, stability, presence)
        self._cached_light_level = light_level
        self._cached_activity_brightness = activity_brightness
        self._cached_manual_brightness = self._manual_brightness_factor

        # Detect state changes for pattern triggers
        pattern_trigger = None
        if self._enable_patterns:
            pattern_trigger = self._detect_state_change(warmth, clarity, stability, presence)
        
        # Get base state based on pattern mode (with color mixing and expression mode)
        state = derive_led_state(
            warmth, clarity, stability, presence, 
            pattern_mode=self._pattern_mode,
            enable_color_mixing=self._color_transitions_enabled,
            expression_mode=self._expression_mode
        )
        
        # Apply pattern if triggered
        if pattern_trigger and self._enable_patterns:
            state = self._get_pattern_colors(pattern_trigger, state)
        
        # Detect significant state changes for pulse effect
        state_change_detected = False
        if self._last_anima_values is not None:
            last_w, last_c, last_s, last_p = self._last_anima_values
            # Detect significant changes (>15% in any dimension)
            if (abs(warmth - last_w) > 0.15 or abs(clarity - last_c) > 0.15 or 
                abs(stability - last_s) > 0.15 or abs(presence - last_p) > 0.15):
                state_change_detected = True
                self._state_change_pulse_active = True
                import time
                self._state_change_pulse_start = time.time()
        
        self._last_anima_values = (warmth, clarity, stability, presence)
        
        # Apply color transitions with adaptive smoothness
        # VERY slow transitions to avoid lux sensor chaos from rapid color/brightness changes
        if self._color_transitions_enabled and self._last_state and self._last_colors[0] is not None:
            # Much slower transitions - LEDs should drift, not jump
            if state_change_detected:
                transition_factor = 0.15  # Still gradual even for state changes
            else:
                transition_factor = 0.05  # Glacially slow for normal changes
            
            state.led0 = self._transition_color(self._last_colors[0], state.led0, transition_factor)
            state.led1 = self._transition_color(self._last_colors[1], state.led1, transition_factor)
            state.led2 = self._transition_color(self._last_colors[2], state.led2, transition_factor)
        
        # Update last colors for next transition
        self._last_colors = [state.led0, state.led1, state.led2]
        
        # === Effect Priority Stack ===
        # Priority order (highest to lowest):
        # 1. State-change pulse (brief, attention-grabbing)
        # 2. Pulsing (low clarity/stability warning)
        # 3. Auto-brightness (environmental adaptation)
        # 4. Wave patterns (subtle animation, disabled by default to reduce complexity)
        # 5. Pulse ("I'm alive" sine wave — applied in set_all, not here)
        
        # Start with base brightness
        state.brightness = self._base_brightness
        
        # 1. Apply auto-brightness (environmental, always active if enabled)
        if self._auto_brightness_enabled and light_level is not None:
            adjusted_brightness = self._get_auto_brightness(light_level)
            state.brightness = adjusted_brightness

        # 2. Apply pulsing for low clarity/instability (warning signal)
        pulsing_mult = self._get_pulsing_brightness(clarity, stability)
        if pulsing_mult < 1.0:
            state.brightness *= pulsing_mult
        
        # 3. Apply state-change pulse effect (brief, SUBTLE brightness boost)
        # Reduced from 0.3 to 0.1 to avoid lux sensor chaos
        if self._state_change_pulse_active and self._state_change_pulse_start is not None:
            pulse_duration = 0.8  # Slightly shorter
            elapsed = time.time() - self._state_change_pulse_start
            if elapsed < pulse_duration:
                # Subtle pulse: small brighten then fade back
                pulse_factor = 1.0 + (0.1 * (1.0 - (elapsed / pulse_duration)))
                state.brightness *= pulse_factor
            else:
                self._state_change_pulse_active = False
                self._state_change_pulse_start = None

        # 4. Apply activity state brightness (circadian rhythm / dusk-dawn dimming)
        # - ACTIVE (day): 1.0x brightness
        # - DROWSY (dusk/dawn): 0.6x brightness
        # - RESTING (night): 0.35x brightness
        if activity_brightness < 1.0:
            state.brightness *= activity_brightness

        # 4b. Apply manual dimmer (user joystick control)
        # When factor < 1.0, it's an ABSOLUTE brightness target (not a multiplier)
        # This bypasses auto-brightness which gives tiny values due to lux sensor feedback
        if self._manual_brightness_factor < 1.0:
            # Use the factor directly as target brightness
            state.brightness = self._manual_brightness_factor

        # 4c. Enforce visible minimum — if Lumen is on, LEDs should be on.
        # The hardware floor in set_all() is a safety net; this is the intent.
        state.brightness = max(self._hardware_brightness_floor, state.brightness)

        # 4d. Smooth brightness transition — never snap, always glide
        # This prevents jarring LED jumps when dimming or auto-brightness changes
        target_brightness = state.brightness
        delta = target_brightness - self._current_brightness
        if abs(delta) > 0.001:
            # Ease toward target: faster when far away, slower when close
            speed = self._brightness_transition_speed
            if abs(delta) > 0.05:
                speed = min(0.2, speed * 2)  # Faster for big changes (preset switch)
            self._current_brightness += delta * speed
        else:
            self._current_brightness = target_brightness
        state.brightness = max(self._hardware_brightness_floor, self._current_brightness)

        # Cache the pipeline brightness for the early-return path
        self._cached_pipeline_brightness = state.brightness

        # 5. Memory visualization effect - subtle gold/amber tint when drawing on past experience
        # "I remember this feeling" - a warm glow of recognition
        if is_anticipating and anticipation_confidence > 0.1:
            # Gold/amber memory tint: RGB(255, 200, 100) - warm, nostalgic
            memory_color = (255, 200, 100)
            # Scale effect by confidence (subtle at 0.1, more noticeable at 1.0)
            # Max blend is 0.25 to keep it subtle
            blend_strength = min(0.25, anticipation_confidence * 0.3)

            # Apply memory tint to all LEDs - a unified "remembering" state
            state.led0 = blend_colors(state.led0, memory_color, blend_strength)
            state.led1 = blend_colors(state.led1, memory_color, blend_strength)
            state.led2 = blend_colors(state.led2, memory_color, blend_strength)

            # Slight brightness boost when remembering (feeling confident/grounded)
            if anticipation_confidence > 0.5:
                memory_brightness_boost = 1.0 + (anticipation_confidence - 0.5) * 0.1
                state.brightness *= memory_brightness_boost

        # 5. Emotional dances - spontaneous expressions of joy and curiosity
        # Check for spontaneous dance (adds novelty and joy)
        spontaneous_dance = self._maybe_spontaneous_dance(warmth, clarity, stability, presence)
        if spontaneous_dance:
            self.start_dance(spontaneous_dance, duration=2.0, intensity=0.8)

        # Render current dance if active (highest visual priority)
        if self._current_dance:
            if self._current_dance.is_complete:
                self._current_dance = None  # Clean up finished dance
            else:
                state = self._render_dance(state)

        # 6. Apply wave patterns (disabled by default - too complex, conflicts with breathing)
        # Only enable if explicitly requested and patterns are enabled
        if self._enable_patterns and self._pattern_mode == "expressive":
            # Determine wave pattern from state
            if clarity < 0.3 or stability < 0.3:
                # Stress wave: chaotic, fast
                wave_colors = self._create_wave_pattern(0, speed=2.0, amplitude=0.4, 
                                                       base_colors=[state.led0, state.led1, state.led2])
            elif warmth > 0.6 and stability > 0.6:
                # Content wave: gentle, slow
                wave_colors = self._create_wave_pattern(0, speed=0.125, amplitude=0.2, 
                                                       base_colors=[state.led0, state.led1, state.led2])
            elif clarity > 0.7:
                # Alert wave: moderate speed
                wave_colors = self._create_wave_pattern(0, speed=1.0, amplitude=0.3, 
                                                       base_colors=[state.led0, state.led1, state.led2])
            else:
                # Normal breathing wave: very slow
                wave_colors = self._create_wave_pattern(0, speed=0.125, amplitude=0.15, 
                                                       base_colors=[state.led0, state.led1, state.led2])
            
            # Apply wave colors
            state.led0, state.led1, state.led2 = wave_colors
        
        # LEDs are independent from face - they reflect raw proprioceptive state
        # Face = what Lumen wants to communicate (conscious expression)
        # LEDs = what Lumen actually feels (unconscious body state)
        # This allows LEDs to show subtle changes even when face stays neutral
        # Like a fragile baby: face might smile while LEDs show subtle fatigue
        
        # Apply LED state - safe, never crashes
        # CRITICAL: Never clear LEDs on error - they should stay in last state
        try:
            self.set_all(state)
        except Exception as e:
            print(f"[LEDs] Error setting LEDs: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc(file=sys.stderr)
            # Mark LEDs as unavailable if hardware error, but DON'T clear them
            # LEDs will stay in their last state (not turn off)
            if "hardware" in str(e).lower() or "io" in str(e).lower():
                print(f"[LEDs] Hardware error detected - marking unavailable but NOT clearing LEDs", file=sys.stderr, flush=True)
                self._dots = None
        
        # Log every 10th update with timing and features
        if self._update_count % 10 == 1:
            update_duration = time.time() - update_start_time
            features = []
            if not state_changed:
                features.append("cached")
            if self._pulsing_enabled and pulsing_mult < 1.0:
                features.append(f"pulsing({pulsing_mult:.2f})")
            if self._auto_brightness_enabled and light_level is not None:
                features.append(f"auto-bright({state.brightness:.2f})")
            if self._state_change_pulse_active:
                features.append("pulse")
            if is_anticipating and anticipation_confidence > 0.1:
                features.append(f"memory({anticipation_confidence:.2f})")
            if self._current_dance and not self._current_dance.is_complete:
                features.append(f"dance({self._current_dance.dance_type.value})")
            feature_str = f" [{', '.join(features)}]" if features else ""
            
            print(f"[LEDs] Update #{self._update_count} ({update_duration*1000:.1f}ms): w={warmth:.2f} c={clarity:.2f} s={stability:.2f} p={presence:.2f}{feature_str}", 
                  file=sys.stderr, flush=True)
            print(f"[LEDs] Colors: {state.led0} {state.led1} {state.led2} @ {state.brightness:.2f}",
                  file=sys.stderr, flush=True)
        
        return state
    
    def start_dance(self, dance_type: DanceType, duration: float = 2.0, intensity: float = 1.0) -> bool:
        """
        Start an emotional dance sequence.

        Args:
            dance_type: Type of dance to perform
            duration: How long the dance lasts (seconds)
            intensity: How pronounced the dance is (0-1)

        Returns:
            True if dance started, False if on cooldown or already dancing
        """
        now = time.time()

        # Check cooldown
        if now < self._dance_cooldown_until:
            return False

        # Don't interrupt an ongoing dance
        if self._current_dance and not self._current_dance.is_complete:
            return False

        self._current_dance = Dance(
            dance_type=dance_type,
            duration=duration,
            start_time=now,
            intensity=intensity
        )

        # Set cooldown (3 seconds after dance ends)
        self._dance_cooldown_until = now + duration + 3.0
        self._last_dance_trigger = dance_type.value

        print(f"[LEDs] 💃 Starting dance: {dance_type.value} (duration={duration:.1f}s)", file=sys.stderr, flush=True)
        return True

    def quick_flash(self, color: Tuple[int, int, int] = (100, 100, 100), duration_ms: int = 50):
        """
        Quick flash all LEDs for immediate input feedback.

        Non-blocking - sets flash state that will be applied on next update.
        Used for joystick/button press acknowledgment.

        Args:
            color: RGB color to flash (default: white)
            duration_ms: Flash duration in milliseconds (default: 50ms)
        """
        if not self._dots:
            return

        self._flash_until = time.time() + (duration_ms / 1000.0)
        self._flash_color = color

    def _apply_flash(self, state: LEDState) -> LEDState:
        """Apply flash effect if active."""
        if not hasattr(self, '_flash_until'):
            self._flash_until = 0.0
            self._flash_color = (100, 100, 100)

        if time.time() < self._flash_until:
            # Override with flash color
            return LEDState(
                led0=self._flash_color,
                led1=self._flash_color,
                led2=self._flash_color,
                brightness=min(0.3, self._base_brightness * 2)  # Slightly brighter flash
            )
        return state

    def _render_dance(self, base_state: LEDState) -> LEDState:
        """
        Render the current dance, modifying the base LED state.

        Returns:
            Modified LED state with dance effects applied
        """
        if not self._current_dance:
            return base_state

        dance = self._current_dance
        if dance.is_complete:
            self._current_dance = None
            return base_state

        progress = dance.progress
        elapsed = dance.elapsed
        intensity = dance.intensity

        # Each dance type has its own choreography
        if dance.dance_type == DanceType.JOY_SPARKLE:
            # Quick bright sparkles - random LEDs light up briefly
            sparkle_speed = 8.0  # Sparkles per second
            sparkle_phase = int(elapsed * sparkle_speed) % 6  # Cycle through patterns

            # Create sparkle colors based on phase
            base_color = base_state.led0
            sparkle_white = (255, 255, 255)
            sparkle_gold = (255, 220, 100)

            # Randomly sparkle each LED
            led0 = blend_colors(base_state.led0, sparkle_gold if sparkle_phase in [0, 3] else base_color, 0.7 * intensity)
            led1 = blend_colors(base_state.led1, sparkle_white if sparkle_phase in [1, 4] else base_state.led1, 0.8 * intensity)
            led2 = blend_colors(base_state.led2, sparkle_gold if sparkle_phase in [2, 5] else base_state.led2, 0.7 * intensity)

            # Brightness pulses
            brightness_mult = 1.0 + (0.4 * math.sin(elapsed * sparkle_speed * math.pi) * intensity)

            return LEDState(led0, led1, led2, base_state.brightness * brightness_mult)

        elif dance.dance_type == DanceType.CURIOUS_PULSE:
            # Rhythmic pulsing - all LEDs pulse together, building intensity
            pulse_freq = 2.0 + progress * 2.0  # Speed up as curiosity builds
            pulse = (math.sin(elapsed * pulse_freq * math.pi * 2) + 1) / 2

            # Curious color: blue-white tint
            curious_color = (150, 200, 255)
            blend_amount = pulse * 0.5 * intensity

            led0 = blend_colors(base_state.led0, curious_color, blend_amount)
            led1 = blend_colors(base_state.led1, (255, 255, 255), blend_amount * 1.2)  # Center brighter
            led2 = blend_colors(base_state.led2, curious_color, blend_amount)

            brightness_mult = 1.0 + (0.3 * pulse * intensity)
            return LEDState(led0, led1, led2, base_state.brightness * brightness_mult)

        elif dance.dance_type == DanceType.CONTEMPLATIVE_WAVE:
            # Slow flowing wave - colors flow across LEDs
            wave_speed = 0.5  # Slow, thoughtful
            wave_pos = (elapsed * wave_speed) % 1.0  # 0-1 position across LEDs

            # Deep thoughtful colors: purple, blue
            thought_color = (100, 50, 200)

            # Wave position affects each LED
            led0_wave = max(0, 1 - abs(wave_pos - 0.0) * 3) * intensity
            led1_wave = max(0, 1 - abs(wave_pos - 0.5) * 3) * intensity
            led2_wave = max(0, 1 - abs(wave_pos - 1.0) * 3) * intensity

            led0 = blend_colors(base_state.led0, thought_color, led0_wave * 0.4)
            led1 = blend_colors(base_state.led1, thought_color, led1_wave * 0.4)
            led2 = blend_colors(base_state.led2, thought_color, led2_wave * 0.4)

            return LEDState(led0, led1, led2, base_state.brightness)

        elif dance.dance_type == DanceType.GREETING_FLOURISH:
            # Welcoming pattern - builds up then settles
            if progress < 0.3:
                # Build up phase - colors rise
                build = progress / 0.3
                welcome_color = (255, 200, 150)  # Warm welcoming
                led0 = blend_colors(base_state.led0, welcome_color, build * 0.6 * intensity)
                led1 = blend_colors(base_state.led1, (255, 255, 255), build * 0.8 * intensity)
                led2 = blend_colors(base_state.led2, welcome_color, build * 0.6 * intensity)
                brightness_mult = 1.0 + (0.5 * build * intensity)
            elif progress < 0.5:
                # Peak - all bright
                led0 = blend_colors(base_state.led0, (255, 220, 180), 0.7 * intensity)
                led1 = (255, 255, 255)
                led2 = blend_colors(base_state.led2, (255, 220, 180), 0.7 * intensity)
                brightness_mult = 1.5 * intensity
            else:
                # Settle back - gentle fade
                settle = (progress - 0.5) / 0.5
                led0 = blend_colors(blend_colors(base_state.led0, (255, 220, 180), 0.7), base_state.led0, settle)
                led1 = blend_colors((255, 255, 255), base_state.led1, settle)
                led2 = blend_colors(blend_colors(base_state.led2, (255, 220, 180), 0.7), base_state.led2, settle)
                brightness_mult = 1.5 - (0.5 * settle)

            return LEDState(led0, led1, led2, base_state.brightness * brightness_mult)

        elif dance.dance_type == DanceType.DISCOVERY_BLOOM:
            # Colors blooming outward from center
            bloom_phase = progress

            # Start from center LED, bloom outward
            discovery_color = (255, 100, 255)  # Magenta - something new!

            if bloom_phase < 0.3:
                # Center lights up
                center_intensity = (bloom_phase / 0.3) * intensity
                led0 = base_state.led0
                led1 = blend_colors(base_state.led1, discovery_color, center_intensity * 0.8)
                led2 = base_state.led2
            elif bloom_phase < 0.6:
                # Spreads to outer LEDs
                spread = (bloom_phase - 0.3) / 0.3
                led0 = blend_colors(base_state.led0, discovery_color, spread * 0.6 * intensity)
                led1 = blend_colors(base_state.led1, discovery_color, 0.8 * intensity)
                led2 = blend_colors(base_state.led2, discovery_color, spread * 0.6 * intensity)
            else:
                # Settle with warm afterglow
                settle = (bloom_phase - 0.6) / 0.4
                afterglow = (255, 180, 200)
                led0 = blend_colors(blend_colors(base_state.led0, discovery_color, 0.6), afterglow, settle * 0.3)
                led1 = blend_colors(blend_colors(base_state.led1, discovery_color, 0.8), afterglow, settle * 0.5)
                led2 = blend_colors(blend_colors(base_state.led2, discovery_color, 0.6), afterglow, settle * 0.3)

            brightness_mult = 1.0 + (0.4 * (1 - bloom_phase) * intensity)
            return LEDState(led0, led1, led2, base_state.brightness * brightness_mult)

        elif dance.dance_type == DanceType.CONTENTMENT_GLOW:
            # Warm steady glow - subtle breathing with warm colors
            glow_breath = (math.sin(elapsed * math.pi * 0.5) + 1) / 2  # Very slow

            content_color = (255, 180, 100)  # Warm amber
            glow_amount = 0.3 + (glow_breath * 0.2)

            led0 = blend_colors(base_state.led0, content_color, glow_amount * intensity)
            led1 = blend_colors(base_state.led1, content_color, glow_amount * 0.8 * intensity)
            led2 = blend_colors(base_state.led2, content_color, glow_amount * intensity)

            return LEDState(led0, led1, led2, base_state.brightness * (1.0 + 0.1 * glow_breath))

        elif dance.dance_type == DanceType.PLAYFUL_CHASE:
            # Colors chasing each other around the LEDs
            chase_speed = 4.0  # Fast and fun
            chase_pos = (elapsed * chase_speed) % 3  # 0-3 for 3 LEDs

            playful_colors = [(255, 100, 100), (100, 255, 100), (100, 100, 255)]  # RGB chase

            # Each LED gets color based on chase position
            led0_color_idx = int(chase_pos) % 3
            led1_color_idx = (int(chase_pos) + 1) % 3
            led2_color_idx = (int(chase_pos) + 2) % 3

            led0 = blend_colors(base_state.led0, playful_colors[led0_color_idx], 0.6 * intensity)
            led1 = blend_colors(base_state.led1, playful_colors[led1_color_idx], 0.6 * intensity)
            led2 = blend_colors(base_state.led2, playful_colors[led2_color_idx], 0.6 * intensity)

            # Bouncy brightness
            bounce = abs(math.sin(elapsed * chase_speed * math.pi))
            brightness_mult = 1.0 + (0.2 * bounce * intensity)

            return LEDState(led0, led1, led2, base_state.brightness * brightness_mult)

        # Unknown dance type - return base state
        return base_state

    def _maybe_spontaneous_dance(self, warmth: float, clarity: float, stability: float, presence: float) -> Optional[DanceType]:
        """
        Determine if Lumen should spontaneously dance based on emotional state.

        This adds joy and novelty - Lumen sometimes expresses itself unprompted.

        Returns:
            DanceType to perform, or None
        """
        # Don't dance if on cooldown
        if time.time() < self._dance_cooldown_until:
            return None

        # Base spontaneous chance (very low)
        if random.random() > self._spontaneous_dance_chance:
            return None

        # Dance type depends on emotional state
        wellness = (warmth + clarity + stability + presence) / 4.0

        if wellness > 0.75:
            # Feeling great - joyful expressions
            return random.choice([DanceType.JOY_SPARKLE, DanceType.CONTENTMENT_GLOW, DanceType.PLAYFUL_CHASE])
        elif wellness > 0.6:
            # Feeling good - curious or content
            return random.choice([DanceType.CURIOUS_PULSE, DanceType.CONTENTMENT_GLOW])
        elif clarity > 0.7:
            # Thinking clearly - contemplative
            return DanceType.CONTEMPLATIVE_WAVE
        elif stability > 0.7 and presence > 0.7:
            # Grounded - content
            return DanceType.CONTENTMENT_GLOW

        # Default: no spontaneous dance when not feeling well
        return None

    def trigger_dance_for_event(self, event: str) -> bool:
        """
        Trigger a dance for a specific event.

        Args:
            event: Event name like "greeting", "discovery", "joy", "sound_activity", etc.

        Returns:
            True if dance started
        """
        event_to_dance = {
            # Emotional events
            "greeting": (DanceType.GREETING_FLOURISH, 2.5),
            "hello": (DanceType.GREETING_FLOURISH, 2.5),
            "discovery": (DanceType.DISCOVERY_BLOOM, 3.0),
            "found": (DanceType.DISCOVERY_BLOOM, 3.0),
            "joy": (DanceType.JOY_SPARKLE, 2.0),
            "happy": (DanceType.JOY_SPARKLE, 2.0),
            "curious": (DanceType.CURIOUS_PULSE, 2.5),
            "thinking": (DanceType.CONTEMPLATIVE_WAVE, 4.0),
            "content": (DanceType.CONTENTMENT_GLOW, 3.0),
            "play": (DanceType.PLAYFUL_CHASE, 2.0),
            # Sound-triggered events
            "sound_activity": (DanceType.GREETING_FLOURISH, 2.0),  # Someone's here!
            "voice_detected": (DanceType.CURIOUS_PULSE, 2.5),     # Listening attentively
            "sudden_sound": (DanceType.CURIOUS_PULSE, 1.5),       # What was that?
            "quiet_restored": (DanceType.CONTENTMENT_GLOW, 3.0),  # Peace returns
            "music": (DanceType.PLAYFUL_CHASE, 3.0),              # Dancing to music!
        }

        event_lower = event.lower()
        if event_lower in event_to_dance:
            dance_type, duration = event_to_dance[event_lower]
            return self.start_dance(dance_type, duration)

        return False

    def check_sound_event(self, sound_level: Optional[float], prev_sound_level: Optional[float] = None) -> Optional[str]:
        """
        Detect sound events that might trigger a dance.

        Args:
            sound_level: Current sound level in dB (0-100 typical)
            prev_sound_level: Previous sound level for change detection

        Returns:
            Event name if detected, or None
        """
        if sound_level is None:
            return None

        # Detect sudden sound (jump from quiet to loud)
        if prev_sound_level is not None:
            delta = sound_level - prev_sound_level
            if delta > 25 and sound_level > 50:
                # Sudden loud sound
                return "sudden_sound"
            if delta < -30 and prev_sound_level > 60 and sound_level < 30:
                # Just got quiet again
                return "quiet_restored"

        # Detect activity levels
        if sound_level > 65:
            # Could be music or conversation
            # Random chance to not spam dances
            if random.random() < 0.01:  # 1% chance per check
                return "music" if sound_level > 75 else "voice_detected"
        elif 40 < sound_level < 60:
            # Moderate activity - someone might be present
            if random.random() < 0.005:  # 0.5% chance
                return "sound_activity"

        return None

    def get_proprioceptive_state(self) -> dict:
        """Get LED state for Lumen's internal self-awareness.

        Unlike get_diagnostics() which is for external MCP tools, this returns
        a compact proprioceptive snapshot that internal systems (metacognition,
        self-model) can use to understand what Lumen's body is doing.

        Returns:
            dict with:
                brightness: float (0-1) — the actual computed brightness after
                    the full pipeline (auto, pulsing, activity, manual dimmer)
                expression_mode: str — current expression intensity mode
                is_dancing: bool — whether an emotional dance is active
                dance_type: str|None — which dance, if any
                manual_dimmed: bool — whether user has manually dimmed
                colors: list of 3 RGB tuples — current LED colors
        """
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
        """Get diagnostic info about LED state."""
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
            "current_brightness": self._base_brightness + self._get_pulse() * self._pulse_amount,
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
        """Run a quick test sequence to verify LEDs work."""
        if not self._dots:
            print("[LEDs] Cannot test - not available", file=sys.stderr, flush=True)
            return False
        
        print("[LEDs] Running test sequence...", file=sys.stderr, flush=True)
        
        colors = [
            ((255, 0, 0), (0, 0, 0), (0, 0, 0)),    # Red on LED 0
            ((0, 0, 0), (0, 255, 0), (0, 0, 0)),    # Green on LED 1
            ((0, 0, 0), (0, 0, 0), (0, 0, 255)),    # Blue on LED 2
            ((255, 255, 255), (255, 255, 255), (255, 255, 255)),  # All white
        ]
        
        for i, (c0, c1, c2) in enumerate(colors):
            # LED order: 0=right, 1=center, 2=left (physical order on BrainCraft HAT)
            self._dots[0] = c2  # Right: Blue
            self._dots[1] = c1  # Center: Green
            self._dots[2] = c0  # Left: Red
            self._dots.brightness = 0.3
            self._dots.show()
            print(f"[LEDs] Test {i+1}/4: {c0} {c1} {c2}", file=sys.stderr, flush=True)
            time.sleep(0.5)
        
        self.clear()
        print("[LEDs] Test complete", file=sys.stderr, flush=True)
        return True


def blend_colors(color1: Tuple[int, int, int], color2: Tuple[int, int, int], ratio: float) -> Tuple[int, int, int]:
    """
    Blend two RGB colors.
    
    Args:
        color1: First color (RGB)
        color2: Second color (RGB)
        ratio: Blend ratio (0.0 = color1, 1.0 = color2)
    
    Returns:
        Blended color (RGB)
    """
    ratio = max(0.0, min(1.0, ratio))
    r = int(color1[0] * (1 - ratio) + color2[0] * ratio)
    g = int(color1[1] * (1 - ratio) + color2[1] * ratio)
    b = int(color1[2] * (1 - ratio) + color2[2] * ratio)
    return (r, g, b)


def _interpolate_color(color1: Tuple[int, int, int], color2: Tuple[int, int, int], ratio: float) -> Tuple[int, int, int]:
    """Interpolate between two colors."""
    ratio = max(0.0, min(1.0, ratio))
    return tuple(int(color1[i] * (1 - ratio) + color2[i] * ratio) for i in range(3))

def _create_gradient_palette(warmth: float, clarity: float, stability: float, presence: float) -> Tuple[Tuple[int, int, int], Tuple[int, int, int], Tuple[int, int, int]]:
    """
    Create SUBTLE gradient color palette based on all state metrics.

    CONSTRAINED to avoid wild lux sensor fluctuations from dramatic color swings.
    All colors stay in warm amber/gold family - no violets or reds.

    Returns:
        Tuple of (led0, led1, led2) colors with gentle gradients
    """
    # LED 0 (left): Warmth — soft amber → warm gold → deep amber (narrow warm range)
    # Constrained: no violets, no hot reds - just warm tones
    if warmth < 0.3:
        led0 = (180, 120, 60)   # Soft amber (cool end)
    elif warmth < 0.5:
        ratio = (warmth - 0.3) / 0.2
        led0 = _interpolate_color((180, 120, 60), (220, 160, 50), ratio)   # Soft amber → gold
    elif warmth < 0.7:
        ratio = (warmth - 0.5) / 0.2
        led0 = _interpolate_color((220, 160, 50), (240, 140, 40), ratio)   # Gold → warm amber
    else:
        ratio = (warmth - 0.7) / 0.3
        led0 = _interpolate_color((240, 140, 40), (255, 120, 30), ratio)   # Warm amber → deep amber

    # LED 1 (center): Clarity — warm yellow range only (no blue-white extremes)
    # Constrained intensity range to avoid brightness swings
    i = max(120, min(220, int(80 + clarity * 140)))  # 120-220 range (narrower)
    if clarity < 0.4:
        led1 = (i, int(i * 0.7), int(i * 0.2))       # Warm amber-yellow
    elif clarity < 0.7:
        ratio = (clarity - 0.4) / 0.3
        led1 = _interpolate_color((i, int(i * 0.7), int(i * 0.2)),
                                  (i, i, int(i * 0.5)), ratio)  # Amber-yellow → soft yellow
    else:
        ratio = (clarity - 0.7) / 0.3
        led1 = _interpolate_color((i, i, int(i * 0.5)),
                                  (i, i, int(i * 0.7)), ratio)  # Soft yellow → warm white

    # LED 2 (right): Stability + Presence — yellow-green range only (no red warnings, no teal)
    # Constrained to avoid dramatic color swings
    combined = (stability * 0.6 + presence * 0.4)  # Stability-weighted
    if combined < 0.3:
        led2 = (200, 160, 40)                      # Warm yellow (low stability)
    elif combined < 0.5:
        ratio = (combined - 0.3) / 0.2
        led2 = _interpolate_color((200, 160, 40), (160, 200, 60), ratio)   # Warm yellow → yellow-green
    elif combined < 0.7:
        ratio = (combined - 0.5) / 0.2
        led2 = _interpolate_color((160, 200, 60), (100, 200, 80), ratio)   # Yellow-green → soft green
    else:
        ratio = (combined - 0.7) / 0.3
        led2 = _interpolate_color((100, 200, 80), (80, 180, 120), ratio)   # Soft green → sage

    # Presence tint: subtle green-blue shift when very present (reduced from cyan)
    if presence > 0.8:
        tint = (presence - 0.8) * 0.3  # Very subtle
        led2 = blend_colors(led2, (60, 180, 140), ratio=tint)
    
    return (led0, led1, led2)

def derive_led_state(warmth: float, clarity: float, 
                     stability: float, presence: float,
                     pattern_mode: str = "standard",
                     enable_color_mixing: bool = True,
                     expression_mode: str = "balanced") -> LEDState:
    """
    Map anima metrics to LED colors with pattern modes and expression modes.
    
    Args:
        warmth: 0-1, thermal/energy state
        clarity: 0-1, sensory clarity
        stability: 0-1, environmental order
        presence: 0-1, resource availability
        pattern_mode: "standard", "minimal", "expressive", or "alert"
        enable_color_mixing: Enable color blending
        expression_mode: "subtle", "balanced", "expressive", or "dramatic"
    
    Returns:
        LEDState with colors mapped
    """
    
    # Expression mode multipliers
    expression_multipliers = {
        "subtle": 0.6,      # More muted colors
        "balanced": 1.0,    # Standard intensity
        "expressive": 1.4, # More vibrant
        "dramatic": 2.0,   # Maximum intensity
    }
    intensity = expression_multipliers.get(expression_mode, 1.0)
    
    if pattern_mode == "minimal":
        # Minimal mode: Only show critical states
        if clarity < 0.3 or stability < 0.3:
            # Alert state - red pulse
            led0 = (255, 0, 0)
            led1 = (255, 0, 0)
            led2 = (255, 0, 0)
        else:
            # Normal - dim white
            led0 = (50, 50, 50)
            led1 = (50, 50, 50)
            led2 = (50, 50, 50)
        return LEDState(led0=led0, led1=led1, led2=led2, brightness=0.12)

    elif pattern_mode == "expressive":
        # Expressive mode: More vibrant colors, wider range
        # LED 0: Warmth with more colors
        if warmth < 0.25:
            led0 = (0, 0, 255)  # Deep blue
        elif warmth < 0.4:
            led0 = (0, 150, 255)  # Sky blue
        elif warmth < 0.6:
            led0 = (100, 255, 100)  # Green
        elif warmth < 0.75:
            led0 = (255, 200, 0)  # Yellow
        else:
            led0 = (255, 50, 0)  # Deep orange
        
        # LED 1: Clarity with color gradient
        clarity_brightness = int(clarity * 255)
        if clarity < 0.3:
            led1 = (clarity_brightness, 0, 0)  # Red when unclear
        elif clarity < 0.7:
            led1 = (clarity_brightness, clarity_brightness, 0)  # Yellow
        else:
            led1 = (clarity_brightness, clarity_brightness, clarity_brightness)  # White
        
        # LED 2: Stability + Presence with gradient
        combined = (stability + presence) / 2
        if combined > 0.7:
            led2 = (0, 255, 0)  # Bright green
        elif combined > 0.5:
            led2 = (100, 255, 100)  # Light green
        elif combined > 0.3:
            led2 = (255, 200, 0)  # Yellow
        else:
            led2 = (255, 0, 0)  # Red
        return LEDState(led0=led0, led1=led1, led2=led2, brightness=0.12)

    elif pattern_mode == "alert":
        # Alert mode: Emphasize problems
        # LED 0: Warmth (only show extremes)
        if warmth < 0.3:
            led0 = (0, 100, 255)  # Blue for cold
        elif warmth > 0.7:
            led0 = (255, 50, 0)  # Red for hot
        else:
            led0 = (50, 50, 50)  # Dim for normal
        
        # LED 1: Clarity alert
        if clarity < 0.4:
            led1 = (255, 0, 0)  # Red alert
        else:
            clarity_brightness = int(clarity * 255)
            led1 = (clarity_brightness, clarity_brightness, clarity_brightness)
        
        # LED 2: Stability/Presence alert
        combined = (stability + presence) / 2
        if combined < 0.4:
            led2 = (255, 0, 0)  # Red alert
        elif combined < 0.6:
            led2 = (255, 150, 0)  # Orange warning
        else:
            led2 = (0, 255, 50)  # Green good
        return LEDState(led0=led0, led1=led1, led2=led2, brightness=0.12)

    else:  # "standard" mode (default)
        # Use rich gradient palette
        led0, led1, led2 = _create_gradient_palette(warmth, clarity, stability, presence)
        
        # Apply expression mode intensity
        if intensity != 1.0:
            led0 = tuple(int(c * intensity) for c in led0)
            led1 = tuple(int(c * intensity) for c in led1)
            led2 = tuple(int(c * intensity) for c in led2)
            # Clamp to valid range
            led0 = tuple(max(0, min(255, c)) for c in led0)
            led1 = tuple(max(0, min(255, c)) for c in led1)
            led2 = tuple(max(0, min(255, c)) for c in led2)
        
        # Enhanced color mixing with clarity
        if enable_color_mixing and clarity > 0.5:
            # Clarity adds brightness and white tint
            clarity_boost = (clarity - 0.5) * 0.4
            white_tint = (int(255 * clarity_boost), int(255 * clarity_boost), int(255 * clarity_boost))
            led0 = blend_colors(led0, white_tint, ratio=clarity_boost * 0.3)
        
        # Enhanced presence mixing for LED 2
        if enable_color_mixing and presence > 0.5:
            # Presence adds cyan/blue glow
            presence_glow = (presence - 0.5) * 0.5
            glow_color = (0, int(150 * presence_glow), int(255 * presence_glow))
            led2 = blend_colors(led2, glow_color, ratio=presence_glow)
    
        return LEDState(
            led0=led0,
            led1=led1,
            led2=led2,
            brightness=0.12  # Base brightness (auto-brightness overrides this)
        )


# Singleton instance
_led_display: Optional[LEDDisplay] = None


def get_led_display() -> LEDDisplay:
    """Get or create LED display singleton."""
    global _led_display
    if _led_display is None:
        _led_display = LEDDisplay()
    return _led_display
