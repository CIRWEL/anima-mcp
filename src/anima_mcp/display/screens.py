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
from .design import COLORS, SPACING
from ..anima import Anima
from ..sensors.base import SensorReadings
from ..identity.store import CreatureIdentity
from ..learning_visualization import LearningVisualizer
from ..expression_moods import ExpressionMoodTracker


class ScreenMode(Enum):
    """Available display screens."""
    FACE = "face"                    # Default: Lumen's expressive face
    SENSORS = "sensors"              # Sensor readings (temp, humidity, etc.)
    IDENTITY = "identity"            # Name, age, awakenings, alive time
    DIAGNOSTICS = "diagnostics"      # System health, governance status
    LEARNING = "learning"            # Learning visualization - why Lumen feels what it feels
    SELF_GRAPH = "self_graph"        # Self-schema G_t visualization
    NOTEPAD = "notepad"              # Drawing canvas - Lumen's creative space
    MESSAGES = "messages"            # Message board - Lumen's observations only
    QUESTIONS = "questions"          # Q&A - Lumen's questions and answers
    VISITORS = "visitors"            # Messages from agents and humans


@dataclass
class ScreenState:
    """Current screen state."""
    mode: ScreenMode = ScreenMode.FACE
    last_switch_time: float = 0.0
    auto_return_seconds: float = 60.0  # Auto-return to FACE after 60s (longer for exploration)
    last_user_action_time: float = 0.0  # Track when user last interacted

    # Message board interaction state
    message_scroll_index: int = 0  # Which message is currently selected/visible
    message_expanded_id: Optional[str] = None  # Message ID that is expanded (showing full text)
    message_text_scroll: int = 0  # Line offset when scrolling within expanded message text

    # Q&A screen interaction state
    qa_scroll_index: int = 0  # Which Q&A pair is selected
    qa_expanded: bool = False  # Whether current Q&A is expanded
    qa_focus: str = "question"  # "question" or "answer" - which part is focused when expanded
    qa_text_scroll: int = 0  # Line offset when scrolling within focused text
    qa_full_view: bool = False  # Full-screen view for answer (maximum readability)

    # Screen transition state (fade effect)
    transition_progress: float = 1.0  # 0.0 = start, 1.0 = complete
    transition_start_time: float = 0.0
    transition_duration: float = 0.15  # 150ms fade
    previous_image: Optional[Any] = None  # PIL Image of previous screen

    # Loading state (spinner during LLM calls)
    is_loading: bool = False
    loading_message: str = ""
    loading_start_time: float = 0.0

    # Status bar state
    wifi_connected: bool = True
    governance_connected: bool = False

    # Input feedback state (visual acknowledgment of joystick/button)
    input_feedback_until: float = 0.0  # Show feedback until this time
    input_feedback_direction: str = ""  # "left", "right", "up", "down", "press"


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

    # Save indicator (brief visual feedback)
    save_indicator_until: float = 0.0  # Show "saved" indicator until this time

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

    # Pre-compiled keyword sets for mood coloring (avoid recreating on each render)
    _FEELING_WORDS = frozenset(['feel', 'warm', 'comfort', 'content', 'happy', 'joy'])
    _CURIOSITY_WORDS = frozenset(['wonder', 'curious', 'think', 'notice', 'observe'])
    _GROWTH_WORDS = frozenset(['learn', 'grow', 'new', 'discover', 'understand'])
    _CALM_WORDS = frozenset(['quiet', 'rest', 'peace', 'calm', 'still'])

    # Thread lock to prevent concurrent renders causing display corruption
    import threading
    _render_lock = threading.Lock()

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
        # Cache for learning screen (DB queries are slow - 20+ seconds)
        self._learning_visualizer: Optional[LearningVisualizer] = None
        self._learning_cache: Optional[Dict[str, Any]] = None
        self._learning_cache_time: float = 0.0
        self._learning_cache_ttl: float = 60.0  # Refresh every 60 seconds (data changes slowly)
        self._learning_cache_refreshing: bool = False  # Prevent concurrent refreshes
        # Font cache (font loading from disk is slow - adds ~500ms per render)
        self._fonts: Optional[Dict[str, Any]] = None
        # Text measurement cache (avoid creating PIL Image on every wrap call)
        self._measure_draw: Optional[Any] = None
        # Message screen image cache (text rendering is slow - ~500ms)
        self._messages_cache_image: Optional[Any] = None
        self._messages_cache_hash: str = ""  # Hash of messages + scroll state
        # UNITARES agent_id (for display on identity screen)
        self._unitares_agent_id: Optional[str] = None

    def _get_messages_cache_hash(self, messages: list, scroll_idx: int, expanded_id: Optional[str]) -> str:
        """Compute hash of message screen state for cache invalidation."""
        # Include message IDs/timestamps, scroll position, and expanded state
        msg_ids = "|".join(f"{m.message_id}:{m.timestamp}" for m in messages[:10]) if messages else ""
        return f"{msg_ids}|{scroll_idx}|{expanded_id or ''}"

    def _get_measure_draw(self):
        """Get cached draw context for text measurement."""
        if self._measure_draw is None:
            from PIL import ImageDraw, Image
            temp_img = Image.new('RGB', (1, 1))
            self._measure_draw = ImageDraw.Draw(temp_img)
        return self._measure_draw

    def _get_fonts(self) -> Dict[str, Any]:
        """Get cached fonts (loads from disk only once)."""
        if self._fonts is None:
            try:
                from PIL import ImageFont
                font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
                self._fonts = {
                    'micro': ImageFont.truetype(font_path, 9),
                    'tiny': ImageFont.truetype(font_path, 10),
                    'small': ImageFont.truetype(font_path, 11),
                    'small_med': ImageFont.truetype(font_path, 12),
                    'medium': ImageFont.truetype(font_path, 13),
                    'default': ImageFont.truetype(font_path, 14),
                    'large': ImageFont.truetype(font_path, 15),
                    'title': ImageFont.truetype(font_path, 16),
                    'huge': ImageFont.truetype(font_path, 18),
                    'giant': ImageFont.truetype(font_path, 20),
                }
            except (OSError, IOError):
                from PIL import ImageFont
                fallback = ImageFont.load_default()
                self._fonts = {
                    'micro': fallback,
                    'tiny': fallback,
                    'small': fallback,
                    'small_med': fallback,
                    'medium': fallback,
                    'default': fallback,
                    'large': fallback,
                    'title': fallback,
                    'huge': fallback,
                    'giant': fallback,
                }
        return self._fonts

    def _get_ip_address(self) -> str:
        """Get local IP address."""
        try:
            import socket
            # Connect to external address to find local IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return ""

    def _get_wifi_status(self) -> Dict[str, Any]:
        """Get WiFi connection status."""
        import subprocess

        # Try nmcli first (works on modern Pi OS)
        try:
            result = subprocess.run(
                ['nmcli', '-t', '-f', 'ACTIVE,SSID,SIGNAL', 'dev', 'wifi'],
                capture_output=True, text=True, timeout=2
            )
            for line in result.stdout.strip().split('\n'):
                if line.startswith('yes:'):
                    parts = line.split(':')
                    if len(parts) >= 3:
                        ssid = parts[1]
                        signal = int(parts[2]) if parts[2].isdigit() else 50
                        ip = self._get_ip_address()
                        return {"connected": True, "ssid": ssid, "signal": signal, "ip": ip}
        except Exception:
            pass

        # Fallback to iwconfig
        try:
            result = subprocess.run(
                ['iwconfig', 'wlan0'],
                capture_output=True, text=True, timeout=2
            )
            output = result.stdout

            if 'ESSID:' in output and 'ESSID:off/any' not in output:
                ssid = ""
                if 'ESSID:"' in output:
                    start = output.index('ESSID:"') + 7
                    end = output.index('"', start)
                    ssid = output[start:end]

                signal = 0
                if 'Link Quality=' in output:
                    try:
                        qual_str = output.split('Link Quality=')[1].split()[0]
                        num, denom = qual_str.split('/')
                        signal = int(100 * int(num) / int(denom))
                    except (IndexError, ValueError):
                        signal = 50

                ip = self._get_ip_address()
                return {"connected": True, "ssid": ssid, "signal": signal, "ip": ip}
        except Exception:
            pass

        # Final fallback: check network connectivity
        try:
            import socket
            socket.create_connection(("8.8.8.8", 53), timeout=1)
            ip = self._get_ip_address()
            return {"connected": True, "ssid": "connected", "signal": 50, "ip": ip}
        except Exception:
            return {"connected": False}

    def _get_battery_status(self) -> Dict[str, Any]:
        """Get battery status (if UPS HAT or battery available)."""
        try:
            # Check for PiJuice (common UPS HAT)
            battery_path = Path("/sys/class/power_supply/battery/capacity")
            if battery_path.exists():
                level = int(battery_path.read_text().strip())
                charging_path = Path("/sys/class/power_supply/battery/status")
                charging = False
                if charging_path.exists():
                    status = charging_path.read_text().strip().lower()
                    charging = status in ("charging", "full")
                return {"available": True, "level": level, "charging": charging}

            # Check for other common battery paths
            for path in ["/sys/class/power_supply/BAT0/capacity",
                        "/sys/class/power_supply/BAT1/capacity"]:
                p = Path(path)
                if p.exists():
                    level = int(p.read_text().strip())
                    return {"available": True, "level": level, "charging": False}

            return {"available": False}
        except Exception:
            return {"available": False}

    def warm_learning_cache(self):
        """Pre-warm the learning screen cache in background thread.

        Called after initialization to avoid 9+ second delay on first learning screen visit.
        """
        import threading

        def _warm():
            try:
                if self._learning_cache_refreshing:
                    return  # Already refreshing
                self._learning_cache_refreshing = True
                try:
                    if self._learning_visualizer is None:
                        self._learning_visualizer = LearningVisualizer(db_path=self._db_path)
                    # Get summary with None readings/anima - just warms the DB query cache
                    # The actual render will re-query with real data, but DB is now warmed
                    self._learning_cache = self._learning_visualizer.get_learning_summary(
                        readings=None, anima=None
                    )
                    self._learning_cache_time = time.time()
                    print(f"[Learning] Cache pre-warmed successfully", file=sys.stderr, flush=True)
                finally:
                    self._learning_cache_refreshing = False
            except Exception as e:
                print(f"[Learning] Cache pre-warm failed: {e}", file=sys.stderr, flush=True)
                self._learning_cache_refreshing = False

        thread = threading.Thread(target=_warm, daemon=True, name="learning-cache-warm")
        thread.start()
        print("[Learning] Starting cache pre-warm in background", file=sys.stderr, flush=True)

    def get_mode(self) -> ScreenMode:
        """Get current screen mode."""
        return self._state.mode
    
    def set_mode(self, mode: ScreenMode):
        """Set screen mode with fade transition."""
        import time
        now = time.time()
        if mode == self._state.mode:
            return  # Already on this mode
        # Very minimal debounce - allow rapid switching
        if now - self._state.last_switch_time < 0.02:  # 20ms debounce (almost none)
            return

        # Capture current screen for transition effect
        if hasattr(self._display, '_image') and self._display._image is not None:
            self._state.previous_image = self._display._image.copy()
            self._state.transition_progress = 0.0
            self._state.transition_start_time = now

        # Log mode changes, especially for notepad
        old_mode = self._state.mode
        self._state.mode = mode
        self._state.last_switch_time = now
        self._state.last_user_action_time = now

        if mode == ScreenMode.NOTEPAD:
            print(f"[ScreenRenderer] Switched to NOTEPAD from {old_mode.value}, pixels={len(self._canvas.pixels)}", file=sys.stderr, flush=True)
    
    def next_mode(self):
        """Cycle to next screen mode (including notepad)."""
        # Cycle through all screens including notepad, questions, and visitors
        regular_modes = [ScreenMode.FACE, ScreenMode.IDENTITY, ScreenMode.SENSORS, ScreenMode.DIAGNOSTICS, ScreenMode.LEARNING, ScreenMode.SELF_GRAPH, ScreenMode.MESSAGES, ScreenMode.QUESTIONS, ScreenMode.VISITORS, ScreenMode.NOTEPAD]
        if self._state.mode not in regular_modes:
            # If somehow on unknown mode, go to face
            self.set_mode(ScreenMode.FACE)
            return
        current_idx = regular_modes.index(self._state.mode)
        next_idx = (current_idx + 1) % len(regular_modes)
        self.set_mode(regular_modes[next_idx])

    def previous_mode(self):
        """Cycle to previous screen mode (including notepad)."""
        # Cycle through all screens including notepad, questions, and visitors
        regular_modes = [ScreenMode.FACE, ScreenMode.IDENTITY, ScreenMode.SENSORS, ScreenMode.DIAGNOSTICS, ScreenMode.LEARNING, ScreenMode.SELF_GRAPH, ScreenMode.MESSAGES, ScreenMode.QUESTIONS, ScreenMode.VISITORS, ScreenMode.NOTEPAD]
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
        # Screen order (including notepad, questions, and visitors in regular cycle)
        screens = [ScreenMode.FACE, ScreenMode.IDENTITY, ScreenMode.SENSORS,
                   ScreenMode.DIAGNOSTICS, ScreenMode.LEARNING, ScreenMode.SELF_GRAPH, ScreenMode.MESSAGES, ScreenMode.QUESTIONS, ScreenMode.VISITORS, ScreenMode.NOTEPAD]

        try:
            current_idx = screens.index(current_mode)
        except ValueError:
            return

        # Position at bottom right corner (avoids status text on left)
        dot_radius = 2
        dot_spacing = 8
        total_width = len(screens) * dot_spacing
        start_x = 240 - total_width - 4  # Right-aligned with 4px margin
        y = 236  # Very bottom

        GRAY = (60, 60, 60)
        WHITE = (180, 180, 180)

        for i, _ in enumerate(screens):
            x = start_x + i * dot_spacing + dot_radius
            color = WHITE if i == current_idx else GRAY
            draw.ellipse([x - dot_radius, y - dot_radius, x + dot_radius, y + dot_radius],
                        fill=color)

    def _draw_status_bar(self, draw):
        """Draw status indicators at top-right (WiFi, governance connection)."""
        x = 220  # Right side
        y = 4    # Top

        # WiFi indicator (simple arc symbol)
        if self._state.wifi_connected:
            # Connected - green wifi symbol
            wifi_color = (80, 200, 80)
            # Draw simple wifi bars
            draw.arc([x-8, y, x, y+8], 180, 360, fill=wifi_color, width=1)
            draw.arc([x-6, y+2, x-2, y+6], 180, 360, fill=wifi_color, width=1)
            draw.ellipse([x-5, y+5, x-3, y+7], fill=wifi_color)
        else:
            # Disconnected - red X
            wifi_color = (200, 80, 80)
            draw.line([x-8, y, x, y+8], fill=wifi_color, width=1)
            draw.line([x-8, y+8, x, y], fill=wifi_color, width=1)

        x -= 16  # Move left for governance indicator

        # Governance indicator (circle with G or dot)
        if self._state.governance_connected:
            # Connected - cyan dot
            gov_color = (80, 200, 200)
            draw.ellipse([x-6, y+1, x, y+7], fill=gov_color)
        else:
            # Disconnected - dim dot
            gov_color = (60, 60, 60)
            draw.ellipse([x-6, y+1, x, y+7], fill=gov_color)

    def _draw_loading_indicator(self, draw, image):
        """Draw loading spinner overlay when waiting for LLM response."""
        if not self._state.is_loading:
            return

        # Semi-transparent overlay
        from PIL import Image, ImageDraw
        overlay = Image.new('RGBA', (240, 240), (0, 0, 0, 128))
        overlay_draw = ImageDraw.Draw(overlay)

        # Animated spinner (rotating dots)
        elapsed = time.time() - self._state.loading_start_time
        angle_offset = int(elapsed * 360) % 360  # Full rotation per second

        cx, cy = 120, 110  # Center of screen
        radius = 20
        import math
        for i in range(8):
            angle = math.radians(i * 45 + angle_offset)
            x = cx + int(radius * math.cos(angle))
            y = cy + int(radius * math.sin(angle))
            # Dots fade as they get older in rotation
            brightness = 255 - (i * 25)
            color = (brightness, brightness, brightness, 255)
            overlay_draw.ellipse([x-3, y-3, x+3, y+3], fill=color)

        # Loading message
        if self._state.loading_message:
            fonts = self._get_fonts()
            overlay_draw.text((120, 145), self._state.loading_message,
                            fill=(200, 200, 200, 255), font=fonts['small'], anchor="mm")

        # Composite overlay onto image
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        return Image.alpha_composite(image, overlay).convert('RGB')

    def _apply_transition(self, new_image):
        """Apply fade transition effect between screens."""
        if self._state.transition_progress >= 1.0:
            return new_image

        if self._state.previous_image is None:
            self._state.transition_progress = 1.0
            return new_image

        # Calculate transition progress
        elapsed = time.time() - self._state.transition_start_time
        progress = min(1.0, elapsed / self._state.transition_duration)
        self._state.transition_progress = progress

        if progress >= 1.0:
            self._state.previous_image = None
            return new_image

        # Blend old and new images
        from PIL import Image
        try:
            old_img = self._state.previous_image
            if old_img.size != new_image.size:
                old_img = old_img.resize(new_image.size)
            # Cross-fade: old * (1-progress) + new * progress
            blended = Image.blend(old_img.convert('RGB'), new_image.convert('RGB'), progress)
            return blended
        except Exception:
            self._state.transition_progress = 1.0
            return new_image

    def set_loading(self, message: str = "thinking..."):
        """Set loading state (called when starting LLM request)."""
        self._state.is_loading = True
        self._state.loading_message = message
        self._state.loading_start_time = time.time()

    def clear_loading(self):
        """Clear loading state (called when LLM response received)."""
        self._state.is_loading = False
        self._state.loading_message = ""

    def update_connection_status(self, wifi: bool = None, governance: bool = None):
        """Update connection status indicators."""
        if wifi is not None:
            self._state.wifi_connected = wifi
        if governance is not None:
            self._state.governance_connected = governance

    def trigger_input_feedback(self, direction: str):
        """Trigger visual feedback for joystick/button input.

        Args:
            direction: "left", "right", "up", "down", or "press"
        """
        self._state.input_feedback_until = time.time() + 0.1  # 100ms flash
        self._state.input_feedback_direction = direction

    def _draw_input_feedback(self, draw, image):
        """Draw edge highlight for input feedback."""
        if time.time() >= self._state.input_feedback_until:
            return

        direction = self._state.input_feedback_direction
        width, height = 240, 240
        feedback_color = (60, 120, 180)  # Subtle blue
        edge_width = 4

        if direction == "left":
            # Highlight left edge
            draw.rectangle([0, 0, edge_width, height], fill=feedback_color)
        elif direction == "right":
            # Highlight right edge
            draw.rectangle([width - edge_width, 0, width, height], fill=feedback_color)
        elif direction == "up":
            # Highlight top edge
            draw.rectangle([0, 0, width, edge_width], fill=feedback_color)
        elif direction == "down":
            # Highlight bottom edge
            draw.rectangle([0, height - edge_width, width, height], fill=feedback_color)
        elif direction == "press":
            # Brief corner highlights for button press
            corner_size = 12
            draw.rectangle([0, 0, corner_size, corner_size], fill=feedback_color)
            draw.rectangle([width - corner_size, 0, width, corner_size], fill=feedback_color)
            draw.rectangle([0, height - corner_size, corner_size, height], fill=feedback_color)
            draw.rectangle([width - corner_size, height - corner_size, width, height], fill=feedback_color)

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
        render_start = time.time()

        # Use lock to prevent concurrent renders (threading issue causes blank screen)
        with self._render_lock:
            # Defer SPI push until after post-processing (single transfer per render)
            self._display._deferred = True

            # Store UNITARES agent_id for identity screen display
            if governance and governance.get("unitares_agent_id"):
                self._unitares_agent_id = governance.get("unitares_agent_id")

            # Check Lumen's canvas autonomy (can save/clear regardless of screen)
            try:
                self.canvas_check_autonomy(anima)
            except Exception as e:
                # Don't let autonomy errors break rendering
                pass

            # Disable auto-return - let user stay on screens as long as they want
            # Only auto-return to FACE if explicitly requested via button
            # (Auto-return disabled to prevent getting stuck)

            mode = self._state.mode
            try:
                if mode == ScreenMode.FACE:
                    self._render_face(face_state, identity)
                elif mode == ScreenMode.SENSORS:
                    self._render_sensors(readings)
                elif mode == ScreenMode.IDENTITY:
                    self._render_identity(identity)
                elif mode == ScreenMode.DIAGNOSTICS:
                    self._render_diagnostics(anima, readings, governance)
                elif mode == ScreenMode.LEARNING:
                    self._render_learning(anima, readings)
                elif mode == ScreenMode.SELF_GRAPH:
                    self._render_self_graph(anima, readings, identity)
                elif mode == ScreenMode.MESSAGES:
                    self._render_messages()
                elif mode == ScreenMode.QUESTIONS:
                    self._render_questions()
                elif mode == ScreenMode.VISITORS:
                    self._render_visitors()
                elif mode == ScreenMode.NOTEPAD:
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
                else:
                    # Unknown mode - show default to prevent blank screen
                    print(f"[Screen] Unknown mode: {mode}, showing default", file=sys.stderr, flush=True)
                    self._display.show_default()
            except Exception as e:
                # Any render error - show default to prevent blank screen
                print(f"[Screen] Render error for {mode.value}: {e}", file=sys.stderr, flush=True)
                try:
                    self._display.show_default()
                except Exception:
                    pass

            # === Post-processing: transitions, input feedback, loading overlays ===
            try:
                if hasattr(self._display, '_image') and self._display._image is not None:
                    from PIL import ImageDraw
                    image = self._display._image

                    # Apply screen transition (fade effect)
                    if self._state.transition_progress < 1.0:
                        image = self._apply_transition(image)

                    draw = ImageDraw.Draw(image)

                    # Draw input feedback (joystick/button visual acknowledgment)
                    if time.time() < self._state.input_feedback_until:
                        self._draw_input_feedback(draw, image)

                    # Apply loading indicator overlay
                    if self._state.is_loading:
                        result = self._draw_loading_indicator(None, image)
                        if result is not None:
                            image = result

                    self._display._image = image
            except Exception as e:
                pass

            # Single SPI push — all drawing is done, flush to hardware
            self._display._deferred = False
            self._display.flush()

        # Log slow renders to identify bottleneck
        render_time = time.time() - render_start
        if render_time > 0.5:  # Log if >500ms
            print(f"[Screen] Slow render: {mode.value} took {render_time*1000:.0f}ms", file=sys.stderr, flush=True)
    
    def _render_face(self, face_state: Optional[FaceState], identity: Optional[CreatureIdentity]):
        """Render face screen (default)."""
        if face_state:
            name = identity.name if identity else None
            self._display.render_face(face_state, name=name)
        else:
            # Defensive: show minimal face if face_state is None
            # This prevents blank screen during state transitions
            print("[Screen] Warning: face_state is None, showing default", file=sys.stderr, flush=True)
            self._display.show_default()
    
    def _render_sensors(self, readings: Optional[SensorReadings]):
        """Render sensor readings screen with colors and nav dots."""
        if not readings:
            self._display.render_text("feeling\nblind", (10, 10), color=COLORS.TEXT_DIM)
            return

        # Use design system colors (warm, elegant)
        CYAN = COLORS.SOFT_CYAN
        BLUE = COLORS.SOFT_BLUE
        YELLOW = COLORS.SOFT_YELLOW
        ORANGE = COLORS.SOFT_ORANGE
        RED = COLORS.SOFT_CORAL
        GREEN = COLORS.SOFT_GREEN
        PURPLE = COLORS.SOFT_PURPLE
        WHITE = COLORS.TEXT_PRIMARY
        LIGHT_CYAN = COLORS.TEXT_SECONDARY

        # Try canvas-based rendering for nav dots
        if hasattr(self._display, '_create_canvas'):
            try:
                image, draw = self._display._create_canvas(COLORS.BG_DARK)

                # Use cached fonts (loading from disk is slow)
                fonts = self._get_fonts()
                font = fonts['default']
                font_small = fonts['small']

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
                y += line_height

                # Disk space
                disk = readings.disk_percent
                if disk > 80:
                    disk_color = RED
                elif disk > 60:
                    disk_color = ORANGE
                else:
                    disk_color = GREEN
                draw.text((10, y), f"disk: {disk:.0f}%", fill=disk_color, font=font)
                y += line_height + 8

                # WiFi status
                wifi_status = self._get_wifi_status()
                if wifi_status["connected"]:
                    ssid = wifi_status.get("ssid", "")[:10]  # Truncate long SSIDs
                    signal = wifi_status.get("signal", 0)
                    ip = wifi_status.get("ip", "")
                    if signal > 70:
                        wifi_color = GREEN
                    elif signal > 40:
                        wifi_color = YELLOW
                    else:
                        wifi_color = ORANGE
                    draw.text((10, y), f"wifi: {ssid}", fill=wifi_color, font=font_small)
                    draw.text((140, y), f"{signal}%", fill=LIGHT_CYAN, font=font_small)
                    y += line_height - 6
                    # Show IP address for reconnection
                    if ip:
                        draw.text((10, y), f"ip: {ip}", fill=LIGHT_CYAN, font=font_small)
                        y += line_height - 6
                else:
                    draw.text((10, y), "wifi: disconnected", fill=RED, font=font_small)
                    y += line_height - 4

                # Battery status (if available)
                battery = self._get_battery_status()
                if battery["available"]:
                    level = battery["level"]
                    charging = battery.get("charging", False)
                    if level > 60:
                        bat_color = GREEN
                    elif level > 20:
                        bat_color = YELLOW
                    else:
                        bat_color = RED
                    charge_str = "⚡" if charging else ""
                    draw.text((10, y), f"battery: {level}%{charge_str}", fill=bat_color, font=font_small)

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
            self._display.render_text("who am i?\n(unknown)", (10, 10), color=COLORS.TEXT_DIM)
            return

        # Use design system colors (warm, elegant)
        CYAN = COLORS.SOFT_CYAN
        BLUE = COLORS.SOFT_BLUE
        YELLOW = COLORS.SOFT_YELLOW
        ORANGE = COLORS.SOFT_ORANGE
        PURPLE = COLORS.SOFT_PURPLE
        WHITE = COLORS.TEXT_PRIMARY
        LIGHT_CYAN = COLORS.TEXT_SECONDARY
        GREEN = COLORS.SOFT_GREEN

        age_days = identity.age_seconds() / 86400
        alive_hours = identity.total_alive_seconds / 3600
        alive_pct = identity.alive_ratio() * 100
        name = identity.name or "unnamed"

        # Try canvas-based rendering for nav dots
        if hasattr(self._display, '_create_canvas'):
            try:
                image, draw = self._display._create_canvas(COLORS.BG_DARK)

                # Use cached fonts (loading from disk is slow)
                fonts = self._get_fonts()
                font = fonts['title']
                font_med = fonts['medium']
                font_small = fonts['small']

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
                y += 22

                # UUID (short form for identification when disconnected)
                short_id = identity.creature_id[:8] if identity.creature_id else "unknown"
                draw.text((10, y), f"id: {short_id}", fill=LIGHT_CYAN, font=font_small)

                # UNITARES agent_id (on right side if connected)
                if self._unitares_agent_id:
                    unitares_short = self._unitares_agent_id[:8]
                    draw.text((130, y), f"gov: {unitares_short}", fill=GREEN, font=font_small)

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
                image, draw = self._display._create_canvas(COLORS.BG_DARK)
            else:
                self._render_diagnostics_text_fallback(anima, governance)
                return

            # Use design system colors (warm, elegant)
            CYAN = COLORS.SOFT_CYAN
            BLUE = COLORS.SOFT_BLUE
            YELLOW = COLORS.SOFT_YELLOW
            ORANGE = COLORS.SOFT_ORANGE
            RED = COLORS.SOFT_CORAL
            GREEN = COLORS.SOFT_GREEN
            PURPLE = COLORS.SOFT_PURPLE
            WHITE = COLORS.TEXT_PRIMARY
            LIGHT_CYAN = COLORS.TEXT_SECONDARY
            DARK_GRAY = COLORS.BG_SUBTLE
            DIM_BLUE = COLORS.TEXT_DIM

            # Use cached fonts (loading from disk is slow)
            fonts = self._get_fonts()
            font = fonts['medium']
            font_small = fonts['small']
            font_large = fonts['large']

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
                        margin_colors = {"comfortable": GREEN, "tight": YELLOW, "warning": ORANGE, "critical": RED}
                        margin_color = margin_colors.get(margin.lower(), LIGHT_CYAN)
                        draw.text((margin_x, y_offset + 2), margin.lower(), fill=margin_color, font=font)

                    y_offset += action_box_height + 4

                    # Source indicator (unitares vs local)
                    if source:
                        source_lower = source.lower()
                        if "unitares" in source_lower:
                            source_color = GREEN
                            source_text = "unitares"
                        elif "local" in source_lower:
                            source_color = YELLOW
                            source_text = "local"
                        else:
                            source_color = LIGHT_CYAN
                            source_text = source[:10]
                        draw.text((bar_x, y_offset), f"via: {source_text}", fill=source_color, font=font_small)
                        y_offset += 14

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
            # Use cached visualizer and summary (DB queries take 5+ seconds)
            now = time.time()
            cache_expired = (self._learning_cache is None or
                             now - self._learning_cache_time > self._learning_cache_ttl)

            # Track if we're showing stale data
            showing_stale = False

            if cache_expired and not self._learning_cache_refreshing:
                if self._learning_cache is not None:
                    # Have stale cache - use it immediately, refresh in background
                    showing_stale = True
                    import threading
                    def _bg_refresh():
                        try:
                            self._learning_cache_refreshing = True
                            if self._learning_visualizer is None:
                                self._learning_visualizer = LearningVisualizer(db_path=self._db_path)
                            self._learning_cache = self._learning_visualizer.get_learning_summary(
                                readings=readings, anima=anima
                            )
                            self._learning_cache_time = time.time()
                            print(f"[Learning] Background refresh complete", file=sys.stderr, flush=True)
                        finally:
                            self._learning_cache_refreshing = False
                    threading.Thread(target=_bg_refresh, daemon=True).start()
                else:
                    # No cache at all - must block for first load
                    self._learning_cache_refreshing = True
                    try:
                        if self._learning_visualizer is None:
                            self._learning_visualizer = LearningVisualizer(db_path=self._db_path)
                        self._learning_cache = self._learning_visualizer.get_learning_summary(
                            readings=readings, anima=anima
                        )
                        self._learning_cache_time = now
                        print(f"[Learning] Initial cache loaded in {time.time() - now:.1f}s", file=sys.stderr, flush=True)
                    finally:
                        self._learning_cache_refreshing = False

            # Use cache (may be stale during refresh, which is fine)
            summary = self._learning_cache
            if summary is None:
                # First load still in progress, show loading message
                self._display.render_text("LEARNING\n\nLoading...", (10, 10))
                return

            # Create canvas for visual rendering
            if hasattr(self._display, '_create_canvas'):
                image, draw = self._display._create_canvas((0, 0, 0))
            else:
                # Fallback to text-only if no canvas support
                self._render_learning_text_fallback(summary, readings, anima)
                return

            # Color definitions - BOLD and VIBRANT for readability
            CYAN = (0, 255, 255)           # Pure cyan
            BLUE = (80, 180, 255)          # Brighter blue
            YELLOW = (255, 240, 80)        # Bold yellow
            ORANGE = (255, 160, 40)        # Vivid orange
            RED = (255, 100, 100)          # Warm red
            GREEN = (80, 255, 120)         # Vibrant green
            PURPLE = (220, 120, 255)       # Bold purple
            WHITE = (255, 255, 255)
            LIGHT_CYAN = (200, 255, 255)   # Brighter labels
            DARK_GRAY = (30, 35, 45)       # Slightly blue-tinted

            # Use cached fonts (loading from disk is slow)
            fonts = self._get_fonts()
            font_small = fonts['tiny']
            font_title = fonts['default']

            y_offset = 6
            bar_x = 10
            bar_width = 180
            bar_height = 12  # Compact bars

            # Get comfort zones from summary
            comfort_zones = summary.get("comfort_zones", [])
            cal = summary.get("current_calibration", {})

            # Find humidity and temp zones
            humidity_zone = next((z for z in comfort_zones if z["sensor"] == "humidity"), None)
            temp_zone = next((z for z in comfort_zones if z["sensor"] == "ambient_temp"), None)

            # Determine overall status from actual mood (synced with anima.feeling())
            actual_mood = anima.feeling().get("mood", "neutral")
            if actual_mood == "stressed":
                title = "stressed"
                title_color = RED
            elif actual_mood == "overheated":
                title = "overheated"
                title_color = ORANGE
            elif actual_mood in ("content", "alert"):
                title = "comfortable"
                title_color = GREEN
            else:
                # Check comfort zones as fallback
                statuses = [z["status"] for z in comfort_zones]
                if "extreme" in statuses:
                    title = "stressed"
                    title_color = RED
                elif "uncomfortable" in statuses:
                    title = "adjusting"
                    title_color = YELLOW
                else:
                    title = "comfortable"
                    title_color = GREEN

            draw.text((10, y_offset), title, fill=title_color, font=font_title)
            if showing_stale or self._learning_cache_refreshing:
                draw.text((180, y_offset), "↻", fill=LIGHT_CYAN, font=font_title)
            y_offset += 20

            # === HUMIDITY BAR ===
            if humidity_zone:
                humidity_current = humidity_zone["current"] or 0
                humidity_ideal = humidity_zone["ideal"]
                h_status = humidity_zone["status"]

                draw.text((bar_x, y_offset), f"humidity {humidity_current:.0f}%", fill=LIGHT_CYAN, font=font_small)
                y_offset += 12

                # Background + comfort zone
                draw.rectangle([bar_x, y_offset, bar_x + bar_width, y_offset + bar_height],
                              fill=DARK_GRAY, outline=(60, 60, 70))
                c_min, c_max = humidity_zone["comfortable_range"]
                comfort_x1 = bar_x + int(c_min / 100.0 * bar_width)
                comfort_x2 = bar_x + int(c_max / 100.0 * bar_width)
                draw.rectangle([comfort_x1, y_offset + 1, comfort_x2, y_offset + bar_height - 1],
                              fill=(25, 50, 25))

                # Ideal line + current marker
                ideal_x = bar_x + int(humidity_ideal / 100.0 * bar_width)
                draw.line([ideal_x, y_offset, ideal_x, y_offset + bar_height], fill=GREEN, width=1)
                current_x = bar_x + int(min(100, humidity_current) / 100.0 * bar_width)
                h_color = GREEN if h_status == "comfortable" else YELLOW if h_status == "uncomfortable" else RED
                draw.rectangle([current_x - 2, y_offset - 1, current_x + 2, y_offset + bar_height + 1], fill=h_color)
                y_offset += bar_height + 6

            # === TEMPERATURE BAR ===
            if temp_zone:
                temp_current = temp_zone["current"] or 0
                temp_ideal = temp_zone["ideal"]
                t_status = temp_zone["status"]
                t_range = temp_zone["comfortable_range"]

                draw.text((bar_x, y_offset), f"temp {temp_current:.1f}°C", fill=LIGHT_CYAN, font=font_small)
                y_offset += 12

                # Normalize temp to 10-35°C range for display
                t_min_display, t_max_display = 10, 35
                def temp_to_x(t):
                    return bar_x + int((t - t_min_display) / (t_max_display - t_min_display) * bar_width)

                draw.rectangle([bar_x, y_offset, bar_x + bar_width, y_offset + bar_height],
                              fill=DARK_GRAY, outline=(60, 60, 70))
                comfort_x1 = max(bar_x, temp_to_x(t_range[0]))
                comfort_x2 = min(bar_x + bar_width, temp_to_x(t_range[1]))
                draw.rectangle([comfort_x1, y_offset + 1, comfort_x2, y_offset + bar_height - 1],
                              fill=(25, 50, 25))

                ideal_x = temp_to_x(temp_ideal)
                draw.line([ideal_x, y_offset, ideal_x, y_offset + bar_height], fill=GREEN, width=1)
                current_x = max(bar_x, min(bar_x + bar_width, temp_to_x(temp_current)))
                t_color = GREEN if t_status == "comfortable" else YELLOW if t_status == "uncomfortable" else RED
                draw.rectangle([current_x - 2, y_offset - 1, current_x + 2, y_offset + bar_height + 1], fill=t_color)
                y_offset += bar_height + 6

            # === WARMTH (Internal State) ===
            # Uses same visual style as sensor bars: comfort zone + ideal + marker
            warmth = anima.warmth
            warmth_color = ORANGE if warmth > 0.6 else CYAN if warmth < 0.3 else YELLOW
            draw.text((bar_x, y_offset), f"warmth {warmth:.0%}", fill=LIGHT_CYAN, font=font_small)
            y_offset += 12

            # Background
            draw.rectangle([bar_x, y_offset, bar_x + bar_width, y_offset + bar_height],
                          fill=DARK_GRAY, outline=(60, 60, 70))
            # Comfort zone (0.3 - 0.7 is comfortable for internal states)
            comfort_x1 = bar_x + int(0.3 * bar_width)
            comfort_x2 = bar_x + int(0.7 * bar_width)
            draw.rectangle([comfort_x1, y_offset + 1, comfort_x2, y_offset + bar_height - 1],
                          fill=(25, 50, 25))
            # Ideal line at 0.5
            ideal_x = bar_x + int(0.5 * bar_width)
            draw.line([ideal_x, y_offset, ideal_x, y_offset + bar_height], fill=GREEN, width=1)
            # Current marker
            current_x = bar_x + int(warmth * bar_width)
            draw.rectangle([current_x - 2, y_offset - 1, current_x + 2, y_offset + bar_height + 1], fill=warmth_color)
            y_offset += bar_height + 6

            # === STABILITY (Internal State) ===
            # Uses same visual style as sensor bars: comfort zone + ideal + marker
            stability = anima.stability
            stab_color = GREEN if stability > 0.6 else YELLOW if stability > 0.3 else RED
            draw.text((bar_x, y_offset), f"stability {stability:.0%}", fill=LIGHT_CYAN, font=font_small)
            y_offset += 12

            # Background
            draw.rectangle([bar_x, y_offset, bar_x + bar_width, y_offset + bar_height],
                          fill=DARK_GRAY, outline=(60, 60, 70))
            # Comfort zone (0.5 - 1.0 is comfortable for stability - higher is better)
            comfort_x1 = bar_x + int(0.5 * bar_width)
            comfort_x2 = bar_x + int(1.0 * bar_width)
            draw.rectangle([comfort_x1, y_offset + 1, comfort_x2, y_offset + bar_height - 1],
                          fill=(25, 50, 25))
            # Ideal line at 0.8 (high stability is ideal)
            ideal_x = bar_x + int(0.8 * bar_width)
            draw.line([ideal_x, y_offset, ideal_x, y_offset + bar_height], fill=GREEN, width=1)
            # Current marker
            current_x = bar_x + int(stability * bar_width)
            draw.rectangle([current_x - 2, y_offset - 1, current_x + 2, y_offset + bar_height + 1], fill=stab_color)
            y_offset += bar_height + 8

            # === INSIGHT TEXT ===
            # Show contextual message based on actual conditions
            mood = anima.feeling().get("mood", "neutral")
            insight_lines = []

            if mood == "stressed":
                # Explain why stressed - only temperature matters for Pi
                if readings.ambient_temp_c and readings.ambient_temp_c > 38:
                    insight_lines.append(f"temp {readings.ambient_temp_c:.0f}°C > 38°C limit")
                    insight_lines.append("seeking cooler conditions")
                elif readings.ambient_temp_c and readings.ambient_temp_c < 10:
                    insight_lines.append(f"temp {readings.ambient_temp_c:.0f}°C < 10°C limit")
                    insight_lines.append("seeking warmer conditions")
                else:
                    insight_lines.append("stability or presence low")
                    insight_lines.append("system resources strained")
            elif mood == "overheated":
                insight_lines.append(f"warmth {anima.warmth:.0%} is high")
                insight_lines.append("system running hot")
            else:
                # Show learning insights if available
                insights = summary.get("why_feels_cold", [])
                if insights:
                    title = insights[0].get("title", "")
                    # Wrap long titles across 2 lines
                    if len(title) > 28:
                        insight_lines.append(title[:28])
                        insight_lines.append(title[28:56])
                    else:
                        insight_lines.append(title)
                else:
                    insight_lines.append("learning from environment...")

            # Draw insight lines
            for i, line in enumerate(insight_lines[:3]):
                color = PURPLE if mood not in ("stressed", "overheated") else ORANGE
                draw.text((bar_x, y_offset + i * 12), line, fill=color, font=font_small)

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

    def _wrap_text(self, text: str, font, max_width: int) -> list:
        """Wrap text to fit within max_width pixels. Returns list of lines."""
        # Use cached draw context for measurement (avoids creating PIL Image every call)
        temp_draw = self._get_measure_draw()

        words = text.split()
        lines = []
        current_line = ""

        for word in words:
            test_line = current_line + (" " if current_line else "") + word
            try:
                bbox = temp_draw.textbbox((0, 0), test_line, font=font)
                width = bbox[2] - bbox[0]
            except Exception:
                # Fallback: estimate ~7 pixels per character
                width = len(test_line) * 7

            if width > max_width and current_line:
                lines.append(current_line)
                current_line = word
            else:
                current_line = test_line

        if current_line:
            lines.append(current_line)

        return lines

    def _render_messages(self):
        """Render message board - Lumen's voice and observations. Interactive scrolling and expansion."""
        try:
            from ..messages import get_recent_messages, MESSAGE_TYPE_USER, MESSAGE_TYPE_OBSERVATION, MESSAGE_TYPE_AGENT, MESSAGE_TYPE_QUESTION

            # Get messages for cache check and rendering
            all_messages = get_recent_messages(50)
            scroll_idx = self._state.message_scroll_index
            expanded_id = self._state.message_expanded_id

            # Check image cache - text rendering is expensive (~500ms)
            cache_hash = self._get_messages_cache_hash(all_messages, scroll_idx, expanded_id)
            if self._messages_cache_image is not None and self._messages_cache_hash == cache_hash:
                # Cache hit - use cached image directly (saves ~500ms)
                if hasattr(self._display, '_image'):
                    self._display._image = self._messages_cache_image
                if hasattr(self._display, '_show'):
                    self._display._show()
                return

            # Cache miss - log why (for debugging slow renders)
            if self._messages_cache_image is None:
                print("[Messages] Cache miss: no cached image", file=sys.stderr, flush=True)
            else:
                print(f"[Messages] Cache miss: hash changed", file=sys.stderr, flush=True)

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

            # Color definitions - BOLD and HIGH CONTRAST for readability
            CYAN = (0, 255, 255)        # Pure cyan for title
            AMBER = (255, 200, 60)      # Brighter amber for agent messages
            LIME = (100, 255, 100)      # Vivid lime for user messages
            VIOLET = (200, 150, 255)    # Brighter violet for Lumen prefixes
            SOFT_GOLD = (255, 245, 150) # Brighter gold for Lumen's observations
            CORAL = (255, 150, 130)     # Brighter coral for feelings
            PEACH = (255, 220, 180)     # Brighter peach for reflections
            SKY = (140, 220, 255)       # Brighter sky blue for questions
            SAGE = (160, 255, 160)      # Brighter sage green for growth
            MUTED = (160, 180, 200)     # Brighter muted for timestamps
            DARK_BG = (12, 16, 24)      # Deeper background for contrast
            SELECTED_BG = (30, 50, 80)  # Selection highlight
            BORDER = (100, 180, 220)    # Bold border

            # Use cached fonts (loading from disk is slow)
            # Larger fonts for readability - user reported text was hard to read
            fonts = self._get_fonts()
            font = fonts['medium']  # 13px for general text (was 11px)
            font_small = fonts['small']  # 11px for message text (was 9px micro - too small!)
            font_title = fonts['default']  # 14px title (was 12px)

            y_offset = 6

            # Minimal title
            draw.text((10, y_offset), "messages", fill=CYAN, font=font_title)
            y_offset += 18

            # all_messages already fetched at start for cache check
            if not all_messages:
                # Empty state - centered, honest
                draw.text((60, 100), "nothing yet", fill=MUTED, font=font)
                draw.text((70, 118), "be patient", fill=MUTED, font=font_small)
            else:
                # Clamp scroll index (scroll_idx already from cache check)
                scroll_idx = max(0, min(scroll_idx, len(all_messages) - 1))
                self._state.message_scroll_index = scroll_idx

                # Check if any message is expanded
                has_expanded = self._state.message_expanded_id is not None

                # Show fewer messages when one is expanded to make room for more lines
                if has_expanded:
                    # When expanded, show only the selected message (full focus)
                    start_idx = scroll_idx
                    end_idx = scroll_idx + 1
                    visible_messages = all_messages[start_idx:end_idx]
                    selected_in_visible = 0
                else:
                    # Normal view: 5 visible (tighter spacing)
                    start_idx = max(0, scroll_idx - 2)
                    end_idx = min(len(all_messages), start_idx + 5)
                    visible_messages = all_messages[start_idx:end_idx]
                    selected_in_visible = scroll_idx - start_idx

                max_y = 210
                msg_padding = 4
                content_width = 200  # Width for text wrapping

                for i, msg in enumerate(visible_messages):
                    if y_offset > max_y:
                        break

                    is_selected = (i == selected_in_visible)
                    is_expanded = (self._state.message_expanded_id == msg.message_id)
                    answer_msg = None  # For Q&A threading

                    # Style by message type - vibrant colors for visibility
                    if msg.msg_type == MESSAGE_TYPE_USER:
                        prefix = "●"
                        text_color = LIME        # Bright lime for user
                        prefix_color = LIME
                        display_text = msg.text
                        author_text = "you"
                    elif msg.msg_type == MESSAGE_TYPE_AGENT:
                        prefix = "◆"
                        text_color = AMBER       # Warm amber for agents
                        prefix_color = AMBER
                        author = getattr(msg, 'author', 'agent')
                        # Truncate long author names
                        author_text = author[:12] if len(author) > 12 else author
                        display_text = msg.text
                    elif msg.msg_type == MESSAGE_TYPE_QUESTION:
                        # Lumen's questions - reaching out for understanding
                        prefix = "?"
                        prefix_color = CYAN      # Bright cyan for questions
                        text_color = CYAN        # Questions stand out
                        display_text = msg.text
                        # Show if answered
                        answered = getattr(msg, 'answered', False)
                        author_text = "answered" if answered else "wondering"
                        # Find the answer if it exists (for threading)
                        answer_msg = None
                        if answered:
                            for m in all_messages:
                                if getattr(m, 'responds_to', None) == msg.message_id:
                                    answer_msg = m
                                    break
                    else:  # MESSAGE_TYPE_OBSERVATION (Lumen)
                        prefix = "▸"
                        prefix_color = VIOLET    # Soft violet prefix
                        display_text = msg.text
                        author_text = None  # Lumen's own words, no author needed
                        # Color Lumen's observations by mood/content (using pre-compiled sets)
                        text_words = set(display_text.lower().split())
                        if text_words & self._FEELING_WORDS:
                            text_color = CORAL      # Warm coral for feelings
                        elif text_words & self._CURIOSITY_WORDS:
                            text_color = SKY        # Sky blue for curiosity
                        elif text_words & self._GROWTH_WORDS:
                            text_color = SAGE       # Sage green for growth
                        elif text_words & self._CALM_WORDS:
                            text_color = PEACH      # Soft peach for calm
                        else:
                            text_color = SOFT_GOLD  # Default warm gold

                    # Only wrap text when expanded (optimization: _wrap_text is slow)
                    line_height = 14
                    msg_padding = 4
                    if is_expanded:
                        wrapped_lines = self._wrap_text(display_text, font_small, content_width)
                        # Calculate how many lines can fit on screen
                        # Use y_offset + padding + author line height as starting point
                        start_y = y_offset + msg_padding + (12 if author_text else 0)
                        available_height = max_y - start_y
                        max_visible_lines = max(1, available_height // line_height)
                        # Use text scroll offset for this expanded message
                        text_scroll = self._state.message_text_scroll
                        max_scroll = max(0, len(wrapped_lines) - max_visible_lines)
                        text_scroll = min(text_scroll, max_scroll)
                        self._state.message_text_scroll = text_scroll
                        num_lines = min(len(wrapped_lines), max_visible_lines)
                    else:
                        wrapped_lines = None  # Don't wrap - just truncate
                        num_lines = 1
                        text_scroll = 0

                    msg_height = (num_lines * line_height) + (msg_padding * 2) + (12 if author_text else 0)

                    # Draw message container
                    if is_selected:
                        draw.rectangle([6, y_offset, 234, y_offset + msg_height],
                                      fill=SELECTED_BG, outline=BORDER, width=1)
                    else:
                        draw.rectangle([6, y_offset, 234, y_offset + msg_height],
                                      fill=DARK_BG)

                    inner_y = y_offset + msg_padding

                    # Author line (if present) with age
                    if author_text:
                        draw.text((12, inner_y), f"{prefix} {author_text}", fill=prefix_color, font=font_small)
                        age = msg.age_str()
                        draw.text((200, inner_y), age, fill=MUTED, font=font_small)
                        inner_y += 12

                    # Message text
                    if is_expanded and wrapped_lines:
                        # Show multiple wrapped lines with scrolling support
                        available_height = max_y - inner_y
                        max_visible_lines = max(1, available_height // line_height)
                        text_scroll = self._state.message_text_scroll
                        max_scroll = max(0, len(wrapped_lines) - max_visible_lines)
                        text_scroll = min(text_scroll, max_scroll)
                        self._state.message_text_scroll = text_scroll
                        
                        # Show visible lines starting from scroll offset
                        visible_lines = wrapped_lines[text_scroll:text_scroll + max_visible_lines]
                        for line in visible_lines:
                            if inner_y > max_y:
                                break
                            draw.text((12, inner_y), line, fill=text_color, font=font_small)
                            inner_y += line_height
                        
                        # Show scroll indicators if there's more content
                        if len(wrapped_lines) > max_visible_lines:
                            if text_scroll > 0:
                                draw.text((220, inner_y - max_visible_lines * line_height + 2), "▲", fill=MUTED, font=font_small)
                            if text_scroll < max_scroll:
                                draw.text((220, inner_y - line_height), "▼", fill=MUTED, font=font_small)
                            # Show scroll position indicator
                            scroll_info = f"{text_scroll + 1}-{min(text_scroll + max_visible_lines, len(wrapped_lines))}/{len(wrapped_lines)}"
                            draw.text((140, max_y - 10), scroll_info, fill=MUTED, font=font_small)
                    else:
                        # Single line, truncated directly (no _wrap_text call - faster)
                        first_line = display_text[:28] + "..." if len(display_text) > 28 else display_text
                        # For Lumen's observations, show prefix inline
                        if not author_text:
                            draw.text((12, inner_y), f"{prefix} {first_line}", fill=text_color, font=font_small)
                            age = msg.age_str()
                            draw.text((200, inner_y), age, fill=MUTED, font=font_small)
                        else:
                            draw.text((12, inner_y), first_line, fill=text_color, font=font_small)
                        inner_y += line_height

                    y_offset += msg_height + 3  # Gap between messages

                    # Q&A Threading: Show answer inline after question
                    if msg.msg_type == MESSAGE_TYPE_QUESTION and answer_msg is not None:
                        if y_offset < max_y - 30:  # Room for answer
                            # Draw connector line
                            draw.line([(18, y_offset - 2), (18, y_offset + 8)], fill=AMBER, width=1)
                            draw.line([(18, y_offset + 8), (24, y_offset + 8)], fill=AMBER, width=1)

                            # Answer text (indented)
                            ans_author = getattr(answer_msg, 'author', 'agent')[:8]
                            ans_text = answer_msg.text[:35] + "..." if len(answer_msg.text) > 35 else answer_msg.text
                            draw.text((26, y_offset + 2), f"↳ {ans_author}:", fill=AMBER, font=font_small)
                            draw.text((26, y_offset + 14), ans_text, fill=(220, 200, 160), font=font_small)
                            y_offset += 30
                        answer_msg = None  # Reset for next message

                # Scroll indicator - visual bar on right edge
                if len(all_messages) > 5:
                    bar_height = 180
                    bar_top = 30
                    thumb_size = max(20, bar_height // len(all_messages) * 5)
                    thumb_pos = bar_top + int((scroll_idx / max(1, len(all_messages) - 1)) * (bar_height - thumb_size))

                    # Track
                    draw.rectangle([236, bar_top, 238, bar_top + bar_height], fill=DARK_BG)
                    # Thumb
                    draw.rectangle([236, thumb_pos, 238, thumb_pos + thumb_size], fill=MUTED)

                # Bottom status (y=218 to avoid dot overlap)
                draw.text((10, 218), f"{scroll_idx + 1}/{len(all_messages)}", fill=MUTED, font=font_small)
                hint = "▼ expand" if not self._state.message_expanded_id else "▼ collapse"
                draw.text((100, 218), hint, fill=MUTED, font=font_small)

            # Screen indicator dots
            self._draw_screen_indicator(draw, ScreenMode.MESSAGES)

            # Cache the rendered image for fast subsequent renders
            self._messages_cache_image = image
            self._messages_cache_hash = cache_hash

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

    def _render_questions(self):
        """Render Questions screen - Lumen's questions and answers."""
        # Use the proper Q&A renderer instead of filtered messages
        try:
            self._render_qa_legacy()
        except Exception as e:
            import traceback
            print(f"[Questions Screen] Error in _render_qa_legacy: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            # Fallback: show error message
            try:
                self._display.render_text("Q&A\n\nError\nrendering", (10, 10))
            except Exception:
                pass

    def _render_visitors(self):
        """Render Visitors screen - messages from agents and humans."""
        # Note: "user" is the actual msg_type for human messages (not "human")
        self._render_filtered_messages("visitors", ["agent", "user"], include_answers=False)

    def _render_filtered_messages(self, title: str, filter_types: list, include_answers: bool):
        """Render a filtered message screen."""
        try:
            from ..messages import get_board, MESSAGE_TYPE_USER, MESSAGE_TYPE_AGENT, MESSAGE_TYPE_QUESTION

            if hasattr(self._display, '_create_canvas'):
                image, draw = self._display._create_canvas((0, 0, 0))
            else:
                self._display.render_text(f"{title.upper()}\n\nNo display", (10, 10))
                return

            # Colors
            CYAN = (80, 220, 255)
            AMBER = (255, 180, 60)
            GREEN = (100, 220, 140)
            MUTED = (140, 160, 180)
            SOFT_WHITE = (220, 220, 230)

            fonts = self._get_fonts()
            font = fonts['medium']
            font_small = fonts['small']
            font_title = fonts['default']

            # Get filtered messages
            board = get_board()
            board._load()
            all_messages = board._messages

            # Filter by type - map string types to message type constants
            type_map = {
                "question": MESSAGE_TYPE_QUESTION,
                "agent": MESSAGE_TYPE_AGENT,
                "user": MESSAGE_TYPE_USER
            }
            filter_type_constants = [type_map.get(t, t) for t in filter_types]
            
            # Filter by type
            # If include_answers, also include agent messages with responds_to (those are answers to questions)
            if include_answers:
                filtered = [m for m in all_messages
                           if m.msg_type in filter_type_constants
                           or (m.msg_type == MESSAGE_TYPE_AGENT and getattr(m, 'responds_to', None))]
            else:
                filtered = [m for m in all_messages if m.msg_type in filter_type_constants]
            filtered = list(reversed(filtered))  # Newest first

            y_offset = 6

            # Title with count
            draw.text((10, y_offset), f"{title} ({len(filtered)})", fill=CYAN, font=font_title)
            y_offset += 22
            
            # Determine mode for later use
            mode = ScreenMode.QUESTIONS if "question" in filter_types else ScreenMode.VISITORS

            if not filtered:
                draw.text((60, 100), f"no {title} yet", fill=MUTED, font=font)
            else:
                # Show messages with scroll support
                # Use message_scroll_index for visitors screen too
                scroll_idx = getattr(self._state, 'message_scroll_index', 0)
                scroll_idx = max(0, min(scroll_idx, len(filtered) - 1))
                self._state.message_scroll_index = scroll_idx

                # Check if any message is expanded
                expanded_id = getattr(self._state, 'message_expanded_id', None)
                has_expanded = expanded_id is not None

                # Calculate visible window - selected message should always be visible
                if has_expanded:
                    # When expanded, only show the expanded message
                    visible_count = 1
                    start_idx = scroll_idx
                else:
                    # Normal view: show 4 messages with selected in view
                    visible_count = 4
                    # Keep selected message visible by centering it when possible
                    start_idx = max(0, min(scroll_idx, len(filtered) - visible_count))

                for i, msg in enumerate(filtered[start_idx:start_idx + visible_count]):
                    # Message at scroll_idx is selected
                    is_selected = (start_idx + i == scroll_idx)
                    is_expanded = (expanded_id == msg.message_id)

                    # Type indicator color
                    if msg.msg_type == MESSAGE_TYPE_QUESTION:
                        type_color = CYAN
                    elif msg.msg_type == MESSAGE_TYPE_AGENT and getattr(msg, 'responds_to', None):
                        # Agent message that answers a question
                        type_color = AMBER
                    elif msg.msg_type in [MESSAGE_TYPE_AGENT, MESSAGE_TYPE_USER]:
                        type_color = GREEN
                    else:
                        type_color = MUTED

                    # Author/type
                    author = getattr(msg, 'author', msg.msg_type)

                    if is_expanded:
                        # EXPANDED VIEW for selected message - show full text with scrolling
                        max_y = 210
                        content_width = 200
                        wrapped_lines = self._wrap_text(msg.text, font_small, content_width)
                        
                        # Calculate how many lines can fit
                        available_height = max_y - y_offset - 20  # Leave room for author/timestamp
                        max_visible_lines = max(1, available_height // 12)
                        
                        # Use text scroll offset
                        text_scroll = getattr(self._state, 'message_text_scroll', 0)
                        max_scroll = max(0, len(wrapped_lines) - max_visible_lines)
                        text_scroll = min(text_scroll, max_scroll)
                        self._state.message_text_scroll = text_scroll
                        
                        # Calculate box height
                        visible_lines = min(len(wrapped_lines), max_visible_lines)
                        box_height = 18 + visible_lines * 12 + 8

                        # Background
                        draw.rectangle([5, y_offset - 2, 235, y_offset + box_height], fill=(35, 55, 85))

                        # Author
                        draw.text((10, y_offset), f"{author}:", fill=type_color, font=font_small)

                        # Timestamp next to author
                        if hasattr(msg, 'timestamp'):
                            from datetime import datetime
                            if isinstance(msg.timestamp, (int, float)):
                                ts = datetime.fromtimestamp(msg.timestamp).strftime("%H:%M")
                            else:
                                ts = str(msg.timestamp)[11:16]
                            draw.text((180, y_offset), ts, fill=MUTED, font=font_small)

                        y_offset += 14

                        # Show visible lines with scroll
                        visible_lines_list = wrapped_lines[text_scroll:text_scroll + max_visible_lines]
                        for line in visible_lines_list:
                            if y_offset > max_y - 10:
                                break
                            draw.text((10, y_offset), line, fill=SOFT_WHITE, font=font_small)
                            y_offset += 12
                        
                        # Show scroll indicators if there's more content
                        if len(wrapped_lines) > max_visible_lines:
                            if text_scroll > 0:
                                draw.text((220, y_offset - max_visible_lines * 12 + 2), "▲", fill=MUTED, font=font_small)
                            if text_scroll < max_scroll:
                                draw.text((220, y_offset - 12), "▼", fill=MUTED, font=font_small)
                            # Show scroll position
                            scroll_info = f"{text_scroll + 1}-{min(text_scroll + max_visible_lines, len(wrapped_lines))}/{len(wrapped_lines)}"
                            draw.text((140, max_y - 10), scroll_info, fill=MUTED, font=font_small)

                        y_offset += 8
                    elif is_selected:
                        # SELECTED but not expanded - show preview with highlight
                        # Selection background
                        draw.rectangle([5, y_offset - 2, 235, y_offset + 32], fill=(30, 50, 80), outline=(80, 140, 200), width=1)

                        draw.text((10, y_offset), f"{author}:", fill=type_color, font=font_small)
                        y_offset += 14

                        # Truncated text preview
                        text = msg.text[:45] + "..." if len(msg.text) > 45 else msg.text
                        draw.text((10, y_offset), text, fill=(220, 220, 230), font=font_small)
                        y_offset += 22
                    else:
                        # COMPACT VIEW for non-selected messages
                        draw.text((10, y_offset), f"{author}:", fill=type_color, font=font_small)
                        y_offset += 12

                        # Truncated text
                        text = msg.text[:50] + "..." if len(msg.text) > 50 else msg.text
                        draw.text((10, y_offset), text, fill=MUTED, font=font_small)
                        y_offset += 18

                # Scroll indicator
                if len(filtered) > visible_count:
                    draw.text((200, 220), f"{scroll_idx + 1}/{len(filtered)}", fill=MUTED, font=font_small)
                
                # Expansion hint - show appropriate action
                expanded_id = getattr(self._state, 'message_expanded_id', None)
                hint = "▼ expand" if not expanded_id else "▼ collapse"
                draw.text((100, 220), hint, fill=MUTED, font=font_small)

            # Screen indicator
            self._draw_screen_indicator(draw, mode)

            # Always update display - ensure image is set and shown
            if hasattr(self._display, '_image'):
                self._display._image = image
            if hasattr(self._display, '_show'):
                self._display._show()
            elif hasattr(self._display, 'render_image'):
                self._display.render_image(image)
            else:
                print(f"[ScreenRenderer] Display has no _show or render_image method for {title}", file=sys.stderr, flush=True)

        except Exception as e:
            import traceback
            print(f"[ScreenRenderer] Error rendering {title}: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            try:
                self._display.render_text(f"{title.upper()}\n\nError", (10, 10))
            except Exception as e2:
                print(f"[ScreenRenderer] Even error fallback failed for {title}: {e2}", file=sys.stderr, flush=True)
                try:
                    self._display.show_default()
                except Exception:
                    pass

    def _render_qa_legacy(self):
        """Render Q&A screen - Lumen's questions and agent answers with full threading (legacy)."""
        try:
            from ..messages import get_board, MESSAGE_TYPE_QUESTION, MESSAGE_TYPE_AGENT

            if not hasattr(self._display, '_create_canvas'):
                self._display.render_text("Q&A\n\nNo display", (10, 10))
                return
            
            image, draw = self._display._create_canvas((0, 0, 0))
            if image is None or draw is None:
                print("[QA Screen] Failed to create canvas", file=sys.stderr, flush=True)
                self._display.render_text("Q&A\n\nCanvas error", (10, 10))
                return

            # Colors
            CYAN = (80, 220, 255)       # Questions
            AMBER = (255, 180, 60)      # Answers
            MUTED = (140, 160, 180)     # Meta text
            DARK_BG = (15, 20, 30)
            SELECTED_BG = (35, 55, 85)
            FOCUSED_BG = (50, 75, 110)  # Brighter when focused
            FOCUSED_BORDER = (120, 180, 255)  # Bright cyan border when focused
            BORDER = (80, 140, 180)
            SOFT_WHITE = (220, 220, 230)

            fonts = self._get_fonts()
            font = fonts['medium']
            font_small = fonts['small']
            font_title = fonts['default']

            # Get all questions with their answers
            board = get_board()
            board._load()
            all_messages = board._messages

            # Build Q&A pairs
            questions = [m for m in all_messages if m.msg_type == MESSAGE_TYPE_QUESTION]
            qa_pairs = []
            for q in questions:
                # Find answer
                answer = None
                for m in all_messages:
                    if getattr(m, 'responds_to', None) == q.message_id:
                        answer = m
                        break
                qa_pairs.append((q, answer))

            # Reverse to show newest first
            qa_pairs = list(reversed(qa_pairs))

            y_offset = 6

            # Title with count - separate waiting (active) from expired
            # q.answered=True means expired, a is None means no actual response
            waiting = sum(1 for q, a in qa_pairs if a is None and not q.answered)
            expired = sum(1 for q, a in qa_pairs if a is None and q.answered)
            if waiting and expired:
                title = f"questions ({waiting} waiting, {expired} expired)"
            elif waiting:
                title = f"questions ({waiting} waiting)"
            elif expired:
                title = f"questions ({expired} expired)"
            else:
                title = "questions"
            draw.text((10, y_offset), title, fill=CYAN, font=font_title)
            y_offset += 20

            if not qa_pairs:
                draw.text((60, 100), "no questions yet", fill=MUTED, font=font)
                draw.text((50, 118), "lumen is still learning", fill=MUTED, font=font_small)
            else:
                # Clamp scroll index
                scroll_idx = max(0, min(self._state.qa_scroll_index, len(qa_pairs) - 1))
                self._state.qa_scroll_index = scroll_idx

                is_expanded = self._state.qa_expanded
                is_full_view = self._state.qa_full_view
                max_y = 205

                if is_full_view:
                    # FULL VIEW: Answer takes entire screen for maximum readability
                    q, answer = qa_pairs[scroll_idx]
                    text_scroll = self._state.qa_text_scroll

                    if answer:
                        # Compact question header (2 lines max)
                        draw.rectangle([6, y_offset, 234, y_offset + 20], fill=DARK_BG, outline=BORDER)
                        draw.text((12, y_offset + 4), "Q:", fill=CYAN, font=font_small)
                        q_preview = q.text[:50] + "..." if len(q.text) > 50 else q.text
                        draw.text((26, y_offset + 4), q_preview, fill=MUTED, font=font_small)
                        y_offset += 22

                        # Full-screen answer area with better highlighting
                        a_lines = self._wrap_text(answer.text, font_small, 220)
                        a_max_lines = 15  # Increased to show more lines
                        max_scroll = max(0, len(a_lines) - a_max_lines)
                        text_scroll = min(text_scroll, max_scroll)
                        self._state.qa_text_scroll = text_scroll

                        # Answer header with brighter background
                        author = getattr(answer, 'author', 'agent')
                        draw.rectangle([6, y_offset, 234, y_offset + 185], fill=FOCUSED_BG, outline=FOCUSED_BORDER, width=2)
                        draw.text((12, y_offset + 4), f"↳ {author} responds:", fill=AMBER, font=font_small)
                        draw.text((160, y_offset + 4), f"{len(a_lines)} lines", fill=MUTED, font=font_small)

                        # Show answer lines with scroll
                        a_y = y_offset + 20
                        for line in a_lines[text_scroll:text_scroll + a_max_lines]:
                            if a_y > y_offset + 180:
                                break
                            draw.text((12, a_y), line, fill=SOFT_WHITE, font=font_small)
                            a_y += 12

                        # Scroll indicators - more visible
                        if len(a_lines) > a_max_lines:
                            if text_scroll > 0:
                                draw.text((220, y_offset + 20), "▲", fill=AMBER, font=font_small)
                            if text_scroll < max_scroll:
                                draw.text((220, y_offset + 180), "▼", fill=AMBER, font=font_small)
                            # Progress indicator
                            progress = f"{text_scroll + 1}-{min(text_scroll + a_max_lines, len(a_lines))}/{len(a_lines)}"
                            draw.text((140, y_offset + 4), progress, fill=MUTED, font=font_small)
                    else:
                        # No answer - can't use full view
                        draw.rectangle([6, y_offset, 234, y_offset + 100], fill=DARK_BG, outline=BORDER)
                        draw.text((60, y_offset + 40), "no answer yet", fill=MUTED, font=font)
                        draw.text((40, y_offset + 60), "press to go back", fill=MUTED, font=font_small)

                elif is_expanded:
                    # EXPANDED VIEW: Show single Q&A pair with text scrolling
                    q, answer = qa_pairs[scroll_idx]
                    focus = self._state.qa_focus
                    text_scroll = self._state.qa_text_scroll

                    # Wrap text for both Q and A
                    q_lines = self._wrap_text(q.text, font_small, 210)
                    a_lines = self._wrap_text(answer.text, font_small, 210) if answer else []

                    # Calculate scroll limits based on focus
                    if focus == "question":
                        q_max_lines = 5  # Show 5 lines when question focused
                        max_scroll = max(0, len(q_lines) - q_max_lines)
                        text_scroll = min(text_scroll, max_scroll)
                        self._state.qa_text_scroll = text_scroll
                    elif answer:
                        # Answer focused - show more lines and allow full scroll
                        a_max_lines = 12  # Increased from 10 to show more
                        max_scroll = max(0, len(a_lines) - a_max_lines)
                        text_scroll = min(text_scroll, max_scroll)
                        self._state.qa_text_scroll = text_scroll
                    else:
                        # Answer focused but no answer yet - reset scroll
                        self._state.qa_text_scroll = 0

                    # Question section - taller when focused with better highlighting
                    q_height = 80 if focus == "question" else 45
                    q_bg = FOCUSED_BG if focus == "question" else DARK_BG
                    q_border = FOCUSED_BORDER if focus == "question" else None
                    q_border_width = 2 if focus == "question" else 0
                    draw.rectangle([6, y_offset, 234, y_offset + q_height], fill=q_bg, outline=q_border, width=q_border_width)

                    # Focus indicator
                    if focus == "question":
                        draw.text((8, y_offset + 2), "▶", fill=CYAN, font=font_small)  # Arrow indicator
                    
                    draw.text((12, y_offset + 4), "? lumen asks:", fill=CYAN, font=font_small)
                    draw.text((180, y_offset + 4), q.age_str(), fill=MUTED, font=font_small)

                    # Show question lines (with scroll when focused)
                    q_start = text_scroll if focus == "question" else 0
                    q_display_lines = q_max_lines if focus == "question" else 2
                    q_y = y_offset + 18
                    for line in q_lines[q_start:q_start + q_display_lines]:
                        if q_y > y_offset + q_height - 5:
                            break
                        draw.text((12, q_y), line, fill=SOFT_WHITE, font=font_small)
                        q_y += 13

                    # Scroll indicator for question
                    if focus == "question" and len(q_lines) > q_max_lines:
                        if text_scroll > 0:
                            draw.text((220, y_offset + 18), "▲", fill=CYAN, font=font_small)
                        if text_scroll < max_scroll:
                            draw.text((220, y_offset + q_height - 16), "▼", fill=CYAN, font=font_small)
                        # Show scroll position
                        scroll_info = f"{text_scroll + 1}-{min(text_scroll + q_max_lines, len(q_lines))}/{len(q_lines)}"
                        draw.text((140, y_offset + q_height - 12), scroll_info, fill=MUTED, font=font_small)

                    y_offset += q_height + 5

                    # Answer section - taller when focused with better highlighting
                    a_height = 155 if focus == "answer" else 60  # Increased height when focused
                    if answer:
                        a_bg = FOCUSED_BG if focus == "answer" else DARK_BG
                        a_border = FOCUSED_BORDER if focus == "answer" else None
                        a_border_width = 2 if focus == "answer" else 0
                        draw.rectangle([6, y_offset, 234, y_offset + a_height], fill=a_bg, outline=a_border, width=a_border_width)

                        # Focus indicator
                        if focus == "answer":
                            draw.text((8, y_offset + 2), "▶", fill=AMBER, font=font_small)  # Arrow indicator

                        author = getattr(answer, 'author', 'agent')
                        draw.text((12, y_offset + 4), f"↳ {author} responds:", fill=AMBER, font=font_small)
                        draw.text((180, y_offset + 4), answer.age_str(), fill=MUTED, font=font_small)

                        # Show answer lines (with scroll when focused)
                        a_start = text_scroll if focus == "answer" else 0
                        a_display_lines = a_max_lines if focus == "answer" else 3
                        a_y = y_offset + 18
                        for line in a_lines[a_start:a_start + a_display_lines]:
                            if a_y > y_offset + a_height - 5:
                                break
                            draw.text((12, a_y), line, fill=SOFT_WHITE, font=font_small)
                            a_y += 13

                        # Scroll indicator for answer - more visible
                        if focus == "answer" and len(a_lines) > a_max_lines:
                            if text_scroll > 0:
                                draw.text((220, y_offset + 18), "▲", fill=AMBER, font=font_small)
                            if text_scroll < max_scroll:
                                draw.text((220, y_offset + a_height - 16), "▼", fill=AMBER, font=font_small)
                            # Show scroll position
                            scroll_info = f"{text_scroll + 1}-{min(text_scroll + a_max_lines, len(a_lines))}/{len(a_lines)}"
                            draw.text((140, y_offset + a_height - 12), scroll_info, fill=MUTED, font=font_small)
                    else:
                        # No answer yet - show waiting message with proper highlighting
                        a_bg = FOCUSED_BG if focus == "answer" else DARK_BG
                        a_border = FOCUSED_BORDER if focus == "answer" else BORDER
                        a_border_width = 2 if focus == "answer" else 1
                        draw.rectangle([6, y_offset, 234, y_offset + 40], fill=a_bg, outline=a_border, width=a_border_width)
                        if focus == "answer":
                            draw.text((8, y_offset + 2), "▶", fill=AMBER, font=font_small)  # Arrow indicator
                        draw.text((12, y_offset + 12), "waiting for an answer...", fill=MUTED, font=font_small)
                        if focus == "answer":
                            draw.text((12, y_offset + 26), "◀▶ to focus question", fill=MUTED, font=font_small)

                else:
                    # Collapsed list view - show multiple Q&A pairs (5 visible)
                    start_idx = max(0, scroll_idx - 2)
                    end_idx = min(len(qa_pairs), start_idx + 5)
                    visible_pairs = qa_pairs[start_idx:end_idx]

                    for i, (q, answer) in enumerate(visible_pairs):
                        if y_offset > max_y:
                            break

                        is_selected = (start_idx + i == scroll_idx)
                        bg = SELECTED_BG if is_selected else DARK_BG

                        # Q&A pair container - compact
                        pair_height = 36
                        draw.rectangle([6, y_offset, 234, y_offset + pair_height], fill=bg, outline=BORDER if is_selected else None)

                        # Question preview
                        q_text = q.text[:32] + "..." if len(q.text) > 32 else q.text
                        status = "✓" if answer else "?"
                        draw.text((12, y_offset + 3), f"{status} {q_text}", fill=CYAN, font=font_small)
                        draw.text((200, y_offset + 3), q.age_str(), fill=MUTED, font=font_small)

                        # Answer preview (if exists)
                        if answer:
                            author = getattr(answer, 'author', 'agent')[:6]
                            a_text = answer.text[:30] + "..." if len(answer.text) > 30 else answer.text
                            draw.text((20, y_offset + 18), f"↳ {author}: {a_text}", fill=AMBER, font=font_small)
                        else:
                            draw.text((20, y_offset + 18), "↳ (waiting...)", fill=MUTED, font=font_small)

                        y_offset += pair_height + 2

                # Scroll indicator
                if len(qa_pairs) > 5:
                    bar_height = 160
                    bar_top = 30
                    thumb_size = max(20, bar_height // len(qa_pairs) * 5)
                    thumb_pos = bar_top + int((scroll_idx / max(1, len(qa_pairs) - 1)) * (bar_height - thumb_size))
                    draw.rectangle([236, bar_top, 238, bar_top + bar_height], fill=DARK_BG)
                    draw.rectangle([236, thumb_pos, 238, thumb_pos + thumb_size], fill=MUTED)

                # Status bar (y=218 to avoid dot overlap)
                draw.text((10, 218), f"{scroll_idx + 1}/{len(qa_pairs)}", fill=MUTED, font=font_small)
                if is_full_view:
                    hint = "▲▼ scroll text  press:back"
                elif is_expanded:
                    focus = self._state.qa_focus
                    if focus == "answer":
                        hint = "▲▼ scroll  ◀▶ Q  press:full"
                    else:
                        hint = "▲▼ scroll  ◀▶ A  press:expand"
                else:
                    hint = "press:expand  ▲▼:select"
                draw.text((80, 218), hint, fill=MUTED, font=font_small)

            # Screen indicator dots
            self._draw_screen_indicator(draw, ScreenMode.QUESTIONS)

            # Always update display - ensure image is set and shown
            if hasattr(self._display, '_image'):
                self._display._image = image
            else:
                print("[QA Screen] Display has no _image attribute", file=sys.stderr, flush=True)
            
            if hasattr(self._display, '_show'):
                self._display._show()
            elif hasattr(self._display, 'render_image'):
                self._display.render_image(image)
            else:
                print("[QA Screen] Display has no _show or render_image method", file=sys.stderr, flush=True)

        except Exception as e:
            import traceback
            print(f"[QA Screen] Error: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            try:
                self._display.render_text("Q&A\n\nError", (10, 10))
            except Exception as e2:
                print(f"[QA Screen] Even error fallback failed: {e2}", file=sys.stderr, flush=True)
                try:
                    self._display.show_default()
                except Exception:
                    pass

    def qa_scroll_up(self):
        """Scroll up in Q&A screen - scroll text when expanded/full, change Q&A when collapsed."""
        if self._state.mode != ScreenMode.QUESTIONS:
            return
        if self._state.qa_full_view or self._state.qa_expanded:
            # Scroll within text
            self._state.qa_text_scroll = max(0, self._state.qa_text_scroll - 1)
            self._state.last_user_action_time = time.time()
        else:
            # Change Q&A pair
            self._state.qa_scroll_index = max(0, self._state.qa_scroll_index - 1)
            self._state.last_user_action_time = time.time()

    def qa_scroll_down(self):
        """Scroll down in Q&A screen - scroll text when expanded/full, change Q&A when collapsed."""
        if self._state.mode != ScreenMode.QUESTIONS:
            return
        if self._state.qa_full_view or self._state.qa_expanded:
            # Scroll within text (limit will be enforced in render)
            # Don't increment beyond reasonable limit here - render will clamp it
            self._state.qa_text_scroll += 1
            self._state.last_user_action_time = time.time()
        else:
            # Change Q&A pair
            from ..messages import get_board, MESSAGE_TYPE_QUESTION
            board = get_board()
            board._load()
            num_questions = sum(1 for m in board._messages if m.msg_type == MESSAGE_TYPE_QUESTION)
            self._state.qa_scroll_index = min(num_questions - 1, self._state.qa_scroll_index + 1)
            self._state.last_user_action_time = time.time()

    def qa_toggle_expand(self):
        """Toggle Q&A expansion: collapsed -> expanded -> full_view (when answer focused) -> collapsed."""
        if self._state.mode != ScreenMode.QUESTIONS:
            return

        if self._state.qa_full_view:
            # Full view -> back to expanded
            self._state.qa_full_view = False
            self._state.qa_text_scroll = 0
        elif self._state.qa_expanded:
            if self._state.qa_focus == "answer":
                # Expanded with answer focused -> full view
                self._state.qa_full_view = True
                self._state.qa_text_scroll = 0
            else:
                # Expanded with question focused -> collapse
                self._state.qa_expanded = False
                self._state.qa_focus = "question"
                self._state.qa_text_scroll = 0
        else:
            # Collapsed -> expanded
            self._state.qa_expanded = True
            self._state.qa_focus = "question"
            self._state.qa_text_scroll = 0

    def qa_focus_next(self):
        """Switch focus between question and answer in expanded view."""
        if self._state.mode != ScreenMode.QUESTIONS:
            return
        if self._state.qa_full_view:
            # In full view, pressing left/right exits to expanded
            self._state.qa_full_view = False
            self._state.qa_focus = "answer"  # Keep focus on answer when exiting full view
            self._state.qa_text_scroll = 0
            self._state.last_user_action_time = time.time()
            return
        if not self._state.qa_expanded:
            # In collapsed view, LEFT/RIGHT does nothing (use button to expand)
            # This prevents accidentally getting trapped in expanded mode
            return
        # Toggle focus between question and answer
        self._state.qa_focus = "answer" if self._state.qa_focus == "question" else "question"
        self._state.qa_text_scroll = 0  # Reset text scroll when changing focus
        self._state.last_user_action_time = time.time()

    def message_scroll_up(self):
        """Scroll up in message board - scroll text when expanded, change message when collapsed."""
        if self._state.mode not in (ScreenMode.MESSAGES, ScreenMode.VISITORS):
            return
        
        try:
            # Get messages based on mode
            if self._state.mode == ScreenMode.MESSAGES:
                from ..messages import get_recent_messages
                messages = get_recent_messages(50)
            else:  # VISITORS
                from ..messages import get_board, MESSAGE_TYPE_USER, MESSAGE_TYPE_AGENT
                board = get_board()
                board._load()
                all_messages = board._messages
                messages = [m for m in all_messages if m.msg_type in [MESSAGE_TYPE_AGENT, MESSAGE_TYPE_USER]]
                messages = list(reversed(messages))  # Newest first
            
            if not messages:
                return
            
            # If a message is expanded, scroll within its text
            if self._state.message_expanded_id is not None:
                if self._state.message_text_scroll > 0:
                    self._state.message_text_scroll -= 1
                    self._state.last_user_action_time = time.time()
                    return
            
            # Otherwise, change selected message
            current_idx = self._state.message_scroll_index
            if current_idx < 0:
                current_idx = 0
            if current_idx >= len(messages):
                current_idx = len(messages) - 1
            
            # Scroll up (decrease index)
            new_idx = max(0, current_idx - 1)
            self._state.message_scroll_index = new_idx
            self._state.last_user_action_time = time.time()
            
            # Clear expansion and text scroll when scrolling (new message selected)
            self._state.message_expanded_id = None
            self._state.message_text_scroll = 0
        except Exception:
            pass
    
    def message_scroll_down(self):
        """Scroll down in message board - scroll text when expanded, change message when collapsed."""
        if self._state.mode not in (ScreenMode.MESSAGES, ScreenMode.VISITORS):
            return
        
        try:
            # Get messages based on mode
            if self._state.mode == ScreenMode.MESSAGES:
                from ..messages import get_recent_messages
                messages = get_recent_messages(50)
            else:  # VISITORS
                from ..messages import get_board, MESSAGE_TYPE_USER, MESSAGE_TYPE_AGENT
                board = get_board()
                board._load()
                all_messages = board._messages
                messages = [m for m in all_messages if m.msg_type in [MESSAGE_TYPE_AGENT, MESSAGE_TYPE_USER]]
                messages = list(reversed(messages))  # Newest first
            
            if not messages:
                return
            
            # If a message is expanded, scroll within its text
            if self._state.message_expanded_id is not None:
                # Calculate max scroll (will be clamped in render, but check here too)
                scroll_idx = self._state.message_scroll_index
                if scroll_idx < len(messages):
                    selected_msg = messages[scroll_idx]
                    display_text = selected_msg.text
                    wrapped_lines = self._wrap_text(display_text, self._get_fonts()['small'], 200)
                    available_height = 210 - 30  # Approximate available space
                    max_visible_lines = max(1, available_height // 14)
                    max_scroll = max(0, len(wrapped_lines) - max_visible_lines)
                    if self._state.message_text_scroll < max_scroll:
                        self._state.message_text_scroll += 1
                        self._state.last_user_action_time = time.time()
                        return
            
            # Otherwise, change selected message
            current_idx = self._state.message_scroll_index
            if current_idx < 0:
                current_idx = 0
            if current_idx >= len(messages):
                current_idx = len(messages) - 1
            
            # Scroll down (increase index)
            max_idx = len(messages) - 1
            new_idx = min(max_idx, current_idx + 1)
            self._state.message_scroll_index = new_idx
            self._state.last_user_action_time = time.time()
            
            # Clear expansion and text scroll when scrolling (new message selected)
            self._state.message_expanded_id = None
            self._state.message_text_scroll = 0
        except Exception:
            pass
    
    def message_toggle_expand(self):
        """Toggle expansion of currently selected message."""
        if self._state.mode not in (ScreenMode.MESSAGES, ScreenMode.VISITORS):
            return

        try:
            if self._state.mode == ScreenMode.MESSAGES:
                from ..messages import get_recent_messages
                messages = get_recent_messages(50)
            else:  # VISITORS
                from ..messages import get_board, MESSAGE_TYPE_USER, MESSAGE_TYPE_AGENT
                board = get_board()
                board._load()
                all_messages = board._messages
                # Filter to agent and user messages
                messages = [m for m in all_messages if m.msg_type in [MESSAGE_TYPE_AGENT, MESSAGE_TYPE_USER]]
                messages = list(reversed(messages))  # Newest first

            if not messages:
                return

            scroll_idx = self._state.message_scroll_index
            if scroll_idx < 0 or scroll_idx >= len(messages):
                return

            selected_msg = messages[scroll_idx]

            # Simple toggle: expand or collapse
            if self._state.message_expanded_id == selected_msg.message_id:
                # Collapse
                self._state.message_expanded_id = None
                self._state.message_text_scroll = 0
            else:
                # Expand
                self._state.message_expanded_id = selected_msg.message_id
                self._state.message_text_scroll = 0

            self._state.last_user_action_time = time.time()
        except Exception:
            pass

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
                fonts = self._get_fonts()
                font = fonts['giant']

                text = f"Canvas Cleared\n\nResuming in {remaining}s..."
                draw.text((40, 90), text, fill=(100, 200, 100), font=font)
                
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
                # Use cached fonts (loading from disk is slow)
                fonts = self._get_fonts()
                font = fonts['small_med']
                font_small = fonts['micro']
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

            # Draw save indicator if recently saved
            if time.time() < self._canvas.save_indicator_until:
                fonts = self._get_fonts()
                font = fonts['medium']
                # Draw "saved" badge at top-center
                text = "✓ saved"
                # Semi-transparent background for readability
                draw.rectangle([85, 5, 155, 25], fill=(20, 60, 20))
                draw.text((90, 7), text, fill=(100, 255, 100), font=font)

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
        # Full palette available: HSV-generated OR direct vibrant colors

        # VIBRANT PALETTE - sometimes Lumen picks directly from these
        VIBRANT_COLORS = [
            # Primary vibrants
            (255, 0, 0),      # Pure red
            (0, 255, 0),      # Pure green
            (0, 0, 255),      # Pure blue
            (255, 255, 0),    # Yellow
            (255, 0, 255),    # Magenta
            (0, 255, 255),    # Cyan
            # Warm spectrum
            (255, 128, 0),    # Orange
            (255, 64, 64),    # Coral
            (255, 192, 203),  # Pink
            (255, 215, 0),    # Gold
            # Cool spectrum
            (0, 191, 255),    # Deep sky blue
            (138, 43, 226),   # Blue violet
            (75, 0, 130),     # Indigo
            (0, 128, 128),    # Teal
            # Earth tones
            (139, 69, 19),    # Saddle brown
            (34, 139, 34),    # Forest green
            (210, 180, 140),  # Tan
            # Pastels
            (255, 182, 193),  # Light pink
            (173, 216, 230),  # Light blue
            (144, 238, 144),  # Light green
            (255, 255, 224),  # Light yellow
            (221, 160, 221),  # Plum
            # Deep/rich
            (128, 0, 0),      # Maroon
            (0, 100, 0),      # Dark green
            (25, 25, 112),    # Midnight blue
            (128, 0, 128),    # Purple
        ]

        # 20% chance to pick from vibrant palette directly
        # Higher presence = more likely to use vibrant colors
        use_vibrant = random.random() < (0.15 + presence * 0.15)

        if use_vibrant:
            color = random.choice(VIBRANT_COLORS)
            # Optionally adjust brightness based on stability
            if stability < 0.5 and random.random() < 0.3:
                # Dim slightly for unstable states
                color = tuple(int(c * (0.6 + stability * 0.4)) for c in color)
            hue_category = "vibrant"
        else:
            # HSV-based generation (original logic)
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
        
        # All styles always available - free expression (expanded palette)
        style_options = [
            ("freeform", center_x, center_y),  # Completely free drawing
            ("layered", center_x, center_y),
            ("gradient_circle", center_x + random.randint(-80, 80), center_y + random.randint(-80, 80)),
            ("circle", center_x + random.randint(-80, 80), center_y + random.randint(-80, 80)),
            ("spiral", center_x + random.randint(-60, 60), center_y + random.randint(-60, 60)),
            ("curve", random.randint(20, 220), random.randint(20, 220), random.randint(20, 220), random.randint(20, 220)),
            ("organic", center_x + random.randint(-60, 60), center_y + random.randint(-60, 60)),
            ("pattern", random.randint(40, 200), random.randint(40, 200)),
            ("line", random.randint(20, 220), random.randint(20, 220), random.randint(20, 220), random.randint(20, 220)),
            ("dots", random.randint(20, 220), random.randint(20, 220)),
            # NEW SHAPES - expanded creative palette
            ("rectangle", center_x + random.randint(-60, 60), center_y + random.randint(-60, 60)),
            ("triangle", center_x + random.randint(-60, 60), center_y + random.randint(-60, 60)),
            ("wave", random.randint(20, 220), random.randint(60, 180)),
            ("rings", center_x + random.randint(-40, 40), center_y + random.randint(-40, 40)),
            ("arc", center_x + random.randint(-60, 60), center_y + random.randint(-60, 60)),
            ("starburst", center_x + random.randint(-50, 50), center_y + random.randint(-50, 50)),
            ("drip", random.randint(40, 200), random.randint(20, 60)),  # Random walk/drip from top
            ("scatter", center_x, center_y),  # Scattered cluster
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
                # NEW SHAPES
                elif style_name == "rectangle":
                    w = random.randint(5, int(15 + stability * 20))
                    h = random.randint(5, int(15 + stability * 20))
                    filled = random.random() < 0.6
                    self._draw_rectangle(selected[1], selected[2], w, h, color, filled)
                    self._mood_tracker.record_drawing("rectangle", hue_category)
                elif style_name == "triangle":
                    size = random.randint(8, int(15 + clarity * 15))
                    self._draw_triangle(selected[1], selected[2], size, color)
                    self._mood_tracker.record_drawing("triangle", hue_category)
                elif style_name == "wave":
                    amplitude = int(5 + warmth * 15)
                    wavelength = int(10 + clarity * 20)
                    self._draw_wave(selected[1], selected[2], amplitude, wavelength, color)
                    self._mood_tracker.record_drawing("wave", hue_category)
                elif style_name == "rings":
                    num_rings = random.randint(2, int(3 + stability * 3))
                    max_radius = int(10 + clarity * 20)
                    self._draw_rings(selected[1], selected[2], num_rings, max_radius, color)
                    self._mood_tracker.record_drawing("rings", hue_category)
                elif style_name == "arc":
                    radius = int(10 + random.random() * 25)
                    start_angle = random.random() * 2 * math.pi
                    arc_length = random.random() * math.pi + 0.5
                    self._draw_arc(selected[1], selected[2], radius, start_angle, arc_length, color)
                    self._mood_tracker.record_drawing("arc", hue_category)
                elif style_name == "starburst":
                    num_rays = random.randint(4, int(6 + clarity * 6))
                    ray_length = int(8 + stability * 15)
                    self._draw_starburst(selected[1], selected[2], num_rays, ray_length, color)
                    self._mood_tracker.record_drawing("starburst", hue_category)
                elif style_name == "drip":
                    length = int(20 + warmth * 60)
                    self._draw_drip(selected[1], selected[2], length, color, stability)
                    self._mood_tracker.record_drawing("drip", hue_category)
                elif style_name == "scatter":
                    num_particles = int(5 + clarity * 15)
                    spread = int(20 + stability * 40)
                    self._draw_scatter(selected[1], selected[2], num_particles, spread, color)
                    self._mood_tracker.record_drawing("scatter", hue_category)
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
        """Update Lumen's drawing phase based on canvas state and anima.

        Phases progress SEQUENTIALLY based on BOTH pixel count AND time:
        - exploring → building → reflecting → resting

        Each phase requires: (1) enough pixels AND (2) minimum time in current phase.
        Phases never skip - must progress through each one.
        """
        import time
        now = time.time()
        phase_duration = now - self._canvas.phase_start_time
        pixel_count = len(self._canvas.pixels)
        current_phase = self._canvas.drawing_phase

        def transition_to(new_phase: str):
            """Helper to transition phase with logging."""
            if self._canvas.drawing_phase != new_phase:
                old_phase = self._canvas.drawing_phase
                self._canvas.drawing_phase = new_phase
                self._canvas.phase_start_time = now
                print(f"[Canvas] Phase: {old_phase} → {new_phase} ({pixel_count} pixels, {phase_duration:.0f}s in {old_phase})", file=sys.stderr, flush=True)

        # Reset to exploring if canvas is nearly empty (after clear)
        if pixel_count < 500:
            transition_to("exploring")
            return

        # Phase progression is SEQUENTIAL - check in order
        if current_phase == "exploring":
            # Progress to building: 1000+ pixels AND 30s exploring
            if pixel_count >= 1000 and phase_duration > 30:
                transition_to("building")

        elif current_phase == "building":
            # Progress to reflecting: 3000+ pixels AND 60s building
            if pixel_count >= 3000 and phase_duration > 60:
                transition_to("reflecting")

        elif current_phase == "reflecting":
            # Progress to resting: 5000+ pixels AND 90s reflecting
            if pixel_count >= 5000 and phase_duration > 90:
                transition_to("resting")

        elif current_phase == "resting":
            # Stay in resting - this is the final phase before save/clear
            pass

        else:
            # Unknown phase - reset to exploring
            transition_to("exploring")
    
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
    
    # === NEW SHAPE DRAWING METHODS ===

    def _draw_rectangle(self, cx: int, cy: int, width: int, height: int,
                        color: Tuple[int, int, int], filled: bool = True):
        """Draw a rectangle (filled or outline)."""
        x1, y1 = cx - width // 2, cy - height // 2
        x2, y2 = cx + width // 2, cy + height // 2

        if filled:
            for x in range(max(0, x1), min(240, x2 + 1)):
                for y in range(max(0, y1), min(240, y2 + 1)):
                    self._canvas.draw_pixel(x, y, color)
        else:
            # Draw outline only
            for x in range(max(0, x1), min(240, x2 + 1)):
                if 0 <= y1 < 240:
                    self._canvas.draw_pixel(x, y1, color)
                if 0 <= y2 < 240:
                    self._canvas.draw_pixel(x, y2, color)
            for y in range(max(0, y1), min(240, y2 + 1)):
                if 0 <= x1 < 240:
                    self._canvas.draw_pixel(x1, y, color)
                if 0 <= x2 < 240:
                    self._canvas.draw_pixel(x2, y, color)

    def _draw_triangle(self, cx: int, cy: int, size: int, color: Tuple[int, int, int]):
        """Draw a filled triangle pointing up."""
        import math
        # Three vertices of equilateral triangle
        for y_offset in range(size):
            # Width at this height
            width_at_y = int((y_offset / size) * size)
            y = cy + y_offset - size // 2
            for x_offset in range(-width_at_y // 2, width_at_y // 2 + 1):
                x = cx + x_offset
                if 0 <= x < 240 and 0 <= y < 240:
                    self._canvas.draw_pixel(x, y, color)

    def _draw_wave(self, start_x: int, y_center: int, amplitude: int,
                   wavelength: int, color: Tuple[int, int, int]):
        """Draw a horizontal sine wave."""
        import math
        for x in range(max(0, start_x), min(240, start_x + 100)):
            y = int(y_center + amplitude * math.sin((x - start_x) * 2 * math.pi / wavelength))
            if 0 <= y < 240:
                self._canvas.draw_pixel(x, y, color)
                # Make wave thicker
                if 0 <= y + 1 < 240:
                    self._canvas.draw_pixel(x, y + 1, color)

    def _draw_rings(self, cx: int, cy: int, num_rings: int, max_radius: int,
                    color: Tuple[int, int, int]):
        """Draw concentric rings."""
        import math
        for ring in range(1, num_rings + 1):
            radius = int(ring * max_radius / num_rings)
            # Draw circle outline
            for angle in range(0, 360, 3):  # Every 3 degrees
                rad = math.radians(angle)
                x = int(cx + radius * math.cos(rad))
                y = int(cy + radius * math.sin(rad))
                if 0 <= x < 240 and 0 <= y < 240:
                    self._canvas.draw_pixel(x, y, color)

    def _draw_arc(self, cx: int, cy: int, radius: int, start_angle: float,
                  arc_length: float, color: Tuple[int, int, int]):
        """Draw an arc (partial circle)."""
        import math
        steps = int(arc_length * radius / 2)  # More steps for larger arcs
        for i in range(max(1, steps)):
            angle = start_angle + (i / max(1, steps)) * arc_length
            x = int(cx + radius * math.cos(angle))
            y = int(cy + radius * math.sin(angle))
            if 0 <= x < 240 and 0 <= y < 240:
                self._canvas.draw_pixel(x, y, color)

    def _draw_starburst(self, cx: int, cy: int, num_rays: int, ray_length: int,
                        color: Tuple[int, int, int]):
        """Draw a starburst pattern - rays emanating from center."""
        import math
        for i in range(num_rays):
            angle = (i / num_rays) * 2 * math.pi
            for r in range(1, ray_length + 1):
                x = int(cx + r * math.cos(angle))
                y = int(cy + r * math.sin(angle))
                if 0 <= x < 240 and 0 <= y < 240:
                    self._canvas.draw_pixel(x, y, color)
        # Center dot
        if 0 <= cx < 240 and 0 <= cy < 240:
            self._canvas.draw_pixel(cx, cy, color)

    def _draw_drip(self, x: int, start_y: int, length: int,
                   color: Tuple[int, int, int], stability: float):
        """Draw a drip/random walk flowing downward."""
        import random
        current_x = x
        wobble = int(3 + (1.0 - stability) * 8)  # Less stable = more wobble

        for y in range(start_y, min(240, start_y + length)):
            if 0 <= current_x < 240:
                self._canvas.draw_pixel(current_x, y, color)
            # Random walk sideways
            current_x += random.randint(-wobble, wobble)
            current_x = max(0, min(239, current_x))

    def _draw_scatter(self, cx: int, cy: int, num_particles: int,
                      spread: int, color: Tuple[int, int, int]):
        """Draw scattered particles in a cluster."""
        import random
        for _ in range(num_particles):
            # Gaussian-ish distribution - more dense at center
            dx = int(random.gauss(0, spread / 3))
            dy = int(random.gauss(0, spread / 3))
            x = cx + dx
            y = cy + dy
            if 0 <= x < 240 and 0 <= y < 240:
                self._canvas.draw_pixel(x, y, color)

    def canvas_clear(self, persist: bool = True):
        """Clear the canvas - saves first if there's a real drawing (50+ pixels).

        Minimal threshold avoids saving noise/stray marks.
        """
        # Prevent clearing if we're already paused (prevents loops)
        now = time.time()
        if now < self._canvas.drawing_paused_until:
            return  # Already paused, don't clear again

        # Save before clearing if there's actual drawing (50+ pixels, not just noise)
        if len(self._canvas.pixels) >= 50:
            saved_path = self.canvas_save(announce=False)
            if saved_path:
                print(f"[Canvas] Saved before clear: {saved_path}", file=sys.stderr, flush=True)

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

            # Trigger save indicator (shows "saved" on screen for 2 seconds)
            self._canvas.save_indicator_until = time.time() + 2.0

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

    def _render_self_graph(
        self,
        anima: Optional[Anima] = None,
        readings: Optional[SensorReadings] = None,
        identity: Optional[CreatureIdentity] = None,
    ):
        """
        Render Lumen's self-schema graph G_t.

        PoC for StructScore visual integrity evaluation.
        Base: 8 nodes (1 identity + 4 anima + 3 sensors).
        Enhanced: +N preference nodes if available.
        """
        from ..self_schema import get_current_schema
        from ..self_schema_renderer import render_schema_to_pixels, COLORS, WIDTH, HEIGHT
        from ..growth import get_growth_system

        # Get growth_system for learned preferences (uses DB, 456K+ observations)
        growth_system = None
        try:
            growth_system = get_growth_system()
        except Exception:
            pass  # Non-fatal

        # Extract current G_t (with preferences if available)
        schema = get_current_schema(
            identity=identity,
            anima=anima,
            readings=readings,
            growth_system=growth_system,
            include_preferences=True,  # Include preferences in enhanced version
        )

        # Render to pixels
        pixels = render_schema_to_pixels(schema)

        # Try canvas-based rendering
        if hasattr(self._display, '_create_canvas'):
            try:
                # Create canvas with schema background color
                image, draw = self._display._create_canvas(COLORS["background"])

                # Draw all pixels from schema render
                for (x, y), color in pixels.items():
                    if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                        image.putpixel((x, y), color)

                # Add title at top
                fonts = self._get_fonts()
                font_small = fonts['small']
                CYAN = (0, 255, 255)
                draw.text((5, 2), "self-schema G_t", fill=CYAN, font=font_small)

                # Add node count at bottom left
                GRAY = (120, 120, 120)
                draw.text((5, 225), f"{len(schema.nodes)} nodes, {len(schema.edges)} edges", fill=GRAY, font=font_small)

                # Nav dots
                self._draw_screen_indicator(draw, ScreenMode.SELF_GRAPH)

                # Update display
                if hasattr(self._display, '_image'):
                    self._display._image = image
                if hasattr(self._display, '_show'):
                    self._display._show()
                return
            except Exception as e:
                print(f"[Self Graph] Canvas error: {e}", file=sys.stderr, flush=True)
                import traceback
                traceback.print_exc(file=sys.stderr)

        # Fallback to text rendering
        text = f"SELF GRAPH\n\n{len(schema.nodes)} nodes\n{len(schema.edges)} edges"
        self._display.render_text(text, (10, 10))

    def _check_lumen_said_finished(self) -> bool:
        """
        Check if Lumen recently said it's finished with the drawing.

        Looks for keywords like "finished", "done", "complete" in recent observations.
        Only triggers once per drawing (resets after save).
        """
        try:
            from ..messages import get_board, MESSAGE_TYPE_OBSERVATION
            board = get_board()
            board._load()

            # Check last 5 observations from the past 5 minutes
            now = time.time()
            five_min_ago = now - 300

            recent_obs = [
                m for m in board._messages
                if m.msg_type == MESSAGE_TYPE_OBSERVATION
                and m.timestamp > five_min_ago
                and m.author == "lumen"
            ][-5:]

            # Keywords that indicate Lumen is done with drawing
            finish_keywords = [
                "finished", "done", "complete", "satisfied",
                "happy with", "ready to save", "time to save",
                "that's enough", "all done"
            ]

            for obs in recent_obs:
                text_lower = obs.text.lower()
                # Check for drawing-related finish statements
                if any(kw in text_lower for kw in finish_keywords):
                    # Make sure it's about drawing/canvas/art
                    drawing_context = ["draw", "canvas", "art", "creat", "work", "piece", "picture"]
                    if any(ctx in text_lower for ctx in drawing_context) or "drawing" in text_lower:
                        return True
                    # Also accept standalone "finished" or "done" if we have pixels
                    if len(self._canvas.pixels) > 500:
                        return True

            return False
        except Exception:
            return False

    def canvas_check_autonomy(self, anima: Optional[Anima] = None) -> Optional[str]:
        """
        Check if Lumen wants to autonomously save or clear the canvas.

        Called during render loop on ALL screens. Returns action taken if any.

        Lumen's autonomy:
        - Auto-save: When Lumen says "finished" OR satisfied + resting + time passed
        - Auto-clear: After save + high clarity (new inspiration) + enough time

        IMPORTANT: Designed to NOT overdo it. Saves should be rare and meaningful.
        - Minimum 3 minutes between saves
        - Need substantial work (2000+ pixels)
        - OR Lumen explicitly says finished
        """
        if anima is None:
            return None

        # CRITICAL: Update drawing phase even when not on notepad screen
        # This allows canvas to progress through phases and eventually save
        self._update_drawing_phase(anima)

        now = time.time()
        pixel_count = len(self._canvas.pixels)
        wellness = (anima.warmth + anima.clarity + anima.stability + anima.presence) / 4.0

        # Minimum time between saves: 3 minutes (prevents save spam)
        MIN_SAVE_INTERVAL = 180.0  # 3 minutes (was 10)
        time_since_save = now - self._canvas.last_save_time if self._canvas.last_save_time > 0 else float('inf')

        # Check if too soon to save again
        if time_since_save < MIN_SAVE_INTERVAL:
            return None  # Too soon since last save

        # === PRIORITY: Check if Lumen said "finished" ===
        # This takes precedence over metrics - if Lumen says done, respect that intent
        if (now >= self._canvas.drawing_paused_until and  # Not paused
            pixel_count > 500 and  # At least some work
            self._check_lumen_said_finished()):
            print(f"[Canvas] Lumen said finished - saving now ({pixel_count} pixels)", file=sys.stderr, flush=True)
            saved_path = self.canvas_save(announce=False)  # Don't double-announce
            if saved_path:
                self._canvas.is_satisfied = False
                self._canvas.satisfaction_time = 0.0
                # Clear canvas so Lumen can start fresh
                print(f"[Canvas] Clearing canvas for new drawing", file=sys.stderr, flush=True)
                self.canvas_clear(persist=True)
                self._canvas.save_to_disk()
                return "saved_and_cleared"

        # === Check for satisfaction ===
        # Lumen feels satisfied when: resting phase for 30s + real drawing + good state
        phase_duration = now - self._canvas.phase_start_time
        if (self._canvas.drawing_phase == "resting" and
            phase_duration > 30.0 and  # In resting phase for 30s
            pixel_count >= 50 and  # Real drawing, not noise
            anima.presence > 0.45 and
            anima.stability > 0.40 and
            not self._canvas.is_satisfied):
            self._canvas.mark_satisfied()

        # === Auto-save: satisfied + time to reflect ===
        # After 20s of satisfaction, save and start fresh
        # CRITICAL: Don't save if we're in pause period (after clear)
        if (now >= self._canvas.drawing_paused_until and  # Not paused
            self._canvas.is_satisfied and
            self._canvas.satisfaction_time > 0 and
            now - self._canvas.satisfaction_time > 20.0 and
            pixel_count >= 50):  # Real drawing, not noise

            print(f"[Canvas] Lumen autonomously saving (satisfied for 20s, {pixel_count} pixels)", file=sys.stderr, flush=True)
            saved_path = self.canvas_save(announce=True)
            if saved_path:
                # Reset satisfaction to prevent repeated saves
                self._canvas.is_satisfied = False
                self._canvas.satisfaction_time = 0.0
                # Clear canvas so Lumen can start fresh
                print(f"[Canvas] Clearing canvas for new drawing", file=sys.stderr, flush=True)
                self.canvas_clear(persist=True)
                self._canvas.save_to_disk()
                return "saved_and_cleared"

        # === Auto-clear: after save + new inspiration ===
        # If Lumen saved recently + clarity spike = wants to start fresh
        time_since_clear = now - self._canvas.last_clear_time

        # CRITICAL: Don't clear if we're in pause period (prevents clearing loop)
        if now < self._canvas.drawing_paused_until:
            return None  # Still paused from previous clear, don't clear again

        # CRITICAL: Add cooldown after clearing to prevent immediate re-clearing
        # Must wait at least 60 seconds after clearing (was 10s)
        if time_since_clear < 60.0:
            return None  # Too soon after last clear

        # Auto-clear only after 20-60 minutes since save (was 10-30 min)
        # Made much more conservative to avoid aggressive clearing
        if (self._canvas.last_save_time > 0 and  # Has saved at least once
            time_since_save > 1200.0 and  # At least 20 min since save (was 10 min)
            time_since_save < 3600.0 and  # Within 60 min of save (was 30 min)
            anima.clarity > 0.80 and  # Higher clarity threshold (was 0.70)
            anima.presence > 0.75 and  # Higher presence threshold (was 0.60)
            wellness > 0.70 and  # Higher wellness threshold (was 0.60)
            pixel_count > 0):  # Has something to clear

            print(f"[Canvas] Lumen autonomously clearing (new inspiration after {time_since_save/60:.1f}min)", file=sys.stderr, flush=True)
            self.canvas_clear(persist=True)
            # Reset last_save_time to prevent repeated clears (only ONE auto-clear per saved drawing)
            self._canvas.last_save_time = 0.0
            self._canvas.save_to_disk()
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
    
