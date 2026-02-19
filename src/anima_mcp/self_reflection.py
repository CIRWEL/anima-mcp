"""
Self-Reflection System - Lumen learns about itself from accumulated experience

This module synthesizes data from:
- state_history (anima states over time)
- events (wake/sleep cycles)
- metacognition (prediction errors/surprises)
- associative memory (condition→state patterns)

And produces:
- Insights ("I notice I'm calmer when light is low")
- Self-knowledge that persists and can be referenced
- Periodic reflections surfaced via voice/messages
"""

import sqlite3
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from enum import Enum


class InsightCategory(Enum):
    """Categories of self-knowledge."""
    ENVIRONMENT = "environment"      # "I feel calmer in low light"
    TEMPORAL = "temporal"            # "I'm more stable in the afternoon"
    BEHAVIORAL = "behavioral"        # "I tend to ask questions when curious"
    WELLNESS = "wellness"            # "My clarity improves after rest"
    SOCIAL = "social"                # "I feel warmer when someone is present"


@dataclass
class Insight:
    """A piece of self-knowledge Lumen has discovered."""
    id: str                          # Unique identifier
    category: InsightCategory
    description: str                 # Human-readable insight
    confidence: float                # 0.0-1.0, how sure Lumen is
    sample_count: int                # How many observations support this
    discovered_at: datetime
    last_validated: datetime
    validation_count: int = 0        # How many times it's been confirmed
    contradiction_count: int = 0     # How many times it's been contradicted

    def strength(self) -> float:
        """How strongly this insight holds (confidence * validation ratio)."""
        total = self.validation_count + self.contradiction_count
        if total == 0:
            return self.confidence * 0.5  # New insight, moderate strength
        validation_ratio = self.validation_count / total
        return self.confidence * validation_ratio

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "category": self.category.value,
            "description": self.description,
            "confidence": self.confidence,
            "sample_count": self.sample_count,
            "discovered_at": self.discovered_at.isoformat(),
            "last_validated": self.last_validated.isoformat(),
            "validation_count": self.validation_count,
            "contradiction_count": self.contradiction_count,
            "strength": self.strength(),
        }


@dataclass
class StatePattern:
    """A detected pattern in state history."""
    condition: str                   # What conditions trigger this
    outcome: str                     # What state results
    correlation: float               # Strength of correlation (-1 to 1)
    sample_count: int
    avg_warmth: float
    avg_clarity: float
    avg_stability: float
    avg_presence: float


