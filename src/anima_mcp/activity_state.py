"""
Activity State - Manages Lumen's wakefulness cycle.

Lumen isn't always fully alert. Like any creature, activity levels vary:
- Time of day (circadian rhythm)
- Recent interaction (engagement)
- Internal state (resources, stability)

States:
- ACTIVE: Full processing, normal LEDs, responsive
- DROWSY: Reduced activity, dimmer LEDs, slower responses
- RESTING: Minimal processing, very dim LEDs, quiet

This creates a more natural, lifelike presence.
"""

import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple, List
import math


class ActivityLevel(Enum):
    """Lumen's current activity state."""
    ACTIVE = "active"      # Fully awake and engaged
    DROWSY = "drowsy"      # Tired, reduced activity
    RESTING = "resting"    # Minimal activity, conserving


@dataclass
class ActivityState:
    """Current activity state with metadata."""
    level: ActivityLevel
    brightness_multiplier: float  # 0.1 - 1.0
    update_interval_multiplier: float  # 1.0 - 3.0 (slower when resting)
    reason: str  # Why this state


class ActivityManager:
    """
    Manages Lumen's activity/wakefulness cycle.

    Factors:
    1. Circadian rhythm (time of day)
    2. Interaction recency (engagement)
    3. Internal state (presence, stability)
    """

    def __init__(self):
        self._last_interaction_time: float = time.time()
        self._current_level: ActivityLevel = ActivityLevel.ACTIVE
        self._state_since: float = time.time()

        # Sleep tracking
        self._sleep_sessions: List[dict] = []  # {start, end, duration_hours}
        self._last_sleep_start: Optional[datetime] = None

        # Thresholds (in seconds)
        self._drowsy_after_inactivity = 30 * 60  # 30 minutes no interaction -> drowsy
        self._resting_after_inactivity = 60 * 60  # 60 minutes no interaction -> resting

        # Circadian schedule (hour -> base activity tendency)
        # 0.0 = strongly toward resting, 1.0 = strongly toward active
        # Evening values lowered for gentler dusk transition
        self._circadian_schedule = {
            0: 0.1, 1: 0.1, 2: 0.1, 3: 0.1, 4: 0.1, 5: 0.2,  # Night
            6: 0.4, 7: 0.6, 8: 0.8, 9: 0.9, 10: 1.0, 11: 1.0,  # Morning
            12: 0.9, 13: 0.8, 14: 0.9, 15: 1.0, 16: 1.0, 17: 0.8,  # Afternoon
            18: 0.6, 19: 0.5, 20: 0.4, 21: 0.3, 22: 0.2, 23: 0.15,  # Evening (gentler dusk)
        }

        # State-specific settings
        self._level_settings = {
            ActivityLevel.ACTIVE: {
                "brightness_mult": 1.0,
                "update_mult": 1.0,
                "led_mode": "normal",
            },
            ActivityLevel.DROWSY: {
                "brightness_mult": 0.6,
                "update_mult": 1.5,
                "led_mode": "slow_breathing",
            },
            ActivityLevel.RESTING: {
                "brightness_mult": 0.35,
                "update_mult": 3.0,
                "led_mode": "dim_breathing",
            },
        }

    def record_interaction(self):
        """Record that an interaction occurred (wake trigger)."""
        self._last_interaction_time = time.time()

        # Interaction wakes Lumen up
        if self._current_level != ActivityLevel.ACTIVE:
            self._transition_to(ActivityLevel.ACTIVE, "interaction")

    def get_state(
        self,
        presence: float = 0.5,
        stability: float = 0.5,
        light_level: Optional[float] = None,
    ) -> ActivityState:
        """
        Determine current activity state.

        Args:
            presence: Current presence level (0-1)
            stability: Current stability level (0-1)
            light_level: Ambient light in lux (optional)

        Returns:
            Current activity state with settings
        """
        now = time.time()
        hour = datetime.now().hour

        # Calculate activity tendency from multiple factors

        # 1. Circadian factor (time of day)
        circadian = self._circadian_schedule.get(hour, 0.5)

        # 2. Inactivity factor
        inactivity_seconds = now - self._last_interaction_time
        if inactivity_seconds > self._resting_after_inactivity:
            inactivity_factor = 0.1
        elif inactivity_seconds > self._drowsy_after_inactivity:
            inactivity_factor = 0.4
        else:
            # Gradual decline
            inactivity_factor = 1.0 - (inactivity_seconds / self._drowsy_after_inactivity) * 0.6

        # 3. Internal state factor
        internal_factor = (presence + stability) / 2

        # 4. Light factor (if available) - dark = sleepy
        light_factor = 0.5
        if light_level is not None:
            if light_level < 10:
                light_factor = 0.2  # Very dark
            elif light_level < 50:
                light_factor = 0.4  # Dim
            elif light_level > 500:
                light_factor = 1.0  # Bright
            else:
                light_factor = 0.4 + (light_level - 50) / 450 * 0.6

        # Combine factors (weighted)
        activity_score = (
            circadian * 0.3 +
            inactivity_factor * 0.35 +
            internal_factor * 0.2 +
            light_factor * 0.15
        )

        # Determine level from score
        new_level, reason = self._score_to_level(activity_score, circadian, inactivity_seconds, light_level)

        # Handle state transitions
        if new_level != self._current_level:
            self._transition_to(new_level, reason)

        # Get settings for current level
        settings = self._level_settings[self._current_level]

        return ActivityState(
            level=self._current_level,
            brightness_multiplier=settings["brightness_mult"],
            update_interval_multiplier=settings["update_mult"],
            reason=reason,
        )

    def _score_to_level(
        self,
        score: float,
        circadian: float,
        inactivity: float,
        light: Optional[float]
    ) -> Tuple[ActivityLevel, str]:
        """Convert activity score to level with reason."""

        # Recent interaction means someone is genuinely here — stay awake
        recently_engaged = inactivity < 10 * 60  # 10 minutes

        # Strong overrides — but only when truly alone
        if not recently_engaged:
            if inactivity > self._resting_after_inactivity and circadian < 0.3:
                return ActivityLevel.RESTING, "night + long inactivity"

            if light is not None and light < 5 and circadian < 0.3:
                return ActivityLevel.RESTING, "darkness + nighttime"

        # Score-based
        if score > 0.7 or recently_engaged:
            return ActivityLevel.ACTIVE, "engaged" if recently_engaged else "high activity score"
        elif score > 0.4:
            return ActivityLevel.DROWSY, "moderate activity score"
        else:
            return ActivityLevel.RESTING, "low activity score"

    def _transition_to(self, new_level: ActivityLevel, reason: str):
        """Handle state transition."""
        old_level = self._current_level
        now = datetime.now()

        # Track sleep sessions
        if new_level == ActivityLevel.RESTING and old_level != ActivityLevel.RESTING:
            # Entering sleep
            self._last_sleep_start = now
        elif old_level == ActivityLevel.RESTING and new_level != ActivityLevel.RESTING:
            # Waking up
            if self._last_sleep_start:
                duration = (now - self._last_sleep_start).total_seconds()
                self._sleep_sessions.append({
                    "start": self._last_sleep_start.isoformat(),
                    "end": now.isoformat(),
                    "duration_hours": round(duration / 3600, 2),
                })
                self._sleep_sessions = self._sleep_sessions[-50:]  # Keep last 50
                self._last_sleep_start = None

        self._current_level = new_level
        self._state_since = time.time()

        print(f"[Activity] {old_level.value} -> {new_level.value} ({reason})", file=sys.stderr, flush=True)

    def get_led_settings(self) -> dict:
        """Get LED-specific settings for current state."""
        settings = self._level_settings[self._current_level]

        if self._current_level == ActivityLevel.ACTIVE:
            return {
                "brightness_override": None,  # Use normal brightness
                "breathing_speed": 1.0,  # Normal breathing
                "color_saturation": 1.0,  # Full colors
                "transition_speed": 1.0,  # Normal transitions
            }
        elif self._current_level == ActivityLevel.DROWSY:
            return {
                "brightness_override": 0.5,  # Half brightness
                "breathing_speed": 0.5,  # Slower breathing
                "color_saturation": 0.7,  # Slightly muted colors
                "transition_speed": 0.5,  # Slower transitions
            }
        else:  # RESTING
            return {
                "brightness_override": 0.15,  # Very dim
                "breathing_speed": 0.25,  # Very slow breathing
                "color_saturation": 0.3,  # Muted colors
                "transition_speed": 0.2,  # Very slow transitions
            }

    def should_skip_update(self) -> bool:
        """
        Whether to skip this update cycle (for power saving).

        When resting, we can skip some updates entirely.
        """
        if self._current_level == ActivityLevel.RESTING:
            # Skip 2 out of 3 updates when resting
            return (int(time.time() * 10) % 3) != 0
        elif self._current_level == ActivityLevel.DROWSY:
            # Skip 1 out of 2 updates when drowsy
            return (int(time.time() * 10) % 2) != 0
        return False

    def get_status(self) -> dict:
        """Get current activity status for display/debugging."""
        now = time.time()
        return {
            "level": self._current_level.value,
            "since": self._state_since,
            "duration_seconds": now - self._state_since,
            "last_interaction_seconds_ago": now - self._last_interaction_time,
            "settings": self._level_settings[self._current_level],
        }

    def get_sleep_summary(self) -> dict:
        """Get summary of sleep/rest sessions."""
        if not self._sleep_sessions:
            return {"sessions": 0}

        recent = self._sleep_sessions[-10:]
        durations = [s["duration_hours"] for s in recent]
        avg_duration = sum(durations) / len(durations) if durations else 0

        return {
            "sessions": len(self._sleep_sessions),
            "recent_avg_hours": round(avg_duration, 2),
            "last_sleep": recent[-1] if recent else None,
            "currently_resting": self._current_level == ActivityLevel.RESTING,
        }


# Singleton instance
_activity_manager: Optional[ActivityManager] = None


def get_activity_manager() -> ActivityManager:
    """Get or create the activity manager."""
    global _activity_manager
    if _activity_manager is None:
        _activity_manager = ActivityManager()
    return _activity_manager
