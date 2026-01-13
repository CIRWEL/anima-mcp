"""
Expression Moods - Persistent drawing styles for Lumen.

Tracks Lumen's drawing preferences over time and creates a signature style
that persists across sessions. Makes Lumen's expression more consistent
and recognizable.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime
import json


@dataclass
class ExpressionMood:
    """
    Lumen's expression mood - persistent drawing style preferences.
    
    Evolves over time based on what Lumen actually draws.
    """
    # Style preferences (0.0 to 1.0, higher = more likely)
    style_preferences: Dict[str, float] = field(default_factory=lambda: {
        "circle": 0.2,
        "line": 0.2,
        "curve": 0.2,
        "spiral": 0.2,
        "pattern": 0.2,
        "organic": 0.2,
        "gradient_circle": 0.2,
        "layered": 0.2,
    })
    
    # Color preferences (hue ranges Lumen prefers)
    preferred_hues: List[str] = field(default_factory=lambda: ["warm", "cool", "neutral"])  # All initially
    
    # Drawing characteristics
    preferred_size_range: tuple = (8, 20)  # Preferred size range
    continuity_preference: float = 0.4  # How much Lumen builds on previous work (0.0-1.0)
    density_preference: float = 0.5  # How dense/complex drawings are (0.0-1.0)
    
    # Mood name (evolves based on dominant style)
    mood_name: str = "exploring"
    
    # Statistics
    total_drawings: int = 0
    last_updated: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExpressionMood":
        """Create from dictionary."""
        # Handle defaults for missing fields
        defaults = {
            "style_preferences": {
                "circle": 0.2, "line": 0.2, "curve": 0.2, "spiral": 0.2,
                "pattern": 0.2, "organic": 0.2, "gradient_circle": 0.2, "layered": 0.2,
            },
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
        
        return cls(**data)
    
    def record_drawing(self, style: str, hue_category: Optional[str] = None):
        """
        Record a drawing to update preferences.
        
        Args:
            style: Drawing style used (e.g., "circle", "spiral")
            hue_category: Color category ("warm", "cool", "neutral")
        """
        self.total_drawings += 1
        
        # Update style preference (gradual learning)
        learning_rate = 0.05  # Slow adaptation
        if style in self.style_preferences:
            # Increase preference for this style
            self.style_preferences[style] = min(1.0, 
                self.style_preferences[style] + learning_rate)
            
            # Decrease others slightly (normalize)
            total = sum(self.style_preferences.values())
            if total > 1.0:
                # Normalize
                for key in self.style_preferences:
                    self.style_preferences[key] /= total
        
        # Update hue preferences
        if hue_category and hue_category in self.preferred_hues:
            # Already preferred, keep it
            pass
        elif hue_category:
            # Add new preference
            self.preferred_hues.append(hue_category)
            # Keep only top 3 preferences
            if len(self.preferred_hues) > 3:
                self.preferred_hues.pop(0)
        
        # Update mood name based on dominant style
        dominant_style = max(self.style_preferences.items(), key=lambda x: x[1])
        if dominant_style[1] > 0.35:
            style_names = {
                "circle": "contemplative",
                "spiral": "flowing",
                "curve": "elegant",
                "pattern": "structured",
                "organic": "organic",
                "layered": "complex",
                "gradient_circle": "radiant",
                "line": "minimal",
            }
            self.mood_name = style_names.get(dominant_style[0], "exploring")
        
        self.last_updated = datetime.now().isoformat()
    
    def get_style_weight(self, style: str) -> float:
        """
        Get weight for a drawing style (higher = more likely to use).
        
        Args:
            style: Style name
        
        Returns:
            Weight (0.0 to 1.0)
        """
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
        """
        Initialize mood tracker.
        
        Args:
            identity_store: IdentityStore instance (for persistence)
        """
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
        
        # Default mood
        self._mood = ExpressionMood()
    
    def _save_mood(self):
        """Save expression mood to identity metadata."""
        if not self._store or not self._mood:
            return
        
        try:
            identity = self._store.get_identity()
            if identity:
                identity.metadata["expression_mood"] = self._mood.to_dict()
                # Update metadata in database
                conn = self._store._connect()
                conn.execute(
                    "UPDATE identity SET metadata = ? WHERE creature_id = ?",
                    (json.dumps(identity.metadata), identity.creature_id)
                )
                conn.commit()
        except Exception:
            pass  # Non-fatal
    
    def get_mood(self) -> ExpressionMood:
        """Get current expression mood."""
        if self._mood is None:
            self._mood = ExpressionMood()
        return self._mood
    
    def record_drawing(self, style: str, hue_category: Optional[str] = None):
        """
        Record a drawing to update mood preferences.
        
        Args:
            style: Drawing style used
            hue_category: Color category
        """
        mood = self.get_mood()
        mood.record_drawing(style, hue_category)
        
        # Save periodically (every 10 drawings)
        if mood.total_drawings % 10 == 0:
            self._save_mood()
    
    def get_style_weights(self) -> Dict[str, float]:
        """
        Get weights for all drawing styles.
        
        Returns:
            Dict mapping style names to weights
        """
        mood = self.get_mood()
        return mood.style_preferences.copy()
    
    def get_mood_info(self) -> Dict[str, Any]:
        """
        Get current mood information.
        
        Returns:
            Dict with mood details
        """
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
