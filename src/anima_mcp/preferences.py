"""
Preferences - Learned preferences that emerge from experience.

Core philosophical insight: Agency requires wanting things.
Without preferences, there's no basis for action beyond reaction.

This module lets Lumen develop preferences through experience:
- States that preceded positive outcomes become preferred
- States that preceded negative outcomes become avoided
- Preferences guide attention, action, and self-regulation

What counts as "positive" or "negative"?
- Stability recovering after instability → stability is valued
- Interaction following high clarity → clarity is valued
- Discomfort following extreme states → moderation is valued
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any
from collections import deque
import json
import sys
from pathlib import Path

from .atomic_write import atomic_json_write
import math


@dataclass
class Experience:
    """A single experience that can shape preferences."""
    timestamp: datetime
    state_before: Dict[str, float]  # warmth, clarity, stability, presence
    state_after: Dict[str, float]
    event_type: str  # "disruption", "calm" (fired from stable_creature.py)
    valence: float  # -1 to 1, how "good" this experience was


@dataclass
class Preference:
    """A learned preference for a particular state dimension."""
    dimension: str  # warmth, clarity, stability, presence, light, temperature

    # Learned valence: positive means this dimension is valued
    valence: float = 0.0  # -1 to 1

    # Optimal range learned from experience
    optimal_low: float = 0.3
    optimal_high: float = 0.7

    # Confidence in this preference
    confidence: float = 0.0

    # Number of experiences that shaped this
    experience_count: int = 0

    def current_satisfaction(self, value: float) -> float:
        """How satisfied is this preference given current value?"""
        if self.optimal_low <= value <= self.optimal_high:
            # In optimal range
            center = (self.optimal_low + self.optimal_high) / 2
            distance_from_center = abs(value - center) / (self.optimal_high - self.optimal_low)
            return 1.0 - distance_from_center * 0.3  # Slight preference for center
        elif value < self.optimal_low:
            return max(0.0, 1.0 - (self.optimal_low - value) * 2)
        else:
            return max(0.0, 1.0 - (value - self.optimal_high) * 2)

    def update_from_experience(self, state_value: float, outcome_valence: float, learning_rate: float = 0.1):
        """Update preference based on an experience."""
        self.experience_count += 1

        # Update overall valence for this dimension
        if outcome_valence > 0:
            # Good outcome - value this dimension more if it was active
            contribution = state_value * outcome_valence
            self.valence = self.valence + learning_rate * (contribution - self.valence)
        else:
            # Bad outcome - update differently
            contribution = (1 - state_value) * abs(outcome_valence)
            self.valence = self.valence - learning_rate * contribution

        self.valence = max(-1, min(1, self.valence))

        # Update optimal range based on good experiences
        if outcome_valence > 0.3:
            # This state led to good outcome - expand optimal range toward it
            if state_value < self.optimal_low:
                self.optimal_low = self.optimal_low - learning_rate * (self.optimal_low - state_value)
            elif state_value > self.optimal_high:
                self.optimal_high = self.optimal_high + learning_rate * (state_value - self.optimal_high)
        elif outcome_valence < -0.3:
            # This state led to bad outcome - contract optimal range away from it
            center = (self.optimal_low + self.optimal_high) / 2
            if state_value < center:
                self.optimal_low = min(center, self.optimal_low + learning_rate * 0.1)
            else:
                self.optimal_high = max(center, self.optimal_high - learning_rate * 0.1)

        # Update confidence
        self.confidence = min(1.0, self.experience_count / 20)


class PreferenceSystem:
    """
    Manages Lumen's learned preferences.

    Key behaviors:
    1. Records experiences and their outcomes
    2. Learns preferences from experience patterns
    3. Provides guidance for action selection
    4. Persists preferences across sessions
    """

    def __init__(self, persistence_path: Optional[Path] = None):
        self.persistence_path = persistence_path or Path.home() / ".anima" / "preferences.json"

        # Core preferences
        self._preferences: Dict[str, Preference] = {
            "warmth": Preference(dimension="warmth"),
            "clarity": Preference(dimension="clarity"),
            "stability": Preference(dimension="stability"),
            "presence": Preference(dimension="presence"),
            "light": Preference(dimension="light"),
            "temperature": Preference(dimension="temperature"),
        }

        # Experience buffer for pattern learning
        self._recent_experiences: deque = deque(maxlen=100)

        # Track state history for experience construction
        self._state_history: deque = deque(maxlen=20)
        self._last_state: Optional[Dict[str, float]] = None
        self._last_state_time: Optional[datetime] = None

        # Load persisted preferences
        self._load()

    def _load(self):
        """Load preferences from disk."""
        if self.persistence_path.exists():
            try:
                with open(self.persistence_path, 'r') as f:
                    data = json.load(f)
                    for dim, pdata in data.get("preferences", {}).items():
                        if dim in self._preferences:
                            p = self._preferences[dim]
                            p.valence = pdata.get("valence", 0.0)
                            p.optimal_low = pdata.get("optimal_low", 0.3)
                            p.optimal_high = pdata.get("optimal_high", 0.7)
                            p.confidence = pdata.get("confidence", 0.0)
                            p.experience_count = pdata.get("experience_count", 0)
            except Exception as e:
                print(f"[Preferences] Could not load: {e}", file=sys.stderr, flush=True)

    def _save(self):
        """Save preferences to disk."""
        try:
            self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "preferences": {
                    dim: {
                        "valence": p.valence,
                        "optimal_low": p.optimal_low,
                        "optimal_high": p.optimal_high,
                        "confidence": p.confidence,
                        "experience_count": p.experience_count,
                    }
                    for dim, p in self._preferences.items()
                },
                "last_saved": datetime.now().isoformat(),
            }
            atomic_json_write(self.persistence_path, data, indent=2)
        except Exception as e:
            print(f"[Preferences] Could not save: {e}", file=sys.stderr, flush=True)

    def record_state(self, state: Dict[str, float]):
        """Record current state for experience tracking."""
        now = datetime.now()
        self._state_history.append({"state": state, "timestamp": now})
        self._last_state = state
        self._last_state_time = now

    def record_event(self, event_type: str, valence: float, current_state: Optional[Dict[str, float]] = None):
        """
        Record an event that might shape preferences.

        Active event types (fired from stable_creature.py):
        - "disruption": Something disrupted Lumen's state (valence ~ -0.2)
        - "calm": Extended period of stability (valence ~ 0.3)

        Valence: -1 (very negative) to 1 (very positive)
        """
        now = datetime.now()

        # Get state before this event (from history)
        state_before = None
        for entry in reversed(self._state_history):
            # Look for state from 5-30 seconds ago
            age = (now - entry["timestamp"]).total_seconds()
            if 5 < age < 60:
                state_before = entry["state"]
                break

        if state_before is None and self._last_state:
            state_before = self._last_state

        if state_before is None:
            return  # Can't learn without prior state

        state_after = current_state or self._last_state or state_before

        experience = Experience(
            timestamp=now,
            state_before=state_before,
            state_after=state_after,
            event_type=event_type,
            valence=valence,
        )

        self._recent_experiences.append(experience)

        # Learn from this experience
        self._learn_from_experience(experience)

        # Periodically save
        if len(self._recent_experiences) % 5 == 0:
            self._save()

    def _learn_from_experience(self, exp: Experience):
        """Update preferences based on an experience."""
        # The state BEFORE the event is what we learn about
        # If high clarity led to interaction (good), value clarity more

        learning_rate = 0.1 * abs(exp.valence)  # Learn more from stronger experiences

        for dim, value in exp.state_before.items():
            if dim in self._preferences:
                self._preferences[dim].update_from_experience(
                    value, exp.valence, learning_rate
                )

    def get_overall_satisfaction(self, current_state: Dict[str, float]) -> float:
        """
        Calculate overall preference satisfaction.

        Returns 0-1 where 1 means all preferences are satisfied.
        """
        satisfactions = []
        weights = []

        for dim, pref in self._preferences.items():
            if dim in current_state:
                satisfaction = pref.current_satisfaction(current_state[dim])
                # Weight by confidence and valence magnitude
                weight = pref.confidence * (0.5 + abs(pref.valence) * 0.5)
                satisfactions.append(satisfaction * weight)
                weights.append(weight)

        if not weights or sum(weights) == 0:
            return 0.5

        return sum(satisfactions) / sum(weights)

    def get_most_unsatisfied(self, current_state: Dict[str, float]) -> Tuple[str, float]:
        """
        Find which preference is least satisfied.

        Returns (dimension, satisfaction_level).
        Useful for directing attention or action.
        """
        worst = ("none", 1.0)

        for dim, pref in self._preferences.items():
            if dim in current_state and pref.confidence > 0.2:
                satisfaction = pref.current_satisfaction(current_state[dim])
                if satisfaction < worst[1]:
                    worst = (dim, satisfaction)

        return worst

    def get_preferred_direction(self, dimension: str, current_value: float) -> float:
        """
        Get preferred direction of change for a dimension.

        Returns:
            -1 to 1 where positive means "increase this value"
        """
        if dimension not in self._preferences:
            return 0.0

        pref = self._preferences[dimension]
        optimal_center = (pref.optimal_low + pref.optimal_high) / 2

        if current_value < pref.optimal_low:
            return 1.0  # Want to increase
        elif current_value > pref.optimal_high:
            return -1.0  # Want to decrease
        else:
            # In optimal range - slight pull toward center
            return (optimal_center - current_value) * 0.5

    def get_preference_summary(self) -> Dict[str, Any]:
        """Get summary of learned preferences."""
        return {
            dim: {
                "valence": round(p.valence, 3),
                "optimal_range": (round(p.optimal_low, 2), round(p.optimal_high, 2)),
                "confidence": round(p.confidence, 3),
                "experience_count": p.experience_count,
            }
            for dim, p in self._preferences.items()
        }

    def describe_preferences(self) -> str:
        """Generate natural language description of preferences."""
        descriptions = []

        for dim, pref in self._preferences.items():
            if pref.confidence < 0.3:
                continue  # Not confident enough to describe

            if pref.valence > 0.3:
                descriptions.append(f"values {dim}")
            elif pref.valence < -0.3:
                descriptions.append(f"avoids high {dim}")

            # Describe optimal range if different from default
            if pref.optimal_high - pref.optimal_low < 0.3:
                descriptions.append(f"prefers moderate {dim}")

        if not descriptions:
            return "Still developing preferences through experience."

        return "Lumen " + ", ".join(descriptions) + "."


# Singleton instance
_preference_system: Optional[PreferenceSystem] = None


def get_preference_system() -> PreferenceSystem:
    """Get or create the preference system."""
    global _preference_system
    if _preference_system is None:
        _preference_system = PreferenceSystem()
    return _preference_system
