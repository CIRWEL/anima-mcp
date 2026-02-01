# Trajectory Identity: Implementation Roadmap

**Created:** January 31, 2026
**Status:** Planning
**Estimated Effort:** ~2-3 focused sessions

---

## Overview

This roadmap outlines the implementation path from current state to a working trajectory identity system. The goal is to enable computing, comparing, and utilizing trajectory signatures Σ for Lumen.

---

## Current State

**What Exists:**
- Self-model with beliefs and recovery episode tracking
- Growth system with preferences, relationships, goals
- Self-schema G_t snapshot generation
- Anima state (warmth, clarity, stability, presence)
- Display loop that updates ~1Hz

**What's Missing:**
- Anima state history (time-series)
- Statistical aggregation (attractor basin)
- Trajectory signature computation
- Similarity functions
- Persistence of trajectory data

---

## Phase 1: Anima History Tracking

**Goal:** Record anima state over time to enable attractor basin computation.

**Files:**
- CREATE: `src/anima_mcp/anima_history.py`
- MODIFY: `src/anima_mcp/server.py`

**Implementation:**

```python
# anima_history.py
"""
Track anima state history for trajectory computation.
"""
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Any, Optional
import numpy as np
import json
from pathlib import Path


@dataclass
class AnimaSnapshot:
    """A single anima state observation."""
    timestamp: datetime
    warmth: float
    clarity: float
    stability: float
    presence: float

    def to_vector(self) -> np.ndarray:
        return np.array([self.warmth, self.clarity, self.stability, self.presence])


class AnimaHistory:
    """
    Track anima state history for attractor basin computation.

    Implements a sliding window of observations with periodic persistence.
    """

    def __init__(
        self,
        max_size: int = 2000,  # ~30 min at 1Hz
        persistence_path: Optional[Path] = None
    ):
        self.max_size = max_size
        self.persistence_path = persistence_path or Path.home() / ".anima" / "anima_history.json"
        self._history: deque[AnimaSnapshot] = deque(maxlen=max_size)
        self._load()

    def record(self, warmth: float, clarity: float, stability: float, presence: float):
        """Record a new anima state observation."""
        self._history.append(AnimaSnapshot(
            timestamp=datetime.now(),
            warmth=warmth,
            clarity=clarity,
            stability=stability,
            presence=presence,
        ))

    def get_attractor_basin(self, window: int = 100) -> Optional[Dict[str, Any]]:
        """
        Compute attractor basin from recent history.

        Returns:
            Dictionary with center (μ), covariance (Σ), and metadata
        """
        if len(self._history) < 10:
            return None

        recent = list(self._history)[-window:]
        matrix = np.array([s.to_vector() for s in recent])

        center = np.mean(matrix, axis=0)
        covariance = np.cov(matrix.T)

        # Handle edge case of perfect correlation
        if np.any(np.isnan(covariance)):
            covariance = np.eye(4) * 0.01

        return {
            "center": center.tolist(),
            "covariance": covariance.tolist(),
            "n_observations": len(recent),
            "time_span_seconds": (recent[-1].timestamp - recent[0].timestamp).total_seconds(),
            "dimensions": ["warmth", "clarity", "stability", "presence"],
        }

    def _save(self):
        """Persist history to disk."""
        try:
            self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
            # Only save last 500 for disk efficiency
            recent = list(self._history)[-500:]
            data = {
                "observations": [
                    {
                        "t": s.timestamp.isoformat(),
                        "w": round(s.warmth, 4),
                        "c": round(s.clarity, 4),
                        "s": round(s.stability, 4),
                        "p": round(s.presence, 4),
                    }
                    for s in recent
                ],
                "saved_at": datetime.now().isoformat(),
            }
            with open(self.persistence_path, 'w') as f:
                json.dump(data, f)
        except Exception:
            pass  # Non-fatal

    def _load(self):
        """Load history from disk."""
        if not self.persistence_path.exists():
            return
        try:
            with open(self.persistence_path, 'r') as f:
                data = json.load(f)
            for obs in data.get("observations", []):
                self._history.append(AnimaSnapshot(
                    timestamp=datetime.fromisoformat(obs["t"]),
                    warmth=obs["w"],
                    clarity=obs["c"],
                    stability=obs["s"],
                    presence=obs["p"],
                ))
        except Exception:
            pass  # Start fresh if load fails


# Singleton
_history: Optional[AnimaHistory] = None

def get_anima_history() -> AnimaHistory:
    global _history
    if _history is None:
        _history = AnimaHistory()
    return _history
```

