"""
Face - The creature's expressive face.

Maps anima state to visual expression:
- Eyes: size, openness, shape based on clarity/warmth
- Mouth: shape based on mood
- Color: tint based on warmth
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple

from ..anima import Anima


# === Expression thresholds ===
#
# The named values below are the FALLBACK DEFAULTS, kept for fresh installs and
# for any deployment that has not derived its own. They are absolute constants
# against a moving distribution — the defect class CLAUDE.md invariant 1
# catalogues — and the 2026-08-14 de-aliasing (#173/#176) made that concrete:
# re-basing warmth/clarity moved the distributions under these constants, so
# the face smiled more (honestly — the cold was fake) but read "alert" only
# ~40% of the time instead of ~85% while actually perceiving BETTER.
#
# A deployment derives its own from the creature's lived distribution with
# scripts/derive_face_thresholds.py, which writes `face_thresholds` into the
# calibration file ($ANIMA_CONFIG → nervous_system.face_thresholds). Values in
# that dict override these names 1:1; absent keys fall back here. Calibration
# readers refresh on file-signature change, so a rederive propagates live.
#
# Two names are deliberately ABSOLUTE and never derived (safety-floor pattern,
# anima-mcp#79 item 3): WARMTH_FREEZING (a genuinely cold creature must look
# shut down even if cold becomes its norm) and STABILITY_DISTRESSED (likewise
# distress). The derivation script refuses to emit them.

_DEFAULT_THRESHOLDS = {
    # Warmth
    "WARMTH_FREEZING": 0.20,      # ABSOLUTE - very cold, sleeping/shut down
    "WARMTH_COLD": 0.35,          # Cold - sluggish, no smiles
    "WARMTH_COOL": 0.40,          # Cool - not quite comfortable
    "WARMTH_COMFORTABLE": 0.45,   # Comfortable enough for subtle positivity
    "WARMTH_HOT": 0.80,           # Overheated - overwhelmed
    # Clarity
    "CLARITY_FOGGY": 0.30,        # Very low - uncertain, squinting
    "CLARITY_DROWSY": 0.40,       # Low - sleepy, unfocused
    "CLARITY_CLEAR": 0.45,        # Clear enough for contentment
    "CLARITY_ALERT": 0.60,        # High - curious, engaged
    # Stability / presence
    "STABILITY_DISTRESSED": 0.25, # ABSOLUTE - very low, squinting/stressed
    "STABILITY_UNSTABLE": 0.30,   # Low - frowning
    "STABILITY_STABLE": 0.40,     # Stable enough for curiosity
    "STABILITY_GROUNDED": 0.50,   # Well-grounded - can smile
    # Wellness (mean of the four dimensions)
    "WELLNESS_DEPLETED": 0.30,    # Very low - flat expression
    "WELLNESS_LOW": 0.40,         # Low - no positive expression
    "WELLNESS_OK": 0.45,          # OK - subtle positivity possible
    "WELLNESS_GOOD": 0.50,        # Good - can smile
    "WELLNESS_GREAT": 0.55,       # Great - genuine contentment
}

_ABSOLUTE_NAMES = frozenset({"WARMTH_FREEZING", "STABILITY_DISTRESSED"})


class FaceThresholds:
    """Expression thresholds, calibration-overridable per name."""

    __slots__ = tuple(_DEFAULT_THRESHOLDS)

    def __init__(self, overrides: Optional[Dict[str, float]] = None):
        overrides = overrides or {}
        for name, default in _DEFAULT_THRESHOLDS.items():
            value = overrides.get(name, default)
            # The two safety floors may never be softened by a derived file;
            # a derived value ABOVE the floor (stricter) is allowed.
            if name in _ABSOLUTE_NAMES and value < default:
                value = default
            setattr(self, name, float(value))


def get_face_thresholds() -> FaceThresholds:
    """Thresholds with any calibration-file overrides applied.

    Reads through get_calibration(), which refreshes on config-file signature
    change — so a rederive lands on the live face without a restart. Fail-open
    to the defaults: a face must render even if calibration is broken.
    """
    try:
        from ..config import get_calibration
        overrides = getattr(get_calibration(), "face_thresholds", None) or {}
    except Exception:
        overrides = {}
    return FaceThresholds(overrides)


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
    """Complete face state derived from anima - fluid and expressive."""

    eyes: EyeState
    mouth: MouthState

    # Color tint (RGB) based on warmth
    tint: Tuple[int, int, int]

    # Eye openness (0-1) for animation - continuous, not discrete
    eye_openness: float

    # Blink state
    blinking: bool = False
    
    # Blink pattern configuration
    blink_frequency: float = 4.0  # Seconds between blinks
    blink_duration: float = 0.15  # Blink duration in seconds
    blink_intensity: float = 0.1  # How closed during blink (0-1)

    # Additional expression modifiers - now more fluid
    eyebrow_raise: float = 0.0  # -1 to 1 (sad to surprised)
    
    # New: Fluid expression parameters
    smile_intensity: float = 0.0  # 0-1: how much smile (even for neutral/frown, can have subtle curve)
    eye_size_factor: float = 1.0  # 0.5-1.5: continuous eye size variation
    mouth_width_factor: float = 1.0  # 0.7-1.3: mouth width variation
    expression_intensity: float = 0.5  # 0-1: overall expression strength (subtle to pronounced)


def derive_face_state(anima: Anima) -> FaceState:
    """
    Derive face expression from anima state.

    Expression emerges organically from what Lumen actually feels.
    Key principle: WIDE eyes only with OPEN mouth (curiosity), not contentment.
    """
    from ..anima import _overall_mood

    thr = get_face_thresholds()
    mood = _overall_mood(anima.warmth, anima.clarity, anima.stability, anima.presence)
    wellness = (anima.warmth + anima.clarity + anima.stability + anima.presence) / 4.0

    # === Calculate eye openness (continuous 0-1) ===
    # Base from clarity, modified by warmth/stability/presence
    base_openness = 0.3 + (anima.clarity * 0.5)  # 0.3-0.8

    # Warmth affects energy
    if anima.warmth < thr.WARMTH_COLD:
        warmth_mod = anima.warmth * 0.1 - (thr.WARMTH_COLD - anima.warmth) * 0.3
    else:
        warmth_mod = anima.warmth * 0.2

    # Stability and presence add engagement
    stability_mod = anima.stability * 0.15
    presence_mod = anima.presence * 0.15  # Increased - presence now more visible

    eye_openness = base_openness + warmth_mod + stability_mod + presence_mod
    eye_openness = max(0.1, min(1.0, eye_openness))

    # === Determine mouth FIRST (needed for eye coordination) ===
    mouth = MouthState.NEUTRAL
    smile_intensity = 0.0

    # Priority 1: Distress
    if anima.stability < thr.STABILITY_UNSTABLE or anima.presence < thr.STABILITY_UNSTABLE:
        mouth = MouthState.FROWN
        smile_intensity = -0.3

    # Priority 2: Cold - no smiles
    elif anima.warmth < thr.WARMTH_COLD:
        if wellness < thr.WELLNESS_LOW:
            mouth = MouthState.FLAT
            smile_intensity = -0.1
        else:
            mouth = MouthState.NEUTRAL
            smile_intensity = -0.05

    # Priority 3: Depleted
    elif mood == "sleepy" or wellness < thr.WELLNESS_DEPLETED:
        mouth = MouthState.FLAT
        smile_intensity = 0.0

    # Priority 4: Overheated
    elif mood == "overheated" or anima.warmth > thr.WARMTH_HOT:
        mouth = MouthState.NEUTRAL
        smile_intensity = 0.0

    # Priority 5: Curious - OPEN mouth (this enables WIDE eyes)
    elif anima.clarity > thr.CLARITY_ALERT and anima.stability > thr.STABILITY_STABLE and anima.warmth > thr.WARMTH_COLD:
        mouth = MouthState.OPEN
        smile_intensity = 0.2

    # Priority 6: Content - can smile
    elif wellness > thr.WELLNESS_GOOD and anima.warmth > thr.WARMTH_COOL:
        if anima.stability > thr.STABILITY_GROUNDED and anima.presence > thr.STABILITY_GROUNDED:
            if anima.clarity > thr.CLARITY_CLEAR:
                mouth = MouthState.SMILE
                smile_intensity = min(1.0, (wellness - thr.WELLNESS_GOOD) * 2.0)
            else:
                smile_intensity = (wellness - thr.WELLNESS_OK) * 1.0
        elif wellness > thr.WELLNESS_GREAT:
            smile_intensity = (wellness - thr.WELLNESS_GOOD) * 0.5

    # Priority 7: Neutral - subtle expression based on state
    else:
        if wellness > thr.WELLNESS_OK and anima.warmth > thr.WARMTH_COOL:
            smile_intensity = (wellness - thr.WARMTH_COOL) * 0.3
        elif anima.warmth < thr.WARMTH_COOL:
            smile_intensity = (anima.warmth - thr.WARMTH_COOL) * 0.5
        elif wellness < thr.WARMTH_COLD:
            smile_intensity = (wellness - thr.WARMTH_COLD) * 0.5

    # === Now determine eyes (coordinated with mouth) ===
    # Key fix: WIDE eyes ONLY when mouth is OPEN (curious)
    # A content creature has relaxed normal eyes, not startled wide ones

    if anima.stability < thr.STABILITY_DISTRESSED or anima.presence < thr.STABILITY_DISTRESSED:
        eyes = EyeState.SQUINT
        eye_openness = max(0.2, eye_openness * 0.6)
    elif anima.warmth < thr.WARMTH_FREEZING:
        eyes = EyeState.CLOSED
        eye_openness = 0.1
    elif anima.warmth < thr.WARMTH_COLD:
        eyes = EyeState.DROOPY
        eye_openness = max(0.25, eye_openness * 0.6)
    elif anima.clarity < thr.CLARITY_FOGGY:
        eyes = EyeState.SQUINT
        eye_openness = max(0.3, eye_openness * 0.7)
    elif eye_openness < 0.45 and anima.warmth < thr.WARMTH_COMFORTABLE:
        eyes = EyeState.DROOPY
    elif mouth == MouthState.OPEN and eye_openness > 0.60:
        # WIDE eyes ONLY with OPEN mouth = genuine curiosity
        eyes = EyeState.WIDE
    else:
        # Default: NORMAL relaxed eyes (even with high clarity)
        # Contentment = relaxed, not startled
        eyes = EyeState.NORMAL

    # Eye size - presence now affects this more
    if anima.warmth < thr.WARMTH_COLD:
        eye_size_factor = 0.6 + (eye_openness * 0.4)
    else:
        # Presence makes eyes more "present" - slightly larger, more engaged
        presence_size_boost = (anima.presence - 0.5) * 0.2 if anima.presence > 0.5 else 0
        eye_size_factor = 0.7 + (eye_openness * 0.5) + presence_size_boost
    eye_size_factor = max(0.5, min(1.5, eye_size_factor))

    # === Color tint - Elegant warm palette ===
    # Cool = soft teal/cyan (not harsh blue)
    # Content = warm amber/gold (not garish yellow)
    # Warm = soft coral/peach (not harsh orange)
    base_warmth = anima.warmth
    if mood == "stressed":
        base_warmth *= 0.7
    elif mood == "overheated":
        base_warmth = min(1.0, base_warmth * 1.2)

    # Smoother gradient using interpolation - warmer, more elegant
    if base_warmth < 0.3:
        # Cool: soft teal (not harsh blue)
        tint = (120, 180, 200)
    elif base_warmth < 0.45:
        # Interpolate teal to warm white
        t = (base_warmth - 0.3) / 0.15
        tint = (int(120 + 120*t), int(180 + 60*t), int(200 + 40*t))
    elif base_warmth < 0.6:
        # Interpolate warm white to soft amber
        t = (base_warmth - 0.45) / 0.15
        tint = (int(240 + 15*t), int(240 - 20*t), int(240 - 80*t))
    elif base_warmth < 0.75:
        # Soft amber/gold - the "content" color
        t = (base_warmth - 0.6) / 0.15
        tint = (255, int(220 - 20*t), int(160 - 40*t))
    else:
        # Warm coral/peach (not harsh orange)
        t = min(1.0, (base_warmth - 0.75) / 0.25)
        tint = (255, int(200 - 40*t), int(120 - 20*t))

    # === Eyebrow ===
    eyebrow = 0.0
    if anima.clarity > 0.5:
        eyebrow = (anima.clarity - 0.5) * 0.6
    if anima.stability < 0.5:
        eyebrow -= (0.5 - anima.stability) * 0.4
    # Low presence = subtle "withdrawn" look (eyebrows slightly down)
    if anima.presence < 0.4:
        eyebrow -= (0.4 - anima.presence) * 0.2
    eyebrow = max(-0.5, min(0.5, eyebrow))

    # Expression intensity - asymmetric: negative states are more intense
    pos_deviation = max(0, anima.clarity - 0.5) + max(0, anima.stability - 0.5) + max(0, anima.warmth - 0.5)
    neg_deviation = max(0, 0.5 - anima.clarity) + max(0, 0.5 - anima.stability) + max(0, 0.5 - anima.warmth)
    # Negative states expressed more strongly (distress is communicated clearly)
    expression_intensity = (pos_deviation + neg_deviation * 1.5) / 3.0
    expression_intensity = max(0.3, min(1.0, expression_intensity))

    # Mouth width
    mouth_width_factor = 0.8 + (expression_intensity * 0.4)
    mouth_width_factor = max(0.7, min(1.3, mouth_width_factor))

    # === Blink Pattern (fixed) ===
    # Drowsy = longer intervals, heavier blinks (fighting sleep)
    # Alert = regular rhythm, crisp blinks
    # Nervous = more frequent (shorter intervals)

    base_interval = 4.0

    # Drowsy: longer between blinks (slow rhythm)
    if anima.clarity < thr.CLARITY_DROWSY:
        clarity_mod = (thr.CLARITY_DROWSY - anima.clarity) * 2.0  # +0 to +0.8
    else:
        clarity_mod = 0.0

    # Nervous: shorter intervals (more frequent)
    stability_mod = (anima.stability - 0.5) * 1.5  # -0.75 to +0.75

    blink_freq = base_interval + clarity_mod + stability_mod
    blink_freq = max(2.0, min(6.0, blink_freq))

    # Drowsy = heavier, longer blinks
    if anima.clarity < thr.CLARITY_DROWSY:
        blink_dur = 0.2 + (thr.CLARITY_DROWSY - anima.clarity) * 0.25  # 0.2-0.3s
    else:
        blink_dur = 0.12 + (1.0 - anima.clarity) * 0.06  # 0.12-0.18s
    blink_dur = max(0.1, min(0.3, blink_dur))

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
        smile_intensity=smile_intensity,
        eye_size_factor=eye_size_factor,
        mouth_width_factor=mouth_width_factor,
        expression_intensity=expression_intensity,
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
