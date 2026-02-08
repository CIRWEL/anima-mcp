"""
Expression Moods - Persistent drawing gesture preferences for Lumen.

Tracks Lumen's mark-making preferences over time. Five gesture primitives
(dot, stroke, curve, cluster, drag) replace the old 18 shape templates.
Preferences evolve based on what Lumen actually draws.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime
import json

# Old style keys that DON'T exist in the new system (for migration detection)
# "curve" exists in both old and new, so it's NOT a migration signal
_OLD_ONLY_KEYS = frozenset([
    "circle", "line", "spiral", "pattern",
    "organic", "gradient_circle", "layered",
])

# New gesture keys
_GESTURE_DEFAULTS = {
    "dot": 0.2,
    "stroke": 0.2,
    "curve": 0.2,
    "cluster": 0.2,
    "drag": 0.2,
}

# Gesture → mood name mapping
_GESTURE_MOOD_NAMES = {
    "dot": "pointillist",
    "stroke": "gestural",
    "curve": "flowing",
    "cluster": "textural",
    "drag": "bold",
}


@dataclass
class ExpressionMood:
    """
    Lumen's expression mood - persistent mark-making gesture preferences.

    Evolves over time based on what Lumen actually draws.
    """
    # Gesture preferences (0.0 to 1.0, higher = more likely)
    style_preferences: Dict[str, float] = field(default_factory=lambda: dict(_GESTURE_DEFAULTS))

    # Color preferences (hue ranges Lumen prefers)
    preferred_hues: List[str] = field(default_factory=lambda: ["warm", "cool", "neutral"])

    # Drawing characteristics
    preferred_size_range: tuple = (8, 20)
    continuity_preference: float = 0.4
    density_preference: float = 0.5

    # Mood name (evolves based on dominant gesture)
    mood_name: str = "exploring"

    # Statistics
    total_drawings: int = 0
    last_updated: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExpressionMood":
        """Create from dictionary. Migrates old shape keys to new gesture keys."""
        defaults = {
            "style_preferences": dict(_GESTURE_DEFAULTS),
            "preferred_hues": ["warm", "cool", "neutral"],
            "preferred_size_range": (8, 20),
            "continuity_preference": 0.4,
            "density_preference": 0.5,
            "mood_name": "exploring",
            "total_drawings": 0,
            "last_updated": None,
        }

        for key, default_value in defaults.items():
            if key not in data:
                data[key] = default_value

        # Migration: if old-only shape keys found, reset to gesture defaults
        prefs = data.get("style_preferences", {})
        if any(k in _OLD_ONLY_KEYS for k in prefs):
            data["style_preferences"] = dict(_GESTURE_DEFAULTS)
            data["mood_name"] = "exploring"

        return cls(**data)

    def record_drawing(self, style: str, hue_category: Optional[str] = None):
        """
        Record a mark to update preferences.

        Args:
            style: Gesture type used (e.g., "dot", "stroke", "curve")
            hue_category: Color category ("warm", "cool", "neutral", "vibrant")
        """
        self.total_drawings += 1

        # Update gesture preference (gradual learning)
        learning_rate = 0.05
        if style in self.style_preferences:
            self.style_preferences[style] = min(1.0,
                self.style_preferences[style] + learning_rate)

            # Normalize
            total = sum(self.style_preferences.values())
            if total > 1.0:
                for key in self.style_preferences:
                    self.style_preferences[key] /= total

        # Update hue preferences
        if hue_category and hue_category in self.preferred_hues:
            pass
        elif hue_category:
            self.preferred_hues.append(hue_category)
            if len(self.preferred_hues) > 3:
                self.preferred_hues.pop(0)

        # Update mood name based on dominant gesture
        dominant = max(self.style_preferences.items(), key=lambda x: x[1])
        if dominant[1] > 0.35:
            self.mood_name = _GESTURE_MOOD_NAMES.get(dominant[0], "exploring")

        self.last_updated = datetime.now().isoformat()

    def get_style_weight(self, style: str) -> float:
        """Get weight for a gesture type."""
        return self.style_preferences.get(style, 0.2)

    def prefers_hue(self, hue_category: str) -> bool:
        """Check if Lumen prefers this hue category."""
        return hue_category in self.preferred_hues


class ExpressionMoodTracker:
    """
    Tracks and manages Lumen's expression moods.

    Loads from identity metadata and updates preferences based on actual drawings.
    """

    def __init__(self, identity_store=None):
        self._store = identity_store
        self._mood: Optional[ExpressionMood] = None
        self._load_mood()

    def _load_mood(self):
        """Load expression mood from identity metadata."""
        if self._store:
            try:
                identity = self._store.get_identity()
                if identity and "expression_mood" in identity.metadata:
                    mood_data = identity.metadata["expression_mood"]
                    self._mood = ExpressionMood.from_dict(mood_data)
                    return
            except Exception:
                pass
        self._mood = ExpressionMood()

    def _save_mood(self):
        """Save expression mood to identity metadata."""
        if not self._store or not self._mood:
            return
        try:
            identity = self._store.get_identity()
            if identity:
                identity.metadata["expression_mood"] = self._mood.to_dict()
                conn = self._store._connect()
                conn.execute(
                    "UPDATE identity SET metadata = ? WHERE creature_id = ?",
                    (json.dumps(identity.metadata), identity.creature_id)
                )
                conn.commit()
        except Exception:
            pass

    def get_mood(self) -> ExpressionMood:
        """Get current expression mood."""
        if self._mood is None:
            self._mood = ExpressionMood()
        return self._mood

    def record_drawing(self, style: str, hue_category: Optional[str] = None):
        """Record a mark to update mood preferences."""
        mood = self.get_mood()
        mood.record_drawing(style, hue_category)
        if mood.total_drawings % 10 == 0:
            self._save_mood()

    def get_style_weights(self) -> Dict[str, float]:
        """Get weights for all gesture types."""
        mood = self.get_mood()
        return mood.style_preferences.copy()

    def get_mood_info(self) -> Dict[str, Any]:
        """Get current mood information."""
        mood = self.get_mood()
        return {
            "mood_name": mood.mood_name,
            "total_drawings": mood.total_drawings,
            "style_preferences": mood.style_preferences,
            "preferred_hues": mood.preferred_hues,
            "continuity_preference": mood.continuity_preference,
            "density_preference": mood.density_preference,
            "last_updated": mood.last_updated,
        }
