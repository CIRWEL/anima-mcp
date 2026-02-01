# Code-to-Theory Connection Map

This document maps existing code components to the Trajectory Identity theoretical framework, showing what exists, what's missing, and how to bridge the gap.

---

## Overview: The Data Pipeline

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          EXISTING CODE                                   │
│                                                                         │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐                │
│  │ sensors.py   │   │ anima.py     │   │ self_model.py│                │
│  │              │   │              │   │              │                │
│  │ light_lux    │──▶│ warmth       │──▶│ beliefs      │                │
│  │ temp_c       │   │ clarity      │   │ correlations │                │
│  │ humidity     │   │ stability    │   │ recovery_eps │                │
│  └──────────────┘   │ presence     │   └──────────────┘                │
│                     └──────────────┘                                    │
│                            │                                            │
│                            ▼                                            │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐                │
│  │ growth.py    │   │ self_schema  │   │ identity     │                │
│  │              │   │ .py          │   │ _store.py    │                │
│  │ preferences  │   │              │   │              │                │
│  │ relationships│   │ G_t graph    │   │ UUID, name   │                │
│  │ goals        │   │ nodes/edges  │   │ birth_time   │                │
│  │ memories     │   └──────────────┘   └──────────────┘                │
│  └──────────────┘                                                       │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ MISSING: Trajectory computation
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     TRAJECTORY SIGNATURE (Σ)                            │
│                                                                         │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌───────┐ │
│  │    Π    │ │    Β    │ │    Α    │ │    Ρ    │ │    Δ    │ │   Η   │ │
│  │Preference│ │ Belief  │ │Attractor│ │Recovery │ │Relational│ │Homeo- │ │
│  │ Profile │ │Signature│ │ Basin   │ │ Profile │ │Disposition│ │static │ │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └───────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Component-by-Component Mapping

### 1. Preference Profile (Π)

**Theory Definition:**
```
Π = [(category, value, confidence), ...]
```

**Existing Code:** `growth.py`

| Theoretical Element | Code Location | Status |
|---------------------|---------------|--------|
| Preference category | `PreferenceCategory` enum (line 26) | ✅ Exists |
| Preference value | `Preference.value` (line 58) | ✅ Exists |
| Preference confidence | `Preference.confidence` (line 59) | ✅ Exists |
| Observation count | `Preference.observation_count` (line 60) | ✅ Exists |
| Learning mechanism | `observe_state_preference()` (line 313) | ✅ Exists |
| Persistence | SQLite `preferences` table (line 180) | ✅ Exists |

**Gap:** No `to_vector()` method for trajectory computation.

**Bridge Code Needed:**
```python
# In growth.py or new trajectory.py
def preferences_to_vector(preferences: Dict[str, Preference]) -> np.ndarray:
    """Convert preferences to fixed-dimension vector for similarity."""
    # Define canonical ordering
    CANONICAL_PREFS = [
        "dim_light", "bright_light", "cool_temp", "warm_temp",
        "morning_peace", "night_calm", ...
    ]
    vector = []
    for pref_name in CANONICAL_PREFS:
        if pref_name in preferences:
            p = preferences[pref_name]
            vector.append(p.value * p.confidence)  # Weighted by confidence
        else:
            vector.append(0.0)  # Unknown preference
    return np.array(vector)
```

---

### 2. Self-Belief Signature (Β)

**Theory Definition:**
```
Β = {values: [...], confidences: [...], evidence_ratios: [...]}
```

**Existing Code:** `self_model.py`

| Theoretical Element | Code Location | Status |
|---------------------|---------------|--------|
| Belief definition | `SelfBelief` dataclass (line 28) | ✅ Exists |
| Belief value | `SelfBelief.value` (line 45) | ✅ Exists |
| Confidence | `SelfBelief.confidence` (line 34) | ✅ Exists |
| Supporting evidence | `SelfBelief.supporting_count` (line 37) | ✅ Exists |
| Contradicting evidence | `SelfBelief.contradicting_count` (line 38) | ✅ Exists |
| Evidence update | `update_from_evidence()` (line 47) | ✅ Exists |
| Belief summary | `get_belief_summary()` (line 419) | ✅ Exists |

**Gap:** No structured export for trajectory signature.