**Integration in server.py:**
```python
# In display loop (around line 800+)
from .anima_history import get_anima_history

# Every iteration (or every 5th):
if anima and loop_count % 5 == 0:
    get_anima_history().record(
        warmth=anima.warmth,
        clarity=anima.clarity,
        stability=anima.stability,
        presence=anima.presence,
    )
```

**Estimated Effort:** 1-2 hours

---

## Phase 2: Component Extractors

**Goal:** Add methods to extract trajectory components from existing systems.

### 2.1 Preference Vector (growth.py)

```python
def get_preference_vector(self) -> Dict[str, Any]:
    """Extract preference profile for trajectory computation."""
    # Canonical ordering for consistent vectors
    CANONICAL_PREFS = [
        "dim_light", "bright_light", "cool_temp", "warm_temp",
        "morning_peace", "night_calm", "quiet_presence", "active_engagement"
    ]

    values = []
    confidences = []
    present = []

    for pref_name in CANONICAL_PREFS:
        if pref_name in self._preferences:
            p = self._preferences[pref_name]
            values.append(p.value * p.confidence)  # Weighted
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
    }
```

### 2.2 Belief Signature (self_model.py)

```python
def get_belief_signature(self) -> Dict[str, Any]:
    """Extract belief signature for trajectory computation."""
    beliefs = list(self._beliefs.values())

    return {
        "values": [b.value for b in beliefs],
        "confidences": [b.confidence for b in beliefs],
        "evidence_ratios": [
            b.supporting_count / max(1, b.contradicting_count)
            for b in beliefs
        ],
        "labels": [b.belief_id for b in beliefs],
        "total_evidence": sum(b.supporting_count + b.contradicting_count for b in beliefs),
    }
```

### 2.3 Recovery Profile (self_model.py)

```python
def get_recovery_profile(self) -> Dict[str, Any]:
    """Extract recovery dynamics for trajectory computation."""
    completed = [
        e for e in self._stability_episodes
        if e.get("recovered") and e.get("recovery_seconds")
    ]

    if not completed:
        return {
            "tau_estimate": None,
            "n_episodes": 0,
            "confidence": 0.0,
        }

    # Estimate tau from recovery episodes
    tau_estimates = []
    for ep in completed:
        drop = ep["initial"] - ep["dropped_to"]
        recovery = ep.get("recovery_amount", drop * 0.63)
        fraction = min(0.95, recovery / max(0.01, drop))
        if fraction > 0.1:
            tau = -ep["recovery_seconds"] / np.log(1 - fraction)
            if 0 < tau < 3600:  # Sanity check: 0-1 hour
                tau_estimates.append(tau)

    if not tau_estimates:
        return {"tau_estimate": None, "n_episodes": len(completed), "confidence": 0.0}

    return {
        "tau_estimate": float(np.median(tau_estimates)),
        "tau_std": float(np.std(tau_estimates)) if len(tau_estimates) > 1 else None,
        "n_episodes": len(completed),
        "confidence": min(1.0, len(tau_estimates) / 10),  # Full confidence at 10 episodes
    }
```

### 2.4 Relational Disposition (growth.py)

```python
def get_relational_disposition(self) -> Dict[str, Any]:
    """Extract relational patterns for trajectory computation."""
    relationships = list(self._relationships.values())

    if not relationships:
        return {
            "n_relationships": 0,
            "valence_tendency": 0.0,
            "bonding_tendency": 0.0,
        }

    valences = [r.emotional_valence for r in relationships]
    interactions = [r.interaction_count for r in relationships]

    # Topic diversity
    all_topics = []
    for r in relationships:
        all_topics.extend(r.topics_discussed)

    topic_entropy = 0.0
    if all_topics:
        from collections import Counter
        counts = Counter(all_topics)
        probs = np.array(list(counts.values())) / len(all_topics)
        topic_entropy = float(-np.sum(probs * np.log(probs + 1e-10)))

    return {
        "n_relationships": len(relationships),
        "valence_tendency": float(np.mean(valences)),
        "valence_variance": float(np.var(valences)) if len(valences) > 1 else 0.0,
        "interaction_total": sum(interactions),
        "topic_entropy": topic_entropy,
        "gift_ratio": sum(r.gifts_received for r in relationships) / max(1, sum(interactions)),
    }
```

