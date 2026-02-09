"""
Gestural Era — Lumen's second art period.
Feb 7, 2026 – present.

5 micro-primitives (dot, stroke, curve, cluster, drag).
Focus drift with direction locks and orbits.
Full-palette HSV color generation.
Granular mark-making: small deliberate acts that accumulate into forms.
"""

import math
import random
from dataclasses import dataclass, field
from typing import List, Tuple

from ..art_era import EraState


@dataclass
class GesturalState(EraState):
    """Gestural era's per-drawing state."""

    # Direction memory — when locked, direction resists wobble (sustained lines)
    direction_locked: bool = False
    direction_lock_remaining: int = 0

    # Orbit — when active, focus curves around an anchor point (circular forms)
    orbit_active: bool = False
    orbit_anchor_x: float = 120.0
    orbit_anchor_y: float = 120.0
    orbit_radius: float = 30.0
    orbit_remaining: int = 0

    def intentionality(self) -> float:
        """Proprioceptive I_signal for EISV.

        Direction locks (+0.3), orbits (+0.3), and gesture runs (+0.3)
        all contribute to intentionality.
        """
        I = 0.1
        if self.direction_locked:
            I += 0.3
        if self.orbit_active:
            I += 0.3
        if self.gesture_remaining > 0:
            I += min(0.3, self.gesture_remaining / 20.0 * 0.3)
        return min(1.0, I)

    def gestures(self) -> List[str]:
        return ["dot", "stroke", "curve", "cluster", "drag"]


