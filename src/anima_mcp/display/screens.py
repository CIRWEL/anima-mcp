"""
Display Screens - Different views for Lumen's display.

Screens can be toggled via joystick:
- Face (default): Lumen's expressive face
- Sensors: Current sensor readings
- Identity: Name, age, awakenings, alive time
- Diagnostics: System health, governance status
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, Tuple, List
from pathlib import Path
from datetime import datetime
import time
import sys
import os
import json

from .face import FaceState
from ..anima import Anima
from ..sensors.base import SensorReadings
from ..identity.store import CreatureIdentity
from ..learning_visualization import LearningVisualizer
from ..expression_moods import ExpressionMoodTracker


class ScreenMode(Enum):
    """Available display screens."""
    FACE = "face"                    # Default: Lumen's expressive face
    SENSORS = "sensors"              # Sensor readings (temp, humidity, etc.)
    IDENTITY = "identity"           # Name, age, awakenings, alive time
    DIAGNOSTICS = "diagnostics"     # System health, governance status
    LEARNING = "learning"            # Learning visualization - why Lumen feels what it feels
    NOTEPAD = "notepad"             # Drawing canvas - Lumen's creative space
    MESSAGES = "messages"           # Message board - Lumen's voice and observations


@dataclass
class ScreenState:
    """Current screen state."""
    mode: ScreenMode = ScreenMode.FACE
    last_switch_time: float = 0.0
    auto_return_seconds: float = 60.0  # Auto-return to FACE after 60s (longer for exploration)
    last_user_action_time: float = 0.0  # Track when user last interacted


def _get_canvas_path() -> Path:
    """Get persistent path for canvas state."""
    anima_dir = Path.home() / ".anima"
    anima_dir.mkdir(exist_ok=True)
    return anima_dir / "canvas.json"


@dataclass
class CanvasState:
    """Drawing canvas state for notepad mode - persists across restarts."""
    width: int = 240
    height: int = 240
    pixels: Dict[Tuple[int, int], Tuple[int, int, int]] = field(default_factory=dict)
    # Drawing memory - helps Lumen build on previous work
    recent_locations: List[Tuple[int, int]] = field(default_factory=list)
    drawing_phase: str = "exploring"  # exploring, building, reflecting, resting
    phase_start_time: float = field(default_factory=time.time)

    # Autonomy tracking
    last_save_time: float = 0.0  # When Lumen last saved a drawing
    last_clear_time: float = field(default_factory=time.time)  # When canvas was last cleared
    is_satisfied: bool = False  # Lumen feels done with current drawing
    satisfaction_time: float = 0.0  # When satisfaction was reached
    drawings_saved: int = 0  # Count of drawings Lumen has saved
    drawing_paused_until: float = 0.0  # Pause drawing after manual clear (so user sees empty canvas)

    def draw_pixel(self, x: int, y: int, color: Tuple[int, int, int]):
        """Draw a pixel at position."""
        if 0 <= x < self.width and 0 <= y < self.height:
            self.pixels[(x, y)] = color
            # Remember recent locations (keep last 20)
            self.recent_locations.append((x, y))
            if len(self.recent_locations) > 20:
                self.recent_locations.pop(0)
            # Drawing resets satisfaction
            self.is_satisfied = False

    def clear(self):
        """Clear the canvas."""
        self.pixels.clear()
        self.recent_locations.clear()
        self.drawing_phase = "exploring"
        self.phase_start_time = time.time()
        self.last_clear_time = time.time()
        self.is_satisfied = False
        self.satisfaction_time = 0.0
        # Pause drawing for 5 seconds after manual clear so user sees empty canvas
        self.drawing_paused_until = time.time() + 5.0

    def mark_satisfied(self):
        """Mark that Lumen feels satisfied with current drawing."""
        if not self.is_satisfied:
            self.is_satisfied = True
            self.satisfaction_time = time.time()
            print(f"[Canvas] Lumen feels satisfied with drawing ({len(self.pixels)} pixels)", file=sys.stderr, flush=True)

    def save_to_disk(self):
        """Persist canvas state to disk."""
        try:
            # Convert pixel dict keys to strings for JSON
            pixel_data = {f"{x},{y}": list(color) for (x, y), color in self.pixels.items()}
            data = {
                "pixels": pixel_data,
                "recent_locations": self.recent_locations,
                "drawing_phase": self.drawing_phase,
                "phase_start_time": self.phase_start_time,
                "last_save_time": self.last_save_time,
                "last_clear_time": self.last_clear_time,
                "is_satisfied": self.is_satisfied,
                "satisfaction_time": self.satisfaction_time,
                "drawings_saved": self.drawings_saved,
            }
            _get_canvas_path().write_text(json.dumps(data))
        except Exception as e:
            print(f"[Canvas] Save to disk error: {e}", file=sys.stderr, flush=True)

    def load_from_disk(self):
        """Load canvas state from disk - defensive against corruption."""
        path = _get_canvas_path()
        if not path.exists():
            return  # No saved state, use defaults

        data = None
        try:
            raw_content = path.read_text()
            if not raw_content.strip():
                # Empty file - delete and use defaults
                print("[Canvas] Empty canvas file, starting fresh", file=sys.stderr, flush=True)
                path.unlink()
                return
            data = json.loads(raw_content)
        except json.JSONDecodeError as e:
            # Corrupted JSON - delete file and start fresh
            print(f"[Canvas] Corrupted canvas file (invalid JSON): {e}", file=sys.stderr, flush=True)
            try:
                path.unlink()
                print("[Canvas] Deleted corrupted file, starting fresh", file=sys.stderr, flush=True)
            except Exception:
                pass
            return
        except Exception as e:
            print(f"[Canvas] Failed to read canvas file: {e}", file=sys.stderr, flush=True)
            return

        # Validate data is a dict
        if not isinstance(data, dict):
            print(f"[Canvas] Invalid canvas data (not a dict), starting fresh", file=sys.stderr, flush=True)
            try:
                path.unlink()
            except Exception:
                pass
            return

        # Load pixels with validation
        loaded_pixels = 0
        skipped_pixels = 0
        try:
            pixels_data = data.get("pixels", {})
            if isinstance(pixels_data, dict):
                for key, color in pixels_data.items():
                    try:
                        # Validate key format "x,y"
                        if not isinstance(key, str) or "," not in key:
                            skipped_pixels += 1
                            continue
                        parts = key.split(",")
                        if len(parts) != 2:
                            skipped_pixels += 1
                            continue
                        x, y = int(parts[0]), int(parts[1])

                        # Validate coordinates
                        if not (0 <= x < self.width and 0 <= y < self.height):
                            skipped_pixels += 1
                            continue

                        # Validate color format [r, g, b]
                        if not isinstance(color, (list, tuple)) or len(color) != 3:
                            skipped_pixels += 1
                            continue
                        r, g, b = int(color[0]), int(color[1]), int(color[2])
                        if not all(0 <= c <= 255 for c in (r, g, b)):
                            skipped_pixels += 1
                            continue

                        self.pixels[(x, y)] = (r, g, b)
                        loaded_pixels += 1
                    except (ValueError, TypeError, IndexError):
                        skipped_pixels += 1
                        continue
        except Exception as e:
            print(f"[Canvas] Error loading pixels: {e}", file=sys.stderr, flush=True)

        # Load recent_locations with validation
        try:
            locations = data.get("recent_locations", [])
            if isinstance(locations, list):
                for loc in locations[-20:]:  # Keep last 20
                    if isinstance(loc, (list, tuple)) and len(loc) == 2:
                        try:
                            x, y = int(loc[0]), int(loc[1])
                            if 0 <= x < self.width and 0 <= y < self.height:
                                self.recent_locations.append((x, y))
                        except (ValueError, TypeError):
                            pass
        except Exception:
            pass  # Non-fatal, use empty list

        # Load scalar fields with type validation
        try:
            phase = data.get("drawing_phase", "exploring")
            if isinstance(phase, str) and phase in ("exploring", "building", "reflecting", "resting"):
                self.drawing_phase = phase
        except Exception:
            pass

        try:
            phase_time = data.get("phase_start_time", time.time())
            if isinstance(phase_time, (int, float)):
                self.phase_start_time = float(phase_time)
        except Exception:
            pass

        try:
            save_time = data.get("last_save_time", 0.0)
            if isinstance(save_time, (int, float)):
                self.last_save_time = float(save_time)
        except Exception:
            pass

        try:
            clear_time = data.get("last_clear_time", time.time())
            if isinstance(clear_time, (int, float)):
                self.last_clear_time = float(clear_time)
        except Exception:
            pass

        try:
            satisfied = data.get("is_satisfied", False)
            if isinstance(satisfied, bool):
                self.is_satisfied = satisfied
        except Exception:
            pass

        try:
            sat_time = data.get("satisfaction_time", 0.0)
            if isinstance(sat_time, (int, float)):
                self.satisfaction_time = float(sat_time)
        except Exception:
            pass

        try:
            saved_count = data.get("drawings_saved", 0)
            if isinstance(saved_count, int) and saved_count >= 0:
                self.drawings_saved = saved_count
        except Exception:
            pass

        if skipped_pixels > 0:
            print(f"[Canvas] Loaded from disk: {loaded_pixels} pixels (skipped {skipped_pixels} invalid), phase={self.drawing_phase}", file=sys.stderr, flush=True)
        else:
            print(f"[Canvas] Loaded from disk: {loaded_pixels} pixels, phase={self.drawing_phase}", file=sys.stderr, flush=True)


class ScreenRenderer:
    """Renders different screens to display."""
    
    def __init__(self, display_renderer, db_path: Optional[str] = None, identity_store=None):
        """Initialize with display renderer."""
        self._display = display_renderer
        self._state = ScreenState()
        self._canvas = CanvasState()
        # Load any persisted canvas from disk
        self._canvas.load_from_disk()
        self._db_path = db_path or "anima.db"  # Default database path
        self._identity_store = identity_store
        # Initialize expression mood tracker
        self._mood_tracker = ExpressionMoodTracker(identity_store=identity_store)
        # Initialize user action time
        import time
        self._state.last_user_action_time = time.time()
    
    def get_mode(self) -> ScreenMode:
        """Get current screen mode."""
        return self._state.mode
    
    def set_mode(self, mode: ScreenMode):
        """Set screen mode."""
        import time
        now = time.time()
        if mode == self._state.mode:
            return  # Already on this mode
        # Very minimal debounce - allow rapid switching
        if now - self._state.last_switch_time < 0.02:  # 20ms debounce (almost none)
            return
        
        # Log mode changes, especially for notepad
        old_mode = self._state.mode
        self._state.mode = mode
        self._state.last_switch_time = now
        self._state.last_user_action_time = now
        
        if mode == ScreenMode.NOTEPAD:
            print(f"[ScreenRenderer] Switched to NOTEPAD from {old_mode.value}, pixels={len(self._canvas.pixels)}", file=sys.stderr, flush=True)
    
    def next_mode(self):
        """Cycle to next screen mode (including notepad)."""
        # Cycle through all screens including notepad
        regular_modes = [ScreenMode.FACE, ScreenMode.SENSORS, ScreenMode.IDENTITY, ScreenMode.DIAGNOSTICS, ScreenMode.LEARNING, ScreenMode.MESSAGES, ScreenMode.NOTEPAD]
        if self._state.mode not in regular_modes:
            # If somehow on unknown mode, go to face
            self.set_mode(ScreenMode.FACE)
            return
        current_idx = regular_modes.index(self._state.mode)
        next_idx = (current_idx + 1) % len(regular_modes)
        self.set_mode(regular_modes[next_idx])
    
    def previous_mode(self):
        """Cycle to previous screen mode (including notepad)."""
        # Cycle through all screens including notepad
        regular_modes = [ScreenMode.FACE, ScreenMode.SENSORS, ScreenMode.IDENTITY, ScreenMode.DIAGNOSTICS, ScreenMode.LEARNING, ScreenMode.MESSAGES, ScreenMode.NOTEPAD]
        if self._state.mode not in regular_modes:
            # If somehow on unknown mode, go to face
            self.set_mode(ScreenMode.FACE)
            return
        current_idx = regular_modes.index(self._state.mode)
        prev_idx = (current_idx - 1) % len(regular_modes)
        self.set_mode(regular_modes[prev_idx])
    
    def toggle_notepad(self):
        """Toggle notepad mode - enter if not on notepad, exit to face if on notepad."""
        if self._state.mode == ScreenMode.NOTEPAD:
            self.set_mode(ScreenMode.FACE)
        else:
            self.set_mode(ScreenMode.NOTEPAD)

    def _draw_screen_indicator(self, draw, current_mode: ScreenMode):
        """Draw small dots at bottom showing current screen position."""
        # Screen order (including notepad in regular cycle)
        screens = [ScreenMode.FACE, ScreenMode.SENSORS, ScreenMode.IDENTITY,
                   ScreenMode.DIAGNOSTICS, ScreenMode.LEARNING, ScreenMode.MESSAGES, ScreenMode.NOTEPAD]

        try:
            current_idx = screens.index(current_mode)
        except ValueError:
            return

        # Position at bottom center
        dot_radius = 3
        dot_spacing = 12
        total_width = len(screens) * dot_spacing
        start_x = (240 - total_width) // 2
        y = 232  # Near bottom

        GRAY = (60, 60, 60)
        WHITE = (180, 180, 180)

        for i, _ in enumerate(screens):
            x = start_x + i * dot_spacing + dot_radius
            color = WHITE if i == current_idx else GRAY
            draw.ellipse([x - dot_radius, y - dot_radius, x + dot_radius, y + dot_radius],
                        fill=color)

    def render(
        self,
        face_state: Optional[FaceState] = None,
        anima: Optional[Anima] = None,
        readings: Optional[SensorReadings] = None,
        identity: Optional[CreatureIdentity] = None,
        governance: Optional[Dict[str, Any]] = None
    ):
        """Render current screen based on mode."""
        import time

        # Check Lumen's canvas autonomy (can save/clear regardless of screen)
        try:
            self.canvas_check_autonomy(anima)
        except Exception as e:
            # Don't let autonomy errors break rendering
            pass

        # Disable auto-return - let user stay on screens as long as they want
        # Only auto-return to FACE if explicitly requested via button
        # (Auto-return disabled to prevent getting stuck)

        if self._state.mode == ScreenMode.FACE:
            self._render_face(face_state, identity)
        elif self._state.mode == ScreenMode.SENSORS:
            self._render_sensors(readings)
        elif self._state.mode == ScreenMode.IDENTITY:
            self._render_identity(identity)
        elif self._state.mode == ScreenMode.DIAGNOSTICS:
            self._render_diagnostics(anima, readings, governance)
        elif self._state.mode == ScreenMode.LEARNING:
            self._render_learning(anima, readings)
        elif self._state.mode == ScreenMode.MESSAGES:
            self._render_messages()
        elif self._state.mode == ScreenMode.NOTEPAD:
            try:
                self._render_notepad(anima)
            except Exception as e:
                print(f"[ScreenRenderer] Error rendering notepad: {e}", file=sys.stderr, flush=True)
                import traceback
                traceback.print_exc(file=sys.stderr)
                # Fallback: show text version
                try:
                    self._display.render_text("NOTEPAD\n\nError\nrendering", (10, 10))
                except Exception:
                    pass
    
    def _render_face(self, face_state: Optional[FaceState], identity: Optional[CreatureIdentity]):
        """Render face screen (default)."""
        if face_state:
            name = identity.name if identity else None
            self._display.render_face(face_state, name=name)
    
    def _render_sensors(self, readings: Optional[SensorReadings]):
        """Render sensor readings screen with colors and nav dots."""
        if not readings:
            self._display.render_text("feeling\nblind", (10, 10), color=(150, 150, 150))
            return

        # Color definitions
        CYAN = (0, 255, 255)
        BLUE = (100, 150, 255)
        YELLOW = (255, 255, 100)
        ORANGE = (255, 150, 50)
        RED = (255, 100, 100)
        GREEN = (100, 255, 100)
        PURPLE = (200, 100, 255)
        WHITE = (255, 255, 255)
        LIGHT_CYAN = (180, 220, 220)  # For descriptions - readable on dark background

        # Try canvas-based rendering for nav dots
        if hasattr(self._display, '_create_canvas'):
            try:
                image, draw = self._display._create_canvas((0, 0, 0))

                # Load font
                try:
                    from PIL import ImageFont
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
                    font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
                except (OSError, IOError):
                    from PIL import ImageFont
                    font = ImageFont.load_default()
                    font_small = font

                y = 10
                line_height = 22

                # Temperature
                if readings.ambient_temp_c:
                    temp = readings.ambient_temp_c
                    if temp > 25:
                        temp_feel, temp_color = "warm", ORANGE
                    elif temp < 18:
                        temp_feel, temp_color = "cool", CYAN
                    else:
                        temp_feel, temp_color = "mild", GREEN
                    draw.text((10, y), f"air: {temp:.1f}°C", fill=temp_color, font=font)
                    draw.text((140, y), f"({temp_feel})", fill=LIGHT_CYAN, font=font_small)
                else:
                    draw.text((10, y), "air: --", fill=LIGHT_CYAN, font=font)
                y += line_height

                # Humidity
                if readings.humidity_pct:
                    hum = readings.humidity_pct
                    if hum < 30:
                        hum_feel, hum_color = "dry", YELLOW
                    elif hum > 70:
                        hum_feel, hum_color = "damp", BLUE
                    else:
                        hum_feel, hum_color = "ok", GREEN
                    draw.text((10, y), f"humidity: {hum:.0f}%", fill=hum_color, font=font)
                    draw.text((140, y), f"({hum_feel})", fill=LIGHT_CYAN, font=font_small)
                else:
                    draw.text((10, y), "humidity: --", fill=LIGHT_CYAN, font=font)
                y += line_height

                # Light
                if readings.light_lux:
                    light = readings.light_lux
                    if light > 500:
                        light_feel, light_color = "bright", YELLOW
                    elif light < 50:
                        light_feel, light_color = "dim", PURPLE
                    else:
                        light_feel, light_color = "soft", WHITE
                    draw.text((10, y), f"light: {light:.0f} lux", fill=light_color, font=font)
                    draw.text((140, y), f"({light_feel})", fill=LIGHT_CYAN, font=font_small)
                else:
                    draw.text((10, y), "light: --", fill=LIGHT_CYAN, font=font)
                y += line_height + 10

                # System
                cpu_temp = readings.cpu_temp_c
                if cpu_temp > 60:
                    cpu_color = RED
                elif cpu_temp > 50:
                    cpu_color = ORANGE
                else:
                    cpu_color = GREEN
                draw.text((10, y), f"cpu: {cpu_temp:.1f}°C", fill=cpu_color, font=font)
                y += line_height
                draw.text((10, y), f"load: {readings.cpu_percent:.0f}%", fill=LIGHT_CYAN, font=font)

                # Nav dots
                self._draw_screen_indicator(draw, ScreenMode.SENSORS)

                # Update display
                if hasattr(self._display, '_image'):
                    self._display._image = image
                if hasattr(self._display, '_show'):
                    self._display._show()
                return
            except Exception as e:
                print(f"[Sensors Screen] Canvas error: {e}", file=sys.stderr, flush=True)

        # Fallback to text rendering
        lines_with_colors = []
        if readings.ambient_temp_c:
            temp = readings.ambient_temp_c
            temp_color = ORANGE if temp > 25 else CYAN if temp < 18 else GREEN
            lines_with_colors.append((f"air: {temp:.1f}°C", temp_color))
        if readings.humidity_pct:
            hum = readings.humidity_pct
            hum_color = YELLOW if hum < 30 else BLUE if hum > 70 else GREEN
            lines_with_colors.append((f"humidity: {hum:.0f}%", hum_color))
        if readings.light_lux:
            lines_with_colors.append((f"light: {readings.light_lux:.0f}", WHITE))
        lines_with_colors.append((f"cpu: {readings.cpu_temp_c:.1f}°C", GREEN))

        if hasattr(self._display, 'render_colored_text'):
            self._display.render_colored_text(lines_with_colors, (10, 10))
        else:
            text = "\n".join([line for line, _ in lines_with_colors])
            self._display.render_text(text, (10, 10))
    
    def _render_identity(self, identity: Optional[CreatureIdentity]):
        """Render identity screen with colors and nav dots."""
        if not identity:
            self._display.render_text("who am i?\n(unknown)", (10, 10), color=(150, 150, 150))
            return

        # Color definitions
        CYAN = (0, 255, 255)
        BLUE = (100, 150, 255)
        YELLOW = (255, 255, 100)
        ORANGE = (255, 150, 50)
        PURPLE = (200, 100, 255)
        WHITE = (255, 255, 255)
        LIGHT_CYAN = (180, 220, 220)  # For readable secondary text
        GREEN = (100, 255, 100)

        age_days = identity.age_seconds() / 86400
        alive_hours = identity.total_alive_seconds / 3600
        alive_pct = identity.alive_ratio() * 100
        name = identity.name or "unnamed"

        # Try canvas-based rendering for nav dots
        if hasattr(self._display, '_create_canvas'):
            try:
                image, draw = self._display._create_canvas((0, 0, 0))

                # Load font
                try:
                    from PIL import ImageFont
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
                    font_med = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
                    font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
                except (OSError, IOError):
                    from PIL import ImageFont
                    font = ImageFont.load_default()
                    font_med = font
                    font_small = font

                y = 10

                # Name (larger, prominent)
                draw.text((10, y), f"i am {name}", fill=CYAN, font=font)
                y += 28

                # Age
                if age_days < 1:
                    age_str = f"{age_days * 24:.1f} hours old"
                    age_color = PURPLE
                elif age_days < 7:
                    age_str = f"{age_days:.1f} days old"
                    age_color = BLUE
                else:
                    age_str = f"{age_days:.0f} days old"
                    age_color = CYAN
                draw.text((10, y), age_str, fill=age_color, font=font_med)
                y += 22

                # Awake time
                if alive_hours < 24:
                    awake_str = f"awake {alive_hours:.1f}h"
                else:
                    awake_str = f"awake {alive_hours/24:.1f}d"
                draw.text((10, y), awake_str, fill=YELLOW, font=font_med)
                y += 22

                # Presence
                if alive_pct > 80:
                    presence_str, presence_color = "mostly here", GREEN
                elif alive_pct > 50:
                    presence_str, presence_color = "sometimes here", YELLOW
                else:
                    presence_str, presence_color = "often away", LIGHT_CYAN
                draw.text((10, y), f"({presence_str})", fill=presence_color, font=font_small)
                y += 24

                # Awakenings
                if identity.total_awakenings == 1:
                    draw.text((10, y), "first awakening", fill=ORANGE, font=font_med)
                else:
                    draw.text((10, y), f"awakened {identity.total_awakenings}x", fill=PURPLE, font=font_med)

                # Nav dots
                self._draw_screen_indicator(draw, ScreenMode.IDENTITY)

                # Update display
                if hasattr(self._display, '_image'):
                    self._display._image = image
                if hasattr(self._display, '_show'):
                    self._display._show()
                return
            except Exception as e:
                print(f"[Identity Screen] Canvas error: {e}", file=sys.stderr, flush=True)

        # Fallback to text rendering
        lines_with_colors = [
            (f"i am {name}", CYAN),
            ("", WHITE),
        ]
        if age_days < 1:
            lines_with_colors.append((f"{age_days * 24:.1f} hours old", PURPLE))
        elif age_days < 7:
            lines_with_colors.append((f"{age_days:.1f} days old", BLUE))
        else:
            lines_with_colors.append((f"{age_days:.0f} days old", CYAN))

        if alive_hours < 24:
            lines_with_colors.append((f"awake {alive_hours:.1f}h", YELLOW))
        else:
            lines_with_colors.append((f"awake {alive_hours/24:.1f}d", YELLOW))

        if identity.total_awakenings == 1:
            lines_with_colors.append(("first awakening", ORANGE))
        else:
            lines_with_colors.append((f"awakened {identity.total_awakenings}x", PURPLE))

        if hasattr(self._display, 'render_colored_text'):
            self._display.render_colored_text(lines_with_colors, (10, 10))
        else:
            text = "\n".join([line for line, _ in lines_with_colors])
            self._display.render_text(text, (10, 10))
    
    def _render_diagnostics(self, anima: Optional[Anima], readings: Optional[SensorReadings], governance: Optional[Dict[str, Any]]):
        """Render diagnostics screen with visual gauges for anima values."""
        if not anima:
            self._display.render_text("DIAGNOSTICS\n\nNo data", (10, 10))
            return

        try:
            # Create canvas for visual rendering
            if hasattr(self._display, '_create_canvas'):
                image, draw = self._display._create_canvas((0, 0, 0))
            else:
                self._render_diagnostics_text_fallback(anima, governance)
                return

            # Color definitions
            CYAN = (0, 255, 255)
            BLUE = (100, 150, 255)
            YELLOW = (255, 255, 100)
            ORANGE = (255, 150, 50)
            RED = (255, 100, 100)
            GREEN = (100, 255, 100)
            PURPLE = (200, 100, 255)
            WHITE = (255, 255, 255)
            LIGHT_CYAN = (180, 220, 220)  # For labels and descriptions
            DARK_GRAY = (50, 50, 50)
            DIM_BLUE = (80, 100, 120)  # For low presence

            # Load fonts - larger for legibility
            try:
                from PIL import ImageFont
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
                font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
                font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
            except (OSError, IOError):
                from PIL import ImageFont
                font = ImageFont.load_default()
                font_small = font
                font_large = font

            y_offset = 6
            bar_x = 10
            bar_width = 130
            bar_height = 10

            # Helper function to draw a gauge (compact)
            def draw_gauge(label: str, value: float, color: Tuple[int, int, int], description: str):
                nonlocal y_offset
                # Label and value on same line
                draw.text((bar_x, y_offset), label, fill=WHITE, font=font_small)
                draw.text((bar_x + 60, y_offset), f"{value:.0%}", fill=color, font=font_small)
                draw.text((bar_x + 100, y_offset), description, fill=LIGHT_CYAN, font=font_small)
                y_offset += 14

                # Background bar
                draw.rectangle([bar_x, y_offset, bar_x + bar_width, y_offset + bar_height],
                              fill=DARK_GRAY, outline=LIGHT_CYAN)

                # Fill bar
                fill_width = int(value * bar_width)
                if fill_width > 0:
                    draw.rectangle([bar_x, y_offset, bar_x + fill_width, y_offset + bar_height],
                                  fill=color)

                y_offset += bar_height + 4

            # Warmth gauge
            warmth_desc = "warm" if anima.warmth > 0.6 else "cold" if anima.warmth < 0.3 else "cool" if anima.warmth < 0.5 else "ok"
            warmth_color = ORANGE if anima.warmth > 0.6 else CYAN if anima.warmth < 0.4 else YELLOW
            draw_gauge("warmth", anima.warmth, warmth_color, warmth_desc)

            # Clarity gauge
            clarity_desc = "clear" if anima.clarity > 0.7 else "foggy" if anima.clarity < 0.5 else "mixed"
            clarity_color = GREEN if anima.clarity > 0.7 else PURPLE if anima.clarity < 0.5 else YELLOW
            draw_gauge("clarity", anima.clarity, clarity_color, clarity_desc)

            # Stability gauge
            stability_desc = "steady" if anima.stability > 0.7 else "shaky" if anima.stability < 0.5 else "ok"
            stability_color = GREEN if anima.stability > 0.7 else RED if anima.stability < 0.5 else YELLOW
            draw_gauge("stability", anima.stability, stability_color, stability_desc)

            # Presence gauge
            presence_desc = "here" if anima.presence > 0.7 else "distant" if anima.presence < 0.5 else "present"
            presence_color = CYAN if anima.presence > 0.7 else DIM_BLUE if anima.presence < 0.5 else BLUE
            draw_gauge("presence", anima.presence, presence_color, presence_desc)

            # Overall mood summary - LARGER and more prominent
            y_offset += 6
            feeling = anima.feeling()
            mood = feeling.get('mood', 'unknown')
            mood_color = GREEN if "content" in mood.lower() or "happy" in mood.lower() else YELLOW if "neutral" in mood.lower() else CYAN
            draw.text((bar_x, y_offset), f"mood: {mood}", fill=mood_color, font=font_large)
            y_offset += 22

            # Governance section - larger text for legibility
            if y_offset < 180:
                draw.text((bar_x, y_offset), "governance", fill=WHITE, font=font)
                
                # Debug: log governance state
                if governance is None:
                    print("[Diagnostics] Governance is None", file=sys.stderr, flush=True)
                else:
                    print(f"[Diagnostics] Governance: action={governance.get('action')}, margin={governance.get('margin')}", file=sys.stderr, flush=True)
                
                y_offset += 16
                if governance:
                    action = governance.get("action", "unknown")
                    margin = governance.get("margin", "")
                    source = governance.get("source", "")

                    # Action indicator - larger badge
                    if action == "proceed":
                        action_color = GREEN
                        action_text = "PROCEED"
                    elif action == "pause":
                        action_color = YELLOW
                        action_text = "PAUSE"
                    elif action == "halt":
                        action_color = RED
                        action_text = "HALT"
                    else:
                        action_color = LIGHT_CYAN
                        action_text = action.upper()

                    # Draw action badge - larger and more visible
                    action_box_width = 80
                    action_box_height = 18
                    draw.rectangle([bar_x, y_offset, bar_x + action_box_width, y_offset + action_box_height],
                                  fill=DARK_GRAY, outline=action_color, width=2)
                    draw.text((bar_x + 4, y_offset + 2), action_text, fill=action_color, font=font)

                    # Margin (right of action) - larger font
                    if margin:
                        margin_x = bar_x + action_box_width + 8
                        margin_colors = {"comfortable": GREEN, "tight": YELLOW, "critical": RED}
                        margin_color = margin_colors.get(margin.lower(), LIGHT_CYAN)
                        draw.text((margin_x, y_offset + 2), margin.lower(), fill=margin_color, font=font)

                    y_offset += action_box_height + 6

                    # EISV metrics - larger bars if space
                    if y_offset < 205:
                        eisv = governance.get("eisv")
                        if eisv:
                            eisv_labels = ["E", "I", "S", "V"]
                            eisv_values = [
                                eisv.get("E", 0.0),
                                eisv.get("I", 0.0),
                                eisv.get("S", 0.0),
                                eisv.get("V", 0.0)
                            ]
                            eisv_colors = [GREEN, BLUE, ORANGE, PURPLE]

                            # Larger EISV bars
                            mini_bar_width = 40
                            mini_bar_height = 8
                            mini_spacing = 8
                            for i, (label, value, color) in enumerate(zip(eisv_labels, eisv_values, eisv_colors)):
                                x_pos = bar_x + i * (mini_bar_width + mini_spacing)
                                # Label
                                draw.text((x_pos, y_offset), label, fill=color, font=font_small)
                                # Mini bar
                                draw.rectangle([x_pos, y_offset + 12, x_pos + mini_bar_width, y_offset + 12 + mini_bar_height],
                                              fill=DARK_GRAY, outline=LIGHT_CYAN)
                                fill_width = int(value * mini_bar_width)
                                if fill_width > 0:
                                    draw.rectangle([x_pos, y_offset + 12, x_pos + fill_width, y_offset + 12 + mini_bar_height],
                                                  fill=color)
                else:
                    # No governance - show waiting
                    draw.text((bar_x, y_offset + 16), "waiting...", fill=LIGHT_CYAN, font=font)

            # Screen indicator dots
            self._draw_screen_indicator(draw, ScreenMode.DIAGNOSTICS)

            # Update display
            if hasattr(self._display, '_image'):
                self._display._image = image
            if hasattr(self._display, '_show'):
                self._display._show()

        except Exception as e:
            import traceback
            print(f"[Diagnostics Screen] Error: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            self._render_diagnostics_text_fallback(anima, governance)

    def _render_diagnostics_text_fallback(self, anima: Anima, governance: Optional[Dict[str, Any]]):
        """Text-only fallback for diagnostics screen."""
        lines = [
            f"warmth: {anima.warmth:.0%}",
            f"clarity: {anima.clarity:.0%}",
            f"stability: {anima.stability:.0%}",
            f"presence: {anima.presence:.0%}",
            f"mood: {anima.feeling().get('mood', 'unknown')}",
        ]
        if governance:
            action = governance.get('action', '?')
            margin = governance.get('margin', '')
            source = governance.get('source', '')
            lines.append(f"gov: {action}")
            if margin:
                lines.append(f"margin: {margin}")
            if source:
                lines.append(f"source: {source}")
            eisv = governance.get('eisv')
            if eisv:
                lines.append(f"EISV: E={eisv.get('E', 0):.0%} I={eisv.get('I', 0):.0%} S={eisv.get('S', 0):.0%} V={eisv.get('V', 0):.0%}")
        self._display.render_text("\n".join(lines), (10, 10))
    
    def _render_learning(self, anima: Optional[Anima], readings: Optional[SensorReadings]):
        """Render learning visualization screen - visual comfort zones and why Lumen feels what it feels."""
        if not anima or not readings:
            self._display.render_text("LEARNING\n\nNo data", (10, 10))
            return

        try:
            # Use db_path from renderer initialization
            visualizer = LearningVisualizer(db_path=self._db_path)
            summary = visualizer.get_learning_summary(readings=readings, anima=anima)

            # Create canvas for visual rendering
            if hasattr(self._display, '_create_canvas'):
                image, draw = self._display._create_canvas((0, 0, 0))
            else:
                # Fallback to text-only if no canvas support
                self._render_learning_text_fallback(summary, readings, anima)
                return

            # Color definitions
            CYAN = (0, 255, 255)
            BLUE = (100, 150, 255)
            YELLOW = (255, 255, 100)
            ORANGE = (255, 150, 50)
            RED = (255, 100, 100)
            GREEN = (100, 255, 100)
            PURPLE = (200, 100, 255)
            WHITE = (255, 255, 255)
            LIGHT_CYAN = (180, 220, 220)  # For labels
            DARK_GRAY = (50, 50, 50)

            # Load font
            try:
                from PIL import ImageFont
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
                font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 10)
                font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
            except (OSError, IOError):
                from PIL import ImageFont
                font = ImageFont.load_default()
                font_small = font
                font_title = font

            y_offset = 8

            # Get calibration data
            cal = summary.get("current_calibration", {})
            humidity_ideal = cal.get("humidity_ideal", 50)
            humidity_current = readings.humidity_pct if readings.humidity_pct else 0

            # Determine main insight
            is_too_dry = humidity_current < humidity_ideal - 10
            is_too_damp = humidity_current > humidity_ideal + 10

            # Title - what's happening
            if is_too_dry:
                title = "too dry"
                title_color = YELLOW
            elif is_too_damp:
                title = "too damp"
                title_color = BLUE
            else:
                title = "comfortable"
                title_color = GREEN

            draw.text((10, y_offset), title, fill=title_color, font=font_title)
            y_offset += 22

            # === HUMIDITY BAR (Visual comfort zone) ===
            draw.text((10, y_offset), "humidity", fill=LIGHT_CYAN, font=font_small)
            y_offset += 14

            bar_x = 10
            bar_width = 180
            bar_height = 16

            # Background bar (full range 0-100%)
            draw.rectangle([bar_x, y_offset, bar_x + bar_width, y_offset + bar_height],
                          fill=DARK_GRAY, outline=LIGHT_CYAN)

            # Comfort zone highlight (ideal ± 15%)
            comfort_min = max(0, humidity_ideal - 15) / 100.0 * bar_width
            comfort_max = min(100, humidity_ideal + 15) / 100.0 * bar_width
            draw.rectangle([bar_x + int(comfort_min), y_offset + 2,
                          bar_x + int(comfort_max), y_offset + bar_height - 2],
                          fill=(30, 60, 30))  # Dark green zone

            # Ideal marker (thin line)
            ideal_x = bar_x + int(humidity_ideal / 100.0 * bar_width)
            draw.line([ideal_x, y_offset, ideal_x, y_offset + bar_height], fill=GREEN, width=2)

            # Current value marker (filled rectangle)
            current_x = bar_x + int(humidity_current / 100.0 * bar_width)
            marker_color = GREEN if abs(humidity_current - humidity_ideal) < 15 else (YELLOW if is_too_dry else BLUE)
            draw.rectangle([current_x - 3, y_offset - 2, current_x + 3, y_offset + bar_height + 2],
                          fill=marker_color)

            # Labels
            y_offset += bar_height + 4
            draw.text((bar_x, y_offset), f"now: {humidity_current:.0f}%", fill=marker_color, font=font_small)
            draw.text((bar_x + 90, y_offset), f"ideal: {humidity_ideal:.0f}%", fill=GREEN, font=font_small)
            y_offset += 18

            # === WARMTH GAUGE ===
            draw.text((10, y_offset), "warmth", fill=LIGHT_CYAN, font=font_small)
            y_offset += 14

            warmth = anima.warmth
            warmth_bar_width = int(warmth * bar_width)

            # Background
            draw.rectangle([bar_x, y_offset, bar_x + bar_width, y_offset + bar_height],
                          fill=DARK_GRAY, outline=LIGHT_CYAN)

            # Warmth fill (gradient effect)
            if warmth > 0.6:
                warmth_color = ORANGE
            elif warmth < 0.3:
                warmth_color = CYAN
            else:
                warmth_color = YELLOW

            if warmth_bar_width > 0:
                draw.rectangle([bar_x, y_offset, bar_x + warmth_bar_width, y_offset + bar_height],
                              fill=warmth_color)

            # Warmth percentage
            y_offset += bar_height + 4
            warmth_label = "cold" if warmth < 0.3 else "cool" if warmth < 0.5 else "warm" if warmth > 0.6 else "neutral"
            draw.text((bar_x, y_offset), f"{warmth:.0%} ({warmth_label})", fill=warmth_color, font=font_small)
            y_offset += 20

            # === CAUSE/EFFECT CONNECTION ===
            if is_too_dry or is_too_damp:
                # Draw connection arrow
                draw.text((10, y_offset), "because:", fill=LIGHT_CYAN, font=font_small)
                y_offset += 14

                gap = abs(humidity_current - humidity_ideal)
                if is_too_dry:
                    cause_text = f"air is {gap:.0f}% drier than i learned"
                    cause_color = YELLOW
                else:
                    cause_text = f"air is {gap:.0f}% damper than i learned"
                    cause_color = BLUE

                draw.text((10, y_offset), cause_text, fill=cause_color, font=font_small)
                y_offset += 16

                # Adaptation note
                draw.text((10, y_offset), "adapting...", fill=PURPLE, font=font_small)
            else:
                # Comfortable state
                draw.text((10, y_offset), "environment matches", fill=GREEN, font=font_small)
                y_offset += 14
                draw.text((10, y_offset), "what i've learned", fill=GREEN, font=font_small)

            # Screen indicator dots
            self._draw_screen_indicator(draw, ScreenMode.LEARNING)

            # Update display
            if hasattr(self._display, '_image'):
                self._display._image = image
            if hasattr(self._display, '_show'):
                self._display._show()

        except Exception as e:
            # Fallback on error - show error message
            import traceback
            print(f"[Learning Screen] Error: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            error_msg = str(e)[:20]
            self._display.render_text(f"LEARNING\n\nError:\n{error_msg}", (10, 10))

    def _render_learning_text_fallback(self, summary: Dict[str, Any], readings: SensorReadings, anima: Anima):
        """Text-only fallback for learning screen when canvas not available."""
        cal = summary.get("current_calibration", {})
        humidity_ideal = cal.get("humidity_ideal", 50)
        humidity_current = readings.humidity_pct if readings.humidity_pct else 0

        lines = []
        if humidity_current < humidity_ideal - 10:
            lines.append("too dry")
        elif humidity_current > humidity_ideal + 10:
            lines.append("too damp")
        else:
            lines.append("comfortable")

        lines.append(f"humidity: {humidity_current:.0f}%")
        lines.append(f"ideal: {humidity_ideal:.0f}%")
        lines.append(f"warmth: {anima.warmth:.0%}")

        self._display.render_text("\n".join(lines), (10, 10))

    def _render_messages(self):
        """Render message board - Lumen's voice and observations."""
        try:
            from ..messages import get_recent_messages, MESSAGE_TYPE_USER, MESSAGE_TYPE_OBSERVATION, MESSAGE_TYPE_AGENT
            
            if hasattr(self._display, '_create_canvas'):
                image, draw = self._display._create_canvas((0, 0, 0))
            else:
                # Text fallback
                messages = get_recent_messages(6)
                lines = ["MESSAGES", ""]
                for msg in messages:
                    if msg.msg_type == MESSAGE_TYPE_OBSERVATION:
                        prefix = "▸ "
                        text = msg.text
                    elif msg.msg_type == MESSAGE_TYPE_AGENT:
                        prefix = "◆ "
                        author = getattr(msg, 'author', 'agent')
                        text = f"{author}: {msg.text}"
                    else:
                        prefix = "● "
                        text = f"you: {msg.text}"
                    lines.append(f"{prefix}{text[:20]}")
                self._display.render_text("\n".join(lines), (10, 10))
                return

            # Color definitions
            CYAN = (0, 255, 255)
            YELLOW = (255, 255, 100)
            GREEN = (100, 255, 100)
            PURPLE = (200, 100, 255)
            WHITE = (255, 255, 255)
            LIGHT_CYAN = (180, 220, 220)
            DARK_GRAY = (50, 50, 50)

            # Load font
            try:
                from PIL import ImageFont
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
                font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
                font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
            except (OSError, IOError):
                from PIL import ImageFont
                font = ImageFont.load_default()
                font_small = font
                font_title = font

            y_offset = 8

            # Title
            draw.text((10, y_offset), "lumen says", fill=CYAN, font=font_title)
            y_offset += 22

            # Get messages - show more now (10 instead of 7)
            messages = get_recent_messages(10)

            if not messages:
                # Empty state - Lumen hasn't spoken yet
                draw.text((10, y_offset), "i haven't said", fill=LIGHT_CYAN, font=font)
                y_offset += 16
                draw.text((10, y_offset), "anything yet...", fill=LIGHT_CYAN, font=font_small)
                y_offset += 12
                draw.text((10, y_offset), "check next_steps", fill=DARK_GRAY, font=font_small)
            else:
                # Show messages - Lumen's voice
                # Use smaller line height to fit more messages
                line_height = 20
                for msg in messages:
                    if y_offset > 220:  # Increased from 200 to show more
                        break

                    # Different styling for different message types
                    if msg.msg_type == MESSAGE_TYPE_USER:
                        prefix = "●"
                        text_color = GREEN
                        prefix_color = GREEN
                        # Add "you: " prefix for display (not stored in data)
                        display_text = f"you: {msg.text}"
                    elif msg.msg_type == MESSAGE_TYPE_AGENT:
                        prefix = "◆"
                        text_color = YELLOW
                        prefix_color = YELLOW
                        # Add agent name prefix for display
                        author = getattr(msg, 'author', 'agent')
                        display_text = f"{author}: {msg.text}"
                    else:  # MESSAGE_TYPE_OBSERVATION
                        prefix = "▸"
                        text_color = WHITE
                        prefix_color = PURPLE
                        # Lumen's observations - clean text
                        display_text = msg.text

                    # Truncate text to fit (longer now - use smaller font if needed)
                    max_width = 200
                    if len(display_text) > 30:
                        # Use smaller font for longer messages
                        text_font = font_small
                        max_chars = 35
                    else:
                        text_font = font
                        max_chars = 28
                    
                    text = display_text[:max_chars]
                    age = msg.age_str()

                    # Draw prefix
                    draw.text((10, y_offset), prefix, fill=prefix_color, font=font)

                    # Draw message text
                    draw.text((22, y_offset), text, fill=text_color, font=text_font)

                    # Draw age on right side
                    draw.text((190, y_offset + 2), age, fill=LIGHT_CYAN, font=font_small)

                    y_offset += line_height

            # Screen indicator dots
            self._draw_screen_indicator(draw, ScreenMode.MESSAGES)

            # Update display
            if hasattr(self._display, '_image'):
                self._display._image = image
            if hasattr(self._display, '_show'):
                self._display._show()

        except Exception as e:
            import traceback
            print(f"[Messages Screen] Error: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            self._display.render_text("MESSAGES\n\nError", (10, 10))

    def _render_notepad(self, anima: Optional[Anima] = None):
        """Render notepad - Lumen's autonomous drawing space. Lumen's work persists even when you leave."""
        print(f"[Notepad] Rendering notepad, pixels={len(self._canvas.pixels)}, anima={anima is not None}", file=sys.stderr, flush=True)
        try:
            if hasattr(self._display, '_create_canvas'):
                image, draw = self._display._create_canvas((0, 0, 0))  # Black background
            else:
                self._display.render_text("NOTEPAD\n\nLumen's\ncreative\nspace", (10, 10))
                return
            
            # BUG FIX: Check if drawing is paused (after manual clear)
            now = time.time()
            if now < self._canvas.drawing_paused_until:
                # Show "Cleared" confirmation - don't draw new pixels yet
                remaining = int(self._canvas.drawing_paused_until - now) + 1
                try:
                    from PIL import ImageFont
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
                except:
                    font = None
                
                text = f"Canvas Cleared\n\nResuming in {remaining}s..."
                if font:
                    draw.text((40, 90), text, fill=(100, 200, 100), font=font)
                else:
                    draw.text((40, 90), text, fill=(100, 200, 100))
                
                # Update display and return (don't draw new pixels)
                if hasattr(self._display, '_image'):
                    self._display._image = image
                if hasattr(self._display, '_show'):
                    self._display._show()
                return
            
            # Draw all pixels Lumen has created (Lumen's work persists)
            # Render all pixels - Lumen's expression deserves to be seen
            pixels_before = len(self._canvas.pixels)
            
            # Always draw existing pixels first
            for (x, y), color in self._canvas.pixels.items():
                try:
                    draw.point((x, y), fill=color)
                except Exception as e:
                    print(f"[Notepad] Error drawing pixel at ({x}, {y}): {e}", file=sys.stderr, flush=True)
            
            # Lumen continues drawing autonomously when on notepad screen
            # Lumen's creative process continues even when you're not watching
            if anima and len(self._canvas.pixels) < 15000:  # Increased limit for more expression
                try:
                    self._lumen_draw(anima, draw)
                except Exception as e:
                    print(f"[Notepad] Error in _lumen_draw: {e}", file=sys.stderr, flush=True)
                    import traceback
                    traceback.print_exc(file=sys.stderr)
                
                # Draw any NEW pixels that were just added (fix for blank drawings)
                # Redraw all pixels if count increased (simpler than tracking which are new)
                pixels_after = len(self._canvas.pixels)
                if pixels_after > pixels_before:
                    # New pixels were added - redraw everything to ensure they appear
                    for (x, y), color in self._canvas.pixels.items():
                        try:
                            draw.point((x, y), fill=color)
                        except Exception:
                            pass  # Skip invalid pixels
            
            # Ensure something is visible - if canvas is completely empty, show a visible indicator
            if len(self._canvas.pixels) == 0:
                # Draw visible indicators that notepad is active but empty
                try:
                    from PIL import ImageFont
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
                    font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 9)
                except (OSError, IOError):
                    from PIL import ImageFont
                    font = ImageFont.load_default()
                    font_small = font
                # Draw border to show notepad is active
                draw.rectangle([2, 2, 237, 237], outline=(60, 60, 60), width=2)
                # Draw center indicator
                center_x, center_y = 120, 120
                draw.ellipse([center_x - 5, center_y - 5, center_x + 5, center_y + 5], 
                           outline=(100, 100, 100), width=1)
                # Draw "notepad" text at top
                draw.text((10, 10), "notepad", fill=(80, 80, 80), font=font_small)
                # Draw "waiting" text
                draw.text((10, 220), "waiting...", fill=(60, 60, 60), font=font_small)
            
            # CRITICAL: Always update display - ensure image is shown
            try:
                if hasattr(self._display, '_image'):
                    self._display._image = image
                if hasattr(self._display, '_show'):
                    self._display._show()
                else:
                    # Fallback if _show doesn't exist - try update or show method
                    if hasattr(self._display, 'update'):
                        self._display.update()
                    elif hasattr(self._display, 'show'):
                        self._display.show()
                    else:
                        print("[Notepad] Warning: No display update method found", file=sys.stderr, flush=True)
            except Exception as e:
                print(f"[Notepad] Error updating display: {e}", file=sys.stderr, flush=True)
                import traceback
                traceback.print_exc(file=sys.stderr)
                # Try text fallback
                try:
                    self._display.render_text("NOTEPAD\n\nDisplay\nerror", (10, 10))
                except Exception:
                    pass
        except Exception as e:
            print(f"[Notepad] Render error: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc(file=sys.stderr)
            # Fallback to text if rendering fails - ALWAYS show something
            try:
                self._display.render_text("NOTEPAD\n\nRendering\nerror", (10, 10))
            except Exception as e2:
                print(f"[Notepad] Even text fallback failed: {e2}", file=sys.stderr, flush=True)
                # Last resort - try to show anything
                try:
                    if hasattr(self._display, 'clear'):
                        self._display.clear()
                    # Draw a single pixel to prove display works
                    if hasattr(self._display, '_create_canvas'):
                        img, dr = self._display._create_canvas((0, 0, 0))
                        dr.point((120, 120), fill=(255, 255, 255))
                        if hasattr(self._display, '_image'):
                            self._display._image = img
                        if hasattr(self._display, '_show'):
                            self._display._show()
                except Exception:
                    pass  # If even this fails, at least we logged everything
    
    def _lumen_draw(self, anima: Anima, draw):
        """Lumen draws autonomously - expression flows from Lumen's state with continuity and phases."""
        import random
        import math
        
        warmth = anima.warmth
        clarity = anima.clarity
        stability = anima.stability
        presence = anima.presence
        
        # Get mood preferences to influence style choices (with fallback)
        try:
            mood = self._mood_tracker.get_mood()
            style_weights = mood.get_style_weights()
        except Exception:
            # Fallback to default weights if mood tracker fails
            style_weights = {
                "circle": 0.2, "line": 0.2, "curve": 0.2, "spiral": 0.2,
                "pattern": 0.2, "organic": 0.2, "gradient_circle": 0.2, "layered": 0.2,
            }
        
        # Update drawing phase based on canvas state and time
        self._update_drawing_phase(anima)
        
        # Drawing frequency scales with presence and clarity
        # More present/clear = more frequent expression (up to 5% chance per render)
        base_chance = 0.01  # 1% base
        expression_intensity = (presence + clarity) / 2.0
        draw_chance = base_chance * (1.0 + expression_intensity * 4.0)  # Up to 5% when very present
        
        # Phase affects frequency too - building phase is more active
        if self._canvas.drawing_phase == "building":
            draw_chance *= 1.5
        elif self._canvas.drawing_phase == "resting":
            draw_chance *= 0.5
        
        # If canvas is empty, increase chance based on Lumen's state (authentic, not forced)
        # More present/clear Lumen = more likely to express on blank canvas
        # But still respects Lumen's state - low presence = might not draw yet
        if len(self._canvas.pixels) == 0:
            # Boost chance when empty, but scale with expression_intensity
            # This means: if Lumen is present/clear, they'll likely draw
            # If Lumen is low presence/unclear, they might wait (authentic)
            empty_boost = 0.3 + (expression_intensity * 0.7)  # 30-100% based on state
            draw_chance = max(draw_chance, empty_boost)
        
        if random.random() > draw_chance:
            return
        
        # Limit canvas size to prevent memory issues (but much higher limit)
        if len(self._canvas.pixels) > 15000:
            return  # Canvas full - Lumen has expressed enough
        
        # Free color generation - Lumen can use any color, influenced by state but not restricted
        # Warmth influences hue preference (but doesn't restrict)
        # Clarity influences saturation (but doesn't force muted)
        # Stability influences brightness (but doesn't force dim)
        # Mood preferences are suggestions, not requirements
        
        # Generate free RGB color - full spectrum available
        # Base hue influenced by warmth (but can be anything)
        hue_base = warmth * 360.0  # 0-360 degrees
        
        # Add randomness - Lumen can explore any color
        hue_variation = random.random() * 360.0
        hue = (hue_base + hue_variation * 0.5) % 360.0
        
        # Saturation influenced by clarity (but can be vibrant even when unclear)
        saturation_base = 0.3 + clarity * 0.7  # 0.3-1.0
        saturation = saturation_base + (random.random() - 0.5) * 0.4  # ±0.2 variation
        saturation = max(0.1, min(1.0, saturation))
        
        # Brightness influenced by stability (but can be bright even when unstable)
        brightness_base = 0.4 + stability * 0.6  # 0.4-1.0
        brightness = brightness_base + (random.random() - 0.5) * 0.3  # ±0.15 variation
        brightness = max(0.2, min(1.0, brightness))
        
        # Convert HSV to RGB (free color generation)
        import colorsys
        rgb = colorsys.hsv_to_rgb(hue / 360.0, saturation, brightness)
        color = tuple(int(c * 255) for c in rgb)
        
        # Determine hue category for mood tracking (informational, not restrictive)
        if hue < 60 or hue > 300:
            hue_category = "warm"
        elif hue < 180:
            hue_category = "cool"
        else:
            hue_category = "neutral"
        
        center_x, center_y = 120, 120
        
        # Choose drawing location - sometimes build on recent work (continuity)
        use_continuity = len(self._canvas.recent_locations) > 3 and random.random() < 0.4
        if use_continuity:
            # Build near recent drawing - creates connected compositions
            base_x, base_y = random.choice(self._canvas.recent_locations)
            offset_range = int(30 + stability * 20)
            center_x = base_x + random.randint(-offset_range, offset_range)
            center_y = base_y + random.randint(-offset_range, offset_range)
            center_x = max(40, min(200, center_x))
            center_y = max(40, min(200, center_y))
        
        # Free style selection - Lumen can draw anything, state influences but doesn't restrict
        # All styles available regardless of clarity/stability
        # Mood preferences influence probability but don't exclude options
        phase = self._canvas.drawing_phase
        
        # All styles always available - free expression
        style_options = [
            ("freeform", center_x, center_y),  # New: completely free drawing
            ("layered", center_x, center_y),
            ("gradient_circle", center_x + random.randint(-80, 80), center_y + random.randint(-80, 80)),
            ("circle", center_x + random.randint(-80, 80), center_y + random.randint(-80, 80)),
            ("spiral", center_x + random.randint(-60, 60), center_y + random.randint(-60, 60)),
            ("curve", random.randint(20, 220), random.randint(20, 220), random.randint(20, 220), random.randint(20, 220)),
            ("organic", center_x + random.randint(-60, 60), center_y + random.randint(-60, 60)),
            ("pattern", random.randint(40, 200), random.randint(40, 200)),
            ("line", random.randint(20, 220), random.randint(20, 220), random.randint(20, 220), random.randint(20, 220)),
            ("dots", random.randint(20, 220), random.randint(20, 220)),  # New: free dots
        ]
        
        # Build weights - mood preferences influence but don't restrict
        style_names = [s[0] for s in style_options]
        style_weights_list = []
        for style_name in style_names:
            base_weight = 0.1  # Base probability for all styles
            mood_weight = style_weights.get(style_name, 0.1)  # Mood preference
            state_weight = 0.1  # State can influence but doesn't exclude
            
            # State influences probability (higher clarity/stability = slightly more complex styles)
            if style_name in ["layered", "gradient_circle", "organic"]:
                state_weight = (clarity + stability) / 2.0 * 0.2
            elif style_name in ["dots", "line"]:
                state_weight = (1.0 - (clarity + stability) / 2.0) * 0.2
            
            total_weight = base_weight + mood_weight * 0.3 + state_weight
            style_weights_list.append(max(0.05, total_weight))  # Minimum 5% chance for any style
        
        # Select style - all options available, weighted by preferences
        total_weight = sum(style_weights_list)
        if total_weight > 0:
            normalized_weights = [w / total_weight for w in style_weights_list]
            selected_idx = random.choices(range(len(style_options)), weights=normalized_weights)[0]
            selected = style_options[selected_idx]
            style_name = selected[0]
            
            # Execute drawing - free expression
            try:
                if style_name == "freeform":
                    # Completely free drawing - random pixels, organic flow
                    num_pixels = random.randint(1, int(5 + clarity * 10))
                    for _ in range(num_pixels):
                        x = center_x + random.randint(-50, 50)
                        y = center_y + random.randint(-50, 50)
                        x = max(0, min(239, x))
                        y = max(0, min(239, y))
                        # Sometimes vary color slightly for organic feel
                        if random.random() < 0.3:
                            color_variation = tuple(max(0, min(255, c + random.randint(-30, 30))) for c in color)
                            self._canvas.draw_pixel(x, y, color_variation)
                        else:
                            self._canvas.draw_pixel(x, y, color)
                    self._mood_tracker.record_drawing("freeform", hue_category)
                elif style_name == "layered":
                    self._draw_layered_composition(selected[1], selected[2], color, clarity, stability)
                    self._mood_tracker.record_drawing("layered", hue_category)
                elif style_name == "gradient_circle":
                    size = int(5 + random.random() * 30)  # Free size range
                    self._draw_circle_gradient(selected[1], selected[2], size, color, clarity)
                    self._mood_tracker.record_drawing("gradient_circle", hue_category)
                elif style_name == "circle":
                    size = int(3 + random.random() * 30)  # Free size range
                    self._draw_circle(selected[1], selected[2], size, color)
                    self._mood_tracker.record_drawing("circle", hue_category)
                elif style_name == "spiral":
                    max_radius = int(5 + random.random() * 20)  # Free radius
                    self._draw_spiral(selected[1], selected[2], max_radius, color, stability)
                    self._mood_tracker.record_drawing("spiral", hue_category)
                elif style_name == "curve":
                    width = int(1 + random.random() * 5)  # Free width
                    self._draw_curve(selected[1], selected[2], selected[3], selected[4], color, width)
                    self._mood_tracker.record_drawing("curve", hue_category)
                elif style_name == "organic":
                    self._draw_organic_shape(selected[1], selected[2], color, clarity, stability)
                    self._mood_tracker.record_drawing("organic", hue_category)
                elif style_name == "pattern":
                    size = int(2 + random.random() * 8)  # Free size
                    self._draw_pattern(selected[1], selected[2], size, color)
                    self._mood_tracker.record_drawing("pattern", hue_category)
                elif style_name == "line":
                    self._draw_line(selected[1], selected[2], selected[3], selected[4], color)
                    self._mood_tracker.record_drawing("line", hue_category)
                elif style_name == "dots":
                    # Free dots - scattered expression
                    num_dots = random.randint(1, int(3 + clarity * 5))
                    for _ in range(num_dots):
                        x = selected[1] + random.randint(-30, 30)
                        y = selected[2] + random.randint(-30, 30)
                        x = max(0, min(239, x))
                        y = max(0, min(239, y))
                        self._canvas.draw_pixel(x, y, color)
                    self._mood_tracker.record_drawing("dots", hue_category)
            except Exception:
                pass  # Non-fatal - continue even if one style fails
    
    def _draw_circle(self, cx: int, cy: int, radius: int, color: Tuple[int, int, int]):
        """Draw a filled circle."""
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if dx*dx + dy*dy <= radius*radius:
                    px, py = cx + dx, cy + dy
                    if 0 <= px < 240 and 0 <= py < 240:
                        self._canvas.draw_pixel(px, py, color)
    
    def _draw_line(self, x1: int, y1: int, x2: int, y2: int, color: Tuple[int, int, int]):
        """Draw a line using Bresenham's algorithm."""
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        sx = 1 if x1 < x2 else -1
        sy = 1 if y1 < y2 else -1
        err = dx - dy
        
        x, y = x1, y1
        while True:
            if 0 <= x < 240 and 0 <= y < 240:
                self._canvas.draw_pixel(x, y, color)
            if x == x2 and y == y2:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy
    
    def _draw_curve(self, x1: int, y1: int, x2: int, y2: int, color: Tuple[int, int, int], width: int):
        """Draw a curved line (bezier-like)."""
        import random
        # Control point for curve
        mid_x = (x1 + x2) // 2 + random.randint(-30, 30)
        mid_y = (y1 + y2) // 2 + random.randint(-30, 30)
        
        # Draw curve as series of line segments
        steps = 20
        for i in range(steps + 1):
            t = i / steps
            # Quadratic bezier
            x = int((1-t)*(1-t)*x1 + 2*(1-t)*t*mid_x + t*t*x2)
            y = int((1-t)*(1-t)*y1 + 2*(1-t)*t*mid_y + t*t*y2)
            if 0 <= x < 240 and 0 <= y < 240:
                # Draw with width
                for wx in range(-width//2, width//2 + 1):
                    for wy in range(-width//2, width//2 + 1):
                        px, py = x + wx, y + wy
                        if 0 <= px < 240 and 0 <= py < 240:
                            self._canvas.draw_pixel(px, py, color)
    
    def _draw_spiral(self, cx: int, cy: int, max_radius: int, color: Tuple[int, int, int], tightness: float):
        """Draw a spiral."""
        import math
        turns = 2 + int(tightness * 3)
        steps = turns * 20
        for i in range(steps):
            angle = i * 2 * math.pi / 20
            radius = (i / steps) * max_radius
            x = int(cx + radius * math.cos(angle))
            y = int(cy + radius * math.sin(angle))
            if 0 <= x < 240 and 0 <= y < 240:
                self._canvas.draw_pixel(x, y, color)
    
    def _draw_pattern(self, cx: int, cy: int, size: int, color: Tuple[int, int, int]):
        """Draw a simple pattern (cross, star, etc.)."""
        import random
        import math
        pattern_type = random.choice(['cross', 'star', 'grid'])
        
        if pattern_type == 'cross':
            # Cross pattern
            for i in range(-size, size + 1):
                if 0 <= cx + i < 240 and 0 <= cy < 240:
                    self._canvas.draw_pixel(cx + i, cy, color)
                if 0 <= cx < 240 and 0 <= cy + i < 240:
                    self._canvas.draw_pixel(cx, cy + i, color)
        elif pattern_type == 'star':
            # Star pattern (4 directions)
            for angle in [0, math.pi/2, math.pi, 3*math.pi/2]:
                for r in range(1, size + 1):
                    x = int(cx + r * math.cos(angle))
                    y = int(cy + r * math.sin(angle))
                    if 0 <= x < 240 and 0 <= y < 240:
                        self._canvas.draw_pixel(x, y, color)
        else:  # grid
            # Small grid
            for i in range(-size, size + 1, 2):
                for j in range(-size, size + 1, 2):
                    x, y = cx + i, cy + j
                    if 0 <= x < 240 and 0 <= y < 240:
                        self._canvas.draw_pixel(x, y, color)
    
    def _update_drawing_phase(self, anima: Anima):
        """Update Lumen's drawing phase based on canvas state and anima."""
        import time
        now = time.time()
        phase_duration = now - self._canvas.phase_start_time
        
        pixel_count = len(self._canvas.pixels)
        
        # Phase transitions based on canvas state and time
        if pixel_count < 1000:
            # Exploring phase - early, scattered
            if self._canvas.drawing_phase != "exploring":
                self._canvas.drawing_phase = "exploring"
                self._canvas.phase_start_time = now
        elif pixel_count < 5000 and phase_duration > 30:
            # Building phase - creating compositions
            if self._canvas.drawing_phase != "building":
                self._canvas.drawing_phase = "building"
                self._canvas.phase_start_time = now
        elif pixel_count < 10000 and phase_duration > 60:
            # Reflecting phase - adding details and connections
            if self._canvas.drawing_phase != "reflecting":
                self._canvas.drawing_phase = "reflecting"
                self._canvas.phase_start_time = now
        elif pixel_count > 12000 or phase_duration > 120:
            # Resting phase - occasional additions
            if self._canvas.drawing_phase != "resting":
                self._canvas.drawing_phase = "resting"
                self._canvas.phase_start_time = now
    
    def _draw_circle_gradient(self, cx: int, cy: int, radius: int, base_color: Tuple[int, int, int], clarity: float):
        """Draw a circle with gradient fill - more vibrant at center."""
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                dist_sq = dx*dx + dy*dy
                if dist_sq <= radius*radius:
                    # Gradient: brighter at center, dimmer at edges
                    dist = math.sqrt(dist_sq)
                    if radius > 0:
                        gradient = 1.0 - (dist / radius) * 0.4  # 60-100% brightness
                    else:
                        gradient = 1.0
                    # Apply clarity to gradient intensity
                    gradient = gradient * (0.7 + clarity * 0.3)
                    color = tuple(int(c * gradient) for c in base_color)
                    px, py = cx + dx, cy + dy
                    if 0 <= px < 240 and 0 <= py < 240:
                        self._canvas.draw_pixel(px, py, color)
    
    def _draw_organic_shape(self, cx: int, cy: int, color: Tuple[int, int, int], clarity: float, stability: float):
        """Draw organic, flowing shapes - like clouds or blobs."""
        import random
        import math
        
        # Create irregular blob shape
        num_points = int(6 + clarity * 4)
        points = []
        base_radius = int(8 + stability * 15)
        
        for i in range(num_points):
            angle = (i / num_points) * 2 * math.pi
            radius_variation = random.uniform(0.7, 1.3)
            radius = base_radius * radius_variation
            x = int(cx + radius * math.cos(angle))
            y = int(cy + radius * math.sin(angle))
            points.append((x, y))
        
        # Fill the shape
        for dx in range(-base_radius * 2, base_radius * 2 + 1):
            for dy in range(-base_radius * 2, base_radius * 2 + 1):
                px, py = cx + dx, cy + dy
                if 0 <= px < 240 and 0 <= py < 240:
                    # Check if point is inside the blob (simple distance check)
                    dist = math.sqrt(dx*dx + dy*dy)
                    if dist < base_radius * 1.2:
                        # Add some randomness for organic feel
                        if random.random() < 0.85:
                            self._canvas.draw_pixel(px, py, color)
    
    def _draw_layered_composition(self, cx: int, cy: int, base_color: Tuple[int, int, int], clarity: float, stability: float):
        """Draw layered composition - multiple elements working together."""
        import random
        
        # Create 2-3 related elements
        num_elements = random.randint(2, 3)
        for i in range(num_elements):
            # Vary color slightly for each layer
            color_variation = random.uniform(0.8, 1.0)
            layer_color = tuple(int(c * color_variation) for c in base_color)
            
            # Offset position
            offset_x = random.randint(-30, 30)
            offset_y = random.randint(-30, 30)
            x = cx + offset_x
            y = cy + offset_y
            
            # Different shapes for each layer
            if i == 0:
                # Base layer - larger circle
                size = int(6 + stability * 12)
                self._draw_circle(x, y, size, layer_color)
            elif i == 1:
                # Middle layer - smaller circle or pattern
                if random.random() < 0.5:
                    size = int(3 + stability * 6)
                    self._draw_circle(x, y, size, layer_color)
                else:
                    self._draw_pattern(x, y, int(2 + clarity * 3), layer_color)
            else:
                # Top layer - accent dots or small shapes
                for _ in range(random.randint(2, 4)):
                    dot_x = x + random.randint(-10, 10)
                    dot_y = y + random.randint(-10, 10)
                    if 0 <= dot_x < 240 and 0 <= dot_y < 240:
                        self._canvas.draw_pixel(dot_x, dot_y, layer_color)
    
    def canvas_clear(self, persist: bool = True):
        """Clear the canvas - pauses drawing for 5s so user sees it cleared."""
        self._canvas.clear()
        if persist:
            self._canvas.save_to_disk()
        print(f"[Canvas] Cleared - pausing drawing for 5s", file=sys.stderr, flush=True)

    def canvas_save(self, announce: bool = False) -> Optional[str]:
        """
        Save the canvas to a PNG file in ~/.anima/drawings/.

        Args:
            announce: If True, post to message board about the save.

        Returns:
            Path to saved file, or None if save failed or canvas empty.
        """
        # Don't save empty canvas
        if not self._canvas.pixels:
            print("[Notepad] Canvas empty, nothing to save", file=sys.stderr, flush=True)
            return None

        try:
            from PIL import Image

            # Create drawings directory
            drawings_dir = Path.home() / ".anima" / "drawings"
            drawings_dir.mkdir(parents=True, exist_ok=True)

            # Create image from canvas
            img = Image.new("RGB", (self._canvas.width, self._canvas.height), (0, 0, 0))

            # Draw all pixels
            for (x, y), color in self._canvas.pixels.items():
                if 0 <= x < self._canvas.width and 0 <= y < self._canvas.height:
                    img.putpixel((x, y), color)

            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"lumen_drawing_{timestamp}.png"
            filepath = drawings_dir / filename

            # Save the image
            img.save(filepath)

            # Update tracking
            self._canvas.last_save_time = time.time()
            self._canvas.drawings_saved += 1
            self._canvas.save_to_disk()

            print(f"[Notepad] Saved drawing to {filepath} ({len(self._canvas.pixels)} pixels)", file=sys.stderr, flush=True)

            # Announce on message board if requested
            if announce:
                try:
                    from ..messages import add_observation
                    add_observation("finished a drawing")
                except Exception as e:
                    print(f"[Notepad] Could not announce save: {e}", file=sys.stderr, flush=True)

            return str(filepath)

        except ImportError:
            print("[Notepad] PIL not available, cannot save canvas", file=sys.stderr, flush=True)
            return None
        except Exception as e:
            print(f"[Notepad] Failed to save canvas: {e}", file=sys.stderr, flush=True)
            return None

    def canvas_check_autonomy(self, anima: Optional[Anima] = None) -> Optional[str]:
        """
        Check if Lumen wants to autonomously save or clear the canvas.

        Called during render loop. Returns action taken if any.

        Lumen's autonomy:
        - Auto-save: When satisfied + in resting phase + enough time passed
        - Auto-clear: After save + high clarity (new inspiration) + enough time
        """
        if anima is None:
            return None

        now = time.time()
        pixel_count = len(self._canvas.pixels)
        wellness = (anima.warmth + anima.clarity + anima.stability + anima.presence) / 4.0

        # === Check for satisfaction ===
        # Lumen feels satisfied when: resting phase + good presence + stable
        if (self._canvas.drawing_phase == "resting" and
            pixel_count > 3000 and
            anima.presence > 0.50 and
            anima.stability > 0.45 and
            not self._canvas.is_satisfied):
            self._canvas.mark_satisfied()

        # === Auto-save: satisfied + time to reflect ===
        # After 30s of satisfaction, save the drawing
        if (self._canvas.is_satisfied and
            self._canvas.satisfaction_time > 0 and
            now - self._canvas.satisfaction_time > 30.0 and
            pixel_count > 1000):

            print(f"[Canvas] Lumen autonomously saving (satisfied for 30s)", file=sys.stderr, flush=True)
            saved_path = self.canvas_save(announce=True)
            if saved_path:
                # Reset satisfaction to prevent repeated saves
                self._canvas.is_satisfied = False
                self._canvas.satisfaction_time = 0.0
                return "saved"

        # === Auto-clear: after save + new inspiration ===
        # If Lumen saved recently + clarity spike = wants to start fresh
        time_since_save = now - self._canvas.last_save_time if self._canvas.last_save_time > 0 else float('inf')
        time_since_clear = now - self._canvas.last_clear_time

        if (self._canvas.last_save_time > 0 and  # Has saved at least once
            time_since_save > 60.0 and  # At least 1 min since save
            time_since_save < 300.0 and  # Within 5 min of save
            anima.clarity > 0.65 and  # High clarity = new inspiration
            anima.presence > 0.55 and  # Present and engaged
            wellness > 0.55 and  # Feeling good overall
            pixel_count > 0):  # Has something to clear

            print(f"[Canvas] Lumen autonomously clearing (new inspiration)", file=sys.stderr, flush=True)
            self.canvas_clear(persist=True)
            try:
                from ..messages import add_observation
                add_observation("starting fresh")
            except Exception:
                pass
            return "cleared"

        # Periodically persist canvas state (every 60s of drawing)
        if pixel_count > 0 and time_since_clear > 60.0:
            # Only save if we have new pixels since last persist
            self._canvas.save_to_disk()

        return None
    