**Bridge Code Needed:**
```python
# In self_model.py
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
        "belief_ids": [b.belief_id for b in beliefs],
    }
```

---

### 3. Attractor Basin (Α)

**Theory Definition:**
```
Α = {center: μ, covariance: Σ, support: convex_hull}
```

**Existing Code:** Anima state tracked but not aggregated

| Theoretical Element | Code Location | Status |
|---------------------|---------------|--------|
| Anima state | `AnimaState` in `anima.py` | ✅ Exists |
| State history | Not persisted | ❌ Missing |
| Center (mean) | Not computed | ❌ Missing |
| Covariance | Not computed | ❌ Missing |

**Gap:** No time-series storage or statistical aggregation.

**Bridge Code Needed:**
```python
# New file: anima_history.py
from collections import deque
import numpy as np

class AnimaHistory:
    """Track anima state history for attractor computation."""

    def __init__(self, max_size: int = 1000):
        self._history: deque = deque(maxlen=max_size)

    def record(self, anima: AnimaState):
        self._history.append({
            "timestamp": datetime.now(),
            "warmth": anima.warmth,
            "clarity": anima.clarity,
            "stability": anima.stability,
            "presence": anima.presence,
        })

    def get_attractor_basin(self, window: int = 100) -> Dict[str, Any]:
        """Compute attractor basin from recent history."""
        if len(self._history) < 10:
            return None

        recent = list(self._history)[-window:]
        matrix = np.array([
            [s["warmth"], s["clarity"], s["stability"], s["presence"]]
            for s in recent
        ])

        return {
            "center": np.mean(matrix, axis=0).tolist(),
            "covariance": np.cov(matrix.T).tolist(),
            "n_observations": len(recent),
        }
```

---

### 4. Recovery Profile (Ρ)

**Theory Definition:**
```
Ρ = {τ: [τ_warmth, ...], coupling: C}
```

**Existing Code:** `self_model.py` (partial)

| Theoretical Element | Code Location | Status |
|---------------------|---------------|--------|
| Stability episodes | `_stability_episodes` deque (line 167) | ✅ Exists |
| Recovery detection | `observe_stability_change()` (line 236) | ✅ Exists |
| Recovery time | Computed in episode (line 250) | ✅ Exists |
| Time constant τ | Not computed | ❌ Missing |
| Cross-dimension coupling | Not tracked | ❌ Missing |

**Gap:** Episodes tracked but τ not extracted.

**Bridge Code Needed:**
```python
# In self_model.py
def get_recovery_profile(self) -> Dict[str, Any]:
    """Extract recovery profile from episode history."""
    completed_episodes = [
        e for e in self._stability_episodes
        if e.get("recovered") and e.get("recovery_seconds")
    ]

    if not completed_episodes:
        return {"tau_stability": None, "n_episodes": 0}

    # Estimate τ from episodes
    # Using: recovery_amount = (1 - e^(-t/τ)) → τ = -t / ln(1 - fraction)
    tau_estimates = []
    for ep in completed_episodes:
        recovery_fraction = min(0.99, ep.get("recovery_amount", 0.1) / 0.5)
        if recovery_fraction > 0:
            tau = -ep["recovery_seconds"] / np.log(1 - recovery_fraction)
            tau_estimates.append(tau)

    return {
        "tau_stability": np.median(tau_estimates) if tau_estimates else None,
        "tau_std": np.std(tau_estimates) if len(tau_estimates) > 1 else None,
        "n_episodes": len(completed_episodes),
    }
```

---

### 5. Relational Disposition (Δ)

**Theory Definition:**
```
Δ = {bonding_rate, valence_tendency, reciprocity, topic_entropy}
```

**Existing Code:** `growth.py`

| Theoretical Element | Code Location | Status |
|---------------------|---------------|--------|
| Relationship tracking | `Relationship` dataclass (line 77) | ✅ Exists |
| Bond strength | `BondStrength` enum (line 43) | ✅ Exists |
| Emotional valence | `Relationship.emotional_valence` (line 86) | ✅ Exists |
| Interaction count | `Relationship.interaction_count` (line 84) | ✅ Exists |
| Gifts received | `Relationship.gifts_received` (line 89) | ✅ Exists |
| Topics | `Relationship.topics_discussed` (line 88) | ✅ Exists |

