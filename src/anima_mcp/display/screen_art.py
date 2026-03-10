"""
Display Screens - Art screen mixin.

Renders the notepad (drawing canvas) and art eras screens.
"""

import sys
import time
from typing import Optional

from .design import COLORS
from ..anima import Anima

# Per-era accent colors for the art eras selector
_ERA_ACCENT = {
    "gestural":    COLORS.SOFT_ORANGE,
    "pointillist": COLORS.SOFT_PURPLE,
    "field":       COLORS.SOFT_CYAN,
    "geometric":   COLORS.SOFT_BLUE,
}


class ArtMixin:
    """Mixin for art-related screens (notepad, art eras)."""

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
                draw.text((40, 90), text, fill=COLORS.SOFT_GREEN, font=font)

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
                draw.text((20, 80), "Governance\nPaused", fill=COLORS.SOFT_ORANGE, font=font)
                draw.text((20, 160), "Waiting for\nproceed", fill=COLORS.TEXT_DIM, font=fonts.get('small', font))
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
                text = "\u2713 saved"
                # Semi-transparent background for readability
                draw.rectangle([85, 5, 155, 25], fill=(15, 40, 15))
                draw.text((90, 7), text, fill=COLORS.SOFT_GREEN, font=font)

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

    def _render_art_eras(self, anima: Optional[Anima] = None):
        """Render Art Eras screen -- era selector with auto-rotate toggle."""
        from .eras import list_all_era_info, auto_rotate as _auto_rotate

        try:
            if hasattr(self._display, '_create_canvas'):
                # Cache: era state + cursor + drawings + phase (skip cache when marquee scrolling)
                current_name = self._active_era.name if self._active_era else "gestural"
                energy = self._intent.state.derived_energy if self._intent else 0.0
                drawings = self._canvas.drawings_saved if self._canvas else 0
                phase = self._canvas.drawing_phase if self._canvas else "?"
                era_key = (
                    f"{current_name}|{self._state.era_cursor}|{_auto_rotate}|"
                    f"{drawings}|{phase}|{energy:.1f}|{self._state.era_marquee_offset}"
                )
                if self._check_screen_cache("art_eras", era_key):
                    return

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
                all_eras = list_all_era_info()
                # Total items = eras + 1 (auto-rotate toggle)
                total_items = len(all_eras) + 1
                cursor = self._state.era_cursor % total_items if total_items else 0

                for i, info in enumerate(all_eras):
                    name = info["name"]
                    desc = info["description"]
                    is_current = (name == current_name)
                    is_cursor = (i == cursor)

                    # Per-era accent color (left-edge identity bar)
                    era_color = _ERA_ACCENT.get(name, SECONDARY)

                    # Cursor era: name line + marquee description line
                    if is_cursor:
                        row_h = 30
                        draw.rectangle([4, y - 2, 236, y + row_h - 2], fill=(25, 35, 50))
                        # Left-edge accent bar (full brightness when cursor is here)
                        draw.rectangle([4, y - 2, 7, y + row_h - 2], fill=era_color)
                        arrow = "\u25b6 "
                        name_color = YELLOW if is_current else SECONDARY
                        label = f"{arrow}{name}"
                        draw.text((10, y), label, fill=name_color, font=fonts['small'])
                        # Current era marker: small filled square in era color
                        if is_current:
                            draw.rectangle([228, y + 2, 233, y + 9], fill=era_color)
                        y += 14

                        # Marquee description: scroll if text wider than available area
                        desc_area_w = 210  # pixels available for description
                        try:
                            desc_full_w = fonts['micro'].getbbox(desc)[2]
                        except Exception:
                            desc_full_w = len(desc) * 6
                        if desc_full_w > desc_area_w:
                            # Advance marquee offset (~every 150ms)
                            now = time.time()
                            if now - self._state.era_marquee_time > 0.15:
                                self._state.era_marquee_offset += 1
                                self._state.era_marquee_time = now
                            # Wrap around with padding gap
                            gap = "     "
                            scroll_text = desc + gap + desc
                            offset = self._state.era_marquee_offset % (len(desc) + len(gap))
                            visible = scroll_text[offset:offset + 40]
                            draw.text((20, y), visible, fill=DIM, font=fonts['micro'])
                        else:
                            draw.text((20, y), desc, fill=DIM, font=fonts['micro'])
                        y += 16
                    else:
                        # Non-cursor era: compact single line with dimmed accent bar
                        era_dim = tuple(int(c * 0.45) for c in era_color)
                        draw.rectangle([4, y, 7, y + 14], fill=era_dim)
                        arrow = "  "
                        name_color = YELLOW if is_current else SECONDARY
                        label = f"{arrow}{name}"
                        draw.text((10, y), label, fill=name_color, font=fonts['small'])
                        # Current era marker: small filled square in era color
                        if is_current:
                            draw.rectangle([228, y + 2, 233, y + 9], fill=era_color)
                        y += 16

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
                era_accent = _ERA_ACCENT.get(current_name, SECONDARY)
                bar_x, bar_w, bar_h = 150, 60, 8
                draw.text((10, y), f"drawing #{drawings}", fill=DIM, font=fonts['small'])
                # Current era name in its accent color
                draw.text((95, y), current_name, fill=era_accent, font=fonts['small'])
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

                # Status bar
                self._draw_status_bar(draw)

                self._store_screen_cache("art_eras", era_key, image)
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