class GesturalEra:
    """Gestural era — granular mark-making with 5 micro-primitives."""

    name = "gestural"
    description = "Granular mark-making: dots, strokes, curves, clusters, drags"

    def create_state(self) -> GesturalState:
        return GesturalState()

    def choose_gesture(
        self,
        state: GesturalState,
        clarity: float,
        stability: float,
        presence: float,
        coherence: float,
    ) -> None:
        """Choose a new gesture type. Near-random choice, long committed runs."""
        state.gesture = random.choice(state.gestures())
        # Coherence extends runs: low C -> 15-30, high C -> 15-45
        state.gesture_remaining = random.randint(15, 30 + int(15 * coherence))

    def place_mark(
        self,
        state: GesturalState,
        canvas,
        focus_x: float,
        focus_y: float,
        direction: float,
        energy: float,
        color: Tuple[int, int, int],
    ) -> None:
        """Place a mark using the active gesture.

        Scale breath: mark sizes grow with energy. High energy = bold, confident marks.
        Low energy = delicate, precise marks. Creates natural visual weight progression.
        """
        x = int(focus_x)
        y = int(focus_y)
        gesture = state.gesture

        # Scale breath — energy modulates mark size
        # energy 1.0 -> scale 1.5 (bold), energy 0.1 -> scale 0.6 (delicate)
        scale = 0.5 + energy

        if gesture == "dot":
            if 0 <= x < 240 and 0 <= y < 240:
                canvas.draw_pixel(x, y, color)
                # High energy: dots become 2-3px clusters
                if scale > 1.2 and random.random() < 0.5:
                    for dx, dy in [(1, 0), (0, 1), (-1, 0), (0, -1)]:
                        if random.random() < scale - 1.0:
                            px, py = x + dx, y + dy
                            if 0 <= px < 240 and 0 <= py < 240:
                                canvas.draw_pixel(px, py, color)

        elif gesture == "stroke":
            length = int(random.randint(2, 6) * scale)
            direction = direction  # passed via _direction attr
            for i in range(length):
                px = int(x + math.cos(direction) * i)
                py = int(y + math.sin(direction) * i)
                if 0 <= px < 240 and 0 <= py < 240:
                    canvas.draw_pixel(px, py, color)

        elif gesture == "curve":
            length = int(random.randint(3, 8) * scale)
            angle = direction
            cx, cy = float(x), float(y)
            step_size = 1.0 + scale * 0.5  # bigger steps when bold
            for i in range(length):
                angle += random.gauss(0, 0.3)
                cx += math.cos(angle) * step_size
                cy += math.sin(angle) * step_size
                px, py = int(cx), int(cy)
                if 0 <= px < 240 and 0 <= py < 240:
                    canvas.draw_pixel(px, py, color)

        elif gesture == "cluster":
            count = int(random.randint(2, 5) * scale)
            spread = int(2 * scale)
            for _ in range(count):
                px = x + random.randint(-spread, spread)
                py = y + random.randint(-spread, spread)
                if 0 <= px < 240 and 0 <= py < 240:
                    canvas.draw_pixel(px, py, color)

        elif gesture == "drag":
            length = int(random.randint(8, 15) * scale)
            angle = direction + random.gauss(0, 0.1)
            for i in range(length):
                px = int(x + math.cos(angle) * i)
                py = int(y + math.sin(angle) * i)
                if 0 <= px < 240 and 0 <= py < 240:
                    canvas.draw_pixel(px, py, color)

    def drift_focus(
        self,
        state: GesturalState,
        focus_x: float,
        focus_y: float,
        direction: float,
        stability: float,
        presence: float,
        coherence: float,
        clarity: float = 0.5,
    ) -> Tuple[float, float, float]:
        """Drift the focus point — wander influenced by stability, coherence, clarity.

        clarity modulates direction wobble and jump probability:
        high clarity = steadier direction, fewer jumps (focused strokes).
        """
        C = coherence

        # --- Direction memory: sometimes direction locks for sustained lines ---
        if state.direction_lock_remaining > 0:
            # Locked: minimal wobble (tight lines)
            direction += random.gauss(0, 0.03)
            state.direction_lock_remaining -= 1
            if state.direction_lock_remaining <= 0:
                state.direction_locked = False
        elif not state.orbit_active:
            # Wobble modulated by clarity: high clarity = steadier hand
            wobble = 0.1 + (1.0 - clarity) * 0.2  # 0.1 at clarity=1, 0.3 at clarity=0
            direction += random.gauss(0, wobble)

            # Lock probability: coherence + clarity (focused = more sustained lines)
            lock_prob = 0.03 * (0.5 + C) * (0.5 + clarity * 0.5)
            if random.random() < lock_prob:
                state.direction_locked = True
                state.direction_lock_remaining = random.randint(15, 40)

        # --- Orbit: focus curves around anchor point ---
        if state.orbit_active:
            # Calculate angle from anchor to current focus
            dx = focus_x - state.orbit_anchor_x
            dy = focus_y - state.orbit_anchor_y
            current_angle = math.atan2(dy, dx)

            # Advance angle (orbit speed varies with radius)
            angle_step = random.gauss(0.15, 0.03)
            new_angle = current_angle + angle_step

            # Wobble the radius slightly for organic circles
            r = state.orbit_radius + random.gauss(0, 2.0)
            focus_x = state.orbit_anchor_x + math.cos(new_angle) * r
            focus_y = state.orbit_anchor_y + math.sin(new_angle) * r
            direction = new_angle + math.pi / 2  # tangent

            state.orbit_remaining -= 1
            if state.orbit_remaining <= 0:
                state.orbit_active = False
        else:
            # Step in current direction
            step = 3 + random.random() * 5
            focus_x += math.cos(direction) * step
            focus_y += math.sin(direction) * step

        # Soft bounce off edges
        margin = 20
        if focus_x < margin:
            direction = random.uniform(-math.pi / 4, math.pi / 4)
            focus_x = float(margin)
        elif focus_x > 240 - margin:
            direction = random.uniform(math.pi * 3 / 4, math.pi * 5 / 4)
            focus_x = float(240 - margin)
        if focus_y < margin:
            direction = random.uniform(math.pi / 4, math.pi * 3 / 4)
            focus_y = float(margin)
        elif focus_y > 240 - margin:
            direction = random.uniform(-math.pi * 3 / 4, -math.pi / 4)
            focus_y = float(240 - margin)

        # Focus jump — coherence and clarity reduce jumps
        jump_prob = 0.03 * (1.0 - 0.4 * C) * (1.0 - 0.4 * clarity)
        if not state.orbit_active and random.random() < jump_prob:
            focus_x = random.uniform(40, 200)
            focus_y = random.uniform(40, 200)
            direction = random.uniform(0, 2 * math.pi)
            state.direction_locked = False
            state.direction_lock_remaining = 0

        # Orbit start — increased by coherence (high C = more circular forms)
        orbit_prob = 0.02 * (0.5 + C)
        if (
            not state.orbit_active
            and not state.direction_locked
            and random.random() < orbit_prob
        ):
            state.orbit_active = True
            state.orbit_anchor_x = focus_x + random.gauss(0, 20)
            state.orbit_anchor_y = focus_y + random.gauss(0, 20)
            state.orbit_radius = random.uniform(10, 50)
            state.orbit_remaining = random.randint(20, 60)

        return focus_x, focus_y, direction

    def generate_color(
        self,
        state: GesturalState,
        warmth: float,
        clarity: float,
        stability: float,
        presence: float,
    ) -> Tuple[Tuple[int, int, int], str]:
        """Generate a color for the current mark. Full palette, state-influenced not restricted."""
        VIBRANT_COLORS = [
            (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
            (255, 0, 255), (0, 255, 255), (255, 128, 0), (255, 64, 64),
            (255, 192, 203), (255, 215, 0), (0, 191, 255), (138, 43, 226),
            (75, 0, 130), (0, 128, 128), (139, 69, 19), (34, 139, 34),
            (210, 180, 140), (255, 182, 193), (173, 216, 230), (144, 238, 144),
            (255, 255, 224), (221, 160, 221), (128, 0, 0), (0, 100, 0),
            (25, 25, 112), (128, 0, 128),
        ]

        use_vibrant = random.random() < (0.15 + presence * 0.15)
        if use_vibrant:
            color = random.choice(VIBRANT_COLORS)
            if stability < 0.5 and random.random() < 0.3:
                color = tuple(int(c * (0.6 + stability * 0.4)) for c in color)
            return color, "vibrant"

        import colorsys

        hue_base = warmth * 360.0
        hue = (hue_base + random.random() * 180.0) % 360.0
        saturation = max(0.1, min(1.0, 0.3 + clarity * 0.7 + (random.random() - 0.5) * 0.4))
        brightness = max(0.2, min(1.0, 0.4 + stability * 0.6 + (random.random() - 0.5) * 0.3))
        rgb = colorsys.hsv_to_rgb(hue / 360.0, saturation, brightness)
        color = tuple(int(c * 255) for c in rgb)

        if hue < 60 or hue > 300:
            hue_category = "warm"
        elif hue < 180:
            hue_category = "cool"
        else:
            hue_category = "neutral"
        return color, hue_category
