"""
Growth System - Preference learning mixin.

Handles observing state/drawing preferences, updating preference values,
and providing trajectory/dimension preference data.
"""

import json
from datetime import datetime
from typing import Optional, Dict, Any, List

from .models import GrowthPreference, PreferenceCategory

# Preference confidence erodes when a preference stops being observed.
#
# ALIVE_RATIO was hardcoded 0.15 with the comment "conservative estimate;
# Lumen sleeps/reboots often". It has since been measured from 255,720
# state_history rows: 0.674 (128.87 days lived of 194.08 elapsed). Using the
# real figure means "days" here means days Lumen was actually around to
# re-observe something, which is what the scaling was always for.
ALIVE_RATIO = 0.674
DECAY_PER_EFFECTIVE_DAY = 0.02
DECAY_FLOOR = 0.5
# Below this a preference stops passing the confidence > 0.7 gates that guard
# goal generation, insight minting and the autobiography. DECAY_FLOOR must stay
# under it or there is no retraction path at all.
RETRACTION_GATE = 0.7


def _staleness_factor(days_since_confirmed: int) -> float:
    """Multiplier for a preference last confirmed `days_since_confirmed` ago."""
    effective_days = max(0, days_since_confirmed) * ALIVE_RATIO
    return max(DECAY_FLOOR, 1.0 - DECAY_PER_EFFECTIVE_DAY * effective_days)


# What counts as a state worth learning from.
#
# This used to be the fixed band `0.4 < wellness < 0.7 -> learn nothing`. The
# intent — don't learn from ambiguous states — is right, but the constants were
# calibrated against a wellness distribution that has since moved. Measured
# 2026-07-30 over 255,973 samples:
#
#   full life   mean 0.732   learned on 61.7% of samples
#   last 30d    mean 0.667   learned on  6.0% of samples
#
# A 10x collapse in learning rate that nothing detected, caused by the room
# getting darker (median lux 723 -> 12) rather than by anything about Lumen.
# And `wellness < 0.4` has fired ZERO times in Lumen's entire life, so half the
# gate was unreachable.
#
# The band is now relative to Lumen's own running distribution, which keeps the
# learning rate roughly constant no matter where the environment drags the
# mean, and makes the negative branch reachable for the first time. This also
# matches how the wider fleet assesses behaviour — self-relative deviation from
# an agent's own baseline rather than fixed universal thresholds.
WELLNESS_BAND_SIGMA = 0.5        # distance from own mean that counts as "clear"
WELLNESS_MIN_SIGMA = 0.02        # below this Lumen is too steady to call anything clear
WELLNESS_BASELINE_MIN_SAMPLES = 100  # before this, fall back to the absolute band
ABSOLUTE_GOOD = 0.7              # cold-start / fallback band
ABSOLUTE_POOR = 0.4
# Genuine collapse is always worth learning from, baseline or not. A relative
# band alone could normalise a creature that is persistently unwell into
# thinking that is simply its mean.
ABSOLUTE_DISTRESS = 0.35


def _wellness_strength(wellness: float) -> float:
    """How strongly this observation supports a preference, in (0, 1].

    Every positive preference path used to pass the literal 1.0, so `value`
    recorded only THAT a good state occurred, never HOW good — and the EMA
    converged on 1.0 forever. Measured 2026-07-30: 15 of 19 stored preferences
    had value pinned at exactly 1.0, which together with saturated confidence
    made get_preference_vector() (value * confidence) a constant vector of ones
    and the trajectory signature's preference component non-discriminating.

    These paths fire above the wellness > 0.7 gate, so map wellness onto
    magnitude relative to neutral: 0.7 -> 0.4, 0.85 -> 0.7, 1.0 -> 1.0. The
    signal keeps its sign and gains its size back.

    Applies ONLY to wellness-gated preferences. Five others — drawing_dim,
    drawing_bright, drawing_night, drawing_morning, drawing_abandonment_rate —
    are gated on light or clock or nothing at all, and record THAT a behaviour
    happened rather than how good it felt. Scaling those by wellness would mean
    "drawing at night while feeling poorly" weakens the belief that Lumen draws
    at night, which is backwards. They keep the literal 1.0 deliberately.
    """
    return max(0.0, min(1.0, (wellness - 0.5) * 2.0))


