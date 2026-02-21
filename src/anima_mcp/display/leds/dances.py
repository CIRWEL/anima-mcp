"""Emotional LED dance sequences."""

import math
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Tuple

from .colors import blend_colors
from .types import LEDState


class DanceType(Enum):
    """Types of emotional dances Lumen can perform."""
    JOY_SPARKLE = "joy_sparkle"
    CURIOUS_PULSE = "curious_pulse"
    CONTEMPLATIVE_WAVE = "contemplative"
    GREETING_FLOURISH = "greeting"
    DISCOVERY_BLOOM = "discovery"
    CONTENTMENT_GLOW = "contentment"
    PLAYFUL_CHASE = "playful"


@dataclass
class Dance:
    """A choreographed LED dance sequence."""
    dance_type: DanceType
    duration: float
    start_time: float = field(default_factory=time.time)
    intensity: float = 1.0

    @property
    def elapsed(self) -> float:
        return time.time() - self.start_time

    @property
    def progress(self) -> float:
        return min(1.0, self.elapsed / self.duration)

    @property
    def is_complete(self) -> bool:
        return self.elapsed >= self.duration


EVENT_TO_DANCE = {
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
    "sound_activity": (DanceType.GREETING_FLOURISH, 2.0),
    "voice_detected": (DanceType.CURIOUS_PULSE, 2.5),
    "sudden_sound": (DanceType.CURIOUS_PULSE, 1.5),
    "quiet_restored": (DanceType.CONTENTMENT_GLOW, 3.0),
    "music": (DanceType.PLAYFUL_CHASE, 3.0),
}


