"""
LED Display - Maps anima state to BrainCraft HAT's 3 DotStar LEDs.

3 LEDs for 4 metrics:
Physical order on BrainCraft HAT (DotStar array indices):
- LED 0 (right): Stability/Presence blend - unstable=red flicker, stable+present=green
- LED 1 (center): Clarity - dim=off, clear=bright white
- LED 2 (left): Warmth - cold=blue, warm=orange

Note: DotStar array index 0 is physically rightmost, index 2 is leftmost.

Brightness indicates intensity. Color indicates quality.
Subtle breathing animation shows the system is alive.
"""

import sys
import time
import math
from dataclasses import dataclass
from typing import Tuple, Optional, Any

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
    brightness: float = 0.15  # Global brightness (0-1) - lower default to prevent self-illumination


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
        except ImportError:
            # Fallback if config not available
            self._base_brightness = brightness if brightness is not None else 0.15  # Lower default - LEDs are bright
            self._enable_breathing = enable_breathing if enable_breathing is not None else True
            self._pulsing_enabled = True
            self._color_transitions_enabled = True
            self._pattern_mode = "standard"
            self._auto_brightness_enabled = True
            self._auto_brightness_min = 0.05  # Lower minimum - LEDs are very bright
            self._auto_brightness_max = 0.15  # Much lower max - prevent self-illumination feedback loop
            self._pulsing_threshold_clarity = 0.4
            self._pulsing_threshold_stability = 0.4
        
        self._dots = None
        self._brightness = self._base_brightness
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
        self._cached_state_change_threshold = 0.05  # Only recalculate if change > 5%
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
                self._dots.brightness = 0.1  # Minimum brightness
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
    
    def _get_breathing_brightness(self) -> float:
        """Calculate breathing brightness (subtle sine wave)."""
        if not self._enable_breathing:
            return self._base_brightness
        
        # Slow breathing: 8 second cycle, ±10% variation
        t = time.time()
        breath = math.sin(t * math.pi / 4) * 0.1  # ±0.1 over 8 seconds
        return max(0.1, min(0.5, self._base_brightness + breath))
    
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
        
        Args:
            pattern_name: Name of pattern to show
            base_state: Base LED state
        
        Returns:
            Modified LED state with pattern colors
        """
        import time
        now = time.time()
        
        if self._pattern_active != pattern_name:
            self._pattern_active = pattern_name
            self._pattern_start_time = now
        
        elapsed = now - self._pattern_start_time
        
        if pattern_name == "warmth_spike":
            # Orange flash (0.3s)
            if elapsed < 0.3:
                return LEDState(
                    led0=(255, 150, 0),
                    led1=base_state.led1,
                    led2=base_state.led2,
                    brightness=0.5
                )
        elif pattern_name == "clarity_boost":
            # White flash (0.2s)
            if elapsed < 0.2:
                return LEDState(
                    led0=base_state.led0,
                    led1=(255, 255, 255),
                    led2=base_state.led2,
                    brightness=0.6
                )
        elif pattern_name == "stability_warning":
            # Red flash (0.4s)
            if elapsed < 0.4:
                return LEDState(
                    led0=base_state.led0,
                    led1=base_state.led1,
                    led2=(255, 0, 0),
                    brightness=0.5
                )
        elif pattern_name == "alert":
            # Yellow pulse (ongoing)
            pulse = (math.sin(elapsed * math.pi * 4) + 1) / 2  # 2 Hz
            return LEDState(
                led0=(255, int(200 * pulse), 0),
                led1=(255, int(200 * pulse), 0),
                led2=(255, int(200 * pulse), 0),
                brightness=0.4 + (0.2 * pulse)
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
        
        IMPORTANT: LEDs can illuminate themselves, creating a feedback loop.
        We compensate by using lower brightness ranges and being conservative.
        
        Args:
            light_level: Light level in lux (None to disable)
        
        Returns:
            Adjusted brightness (0-1)
        """
        if not self._auto_brightness_enabled or light_level is None:
            return self._base_brightness
        
        self._last_light_level = light_level
        
        # Map light level to brightness
        # Dark (< 10 lux): brighter (max)
        # Bright (> 1000 lux): dimmer (min)
        # Logarithmic mapping for better feel
        
        # COMPENSATION: If LEDs are currently bright, they might be contributing to lux reading
        # Use more conservative brightness to avoid self-illumination feedback loop
        # LEDs provide their own "clarity" (lux) - we need to account for this
        
        if light_level < 10:
            brightness = self._auto_brightness_max
        elif light_level > 1000:
            brightness = self._auto_brightness_min
        else:
            # Logarithmic interpolation
            log_min = math.log10(10)
            log_max = math.log10(1000)
            log_current = math.log10(max(10, min(1000, light_level)))
            ratio = (log_current - log_min) / (log_max - log_min)
            brightness = self._auto_brightness_max - (ratio * (self._auto_brightness_max - self._auto_brightness_min))
        
        # Additional safety: Cap brightness lower if we suspect self-illumination
        # If brightness is high and light level is moderate, LEDs might be contributing
        # Be more conservative to break feedback loop
        if brightness > self._base_brightness * 1.5 and 50 < light_level < 500:
            # Suspect self-illumination - reduce brightness more aggressively
            brightness = brightness * 0.7
        
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
        
        # Skip if state hasn't changed (performance optimization)
        if self._last_state and self._last_state == state:
            return
        
        from ..error_recovery import safe_call
        
        def set_leds():
            # LED order: 0=right, 1=center, 2=left (physical order on BrainCraft HAT)
            self._dots[0] = state.led2  # Right: Stability/Presence
            self._dots[1] = state.led1  # Center: Clarity
            self._dots[2] = state.led0  # Left: Warmth
            
            # Apply brightness (state.brightness already includes auto-adjust and pulsing)
            # Then apply breathing on top if enabled
            if self._enable_breathing:
                breathing_brightness = self._get_breathing_brightness()
                # Breathing modulates the base brightness
                # Protect against division by zero or invalid base_brightness
                if self._base_brightness > 0:
                    final_brightness = state.brightness * (breathing_brightness / self._base_brightness)
                else:
                    final_brightness = state.brightness  # Fallback if base_brightness is 0
                # Ensure minimum brightness - LEDs should never go completely off
                self._dots.brightness = max(0.1, min(0.5, final_brightness))
            else:
                # Ensure minimum brightness even without breathing
                # Protect against state.brightness being 0 or negative
                safe_brightness = max(0.1, min(0.5, max(0.0, state.brightness)))
                self._dots.brightness = safe_brightness
            
            # CRITICAL: Always call show() to update LEDs
            # If show() fails, LEDs will stay in previous state (not turn off)
            # Note: show() can block on SPI communication - we rely on safe_call timeout
            self._dots.show()
        
        # Fast path: no retries, just try once
        # LEDs don't need retries - if hardware works, it works; if not, retries won't help
        # Use safe_call to catch exceptions but don't retry (prevents blocking)
        start_time = time.time()
        success = safe_call(
            set_leds,
            default=False,
            log_error=False  # Don't log every failure - too noisy
        )
        elapsed = time.time() - start_time
        
        # Warn if LED update takes too long (indicates SPI bottleneck)
        if elapsed > 0.5 and self._update_count % 20 == 0:  # Log every 20th slow update
            print(f"[LEDs] Slow update: {elapsed*1000:.1f}ms (SPI bottleneck?)", file=sys.stderr, flush=True)
        
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
                          face_state: Optional[Any] = None,
                          expression_mode: str = "balanced") -> LEDState:
        """
        Update LEDs based on anima state with enhanced features.
        
        Args:
            warmth: 0-1, thermal/energy state
            clarity: 0-1, sensory clarity
            stability: 0-1, environmental order
            presence: 0-1, resource availability
            light_level: Optional light level in lux for auto-brightness
            face_state: DEPRECATED - LEDs are now independent from face expression
            expression_mode: "subtle", "balanced", "expressive", or "dramatic"
            
        Returns:
            LEDState that was applied
        """
        import time
        update_start_time = time.time()
        
        # Optimization: Check if state has changed significantly
        # Skip expensive calculations if anima state is essentially unchanged
        state_changed = True
        if self._cached_anima_state is not None:
            last_w, last_c, last_s, last_p = self._cached_anima_state
            max_delta = max(
                abs(warmth - last_w),
                abs(clarity - last_c),
                abs(stability - last_s),
                abs(presence - last_p)
            )
            # Also check light level change
            light_changed = (light_level is not None and 
                            self._cached_light_level is not None and
                            abs(light_level - self._cached_light_level) > 50)  # 50 lux threshold
            
            if max_delta < self._cached_state_change_threshold and not light_changed:
                # State essentially unchanged - skip most calculations, just apply breathing
                state_changed = False
                if self._last_state and self._dots:  # Only cache if LEDs are available
                    # Apply minimal updates: breathing animation only
                    if self._enable_breathing:
                        breathing_brightness = self._get_breathing_brightness()
                        self._dots.brightness = max(0.1, min(0.5, breathing_brightness))
                        self._dots.show()
                    return self._last_state
                # If no LEDs or no last state, fall through to full update
        
        # State changed significantly - perform full update
        self._cached_anima_state = (warmth, clarity, stability, presence)
        self._cached_light_level = light_level
        
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
        if self._color_transitions_enabled and self._last_state and self._last_colors[0] is not None:
            # Smoother transitions for gradual changes, faster for state changes
            if state_change_detected:
                transition_factor = 0.5  # Faster transition for state changes
            else:
                transition_factor = 0.2  # Very smooth for gradual changes
            
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
        # 5. Breathing (always-on subtle animation)
        
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
        
        # 3. Apply state-change pulse effect (highest priority - brief brightness boost)
        if self._state_change_pulse_active and self._state_change_pulse_start is not None:
            pulse_duration = 1.0  # Pulse for 1 second
            elapsed = time.time() - self._state_change_pulse_start
            if elapsed < pulse_duration:
                # Pulse: brighten then fade back
                pulse_factor = 1.0 + (0.3 * (1.0 - (elapsed / pulse_duration)))
                state.brightness *= pulse_factor
            else:
                self._state_change_pulse_active = False
                self._state_change_pulse_start = None
        
        # 4. Apply wave patterns (disabled by default - too complex, conflicts with breathing)
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
            feature_str = f" [{', '.join(features)}]" if features else ""
            
            print(f"[LEDs] Update #{self._update_count} ({update_duration*1000:.1f}ms): w={warmth:.2f} c={clarity:.2f} s={stability:.2f} p={presence:.2f}{feature_str}", 
                  file=sys.stderr, flush=True)
            print(f"[LEDs] Colors: {state.led0} {state.led1} {state.led2} @ {state.brightness:.2f}",
                  file=sys.stderr, flush=True)
        
        return state
    
    def get_diagnostics(self) -> dict:
        """Get diagnostic info about LED state."""
        return {
            "available": self.is_available(),
            "has_dotstar": HAS_DOTSTAR,
            "update_count": self._update_count,
            "base_brightness": self._base_brightness,
            "current_brightness": self._get_breathing_brightness() if self._enable_breathing else self._base_brightness,
            "breathing_enabled": self._enable_breathing,
            "pulsing_enabled": self._pulsing_enabled,
            "color_transitions_enabled": self._color_transitions_enabled,
            "pattern_mode": self._pattern_mode,
            "auto_brightness_enabled": self._auto_brightness_enabled,
            "last_light_level": self._last_light_level,
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
    Create rich gradient color palette based on all state metrics.
    
    Returns:
        Tuple of (led0, led1, led2) colors with rich gradients
    """
    # LED 0: Warmth gradient (cold to hot spectrum)
    if warmth < 0.2:
        led0 = (0, 50, 200)  # Deep blue
    elif warmth < 0.4:
        ratio = (warmth - 0.2) / 0.2
        led0 = _interpolate_color((0, 50, 200), (0, 150, 255), ratio)  # Blue to cyan
    elif warmth < 0.6:
        ratio = (warmth - 0.4) / 0.2
        led0 = _interpolate_color((0, 150, 255), (100, 255, 150), ratio)  # Cyan to green
    elif warmth < 0.8:
        ratio = (warmth - 0.6) / 0.2
        led0 = _interpolate_color((100, 255, 150), (255, 220, 100), ratio)  # Green to yellow
    else:
        ratio = (warmth - 0.8) / 0.2
        led0 = _interpolate_color((255, 220, 100), (255, 100, 0), ratio)  # Yellow to orange-red
    
    # LED 1: Clarity gradient (dim to bright, with color shifts)
    clarity_brightness = int(clarity * 255)
    if clarity < 0.3:
        # Low clarity: red-orange warning
        led1 = (clarity_brightness, int(clarity_brightness * 0.3), 0)
    elif clarity < 0.5:
        # Medium-low: yellow-orange
        ratio = (clarity - 0.3) / 0.2
        led1 = _interpolate_color((clarity_brightness, int(clarity_brightness * 0.3), 0),
                                  (clarity_brightness, clarity_brightness, 0), ratio)
    elif clarity < 0.7:
        # Medium: yellow-white
        ratio = (clarity - 0.5) / 0.2
        led1 = _interpolate_color((clarity_brightness, clarity_brightness, 0),
                                  (clarity_brightness, clarity_brightness, int(clarity_brightness * 0.5)), ratio)
    else:
        # High clarity: bright white with blue tint
        ratio = (clarity - 0.7) / 0.3
        led1 = _interpolate_color((clarity_brightness, clarity_brightness, int(clarity_brightness * 0.5)),
                                  (clarity_brightness, clarity_brightness, clarity_brightness), ratio)
    
    # LED 2: Stability + Presence gradient (red to green spectrum)
    combined = (stability + presence) / 2
    if combined < 0.3:
        # Low: red-orange warning
        led2 = (255, int(combined * 255 * 0.5), 0)
    elif combined < 0.5:
        # Medium-low: orange-yellow
        ratio = (combined - 0.3) / 0.2
        led2 = _interpolate_color((255, int(0.3 * 255 * 0.5), 0),
                                  (255, 200, 0), ratio)
    elif combined < 0.7:
        # Medium: yellow-green
        ratio = (combined - 0.5) / 0.2
        led2 = _interpolate_color((255, 200, 0),
                                  (150, 255, 50), ratio)
    else:
        # High: green-cyan
        ratio = (combined - 0.7) / 0.3
        led2 = _interpolate_color((150, 255, 50),
                                  (0, 255, 200), ratio)
    
    # Add presence blue tint to LED 2
    if presence > 0.6:
        presence_tint = (presence - 0.6) * 0.4
        led2 = blend_colors(led2, (0, 100, 255), ratio=presence_tint)
    
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
            brightness=0.15  # Base brightness (will be adjusted) - lower to prevent self-illumination
        )


# Singleton instance
_led_display: Optional[LEDDisplay] = None


def get_led_display() -> LEDDisplay:
    """Get or create LED display singleton."""
    global _led_display
    if _led_display is None:
        _led_display = LEDDisplay()
    return _led_display