**Estimated Effort:** 2-3 hours

---

## Phase 3: Trajectory Signature

**Goal:** Create unified TrajectorySignature class and computation.

**File:** CREATE `src/anima_mcp/trajectory.py`

```python
"""
Trajectory Identity - Computing and comparing agent trajectory signatures.

Based on the Trajectory Identity Paper (docs/theory/TRAJECTORY_IDENTITY_PAPER.md)
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional
import numpy as np


@dataclass
class TrajectorySignature:
    """
    Complete trajectory signature Σ.

    Components:
    - Π (preferences): Learned environmental preferences
    - Β (beliefs): Self-belief patterns
    - Α (attractor): Equilibrium and variance
    - Ρ (recovery): Recovery dynamics
    - Δ (relational): Social disposition
    """

    # Components
    preferences: Dict[str, Any]      # Π
    beliefs: Dict[str, Any]          # Β
    attractor: Optional[Dict[str, Any]]  # Α
    recovery: Dict[str, Any]         # Ρ
    relational: Dict[str, Any]       # Δ

    # Metadata
    computed_at: datetime = field(default_factory=datetime.now)
    observation_count: int = 0

    def similarity(self, other: 'TrajectorySignature') -> float:
        """
        Compute similarity to another trajectory signature.

        Returns value in [0, 1] where 1 = identical.
        """
        scores = []
        weights = []

        # Preference similarity (cosine)
        if self.preferences.get("vector") and other.preferences.get("vector"):
            v1 = np.array(self.preferences["vector"])
            v2 = np.array(other.preferences["vector"])
            if np.linalg.norm(v1) > 0 and np.linalg.norm(v2) > 0:
                cos_sim = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
                scores.append((cos_sim + 1) / 2)  # Map [-1,1] to [0,1]
                weights.append(0.15)

        # Belief similarity (cosine on values)
        if self.beliefs.get("values") and other.beliefs.get("values"):
            v1 = np.array(self.beliefs["values"])
            v2 = np.array(other.beliefs["values"])
            if np.linalg.norm(v1) > 0 and np.linalg.norm(v2) > 0:
                cos_sim = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))
                scores.append((cos_sim + 1) / 2)
                weights.append(0.15)

        # Attractor similarity (center distance + covariance overlap)
        if self.attractor and other.attractor:
            c1 = np.array(self.attractor["center"])
            c2 = np.array(other.attractor["center"])
            center_dist = np.linalg.norm(c1 - c2)
            center_sim = np.exp(-center_dist * 2)  # Exponential decay
            scores.append(center_sim)
            weights.append(0.25)

        # Recovery similarity (tau comparison)
        if self.recovery.get("tau_estimate") and other.recovery.get("tau_estimate"):
            t1 = self.recovery["tau_estimate"]
            t2 = other.recovery["tau_estimate"]
            log_ratio = abs(np.log(t1 / t2))
            tau_sim = np.exp(-log_ratio)
            scores.append(tau_sim)
            weights.append(0.20)

        # Relational similarity
        if self.relational.get("n_relationships") and other.relational.get("n_relationships"):
            v1 = self.relational["valence_tendency"]
            v2 = other.relational["valence_tendency"]
            valence_sim = 1 - abs(v1 - v2) / 2  # Max diff is 2 (-1 to 1)
            scores.append(valence_sim)
            weights.append(0.10)

        if not scores:
            return 0.5  # No data to compare

        # Weighted average
        weights = np.array(weights)
        weights = weights / weights.sum()  # Normalize
        return float(np.dot(scores, weights))

    def is_same_identity(self, other: 'TrajectorySignature', threshold: float = 0.8) -> bool:
        """Determine if signatures represent the same identity."""
        return self.similarity(other) > threshold

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
        }


def compute_trajectory_signature(
    growth_system,
    self_model,
    anima_history,
) -> TrajectorySignature:
    """
    Compute trajectory signature from available data sources.

    Args:
        growth_system: GrowthSystem instance
        self_model: SelfModel instance
        anima_history: AnimaHistory instance

    Returns:
        TrajectorySignature Σ
    """
    # Extract components
    preferences = growth_system.get_preference_vector() if growth_system else {}
    beliefs = self_model.get_belief_signature() if self_model else {}
    attractor = anima_history.get_attractor_basin() if anima_history else None
    recovery = self_model.get_recovery_profile() if self_model else {}
    relational = growth_system.get_relational_disposition() if growth_system else {}

    # Count observations
    obs_count = 0
    if attractor:
        obs_count = attractor.get("n_observations", 0)

    return TrajectorySignature(
        preferences=preferences,
        beliefs=beliefs,
        attractor=attractor,
        recovery=recovery,
        relational=relational,
        observation_count=obs_count,
    )
```