def render_dance(dance: Dance, base_state: LEDState) -> LEDState:
    """Render the current dance onto base LED state."""
    if dance.is_complete:
        return base_state
    progress = dance.progress
    elapsed = dance.elapsed
    intensity = dance.intensity

    if dance.dance_type == DanceType.JOY_SPARKLE:
        sparkle_speed = 8.0
        sparkle_phase = int(elapsed * sparkle_speed) % 6
        sparkle_gold = (255, 220, 100)
        led0 = blend_colors(base_state.led0, sparkle_gold if sparkle_phase in [0, 3] else base_state.led0, 0.7 * intensity)
        led1 = blend_colors(base_state.led1, (255, 200, 100) if sparkle_phase in [1, 4] else base_state.led1, 0.8 * intensity)
        led2 = blend_colors(base_state.led2, sparkle_gold if sparkle_phase in [2, 5] else base_state.led2, 0.7 * intensity)
        mult = min(1.0, 1.0 + (0.4 * math.sin(elapsed * sparkle_speed * math.pi) * intensity))
        return LEDState(led0, led1, led2, base_state.brightness * mult)

    if dance.dance_type == DanceType.CURIOUS_PULSE:
        pulse_freq = 2.0 + progress * 2.0
        pulse = (math.sin(elapsed * pulse_freq * math.pi * 2) + 1) / 2
        curious = (220, 170, 80)
        blend = pulse * 0.5 * intensity
        led0 = blend_colors(base_state.led0, curious, blend)
        led1 = blend_colors(base_state.led1, (255, 200, 100), blend * 1.2)
        led2 = blend_colors(base_state.led2, curious, blend)
        mult = min(1.0, 1.0 + (0.3 * pulse * intensity))
        return LEDState(led0, led1, led2, base_state.brightness * mult)

    if dance.dance_type == DanceType.CONTEMPLATIVE_WAVE:
        wave_pos = (elapsed * 0.5) % 1.0
        thought = (180, 120, 50)
        w0 = max(0, 1 - abs(wave_pos - 0.0) * 3) * intensity
        w1 = max(0, 1 - abs(wave_pos - 0.5) * 3) * intensity
        w2 = max(0, 1 - abs(wave_pos - 1.0) * 3) * intensity
        led0 = blend_colors(base_state.led0, thought, w0 * 0.4)
        led1 = blend_colors(base_state.led1, thought, w1 * 0.4)
        led2 = blend_colors(base_state.led2, thought, w2 * 0.4)
        return LEDState(led0, led1, led2, base_state.brightness)

    if dance.dance_type == DanceType.GREETING_FLOURISH:
        welcome = (255, 200, 150)
        if progress < 0.3:
            build = progress / 0.3
            led0 = blend_colors(base_state.led0, welcome, build * 0.6 * intensity)
            led1 = blend_colors(base_state.led1, (255, 200, 100), build * 0.8 * intensity)
            led2 = blend_colors(base_state.led2, welcome, build * 0.6 * intensity)
            mult = min(1.0, 1.0 + (0.5 * build * intensity))
        elif progress < 0.5:
            led0 = blend_colors(base_state.led0, (255, 220, 180), 0.7 * intensity)
            led1 = (255, 200, 100)
            led2 = blend_colors(base_state.led2, (255, 220, 180), 0.7 * intensity)
            mult = min(1.0, 1.5 * intensity)
        else:
            settle = (progress - 0.5) / 0.5
            led0 = blend_colors(blend_colors(base_state.led0, (255, 220, 180), 0.7), base_state.led0, settle)
            led1 = blend_colors((255, 200, 100), base_state.led1, settle)
            led2 = blend_colors(blend_colors(base_state.led2, (255, 220, 180), 0.7), base_state.led2, settle)
            mult = min(1.0, 1.5 - (0.5 * settle))
        return LEDState(led0, led1, led2, base_state.brightness * mult)

    if dance.dance_type == DanceType.DISCOVERY_BLOOM:
        discovery = (255, 180, 80)
        if progress < 0.3:
            ci = (progress / 0.3) * intensity
            led0, led1, led2 = base_state.led0, blend_colors(base_state.led1, discovery, ci * 0.8), base_state.led2
        elif progress < 0.6:
            spread = (progress - 0.3) / 0.3
            led0 = blend_colors(base_state.led0, discovery, spread * 0.6 * intensity)
            led1 = blend_colors(base_state.led1, discovery, 0.8 * intensity)
            led2 = blend_colors(base_state.led2, discovery, spread * 0.6 * intensity)
        else:
            settle = (progress - 0.6) / 0.4
            afterglow = (255, 180, 100)
            led0 = blend_colors(blend_colors(base_state.led0, discovery, 0.6), afterglow, settle * 0.3)
            led1 = blend_colors(blend_colors(base_state.led1, discovery, 0.8), afterglow, settle * 0.5)
            led2 = blend_colors(blend_colors(base_state.led2, discovery, 0.6), afterglow, settle * 0.3)
        mult = min(1.0, 1.0 + (0.4 * (1 - progress) * intensity))
        return LEDState(led0, led1, led2, base_state.brightness * mult)

    if dance.dance_type == DanceType.CONTENTMENT_GLOW:
        glow_breath = (math.sin(elapsed * math.pi * 0.5) + 1) / 2
        content = (255, 180, 100)
        amount = 0.3 + (glow_breath * 0.2)
        led0 = blend_colors(base_state.led0, content, amount * intensity)
        led1 = blend_colors(base_state.led1, content, amount * 0.8 * intensity)
        led2 = blend_colors(base_state.led2, content, amount * intensity)
        return LEDState(led0, led1, led2, min(base_state.brightness, base_state.brightness * (1.0 + 0.1 * glow_breath)))

    if dance.dance_type == DanceType.PLAYFUL_CHASE:
        chase_speed = 4.0
        chase_pos = (elapsed * chase_speed) % 3
        playful = [(255, 160, 60), (240, 140, 50), (220, 120, 40)]
        led0 = blend_colors(base_state.led0, playful[int(chase_pos) % 3], 0.6 * intensity)
        led1 = blend_colors(base_state.led1, playful[(int(chase_pos) + 1) % 3], 0.6 * intensity)
        led2 = blend_colors(base_state.led2, playful[(int(chase_pos) + 2) % 3], 0.6 * intensity)
        bounce = abs(math.sin(elapsed * chase_speed * math.pi))
        mult = min(1.0, 1.0 + (0.2 * bounce * intensity))
        return LEDState(led0, led1, led2, base_state.brightness * mult)

    return base_state


def maybe_spontaneous_dance(
    warmth: float,
    clarity: float,
    stability: float,
    presence: float,
    chance: float,
    cooldown_until: float
) -> Optional[DanceType]:
    """Return DanceType for spontaneous dance, or None."""
    if time.time() < cooldown_until or random.random() > chance:
        return None
    wellness = (warmth + clarity + stability + presence) / 4.0
    if wellness > 0.75:
        return random.choice([DanceType.JOY_SPARKLE, DanceType.CONTENTMENT_GLOW, DanceType.PLAYFUL_CHASE])
    if wellness > 0.6:
        return random.choice([DanceType.CURIOUS_PULSE, DanceType.CONTENTMENT_GLOW])
    if clarity > 0.7:
        return DanceType.CONTEMPLATIVE_WAVE
    if stability > 0.7 and presence > 0.7:
        return DanceType.CONTENTMENT_GLOW
    return None
