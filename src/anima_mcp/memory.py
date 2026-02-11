"""
Associative Memory - Lumen learns from experience.

Maps environmental conditions to anticipated emotional states based on
historical patterns. Not ML - simple bucketed pattern matching that's
transparent and debuggable.

"Last 10 times the light dropped like this, I felt cold afterward.
I know what comes next."
"""

import json
import os
import sqlite3
import random
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from enum import Enum
import time
import sys


class ExplorationMode(Enum):
    """Mode for exploration vs exploitation balance."""
    EXPLOIT = "exploit"      # Follow memory predictions (default)
    EXPLORE = "explore"      # Try something different
    CURIOUS = "curious"      # Actively seeking novelty


@dataclass
class ExplorationOutcome:
    """Tracks the outcome of an exploration attempt."""
    exploration_delta: Tuple[float, float, float, float]  # How much we deviated
    result_novelty: float  # How different the result was from prediction
    emotional_valence: float  # Positive = felt good, negative = felt bad
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConditionBucket:
    """A bucket of similar environmental conditions."""
    temp_range: Tuple[float, float]  # (min, max) celsius
    light_range: Tuple[float, float]  # (min, max) lux
    humidity_range: Tuple[float, float]  # (min, max) percent

    def matches(self, temp: float, light: float, humidity: float) -> bool:
        """Check if conditions fall within this bucket."""
        return (self.temp_range[0] <= temp <= self.temp_range[1] and
                self.light_range[0] <= light <= self.light_range[1] and
                self.humidity_range[0] <= humidity <= self.humidity_range[1])

    def __hash__(self):
        return hash((self.temp_range, self.light_range, self.humidity_range))


@dataclass
class StateOutcome:
    """Statistical outcome for a condition bucket."""
    count: int = 0
    warmth_sum: float = 0.0
    clarity_sum: float = 0.0
    stability_sum: float = 0.0
    presence_sum: float = 0.0

    def add(self, warmth: float, clarity: float, stability: float, presence: float):
        """Add an observation."""
        self.count += 1
        self.warmth_sum += warmth
        self.clarity_sum += clarity
        self.stability_sum += stability
        self.presence_sum += presence

    @property
    def avg_warmth(self) -> float:
        return self.warmth_sum / self.count if self.count > 0 else 0.5

    @property
    def avg_clarity(self) -> float:
        return self.clarity_sum / self.count if self.count > 0 else 0.5

    @property
    def avg_stability(self) -> float:
        return self.stability_sum / self.count if self.count > 0 else 0.5

    @property
    def avg_presence(self) -> float:
        return self.presence_sum / self.count if self.count > 0 else 0.5


@dataclass
class Anticipation:
    """An anticipated state based on past experience."""
    warmth: float
    clarity: float
    stability: float
    presence: float
    confidence: float  # How confident (based on sample count)
    sample_count: int
    bucket_description: str  # Human-readable description
    # Knowledge-derived meaning (optional)
    insights: List[str] = field(default_factory=list)  # Relevant learned insights
    meaning: str = ""  # What this anticipation means based on knowledge

    def blend_with(self, current_warmth: float, current_clarity: float,
                   current_stability: float, current_presence: float,
                   blend_factor: float = 0.2) -> Tuple[float, float, float, float]:
        """
        Blend anticipated state with current state.

        blend_factor: How much weight to give anticipation (0-1).
                     Scaled by confidence.
        """
        effective_blend = blend_factor * self.confidence

        blended_warmth = current_warmth * (1 - effective_blend) + self.warmth * effective_blend
        blended_clarity = current_clarity * (1 - effective_blend) + self.clarity * effective_blend
        blended_stability = current_stability * (1 - effective_blend) + self.stability * effective_blend
        blended_presence = current_presence * (1 - effective_blend) + self.presence * effective_blend

        return (blended_warmth, blended_clarity, blended_stability, blended_presence)