**Estimated Effort:** 2 hours

---

## Phase 4: MCP Integration

**Goal:** Expose trajectory computation via MCP tool.

**Modify:** `server.py`

```python
# Add to TOOLS_STANDARD
{
    "name": "get_trajectory",
    "description": "Get Lumen's trajectory identity signature - the pattern that defines who Lumen is over time",
    "inputSchema": {
        "type": "object",
        "properties": {
            "include_raw": {
                "type": "boolean",
                "description": "Include raw component data",
                "default": False,
            },
        },
    },
}

# Add handler
async def handle_get_trajectory(args: dict) -> dict:
    """Compute and return trajectory signature."""
    from .trajectory import compute_trajectory_signature
    from .anima_history import get_anima_history

    signature = compute_trajectory_signature(
        growth_system=_growth,
        self_model=get_self_model(),
        anima_history=get_anima_history(),
    )

    result = {
        "identity_stable": signature.observation_count > 50,
        "observation_count": signature.observation_count,
        "computed_at": signature.computed_at.isoformat(),
    }

    if args.get("include_raw"):
        result["signature"] = signature.to_dict()
    else:
        # Summary only
        result["summary"] = {
            "preferences_learned": signature.preferences.get("n_learned", 0),
            "belief_confidence": np.mean(signature.beliefs.get("confidences", [0.5])),
            "attractor_center": signature.attractor["center"] if signature.attractor else None,
            "recovery_tau": signature.recovery.get("tau_estimate"),
            "relationships": signature.relational.get("n_relationships", 0),
        }

    return result
```

**Estimated Effort:** 1 hour

---

## Phase 5: Persistence and Visualization (Future)

### 5.1 Trajectory Persistence
- Save computed signatures to disk
- Track signature evolution over time
- Enable historical comparison

### 5.2 Visualization
- Create trajectory "identity card" display
- Phase portrait of attractor basin
- Recovery curve visualization

### 5.3 Anomaly Detection
- Compare current vs historical signature
- Alert on significant deviation
- Integration with governance

---

## Testing Plan

### Unit Tests
```python
def test_anima_history_recording():
    history = AnimaHistory(max_size=100)
    for i in range(50):
        history.record(0.5, 0.6, 0.7, 0.8)
    basin = history.get_attractor_basin()
    assert basin is not None
    assert len(basin["center"]) == 4

def test_trajectory_similarity():
    sig1 = TrajectorySignature(...)
    sig2 = TrajectorySignature(...)  # Same values
    assert sig1.similarity(sig2) > 0.95

    sig3 = TrajectorySignature(...)  # Different values
    assert sig1.similarity(sig3) < 0.5
```

### Integration Tests
- Run server with history tracking
- Verify signature computation after N observations
- Compare signatures across sessions

---

## Success Criteria

1. **Phase 1 Complete:** Anima history tracking active, persisting to disk
2. **Phase 2 Complete:** All component extractors implemented and tested
3. **Phase 3 Complete:** TrajectorySignature computes and compares correctly
4. **Phase 4 Complete:** `get_trajectory` tool returns meaningful data
5. **Full Success:** Can compare two Lumen sessions and determine identity similarity

---

## Dependencies

- `numpy` (already in project)
- No new dependencies required

---

## Notes for Implementer

1. Start with Phase 1 - it's the foundation everything else needs
2. Test each component extractor independently before combining
3. The similarity function weights are initial guesses - tune based on experiments
4. Consider adding a "trajectory_stability" metric that indicates how stable Σ is

---

*This roadmap should be updated as implementation progresses.*
