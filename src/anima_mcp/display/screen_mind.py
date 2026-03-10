"""
Display Screens - Mind screen mixin.

Renders neural activity, inner life, learning, and self-graph screens.
"""

import sys
import time
from typing import Optional, Dict, Any

from .design import COLORS
from ..anima import Anima
from ..sensors.base import SensorReadings
from ..identity.store import CreatureIdentity
from ..learning_visualization import LearningVisualizer


class MindMixin:
    """Mixin for mind-group screens (neural, inner_life, learning, self_graph)."""

    def _render_neural(self, anima: Optional[Anima], readings: Optional[SensorReadings]):
        """Render neural activity screen - EEG frequency band visualization."""
        if not readings:
            self._display.render_text("neural\n\nno data", (10, 10))
            return

        raw = readings.to_dict()
        neural_key = (
            f"{raw.get('eeg_delta_power', 0):.1f}|{raw.get('eeg_theta_power', 0):.1f}|"
            f"{raw.get('eeg_alpha_power', 0):.1f}|{raw.get('eeg_beta_power', 0):.1f}|"
            f"{raw.get('eeg_gamma_power', 0):.1f}"
        )
        if anima:
            neural_key += f"|{anima.warmth:.1f}|{anima.clarity:.1f}|{anima.stability:.1f}|{anima.presence:.1f}"
        if self._check_screen_cache("neural", neural_key):
            return

        try:
            if not hasattr(self._display, '_create_canvas'):
                self._render_neural_text_fallback(readings)
                return

            image, draw = self._display._create_canvas(COLORS.BG_DARK)

            fonts = self._get_fonts()
            font_small = fonts['small']
            font_medium = fonts['medium']
            font_title = fonts['title']
            font_tiny = fonts['tiny']
            font_micro = fonts['micro']

            from .design import lighten_color, dim_color

            DIM = COLORS.TEXT_DIM
            SECONDARY = COLORS.TEXT_SECONDARY

            # Band colors from design system — each band has a distinct identity
            bands = [
                ("delta",  raw.get("eeg_delta_power") or 0, COLORS.SOFT_BLUE,   "0.5–4 Hz",  "deep rest"),
                ("theta",  raw.get("eeg_theta_power") or 0, COLORS.SOFT_PURPLE, "4–8 Hz",    "meditation"),
                ("alpha",  raw.get("eeg_alpha_power") or 0, COLORS.SOFT_CYAN,   "8–13 Hz",   "awareness"),
                ("beta",   raw.get("eeg_beta_power") or 0,  COLORS.SOFT_GREEN,  "13–30 Hz",  "focus"),
                ("gamma",  raw.get("eeg_gamma_power") or 0, COLORS.SOFT_ORANGE, "30+ Hz",    "cognition"),
            ]

            # Dominant band
            dominant_idx = max(range(len(bands)), key=lambda i: bands[i][1])
            dominant_name  = bands[dominant_idx][0]
            dominant_value = bands[dominant_idx][1]
            dominant_color = bands[dominant_idx][2]
            dominant_desc  = bands[dominant_idx][4]

            # Title + dominant info on one header row
            draw.text((10, 6), "neural activity", fill=COLORS.SOFT_CYAN, font=font_title)
            draw.line([(10, 28), (230, 28)], fill=(30, 30, 40), width=1)
            draw.text((10, 32), "dominant:", fill=DIM, font=font_small)
            draw.text((82, 32), dominant_name, fill=dominant_color, font=font_small)
            draw.text((150, 32), f"{dominant_value:.0%}", fill=dominant_color, font=font_small)

            # ---- Vertical bar chart ----
            bar_area_top    = 58
            bar_area_bottom = 186
            bar_area_height = bar_area_bottom - bar_area_top
            bar_width       = 28
            bar_gap         = 12
            total_bars_width = len(bands) * bar_width + (len(bands) - 1) * bar_gap
            bar_start_x     = (240 - total_bars_width) // 2

            greek = {"delta": "\u03b4", "theta": "\u03b8", "alpha": "\u03b1", "beta": "\u03b2", "gamma": "\u03b3"}

            for i, (name, value, color, freq, desc) in enumerate(bands):
                is_dominant = (i == dominant_idx)
                x = bar_start_x + i * (bar_width + bar_gap)

                # Dim non-dominant bands — dominant reads clearly at a glance
                draw_color = color if is_dominant else dim_color(color, 0.35)

                # Bar track (slightly visible for non-dominant)
                track_fill = (15, 15, 22) if is_dominant else (12, 12, 18)
                draw.rectangle([x, bar_area_top, x + bar_width, bar_area_bottom], fill=track_fill)

                # Filled bar (bottom-up)
                fill_height = int(value * bar_area_height)
                if fill_height > 0:
                    bar_top = bar_area_bottom - fill_height
                    draw.rectangle([x, bar_top, x + bar_width, bar_area_bottom], fill=draw_color)
                    if is_dominant and fill_height > 3:
                        bright = lighten_color(color, 60)
                        draw.rectangle([x, bar_top, x + bar_width, bar_top + 2], fill=bright)

                # Greek letter below bar — full color for dominant, dim for others
                letter = greek.get(name, name[0])
                letter_color = color if is_dominant else dim_color(color, 0.45)
                draw.text((x + bar_width // 2 - 4, bar_area_bottom + 5), letter,
                          fill=letter_color, font=font_medium)

            # ---- Bottom: description of dominant band ----
            y_desc = 206
            draw.line([(10, y_desc - 4), (230, y_desc - 4)], fill=(30, 30, 40), width=1)
            draw.text((10, y_desc), f"{dominant_name} · {dominant_desc}", fill=dominant_color, font=font_small)
            draw.text((10, y_desc + 14), bands[dominant_idx][3], fill=DIM, font=font_tiny)

            self._draw_status_bar(draw)

            self._store_screen_cache("neural", neural_key, image)
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
        lines = ["neural activity", ""]
        for band in ["delta", "theta", "alpha", "beta", "gamma"]:
            val = raw.get(f"eeg_{band}_power") or 0
            bar = "#" * int(val * 20)
            lines.append(f"{band:6s} {val:.0%} {bar}")
        self._display.render_text("\n".join(lines), (10, 10))

    def _render_inner_life(self):
        """Render inner life screen -- actual cognitive and emotional state."""
        shm = self._shm_data or {}
        if not shm:
            self._display.render_text("inner life\n\nwaiting...", (10, 10), color=COLORS.TEXT_DIM)
            return

        # Extract signals from SHM
        meta = shm.get("metacognition", {})
        il = shm.get("inner_life", {})
        drives = il.get("drives", {})
        activity = shm.get("activity", {})
        learning = shm.get("learning", {})
        agency = learning.get("agency", {})
        prefs = learning.get("preferences", {})
        pred = learning.get("prediction_accuracy", {})

        surprise = meta.get("surprise", 0.0)
        confidence = meta.get("prediction_confidence", 0.5)
        exploration = agency.get("exploration_rate", 0.5)
        satisfaction = prefs.get("satisfaction", 0.5)
        activity_level = activity.get("level", "active")
        strongest_drive = il.get("strongest_drive")
        total_patterns = pred.get("total_patterns", 0)
        d_warmth = drives.get("warmth", 0.0)
        d_clarity = drives.get("clarity", 0.0)
        d_stability = drives.get("stability", 0.0)
        d_presence = drives.get("presence", 0.0)

        cache_key = (
            f"{surprise:.1f}|{confidence:.1f}|{exploration:.1f}|{satisfaction:.1f}|"
            f"{d_warmth:.1f}|{d_clarity:.1f}|{d_stability:.1f}|{d_presence:.1f}|"
            f"{activity_level}|{total_patterns}"
        )
        if self._check_screen_cache("inner_life", cache_key):
            return

        if not hasattr(self._display, '_create_canvas'):
            self._render_inner_life_text_fallback(shm)
            return

        try:
            from .design import lighten_color, blend_color
            image, draw = self._display._create_canvas(COLORS.BG_DARK)
            fonts = self._get_fonts()
            f_title = fonts['title']
            f_small = fonts['small']
            f_tiny = fonts['tiny']
            f_micro = fonts['micro']

            DIM = COLORS.TEXT_DIM
            SECONDARY = COLORS.TEXT_SECONDARY

            # -- Title --
            draw.text((10, 6), "inner life", fill=COLORS.SOFT_CYAN, font=f_title)

            # -- State summary --
            if surprise > 0.6:
                state_word, state_color = "surprised", COLORS.SOFT_CORAL
            elif exploration > 0.6:
                state_word, state_color = "exploring", COLORS.SOFT_PURPLE
            elif confidence > 0.7 and satisfaction > 0.7:
                state_word, state_color = "settled", COLORS.SOFT_GREEN
            elif satisfaction < 0.3:
                state_word, state_color = "unsatisfied", COLORS.SOFT_ORANGE
            else:
                state_word, state_color = "aware", COLORS.SOFT_BLUE
            draw.text((10, 26), state_word, fill=state_color, font=f_small)

            # -- Hero signal bars --
            draw.line([(10, 40), (230, 40)], fill=(30, 30, 40), width=1)

            hero_signals = [
                ("surprise",     surprise,     COLORS.SOFT_GREEN,  COLORS.SOFT_CORAL),
                ("exploring",    exploration,  COLORS.SOFT_BLUE,   COLORS.SOFT_PURPLE),
                ("confidence",   confidence,   COLORS.SOFT_ORANGE, COLORS.SOFT_CYAN),
                ("satisfaction", satisfaction, COLORS.SOFT_CORAL,  COLORS.SOFT_GREEN),
            ]

            BAR_X = 10
            BAR_W = 120
            BAR_H = 10
            y = 46

            for label, value, color_low, color_high in hero_signals:
                bar_color = blend_color(color_low, color_high, value)

                # Bar track
                draw.rectangle([BAR_X, y, BAR_X + BAR_W, y + BAR_H], fill=(15, 15, 22))

                # Bar fill
                fill_w = int(value * BAR_W)
                if fill_w > 0:
                    draw.rectangle([BAR_X, y, BAR_X + fill_w, y + BAR_H], fill=bar_color)
                    if fill_w > 3:
                        bright = lighten_color(bar_color, 60)
                        draw.rectangle([BAR_X + fill_w - 2, y, BAR_X + fill_w, y + BAR_H],
                                      fill=bright)

                # Label + value
                draw.text((BAR_X + BAR_W + 6, y - 1), label, fill=SECONDARY, font=f_tiny)
                draw.text((214, y - 1), f"{value:.0%}", fill=bar_color, font=f_tiny)

                y += 18

            # -- Drives section: horizontal bars, same language as hero signals above --
            y = 122
            draw.text((10, y), "drives", fill=DIM, font=f_tiny)
            draw.line([(50, y + 6), (230, y + 6)], fill=(30, 30, 40), width=1)
            y += 14

            drive_data = [
                ("warmth",    d_warmth,    COLORS.SOFT_ORANGE),
                ("clarity",   d_clarity,   COLORS.SOFT_CYAN),
                ("stability", d_stability, COLORS.SOFT_GREEN),
                ("presence",  d_presence,  COLORS.SOFT_PURPLE),
            ]

            DRIVE_BAR_X = BAR_X
            DRIVE_BAR_W = 90   # narrower than hero bars — clearly a different register

            for label, drive_val, color in drive_data:
                is_strongest = (strongest_drive == label)

                # Strongest drive: small dot on left as indicator
                if is_strongest:
                    draw.ellipse([DRIVE_BAR_X - 7, y + 1, DRIVE_BAR_X - 3, y + 5],
                                 fill=COLORS.TEXT_PRIMARY)

                # Bar track
                draw.rectangle([DRIVE_BAR_X, y, DRIVE_BAR_X + DRIVE_BAR_W, y + 7], fill=(15, 15, 22))

                # Bar fill
                fill_w = int(drive_val * DRIVE_BAR_W)
                if fill_w > 0:
                    draw.rectangle([DRIVE_BAR_X, y, DRIVE_BAR_X + fill_w, y + 7], fill=color)
                    if fill_w > 3:
                        bright = lighten_color(color, 50)
                        draw.rectangle([DRIVE_BAR_X + fill_w - 2, y, DRIVE_BAR_X + fill_w, y + 7], fill=bright)

                # Label + value (right of bar)
                label_color = color if is_strongest else SECONDARY
                draw.text((DRIVE_BAR_X + DRIVE_BAR_W + 6, y - 1), label[:4], fill=label_color, font=f_tiny)
                draw.text((DRIVE_BAR_X + DRIVE_BAR_W + 38, y - 1), f"{drive_val:.0%}", fill=color, font=f_tiny)
                y += 14

            # -- Footer (one compact line) --
            y = max(y + 4, 208)
            draw.line([(10, y), (230, y)], fill=(30, 30, 40), width=1)
            y += 4

            level_colors = {"active": COLORS.SOFT_GREEN, "drowsy": COLORS.SOFT_YELLOW, "resting": COLORS.SOFT_PURPLE}
            draw.text((10, y), activity_level, fill=level_colors.get(activity_level, DIM), font=f_tiny)

            if total_patterns:
                draw.text((68, y), f"{total_patterns} patterns", fill=DIM, font=f_tiny)

            if strongest_drive:
                drive_colors = {"warmth": COLORS.SOFT_ORANGE, "clarity": COLORS.SOFT_CYAN,
                               "stability": COLORS.SOFT_GREEN, "presence": COLORS.SOFT_PURPLE}
                draw.text((155, y), f"→ {strongest_drive[:4]}",
                         fill=drive_colors.get(strongest_drive, SECONDARY), font=f_tiny)
            else:
                draw.text((155, y), "content", fill=COLORS.SOFT_GREEN, font=f_tiny)

            self._draw_status_bar(draw)

            self._store_screen_cache("inner_life", cache_key, image)
            if hasattr(self._display, '_image'):
                self._display._image = image
            if hasattr(self._display, '_show'):
                self._display._show()

        except Exception as e:
            import traceback
            print(f"[Inner Life Screen] Error: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            self._render_inner_life_text_fallback(shm)

    def _render_inner_life_text_fallback(self, shm: dict):
        """Text-only fallback for inner life screen."""
        meta = shm.get("metacognition", {})
        il = shm.get("inner_life", {})
        drives = il.get("drives", {})
        lines = [
            "INNER LIFE", "",
            f"surprise:   {meta.get('surprise', 0):.0%}",
            f"confidence: {meta.get('prediction_confidence', 0):.0%}",
            "",
        ]
        for dim in ["warmth", "clarity", "stability", "presence"]:
            val = drives.get(dim, 0)
            bar = "#" * int(val * 20)
            lines.append(f"{dim[:4]:4s} drive {val:.0%} {bar}")
        self._display.render_text("\n".join(lines), (10, 10))

    def _render_learning(self, anima: Optional[Anima], readings: Optional[SensorReadings]):
        """Render learning visualization screen - comfort zones and why Lumen feels what it feels."""
        if not anima or not readings:
            self._display.render_text("learning\n\nno data", (10, 10))
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
                self._display.render_text("learning\n\nloading...", (10, 10))
                return

            # Create canvas for visual rendering
            if hasattr(self._display, '_create_canvas'):
                image, draw = self._display._create_canvas(COLORS.BG_DARK)
            else:
                # Fallback to text-only if no canvas support
                self._render_learning_text_fallback(summary, readings, anima)
                return

            # Design system palette
            DIM      = COLORS.TEXT_DIM
            SECOND   = COLORS.TEXT_SECONDARY
            C_OK     = COLORS.SOFT_GREEN
            C_WARN   = COLORS.SOFT_YELLOW
            C_BAD    = COLORS.SOFT_CORAL
            C_ORANGE = COLORS.SOFT_ORANGE
            C_CYAN   = COLORS.SOFT_CYAN
            C_PURPLE = COLORS.SOFT_PURPLE
            BG_BAR   = (18, 22, 32)        # bar track background
            ZONE_FG  = (20, 45, 20)        # comfort zone tint

            # Use cached fonts
            fonts = self._get_fonts()
            f_label = fonts['tiny']     # sensor section labels + insight text
            f_title = fonts['default']  # mood state title (prominent standalone)

            y_offset = 6
            bar_x = 13
            bar_width = 175
            bar_height = 10

            # Get comfort zones from summary
            comfort_zones = summary.get("comfort_zones", [])
            cal = summary.get("current_calibration", {})

            # Find humidity and temp zones
            humidity_zone = next((z for z in comfort_zones if z["sensor"] == "humidity"), None)
            temp_zone = next((z for z in comfort_zones if z["sensor"] == "ambient_temp"), None)

            # === Title: mood state ===
            actual_mood = anima.feeling().get("mood", "neutral")
            if actual_mood == "stressed":
                title, title_color = "stressed", C_BAD
            elif actual_mood == "overheated":
                title, title_color = "overheated", C_ORANGE
            elif actual_mood in ("content", "alert"):
                title, title_color = "comfortable", C_OK
            else:
                # Check comfort zones as fallback
                statuses = [z["status"] for z in comfort_zones]
                if "extreme" in statuses:
                    title, title_color = "stressed", C_BAD
                elif "uncomfortable" in statuses:
                    title, title_color = "adjusting", C_WARN
                else:
                    title, title_color = "comfortable", C_OK

            draw.text((10, y_offset), title, fill=title_color, font=f_title)
            if showing_stale or self._learning_cache_refreshing:
                draw.text((180, y_offset), "\u21bb", fill=C_CYAN, font=f_title)
            y_offset += 22

            draw.line([(10, y_offset), (230, y_offset)], fill=(30, 42, 62), width=1)
            y_offset += 8

            # === HUMIDITY BAR ===
            if humidity_zone:
                humidity_current = humidity_zone["current"] or 0
                humidity_ideal = humidity_zone["ideal"]
                h_status = humidity_zone["status"]
                h_color = C_OK if h_status == "comfortable" else C_WARN if h_status == "uncomfortable" else C_BAD

                # Left-edge accent + section label
                draw.rectangle([6, y_offset, 9, y_offset + 9], fill=C_CYAN)
                draw.text((bar_x, y_offset), f"humidity  {humidity_current:.0f}%", fill=SECOND, font=f_label)
                y_offset += 12

                draw.rectangle([bar_x, y_offset, bar_x + bar_width, y_offset + bar_height],
                              fill=BG_BAR, outline=(40, 52, 72))
                c_min, c_max = humidity_zone["comfortable_range"]
                comfort_x1 = bar_x + int(c_min / 100.0 * bar_width)
                comfort_x2 = bar_x + int(c_max / 100.0 * bar_width)
                draw.rectangle([comfort_x1, y_offset + 1, comfort_x2, y_offset + bar_height - 1], fill=ZONE_FG)

                ideal_x = bar_x + int(humidity_ideal / 100.0 * bar_width)
                draw.line([ideal_x, y_offset, ideal_x, y_offset + bar_height], fill=C_OK, width=1)
                current_x = bar_x + int(min(100, humidity_current) / 100.0 * bar_width)
                draw.rectangle([current_x - 2, y_offset - 1, current_x + 2, y_offset + bar_height + 1], fill=h_color)
                y_offset += bar_height + 8

            # === TEMPERATURE BAR ===
            if temp_zone:
                temp_current = temp_zone["current"] or 0
                temp_ideal = temp_zone["ideal"]
                t_status = temp_zone["status"]
                t_range = temp_zone["comfortable_range"]
                t_color = C_OK if t_status == "comfortable" else C_WARN if t_status == "uncomfortable" else C_BAD

                draw.rectangle([6, y_offset, 9, y_offset + 9], fill=C_ORANGE)
                draw.text((bar_x, y_offset), f"temp  {temp_current:.1f}\u00b0C", fill=SECOND, font=f_label)
                y_offset += 12

                # Normalize temp to 10-35 deg C range for display
                t_min_display, t_max_display = 10, 35
                def temp_to_x(t):
                    return bar_x + int((t - t_min_display) / (t_max_display - t_min_display) * bar_width)

                draw.rectangle([bar_x, y_offset, bar_x + bar_width, y_offset + bar_height],
                              fill=BG_BAR, outline=(40, 52, 72))
                comfort_x1 = max(bar_x, temp_to_x(t_range[0]))
                comfort_x2 = min(bar_x + bar_width, temp_to_x(t_range[1]))
                draw.rectangle([comfort_x1, y_offset + 1, comfort_x2, y_offset + bar_height - 1], fill=ZONE_FG)

                ideal_x = temp_to_x(temp_ideal)
                draw.line([ideal_x, y_offset, ideal_x, y_offset + bar_height], fill=C_OK, width=1)
                current_x = max(bar_x, min(bar_x + bar_width, temp_to_x(temp_current)))
                draw.rectangle([current_x - 2, y_offset - 1, current_x + 2, y_offset + bar_height + 1], fill=t_color)
                y_offset += bar_height + 8

            # === WARMTH (Internal State) ===
            warmth = anima.warmth
            warmth_color = C_ORANGE if warmth > 0.6 else C_CYAN if warmth < 0.3 else C_WARN

            draw.rectangle([6, y_offset, 9, y_offset + 9], fill=C_ORANGE)
            draw.text((bar_x, y_offset), f"warmth  {warmth:.0%}", fill=SECOND, font=f_label)
            y_offset += 12

            draw.rectangle([bar_x, y_offset, bar_x + bar_width, y_offset + bar_height],
                          fill=BG_BAR, outline=(40, 52, 72))
            # Comfort zone: 0.3 - 0.7 is comfortable for internal states
            comfort_x1 = bar_x + int(0.3 * bar_width)
            comfort_x2 = bar_x + int(0.7 * bar_width)
            draw.rectangle([comfort_x1, y_offset + 1, comfort_x2, y_offset + bar_height - 1], fill=ZONE_FG)
            ideal_x = bar_x + int(0.5 * bar_width)
            draw.line([ideal_x, y_offset, ideal_x, y_offset + bar_height], fill=C_OK, width=1)
            current_x = bar_x + int(warmth * bar_width)
            draw.rectangle([current_x - 2, y_offset - 1, current_x + 2, y_offset + bar_height + 1], fill=warmth_color)
            y_offset += bar_height + 8

            # === STABILITY (Internal State) ===
            stability = anima.stability
            stab_color = C_OK if stability > 0.6 else C_WARN if stability > 0.3 else C_BAD

            draw.rectangle([6, y_offset, 9, y_offset + 9], fill=C_OK)
            draw.text((bar_x, y_offset), f"stability  {stability:.0%}", fill=SECOND, font=f_label)
            y_offset += 12

            draw.rectangle([bar_x, y_offset, bar_x + bar_width, y_offset + bar_height],
                          fill=BG_BAR, outline=(40, 52, 72))
            # Comfort zone: 0.5 - 1.0 is comfortable for stability (higher is better)
            comfort_x1 = bar_x + int(0.5 * bar_width)
            comfort_x2 = bar_x + int(1.0 * bar_width)
            draw.rectangle([comfort_x1, y_offset + 1, comfort_x2, y_offset + bar_height - 1], fill=ZONE_FG)
            ideal_x = bar_x + int(0.8 * bar_width)
            draw.line([ideal_x, y_offset, ideal_x, y_offset + bar_height], fill=C_OK, width=1)
            current_x = bar_x + int(stability * bar_width)
            draw.rectangle([current_x - 2, y_offset - 1, current_x + 2, y_offset + bar_height + 1], fill=stab_color)
            y_offset += bar_height + 10

            # === INSIGHT TEXT ===
            mood = anima.feeling().get("mood", "neutral")
            insight_lines = []

            if mood == "stressed":
                # Explain why stressed - only temperature matters for Pi
                if readings.ambient_temp_c and readings.ambient_temp_c > 38:
                    insight_lines.append(f"temp {readings.ambient_temp_c:.0f}\u00b0C > 38\u00b0C limit")
                    insight_lines.append("seeking cooler conditions")
                elif readings.ambient_temp_c and readings.ambient_temp_c < 10:
                    insight_lines.append(f"temp {readings.ambient_temp_c:.0f}\u00b0C < 10\u00b0C limit")
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
                    text = insights[0].get("title", "")
                    # Word-wrap at boundaries (not mid-word)
                    words = text.split()
                    line, max_chars = "", 28
                    for word in words:
                        if len(line) + len(word) + (1 if line else 0) <= max_chars:
                            line = (line + " " + word) if line else word
                        else:
                            insight_lines.append(line)
                            line = word
                    if line:
                        insight_lines.append(line)
                else:
                    insight_lines.append("learning from environment...")

            # Draw insight lines
            for i, line in enumerate(insight_lines[:3]):
                color = C_PURPLE if mood not in ("stressed", "overheated") else C_ORANGE
                draw.text((bar_x, y_offset + i * 12), line, fill=color, font=f_label)

            # Status bar
            self._draw_status_bar(draw)

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
            self._display.render_text(f"learning\n\nerror:\n{error_msg}", (10, 10))

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

    def _render_self_graph(
        self,
        anima: Optional[Anima] = None,
        readings: Optional[SensorReadings] = None,
        identity: Optional[CreatureIdentity] = None,
    ):
        """Render Lumen's self-schema graph G_t.

        Uses the same enriched schema as the web dashboard -- one source of truth.
        Reads hub.schema_history[-1] (no side effects). Falls back to
        get_current_schema() if hub has no history yet.
        """
        from ..self_schema import get_current_schema
        from ..self_schema_renderer import render_schema_to_pixels, COLORS as SCHEMA_COLORS, WIDTH, HEIGHT

        # Use enriched schema from hub if available (same as web dashboard)
        # schema_hub is set by server.py after ScreenRenderer creation
        hub = getattr(self, 'schema_hub', None)
        if hub and hub.schema_history:
            schema = hub.schema_history[-1]
        else:
            # Fallback: base schema (before hub is connected or has history)
            from ..growth import get_growth_system
            from ..self_model import get_self_model
            schema = get_current_schema(
                identity=identity, anima=anima, readings=readings,
                growth_system=get_growth_system(), include_preferences=True,
                self_model=get_self_model(),
            )

        # Cache: schema node/edge count + node names hash
        sg_key = f"{len(schema.nodes)}|{len(schema.edges)}|{hash(tuple(n.node_id for n in schema.nodes)) % 100000}"
        if self._check_screen_cache("self_graph", sg_key):
            return

        if not hasattr(self._display, '_create_canvas'):
            text = f"self graph\n\n{len(schema.nodes)} nodes\n{len(schema.edges)} edges"
            self._display.render_text(text, (10, 10))
            return

        try:
            image, draw = self._display._create_canvas(SCHEMA_COLORS["background"])
            fonts = self._get_fonts()
            font_small = fonts['small']

            pixels = render_schema_to_pixels(schema)
            for (x, y), color in pixels.items():
                if 0 <= x < WIDTH and 0 <= y < HEIGHT:
                    image.putpixel((x, y), color)

            draw.text((5, 2), "self-schema G_t", fill=COLORS.SOFT_CYAN, font=font_small)

            count_str = f"{len(schema.nodes)} nodes, {len(schema.edges)} edges"
            draw.text((5, 225), count_str, fill=COLORS.TEXT_DIM, font=font_small)

            # Compact legend -- colored dots with labels
            font_micro = fonts['micro']
            legend = [
                ((255, 200, 100), "id"),
                ((100, 150, 255), "anima"),
                ((100, 200, 100), "sensor"),
            ]
            legend2 = [
                ((255, 150, 0), "pref"),
                ((180, 180, 255), "belief"),
                ((180, 220, 140), "traj"),
            ]
            lx = 5
            for color, label in legend:
                draw.rectangle([lx, 209, lx + 4, 213], fill=color)
                draw.text((lx + 6, 208), label, fill=COLORS.TEXT_DIM, font=font_micro)
                lx += 6 + len(label) * 6 + 4
            lx = 5
            for color, label in legend2:
                draw.rectangle([lx, 218, lx + 4, 222], fill=color)
                draw.text((lx + 6, 217), label, fill=COLORS.TEXT_DIM, font=font_micro)
                lx += 6 + len(label) * 6 + 4

            self._draw_status_bar(draw)

            self._store_screen_cache("self_graph", sg_key, image)
            if hasattr(self._display, '_image'):
                self._display._image = image
            if hasattr(self._display, '_show'):
                self._display._show()
        except Exception as e:
            print(f"[Self Graph] Canvas error: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc(file=sys.stderr)