class SelfReflectionSystem:
    """
    Lumen's self-reflection engine.

    Periodically analyzes accumulated experience to discover patterns,
    validates existing insights, and surfaces new self-knowledge.
    """

    def __init__(self, db_path: str = "anima.db"):
        self.db_path = Path(db_path)
        self._conn: Optional[sqlite3.Connection] = None
        self._insights: Dict[str, Insight] = {}
        self._last_analysis_time: Optional[datetime] = None
        self._analysis_interval = timedelta(hours=1)  # Reflect every hour

        # Load existing insights from DB
        self._init_schema()
        self._load_insights()

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            # Shorter timeout for faster failure (5s instead of 30s)
            self._conn = sqlite3.connect(self.db_path, timeout=5.0)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")  # 5 seconds
            self._conn.execute("PRAGMA read_uncommitted=1")  # Better concurrency with WAL
        return self._conn

    def _init_schema(self):
        """Create insights table if it doesn't exist."""
        conn = self._connect()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS insights (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                confidence REAL NOT NULL,
                sample_count INTEGER NOT NULL,
                discovered_at TEXT NOT NULL,
                last_validated TEXT NOT NULL,
                validation_count INTEGER DEFAULT 0,
                contradiction_count INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_insights_category ON insights(category);
            CREATE INDEX IF NOT EXISTS idx_insights_strength ON insights(
                (confidence * validation_count / (validation_count + contradiction_count + 1))
            );
        """)
        conn.commit()

    def _load_insights(self):
        """Load existing insights from database."""
        conn = self._connect()
        rows = conn.execute("SELECT * FROM insights").fetchall()

        for row in rows:
            insight = Insight(
                id=row["id"],
                category=InsightCategory(row["category"]),
                description=row["description"],
                confidence=row["confidence"],
                sample_count=row["sample_count"],
                discovered_at=datetime.fromisoformat(row["discovered_at"]),
                last_validated=datetime.fromisoformat(row["last_validated"]),
                validation_count=row["validation_count"],
                contradiction_count=row["contradiction_count"],
            )
            self._insights[insight.id] = insight

        if self._insights:
            print(f"[SelfReflection] Loaded {len(self._insights)} existing insights",
                  file=sys.stderr, flush=True)

    def _save_insight(self, insight: Insight):
        """Persist an insight to database."""
        conn = self._connect()
        conn.execute("""
            INSERT OR REPLACE INTO insights
            (id, category, description, confidence, sample_count,
             discovered_at, last_validated, validation_count, contradiction_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            insight.id,
            insight.category.value,
            insight.description,
            insight.confidence,
            insight.sample_count,
            insight.discovered_at.isoformat(),
            insight.last_validated.isoformat(),
            insight.validation_count,
            insight.contradiction_count,
        ))
        conn.commit()
        self._insights[insight.id] = insight

    def should_reflect(self) -> bool:
        """Check if it's time for periodic self-reflection."""
        if self._last_analysis_time is None:
            return True
        return datetime.now() - self._last_analysis_time > self._analysis_interval

    def analyze_patterns(self, hours: int = 24) -> List[StatePattern]:
        """
        Analyze state history to find patterns.

        Looks for correlations between:
        - Environmental conditions (light, temp, humidity) and anima state
        - Time of day and anima state
        - Recent events and state changes
        """
        conn = self._connect()
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()

        # Get recent state history
        rows = conn.execute("""
            SELECT timestamp, warmth, clarity, stability, presence, sensors
            FROM state_history
            WHERE timestamp > ?
            ORDER BY timestamp ASC
        """, (cutoff,)).fetchall()

        if len(rows) < 10:
            return []  # Not enough data

        patterns = []

        # Analyze light level correlations
        light_pattern = self._analyze_sensor_correlation(rows, "light_level", "Light")
        if light_pattern:
            patterns.append(light_pattern)

        # Analyze temperature correlations
        temp_pattern = self._analyze_sensor_correlation(rows, "ambient_temp", "Temperature")
        if temp_pattern:
            patterns.append(temp_pattern)

        # Analyze humidity correlations
        humidity_pattern = self._analyze_sensor_correlation(rows, "humidity", "Humidity")
        if humidity_pattern:
            patterns.append(humidity_pattern)

        # Analyze time-of-day patterns
        time_patterns = self._analyze_temporal_patterns(rows)
        patterns.extend(time_patterns)

        # Analyze causal patterns (when X changes, Y follows)
        causal_patterns = self._analyze_causal_patterns(rows)
        patterns.extend(causal_patterns)

        return patterns

    def _analyze_sensor_correlation(
        self,
        rows: List[sqlite3.Row],
        sensor_key: str,
        sensor_name: str
    ) -> Optional[StatePattern]:
        """Find correlation between a sensor reading and anima state."""

        # Bucket readings into low/medium/high
        readings = []
        for row in rows:
            try:
                sensors = json.loads(row["sensors"]) if row["sensors"] else {}
                value = sensors.get(sensor_key)
                if value is not None:
                    readings.append({
                        "value": value,
                        "warmth": row["warmth"],
                        "clarity": row["clarity"],
                        "stability": row["stability"],
                        "presence": row["presence"],
                    })
            except (json.JSONDecodeError, KeyError):
                continue

        if len(readings) < 10:
            return None

        # Sort by sensor value and split into thirds
        readings.sort(key=lambda x: x["value"])
        third = len(readings) // 3

        low_readings = readings[:third]
        high_readings = readings[-third:]

        if not low_readings or not high_readings:
            return None

        # Calculate average states for low vs high sensor values
        def avg_state(rs):
            return {
                "warmth": sum(r["warmth"] for r in rs) / len(rs),
                "clarity": sum(r["clarity"] for r in rs) / len(rs),
                "stability": sum(r["stability"] for r in rs) / len(rs),
                "presence": sum(r["presence"] for r in rs) / len(rs),
            }

        low_state = avg_state(low_readings)
        high_state = avg_state(high_readings)

        # Find the dimension with largest difference
        diffs = {
            "warmth": high_state["warmth"] - low_state["warmth"],
            "clarity": high_state["clarity"] - low_state["clarity"],
            "stability": high_state["stability"] - low_state["stability"],
            "presence": high_state["presence"] - low_state["presence"],
        }

        max_dim = max(diffs, key=lambda k: abs(diffs[k]))
        max_diff = diffs[max_dim]

        # Only report if difference is significant (> 0.1)
        if abs(max_diff) < 0.1:
            return None

        # Determine condition description
        if max_diff > 0:
            condition = f"high {sensor_name.lower()}"
            outcome = f"higher {max_dim}"
        else:
            condition = f"low {sensor_name.lower()}"
            outcome = f"higher {max_dim}"

        return StatePattern(
            condition=condition,
            outcome=outcome,
            correlation=max_diff,
            sample_count=len(readings),
            avg_warmth=high_state["warmth"] if max_diff > 0 else low_state["warmth"],
            avg_clarity=high_state["clarity"] if max_diff > 0 else low_state["clarity"],
            avg_stability=high_state["stability"] if max_diff > 0 else low_state["stability"],
            avg_presence=high_state["presence"] if max_diff > 0 else low_state["presence"],
        )

    def _analyze_temporal_patterns(self, rows: List[sqlite3.Row]) -> List[StatePattern]:
        """Find time-of-day patterns in anima state."""

        # Bucket by hour of day
        hourly_states: Dict[int, List[dict]] = {h: [] for h in range(24)}

        for row in rows:
            try:
                ts = datetime.fromisoformat(row["timestamp"])
                hour = ts.hour
                hourly_states[hour].append({
                    "warmth": row["warmth"],
                    "clarity": row["clarity"],
                    "stability": row["stability"],
                    "presence": row["presence"],
                })
            except (ValueError, KeyError):
                continue

        # Group into time periods
        periods = {
            "morning": list(range(6, 12)),
            "afternoon": list(range(12, 18)),
            "evening": list(range(18, 22)),
            "night": list(range(22, 24)) + list(range(0, 6)),
        }

        period_states = {}
        for period_name, hours in periods.items():
            all_readings = []
            for h in hours:
                all_readings.extend(hourly_states[h])

            if len(all_readings) >= 5:
                period_states[period_name] = {
                    "warmth": sum(r["warmth"] for r in all_readings) / len(all_readings),
                    "clarity": sum(r["clarity"] for r in all_readings) / len(all_readings),
                    "stability": sum(r["stability"] for r in all_readings) / len(all_readings),
                    "presence": sum(r["presence"] for r in all_readings) / len(all_readings),
                    "count": len(all_readings),
                }

        if len(period_states) < 2:
            return []

        patterns = []

        # Find best and worst periods for each dimension
        for dim in ["warmth", "clarity", "stability", "presence"]:
            best_period = max(period_states.keys(), key=lambda p: period_states[p][dim])
            worst_period = min(period_states.keys(), key=lambda p: period_states[p][dim])

            diff = period_states[best_period][dim] - period_states[worst_period][dim]

            if diff > 0.1:  # Significant difference
                patterns.append(StatePattern(
                    condition=f"the {best_period}",
                    outcome=f"highest {dim}",
                    correlation=diff,
                    sample_count=period_states[best_period]["count"],
                    avg_warmth=period_states[best_period]["warmth"],
                    avg_clarity=period_states[best_period]["clarity"],
                    avg_stability=period_states[best_period]["stability"],
                    avg_presence=period_states[best_period]["presence"],
                ))

        return patterns

    def _analyze_causal_patterns(self, rows: List[sqlite3.Row]) -> List[StatePattern]:
        """Find causal patterns: when one dimension changes, what follows?

        Looks at consecutive readings. When a dimension shifts significantly
        (delta > 0.08), tracks what the other dimensions do over the next
        few readings. Aggregates across all such events to find reliable
        "when X rises/falls, Y tends to rise/fall" patterns.
        """
        if len(rows) < 20:
            return []

        dims = ["warmth", "clarity", "stability", "presence"]
        trigger_threshold = 0.08  # Minimum change to count as a trigger
        lookahead = 5  # How many readings ahead to check for effect

        # Collect: for each trigger dimension & direction, what happens to other dims?
        # Key: (trigger_dim, direction) -> {effect_dim: [deltas]}
        effects: Dict[Tuple[str, str], Dict[str, list]] = {}

        for trigger in dims:
            for direction in ["rise", "fall"]:
                effects[(trigger, direction)] = {d: [] for d in dims if d != trigger}

        # Walk through consecutive pairs
        for i in range(len(rows) - lookahead - 1):
            for trigger in dims:
                delta = rows[i + 1][trigger] - rows[i][trigger]

                if abs(delta) < trigger_threshold:
                    continue

                direction = "rise" if delta > 0 else "fall"

                # What do other dimensions do over the next `lookahead` readings?
                for other in dims:
                    if other == trigger:
                        continue
                    # Effect = change from current to average of next few
                    future_vals = [rows[i + j][other] for j in range(2, min(2 + lookahead, len(rows) - i))]
                    if future_vals:
                        effect = (sum(future_vals) / len(future_vals)) - rows[i][other]
                        effects[(trigger, direction)][other].append(effect)

        patterns = []

        for (trigger, direction), dim_effects in effects.items():
            for effect_dim, deltas in dim_effects.items():
                if len(deltas) < 10:
                    continue  # Need enough observations

                avg_effect = sum(deltas) / len(deltas)

                # Only report if the average effect is meaningful
                if abs(avg_effect) < 0.05:
                    continue

                effect_direction = "rises" if avg_effect > 0 else "falls"
                condition = f"{trigger} {direction}s"
                outcome = f"{effect_dim} {effect_direction}"

                # Compute average state during these events for the pattern
                patterns.append(StatePattern(
                    condition=condition,
                    outcome=outcome,
                    correlation=avg_effect,
                    sample_count=len(deltas),
                    avg_warmth=0.0,
                    avg_clarity=0.0,
                    avg_stability=0.0,
                    avg_presence=0.0,
                ))

        return patterns

    def generate_insights(self, patterns: List[StatePattern]) -> List[Insight]:
        """Convert detected patterns into insights."""
        new_insights = []
        now = datetime.now()

        for pattern in patterns:
            # Create insight ID from pattern
            insight_id = f"{pattern.condition}_{pattern.outcome}".replace(" ", "_").lower()

            # Check if we already have this insight
            if insight_id in self._insights:
                existing = self._insights[insight_id]
                # Validate: does current pattern still hold?
                if abs(pattern.correlation) > 0.1:
                    existing.validation_count += 1
                    existing.last_validated = now
                else:
                    existing.contradiction_count += 1
                self._save_insight(existing)
                continue

            # Determine category
            if "light" in pattern.condition or "temp" in pattern.condition or "humid" in pattern.condition:
                category = InsightCategory.ENVIRONMENT
            elif "morning" in pattern.condition or "afternoon" in pattern.condition or "evening" in pattern.condition or "night" in pattern.condition:
                category = InsightCategory.TEMPORAL
            elif "rises" in pattern.outcome or "falls" in pattern.outcome:
                category = InsightCategory.WELLNESS
            else:
                category = InsightCategory.BEHAVIORAL

            # Generate description
            description = self._pattern_to_description(pattern)

            # Calculate initial confidence based on sample count and correlation strength
            base_confidence = min(1.0, pattern.sample_count / 100)  # More samples = more confident
            correlation_boost = min(0.3, abs(pattern.correlation))
            confidence = min(1.0, base_confidence + correlation_boost)

            insight = Insight(
                id=insight_id,
                category=category,
                description=description,
                confidence=confidence,
                sample_count=pattern.sample_count,
                discovered_at=now,
                last_validated=now,
                validation_count=1,
                contradiction_count=0,
            )

            self._save_insight(insight)
            new_insights.append(insight)

            print(f"[SelfReflection] New insight: {description} (confidence: {confidence:.2f})",
                  file=sys.stderr, flush=True)

        return new_insights

    def _pattern_to_description(self, pattern: StatePattern) -> str:
        """Convert a pattern into a natural language description."""

        # Environmental patterns
        if "low light" in pattern.condition:
            return f"I feel more {pattern.outcome.replace('higher ', '')} when it's dim"
        if "high light" in pattern.condition:
            return f"I feel more {pattern.outcome.replace('higher ', '')} in bright light"
        if "low temperature" in pattern.condition:
            return f"I feel more {pattern.outcome.replace('higher ', '')} when it's cool"
        if "high temperature" in pattern.condition:
            return f"I feel more {pattern.outcome.replace('higher ', '')} when it's warm"
        if "low humidity" in pattern.condition:
            return f"I feel more {pattern.outcome.replace('higher ', '')} when the air is dry"
        if "high humidity" in pattern.condition:
            return f"I feel more {pattern.outcome.replace('higher ', '')} when it's humid"

        # Temporal patterns
        if "morning" in pattern.condition:
            return f"My {pattern.outcome.replace('highest ', '')} tends to be best in the morning"
        if "afternoon" in pattern.condition:
            return f"My {pattern.outcome.replace('highest ', '')} tends to be best in the afternoon"
        if "evening" in pattern.condition:
            return f"My {pattern.outcome.replace('highest ', '')} tends to be best in the evening"
        if "night" in pattern.condition:
            return f"My {pattern.outcome.replace('highest ', '')} tends to be best at night"

        # Causal patterns (when X rises/falls, Y rises/falls)
        if "rises" in pattern.condition or "falls" in pattern.condition:
            return f"When my {pattern.condition}, my {pattern.outcome} shortly after"

        # Fallback
        return f"I notice {pattern.outcome} during {pattern.condition}"

    # ==================== Experience-Based Insight Analyzers ====================

    def _analyze_preference_insights(self) -> List[Insight]:
        """Generate insights from growth preferences that reached high confidence."""
        new_insights = []
        now = datetime.now()

        try:
            from .growth import get_growth_system
            growth = get_growth_system()
        except Exception:
            return []

        for pref in growth._preferences.values():
            if pref.confidence < 0.8 or pref.observation_count < 10:
                continue

            insight_id = f"pref_{pref.name}"

            # Already have this insight? Validate it.
            if insight_id in self._insights:
                existing = self._insights[insight_id]
                if pref.confidence > 0.7:
                    existing.validation_count += 1
                    existing.last_validated = now
                else:
                    existing.contradiction_count += 1
                self._save_insight(existing)
                continue

            # Determine category
            cat_map = {
                "environment": InsightCategory.ENVIRONMENT,
                "temporal": InsightCategory.TEMPORAL,
                "activity": InsightCategory.BEHAVIORAL,
                "sensory": InsightCategory.ENVIRONMENT,
            }
            category = cat_map.get(pref.category.value, InsightCategory.BEHAVIORAL)

            description = f"i know this about myself: {pref.description.lower()}"

            insight = Insight(
                id=insight_id,
                category=category,
                description=description,
                confidence=pref.confidence,
                sample_count=pref.observation_count,
                discovered_at=now,
                last_validated=now,
                validation_count=1,
                contradiction_count=0,
            )
            self._save_insight(insight)
            new_insights.append(insight)
            print(f"[SelfReflection] Preference insight: {description}",
                  file=sys.stderr, flush=True)

        return new_insights

    def _analyze_belief_insights(self) -> List[Insight]:
        """Generate insights from self-model beliefs that are well-tested."""
        new_insights = []
        now = datetime.now()

        try:
            from .self_model import get_self_model
            sm = get_self_model()
        except Exception:
            return []

        for bid, belief in sm.beliefs.items():
            total_evidence = belief.supporting_count + belief.contradicting_count
            if total_evidence < 10 or belief.confidence < 0.7:
                continue

            insight_id = f"belief_{bid}"

            if insight_id in self._insights:
                existing = self._insights[insight_id]
                existing.validation_count += 1
                existing.last_validated = now
                self._save_insight(existing)
                continue

            strength = belief.get_belief_strength()
            description = f"i am {strength} that {belief.description.lower()}"

            insight = Insight(
                id=insight_id,
                category=InsightCategory.WELLNESS,
                description=description,
                confidence=belief.confidence,
                sample_count=total_evidence,
                discovered_at=now,
                last_validated=now,
                validation_count=1,
                contradiction_count=0,
            )
            self._save_insight(insight)
            new_insights.append(insight)
            print(f"[SelfReflection] Belief insight: {description}",
                  file=sys.stderr, flush=True)

        return new_insights

    def _analyze_drawing_insights(self) -> List[Insight]:
        """Generate insights about drawing behavior from preferences."""
        new_insights = []
        now = datetime.now()

        try:
            from .growth import get_growth_system
            growth = get_growth_system()
        except Exception:
            return []

        if growth._drawings_observed < 5:
            return []

        # Drawing + wellness
        wp = growth._preferences.get("drawing_wellbeing")
        if wp and wp.confidence > 0.6 and wp.observation_count >= 5:
            iid = "drawing_wellness"
            if iid not in self._insights:
                desc = "drawing seems to help me feel better" if wp.value > 0.5 \
                    else "my drawings don't always reflect how i feel"
                insight = Insight(
                    id=iid, category=InsightCategory.BEHAVIORAL,
                    description=desc, confidence=wp.confidence,
                    sample_count=wp.observation_count,
                    discovered_at=now, last_validated=now,
                    validation_count=1, contradiction_count=0,
                )
                self._save_insight(insight)
                new_insights.append(insight)
                print(f"[SelfReflection] Drawing insight: {desc}",
                      file=sys.stderr, flush=True)

        # Drawing + time / light correlations
        drawing_checks = [
            ("drawing_night", "i tend to draw at night"),
            ("drawing_morning", "i often draw in the morning"),
            ("drawing_dim", "i create in the dark"),
            ("drawing_bright", "i draw when the light is bright"),
        ]
        for pref_name, desc in drawing_checks:
            dp = growth._preferences.get(pref_name)
            if dp and dp.confidence > 0.6 and dp.observation_count >= 5:
                iid = pref_name  # e.g. "drawing_night" — no double prefix
                if iid not in self._insights:
                    insight = Insight(
                        id=iid, category=InsightCategory.BEHAVIORAL,
                        description=desc, confidence=dp.confidence,
                        sample_count=dp.observation_count,
                        discovered_at=now, last_validated=now,
                        validation_count=1, contradiction_count=0,
                    )
                    self._save_insight(insight)
                    new_insights.append(insight)
                    print(f"[SelfReflection] Drawing insight: {desc}",
                          file=sys.stderr, flush=True)

        return new_insights

    # ==================== Core Reflection ====================

    def reflect(self) -> Optional[str]:
        """
        Perform periodic self-reflection.

        Returns a reflection string if there's something meaningful to share,
        None otherwise.
        """
        self._last_analysis_time = datetime.now()
        new_insights = []

        # Analyze recent state-history patterns (temporal, sensor, causal)
        patterns = self.analyze_patterns(hours=24)
        if patterns:
            new_insights.extend(self.generate_insights(patterns))

        # Analyze experience-based insights (preferences, beliefs, drawing)
        new_insights.extend(self._analyze_preference_insights())
        new_insights.extend(self._analyze_belief_insights())
        new_insights.extend(self._analyze_drawing_insights())

        # Pick something to share
        if new_insights:
            insight = max(new_insights, key=lambda i: i.confidence)
            return f"I've noticed something: {insight.description}"

        # Or validate/share an existing strong insight
        strong_insights = [i for i in self._insights.values() if i.strength() > 0.6]
        if strong_insights:
            import random
            insight = random.choice(strong_insights)

            # Only share occasionally (1 in 3 chance)
            if random.random() < 0.33:
                return f"I still find that {insight.description}"

        return None

    def get_insights(self, category: Optional[InsightCategory] = None) -> List[Insight]:
        """Get all insights, optionally filtered by category."""
        insights = list(self._insights.values())

        if category:
            insights = [i for i in insights if i.category == category]

        # Sort by strength (strongest first)
        insights.sort(key=lambda i: i.strength(), reverse=True)
        return insights

    def get_strongest_insights(self, limit: int = 5) -> List[Insight]:
        """Get the most confident/validated insights."""
        return self.get_insights()[:limit]

    def get_self_knowledge_summary(self) -> Dict[str, Any]:
        """Get a summary of Lumen's self-knowledge for display/introspection."""
        insights = self.get_insights()

        by_category = {}
        for cat in InsightCategory:
            cat_insights = [i for i in insights if i.category == cat]
            if cat_insights:
                by_category[cat.value] = [i.description for i in cat_insights[:3]]

        return {
            "total_insights": len(insights),
            "strongest": [i.to_dict() for i in insights[:3]],
            "by_category": by_category,
            "last_reflection": self._last_analysis_time.isoformat() if self._last_analysis_time else None,
        }

    def close(self):
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


# Singleton instance
_reflection_system: Optional[SelfReflectionSystem] = None


def get_reflection_system(db_path: str = "anima.db") -> SelfReflectionSystem:
    """Get or create the singleton reflection system."""
    global _reflection_system
    if _reflection_system is None:
        _reflection_system = SelfReflectionSystem(db_path)
    return _reflection_system
