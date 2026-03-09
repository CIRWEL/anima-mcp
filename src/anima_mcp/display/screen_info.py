"""
Display Screens - Info screen mixin.

Renders sensors, identity, diagnostics, and health screens.
"""

import sys
import time
from typing import Optional, Dict, Any, Tuple

from .design import COLORS
from ..anima import Anima
from ..sensors.base import SensorReadings
from ..identity.store import CreatureIdentity


class InfoMixin:
    """Mixin for info-group screens (sensors, identity, diagnostics, health)."""

    def _render_sensors(self, readings: Optional[SensorReadings]):
        """Render sensor readings with gauge bars and visual grouping."""
        if not readings:
            self._display.render_text("feeling\nblind", (10, 10), color=COLORS.TEXT_DIM)
            return

        # Cache: sensor values rounded to display precision (avoids redraw for noise)
        throttle = getattr(readings, 'throttle_bits', None) or 0
        cache_key = (
            f"{(readings.ambient_temp_c or 0):.1f}|{(readings.humidity_pct or 0):.0f}|"
            f"{(readings.light_lux or 0):.0f}|{(readings.cpu_temp_c or 0):.1f}|"
            f"{(readings.cpu_percent or 0):.0f}|{(readings.disk_percent or 0):.0f}|"
            f"{(readings.memory_percent or 0):.0f}|{throttle}"
        )
        if self._check_screen_cache("sensors", cache_key):
            return

        CYAN = COLORS.SOFT_CYAN
        BLUE = COLORS.SOFT_BLUE
        YELLOW = COLORS.SOFT_YELLOW
        ORANGE = COLORS.SOFT_ORANGE
        RED = COLORS.SOFT_CORAL
        GREEN = COLORS.SOFT_GREEN
        PURPLE = COLORS.SOFT_PURPLE
        WHITE = COLORS.TEXT_PRIMARY
        SECONDARY = COLORS.TEXT_SECONDARY
        DIM = COLORS.TEXT_DIM
        DIVIDER = (56, 54, 50)

        if not hasattr(self._display, '_create_canvas'):
            self._render_sensors_text_fallback(readings)
            return

        try:
            from .design import lighten_color
            image, draw = self._display._create_canvas(COLORS.BG_DARK)
            fonts = self._get_fonts()
            f_title = fonts['title']
            f_small = fonts['small']
            f_tiny = fonts['tiny']
            f_micro = fonts['micro']

            BAR_X = 10
            BAR_W = 160  # env bars (10 to 170), sparklines go to the right
            BAR_H = 6
            INLINE_BAR_W = 80
            INLINE_BAR_H = 4

            # -- Title --
            draw.text((10, 6), "sensors", fill=CYAN, font=f_title)

            # -- Section: environment --
            y = 28
            draw.text((10, y), "environment", fill=DIM, font=f_tiny)
            draw.line([(80, y + 6), (230, y + 6)], fill=DIVIDER, width=1)
            y += 16

            # Environment gauges: (label, value_str, fill_frac, color, feel)
            env_gauges = []

            # Temperature
            temp = readings.ambient_temp_c
            if temp is not None:
                if temp > 35:
                    feel, color = "hot", RED
                elif temp > 25:
                    feel, color = "warm", ORANGE
                elif temp < 10:
                    feel, color = "cold", CYAN
                elif temp < 18:
                    feel, color = "cool", CYAN
                else:
                    feel, color = "mild", GREEN
                frac = max(0.0, min(1.0, temp / 50.0))
                env_gauges.append(("temp", f"{temp:.1f}\u00b0C", frac, color, feel))
            else:
                env_gauges.append(("temp", "--", 0, DIM, ""))

            # Humidity
            hum = readings.humidity_pct
            if hum is not None:
                if hum < 30:
                    feel, color = "dry", YELLOW
                elif hum > 70:
                    feel, color = "damp", BLUE
                else:
                    feel, color = "ok", GREEN
                frac = max(0.0, min(1.0, hum / 100.0))
                env_gauges.append(("humidity", f"{hum:.0f}%", frac, color, feel))
            else:
                env_gauges.append(("humidity", "--", 0, DIM, ""))

            # Light
            light = readings.light_lux
            if light is not None:
                if light > 1000:
                    feel, color = "vivid", YELLOW
                elif light > 500:
                    feel, color = "bright", YELLOW
                elif light < 5:
                    feel, color = "dark", PURPLE
                elif light < 50:
                    feel, color = "dim", PURPLE
                else:
                    feel, color = "soft", WHITE
                frac = max(0.0, min(1.0, light / 2000.0))
                env_gauges.append(("light", f"{light:.0f} lux", frac, color, feel))
            else:
                env_gauges.append(("light", "--", 0, DIM, ""))

            # Draw environment gauges
            for label, val_str, frac, color, feel in env_gauges:
                # Label (left) + value (center-left) + feel (right)
                draw.text((BAR_X, y), label, fill=DIM, font=f_small)
                draw.text((70, y), val_str, fill=color, font=f_small)
                if feel:
                    draw.text((200, y), feel, fill=color, font=f_small)
                y += 14

                # Bar track
                draw.rectangle([BAR_X, y, BAR_X + BAR_W, y + BAR_H],
                              fill=COLORS.BG_SUBTLE)
                # Bar fill
                fill_w = int(frac * BAR_W)
                if fill_w > 0:
                    draw.rectangle([BAR_X, y, BAR_X + fill_w, y + BAR_H],
                                  fill=color)
                    # Bright cap at end
                    if fill_w > 3:
                        cap_color = lighten_color(color, 60)
                        draw.rectangle([BAR_X + fill_w - 2, y, BAR_X + fill_w, y + BAR_H],
                                      fill=cap_color)
                y += BAR_H + 6

            # I2C hint
            if not any([readings.ambient_temp_c, readings.humidity_pct, readings.light_lux]):
                draw.text((BAR_X, y - 4), "I2C off? sudo raspi-config", fill=DIM, font=f_micro)

            # -- Section: system --
            y = 132
            draw.text((10, y), "system", fill=DIM, font=f_tiny)
            draw.line([(52, y + 6), (230, y + 6)], fill=DIVIDER, width=1)
            y += 16

            # System inline gauges: (label, value_str, fill_frac, color)
            sys_gauges = []

            cpu_temp = readings.cpu_temp_c or 0
            cpu_color = RED if cpu_temp > 60 else ORANGE if cpu_temp > 50 else GREEN
            cpu_frac = max(0.0, min(1.0, (cpu_temp - 30) / 55.0))
            sys_gauges.append(("cpu", f"{cpu_temp:.0f}\u00b0C", cpu_frac, cpu_color))

            cpu_pct = readings.cpu_percent or 0
            sys_gauges.append(("load", f"{cpu_pct:.0f}%", max(0.0, min(1.0, cpu_pct / 100.0)), SECONDARY))

            mem_pct = readings.memory_percent or 0
            sys_gauges.append(("mem", f"{mem_pct:.0f}%", max(0.0, min(1.0, mem_pct / 100.0)), SECONDARY))

            disk = readings.disk_percent or 0
            disk_color = RED if disk > 80 else ORANGE if disk > 60 else GREEN
            sys_gauges.append(("disk", f"{disk:.0f}%", max(0.0, min(1.0, disk / 100.0)), disk_color))

            for label, val_str, frac, color in sys_gauges:
                # Label + value + inline bar on one line
                draw.text((BAR_X, y), label, fill=DIM, font=f_small)
                draw.text((48, y), val_str, fill=color, font=f_small)

                # Inline bar (vertically centered with text)
                bar_y = y + 5
                bar_x = 100
                draw.rectangle([bar_x, bar_y, bar_x + INLINE_BAR_W, bar_y + INLINE_BAR_H],
                              fill=COLORS.BG_SUBTLE)
                fill_w = int(frac * INLINE_BAR_W)
                if fill_w > 0:
                    draw.rectangle([bar_x, bar_y, bar_x + fill_w, bar_y + INLINE_BAR_H],
                                  fill=color)
                y += 16

            # -- Footer --
            y = 216
            # Power status
            if hasattr(readings, 'undervoltage_now') and readings.undervoltage_now is not None:
                if readings.undervoltage_now:
                    draw.text((BAR_X, y), "\u26a1UNDERVOLT!", fill=RED, font=f_micro)
                elif readings.undervoltage_occurred:
                    draw.text((BAR_X, y), "pwr:warn", fill=ORANGE, font=f_micro)
                elif readings.throttled_now:
                    draw.text((BAR_X, y), "pwr:throttle", fill=ORANGE, font=f_micro)
                else:
                    draw.text((BAR_X, y), "pwr:ok", fill=GREEN, font=f_micro)

            # Pressure
            if readings.pressure_hpa:
                draw.text((70, y), f"{readings.pressure_hpa:.0f}hPa", fill=DIM, font=f_micro)

            # WiFi + IP
            wifi_status = self._get_wifi_status()
            if wifi_status["connected"]:
                ssid = wifi_status.get("ssid", "")[:8]
                signal = wifi_status.get("signal", 0)
                ip = wifi_status.get("ip", "")
                wifi_color = GREEN if signal > 70 else YELLOW if signal > 40 else ORANGE
                draw.text((130, y), f"{ssid} {signal}%", fill=wifi_color, font=f_micro)
                if ip:
                    draw.text((BAR_X, y + 11), f"ip: {ip}", fill=DIM, font=f_micro)
            else:
                draw.text((130, y), "no wifi", fill=RED, font=f_micro)

            # Record sensor history for sparklines
            self._sensor_history.append((
                readings.ambient_temp_c or 0,
                readings.humidity_pct or 0,
                readings.cpu_temp_c or 0,
            ))
            # Draw sparklines in dedicated strip between system gauges and footer
            if len(self._sensor_history) >= 5:
                self._draw_sensor_sparklines(draw, readings)

            self._draw_status_bar(draw)

            self._store_screen_cache("sensors", cache_key, image)
            if hasattr(self._display, '_image'):
                self._display._image = image
            if hasattr(self._display, '_show'):
                self._display._show()
            return
        except Exception as e:
            import traceback
            print(f"[Sensors Screen] Canvas error: {e}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)

        self._render_sensors_text_fallback(readings)

    def _render_sensors_text_fallback(self, readings: SensorReadings):
        """Text-only fallback for sensors screen."""
        CYAN = COLORS.SOFT_CYAN
        ORANGE = COLORS.SOFT_ORANGE
        GREEN = COLORS.SOFT_GREEN
        YELLOW = COLORS.SOFT_YELLOW
        BLUE = COLORS.SOFT_BLUE
        RED = COLORS.SOFT_CORAL
        WHITE = COLORS.TEXT_PRIMARY

        lines_with_colors = []
        if not any([readings.ambient_temp_c, readings.humidity_pct, readings.light_lux]):
            lines_with_colors.append(("I2C off? sudo raspi-config", COLORS.TEXT_DIM))
        if readings.ambient_temp_c:
            temp = readings.ambient_temp_c
            temp_color = ORANGE if temp > 25 else CYAN if temp < 18 else GREEN
            lines_with_colors.append((f"air: {temp:.1f}\u00b0C", temp_color))
        if readings.humidity_pct:
            hum = readings.humidity_pct
            hum_color = YELLOW if hum < 30 else BLUE if hum > 70 else GREEN
            lines_with_colors.append((f"humidity: {hum:.0f}%", hum_color))
        if readings.light_lux:
            lines_with_colors.append((f"light: {readings.light_lux:.0f}", WHITE))
        cpu_t = readings.cpu_temp_c or 0
        lines_with_colors.append((f"cpu: {cpu_t:.1f}\u00b0C", GREEN))
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
            self._display.render_text("sensors\n\nno data", (10, 10), color=COLORS.TEXT_DIM)

    def _draw_sensor_sparklines(self, draw, readings):
        """Draw tiny sparklines to the right of gauge bars (not overlapping)."""
        history = list(self._sensor_history)
        n = len(history)
        if n < 5:
            return

        ORANGE = COLORS.SOFT_ORANGE
        GREEN = COLORS.SOFT_GREEN

        # Sparkline config: (data_index, y_top, color)
        # Positioned to the right of env bars (bars end at x=170)
        # Env bar y positions: temp=58, humidity=84, light=110 (each 6px tall)
        # CPU system row at y=148
        sparklines = [
            (0, 57, ORANGE if (readings.ambient_temp_c or 0) > 25 else GREEN),  # temp
            (1, 83, GREEN),   # humidity
            (2, 152, GREEN),  # cpu temp (next to inline bar)
        ]

        spark_x = 178
        spark_w = 50
        spark_h = 8

        for data_idx, y_top, color in sparklines:
            values = [h[data_idx] for h in history]
            v_min = min(values)
            v_max = max(values)
            v_range = v_max - v_min if v_max > v_min else 1.0

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

        # Cache: round values to avoid redraws for invisible changes
        id_key = (
            f"{name}|{age_days:.1f}|{alive_hours:.1f}|{alive_pct:.0f}|"
            f"{identity.total_awakenings}|{self._unitares_agent_id or ''}"
        )
        if self._check_screen_cache("identity", id_key):
            return

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
                y += 22
                draw.line([(10, y), (230, y)], fill=(30, 30, 40), width=1)
                y += 6

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

                # Status bar
                self._draw_status_bar(draw)

                # Update display
                self._store_screen_cache("identity", id_key, image)
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
            self._display.render_text("diagnostics\n\nno data", (10, 10))
            return

        # Cache: anima values + governance state rounded to display precision
        gov_state = (governance.get("unitares_agent_id") or "")[:8] if governance else ""
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

            font_title = fonts['title']

            y_offset = 6
            draw.text((10, y_offset), "diagnostics", fill=CYAN, font=font_title)
            y_offset += 22
            draw.line([(10, y_offset), (230, y_offset)], fill=(30, 30, 40), width=1)
            y_offset += 4

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
            self._display.render_text("health\n\nno registry", (10, 10))
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
                lines = ["health", f"overall: {overall}", ""]
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
            draw.text((10, y), "health", fill=COLORS.SOFT_CYAN, font=fonts['title'])
            overall_color = OVERALL_COLORS.get(overall, COLORS.TEXT_DIM)
            draw.text((90, y + 2), overall, fill=overall_color, font=font_small)
            y += 22

            # Thin separator line
            draw.line([(10, y), (230, y)], fill=(30, 30, 40), width=1)
            y += 4

            # One row per subsystem
            dot_radius = 4
            subsystems = sorted(status_data.items())
            row_height = min(22, max(16, (228 - y) // max(1, len(subsystems))))

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


            self._display.render_image(image)
            self._store_screen_cache("health", health_key, image)

        except Exception as e:
            print(f"[Screen] Health render error: {e}", file=sys.stderr, flush=True)
            self._display.render_text(f"health\n\n{overall}\n\nerror:\n{str(e)[:40]}", (10, 10))