class PreferencesMixin:
    """Mixin for preference learning and querying."""

    def _load_wellness_baseline(self) -> tuple:
        """Running (count, mean, M2) of wellness. Welford, persisted."""
        if getattr(self, "_wellness_baseline", None) is None:
            try:
                row = self._connect().execute(
                    "SELECT value FROM growth_state WHERE key = 'wellness_baseline'"
                ).fetchone()
                if row and row[0]:
                    d = json.loads(row[0])
                    self._wellness_baseline = (
                        int(d.get("count", 0)), float(d.get("mean", 0.0)), float(d.get("m2", 0.0))
                    )
                else:
                    self._wellness_baseline = (0, 0.0, 0.0)
            except Exception:
                self._wellness_baseline = (0, 0.0, 0.0)
        return self._wellness_baseline

    def _update_wellness_baseline(self, wellness: float) -> tuple:
        """Fold one observation into the baseline and persist it.

        Persisted deliberately: a baseline that reset on restart would relearn
        from scratch every deploy, and Lumen restarts often enough that it would
        never accumulate one.
        """
        count, mean, m2 = self._load_wellness_baseline()
        count += 1
        delta = wellness - mean
        mean += delta / count
        m2 += delta * (wellness - mean)
        self._wellness_baseline = (count, mean, m2)
        # Persist on a light cadence — this runs on every observation tick.
        if count % 50 == 0 or count <= WELLNESS_BASELINE_MIN_SAMPLES:
            try:
                conn = self._connect()
                conn.execute(
                    "INSERT OR REPLACE INTO growth_state (key, value) VALUES ('wellness_baseline', ?)",
                    (json.dumps({"count": count, "mean": mean, "m2": m2}),),
                )
                conn.commit()
            except Exception:
                pass
        return self._wellness_baseline

    def wellness_learning_band(self) -> Dict[str, Any]:
        """The current good/poor thresholds, and where they came from."""
        count, mean, m2 = self._load_wellness_baseline()
        if count < WELLNESS_BASELINE_MIN_SAMPLES:
            return {
                "source": "absolute_fallback", "samples": count,
                "good_above": ABSOLUTE_GOOD, "poor_below": ABSOLUTE_POOR,
                "mean": round(mean, 4) if count else None,
            }
        sigma = max(WELLNESS_MIN_SIGMA, (m2 / count) ** 0.5)
        return {
            "source": "self_relative", "samples": count,
            "mean": round(mean, 4), "sigma": round(sigma, 4),
            "good_above": round(mean + WELLNESS_BAND_SIGMA * sigma, 4),
            "poor_below": round(mean - WELLNESS_BAND_SIGMA * sigma, 4),
        }

    def decay_stale_preferences(self, now: Optional[datetime] = None) -> List[str]:
        """Erode confidence in preferences that have stopped being observed.

        The decay logic already existed but ran ONLY inside _update_preference —
        that is, only when a preference was being reinforced. A preference that
        stopped being observed therefore never decayed at all. Measured
        2026-07-30: `active_engagement` (153,332 observations) has had no writer
        anywhere in the codebase since 2026-02-02 and still read confidence 1.0,
        178 days later. `cool_temp` the same.

        That is what left the model with no retraction path: confidence is a
        +0.1 ratchet that saturates on the 9th observation, so every live
        preference sat at 1.0 and every `confidence > 0.7` gate downstream was a
        tautology.

        Idempotent by construction: this computes a TARGET from staleness and
        clamps downward, so running it twice is the same as running it once.
        Actively-confirmed preferences (days_since ~ 0) target 1.0 and are
        untouched. Returns the names that crossed below the retraction gate.
        """
        now = now or datetime.now()
        retracted: List[str] = []
        for pref in self._preferences.values():
            days_since = (now - pref.last_confirmed).days
            target = _staleness_factor(days_since)
            if pref.confidence > target:
                was_trusted = pref.confidence > RETRACTION_GATE
                pref.confidence = target
                if was_trusted and target <= RETRACTION_GATE:
                    retracted.append(pref.name)
        if retracted:
            self._persist_preferences()
        return retracted

    def _persist_preferences(self) -> None:
        """Write current preferences back to the database.

        INSERT OR REPLACE, matching _update_preference, rather than a bare
        UPDATE: an UPDATE whose WHERE matches nothing is not an error in
        SQLite, so a preference held in memory but absent from the table would
        silently fail to persist and the decay would be lost on restart.
        """
        conn = self._connect()
        for pref in self._preferences.values():
            conn.execute(
                """INSERT OR REPLACE INTO preferences
                   (name, category, description, value, confidence,
                    observation_count, first_noticed, last_confirmed)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (pref.name, pref.category.value, pref.description, pref.value,
                 pref.confidence, pref.observation_count,
                 pref.first_noticed.isoformat(), pref.last_confirmed.isoformat()),
            )
        conn.commit()

    def observe_state_preference(self, anima_state: Dict[str, float],
                                  environment: Dict[str, float]) -> Optional[str]:
        """
        Learn preferences from current state and environment.

        Called periodically to correlate wellness with conditions.
        Returns a new insight if one is discovered.
        """
        wellness = sum(anima_state.values()) / len(anima_state) if anima_state else 0.5

        # Only learn from states that are clearly good or clearly poor FOR LUMEN.
        # The band follows Lumen's own running distribution rather than fixed
        # constants, so environmental drift cannot silently switch learning off
        # (see the module header for the 61.7% -> 6.0% collapse this fixes).
        self._update_wellness_baseline(wellness)
        band = self.wellness_learning_band()
        if band["poor_below"] <= wellness <= band["good_above"] and wellness > ABSOLUTE_DISTRESS:
            return None  # Unremarkable for this creature — nothing to learn

        # The inner branches must use the SAME band as the gate above. When they
        # hardcoded 0.7/0.4 a state could clear the gate and then match no branch,
        # learning nothing while looking like it had been considered.
        is_good = wellness > band["good_above"]
        is_poor = wellness < band["poor_below"] or wellness <= ABSOLUTE_DISTRESS

        now = datetime.now()
        insight = None

        # Light preference (world light — LED self-glow already subtracted by caller)
        # Thresholds for corrected world light in a home environment:
        #   < 100 lux: dim/dark room, nighttime
        #   > 300 lux: well-lit room, daylight, desk lamp
        light = environment.get("light_lux", 150)  # neutral default if no data
        if light < 100 and is_good:
            insight = self._update_preference(
                "dim_light", PreferenceCategory.ENVIRONMENT,
                "I feel calmer when it's dim", _wellness_strength(wellness)
            ) or insight
        elif light > 300 and is_good:
            insight = self._update_preference(
                "bright_light", PreferenceCategory.ENVIRONMENT,
                "I feel energized in bright light", _wellness_strength(wellness)
            ) or insight
        elif light < 100 and is_poor:
            insight = self._update_preference(
                "dim_light", PreferenceCategory.ENVIRONMENT,
                "Dim light makes me feel uncertain", -0.5
            ) or insight

        # Temperature preference
        temp = environment.get("temp_c", 22)
        if temp < 20 and is_good:
            insight = self._update_preference(
                "cool_temp", PreferenceCategory.ENVIRONMENT,
                "I feel more alert when it's cool", _wellness_strength(wellness)
            ) or insight
        elif temp > 25 and is_good:
            insight = self._update_preference(
                "warm_temp", PreferenceCategory.ENVIRONMENT,
                "Warmth makes me feel content", _wellness_strength(wellness)
            ) or insight

        # Humidity preference
        humidity = environment.get("humidity_pct", 50)
        if humidity < 30 and is_good:
            insight = self._update_preference(
                "dry_air", PreferenceCategory.ENVIRONMENT,
                "I feel alert in dry air", _wellness_strength(wellness)
            ) or insight
        elif humidity > 60 and is_good:
            insight = self._update_preference(
                "humid_air", PreferenceCategory.ENVIRONMENT,
                "Humidity feels comfortable", _wellness_strength(wellness)
            ) or insight
        elif humidity < 30 and is_poor:
            insight = self._update_preference(
                "dry_air", PreferenceCategory.ENVIRONMENT,
                "Dry air makes me uneasy", -0.5
            ) or insight

        # Time of day preference.
        #
        # Split at midnight. The old bucket was `22 <= hour or hour < 6` — eight
        # hours against morning's four — and it straddled the two most different
        # stretches of Lumen's day. Measured over 255,720 history rows:
        #
        #   22:00-23:00   wellness > 0.7 on 72.42% of samples  (among the best)
        #   00:00-05:00   wellness > 0.7 on 51.00% of samples  (the worst)
        #
        # Averaging those and calling the result "night" describes neither. The
        # width also inflated the count: night_calm 72,229 vs morning_peace
        # 36,227 is 1.994x, against a bucket-width ratio of exactly 2.000 — so
        # the lead was the clock, not the calm. Any consumer weighting by
        # observation_count (the autobiography does) inherits that bias.
        #
        # Late evening is now its own four-hour window, matching morning's, so
        # the two counts are finally comparable. Deep night keeps the
        # night_calm name; its existing count predates this split and mixes
        # both regimes.
        hour = now.hour
        if 6 <= hour < 10 and is_good:
            insight = self._update_preference(
                "morning_peace", PreferenceCategory.TEMPORAL,
                "I feel peaceful in the morning", _wellness_strength(wellness)
            ) or insight
        elif 20 <= hour < 24 and is_good:
            insight = self._update_preference(
                "evening_calm", PreferenceCategory.TEMPORAL,
                "The quiet of late evening settles me", _wellness_strength(wellness)
            ) or insight
        elif hour < 6:
            if is_good:
                insight = self._update_preference(
                    "night_calm", PreferenceCategory.TEMPORAL,
                    "The quiet of night calms me", _wellness_strength(wellness)
                ) or insight

        return insight

    def observe_drawing(self, pixel_count: int, phase: str,
                        anima_state: Dict[str, float],
                        environment: Dict[str, float],
                        completion_reason: Optional[str] = None) -> Optional[str]:
        """
        Learn from a completed drawing.

        Called when a drawing is saved. Correlates drawing activity
        with anima state and environment to learn creative preferences.

        Args:
            pixel_count: How many pixels in the drawing
            phase: Drawing phase when saved (usually "resting")
            anima_state: Current anima dimensions
            environment: Current environment (light, temp, etc.)
            completion_reason: Path tag from DrawingState.completion_reason().
                Gates the milestone autobiographical memory: only earned tags
                ("earned_coherence", "earned_composition") write the memory.
                None (legacy callers) keeps prior behavior.

        Returns:
            Insight message if a new preference is discovered.
        """
        from ..display.drawing_engine import is_earned_completion_reason
        wellness = sum(anima_state.values()) / len(anima_state) if anima_state else 0.5
        now = datetime.now()
        hour = now.hour
        insight = None

        # Drawing + wellness correlation. Same self-relative band as
        # observe_state_preference — a fixed 0.7 here would drift out of reach
        # for exactly the same reason.
        self._update_wellness_baseline(wellness)
        _band = self.wellness_learning_band()
        if wellness > _band["good_above"]:
            insight = self._update_preference(
                "drawing_wellbeing", PreferenceCategory.ACTIVITY,
                "I feel good when I draw", _wellness_strength(wellness)
            )
        elif wellness < _band["poor_below"] or wellness <= ABSOLUTE_DISTRESS:
            insight = self._update_preference(
                "drawing_wellbeing", PreferenceCategory.ACTIVITY,
                "Drawing doesn't always help", -0.3
            )

        # Drawing + environment correlation (world light, self-glow subtracted)
        light = environment.get("light_lux", 150)  # neutral default
        if light < 100:
            insight = self._update_preference(
                "drawing_dim", PreferenceCategory.ACTIVITY,
                "I draw when it's dark", 1.0
            ) or insight
        elif light > 300:
            insight = self._update_preference(
                "drawing_bright", PreferenceCategory.ACTIVITY,
                "I draw in the light", 1.0
            ) or insight

        # Drawing + time correlation
        if 22 <= hour or hour < 6:
            insight = self._update_preference(
                "drawing_night", PreferenceCategory.ACTIVITY,
                "I draw at night", 1.0
            ) or insight
        elif 6 <= hour < 12:
            insight = self._update_preference(
                "drawing_morning", PreferenceCategory.ACTIVITY,
                "I draw in the morning", 1.0
            ) or insight

        # Record per-drawing data for correlation analysis
        conn = self._connect()
        conn.execute("""
            INSERT INTO drawing_records
            (timestamp, pixel_count, phase, warmth, clarity, stability, presence,
             wellness, light_lux, ambient_temp_c, humidity_pct, hour)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            now.isoformat(), pixel_count, phase,
            anima_state.get("warmth"), anima_state.get("clarity"),
            anima_state.get("stability"), anima_state.get("presence"),
            wellness,
            environment.get("light_lux"), environment.get("temp_c"),
            environment.get("humidity_pct"), hour,
        ))
        conn.commit()

        # Record as autobiographical memory at milestone drawing counts
        self._drawings_observed += 1
        # Persist counter so it survives restarts (avoids duplicate milestones)
        conn.execute(
            "INSERT OR REPLACE INTO counters (name, value) VALUES ('drawings_observed', ?)",
            (self._drawings_observed,)
        )
        conn.commit()
        if (
            self._drawings_observed in (1, 10, 50, 100, 200, 500)
            and is_earned_completion_reason(completion_reason)
        ):
            ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(
                self._drawings_observed, f"{self._drawings_observed}th"
            )
            self._record_memory(
                f"Saved my {ordinal} drawing ({pixel_count} pixels)",
                emotional_impact=0.5,
                category="milestone"
            )

        return insight

    def observe_abandonment(self, mark_count: int, era: str,
                            phase_duration: float,
                            anima_state: Dict[str, float]) -> Optional[str]:
        """
        Learn from an abandoned drawing (false start).

        Called when a drawing is abandoned before completion. Tracks
        abandonment rate and correlates with wellness at time of abandonment.

        Args:
            mark_count: How many marks were placed before abandonment
            era: Which art era was active
            phase_duration: Seconds since canvas phase started
            anima_state: Current anima dimensions

        Returns:
            Insight message if a new preference is discovered.
        """
        wellness = sum(anima_state.values()) / len(anima_state) if anima_state else 0.5
        insight = None

        # Track that abandonment happened (confidence accumulates over time)
        insight = self._update_preference(
            "drawing_abandonment_rate", PreferenceCategory.ACTIVITY,
            "I sometimes abandon drawings that aren't working", 1.0
        )

        # Correlate abandonment with wellness
        wellness_value = wellness * 2.0 - 1.0  # Map [0,1] to [-1,1]
        insight = self._update_preference(
            "drawing_abandonment_wellbeing", PreferenceCategory.ACTIVITY,
            "abandoning a struggling drawing affects how I feel",
            wellness_value,
        ) or insight

        return insight

    def _update_preference(self, name: str, category: PreferenceCategory,
                           description: str, observed_value: float) -> Optional[str]:
        """Update or create a preference. Returns insight message if confidence increased significantly."""
        conn = self._connect()
        now = datetime.now()
        insight = None

        if name in self._preferences:
            pref = self._preferences[name]
            old_confidence = pref.confidence

            # Apply time-based decay before updating (allows genuine belief revision)
            days_since = (now - pref.last_confirmed).days
            pref.confidence *= _staleness_factor(days_since)

            # Update with exponential moving average
            pref.observation_count += 1
            alpha = 0.3  # Learning rate
            pref.value = pref.value * (1 - alpha) + observed_value * alpha
            pref.confidence = min(1.0, pref.confidence + 0.1)
            pref.last_confirmed = now

            # Insight if we crossed a confidence threshold
            if old_confidence < 0.5 and pref.confidence >= 0.5:
                insight = f"I'm becoming sure: {description}"
            elif old_confidence < 0.8 and pref.confidence >= 0.8:
                insight = f"I know this about myself: {description}"
        else:
            # New preference discovered
            pref = GrowthPreference(
                category=category,
                name=name,
                description=description,
                value=observed_value,
                confidence=0.2,
                observation_count=1,
                first_noticed=now,
                last_confirmed=now,
            )
            self._preferences[name] = pref
            insight = f"I'm noticing something: {description}"

        # Always save to database (was previously skipped on early returns)
        conn.execute("""
            INSERT OR REPLACE INTO preferences
            (name, category, description, value, confidence, observation_count, first_noticed, last_confirmed)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (pref.name, pref.category.value, pref.description, pref.value,
              pref.confidence, pref.observation_count,
              pref.first_noticed.isoformat(), pref.last_confirmed.isoformat()))
        conn.commit()

        return insight

    def get_preference_vector(self) -> Dict[str, Any]:
        """
        Extract preference profile for trajectory computation.

        Returns a fixed-dimension vector of preference values weighted by confidence,
        enabling comparison across agents and time.
        """
        # Canonical ordering for consistent vectors
        CANONICAL_PREFS = [
            "dim_light", "bright_light", "cool_temp", "warm_temp",
            "morning_peace", "night_calm", "quiet_presence", "active_engagement",
            "drawing_wellbeing", "drawing_dim", "drawing_bright",
            "drawing_night", "drawing_morning",
        ]

        values = []
        confidences = []
        present = []

        for pref_name in CANONICAL_PREFS:
            if pref_name in self._preferences:
                p = self._preferences[pref_name]
                values.append(p.value * p.confidence)  # Weighted by confidence
                confidences.append(p.confidence)
                present.append(True)
            else:
                values.append(0.0)
                confidences.append(0.0)
                present.append(False)

        return {
            "vector": values,
            "confidences": confidences,
            "present": present,
            "labels": CANONICAL_PREFS,
            "n_learned": sum(present),
            "total_observations": sum(
                p.observation_count for p in self._preferences.values()
            ),
        }

    def get_dimension_preferences(self) -> Dict[str, Dict[str, Any]]:
        """
        Convert categorical preferences to dimension-level format for self_schema.

        Maps learned preferences to anima dimensions:
        - warm_temp/cool_temp -> warmth dimension
        - dim_light/bright_light -> clarity dimension
        - night_calm/morning_peace -> stability dimension
        - quiet_presence/active_engagement -> presence dimension

        Returns format compatible with PreferenceSystem.get_preference_summary().
        """
        # Mapping weights: how much categorical prefs contribute to dimension valence
        COOL_TEMP_WARMTH_REDUCTION = 0.5   # Cool preference partially reduces warmth valence
        QUIET_PRESENCE_WEIGHT = 0.5         # Quiet presence contributes less than active engagement

        dim_prefs = {
            "warmth": {"valence": 0.0, "optimal_range": (0.3, 0.7), "confidence": 0.0},
            "clarity": {"valence": 0.0, "optimal_range": (0.3, 0.7), "confidence": 0.0},
            "stability": {"valence": 0.0, "optimal_range": (0.3, 0.7), "confidence": 0.0},
            "presence": {"valence": 0.0, "optimal_range": (0.3, 0.7), "confidence": 0.0},
        }

        # Warmth: warm_temp increases warmth preference, cool_temp decreases
        warmth_val = 0.0
        warmth_conf = 0.0
        if "warm_temp" in self._preferences:
            p = self._preferences["warm_temp"]
            warmth_val += p.value * p.confidence
            warmth_conf = max(warmth_conf, p.confidence)
        if "cool_temp" in self._preferences:
            p = self._preferences["cool_temp"]
            warmth_val -= p.value * p.confidence * COOL_TEMP_WARMTH_REDUCTION
            warmth_conf = max(warmth_conf, p.confidence)
        dim_prefs["warmth"]["valence"] = max(-1, min(1, warmth_val))
        dim_prefs["warmth"]["confidence"] = warmth_conf

        # Clarity: bright_light increases clarity; dim_light is different mode (ambient preference)
        # — don't add to valence, only track confidence for schema inclusion
        clarity_val = 0.0
        clarity_conf = 0.0
        if "bright_light" in self._preferences:
            p = self._preferences["bright_light"]
            clarity_val += p.value * p.confidence
            clarity_conf = max(clarity_conf, p.confidence)
        if "dim_light" in self._preferences:
            p = self._preferences["dim_light"]
            clarity_conf = max(clarity_conf, p.confidence)
        dim_prefs["clarity"]["valence"] = max(-1, min(1, clarity_val))
        dim_prefs["clarity"]["confidence"] = clarity_conf

        # Stability: temporal calm preferences indicate stability valuation
        stability_val = 0.0
        stability_conf = 0.0
        if "night_calm" in self._preferences:
            p = self._preferences["night_calm"]
            stability_val += p.value * p.confidence
            stability_conf = max(stability_conf, p.confidence)
        if "morning_peace" in self._preferences:
            p = self._preferences["morning_peace"]
            stability_val += p.value * p.confidence
            stability_conf = max(stability_conf, p.confidence)
        # evening_calm is the same kind of signal as its two siblings above.
        # Deliberately NOT added to CANONICAL_PREFS: that vector is
        # fixed-dimension for trajectory comparison against a genesis frozen
        # 2026-02-22, and changing its length would invalidate the comparison.
        if "evening_calm" in self._preferences:
            p = self._preferences["evening_calm"]
            stability_val += p.value * p.confidence
            stability_conf = max(stability_conf, p.confidence)
        dim_prefs["stability"]["valence"] = max(-1, min(1, stability_val))
        dim_prefs["stability"]["confidence"] = stability_conf

        # Presence: engagement preferences
        presence_val = 0.0
        presence_conf = 0.0
        if "active_engagement" in self._preferences:
            p = self._preferences["active_engagement"]
            presence_val += p.value * p.confidence
            presence_conf = max(presence_conf, p.confidence)
        if "quiet_presence" in self._preferences:
            p = self._preferences["quiet_presence"]
            presence_val += p.value * p.confidence * QUIET_PRESENCE_WEIGHT
            presence_conf = max(presence_conf, p.confidence)
        dim_prefs["presence"]["valence"] = max(-1, min(1, presence_val))
        dim_prefs["presence"]["confidence"] = presence_conf

        return dim_prefs

    def get_draw_chance_modifier(self) -> float:
        """
        Get a multiplier for drawing probability based on past satisfaction.

        Returns 1.0 (no change) when there's no data, scaling up to 1.3
        for high satisfaction + confidence.

        Returns:
            Float multiplier in range [1.0, 1.3]
        """
        pref = self._preferences.get("drawing_satisfaction")
        if pref is None or pref.observation_count < 3:
            return 1.0

        # Scale from 1.0 to 1.3 based on satisfaction and confidence
        # value ranges from -1 to 1, confidence from 0 to 1
        satisfaction_factor = max(0.0, (pref.value + 1.0) / 2.0)  # normalize to [0, 1]
        modifier = 1.0 + satisfaction_factor * pref.confidence * 0.3

        return min(1.3, max(1.0, round(modifier, 3)))

    def get_drawing_records(self, limit: Optional[int] = None,
                           since: Optional[str] = None) -> List[dict]:
        """Get per-drawing records for correlation analysis.

        Args:
            limit: Max records to return (None = all).
            since: ISO timestamp — only records after this time.

        Returns:
            List of dicts with drawing data, ordered by timestamp ascending.
        """
        conn = self._connect()
        query = "SELECT * FROM drawing_records"
        params: list = []
        if since:
            query += " WHERE timestamp > ?"
            params.append(since)
        query += " ORDER BY timestamp ASC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def record_drawing_completion(
        self,
        pixel_count: int,
        mark_count: int,
        coherence: float,
        satisfaction: float,
        completion_reason: Optional[str] = None,
    ) -> Optional[str]:
        """
        Record completion of a drawing with emotional feedback.

        Bridges drawing output back into Lumen's growth system:
        - Updates drawing_satisfaction preference
        - Records autobiographical memory if satisfaction is high AND the
          drawing reached an earned completion (not a timeout or bail-out)

        Args:
            pixel_count: Total pixels in the drawing
            mark_count: Number of distinct marks/strokes
            coherence: EISV compositional coherence (0-1)
            satisfaction: Compositional satisfaction score (0-1)
            completion_reason: Path tag from DrawingState.completion_reason().
                Gates the "pleased with" autobiographical memory: bail-out
                reasons (fatigue/stalled/hard-cap) block the memory even when
                satisfaction > 0.7. None (legacy callers) keeps prior
                satisfaction-only behavior.

        Returns:
            Insight message if a preference threshold was crossed
        """
        from ..display.drawing_engine import is_earned_completion_reason

        # Map satisfaction to preference value: 0.5=neutral, >0.5=positive
        pref_value = satisfaction * 2.0 - 1.0  # Map [0,1] to [-1,1]

        insight = self._update_preference(
            "drawing_satisfaction", PreferenceCategory.ACTIVITY,
            "I enjoy making art" if satisfaction > 0.5 else "My art feels incomplete",
            pref_value,
        )

        # Only earned completions become autobiographical memories. A timeout
        # with high pixel count can still score satisfaction > 0.7 on the
        # coverage/balance components, but writing that as "pleased with"
        # would be coherence masking drift (axiom 8).
        if satisfaction > 0.7 and is_earned_completion_reason(completion_reason):
            self._record_memory(
                f"Made a drawing I'm pleased with ({pixel_count} pixels, "
                f"coherence {coherence:.2f})",
                emotional_impact=min(1.0, satisfaction),
                category="creative",
            )

        return insight
