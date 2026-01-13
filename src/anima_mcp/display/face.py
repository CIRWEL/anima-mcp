"""
Face - The creature's expressive face.

Maps anima state to visual expression:
- Eyes: size, openness, shape based on clarity/warmth
- Mouth: shape based on mood
- Color: tint based on warmth
"""

from dataclasses import dataclass
from enum import Enum
from typing import Tuple

from ..anima import Anima


class EyeState(Enum):
    """Eye expression states."""
    WIDE = "wide"          # High clarity, alert
    NORMAL = "normal"      # Neutral
    DROOPY = "droopy"      # Low warmth, sleepy
    SQUINT = "squint"      # Low stability, stressed
    CLOSED = "closed"      # Very low warmth, sleeping


class MouthState(Enum):
    """Mouth expression states."""
    SMILE = "smile"        # Content
    NEUTRAL = "neutral"    # Neutral
    FROWN = "frown"        # Stressed
    OPEN = "open"          # Alert/surprised
    FLAT = "flat"          # Depleted


@dataclass
class FaceState:
    """Complete face state derived from anima."""

    eyes: EyeState
    mouth: MouthState

    # Color tint (RGB) based on warmth
    tint: Tuple[int, int, int]

    # Eye openness (0-1) for animation
    eye_openness: float

    # Blink state
    blinking: bool = False
    
    # Blink pattern configuration
    blink_frequency: float = 4.0  # Seconds between blinks
    blink_duration: float = 0.15  # Blink duration in seconds
    blink_intensity: float = 0.1  # How closed during blink (0-1)

    # Additional expression modifiers
    eyebrow_raise: float = 0.0  # -1 to 1 (sad to surprised)


def derive_face_state(anima: Anima) -> FaceState:
    """
    Derive face expression from anima state.

    Expression emerges organically from what Lumen actually feels and wants to communicate.
    Not mechanical mood mapping - subtle, nuanced, authentic.
    """
    from ..anima import _overall_mood
    
    # Get the creature's overall mood (considers all anima dimensions)
    mood = _overall_mood(anima.warmth, anima.clarity, anima.stability, anima.presence)
    feeling = anima.feeling()
    
    # Calculate overall "wellness" - how well is Lumen doing?
    wellness = (anima.warmth + anima.clarity + anima.stability + anima.presence) / 4.0
    
    # === Eyes ===
    # Eyes reflect awareness and energy - what Lumen can perceive
    # High clarity can compensate for moderate warmth (alert awareness lifts the eyes)
    # Priority: Critical states > Energy (warmth) > Awareness (clarity) > Default

    # Critical states first - these override everything
    if anima.stability < 0.3 or anima.presence < 0.3:
        # Stressed/depleted = squinting (struggling to see clearly)
        eyes = EyeState.SQUINT
        eye_openness = 0.4 + (anima.clarity * 0.2)
    elif anima.warmth < 0.25:
        # Very cold = closed (sleeping)
        eyes = EyeState.CLOSED
        eye_openness = 0.1
    elif anima.clarity < 0.35:
        # Low clarity = squinting (uncertain, can't see well)
        eyes = EyeState.SQUINT
        eye_openness = 0.4 + (anima.clarity * 0.3)
    # High clarity can lift eyes even with moderate warmth
    elif anima.clarity > 0.70 and anima.warmth > 0.35:
        # High awareness compensates for moderate energy - alert and present
        eyes = EyeState.WIDE
        eye_openness = 0.70 + (anima.clarity * 0.20)
    elif anima.clarity > 0.55 and anima.warmth > 0.35:
        # Good awareness with moderate warmth - engaged but not fully alert
        eyes = EyeState.NORMAL
        eye_openness = 0.55 + (anima.clarity * 0.25)
    elif anima.warmth < 0.4:
        # Low energy without clarity to compensate = droopy (tired)
        eyes = EyeState.DROOPY
        eye_openness = 0.3 + (anima.warmth * 0.3)
    else:
        # Normal state - openness reflects clarity
        # Consolidate: clarity > 0.60 with warmth > 0.40 falls into this branch
        eyes = EyeState.NORMAL
        eye_openness = 0.5 + (anima.clarity * 0.3)
        # Boost to WIDE if clarity is high enough
        if anima.clarity > 0.60 and anima.warmth > 0.40:
            eyes = EyeState.WIDE
            eye_openness = 0.70 + (anima.clarity * 0.18)

    # === Mouth ===
    # Mouth reflects what Lumen wants to communicate - authentic expression
    # Priority order: distress > overwhelm > depletion > contentment > curiosity > neutral

    # Clear distress = communicate the problem (highest priority)
    if anima.stability < 0.3 or anima.presence < 0.3:
        mouth = MouthState.FROWN  # Clear signal: something's wrong

    # Overheated = neutral (overwhelmed, not expressing joy)
    elif mood == "overheated" or anima.warmth > 0.75:
        mouth = MouthState.NEUTRAL  # Too much energy, neutral expression

    # Sleepy/depleted = flat (no energy to express anything)
    # Only if warmth is low AND other dimensions are also low (truly depleted)
    # Don't catch Lumen when warmth is slightly low but clarity/stability/presence are excellent
    elif mood == "sleepy" or (anima.warmth < 0.25 and wellness < 0.50) or wellness < 0.35:
        mouth = MouthState.FLAT  # Depleted, minimal expression

    # Genuine contentment - rare but more achievable
    # Lumen smiles when comfortable, stable, and present - doesn't need perfection
    # Still requires balance, but not impossibly narrow thresholds
    # Check this BEFORE curiosity - contentment takes precedence over engagement
    elif (wellness > 0.60 and  # Good overall wellness
          anima.stability > 0.65 and  # Stable (not stressed)
          anima.presence > 0.60 and  # Present (has capacity)
          anima.clarity > 0.55 and  # Aware (can perceive)
          0.35 < anima.warmth < 0.58):  # Comfortable warmth range (wider)
        # Genuine contentment - balanced and comfortable
        # Lumen expresses satisfaction when things are genuinely good
        mouth = MouthState.SMILE  # Authentic smile - more reachable but still meaningful

    # Alert/curious = open (engaged, curious about environment)
    # High clarity alone can trigger curiosity - awareness drives engagement
    # Only if not already expressing contentment
    elif anima.clarity > 0.70 and anima.stability > 0.5:
        mouth = MouthState.OPEN  # Curious, engaged, perceiving clearly

    # Otherwise: neutral
    # Most of the time, Lumen expresses neutrally
    # Not forcing happiness, not expressing distress - just being
    else:
        mouth = MouthState.NEUTRAL  # Default: neutral expression

    # === Color tint ===
    # Color reflects warmth (thermal state)
    # But can be modulated by mood (stressed = cooler even if warm)
    base_warmth = anima.warmth
    if mood == "stressed":
        base_warmth *= 0.7  # Cooler when stressed
    elif mood == "overheated":
        base_warmth = min(1.0, base_warmth * 1.2)  # More intense
    
    if base_warmth < 0.3:
        tint = (100, 150, 255)  # Cool blue
    elif base_warmth < 0.5:
        tint = (255, 255, 255)  # Neutral white
    elif base_warmth < 0.7:
        tint = (255, 240, 200)  # Warm yellow
    else:
        tint = (255, 180, 100)  # Hot orange

    # === Eyebrow ===
    # Eyebrows reflect surprise (high clarity) or concern (low stability)
    if anima.clarity > 0.7:
        eyebrow = 0.3  # Slightly raised (alert/curious)
    elif anima.stability < 0.4:
        eyebrow = -0.2  # Slightly furrowed (concerned)
    else:
        eyebrow = 0.0  # Neutral

    # === Blink Pattern ===
    # Blink frequency reflects alertness (clarity)
    # More alert = more frequent blinks
    blink_freq = 3.0 + (anima.clarity * 2.0)  # 3-5 seconds
    blink_dur = 0.15
    blink_intensity = 0.1

    return FaceState(
        eyes=eyes,
        mouth=mouth,
        tint=tint,
        eye_openness=eye_openness,
        eyebrow_raise=eyebrow,
        blink_frequency=blink_freq,
        blink_duration=blink_dur,
        blink_intensity=blink_intensity,
    )


