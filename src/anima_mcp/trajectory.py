"""
Trajectory Identity - Computing and comparing agent trajectory signatures.

This module implements the core framework from the Trajectory Identity Paper:
identity as dynamical invariant, computed from behavioral history.

The trajectory signature Σ = {Π, Β, Α, Ρ, Δ, Η} captures the invariant
characteristics that define an agent's identity:
- Π (Preference Profile): Learned environmental preferences
- Β (Belief Signature): Self-belief patterns
- Α (Attractor Basin): Equilibrium and variance in anima state
- Ρ (Recovery Profile): Characteristic time constants
- Δ (Relational Disposition): Social behavior patterns
- Η (Homeostatic Identity): Unified self-maintenance characterization

See: docs/theory/TRAJECTORY_IDENTITY_PAPER.md
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional, TYPE_CHECKING
import sys

# Optional numpy for advanced computations
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

# Type hints without circular imports
if TYPE_CHECKING:
    from .growth import GrowthSystem
    from .self_model import SelfModel
    from .anima_history import AnimaHistory


@dataclass
class TrajectorySignature:
    """
    Complete trajectory signature Σ.

    This is the mathematical encoding of "who this agent is" - not a static
    ID, but the pattern that persists across time.

    Attributes:
        preferences: Π - Learned environmental preferences
        beliefs: Β - Self-belief patterns
        attractor: Α - Equilibrium and variance in state space
        recovery: Ρ - Recovery dynamics (time constants)
        relational: Δ - Social behavior patterns
        computed_at: When this signature was computed
        observation_count: Number of observations used
    """

    # Components (all are dictionaries from component extractors)
    preferences: Dict[str, Any] = field(default_factory=dict)  # Π
    beliefs: Dict[str, Any] = field(default_factory=dict)       # Β
    attractor: Optional[Dict[str, Any]] = None                  # Α
    recovery: Dict[str, Any] = field(default_factory=dict)      # Ρ
    relational: Dict[str, Any] = field(default_factory=dict)    # Δ

    # Metadata
    computed_at: datetime = field(default_factory=datetime.now)
    observation_count: int = 0

    # Genesis Signature (Σ₀) - Reference anchor for drift detection
    # Set once at agent creation/fork, never updated
    genesis_signature: Optional['TrajectorySignature'] = None

    # Component variance history for adaptive weighting
    # Keys: "preferences", "beliefs", "attractor", "recovery", "relational"
    # Values: list of recent similarity scores for each component
    component_history: Dict[str, List[float]] = field(default_factory=dict)

    def similarity(self, other: 'TrajectorySignature') -> float:
        """
        Compute similarity to another trajectory signature.

        This is the core operation for determining identity:
        sim(Σ₁, Σ₂) > θ implies "same identity"

        Args:
            other: Another TrajectorySignature to compare against

        Returns:
            Similarity score in [0, 1] where 1 = identical trajectories
        """
        scores = []
        weights = []

        # --- Preference Similarity (Π) ---
        # Cosine similarity of preference vectors
        if self.preferences.get("vector") and other.preferences.get("vector"):
            v1 = self.preferences["vector"]
            v2 = other.preferences["vector"]
            sim = self._cosine_similarity(v1, v2)
            if sim is not None:
                scores.append((sim + 1) / 2)  # Map [-1,1] to [0,1]
                weights.append(0.15)

        # --- Belief Similarity (Β) ---
        # Cosine similarity of belief values
        if self.beliefs.get("values") and other.beliefs.get("values"):
            v1 = self.beliefs["values"]
            v2 = other.beliefs["values"]
            sim = self._cosine_similarity(v1, v2)
            if sim is not None:
                scores.append((sim + 1) / 2)
                weights.append(0.15)

        # --- Attractor Similarity (Α) ---
        # Distance between attractor centers
        if self.attractor and other.attractor:
            c1 = self.attractor.get("center")
            c2 = other.attractor.get("center")
            if c1 and c2:
                dist = sum((a - b)**2 for a, b in zip(c1, c2)) ** 0.5
                # Exponential decay: sim = e^(-k*dist)
                center_sim = 2.71828 ** (-dist * 2)
                scores.append(center_sim)
                weights.append(0.25)

        # --- Recovery Similarity (Ρ) ---
        # Similarity of time constants (log-scale)
        t1 = self.recovery.get("tau_estimate")
        t2 = other.recovery.get("tau_estimate")
        if t1 and t2 and t1 > 0 and t2 > 0:
            import math
            log_ratio = abs(math.log(t1 / t2))
            tau_sim = math.exp(-log_ratio)
            scores.append(tau_sim)
            weights.append(0.20)

        # --- Relational Similarity (Δ) ---
        # Valence tendency similarity
        v1 = self.relational.get("valence_tendency")
        v2 = other.relational.get("valence_tendency")
        if v1 is not None and v2 is not None:
            # Max diff is 2 (-1 to 1 range)
            valence_sim = 1 - abs(v1 - v2) / 2
            scores.append(valence_sim)
            weights.append(0.10)

        # --- Compute weighted average ---
        if not scores:
            return 0.5  # No data to compare

        # Normalize weights
        total_weight = sum(weights)
        if total_weight == 0:
            return 0.5

        weighted_sum = sum(s * w for s, w in zip(scores, weights))
        return float(weighted_sum / total_weight)

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> Optional[float]:
        """Compute cosine similarity between two vectors."""
        if len(v1) != len(v2) or len(v1) == 0:
            return None

        dot = sum(a * b for a, b in zip(v1, v2))
        norm1 = sum(a * a for a in v1) ** 0.5
        norm2 = sum(b * b for b in v2) ** 0.5

        if norm1 == 0 or norm2 == 0:
            return None

        return dot / (norm1 * norm2)

    def compute_adaptive_weights(self, default_weights: Optional[Dict[str, float]] = None) -> Dict[str, float]:
        """
        Compute adaptive weights using inverse variance weighting.

        Components with lower historical variance get higher weights
        because they are more stable identity markers.

        Args:
            default_weights: Fallback weights if no history exists

        Returns:
            Dictionary mapping component names to weights (sum to ~1.0)
        """
        if default_weights is None:
            default_weights = {
                "preferences": 0.15,
                "beliefs": 0.15,
                "attractor": 0.25,
                "recovery": 0.20,
                "relational": 0.10,
            }

        # Need at least 5 observations per component for variance
        if not self.component_history:
            return default_weights

        variances = {}
        for component, history in self.component_history.items():
            if len(history) >= 5:
                mean = sum(history) / len(history)
                var = sum((x - mean) ** 2 for x in history) / len(history)
                # Add epsilon to prevent division by zero
                variances[component] = max(var, 1e-6)

        if not variances:
            return default_weights

        # Inverse variance weighting: w_i = (1/var_i) / sum(1/var_j)
        inv_variances = {k: 1.0 / v for k, v in variances.items()}
        total_inv_var = sum(inv_variances.values())

        adaptive_weights = {}
        for component in default_weights:
            if component in inv_variances:
                adaptive_weights[component] = inv_variances[component] / total_inv_var
            else:
                # Use default for components without history
                adaptive_weights[component] = default_weights[component]

        return adaptive_weights

    def similarity_adaptive(
        self,
        other: 'TrajectorySignature',
        update_history: bool = True,
    ) -> Dict[str, Any]:
        """
        Compute similarity using adaptive inverse variance weighting.

        This is the production version that learns which components
        are most stable for this agent and weights them accordingly.

        Args:
            other: Another TrajectorySignature to compare against
            update_history: Whether to update component history

        Returns:
            Dictionary with similarity score and component breakdown
        """
        component_scores = {}

        # Compute each component similarity
        if self.preferences.get("vector") and other.preferences.get("vector"):
            sim = self._cosine_similarity(
                self.preferences["vector"], other.preferences["vector"]
            )
            if sim is not None:
                component_scores["preferences"] = (sim + 1) / 2

        if self.beliefs.get("values") and other.beliefs.get("values"):
            sim = self._cosine_similarity(
                self.beliefs["values"], other.beliefs["values"]
            )
            if sim is not None:
                component_scores["beliefs"] = (sim + 1) / 2

        if self.attractor and other.attractor:
            c1 = self.attractor.get("center")
            c2 = other.attractor.get("center")
            if c1 and c2:
                dist = sum((a - b)**2 for a, b in zip(c1, c2)) ** 0.5
                component_scores["attractor"] = 2.71828 ** (-dist * 2)

        t1 = self.recovery.get("tau_estimate")
        t2 = other.recovery.get("tau_estimate")
        if t1 and t2 and t1 > 0 and t2 > 0:
            import math
            log_ratio = abs(math.log(t1 / t2))
            component_scores["recovery"] = math.exp(-log_ratio)

        v1 = self.relational.get("valence_tendency")
        v2 = other.relational.get("valence_tendency")
        if v1 is not None and v2 is not None:
            component_scores["relational"] = 1 - abs(v1 - v2) / 2

        # Update history if requested
        if update_history:
            for component, score in component_scores.items():
                if component not in self.component_history:
                    self.component_history[component] = []
                self.component_history[component].append(score)
                # Keep last 100 observations
                if len(self.component_history[component]) > 100:
                    self.component_history[component] = self.component_history[component][-100:]

        # Compute adaptive weights
        adaptive_weights = self.compute_adaptive_weights()

        # Compute weighted similarity
        if not component_scores:
            return {"similarity": 0.5, "components": {}, "weights": adaptive_weights}

        weighted_sum = 0.0
        total_weight = 0.0
        for component, score in component_scores.items():
            weight = adaptive_weights.get(component, 0.1)
            weighted_sum += score * weight
            total_weight += weight

        similarity = weighted_sum / total_weight if total_weight > 0 else 0.5

        return {
            "similarity": round(similarity, 4),
            "components": {k: round(v, 4) for k, v in component_scores.items()},
            "weights": {k: round(v, 4) for k, v in adaptive_weights.items()},
            "history_depth": {k: len(v) for k, v in self.component_history.items()},
        }

    def is_same_identity(self, other: 'TrajectorySignature', threshold: float = 0.8) -> bool:
        """
        Determine if two signatures represent the same identity.

        Args:
            other: Another TrajectorySignature
            threshold: Similarity threshold (default 0.8)

        Returns:
            True if similarity > threshold
        """
        return self.similarity(other) > threshold

    def detect_anomaly(self, historical: 'TrajectorySignature', threshold: float = 0.7) -> Dict[str, Any]:
        """
        Detect if current signature deviates significantly from historical.

        Args:
            historical: Previous trajectory signature to compare against
            threshold: Minimum similarity to be considered "normal"

        Returns:
            Dictionary with anomaly detection results
        """
        sim = self.similarity(historical)
        is_anomaly = sim < threshold

        return {
            "is_anomaly": is_anomaly,
            "similarity": round(sim, 4),
            "threshold": threshold,
            "deviation": round(1 - sim, 4),
        }

    def lineage_similarity(self) -> Optional[float]:
        """
        Compute similarity to genesis signature (Σ₀).

        This measures how much the agent has drifted from its original
        identity - the "boiling frog" detector for gradual identity shift.

        Returns:
            Similarity to genesis signature [0, 1], or None if no genesis
        """
        if self.genesis_signature is None:
            return None
        return self.similarity(self.genesis_signature)

    def detect_anomaly_two_tier(
        self,
        recent_signature: 'TrajectorySignature',
        coherence_threshold: float = 0.7,
        lineage_threshold: float = 0.6,
    ) -> Dict[str, Any]:
        """
        Two-tier anomaly detection as specified in paper Section 6.1.2.

        Tier 1 (Coherence): Compare to recent behavior (short-term)
        Tier 2 (Lineage): Compare to genesis signature (long-term)

        Args:
            recent_signature: Recent trajectory for coherence check
            coherence_threshold: Threshold for short-term coherence
            lineage_threshold: Threshold for long-term lineage drift

        Returns:
            Dictionary with two-tier anomaly results
        """
        # Tier 1: Coherence check (short-term)
        coherence_sim = self.similarity(recent_signature)
        coherence_ok = coherence_sim >= coherence_threshold

        # Tier 2: Lineage check (long-term drift from genesis)
        lineage_sim = self.lineage_similarity()
        if lineage_sim is not None:
            lineage_ok = lineage_sim >= lineage_threshold
        else:
            lineage_ok = True  # No genesis to compare against
            lineage_sim = 1.0

        # Anomaly if either tier fails
        is_anomaly = not (coherence_ok and lineage_ok)

        return {
            "is_anomaly": is_anomaly,
            "coherence": {
                "similarity": round(coherence_sim, 4),
                "threshold": coherence_threshold,
                "passed": coherence_ok,
            },
            "lineage": {
                "similarity": round(lineage_sim, 4) if lineage_sim else None,
                "threshold": lineage_threshold,
                "passed": lineage_ok,
                "has_genesis": self.genesis_signature is not None,
            },
            "tier_failed": None if not is_anomaly else (
                "coherence" if not coherence_ok else "lineage"
            ),
        }

    @property
    def identity_confidence(self) -> float:
        """
        Confidence in identity stability, as per paper Section 4.5.

        Formula: min(1.0, observation_count / 50) * stability_score

        Returns:
            Confidence score [0, 1] where 1 = high confidence
        """
        # Cold start factor: confidence grows with observations (saturates at 50)
        cold_start_factor = min(1.0, self.observation_count / 50)
        return cold_start_factor * self.get_stability_score()

    def get_stability_score(self) -> float:
        """
        Compute how stable/mature this signature is.

        Based on:
        - Number of observations
        - Confidence in beliefs
        - Number of recovery episodes

        Returns:
            Stability score in [0, 1]
        """
        factors = []

        # Observation count (saturates at 100)
        obs_factor = min(1.0, self.observation_count / 100)
        factors.append(obs_factor)

        # Belief confidence
        if self.beliefs.get("avg_confidence"):
            factors.append(self.beliefs["avg_confidence"])

        # Recovery confidence
        if self.recovery.get("confidence"):
            factors.append(self.recovery["confidence"])

        # Preference learning
        if self.preferences.get("n_learned"):
            pref_factor = min(1.0, self.preferences["n_learned"] / 5)
            factors.append(pref_factor)

        if not factors:
            return 0.0

        return sum(factors) / len(factors)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "preferences": self.preferences,
            "beliefs": self.beliefs,
            "attractor": self.attractor,
            "recovery": self.recovery,
            "relational": self.relational,
            "computed_at": self.computed_at.isoformat(),
            "observation_count": self.observation_count,
            "stability_score": round(self.get_stability_score(), 3),
        }

    def summary(self) -> Dict[str, Any]:
        """Get a compact summary of the signature."""
        lineage_sim = self.lineage_similarity()
        return {
            "identity_confidence": round(self.identity_confidence, 3),
            "stability_score": round(self.get_stability_score(), 3),
            "observation_count": self.observation_count,
            "preferences_learned": self.preferences.get("n_learned", 0),
            "belief_confidence": self.beliefs.get("avg_confidence", 0),
            "attractor_defined": self.attractor is not None,
            "recovery_tau": self.recovery.get("tau_estimate"),
            "relationships": self.relational.get("n_relationships", 0),
            "lineage_similarity": round(lineage_sim, 3) if lineage_sim else None,
            "has_genesis": self.genesis_signature is not None,
            "computed_at": self.computed_at.isoformat(),
        }


def compute_trajectory_signature(
    growth_system: Optional['GrowthSystem'] = None,
    self_model: Optional['SelfModel'] = None,
    anima_history: Optional['AnimaHistory'] = None,
) -> TrajectorySignature:
    """
    Compute trajectory signature from available data sources.

    This function aggregates data from multiple systems to compute Σ.
    Each component is optional - the signature will include whatever
    data is available.

    Args:
        growth_system: GrowthSystem instance (for Π, Δ)
        self_model: SelfModel instance (for Β, Ρ)
        anima_history: AnimaHistory instance (for Α)

    Returns:
        TrajectorySignature Σ
    """
    # Extract components from each system

    # Π: Preference Profile
    preferences = {}
    if growth_system:
        try:
            preferences = growth_system.get_preference_vector()
        except Exception as e:
            print(f"[Trajectory] Could not get preferences: {e}", file=sys.stderr)

    # Β: Belief Signature
    beliefs = {}
    if self_model:
        try:
            beliefs = self_model.get_belief_signature()
        except Exception as e:
            print(f"[Trajectory] Could not get beliefs: {e}", file=sys.stderr)

    # Α: Attractor Basin
    attractor = None
    observation_count = 0
    if anima_history:
        try:
            attractor = anima_history.get_attractor_basin()
            if attractor:
                observation_count = attractor.get("n_observations", 0)
        except Exception as e:
            print(f"[Trajectory] Could not get attractor: {e}", file=sys.stderr)

    # Ρ: Recovery Profile
    recovery = {}
    if self_model:
        try:
            recovery = self_model.get_recovery_profile()
        except Exception as e:
            print(f"[Trajectory] Could not get recovery: {e}", file=sys.stderr)

    # Δ: Relational Disposition
    relational = {}
    if growth_system:
        try:
            relational = growth_system.get_relational_disposition()
        except Exception as e:
            print(f"[Trajectory] Could not get relational: {e}", file=sys.stderr)

    return TrajectorySignature(
        preferences=preferences,
        beliefs=beliefs,
        attractor=attractor,
        recovery=recovery,
        relational=relational,
        observation_count=observation_count,
    )


def compare_signatures(sig1: TrajectorySignature, sig2: TrajectorySignature) -> Dict[str, Any]:
    """
    Compare two trajectory signatures in detail.

    Returns per-component similarity breakdown.
    """
    overall = sig1.similarity(sig2)

    # Per-component breakdown
    components = {}

    # Preferences
    if sig1.preferences.get("vector") and sig2.preferences.get("vector"):
        v1, v2 = sig1.preferences["vector"], sig2.preferences["vector"]
        sim = sig1._cosine_similarity(v1, v2)
        if sim:
            components["preferences"] = round((sim + 1) / 2, 4)

    # Beliefs
    if sig1.beliefs.get("values") and sig2.beliefs.get("values"):
        v1, v2 = sig1.beliefs["values"], sig2.beliefs["values"]
        sim = sig1._cosine_similarity(v1, v2)
        if sim:
            components["beliefs"] = round((sim + 1) / 2, 4)

    # Attractor
    if sig1.attractor and sig2.attractor:
        c1 = sig1.attractor.get("center")
        c2 = sig2.attractor.get("center")
        if c1 and c2:
            dist = sum((a - b)**2 for a, b in zip(c1, c2)) ** 0.5
            components["attractor"] = round(2.71828 ** (-dist * 2), 4)

    # Recovery
    t1 = sig1.recovery.get("tau_estimate")
    t2 = sig2.recovery.get("tau_estimate")
    if t1 and t2 and t1 > 0 and t2 > 0:
        import math
        log_ratio = abs(math.log(t1 / t2))
        components["recovery"] = round(math.exp(-log_ratio), 4)

    # Relational
    v1 = sig1.relational.get("valence_tendency")
    v2 = sig2.relational.get("valence_tendency")
    if v1 is not None and v2 is not None:
        components["relational"] = round(1 - abs(v1 - v2) / 2, 4)

    return {
        "overall_similarity": round(overall, 4),
        "components": components,
        "is_same_identity": overall > 0.8,
    }