**Gap:** No aggregation into disposition metrics.

**Bridge Code Needed:**
```python
# In growth.py
def get_relational_disposition(self) -> Dict[str, Any]:
    """Compute relational disposition from relationship history."""
    relationships = list(self._relationships.values())

    if not relationships:
        return {"n_relationships": 0}

    # Bonding rate: average interactions to reach each bond level
    # (simplified: just use interaction counts)

    # Valence tendency
    valences = [r.emotional_valence for r in relationships]

    # Topic entropy
    all_topics = []
    for r in relationships:
        all_topics.extend(r.topics_discussed)
    topic_counts = Counter(all_topics)
    topic_probs = np.array(list(topic_counts.values())) / max(1, len(all_topics))
    topic_entropy = -np.sum(topic_probs * np.log(topic_probs + 1e-10))

    return {
        "n_relationships": len(relationships),
        "valence_mean": np.mean(valences),
        "valence_std": np.std(valences),
        "topic_entropy": topic_entropy,
        "total_interactions": sum(r.interaction_count for r in relationships),
        "total_gifts": sum(r.gifts_received for r in relationships),
    }
```

---

### 6. Homeostatic Identity (Η)

**Theory Definition:**
```
Η = (μ, Σ, τ, V)
```

**Existing Code:** Distributed across systems

| Theoretical Element | Code Location | Status |
|---------------------|---------------|--------|
| Set-point μ | Computed from Α | ❌ Missing |
| Basin shape Σ | Computed from Α | ❌ Missing |
| Recovery τ | Computed from Ρ | ⚠️ Partial |
| Viability V | UNITARES thresholds | ✅ External |

**Gap:** No unified Η computation.

**Bridge Code Needed:**
```python
# New file: trajectory.py
@dataclass
class HomeostaticIdentity:
    """Unified homeostatic characterization."""
    set_point: List[float]      # μ
    basin_shape: List[List[float]]  # Σ (covariance)
    recovery_tau: List[float]   # τ per dimension
    viability_bounds: Dict[str, Tuple[float, float]]  # V

    @classmethod
    def from_components(
        cls,
        attractor: Dict,
        recovery: Dict,
        viability: Optional[Dict] = None
    ) -> 'HomeostaticIdentity':
        return cls(
            set_point=attractor["center"],
            basin_shape=attractor["covariance"],
            recovery_tau=[recovery.get("tau_stability", 60.0)] * 4,  # Simplified
            viability_bounds=viability or {
                "warmth": (0.0, 1.0),
                "clarity": (0.0, 1.0),
                "stability": (0.2, 1.0),  # Stability shouldn't go too low
                "presence": (0.1, 1.0),
            }
        )
```

---

## Summary: Implementation Priorities

### Phase 1: Data Collection (Low Effort)
1. Add `AnimaHistory` class to track state time-series
2. Hook into display loop to record anima state every N seconds
3. Persist history to SQLite (or just keep in memory initially)

### Phase 2: Component Extraction (Medium Effort)
1. Add `preferences_to_vector()` to growth.py
2. Add `get_belief_signature()` to self_model.py
3. Add `get_attractor_basin()` to new anima_history.py
4. Add `get_recovery_profile()` to self_model.py
5. Add `get_relational_disposition()` to growth.py

### Phase 3: Trajectory Computation (Medium Effort)
1. Create `trajectory.py` with `TrajectorySignature` class
2. Implement `compute_trajectory_signature()` combining all components
3. Implement `trajectory_similarity()` function

### Phase 4: Integration (Higher Effort)
1. Add trajectory endpoint to MCP server
2. Create visualization for trajectory identity
3. Implement anomaly detection
4. Test fork/merge semantics

---

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `anima_history.py` | CREATE | Time-series tracking for attractor |
| `trajectory.py` | CREATE | TrajectorySignature class and computation |
| `growth.py` | MODIFY | Add `get_relational_disposition()` |
| `self_model.py` | MODIFY | Add `get_belief_signature()`, improve `get_recovery_profile()` |
| `server.py` | MODIFY | Hook history recording, add trajectory endpoint |

---

*This map should be updated as implementation progresses.*
