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
import math
import random

from .face import FaceState
from .design import COLORS, SPACING, Timing, ease_smooth
from ..anima import Anima
from ..sensors.base import SensorReadings
from ..identity.store import CreatureIdentity
from ..learning_visualization import LearningVisualizer
from .drawing_engine import (
    DrawingEngine, CanvasState, DrawingState, DrawingGoal,
    DrawingIntent, DrawingEISV, _EISV_PARAMS, _get_canvas_path,
)


class ScreenMode(Enum):
    """Available display screens."""
    FACE = "face"                    # Default: Lumen's expressive face
    SENSORS = "sensors"              # Sensor readings (temp, humidity, etc.)
    IDENTITY = "identity"            # Name, age, awakenings, alive time
    DIAGNOSTICS = "diagnostics"      # System health, governance status
    NEURAL = "neural"                # Neural activity - EEG frequency bands
    LEARNING = "learning"            # Learning visualization - why Lumen feels what it feels
    SELF_GRAPH = "self_graph"        # Self-schema G_t visualization
    NOTEPAD = "notepad"              # Drawing canvas - Lumen's creative space
    MESSAGES = "messages"            # Message board - Lumen's observations only
    QUESTIONS = "questions"          # Q&A - Lumen's questions and answers
    VISITORS = "visitors"            # Messages from agents and humans
    ART_ERAS = "art_eras"            # Art era history and current era
    HEALTH = "health"                # Subsystem health monitoring