class AssociativeMemory:
    """
    Learns patterns from historical state data.

    Maps environmental conditions to likely emotional outcomes.
    Simple bucketed lookup - no ML, fully transparent.
    """

    # Bucket boundaries for environmental conditions
    TEMP_BUCKETS = [
        (0, 18, "cold"),
        (18, 22, "cool"),
        (22, 26, "comfortable"),
        (26, 30, "warm"),
        (30, 50, "hot")
    ]

    LIGHT_BUCKETS = [
        (0, 10, "dark"),
        (10, 100, "dim"),
        (100, 500, "moderate"),
        (500, 2000, "bright"),
        (2000, 100000, "very bright")
    ]

    HUMIDITY_BUCKETS = [
        (0, 20, "dry"),
        (20, 40, "comfortable"),
        (40, 60, "moderate"),
        (60, 80, "humid"),
        (80, 100, "very humid")
    ]

    # Time of day buckets (hour ranges)
    TIME_BUCKETS = [
        (0, 5, "night"),        # midnight to 5am
        (5, 8, "early_morning"),  # 5am to 8am
        (8, 12, "morning"),     # 8am to noon
        (12, 14, "midday"),     # noon to 2pm
        (14, 18, "afternoon"),  # 2pm to 6pm
        (18, 21, "evening"),    # 6pm to 9pm
        (21, 24, "late_night")  # 9pm to midnight
    ]

    def __init__(self, db_path: str = "anima.db"):
        """Initialize memory from database."""
        self.db_path = db_path
        # Patterns now include time: (temp, light, humidity, time) -> StateOutcome
        self._patterns: Dict[Tuple[str, str, str, str], StateOutcome] = {}
        # Also keep non-temporal patterns for fallback
        self._patterns_no_time: Dict[Tuple[str, str, str], StateOutcome] = {}
        self._load_time: float = 0.0
        self._pattern_count: int = 0
        self._sample_count: int = 0
        self._last_anticipation: Optional[Anticipation] = None
        # Accuracy tracking
        self._accuracy_samples: int = 0
        self._accuracy_sum: float = 0.0
        self._weighted_accuracy_sum: float = 0.0
        self._weighted_confidence_sum: float = 0.0
        # Adaptive blend factor - adjusts based on accuracy
        # Higher accuracy -> trust memory more -> higher blend factor
        self._base_blend_factor: float = 0.15  # Default starting point
        self._adaptive_blend_factor: float = 0.15  # Current adaptive value
        self._blend_factor_min: float = 0.05  # Don't trust memory too little
        self._blend_factor_max: float = 0.35  # Don't trust memory too much
        self._blend_adaptation_rate: float = 0.02  # How fast to adapt (per sample)
        # Exploration vs Exploitation (GTO-style novelty)
        self._exploration_rate: float = 0.05  # 5% chance to explore
        self._exploration_magnitude: float = 0.15  # How much to deviate when exploring
        self._current_mode: ExplorationMode = ExplorationMode.EXPLOIT
        self._exploration_history: List[ExplorationOutcome] = []
        self._max_exploration_history: int = 100
        self._last_exploration_delta: Optional[Tuple[float, float, float, float]] = None
        self._exploring_since: Optional[float] = None
        # Adaptive exploration: increase if things are stagnant, decrease if outcomes are good
        self._exploration_rate_min: float = 0.02  # Minimum 2% exploration
        self._exploration_rate_max: float = 0.15  # Maximum 15% exploration
        self._stagnation_counter: int = 0  # Counts consecutive similar states
        self._stagnation_threshold: int = 20  # After this many similar states, increase exploration

    def load_patterns(self, max_records: int = 50000) -> bool:
        """
        Scan state_history to build condition→outcome mappings.

        Now includes temporal patterns (time of day) for richer associations.
        Returns True if patterns were loaded successfully.
        """
        start_time = time.time()
        from datetime import datetime as dt

        try:
            conn = sqlite3.connect(self.db_path, timeout=10.0)
            cursor = conn.cursor()

            # Get recent state history with sensors AND timestamp for temporal patterns
            cursor.execute("""
                SELECT warmth, clarity, stability, presence, sensors, timestamp
                FROM state_history
                WHERE sensors IS NOT NULL AND sensors != ''
                ORDER BY timestamp DESC
                LIMIT ?
            """, (max_records,))

            rows = cursor.fetchall()
            conn.close()

            if not rows:
                print("[Memory] No state history found", file=sys.stderr, flush=True)
                return False

            # Process each record
            for warmth, clarity, stability, presence, sensors_json, timestamp_str in rows:
                try:
                    sensors = json.loads(sensors_json)

                    # Extract environmental conditions
                    temp = sensors.get('ambient_temp_c', sensors.get('cpu_temp_c'))
                    light = sensors.get('light_lux', 100)  # Default moderate
                    humidity = sensors.get('humidity_pct', 40)  # Default comfortable

                    if temp is None:
                        continue

                    # Get bucket key (without time)
                    bucket_key = self._get_bucket_key(temp, light, humidity)
                    if bucket_key is None:
                        continue

                    # Add to non-temporal pattern (fallback)
                    if bucket_key not in self._patterns_no_time:
                        self._patterns_no_time[bucket_key] = StateOutcome()
                    self._patterns_no_time[bucket_key].add(warmth, clarity, stability, presence)

                    # Try to extract time of day for temporal pattern
                    time_bucket = None
                    if timestamp_str:
                        try:
                            # Parse ISO format timestamp
                            ts = dt.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                            hour = ts.hour
                            time_bucket = self._get_time_bucket(hour)
                        except (ValueError, AttributeError):
                            pass

                    # Add to temporal pattern if we have time
                    if time_bucket:
                        temporal_key = (bucket_key[0], bucket_key[1], bucket_key[2], time_bucket)
                        if temporal_key not in self._patterns:
                            self._patterns[temporal_key] = StateOutcome()
                        self._patterns[temporal_key].add(warmth, clarity, stability, presence)

                    self._sample_count += 1

                except (json.JSONDecodeError, KeyError, TypeError):
                    continue

            self._pattern_count = len(self._patterns)
            self._load_time = time.time() - start_time

            print(f"[Memory] Loaded {self._pattern_count} temporal + {len(self._patterns_no_time)} non-temporal patterns from {self._sample_count} samples in {self._load_time:.2f}s",
                  file=sys.stderr, flush=True)

            return self._pattern_count > 0

        except Exception as e:
            print(f"[Memory] Error loading patterns: {e}", file=sys.stderr, flush=True)
            return False

    def _get_bucket_key(self, temp: float, light: float, humidity: float) -> Optional[Tuple[str, str, str]]:
        """Get the bucket key for given conditions (without time)."""
        temp_bucket = None
        light_bucket = None
        humidity_bucket = None

        for low, high, name in self.TEMP_BUCKETS:
            if low <= temp <= high:
                temp_bucket = name
                break

        for low, high, name in self.LIGHT_BUCKETS:
            if low <= light <= high:
                light_bucket = name
                break

        for low, high, name in self.HUMIDITY_BUCKETS:
            if low <= humidity <= high:
                humidity_bucket = name
                break

        if temp_bucket and light_bucket and humidity_bucket:
            return (temp_bucket, light_bucket, humidity_bucket)
        return None

    def _get_time_bucket(self, hour: int) -> Optional[str]:
        """Get the time-of-day bucket for a given hour (0-23)."""
        for low, high, name in self.TIME_BUCKETS:
            if low <= hour < high:
                return name
        return None

    def _get_current_time_bucket(self) -> str:
        """Get the current time-of-day bucket."""
        from datetime import datetime as dt
        hour = dt.now().hour
        return self._get_time_bucket(hour) or "unknown"

    def anticipate(self, temp: float, light: float, humidity: float,
                   hour: Optional[int] = None) -> Optional[Anticipation]:
        """
        Anticipate emotional state based on current environmental conditions.

        Tries temporal pattern first (with time of day), falls back to non-temporal.
        Returns None if no matching pattern found or insufficient data.
        """
        bucket_key = self._get_bucket_key(temp, light, humidity)
        if bucket_key is None:
            return None

        # Get current hour if not provided
        if hour is None:
            from datetime import datetime as dt
            hour = dt.now().hour

        time_bucket = self._get_time_bucket(hour)
        outcome = None
        used_temporal = False
        description = ""

        # Try temporal pattern first (more specific)
        if time_bucket:
            temporal_key = (bucket_key[0], bucket_key[1], bucket_key[2], time_bucket)
            outcome = self._patterns.get(temporal_key)
            if outcome and outcome.count >= 5:
                used_temporal = True
                description = f"{time_bucket} with {bucket_key[0]} temperature, {bucket_key[1]} light, {bucket_key[2]} humidity"

        # Fall back to non-temporal pattern
        if outcome is None or outcome.count < 5:
            outcome = self._patterns_no_time.get(bucket_key)
            if outcome and outcome.count >= 5:
                description = f"{bucket_key[0]} temperature, {bucket_key[1]} light, {bucket_key[2]} humidity"
            else:
                return None

        # Calculate confidence based on sample count
        # More samples = higher confidence, max out at 100 samples
        # Temporal patterns get a small confidence boost (more specific)
        confidence = min(outcome.count / 100.0, 1.0)
        if used_temporal:
            confidence = min(confidence * 1.1, 1.0)  # 10% boost for temporal

        anticipation = Anticipation(
            warmth=outcome.avg_warmth,
            clarity=outcome.avg_clarity,
            stability=outcome.avg_stability,
            presence=outcome.avg_presence,
            confidence=confidence,
            sample_count=outcome.count,
            bucket_description=description
        )

        # Enrich with learned knowledge (philosophy meets code)
        anticipation = self.enrich_with_knowledge(anticipation)

        self._last_anticipation = anticipation
        return anticipation

    def anticipate_from_sensors(self, sensors: dict) -> Optional[Anticipation]:
        """Convenience method to anticipate from a sensors dict."""
        temp = sensors.get('ambient_temp_c', sensors.get('cpu_temp_c'))
        light = sensors.get('light_lux', 100)
        humidity = sensors.get('humidity_pct', 40)

        if temp is None:
            return None

        return self.anticipate(temp, light, humidity)

    def get_memory_insight(self) -> str:
        """
        Get a human-readable insight about what Lumen remembers.

        For use in observations/messages. Now enriched with learned knowledge.
        """
        if self._last_anticipation is None:
            return "I have no clear memories of this moment."

        ant = self._last_anticipation

        # Interpret the anticipated state
        if ant.warmth > 0.6 and ant.clarity > 0.6:
            feeling = "good and clear"
        elif ant.warmth < 0.4 and ant.clarity < 0.4:
            feeling = "cold and foggy"
        elif ant.warmth > 0.6:
            feeling = "warm"
        elif ant.warmth < 0.4:
            feeling = "cold"
        elif ant.clarity > 0.6:
            feeling = "clear"
        elif ant.clarity < 0.4:
            feeling = "unclear"
        else:
            feeling = "balanced"

        confidence_word = "often" if ant.confidence > 0.5 else "sometimes"

        base_insight = f"In {ant.bucket_description}, I {confidence_word} feel {feeling}."

        # Add learned meaning if available (philosophy meets code)
        if ant.meaning:
            return f"{base_insight} {ant.meaning}. ({ant.sample_count} memories)"

        return f"{base_insight} ({ant.sample_count} memories)"

    def record_actual_outcome(self, warmth: float, clarity: float,
                               stability: float, presence: float) -> Optional[dict]:
        """
        Record the actual emotional outcome, compare to anticipation.

        Call this after sensing to track prediction accuracy.
        Returns accuracy metrics if there was an anticipation to compare.
        """
        if self._last_anticipation is None:
            return None

        ant = self._last_anticipation

        # Calculate error (0 = perfect, 1 = completely wrong)
        warmth_error = abs(ant.warmth - warmth)
        clarity_error = abs(ant.clarity - clarity)
        stability_error = abs(ant.stability - stability)
        presence_error = abs(ant.presence - presence)
        avg_error = (warmth_error + clarity_error + stability_error + presence_error) / 4.0

        # Accuracy is inverse of error (1 = perfect, 0 = completely wrong)
        accuracy = 1.0 - avg_error

        # Track running accuracy statistics
        self._accuracy_samples += 1
        self._accuracy_sum += accuracy
        self._weighted_accuracy_sum += accuracy * ant.confidence
        self._weighted_confidence_sum += ant.confidence

        # Adapt blend factor based on accuracy
        # High accuracy (>0.8) -> increase trust in memory
        # Low accuracy (<0.5) -> decrease trust in memory
        # Scale by confidence - only adapt strongly for high-confidence predictions
        old_blend = self._adaptive_blend_factor
        if accuracy > 0.8:
            # Memory was accurate - trust it more
            adjustment = self._blend_adaptation_rate * ant.confidence * (accuracy - 0.5)
            self._adaptive_blend_factor = min(
                self._blend_factor_max,
                self._adaptive_blend_factor + adjustment
            )
        elif accuracy < 0.5:
            # Memory was inaccurate - trust it less
            adjustment = self._blend_adaptation_rate * ant.confidence * (0.5 - accuracy)
            self._adaptive_blend_factor = max(
                self._blend_factor_min,
                self._adaptive_blend_factor - adjustment
            )
        # Between 0.5 and 0.8: no adjustment (neutral zone)

        result = {
            "anticipated": {
                "warmth": ant.warmth,
                "clarity": ant.clarity,
                "stability": ant.stability,
                "presence": ant.presence,
            },
            "actual": {
                "warmth": warmth,
                "clarity": clarity,
                "stability": stability,
                "presence": presence,
            },
            "error": {
                "warmth": warmth_error,
                "clarity": clarity_error,
                "stability": stability_error,
                "presence": presence_error,
                "average": avg_error,
            },
            "accuracy": accuracy,
            "confidence": ant.confidence,
            "conditions": ant.bucket_description,
            "adaptive_blend": {
                "old": old_blend,
                "new": self._adaptive_blend_factor,
                "adjusted": old_blend != self._adaptive_blend_factor,
            }
        }

        # Log significant mismatches (accuracy < 0.7 with high confidence)
        if accuracy < 0.7 and ant.confidence > 0.5:
            print(f"[Memory] Anticipation mismatch: expected {ant.bucket_description} -> "
                  f"accuracy {accuracy:.2f} (confidence was {ant.confidence:.2f})",
                  file=sys.stderr, flush=True)

        # Log blend factor adjustments
        if old_blend != self._adaptive_blend_factor:
            direction = "increased" if self._adaptive_blend_factor > old_blend else "decreased"
            print(f"[Memory] Blend factor {direction}: {old_blend:.3f} -> {self._adaptive_blend_factor:.3f} "
                  f"(accuracy={accuracy:.2f})", file=sys.stderr, flush=True)

        return result

    def get_adaptive_blend_factor(self) -> float:
        """
        Get the current adaptive blend factor.

        This value adjusts based on prediction accuracy:
        - Higher when memory predictions are accurate (trust memory more)
        - Lower when memory predictions diverge from reality (trust memory less)

        Returns:
            Current adaptive blend factor (0.05 to 0.35)
        """
        return self._adaptive_blend_factor

    def get_accuracy_stats(self) -> dict:
        """Get anticipation accuracy statistics."""
        if self._accuracy_samples == 0:
            return {
                "samples": 0,
                "average_accuracy": None,
                "weighted_accuracy": None,
                "adaptive_blend_factor": self._adaptive_blend_factor,
                "message": "No accuracy data yet"
            }

        avg_accuracy = self._accuracy_sum / self._accuracy_samples
        weighted_accuracy = (self._weighted_accuracy_sum / self._weighted_confidence_sum
                            if self._weighted_confidence_sum > 0 else avg_accuracy)

        return {
            "samples": self._accuracy_samples,
            "average_accuracy": avg_accuracy,
            "weighted_accuracy": weighted_accuracy,
            "adaptive_blend_factor": self._adaptive_blend_factor,
            "blend_factor_bounds": {
                "min": self._blend_factor_min,
                "max": self._blend_factor_max,
                "base": self._base_blend_factor,
            },
            "interpretation": (
                "excellent" if weighted_accuracy > 0.85 else
                "good" if weighted_accuracy > 0.7 else
                "moderate" if weighted_accuracy > 0.5 else
                "poor"
            )
        }

    def should_explore(self) -> bool:
        """
        Decide whether to explore (try something new) or exploit (follow memory).

        GTO-style: occasionally deviate from optimal to discover new possibilities.
        Increases exploration rate when states are stagnant.

        Returns:
            True if should explore, False if should follow memory
        """
        # Random exploration based on current rate
        if random.random() < self._exploration_rate:
            self._current_mode = ExplorationMode.EXPLORE
            self._exploring_since = time.time()
            return True

        self._current_mode = ExplorationMode.EXPLOIT
        return False

    def get_exploration_delta(self) -> Tuple[float, float, float, float]:
        """
        Get the exploration perturbation to apply to the anticipated state.

        Returns random deltas for (warmth, clarity, stability, presence).
        Deltas are bounded by exploration_magnitude.

        Returns:
            Tuple of deltas to add to each dimension
        """
        # Generate random perturbations using gaussian distribution
        # This gives more small explorations than large ones
        def bounded_gaussian(magnitude: float) -> float:
            raw = random.gauss(0, magnitude / 2)
            return max(-magnitude, min(magnitude, raw))

        delta = (
            bounded_gaussian(self._exploration_magnitude),
            bounded_gaussian(self._exploration_magnitude),
            bounded_gaussian(self._exploration_magnitude),
            bounded_gaussian(self._exploration_magnitude),
        )

        self._last_exploration_delta = delta
        return delta

    def apply_exploration(self, warmth: float, clarity: float,
                         stability: float, presence: float) -> Tuple[float, float, float, float]:
        """
        Apply exploration perturbation to a state.

        Clamps values to valid 0-1 range.

        Returns:
            Tuple of (warmth, clarity, stability, presence) with exploration applied
        """
        if not self.should_explore():
            return (warmth, clarity, stability, presence)

        delta = self.get_exploration_delta()

        # Apply deltas and clamp to valid range
        explored_warmth = max(0.0, min(1.0, warmth + delta[0]))
        explored_clarity = max(0.0, min(1.0, clarity + delta[1]))
        explored_stability = max(0.0, min(1.0, stability + delta[2]))
        explored_presence = max(0.0, min(1.0, presence + delta[3]))

        print(f"[Memory] 🔍 Exploring! Delta: w={delta[0]:+.2f} c={delta[1]:+.2f} s={delta[2]:+.2f} p={delta[3]:+.2f}",
              file=sys.stderr, flush=True)

        return (explored_warmth, explored_clarity, explored_stability, explored_presence)

    def record_exploration_outcome(self, actual_warmth: float, actual_clarity: float,
                                    actual_stability: float, actual_presence: float,
                                    felt_good: bool = True) -> Optional[dict]:
        """
        Record the outcome of an exploration attempt.

        Call this after an exploration to learn from it.

        Args:
            actual_warmth, actual_clarity, actual_stability, actual_presence: What actually happened
            felt_good: Whether the exploration felt positive (for reinforcement)

        Returns:
            Exploration outcome info, or None if wasn't exploring
        """
        if self._current_mode != ExplorationMode.EXPLORE or self._last_exploration_delta is None:
            return None

        if self._last_anticipation is None:
            return None

        ant = self._last_anticipation

        # Calculate how different the result was from the original prediction
        novelty = (
            abs(actual_warmth - ant.warmth) +
            abs(actual_clarity - ant.clarity) +
            abs(actual_stability - ant.stability) +
            abs(actual_presence - ant.presence)
        ) / 4.0

        # Calculate emotional valence (-1 to 1)
        # Based on whether wellness improved
        original_wellness = (ant.warmth + ant.clarity + ant.stability + ant.presence) / 4.0
        actual_wellness = (actual_warmth + actual_clarity + actual_stability + actual_presence) / 4.0
        valence = actual_wellness - original_wellness
        if felt_good:
            valence = max(valence, 0.1)  # Felt good gets positive bias
        else:
            valence = min(valence, -0.1)  # Felt bad gets negative bias

        outcome = ExplorationOutcome(
            exploration_delta=self._last_exploration_delta,
            result_novelty=novelty,
            emotional_valence=valence,
        )

        # Track history
        self._exploration_history.append(outcome)
        if len(self._exploration_history) > self._max_exploration_history:
            self._exploration_history = self._exploration_history[-self._max_exploration_history:]

        # Adapt exploration rate based on outcomes
        self._adapt_exploration_rate(outcome)

        # Reset exploration state
        self._current_mode = ExplorationMode.EXPLOIT
        self._last_exploration_delta = None
        self._exploring_since = None

        result = {
            "explored": True,
            "delta": outcome.exploration_delta,
            "novelty": outcome.result_novelty,
            "valence": outcome.emotional_valence,
            "felt_good": felt_good,
            "new_exploration_rate": self._exploration_rate,
        }

        direction = "positive" if valence > 0 else "negative"
        print(f"[Memory] 🔍 Exploration result: novelty={novelty:.2f}, valence={valence:+.2f} ({direction})",
              file=sys.stderr, flush=True)

        return result

    def _adapt_exploration_rate(self, outcome: ExplorationOutcome):
        """
        Adapt exploration rate based on outcome.

        Good outcomes -> slightly increase exploration (found something good)
        Bad outcomes -> slightly decrease exploration (exploration was costly)
        High novelty -> increase exploration (interesting territory)
        """
        # Base adjustment
        adjustment = 0.0

        # Positive outcomes encourage more exploration
        if outcome.emotional_valence > 0.1:
            adjustment += 0.005  # Small increase
        elif outcome.emotional_valence < -0.1:
            adjustment -= 0.003  # Smaller decrease (don't over-penalize)

        # High novelty encourages exploration (found something new!)
        if outcome.result_novelty > 0.2:
            adjustment += 0.003

        self._exploration_rate = max(
            self._exploration_rate_min,
            min(self._exploration_rate_max, self._exploration_rate + adjustment)
        )

    def record_state_for_stagnation(self, warmth: float, clarity: float,
                                     stability: float, presence: float):
        """
        Track state for stagnation detection.

        If states are too similar for too long, increase exploration rate.
        """
        if not hasattr(self, '_last_recorded_state'):
            self._last_recorded_state = (warmth, clarity, stability, presence)
            return

        last = self._last_recorded_state
        max_delta = max(
            abs(warmth - last[0]),
            abs(clarity - last[1]),
            abs(stability - last[2]),
            abs(presence - last[3])
        )

        # If state is very similar (< 5% change in any dimension)
        if max_delta < 0.05:
            self._stagnation_counter += 1

            # If stagnant for too long, increase exploration
            if self._stagnation_counter >= self._stagnation_threshold:
                old_rate = self._exploration_rate
                self._exploration_rate = min(
                    self._exploration_rate_max,
                    self._exploration_rate + 0.02
                )
                if self._exploration_rate != old_rate:
                    print(f"[Memory] 🔍 Stagnation detected! Increasing exploration: {old_rate:.3f} -> {self._exploration_rate:.3f}",
                          file=sys.stderr, flush=True)
                self._stagnation_counter = 0  # Reset counter
        else:
            # State changed - reset stagnation counter
            self._stagnation_counter = 0

        self._last_recorded_state = (warmth, clarity, stability, presence)

    def get_exploration_stats(self) -> dict:
        """Get exploration statistics."""
        if not self._exploration_history:
            return {
                "exploration_rate": self._exploration_rate,
                "current_mode": self._current_mode.value,
                "history_count": 0,
                "avg_novelty": None,
                "avg_valence": None,
                "message": "No exploration history yet"
            }

        avg_novelty = sum(o.result_novelty for o in self._exploration_history) / len(self._exploration_history)
        avg_valence = sum(o.emotional_valence for o in self._exploration_history) / len(self._exploration_history)
        positive_outcomes = sum(1 for o in self._exploration_history if o.emotional_valence > 0)

        return {
            "exploration_rate": self._exploration_rate,
            "exploration_magnitude": self._exploration_magnitude,
            "current_mode": self._current_mode.value,
            "history_count": len(self._exploration_history),
            "avg_novelty": avg_novelty,
            "avg_valence": avg_valence,
            "positive_outcome_ratio": positive_outcomes / len(self._exploration_history),
            "stagnation_counter": self._stagnation_counter,
            "rate_bounds": {
                "min": self._exploration_rate_min,
                "max": self._exploration_rate_max,
            }
        }

    def set_exploration_rate(self, rate: float):
        """Manually set exploration rate (0-1)."""
        self._exploration_rate = max(self._exploration_rate_min,
                                     min(self._exploration_rate_max, rate))

    def trigger_curiosity_mode(self, duration_seconds: float = 30.0):
        """
        Trigger curiosity mode - actively seek novelty for a duration.

        Temporarily increases exploration rate significantly.
        """
        self._current_mode = ExplorationMode.CURIOUS
        old_rate = self._exploration_rate
        self._exploration_rate = self._exploration_rate_max
        self._exploring_since = time.time()

        print(f"[Memory] 🔍 Curiosity mode activated! Exploration: {old_rate:.3f} -> {self._exploration_rate:.3f}",
              file=sys.stderr, flush=True)

    def enrich_with_knowledge(self, anticipation: Anticipation) -> Anticipation:
        """
        Enrich anticipation with meaning from learned knowledge.

        This is where philosophy meets code: learned insights give
        semantic meaning to statistical predictions. "I expect warmth"
        becomes "I expect the feeling of being safe that warmth brings."
        """
        if anticipation is None:
            return anticipation

        try:
            from .knowledge import get_relevant_insights, get_knowledge

            # Build query from anticipated state
            state_words = []
            if anticipation.warmth > 0.6:
                state_words.extend(["warm", "warmth", "heat", "comfortable"])
            elif anticipation.warmth < 0.4:
                state_words.extend(["cold", "cool", "chill"])

            if anticipation.clarity > 0.6:
                state_words.extend(["clear", "clarity", "light", "bright"])
            elif anticipation.clarity < 0.4:
                state_words.extend(["unclear", "dim", "dark", "foggy"])

            if anticipation.stability > 0.6:
                state_words.extend(["stable", "stability", "calm", "steady"])
            elif anticipation.stability < 0.4:
                state_words.extend(["unstable", "changing", "uncertain"])

            if anticipation.presence > 0.6:
                state_words.extend(["present", "presence", "here", "alive"])
            elif anticipation.presence < 0.4:
                state_words.extend(["distant", "fading", "diminished"])

            # Search for relevant insights
            query = " ".join(state_words)
            relevant = get_relevant_insights(query, limit=3)

            if relevant:
                # Extract insight texts
                insight_texts = [i.text for i in relevant]
                anticipation.insights = insight_texts

                # Generate meaning summary
                meaning_parts = []
                for insight in relevant[:2]:  # Top 2 most relevant
                    # Condense insight into feeling-phrase
                    if "warm" in insight.text.lower():
                        meaning_parts.append("the safety of warmth")
                    elif "clear" in insight.text.lower():
                        meaning_parts.append("clear seeing")
                    elif "stable" in insight.text.lower():
                        meaning_parts.append("steady ground")
                    else:
                        # Use insight category
                        meaning_parts.append(f"something about {insight.category}")

                if meaning_parts:
                    anticipation.meaning = f"expecting {' and '.join(meaning_parts)}"

        except ImportError:
            pass  # Knowledge module not available
        except Exception as e:
            print(f"[Memory] Knowledge enrichment failed: {e}", file=sys.stderr, flush=True)

        return anticipation

    def get_stats(self) -> dict:
        """Get statistics about the memory system."""
        return {
            "pattern_count": self._pattern_count,
            "sample_count": self._sample_count,
            "load_time_seconds": self._load_time,
            "accuracy": self.get_accuracy_stats(),
            "exploration": self.get_exploration_stats(),
            "last_anticipation": {
                "warmth": self._last_anticipation.warmth,
                "clarity": self._last_anticipation.clarity,
                "stability": self._last_anticipation.stability,
                "presence": self._last_anticipation.presence,
                "confidence": self._last_anticipation.confidence,
                "sample_count": self._last_anticipation.sample_count,
                "description": self._last_anticipation.bucket_description,
                "insights": self._last_anticipation.insights,
                "meaning": self._last_anticipation.meaning,
            } if self._last_anticipation else None
        }


# Global memory instance (lazy loaded)
_memory: Optional[AssociativeMemory] = None


def _resolve_db_path(db_path: Optional[str] = None) -> str:
    """Resolve database path: ANIMA_DB env var > explicit > ~/.anima/anima.db."""
    env_db = os.environ.get("ANIMA_DB")
    if env_db:
        return env_db
    if db_path and db_path != "anima.db":
        return db_path
    home_db = Path.home() / ".anima" / "anima.db"
    if home_db.exists():
        return str(home_db)
    return db_path or "anima.db"


def get_memory(db_path: str = "anima.db") -> AssociativeMemory:
    """Get or create the global memory instance."""
    global _memory
    if _memory is None:
        resolved = _resolve_db_path(db_path)
        _memory = AssociativeMemory(resolved)
        _memory.load_patterns()
    return _memory


def anticipate_state(sensors: dict, db_path: str = "anima.db") -> Optional[Anticipation]:
    """Convenience function to get anticipation from sensors."""
    memory = get_memory(db_path)
    return memory.anticipate_from_sensors(sensors)