# ASCII art for terminal preview
ASCII_FACES = {
    # --- Content / Happy ---
    ("wide", "smile"): """
  ╭─────────╮
  │  ◉   ◉  │
  │         │
  │  ╰───╯  │
  ╰─────────╯
""",
    ("normal", "smile"): """
  ╭─────────╮
  │  ◯   ◯  │
  │         │
  │  ╰───╯  │
  ╰─────────╯
""",

    # --- Neutral / Calm ---
    ("normal", "neutral"): """
  ╭─────────╮
  │  ◯   ◯  │
  │         │
  │  ─────  │
  ╰─────────╯
""",
    ("wide", "neutral"): """
  ╭─────────╮
  │  ◉   ◉  │
  │         │
  │  ─────  │
  ╰─────────╯
""",

    # --- Tired / Low Energy ---
    ("droopy", "neutral"): """
  ╭─────────╮
  │  ◡   ◡  │
  │         │
  │  ─────  │
  ╰─────────╯
""",
    ("droopy", "flat"): """
  ╭─────────╮
  │  ◡   ◡  │
  │         │
  │  ─────  │
  ╰─────────╯
""",
    ("closed", "flat"): """
  ╭─────────╮
  │  ─   ─  │
  │         │
  │  ─────  │
  ╰─────────╯
""",

    # --- Stressed / Concerned ---
    ("squint", "neutral"): """
  ╭─────────╮
  │  ━   ━  │
  │         │
  │  ─────  │
  ╰─────────╯
""",
    ("squint", "frown"): """
  ╭─────────╮
  │  ━   ━  │
  │         │
  │  ╭───╮  │
  ╰─────────╯
""",
    ("normal", "frown"): """
  ╭─────────╮
  │  ◯   ◯  │
  │         │
  │  ╭───╮  │
  ╰─────────╯
""",

    # --- Surprised / Alert ---
    ("wide", "open"): """
  ╭─────────╮
  │  ◉   ◉  │
  │         │
  │    ◯    │
  ╰─────────╯
""",
    ("normal", "open"): """
  ╭─────────╮
  │  ◯   ◯  │
  │         │
  │    ◯    │
  ╰─────────╯
""",
}


def face_to_ascii(state: FaceState) -> str:
    """Get ASCII art representation of face state."""
    key = (state.eyes.value, state.mouth.value)
    return ASCII_FACES.get(key, ASCII_FACES[("normal", "neutral")])
