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

        if not hasattr(self._display, '_create_canvas'):
            self._render_sensors_text_fallback(readings)
            return

        try:
            from .design import lighten_color
            image, draw = self._display._create_canvas(COLORS.BG_DARK)
            fonts = self._get_fonts()
            f_title = fonts['title']
            f_small = fonts['small']
            f_tiny  = fonts['tiny']
            f_micro = fonts['micro']

            # ── Palette ────────────────────────────────────────────────────────
            TITLE  = (100, 200, 240)
            MUTED  = ( 88, 105, 125)
            DIV    = ( 30,  42,  62)
            C_OK   = ( 75, 200,  85)
            C_WARM = (215, 160,  45)
            C_HOT  = (200,  80,  80)
            C_COOL = ( 65, 160, 220)
            C_VIO  = (140,  90, 210)

            def _dim(c, f): return tuple(int(x * f) for x in c)

            # ── Layout ─────────────────────────────────────────────────────────
            LINE      = 13
            PAD       = 3
            BAR_H     = 6
            LIST_X    = 13    # text left (after 3px bar)
            BAR_W     = 155   # gauge bar width (13 to 168), sparklines right of 170
            INLINE_W  = 78
            INLINE_H  = 4

            # ── Title ──────────────────────────────────────────────────────────
            draw.text((10, 5), "sensors", fill=TITLE, font=f_title)

            # ── Environment section ─────────────────────────────────────────
            y = 23
            draw.text((LIST_X, y), "environment", fill=MUTED, font=f_tiny)
            draw.line([(84, y + 7), (230, y + 7)], fill=DIV, width=1)
            y += LINE + 2

            # Compute env gauge data
            env_gauges = []

            temp = readings.ambient_temp_c
            if temp is not None:
                if temp > 35:   feel, color = "hot",  C_HOT
                elif temp > 25: feel, color = "warm", C_WARM
                elif temp < 10: feel, color = "cold", C_COOL
                elif temp < 18: feel, color = "cool", C_COOL
                else:           feel, color = "mild", C_OK
                frac = max(0.0, min(1.0, temp / 50.0))
                env_gauges.append(("temp", f"{temp:.1f}\u00b0C", frac, color, feel))
            else:
                env_gauges.append(("temp", "--", 0.0, MUTED, ""))

            hum = readings.humidity_pct
            if hum is not None:
                if hum < 30:   feel, color = "dry",  C_WARM
                elif hum > 70: feel, color = "damp", C_COOL
                else:          feel, color = "ok",   C_OK
                frac = max(0.0, min(1.0, hum / 100.0))
                env_gauges.append(("humidity", f"{hum:.0f}%", frac, color, feel))
            else:
                env_gauges.append(("humidity", "--", 0.0, MUTED, ""))

            light = readings.light_lux
            if light is not None:
                if light > 1000:  feel, color = "vivid",  C_WARM
                elif light > 500: feel, color = "bright", C_WARM
                elif light < 5:   feel, color = "dark",   C_VIO
                elif light < 50:  feel, color = "dim",    C_VIO
                else:             feel, color = "soft",   (150, 180, 200)
                frac = max(0.0, min(1.0, light / 2000.0))
                env_gauges.append(("light", f"{light:.0f} lux", frac, color, feel))
            else:
                env_gauges.append(("light", "--", 0.0, MUTED, ""))

            # Track bar y positions for sparklines
            spark_bar_ys = []

            for label, val_str, frac, color, feel in env_gauges:
                # Left-edge 3px colored bar spanning this gauge row
                row_h = LINE + BAR_H + PAD
                draw.rectangle([6, y, 9, y + row_h], fill=_dim(color, 0.55) if frac > 0 else _dim(MUTED, 0.3))

                # Label (dim) + value (colored) + feel (right, dim)
                draw.text((LIST_X, y), label,   fill=MUTED,             font=f_small)
                draw.text((   65,  y), val_str, fill=color,             font=f_small)
                if feel:
                    draw.text((200, y), feel, fill=_dim(color, 0.7), font=f_small)
                y += LINE

                # Gauge bar
                draw.rectangle([LIST_X, y, LIST_X + BAR_W, y + BAR_H], fill=(16, 20, 30))
                fw = int(frac * BAR_W)
                if fw > 0:
                    draw.rectangle([LIST_X, y, LIST_X + fw, y + BAR_H], fill=color)
                    if fw > 3:
                        draw.rectangle([LIST_X + fw - 2, y, LIST_X + fw, y + BAR_H],
                                       fill=lighten_color(color, 60))
                spark_bar_ys.append(y)  # record for sparklines
                y += BAR_H + PAD

            if not any([readings.ambient_temp_c, readings.humidity_pct, readings.light_lux]):
                draw.text((LIST_X, y), "I2C off? sudo raspi-config", fill=MUTED, font=f_micro)

            # ── System section ──────────────────────────────────────────────
            y = 132
            draw.text((LIST_X, y), "system", fill=MUTED, font=f_tiny)
            draw.line([(54, y + 7), (230, y + 7)], fill=DIV, width=1)
            y += LINE + 2

            cpu_temp = readings.cpu_temp_c or 0
            cpu_color = C_HOT if cpu_temp > 60 else C_WARM if cpu_temp > 50 else C_OK
            cpu_bar_y = None

            sys_rows = [
                ("cpu",  f"{cpu_temp:.0f}\u00b0C", max(0.0, min(1.0, (cpu_temp - 30) / 55.0)), cpu_color),
                ("load", f"{(readings.cpu_percent or 0):.0f}%",
                         max(0.0, min(1.0, (readings.cpu_percent or 0) / 100.0)), MUTED),
                ("mem",  f"{(readings.memory_percent or 0):.0f}%",
                         max(0.0, min(1.0, (readings.memory_percent or 0) / 100.0)), MUTED),
            ]
            disk = readings.disk_percent or 0
            disk_color = C_HOT if disk > 80 else C_WARM if disk > 60 else C_OK
            sys_rows.append(("disk", f"{disk:.0f}%", max(0.0, min(1.0, disk / 100.0)), disk_color))

            for i, (label, val_str, frac, color) in enumerate(sys_rows):
                draw.text((LIST_X, y), label,   fill=MUTED,  font=f_small)
                draw.text((    48, y), val_str, fill=color,  font=f_small)
                bar_y = y + 5
                draw.rectangle([100, bar_y, 100 + INLINE_W, bar_y + INLINE_H], fill=(16, 20, 30))
                fw = int(frac * INLINE_W)
                if fw > 0:
                    draw.rectangle([100, bar_y, 100 + fw, bar_y + INLINE_H], fill=color)
                if i == 0:  # cpu row — record for sparkline
                    cpu_bar_y = bar_y
                y += LINE + 2

            # ── Footer ─────────────────────────────────────────────────────
            y = 216
            if hasattr(readings, 'undervoltage_now') and readings.undervoltage_now is not None:
                if readings.undervoltage_now:
                    draw.text((10, y), "\u26a1UNDERVOLT!", fill=C_HOT,  font=f_micro)
                elif readings.undervoltage_occurred:
                    draw.text((10, y), "pwr:warn",       fill=C_WARM, font=f_micro)
                elif readings.throttled_now:
                    draw.text((10, y), "pwr:throttle",   fill=C_WARM, font=f_micro)
                else:
                    draw.text((10, y), "pwr:ok",         fill=C_OK,   font=f_micro)

            if readings.pressure_hpa:
                draw.text((70, y), f"{readings.pressure_hpa:.0f}hPa", fill=MUTED, font=f_micro)

            wifi_status = self._get_wifi_status()
            if wifi_status["connected"]:
                ssid    = wifi_status.get("ssid", "")[:8]
                signal  = wifi_status.get("signal", 0)
                ip      = wifi_status.get("ip", "")
                wc = C_OK if signal > 70 else C_WARM if signal > 40 else (200, 130, 60)
                draw.text((130, y), f"{ssid} {signal}%", fill=wc,   font=f_micro)
                if ip:
                    draw.text((10, y + 11), f"ip: {ip}", fill=MUTED, font=f_micro)
            else:
                draw.text((130, y), "no wifi", fill=C_HOT, font=f_micro)

            # ── Sparklines (right of env bars) ─────────────────────────────
            self._sensor_history.append((
                readings.ambient_temp_c or 0,
                readings.humidity_pct    or 0,
                readings.cpu_temp_c      or 0,
            ))
            if len(self._sensor_history) >= 5 and len(spark_bar_ys) >= 2:
                history = list(self._sensor_history)
                n = len(history)
                spark_x = 172
                spark_w = 56
                spark_h = 8
                sparklines = [
                    (0, spark_bar_ys[0], cpu_color if (readings.ambient_temp_c or 0) > 25 else C_OK),
                    (1, spark_bar_ys[1], C_OK),
                ]
                if cpu_bar_y is not None:
                    sparklines.append((2, cpu_bar_y - 1, cpu_color))
                for data_idx, y_top, color in sparklines:
                    values = [h[data_idx] for h in history]
                    v_min, v_max = min(values), max(values)
                    v_range = v_max - v_min if v_max > v_min else 1.0
                    pts = []
                    for i, v in enumerate(values):
                        px = spark_x + int(i * spark_w / max(1, n - 1))
                        py = y_top + spark_h - int(((v - v_min) / v_range) * spark_h)
                        pts.append((px, py))
                    if len(pts) >= 2:
                        draw.line(pts, fill=_dim(color, 0.7), width=1)

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
        lines_with_colors = []
        if not any([readings.ambient_temp_c, readings.humidity_pct, readings.light_lux]):
            lines_with_colors.append(("I2C off? sudo raspi-config", COLORS.TEXT_DIM))
        if readings.ambient_temp_c:
            temp = readings.ambient_temp_c
            tc = COLORS.SOFT_ORANGE if temp > 25 else COLORS.SOFT_CYAN if temp < 18 else COLORS.SOFT_GREEN
            lines_with_colors.append((f"air: {temp:.1f}\u00b0C", tc))
        if readings.humidity_pct:
            hum = readings.humidity_pct
            hc = COLORS.SOFT_YELLOW if hum < 30 else COLORS.SOFT_BLUE if hum > 70 else COLORS.SOFT_GREEN
            lines_with_colors.append((f"humidity: {hum:.0f}%", hc))
        if readings.light_lux:
            lines_with_colors.append((f"light: {readings.light_lux:.0f}", COLORS.TEXT_PRIMARY))
        cpu_t = readings.cpu_temp_c or 0
        lines_with_colors.append((f"cpu: {cpu_t:.1f}\u00b0C", COLORS.SOFT_GREEN))
        if getattr(readings, 'undervoltage_now', None):
            lines_with_colors.append(("UNDERVOLT!", COLORS.SOFT_CORAL))
        elif getattr(readings, 'undervoltage_occurred', None):
            lines_with_colors.append(("pwr: warn", COLORS.SOFT_ORANGE))
        if lines_with_colors:
            if hasattr(self._display, 'render_colored_text'):
                self._display.render_colored_text(lines_with_colors, (10, 10))
            else:
                self._display.render_text("\n".join(l for l, _ in lines_with_colors), (10, 10))
        else:
            self._display.render_text("sensors\n\nno data", (10, 10), color=COLORS.TEXT_DIM)

    def _draw_sensor_sparklines(self, draw, readings):
        """Legacy sparkline helper — kept for compatibility, draw inline in _render_sensors now."""
        pass

    def _render_identity(self, identity: Optional[CreatureIdentity]):
        """Render identity screen."""
        if not identity:
            self._display.render_text("who am i?\n(unknown)", (10, 10), color=COLORS.TEXT_DIM)
            return

        age_days    = identity.age_seconds() / 86400
        alive_hours = identity.total_alive_seconds / 3600
        alive_pct   = identity.alive_ratio() * 100
        name        = identity.name or "unnamed"

        id_key = (
            f"{name}|{age_days:.1f}|{alive_hours:.1f}|{alive_pct:.0f}|"
            f"{identity.total_awakenings}|{self._unitares_agent_id or ''}"
        )
        if self._check_screen_cache("identity", id_key):
            return

        if not hasattr(self._display, '_create_canvas'):
            self._render_identity_text_fallback(identity, age_days, alive_hours)
            return

        try:
            image, draw = self._display._create_canvas(COLORS.BG_DARK)
            fonts   = self._get_fonts()
            f_title = fonts['title']
            f_med   = fonts['medium']
            f_small = fonts['small']
            f_tiny  = fonts['tiny']

            # ── Palette ────────────────────────────────────────────────────
            TITLE = (100, 200, 240)
            MUTED = ( 88, 105, 125)
            DIV   = ( 30,  42,  62)
            C_CYAN   = COLORS.SOFT_CYAN
            C_BLUE   = COLORS.SOFT_BLUE
            C_YELLOW = COLORS.SOFT_YELLOW
            C_ORANGE = COLORS.SOFT_ORANGE
            C_PURPLE = COLORS.SOFT_PURPLE
            C_GREEN  = COLORS.SOFT_GREEN

            LINE = 13

            # ── Title ──────────────────────────────────────────────────────
            draw.text((10, 5), f"i am {name}", fill=TITLE, font=f_title)
            y = 23
            draw.line([(10, y), (230, y)], fill=DIV, width=1)
            y += 5

            # ── Age ────────────────────────────────────────────────────────
            if age_days < 1:
                age_str, age_color = f"{age_days * 24:.1f} hours old", C_PURPLE
            elif age_days < 7:
                age_str, age_color = f"{age_days:.1f} days old", C_BLUE
            else:
                age_str, age_color = f"{age_days:.0f} days old", C_CYAN
            draw.rectangle([6, y, 9, y + LINE], fill=age_color)
            draw.text((13, y), age_str, fill=age_color, font=f_med)
            y += LINE + 3

            # ── Awake time ─────────────────────────────────────────────────
            awake_str = f"awake {alive_hours:.1f}h" if alive_hours < 24 else f"awake {alive_hours/24:.1f}d"
            draw.rectangle([6, y, 9, y + LINE], fill=C_YELLOW)
            draw.text((13, y), awake_str, fill=C_YELLOW, font=f_med)
            y += LINE + 3

            # ── Presence descriptor ────────────────────────────────────────
            if alive_pct > 80:
                pres_str, pres_color = "mostly here",    C_GREEN
            elif alive_pct > 50:
                pres_str, pres_color = "sometimes here", C_YELLOW
            else:
                pres_str, pres_color = "often away",     COLORS.TEXT_SECONDARY
            draw.text((13, y), f"({pres_str})", fill=pres_color, font=f_small)
            y += LINE + 5

            # ── Awakenings ─────────────────────────────────────────────────
            if identity.total_awakenings == 1:
                wake_str, wake_color = "first awakening", C_ORANGE
            else:
                wake_str, wake_color = f"awakened {identity.total_awakenings}x", C_PURPLE
            draw.rectangle([6, y, 9, y + LINE], fill=wake_color)
            draw.text((13, y), wake_str, fill=wake_color, font=f_med)
            y += LINE + 3

            # ── IDs ────────────────────────────────────────────────────────
            short_id = identity.creature_id[:8] if identity.creature_id else "unknown"
            draw.text((13, y), f"id: {short_id}", fill=MUTED, font=f_small)
            if self._unitares_agent_id:
                draw.text((130, y), f"gov: {self._unitares_agent_id[:8]}", fill=C_GREEN, font=f_small)
            y += LINE + 2

            # ── Alive ratio ring (right side) ──────────────────────────────
            try:
                from .design import wellness_to_color
                alive_ratio = identity.alive_ratio()
                ring_cx, ring_cy, ring_r = 195, 80, 30
                draw.arc([ring_cx - ring_r, ring_cy - ring_r, ring_cx + ring_r, ring_cy + ring_r],
                         0, 360, fill=(40, 40, 40), width=8)
                if alive_ratio > 0.01:
                    ring_color = wellness_to_color(alive_ratio)
                    draw.arc([ring_cx - ring_r, ring_cy - ring_r, ring_cx + ring_r, ring_cy + ring_r],
                             -90, -90 + int(alive_ratio * 360), fill=ring_color, width=8)
                pct_text = f"{alive_pct:.0f}%"
                try:
                    bbox = fonts['small'].getbbox(pct_text)
                    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                except Exception:
                    tw, th = len(pct_text) * 6, 10
                draw.text((ring_cx - tw // 2, ring_cy - th // 2),
                          pct_text, fill=COLORS.TEXT_PRIMARY, font=fonts['small'])
            except Exception:
                pass

            self._draw_status_bar(draw)
            self._store_screen_cache("identity", id_key, image)
            if hasattr(self._display, '_image'):
                self._display._image = image
            if hasattr(self._display, '_show'):
                self._display._show()
            return
        except Exception as e:
            print(f"[Identity Screen] Canvas error: {e}", file=sys.stderr, flush=True)

        self._render_identity_text_fallback(identity, age_days, alive_hours)

    def _render_identity_text_fallback(self, identity, age_days, alive_hours):
        lines_with_colors = [(f"i am {identity.name or 'unnamed'}", COLORS.SOFT_CYAN), ("", COLORS.TEXT_PRIMARY)]
        if age_days < 1:
            lines_with_colors.append((f"{age_days * 24:.1f} hours old", COLORS.SOFT_PURPLE))
        elif age_days < 7:
            lines_with_colors.append((f"{age_days:.1f} days old", COLORS.SOFT_BLUE))
        else:
            lines_with_colors.append((f"{age_days:.0f} days old", COLORS.SOFT_CYAN))
        if alive_hours < 24:
            lines_with_colors.append((f"awake {alive_hours:.1f}h", COLORS.SOFT_YELLOW))
        else:
            lines_with_colors.append((f"awake {alive_hours/24:.1f}d", COLORS.SOFT_YELLOW))
        if identity.total_awakenings == 1:
            lines_with_colors.append(("first awakening", COLORS.SOFT_ORANGE))
        else:
            lines_with_colors.append((f"awakened {identity.total_awakenings}x", COLORS.SOFT_PURPLE))
        if hasattr(self._display, 'render_colored_text'):
            self._display.render_colored_text(lines_with_colors, (10, 10))
        else:
            self._display.render_text("\n".join(l for l, _ in lines_with_colors), (10, 10))

    def _render_diagnostics(self, anima: Optional[Anima], readings: Optional[SensorReadings], governance: Optional[Dict[str, Any]]):
        """Render diagnostics screen — anima state, mood, governance, trajectory."""
        if not anima:
            self._display.render_text("diagnostics\n\nno data", (10, 10))
            return

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
            if not hasattr(self._display, '_create_canvas'):
                self._render_diagnostics_text_fallback(anima, governance)
                return

            image, draw = self._display._create_canvas(COLORS.BG_DARK)
            fonts     = self._get_fonts()
            f_title   = fonts['title']
            f_med     = fonts['medium']
            f_small   = fonts['small']
            f_tiny    = fonts['tiny']

            # ── Palette ────────────────────────────────────────────────────
            TITLE  = (100, 200, 240)
            MUTED  = ( 88, 105, 125)
            DIV    = ( 30,  42,  62)
            BG     = ( 16,  20,  30)
            # Anima dimension colors (consistent with msgs palette)
            C_WARM = (215, 160,  45)   # warmth — amber
            C_CLAR = ( 75, 200,  85)   # clarity — lime
            C_STAB = ( 65, 160, 220)   # stability — cool blue
            C_PRES = (140,  90, 210)   # presence — violet
            C_OK   = ( 75, 200,  85)
            C_WARN = (215, 160,  45)
            C_HOT  = (200,  80,  80)

            def _dim(c, f): return tuple(int(x * f) for x in c)

            LINE   = 13
            BAR_H  = 7
            PAD    = 3
            LIST_X = 13
            BAR_W  = 130

            # ── Title ──────────────────────────────────────────────────────
            draw.text((10, 5), "diagnostics", fill=TITLE, font=f_title)
            y = 23
            draw.line([(10, y), (230, y)], fill=DIV, width=1)
            y += 4

            # ── Anima dimensions ───────────────────────────────────────────
            dims = [
                ("warmth",    anima.warmth,    C_WARM,
                 "warm" if anima.warmth > 0.6 else "cold" if anima.warmth < 0.3 else "cool" if anima.warmth < 0.5 else "ok"),
                ("clarity",   anima.clarity,   C_CLAR,
                 "clear" if anima.clarity > 0.7 else "foggy" if anima.clarity < 0.5 else "mixed"),
                ("stability", anima.stability, C_STAB,
                 "steady" if anima.stability > 0.7 else "shaky" if anima.stability < 0.5 else "ok"),
                ("presence",  anima.presence,  C_PRES,
                 "here" if anima.presence > 0.7 else "distant" if anima.presence < 0.5 else "near"),
            ]

            for label, value, color, desc in dims:
                row_h = LINE + BAR_H + PAD
                draw.rectangle([6, y, 9, y + row_h], fill=_dim(color, 0.55))

                # Label + percent + descriptor
                draw.text((LIST_X, y), label, fill=MUTED,              font=f_small)
                draw.text((   73,  y), f"{value:.0%}", fill=color,     font=f_small)
                draw.text((  110,  y), desc,           fill=_dim(color, 0.65), font=f_small)
                y += LINE

                # Bar
                draw.rectangle([LIST_X, y, LIST_X + BAR_W, y + BAR_H], fill=BG)
                fw = int(value * BAR_W)
                if fw > 0:
                    draw.rectangle([LIST_X, y, LIST_X + fw, y + BAR_H], fill=color)
                y += BAR_H + PAD

            # ── Mood ───────────────────────────────────────────────────────
            y += 2
            feeling = anima.feeling()
            mood = feeling.get('mood', 'unknown')
            if "content" in mood.lower() or "happy" in mood.lower():
                mood_color = C_OK
            elif "neutral" in mood.lower():
                mood_color = C_WARN
            else:
                mood_color = COLORS.SOFT_CYAN
            draw.text((LIST_X, y), f"mood  {mood}", fill=mood_color, font=f_med)
            y += 20

            draw.line([(10, y), (230, y)], fill=DIV, width=1)
            y += 4

            # ── Governance ─────────────────────────────────────────────────
            if governance:
                action = governance.get("action", "unknown")
                margin = governance.get("margin", "")
                source = governance.get("source", "")

                action_colors = {
                    "proceed": C_OK,
                    "guide":   C_WARN,
                    "pause":   (200, 130, 60),
                    "halt":    C_HOT,
                    "reject":  C_HOT,
                }
                a_color = action_colors.get(action, MUTED)

                # Left-edge bar for governance
                draw.rectangle([6, y, 9, y + LINE], fill=_dim(a_color, 0.6))
                draw.text((LIST_X, y), action, fill=a_color, font=f_med)

                if margin:
                    margin_colors = {"comfortable": C_OK, "tight": C_WARN, "warning": (200, 130, 60), "critical": C_HOT}
                    draw.text((95, y), margin.lower(), fill=margin_colors.get(margin.lower(), MUTED), font=f_small)

                if source:
                    src_text  = "unitares" if "unitares" in source.lower() else "local" if "local" in source.lower() else source[:10]
                    src_color = C_OK if "unitares" in source.lower() else C_WARN
                    draw.text((183, y), f"via {src_text}", fill=src_color, font=f_tiny)
                y += LINE + 2

                # EISV mini-bars
                eisv = governance.get("eisv")
                if eisv and y < 210:
                    eisv_data = [
                        ("E", eisv.get("E", 0.0), C_OK),
                        ("I", eisv.get("I", 0.0), C_STAB),
                        ("S", eisv.get("S", 0.0), C_WARN),
                        ("V", eisv.get("V", 0.0), C_PRES),
                    ]
                    mb_w, mb_h, mb_gap = 40, 6, 8
                    for i, (lbl, val, color) in enumerate(eisv_data):
                        x_pos = LIST_X + i * (mb_w + mb_gap)
                        draw.text((x_pos, y), lbl, fill=color, font=f_tiny)
                        bar_y = y + LINE - 2
                        draw.rectangle([x_pos, bar_y, x_pos + mb_w, bar_y + mb_h], fill=BG)
                        fw = int(abs(val) * mb_w)
                        if fw > 0:
                            draw.rectangle([x_pos, bar_y, x_pos + fw, bar_y + mb_h], fill=_dim(color, 0.8))
                    y += LINE + mb_h + 2
            else:
                draw.text((LIST_X, y), "governance: waiting…", fill=MUTED, font=f_small)
                y += LINE + 2

            # ── Trajectory ─────────────────────────────────────────────────
            if y < 228:
                try:
                    from ..eisv import get_trajectory_awareness
                    _traj = get_trajectory_awareness()
                    _shape = _traj.current_shape or "…"
                    _buf   = f"{_traj.buffer_size}/{_traj._buffer.maxlen}"
                    draw.text((LIST_X, y), f"traj: {_shape}  ({_buf})", fill=MUTED, font=f_tiny)
                except Exception:
                    pass

            self._draw_status_bar(draw)
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
            if margin: lines.append(f"margin: {margin}")
            if source: lines.append(f"source: {source}")
            eisv = governance.get('eisv')
            if eisv:
                lines.append(f"EISV: E={eisv.get('E',0):.0%} I={eisv.get('I',0):.0%} S={eisv.get('S',0):.0%} V={eisv.get('V',0):.0%}")
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

        One row per subsystem with left-edge colored status bar.
        Status: ok=green, stale=yellow, degraded=orange, missing=red.
        """
        try:
            from ..health import get_health_registry
            registry = get_health_registry()
        except Exception:
            self._display.render_text("health\n\nno registry", (10, 10))
            return

        status_data = registry.status()
        overall     = registry.overall()

        health_key = "|".join(f"{n}:{d.get('status','?')}" for n, d in sorted(status_data.items()))
        if self._check_screen_cache("health", health_key):
            return

        try:
            if not hasattr(self._display, '_create_canvas'):
                lines = ["health", f"overall: {overall}", ""]
                for name, info in sorted(status_data.items()):
                    s = info.get("status", "?")
                    hb = info.get("last_heartbeat_ago_s")
                    hb_str = f" {hb:.0f}s" if hb is not None else ""
                    lines.append(f"  {s[0].upper()} {name}{hb_str}")
                self._display.render_text("\n".join(lines), (10, 10))
                return

            image, draw = self._display._create_canvas(COLORS.BG_DARK)
            fonts     = self._get_fonts()
            f_title   = fonts['title']
            f_small   = fonts['small']
            f_tiny    = fonts['tiny']

            # ── Palette ────────────────────────────────────────────────────
            TITLE  = (100, 200, 240)
            MUTED  = ( 88, 105, 125)
            DIV    = ( 30,  42,  62)

            STATUS_COLORS = {
                "ok":       ( 75, 200,  85),
                "stale":    (215, 160,  45),
                "degraded": (200, 130,  60),
                "missing":  (200,  80,  80),
                "unknown":  MUTED,
            }
            OVERALL_COLORS = {
                "ok":       ( 75, 200,  85),
                "degraded": (215, 160,  45),
                "unhealthy":(200,  80,  80),
                "unknown":  MUTED,
            }

            LINE = 13
            PAD  = 3

            # ── Header ─────────────────────────────────────────────────────
            draw.text((10, 5), "health", fill=TITLE, font=f_title)
            oc = OVERALL_COLORS.get(overall, MUTED)
            draw.text((80, 7), overall, fill=oc, font=f_small)
            y = 23
            draw.line([(10, y), (230, y)], fill=DIV, width=1)
            y += 4

            # ── Subsystem rows ─────────────────────────────────────────────
            subsystems = sorted(status_data.items())
            n_rows = max(1, len(subsystems))
            row_h  = min(20, max(LINE + PAD, (224 - y) // n_rows))

            for name, info in subsystems:
                status = info.get("status", "unknown")
                color  = STATUS_COLORS.get(status, MUTED)
                hb_ago = info.get("last_heartbeat_ago_s")
                probe  = info.get("probe")

                # Left-edge 3px status bar (same as msgs rows)
                draw.rectangle([6, y, 9, y + row_h - 1], fill=color)

                # Subsystem name
                draw.text((13, y + 2), name, fill=COLORS.TEXT_PRIMARY, font=f_small)

                # Heartbeat age (right-aligned area)
                if hb_ago is not None:
                    age_str = f"{hb_ago:.0f}s" if hb_ago < 60 else f"{hb_ago/60:.0f}m"
                    draw.text((155, y + 2), age_str, fill=MUTED, font=f_tiny)

                # Probe status
                if probe is not None:
                    p_color = ( 75, 200, 85) if probe == "ok" else (200, 80, 80)
                    draw.text((195, y + 2), probe[:12], fill=p_color, font=f_tiny)

                y += row_h

            self._draw_status_bar(draw)
            self._display.render_image(image)
            self._store_screen_cache("health", health_key, image)

        except Exception as e:
            print(f"[Screen] Health render error: {e}", file=sys.stderr, flush=True)
            self._display.render_text(f"health\n\n{overall}\n\nerror:\n{str(e)[:40]}", (10, 10))