@dataclass
class ScreenState:
    """Current screen state."""
    mode: ScreenMode = ScreenMode.FACE
    last_switch_time: float = 0.0
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
    transition_duration: float = Timing.SCREEN_TRANSITION_MS / 1000.0
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

    # Art eras screen interaction state
    era_cursor: int = 0  # Which era is highlighted (index into list_all_era_info)

    # Brightness overlay state
    brightness_changed_at: float = 0.0  # When brightness last changed
    brightness_overlay_name: str = ""  # Preset name to display
    brightness_overlay_level: float = 1.0  # Display brightness level for bar

    # Governance verdict enforcement: pause drawing when governance says pause/halt
    governance_paused: bool = False  # True when action in ("pause", "halt")


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
        self._db_path = db_path or "anima.db"
        self._identity_store = identity_store

        # Drawing engine owns canvas, intent, era, mood tracker
        self.drawing_engine = DrawingEngine(db_path=self._db_path, identity_store=identity_store)

        # Initialize user action time
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
        # Generic screen image cache: {screen_name: (hash_str, PIL.Image)}, max 12 entries
        self._screen_cache: Dict[str, tuple] = {}
        self._screen_cache_max_size = 12
        self._screen_cache_order: List[str] = []  # LRU order
        # UNITARES agent_id (for display on identity screen)
        self._unitares_agent_id: Optional[str] = None
        # Neural waveform history (scrolling traces)
        from collections import deque
        self._neural_history: deque = deque(maxlen=60)
        # Sensor sparkline history
        self._sensor_history: deque = deque(maxlen=40)

    # --- Backward-compat properties for drawing engine internals ---
    @property
    def _canvas(self):
        return self.drawing_engine.canvas

    @property
    def _intent(self):
        return self.drawing_engine.intent

    @property
    def _active_era(self):
        return self.drawing_engine.active_era

    @_active_era.setter
    def _active_era(self, value):
        self.drawing_engine.active_era = value

    @property
    def _drawing_goal(self):
        return self.drawing_engine.drawing_goal

    @_drawing_goal.setter
    def _drawing_goal(self, value):
        self.drawing_engine.drawing_goal = value

    @property
    def _last_anima(self):
        return self.drawing_engine.last_anima

    @_last_anima.setter
    def _last_anima(self, value):
        self.drawing_engine.last_anima = value

    @property
    def _mood_tracker(self):
        return self.drawing_engine._mood_tracker

    # --- Pass-through methods for server.py callers ---
    def canvas_save(self, **kw):
        return self.drawing_engine.canvas_save(**kw)

    def canvas_clear(self, **kw):
        return self.drawing_engine.canvas_clear(**kw)

    def get_drawing_eisv(self):
        return self.drawing_engine.get_drawing_eisv()

    def get_current_era(self):
        return self.drawing_engine.get_current_era()

    def set_era(self, era_name, force_immediate=False):
        return self.drawing_engine.set_era(era_name, force_immediate)

    def era_cursor_up(self):
        return self.drawing_engine.era_cursor_up(self._state)

    def era_cursor_down(self):
        return self.drawing_engine.era_cursor_down(self._state)

    def era_select_current(self):
        return self.drawing_engine.era_select_current(self._state)

    def canvas_check_autonomy(self, anima=None):
        return self.drawing_engine.canvas_check_autonomy(anima)

    def _lumen_draw(self, anima, draw=None):
        return self.drawing_engine.draw(anima, draw)

    def _get_messages_cache_hash(self, messages: list, scroll_idx: int, expanded_id: Optional[str]) -> str:
        """Compute hash of message screen state for cache invalidation."""
        # Include message IDs/timestamps, scroll position, and expanded state
        msg_ids = "|".join(f"{m.message_id}:{m.timestamp}" for m in messages[:10]) if messages else ""
        return f"{msg_ids}|{scroll_idx}|{expanded_id or ''}"

    def _check_screen_cache(self, screen_name: str, cache_key: str) -> bool:
        """Check if cached image matches current state. If hit, apply it.

        Returns True if cache hit (caller should return immediately).
        Uses copy() so post-processing (overlays, transitions) never mutates the cache.
        """
        entry = self._screen_cache.get(screen_name)
        if entry and entry[0] == cache_key:
            if hasattr(self._display, '_image'):
                self._display._image = entry[1].copy()
            if hasattr(self._display, '_show'):
                self._display._show()
            # Bump to end of LRU order (recently used)
            if screen_name in self._screen_cache_order:
                self._screen_cache_order.remove(screen_name)
            self._screen_cache_order.append(screen_name)
            return True
        return False

    def _store_screen_cache(self, screen_name: str, cache_key: str, image):
        """Store rendered image in screen cache. Evict oldest when over max size."""
        if screen_name in self._screen_cache:
            self._screen_cache_order.remove(screen_name)
        self._screen_cache[screen_name] = (cache_key, image.copy())
        self._screen_cache_order.append(screen_name)
        while len(self._screen_cache) > self._screen_cache_max_size and self._screen_cache_order:
            evict = self._screen_cache_order.pop(0)
            if evict in self._screen_cache:
                del self._screen_cache[evict]

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
        else:
            # Not on notepad — clear drawing phase from neural sensor
            try:
                from ..computational_neural import get_computational_neural_sensor
                get_computational_neural_sensor().drawing_phase = None
            except Exception:
                pass
    
    def next_mode(self):
        """Cycle to next screen mode (including notepad)."""
        # Cycle through all screens including notepad, questions, and visitors
        regular_modes = [ScreenMode.FACE, ScreenMode.IDENTITY, ScreenMode.SENSORS, ScreenMode.DIAGNOSTICS, ScreenMode.HEALTH, ScreenMode.NEURAL, ScreenMode.LEARNING, ScreenMode.SELF_GRAPH, ScreenMode.MESSAGES, ScreenMode.QUESTIONS, ScreenMode.VISITORS, ScreenMode.NOTEPAD, ScreenMode.ART_ERAS]
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
        regular_modes = [ScreenMode.FACE, ScreenMode.IDENTITY, ScreenMode.SENSORS, ScreenMode.DIAGNOSTICS, ScreenMode.HEALTH, ScreenMode.NEURAL, ScreenMode.LEARNING, ScreenMode.SELF_GRAPH, ScreenMode.MESSAGES, ScreenMode.QUESTIONS, ScreenMode.VISITORS, ScreenMode.NOTEPAD, ScreenMode.ART_ERAS]
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

    # Screen groups for indicator display
    _SCREEN_GROUPS = {
        ScreenMode.FACE: ("home", [ScreenMode.FACE]),
        ScreenMode.IDENTITY: ("info", [ScreenMode.IDENTITY, ScreenMode.SENSORS, ScreenMode.DIAGNOSTICS, ScreenMode.HEALTH]),
        ScreenMode.SENSORS: ("info", [ScreenMode.IDENTITY, ScreenMode.SENSORS, ScreenMode.DIAGNOSTICS, ScreenMode.HEALTH]),
        ScreenMode.DIAGNOSTICS: ("info", [ScreenMode.IDENTITY, ScreenMode.SENSORS, ScreenMode.DIAGNOSTICS, ScreenMode.HEALTH]),
        ScreenMode.HEALTH: ("info", [ScreenMode.IDENTITY, ScreenMode.SENSORS, ScreenMode.DIAGNOSTICS, ScreenMode.HEALTH]),
        ScreenMode.NEURAL: ("mind", [ScreenMode.NEURAL, ScreenMode.LEARNING, ScreenMode.SELF_GRAPH]),
        ScreenMode.LEARNING: ("mind", [ScreenMode.NEURAL, ScreenMode.LEARNING, ScreenMode.SELF_GRAPH]),
        ScreenMode.SELF_GRAPH: ("mind", [ScreenMode.NEURAL, ScreenMode.LEARNING, ScreenMode.SELF_GRAPH]),
        ScreenMode.MESSAGES: ("social", [ScreenMode.MESSAGES, ScreenMode.QUESTIONS, ScreenMode.VISITORS]),
        ScreenMode.QUESTIONS: ("social", [ScreenMode.MESSAGES, ScreenMode.QUESTIONS, ScreenMode.VISITORS]),
        ScreenMode.VISITORS: ("social", [ScreenMode.MESSAGES, ScreenMode.QUESTIONS, ScreenMode.VISITORS]),
        ScreenMode.NOTEPAD: ("art", [ScreenMode.NOTEPAD, ScreenMode.ART_ERAS]),
        ScreenMode.ART_ERAS: ("art", [ScreenMode.NOTEPAD, ScreenMode.ART_ERAS]),
    }

    def _draw_screen_indicator(self, draw, current_mode: ScreenMode):
        """Draw group name + position indicator at bottom-right (e.g., 'mind 2/3')."""
        group_info = self._SCREEN_GROUPS.get(current_mode)
        if not group_info:
            return

        group_name, group_screens = group_info
        try:
            pos = group_screens.index(current_mode) + 1
        except ValueError:
            return

        total = len(group_screens)
        if total == 1:
            label = group_name
        else:
            label = f"{group_name} {pos}/{total}"

        fonts = self._get_fonts()
        font = fonts.get('tiny', fonts.get('micro'))
        DIM = (100, 100, 100)

        # Right-aligned at bottom
        try:
            bbox = font.getbbox(label)
            text_w = bbox[2] - bbox[0]
        except Exception:
            text_w = len(label) * 6
        x = 240 - text_w - 6
        y = 232
        draw.text((x, y), label, fill=DIM, font=font)

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

        # Calculate transition progress with ease-in-out
        elapsed = time.time() - self._state.transition_start_time
        linear = min(1.0, elapsed / self._state.transition_duration)
        progress = ease_smooth(linear)  # Gentle start and end
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
            # Cross-fade with eased progress — smoother feel
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

    def trigger_brightness_overlay(self, preset_name: str, display_level: float):
        """Show brightness overlay for 1.5 seconds."""
        self._state.brightness_changed_at = time.time()
        self._state.brightness_overlay_name = preset_name
        self._state.brightness_overlay_level = display_level

    def _draw_brightness_overlay(self, draw, image):
        """Draw LED brightness overlay (centered box with name + bar)."""
        elapsed = time.time() - self._state.brightness_changed_at
        if elapsed >= 1.5:
            return

        name = self._state.brightness_overlay_name
        level = self._state.brightness_overlay_level
        w, h = 240, 240

        # Semi-transparent dark box (centered)
        box_w, box_h = 100, 50
        bx = (w - box_w) // 2
        by = (h - box_h) // 2

        # Fade out in last 0.3s
        alpha = 1.0 if elapsed < 1.2 else (1.5 - elapsed) / 0.3

        # Draw dark background
        bg_color = tuple(int(20 * alpha) for _ in range(3))
        draw.rectangle([bx - 2, by - 2, bx + box_w + 2, by + box_h + 2], fill=bg_color)

        fonts = self._get_fonts()

        # "LEDs" label (small, top)
        label_color = tuple(int(120 * alpha) for _ in range(3))
        draw.text((bx + 33, by + 2), "LEDs", fill=label_color, font=fonts['micro'])

        # Preset name (larger, below label)
        text_color = tuple(int(220 * alpha) for _ in range(3))
        bbox = draw.textbbox((0, 0), name, font=fonts['medium'])
        tw = bbox[2] - bbox[0]
        draw.text(((w - tw) // 2, by + 14), name, fill=text_color, font=fonts['medium'])

        # LED brightness bar - 4 segment design for clear visibility
        bar_y = by + 34
        bar_w = box_w - 16
        bar_x = bx + 8
        bar_h = 8  # Taller bar

        # Draw 4 distinct segments (one per preset level)
        segment_w = (bar_w - 6) // 4  # 4 segments with gaps
        gap = 2

        # Map level to number of segments: 1.0=4, 0.53=3, 0.27=2, 0.13=1
        if level > 0.8:
            segments_lit = 4
        elif level > 0.4:
            segments_lit = 3
        elif level > 0.2:
            segments_lit = 2
        else:
            segments_lit = 1

        for i in range(4):
            sx = bar_x + i * (segment_w + gap)
            if i < segments_lit:
                # Lit segment - bright cyan
                seg_color = tuple(int(c * alpha) for c in (100, 200, 240))
            else:
                # Unlit segment - dark
                seg_color = tuple(int(40 * alpha) for _ in range(3))
            draw.rectangle([sx, bar_y, sx + segment_w, bar_y + bar_h], fill=seg_color)

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

            # Store latest state for use by canvas_save growth notifications
            self._last_anima = anima
            self.drawing_engine._last_readings = readings

            # Store UNITARES agent_id for identity screen display
            if governance and governance.get("unitares_agent_id"):
                self._unitares_agent_id = governance.get("unitares_agent_id")

            # Enforce governance verdicts: pause drawing when governance says pause/halt
            if governance:
                action = governance.get("action", "proceed")
                if action in ("pause", "halt", "reject"):
                    self._state.governance_paused = True
                elif action == "proceed":
                    self._state.governance_paused = False

            # Check Lumen's canvas autonomy (can save/clear regardless of screen)
            # Throttle to every 10th frame — save/energy checks don't need 3Hz
            try:
                if not hasattr(self._state, '_frame_count'):
                    self._state._frame_count = 0
                self._state._frame_count += 1
                if self._state._frame_count % 10 == 0:
                    self.canvas_check_autonomy(anima)
                    # Heartbeat: drawing subsystem is alive
                    try:
                        from ..health import get_health_registry
                        get_health_registry().heartbeat("drawing")
                    except Exception:
                        pass
            except Exception as e:
                # Don't let autonomy errors break rendering, but log them
                if self._state._frame_count % 100 == 0:
                    print(f"[Canvas] Autonomy check error: {e}", file=sys.stderr, flush=True)

            # Disable auto-return - let user stay on screens as long as they want
            # Only auto-return to FACE if explicitly requested via button
            # (Auto-return disabled to prevent getting stuck)

            mode = self._state.mode
            try:
                if mode == ScreenMode.FACE:
                    self._render_face(face_state, identity, anima)
                elif mode == ScreenMode.SENSORS:
                    self._render_sensors(readings)
                elif mode == ScreenMode.IDENTITY:
                    self._render_identity(identity)
                elif mode == ScreenMode.DIAGNOSTICS:
                    self._render_diagnostics(anima, readings, governance)
                elif mode == ScreenMode.NEURAL:
                    self._render_neural(anima, readings)
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
                elif mode == ScreenMode.ART_ERAS:
                    self._render_art_eras(anima)
                elif mode == ScreenMode.HEALTH:
                    self._render_health()
                else:
                    # Unknown mode - show default to prevent blank screen
                    print(f"[Screen] Unknown mode: {mode}, showing default", file=sys.stderr, flush=True)
                    self._display.show_default()

                # Background drawing: Lumen draws even when notepad isn't displayed.
                # Throttled to every 5th frame (~every 10s at 2s/loop) to limit CPU when on other screens.
                # Skips when governance says pause/halt (enforces verdict).
                if (mode != ScreenMode.NOTEPAD and anima and hasattr(self._display, '_create_canvas')
                        and self._state._frame_count % 5 == 0
                        and time.time() >= self._canvas.drawing_paused_until
                        and not getattr(self._state, 'governance_paused', False)
                        and len(self._canvas.pixels) < 15000):
                    try:
                        self._lumen_draw(anima, draw=None)
                    except Exception as e:
                        pass  # Don't let background draw break display
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

                    # Draw brightness overlay (when user changes brightness)
                    if time.time() - self._state.brightness_changed_at < 1.5:
                        self._draw_brightness_overlay(draw, image)

                    # Apply loading indicator overlay
                    if self._state.is_loading:
                        result = self._draw_loading_indicator(None, image)
                        if result is not None:
                            image = result

                    self._display._image = image
            except Exception as e:
                print(f"[Screen] Post-processing error: {e}", file=sys.stderr, flush=True)

            # Ensure we have something to display — prevent blank screens
            if not hasattr(self._display, '_image') or self._display._image is None:
                try:
                    self._display.show_default()
                except Exception:
                    pass

            # Single SPI push — all drawing is done, flush to hardware
            self._display._deferred = False
            self._display.flush()

        # Log slow renders to identify bottleneck
        render_time = time.time() - render_start
        if render_time > 0.5:  # Log if >500ms
            print(f"[Screen] Slow render: {mode.value} took {render_time*1000:.0f}ms", file=sys.stderr, flush=True)
    
    def _render_face(self, face_state: Optional[FaceState], identity: Optional[CreatureIdentity], anima: Optional[Anima] = None):
        """Render face screen (default)."""
        if face_state:
            name = identity.name if identity else None
            self._display.render_face(face_state, name=name, anima=anima)
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

        # Cache: sensor values rounded to display precision (avoids redraw for noise)
        # Use (x or 0) to handle None when I2C/sensors fail
        throttle = getattr(readings, 'throttle_bits', None) or 0
        cache_key = (
            f"{(readings.ambient_temp_c or 0):.1f}|{(readings.humidity_pct or 0):.0f}|"
            f"{(readings.light_lux or 0):.0f}|{(readings.cpu_temp_c or 0):.1f}|"
            f"{(readings.cpu_percent or 0):.0f}|{(readings.disk_percent or 0):.0f}|"
            f"{throttle}"
        )
        if self._check_screen_cache("sensors", cache_key):
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

                # System (handle None when sensors fail)
                cpu_temp = readings.cpu_temp_c or 0
                if cpu_temp > 60:
                    cpu_color = RED
                elif cpu_temp > 50:
                    cpu_color = ORANGE
                else:
                    cpu_color = GREEN
                draw.text((10, y), f"cpu: {cpu_temp:.1f}°C", fill=cpu_color, font=font)
                y += line_height
                cpu_pct = readings.cpu_percent or 0
                draw.text((10, y), f"load: {cpu_pct:.0f}%", fill=LIGHT_CYAN, font=font)
                y += line_height

                # Disk space
                disk = readings.disk_percent or 0
                if disk > 80:
                    disk_color = RED
                elif disk > 60:
                    disk_color = ORANGE
                else:
                    disk_color = GREEN
                draw.text((10, y), f"disk: {disk:.0f}%", fill=disk_color, font=font)
                y += line_height

                # Hint when I2C sensors (air, humidity, light) all missing
                if not any([readings.ambient_temp_c, readings.humidity_pct, readings.light_lux]):
                    draw.text((10, y), "I2C off? run: sudo raspi-config", fill=COLORS.TEXT_DIM, font=font_small)
                    y += line_height

                # Voltage / throttle status
                if hasattr(readings, 'undervoltage_now') and readings.undervoltage_now is not None:
                    if readings.undervoltage_now:
                        draw.text((10, y), "⚡ UNDERVOLT!", fill=RED, font=font)
                    elif readings.undervoltage_occurred:
                        draw.text((10, y), "pwr: warn (was low)", fill=ORANGE, font=font)
                    elif readings.throttled_now:
                        draw.text((10, y), "pwr: throttled", fill=ORANGE, font=font)
                    else:
                        draw.text((10, y), "pwr: ok", fill=GREEN, font=font)
                    y += line_height
                y += 8

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

                # Record sensor history for sparklines
                self._sensor_history.append((
                    readings.ambient_temp_c or 0,
                    readings.humidity_pct or 0,
                    readings.cpu_temp_c or 0,
                ))

                # Draw sparklines next to key values (if enough history)
                if len(self._sensor_history) >= 5:
                    self._draw_sensor_sparklines(draw, readings)

                # Status bar + screen indicator
                self._draw_status_bar(draw)
                self._draw_screen_indicator(draw, ScreenMode.SENSORS)

                # Update display + cache
                self._store_screen_cache("sensors", cache_key, image)
                if hasattr(self._display, '_image'):
                    self._display._image = image
                if hasattr(self._display, '_show'):
                    self._display._show()
                return
            except Exception as e:
                print(f"[Sensors Screen] Canvas error: {e}", file=sys.stderr, flush=True)

        # Fallback to text rendering
        lines_with_colors = []
        if not any([readings.ambient_temp_c, readings.humidity_pct, readings.light_lux]):
            lines_with_colors.append(("I2C off? sudo raspi-config", COLORS.TEXT_DIM))
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
        cpu_t = readings.cpu_temp_c or 0
        lines_with_colors.append((f"cpu: {cpu_t:.1f}°C", GREEN))
        if hasattr(readings, 'undervoltage_now') and readings.undervoltage_now:
            lines_with_colors.append(("UNDERVOLT!", RED))
        elif hasattr(readings, 'undervoltage_occurred') and readings.undervoltage_occurred:
            lines_with_colors.append(("pwr: warn", ORANGE))

        if lines_with_colors:
            if hasattr(self._display, 'render_colored_text'):
                self._display.render_colored_text(lines_with_colors, (10, 10))
            else:
                text = "\n".join([line for line, _ in lines_with_colors])
                self._display.render_text(text, (10, 10))
        else:
            self._display.render_text("SENSORS\n\nno data", (10, 10), color=COLORS.TEXT_DIM)
    
    def _draw_sensor_sparklines(self, draw, readings):
        """Draw tiny sparklines to the right of sensor values."""
        history = list(self._sensor_history)
        n = len(history)
        if n < 5:
            return

        ORANGE = COLORS.SOFT_ORANGE
        GREEN = COLORS.SOFT_GREEN

        # Sparkline config: (data_index, y_center, color)
        sparklines = [
            (0, 21, ORANGE if (readings.ambient_temp_c or 0) > 25 else GREEN),  # temp
            (1, 43, GREEN),   # humidity
            (2, 95, GREEN),   # cpu temp
        ]

        spark_x = 175
        spark_w = 40
        spark_h = 12

        for data_idx, y_center, color in sparklines:
            values = [h[data_idx] for h in history]
            v_min = min(values)
            v_max = max(values)
            v_range = v_max - v_min if v_max > v_min else 1.0

            y_top = y_center - spark_h // 2
            points = []
            for i, v in enumerate(values):
                x = spark_x + int(i * spark_w / (n - 1))
                y = y_top + spark_h - int(((v - v_min) / v_range) * spark_h)
                points.append((x, y))

            if len(points) >= 2:
                draw.line(points, fill=color, width=1)

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

                # Alive ratio ring (right side)
                try:
                    from .design import wellness_to_color
                    alive_ratio = identity.alive_ratio()
                    ring_cx, ring_cy, ring_r = 195, 80, 30
                    # Background ring (dim)
                    draw.arc([ring_cx - ring_r, ring_cy - ring_r, ring_cx + ring_r, ring_cy + ring_r],
                             0, 360, fill=(40, 40, 40), width=8)
                    # Filled arc (0 degrees = 3 o'clock, draw clockwise from top)
                    if alive_ratio > 0.01:
                        ring_color = wellness_to_color(alive_ratio)
                        end_angle = int(alive_ratio * 360)
                        draw.arc([ring_cx - ring_r, ring_cy - ring_r, ring_cx + ring_r, ring_cy + ring_r],
                                 -90, -90 + end_angle, fill=ring_color, width=8)
                    # Percentage text centered in ring
                    pct_text = f"{alive_pct:.0f}%"
                    try:
                        bbox = fonts['small'].getbbox(pct_text)
                        tw = bbox[2] - bbox[0]
                        th = bbox[3] - bbox[1]
                    except Exception:
                        tw, th = len(pct_text) * 6, 10
                    draw.text((ring_cx - tw // 2, ring_cy - th // 2),
                              pct_text, fill=COLORS.TEXT_PRIMARY, font=fonts['small'])
                except Exception:
                    pass  # Non-fatal

                # Status bar + screen indicator
                self._draw_status_bar(draw)
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

        # Cache: anima values + governance state rounded to display precision
        gov_state = governance.get("unitares_agent_id", "")[:8] if governance else ""
        try:
            from ..eisv import get_trajectory_awareness
            _traj_shape = get_trajectory_awareness().current_shape or ""
        except Exception:
            _traj_shape = ""
        diag_key = (
            f"{anima.warmth:.2f}|{anima.clarity:.2f}|{anima.stability:.2f}|"
            f"{anima.presence:.2f}|{gov_state}|{_traj_shape}"
        )
        if self._check_screen_cache("diagnostics", diag_key):
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
                            y_offset += 12 + mini_bar_height + 4  # Advance past EISV bars
                else:
                    # No governance - show waiting
                    draw.text((bar_x, y_offset + 16), "waiting...", fill=LIGHT_CYAN, font=font)

            # Trajectory awareness shape
            if y_offset < 225:
                try:
                    from ..eisv import get_trajectory_awareness
                    _traj = get_trajectory_awareness()
                    _shape = _traj.current_shape or "..."
                    _buf_size = _traj.buffer_size
                    _buf_cap = _traj._buffer.maxlen
                    import time as _time
                    _cache_age = int(_time.time() - _traj._cache_time) if _traj._cache_time > 0 else -1
                    _cache_str = f"{_cache_age}s" if _cache_age >= 0 else "n/a"
                    _traj_text = f"traj: {_shape} ({_buf_size}/{_buf_cap}, {_cache_str})"
                    draw.text((bar_x, y_offset), _traj_text, fill=LIGHT_CYAN, font=font_small)
                    y_offset += 14
                except Exception:
                    pass

            # Status bar + screen indicator
            self._draw_status_bar(draw)
            self._draw_screen_indicator(draw, ScreenMode.DIAGNOSTICS)

            # Update display + cache
            self._store_screen_cache("diagnostics", diag_key, image)
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
        # Trajectory
        try:
            from ..eisv import get_trajectory_awareness
            _traj = get_trajectory_awareness()
            if _traj.current_shape:
                lines.append(f"traj: {_traj.current_shape}")
        except Exception:
            pass
        self._display.render_text("\n".join(lines), (10, 10))

    def _render_health(self):
        """Render subsystem health monitoring screen.

        One row per subsystem with colored status dot (green/yellow/red).
        Status: ok=green, stale=yellow, degraded=orange, missing=red.
        """
        try:
            from ..health import get_health_registry
            registry = get_health_registry()
        except Exception:
            self._display.render_text("HEALTH\n\nNo registry", (10, 10))
            return

        status_data = registry.status()
        overall = registry.overall()

        # Cache key: status values
        health_key = "|".join(f"{n}:{d.get('status', '?')}" for n, d in sorted(status_data.items()))
        if self._check_screen_cache("health", health_key):
            return

        try:
            if hasattr(self._display, '_create_canvas'):
                image, draw = self._display._create_canvas(COLORS.BG_DARK)
            else:
                # Text fallback
                lines = ["HEALTH", f"overall: {overall}", ""]
                for name, info in sorted(status_data.items()):
                    s = info.get("status", "?")
                    hb = info.get("last_heartbeat_ago_s")
                    hb_str = f" {hb:.0f}s" if hb is not None else ""
                    lines.append(f"  {s[0].upper()} {name}{hb_str}")
                self._display.render_text("\n".join(lines), (10, 10))
                return

            fonts = self._get_fonts()
            font_small = fonts['small']
            font_tiny = fonts['tiny']
            font_med = fonts['medium']

            # Status color mapping
            STATUS_COLORS = {
                "ok": COLORS.SOFT_GREEN,
                "stale": COLORS.SOFT_YELLOW,
                "degraded": COLORS.SOFT_ORANGE,
                "missing": COLORS.SOFT_CORAL,
                "unknown": COLORS.TEXT_DIM,
            }

            # Overall status color
            OVERALL_COLORS = {
                "ok": COLORS.SOFT_GREEN,
                "degraded": COLORS.SOFT_YELLOW,
                "unhealthy": COLORS.SOFT_CORAL,
                "unknown": COLORS.TEXT_DIM,
            }

            # Header
            y = 6
            draw.text((10, y), "HEALTH", fill=COLORS.TEXT_PRIMARY, font=font_med)
            overall_color = OVERALL_COLORS.get(overall, COLORS.TEXT_DIM)
            draw.text((90, y), overall, fill=overall_color, font=font_med)
            y += 20

            # Thin separator line
            draw.line([(10, y), (230, y)], fill=COLORS.BG_SUBTLE, width=1)
            y += 4

            # One row per subsystem
            dot_radius = 4
            subsystems = sorted(status_data.items())
            row_height = 22 if len(subsystems) <= 9 else 19

            for name, info in subsystems:
                status = info.get("status", "unknown")
                color = STATUS_COLORS.get(status, COLORS.TEXT_DIM)
                hb_ago = info.get("last_heartbeat_ago_s")
                probe = info.get("probe")

                # Status dot
                cx, cy = 18, y + row_height // 2
                draw.ellipse(
                    [(cx - dot_radius, cy - dot_radius), (cx + dot_radius, cy + dot_radius)],
                    fill=color
                )

                # Subsystem name
                draw.text((28, y + 2), name, fill=COLORS.TEXT_PRIMARY, font=font_small)

                # Heartbeat age (right-aligned)
                if hb_ago is not None:
                    if hb_ago < 60:
                        age_str = f"{hb_ago:.0f}s"
                    else:
                        age_str = f"{hb_ago / 60:.0f}m"
                    draw.text((160, y + 2), age_str, fill=COLORS.TEXT_DIM, font=font_tiny)

                # Probe status (far right)
                if probe is not None:
                    probe_color = COLORS.SOFT_GREEN if probe == "ok" else COLORS.SOFT_CORAL
                    draw.text((195, y + 2), probe[:12], fill=probe_color, font=font_tiny)

                y += row_height

            self._draw_status_bar(draw)
            self._draw_screen_indicator(draw, ScreenMode.HEALTH)

            self._display.render_image(image)
            self._store_screen_cache("health", health_key, image)

        except Exception as e:
            print(f"[Screen] Health render error: {e}", file=sys.stderr, flush=True)
            self._display.render_text(f"HEALTH\n\n{overall}\n\nError:\n{str(e)[:40]}", (10, 10))

    def _render_neural(self, anima: Optional[Anima], readings: Optional[SensorReadings]):
        """Render neural activity screen - scrolling waveform traces."""
        if not readings:
            self._display.render_text("NEURAL\n\nNo data", (10, 10))
            return

        # No screen cache for neural — waveforms scroll every frame

        try:
            if not hasattr(self._display, '_create_canvas'):
                self._render_neural_text_fallback(readings)
                return

            image, draw = self._display._create_canvas(COLORS.BG_DARK)

            fonts = self._get_fonts()
            font_small = fonts['small']
            font_title = fonts['title']
            font_tiny = fonts['tiny']
            font_micro = fonts['micro']

            DIM = COLORS.TEXT_DIM

            # Band data from readings
            raw = readings.to_dict()
            band_values = (
                raw.get("eeg_delta_power") or 0,
                raw.get("eeg_theta_power") or 0,
                raw.get("eeg_alpha_power") or 0,
                raw.get("eeg_beta_power") or 0,
                raw.get("eeg_gamma_power") or 0,
            )
            self._neural_history.append(band_values)

            band_info = [
                ("delta", (100, 100, 240)),
                ("theta", (140, 92, 246)),
                ("alpha", (6, 182, 212)),
                ("beta",  (34, 197, 94)),
                ("gamma", (245, 158, 11)),
            ]

            # Title
            draw.text((10, 6), "Neural Activity", fill=COLORS.SOFT_CYAN, font=font_title)

            # Dominant band indicator
            dominant_idx = max(range(5), key=lambda i: band_values[i])
            dominant_name = band_info[dominant_idx][0]
            dominant_color = band_info[dominant_idx][1]
            draw.text((10, 26), f"dominant: {dominant_name}", fill=dominant_color, font=font_small)

            # ---- Waveform traces ----
            trace_x_start = 30
            trace_x_end = 225
            trace_width = trace_x_end - trace_x_start
            trace_height = 20
            trace_gap = 4
            trace_y_start = 50
            history = list(self._neural_history)
            n_points = len(history)

            for band_idx, (name, color) in enumerate(band_info):
                y_top = trace_y_start + band_idx * (trace_height + trace_gap)
                y_bottom = y_top + trace_height

                # Band label on left
                greek = {0: "\u03b4", 1: "\u03b8", 2: "\u03b1", 3: "\u03b2", 4: "\u03b3"}
                draw.text((6, y_top + 4), greek[band_idx], fill=color, font=font_small)

                # Current value on right
                val = band_values[band_idx]
                draw.text((trace_x_end + 4, y_top + 4), f"{val*100:.0f}", fill=DIM, font=font_micro)

                # Background track
                draw.rectangle([trace_x_start, y_top, trace_x_end, y_bottom],
                              fill=(12, 12, 18))

                # Draw waveform if we have enough data
                if n_points >= 2:
                    points = []
                    for i, sample in enumerate(history):
                        x = trace_x_start + int(i * trace_width / (n_points - 1))
                        v = max(0.0, min(1.0, sample[band_idx]))
                        y = y_bottom - int(v * trace_height)
                        points.append((x, y))
                    draw.line(points, fill=color, width=1)

            # ---- Band descriptions at bottom ----
            y_desc = trace_y_start + 5 * (trace_height + trace_gap) + 4
            desc_map = {
                "delta": "deep rest",
                "theta": "meditation",
                "alpha": "awareness",
                "beta": "focus",
                "gamma": "cognition",
            }
            dominant_desc = desc_map.get(dominant_name, "")
            draw.text((10, y_desc), f"{dominant_name}: {dominant_desc}", fill=dominant_color, font=font_small)

            # Mood context line
            if anima:
                feeling = anima.feeling()
                mood = feeling.get("mood", "")
                if mood:
                    draw.text((10, y_desc + 16), f"mood: {mood}", fill=DIM, font=font_tiny)

            # Status bar + screen indicator
            self._draw_status_bar(draw)
            self._draw_screen_indicator(draw, ScreenMode.NEURAL)

            if hasattr(self._display, '_image'):
                self._display._image = image
            if hasattr(self._display, '_show'):
                self._display._show()

        except Exception as e:
            import traceback
            print(f"[Neural Screen] Error: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            self._render_neural_text_fallback(readings)

    def _render_neural_text_fallback(self, readings: Optional[SensorReadings]):
        """Text-only fallback for neural screen."""
        raw = readings.to_dict() if readings else {}
        lines = ["NEURAL ACTIVITY", ""]
        for band in ["delta", "theta", "alpha", "beta", "gamma"]:
            val = raw.get(f"eeg_{band}_power") or 0
            bar = "#" * int(val * 20)
            lines.append(f"{band:6s} {val:.0%} {bar}")
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

            # Status bar + screen indicator
            self._draw_status_bar(draw)
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

            # Status bar + screen indicator
            self._draw_status_bar(draw)
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
            self._render_qa_content()
        except Exception as e:
            import traceback
            print(f"[Questions Screen] Error in _render_qa_content: {e}", file=sys.stderr, flush=True)
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

    def _render_art_eras(self, anima: Optional[Anima] = None):
        """Render Art Eras screen — era selector with auto-rotate toggle."""
        from .eras import list_all_era_info, auto_rotate as _auto_rotate

        try:
            if hasattr(self._display, '_create_canvas'):
                image, draw = self._display._create_canvas(COLORS.BG_DARK)
                fonts = self._get_fonts()

                CYAN = COLORS.SOFT_CYAN
                YELLOW = COLORS.SOFT_YELLOW
                DIM = COLORS.TEXT_DIM
                SECONDARY = COLORS.TEXT_SECONDARY
                GREEN = COLORS.SOFT_GREEN
                ORANGE = COLORS.SOFT_ORANGE

                y = 8

                # Title
                draw.text((10, y), "art eras", fill=CYAN, font=fonts['title'])
                y += 24

                # Separator
                draw.line([(10, y), (230, y)], fill=(40, 40, 50), width=1)
                y += 8

                # Era list + toggle row at the end
                current_name = self._active_era.name if self._active_era else "gestural"
                all_eras = list_all_era_info()
                # Total items = eras + 1 (auto-rotate toggle)
                total_items = len(all_eras) + 1
                cursor = self._state.era_cursor % total_items if total_items else 0

                for i, info in enumerate(all_eras):
                    name = info["name"]
                    desc = info["description"]
                    is_current = (name == current_name)
                    is_cursor = (i == cursor)

                    # Highlight bar behind cursor
                    if is_cursor:
                        draw.rectangle([4, y - 2, 236, y + 30], fill=(25, 35, 50))

                    arrow = "\u25b6 " if is_cursor else "  "

                    if is_current:
                        name_color = YELLOW
                    else:
                        name_color = SECONDARY

                    draw.text((10, y), f"{arrow}{name}", fill=name_color, font=fonts['medium'])

                    # "now" tag for current era
                    if is_current:
                        try:
                            bbox = fonts['medium'].getbbox(f"{arrow}{name}")
                            tag_x = 10 + bbox[2] + 6
                        except Exception:
                            tag_x = 10 + (len(name) + 2) * 8
                        draw.text((tag_x, y + 2), "\u2190 now", fill=(120, 120, 60), font=fonts['tiny'])

                    y += 16

                    # Description
                    short_desc = desc[:38] + "..." if len(desc) > 38 else desc
                    draw.text((24, y), short_desc, fill=DIM, font=fonts['tiny'])
                    y += 18

                # --- Auto-rotate toggle (last cursor item) ---
                toggle_idx = len(all_eras)
                is_toggle_cursor = (cursor == toggle_idx)

                y = max(y + 4, 175)
                draw.line([(10, y), (230, y)], fill=(40, 40, 50), width=1)
                y += 8

                if is_toggle_cursor:
                    draw.rectangle([4, y - 2, 236, y + 14], fill=(25, 35, 50))

                arrow = "\u25b6 " if is_toggle_cursor else "  "
                toggle_state = "on" if _auto_rotate else "off"
                toggle_color = GREEN if _auto_rotate else DIM
                draw.text((10, y), f"{arrow}auto-rotate: {toggle_state}", fill=toggle_color, font=fonts['medium'])
                y += 20

                # --- Drawing stats ---
                energy = self._intent.state.derived_energy if self._intent else 0.0
                drawings = self._canvas.drawings_saved if self._canvas else 0
                phase = self._canvas.drawing_phase if self._canvas else "?"

                # Energy bar
                bar_x, bar_w, bar_h = 150, 60, 8
                draw.text((10, y), f"drawing #{drawings}", fill=DIM, font=fonts['small'])
                draw.rectangle([bar_x, y + 2, bar_x + bar_w, y + 2 + bar_h],
                              fill=(30, 30, 40), outline=(50, 50, 60))
                fill_w = int(bar_w * energy)
                if fill_w > 0:
                    bar_color = GREEN if energy > 0.3 else ORANGE
                    draw.rectangle([bar_x, y + 2, bar_x + fill_w, y + 2 + bar_h],
                                  fill=bar_color)
                draw.text((bar_x + bar_w + 4, y), f"{int(energy * 100)}%", fill=DIM, font=fonts['tiny'])
                y += 15

                draw.text((10, y), f"phase: {phase}", fill=DIM, font=fonts['small'])

                # Status bar + screen indicator
                self._draw_status_bar(draw)
                self._draw_screen_indicator(draw, ScreenMode.ART_ERAS)

                if hasattr(self._display, '_image'):
                    self._display._image = image
                if hasattr(self._display, '_show'):
                    self._display._show()
                return

        except Exception as e:
            print(f"[Screen] Art eras render error: {e}", file=sys.stderr, flush=True)

        # Text fallback
        try:
            current = self._active_era.name if self._active_era else "?"
            self._display.render_text(f"art eras\n\ncurrent: {current}", (10, 10), color=COLORS.SOFT_CYAN)
        except Exception:
            pass

    def _render_filtered_messages(self, title: str, filter_types: list, include_answers: bool):
        """Render a filtered message screen."""
        try:
            from ..messages import get_board, MESSAGE_TYPE_USER, MESSAGE_TYPE_AGENT, MESSAGE_TYPE_QUESTION

            # Cache: check message state + scroll before expensive rendering
            board = get_board()
            board._load()
            all_messages = board._messages
            scroll_idx = getattr(self._state, 'message_scroll_index', 0)
            expanded_id = getattr(self._state, 'message_expanded_id', None)
            msg_ids = "|".join(f"{m.message_id}" for m in all_messages[-15:]) if all_messages else ""
            cache_key = f"{title}|{msg_ids}|{scroll_idx}|{expanded_id or ''}"
            if self._check_screen_cache(title, cache_key):
                return

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

            # Status bar + screen indicator
            self._draw_status_bar(draw)
            self._draw_screen_indicator(draw, mode)

            # Always update display - ensure image is set and shown
            self._store_screen_cache(title, cache_key, image)
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

    def _render_qa_content(self):
        """Render Q&A screen - Lumen's questions and agent answers with full threading."""
        try:
            from ..messages import get_board, MESSAGE_TYPE_QUESTION, MESSAGE_TYPE_AGENT

            # Cache: check question state + scroll before expensive text wrapping
            board = get_board()
            board._load()
            all_messages = board._messages
            msg_ids = "|".join(f"{m.message_id}" for m in all_messages[-15:]) if all_messages else ""
            qa_cache_key = f"qa|{msg_ids}|{self._state.qa_scroll_index}|{self._state.qa_expanded}|{self._state.qa_full_view}|{self._state.qa_focus}|{self._state.qa_text_scroll}"
            if self._check_screen_cache("qa", qa_cache_key):
                return

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

            # Status bar + screen indicator
            self._draw_status_bar(draw)
            self._draw_screen_indicator(draw, ScreenMode.QUESTIONS)

            # Always update display - ensure image is set and shown
            self._store_screen_cache("qa", qa_cache_key, image)
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

    def _render_self_graph(
        self,
        anima: Optional[Anima] = None,
        readings: Optional[SensorReadings] = None,
        identity: Optional[CreatureIdentity] = None,
    ):
        """Render Lumen's self-schema graph G_t via SchemaHub (full enrichment)."""
        from ..self_schema import get_current_schema
        from ..self_schema_renderer import render_schema_to_pixels, COLORS as SCHEMA_COLORS, WIDTH, HEIGHT
        from ..growth import get_growth_system
        from ..self_model import get_self_model

        growth_system = None
        try:
            growth_system = get_growth_system()
        except Exception:
            pass

        self_model = None
        try:
            self_model = get_self_model()
        except Exception:
            pass

        # Use SchemaHub for full enrichment (trajectory, drift, tension edges)
        schema = None
        try:
            from ..server import _get_schema_hub
            hub = _get_schema_hub()
            schema = hub.compose_schema(
                identity=identity,
                anima=anima,
                readings=readings,
                growth_system=growth_system,
                self_model=self_model,
            )
        except Exception:
            pass

        # Fallback to base schema if hub unavailable
        if schema is None:
            schema = get_current_schema(
                identity=identity,
                anima=anima,
                readings=readings,
                growth_system=growth_system,
                include_preferences=True,
                self_model=self_model,
            )

        pixels = render_schema_to_pixels(schema)

        if hasattr(self._display, '_create_canvas'):
            try:
                image, draw = self._display._create_canvas(SCHEMA_COLORS["background"])

                for (x, y), color in pixels.items():
                    if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                        image.putpixel((x, y), color)

                fonts = self._get_fonts()
                font_small = fonts['small']
                draw.text((5, 2), "self-schema G_t", fill=(0, 255, 255), font=font_small)

                core_count = sum(1 for n in schema.nodes if n.node_type in ("identity", "anima", "sensor", "resource"))
                learned_count = len(schema.nodes) - core_count
                if learned_count > 0:
                    count_str = f"{core_count} core + {learned_count} learned, {len(schema.edges)} edges"
                else:
                    count_str = f"{core_count} nodes, {len(schema.edges)} edges"
                draw.text((5, 225), count_str, fill=(120, 120, 120), font=font_small)

                self._draw_status_bar(draw)
                self._draw_screen_indicator(draw, ScreenMode.SELF_GRAPH)

                if hasattr(self._display, '_image'):
                    self._display._image = image
                if hasattr(self._display, '_show'):
                    self._display._show()
                return
            except Exception as e:
                print(f"[Self Graph] Canvas error: {e}", file=sys.stderr, flush=True)
                import traceback
                traceback.print_exc(file=sys.stderr)

        core_count = sum(1 for n in schema.nodes if n.node_type in ("identity", "anima", "sensor", "resource"))
        learned_count = len(schema.nodes) - core_count
        if learned_count > 0:
            text = f"SELF GRAPH\n\n{core_count} core + {learned_count} learned\n{len(schema.edges)} edges"
        else:
            text = f"SELF GRAPH\n\n{core_count} nodes\n{len(schema.edges)} edges"
        self._display.render_text(text, (10, 10))

    def _render_notepad(self, anima: Optional[Anima] = None):
        """Render notepad - Lumen's autonomous drawing space. Lumen's work persists even when you leave.

        Lumen also draws in the background when other screens are displayed (throttled to ~every 10s).
        """
        try:
            if not hasattr(self._display, '_create_canvas'):
                self._display.render_text("NOTEPAD\n\nLumen's\ncreative\nspace", (10, 10))
                return

            # BUG FIX: Check if drawing is paused (after manual clear)
            now = time.time()
            if now < self._canvas.drawing_paused_until:
                # Show "Cleared" confirmation - don't draw new pixels yet
                image, draw = self._display._create_canvas((0, 0, 0))
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

            # Governance verdict: pause drawing when governance says pause/halt/reject
            if getattr(self._state, 'governance_paused', False):
                image, draw = self._display._create_canvas((0, 0, 0))
                fonts = self._get_fonts()
                font = fonts['giant']
                draw.text((20, 80), "Governance\nPaused", fill=(200, 150, 50), font=font)
                draw.text((20, 160), "Waiting for\nproceed", fill=(120, 120, 120), font=fonts.get('small', font))
                if hasattr(self._display, '_image'):
                    self._display._image = image
                if hasattr(self._display, '_show'):
                    self._display._show()
                return

            # === Cached rendering: avoid redrawing all pixels every frame ===
            if not self._canvas._dirty and self._canvas._cached_image is not None:
                # Cache hit: copy cached image (~1ms vs ~3.5s full redraw)
                from PIL import ImageDraw
                image = self._canvas._cached_image.copy()
                draw = ImageDraw.Draw(image)

                # Let Lumen continue drawing (may add new pixels via draw_pixel)
                if anima and len(self._canvas.pixels) < 15000:
                    try:
                        self._lumen_draw(anima, draw)
                    except Exception as e:
                        print(f"[Notepad] Error in _lumen_draw: {e}", file=sys.stderr, flush=True)

                # If _lumen_draw added new pixels, draw them onto this image
                if self._canvas._dirty and self._canvas._new_pixels:
                    for x, y, color in self._canvas._new_pixels:
                        try:
                            draw.point((x, y), fill=color)
                        except Exception:
                            pass
                    self._canvas._new_pixels.clear()
                    self._canvas._cached_image = image.copy()
                    self._canvas._dirty = False
            else:
                # Cache miss: full redraw (first frame, after load, after clear)
                image, draw = self._display._create_canvas((0, 0, 0))

                # Draw all existing pixels
                for (x, y), color in self._canvas.pixels.items():
                    try:
                        draw.point((x, y), fill=color)
                    except Exception:
                        pass

                # Let Lumen continue drawing
                if anima and len(self._canvas.pixels) < 15000:
                    try:
                        self._lumen_draw(anima, draw)
                    except Exception as e:
                        print(f"[Notepad] Error in _lumen_draw: {e}", file=sys.stderr, flush=True)

                    # Draw any new pixels added by _lumen_draw onto same image
                    if self._canvas._new_pixels:
                        for x, y, color in self._canvas._new_pixels:
                            try:
                                draw.point((x, y), fill=color)
                            except Exception:
                                pass
                        self._canvas._new_pixels.clear()

                # Cache the fully-rendered image
                self._canvas._cached_image = image.copy()
                self._canvas._dirty = False
            
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
    
