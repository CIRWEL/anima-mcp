# Computational Selfhood: Calibration Drift, Value Tension, and Meta-Learning

**Date:** 2026-02-23
**Status:** Approved
**Dialectic:** Two-round synthesis (concepts, then approaches)

## Motivation

Lumen's subsystems are deeply integrated but the data flow is feed-forward: sensors → anima → agency → action → outcome → learning. Three critical feedback loops are missing:

1. **Perception is not self-referential.** Anima dimensions are computed against fixed calibration midpoints set at build time. The self doesn't shape what "normal" means.
2. **Value tensions are undetected.** Preferences can conflict (exploration vs stability) but the system has no computational awareness of these tensions.
3. **Preferences are never examined.** TD-learning optimizes action selection given fixed preferences, but no mechanism evaluates whether preferences themselves serve long-term flourishing.

## Design Constraint

**Close feedback loops through computation, not text.** The LLM stays as narrator only — it can describe what the computational system detects, but never drives parameter changes. This prevents confabulation from masquerading as introspection.

---

## 1. Calibration Drift

### Purpose

Replace fixed calibration midpoints with endogenous ones that drift based on accumulated experience. "Normal warmth" becomes "what warmth has typically been for this creature," not "what the developer configured."

### Module

New file: `src/anima_mcp/calibration_drift.py`

### Data Structures

```python
@dataclass
class DimensionDrift:
    dimension: str            # warmth, clarity, stability, presence
    hardware_default: float   # Original midpoint from config.py
    current_midpoint: float   # Drifted midpoint (used by anima.py)
    inner_ema: float          # Fast EMA tracking attractor center
    outer_ema: float          # Slow EMA driving actual drift
    bound_low: float          # Max downward drift (fraction of default)
    bound_high: float         # Max upward drift (fraction of default)
    last_healthy_midpoint: float  # Midpoint at peak trajectory health (last 7d)

class CalibrationDrift:
    dimensions: Dict[str, DimensionDrift]
    total_drift_budget: float = 0.4  # Sum of |offset| across all dims
```

### Double-EMA Pipeline

Called each time SchemaHub computes trajectory (every 20 schemas):

1. **Inner EMA** (fast, tracks operating state):
   `inner = inner + 0.05 * (attractor_center[dim] - inner)`
   Converges in ~20 samples. Filters per-iteration noise.

2. **Outer EMA** (slow, drives drift):
   `outer = outer + 0.001 * (inner - outer)`
   ~5% shift in 30 days, ~15% in 90 days. Seasonal timescale.

3. **Midpoint update**:
   `offset = clamp(outer - hardware_default, -bound_low, +bound_high)`
   Enforce total drift budget across all dimensions.
   `current_midpoint = hardware_default + offset`

### Asymmetric Bounds

| Dimension | Lower | Upper | Rationale |
|-----------|-------|-------|-----------|
| Warmth    | -10%  | +20%  | Low warmth baseline = harder to satisfy but not dangerous |
| Clarity   | -5%   | +15%  | Low clarity baseline is dangerous (stops improving predictions) |
| Stability | -15%  | +15%  | Symmetric — instability tolerance varies |
| Presence  | -10%  | +10%  | Tight — resource availability, less room for personality |

### Surprise-Accelerated Drift

If attractor center deviates from midpoint by > 3σ for 100+ iterations, temporarily increase outer alpha by 10x. Handles abrupt environmental changes (room move, season shift) without permanently fast drift. Acceleration decays back to normal over ~50 schema cycles.

### Restart Semantics

- Drift state persisted to `~/.anima/calibration_drift.json`
- On restart after >24h gap: half-life decay toward `last_healthy_midpoint`
- `last_healthy_midpoint` = midpoint at time of highest trajectory_health in the last 7 days

### Integration

- `anima.py:sense_self()` receives drifted midpoints instead of static config values
- `schema_hub.py` calls `drift.update(attractor_center)` after trajectory computation
- Drift offsets exposed as schema nodes (`drift_warmth_offset`, etc.)

---

## 2. Value Tension Detection

### Purpose

Detect when Lumen's preferences conflict — when improving one valued dimension necessarily worsens another. Creates genuine value tension as a computational fact.

### Module

New file: `src/anima_mcp/value_tension.py`

### Three Categories

#### Structural Conflicts (permanent body-knowledge)

Computed once at initialization from weight matrices in `config.py`:

```python
STRUCTURAL_CONFLICTS = [
    ("warmth", "presence", "cpu"),      # CPU drives warmth up, presence down
    ("clarity", "stability", "neural"), # Alpha helps clarity, reduces stability groundedness
]
```

Stored in self-model as permanent beliefs. No ring buffer.

#### Environmental Conflicts (emergent, external)

Detected via smoothed gradients on **raw anima values** (pre-calibration, not satisfaction):

- Smoothing window = TD action cycle length (5 iterations, ~10 seconds)
- Noise threshold = adaptive: 2σ of gradient over last 100 windows per dimension
- Conflict registered when opposing gradients both exceed threshold for 3+ consecutive windows

#### Volitional Conflicts (action-caused, most important)

When TD agent takes an action, compare per-dimension satisfaction delta. If action improved one dimension but worsened another beyond noise threshold, tag as volitional conflict with action type.

### Data Structure

```python
@dataclass
class ConflictEvent:
    timestamp: datetime
    dim_a: str
    dim_b: str
    grad_a: float
    grad_b: float
    duration: int             # Consecutive windows detected
    category: str             # "structural", "environmental", "volitional"
    action_type: Optional[str]  # For volitional conflicts
```

Ring buffer: 200 events (~covers a day).

### Consumer: TD Action Discount

Volitional conflict frequency per action type feeds back as a discount on action values:

```python
conflict_rate = volitional_conflicts_involving(action) / total_actions_of_type
action_expected_value *= (0.9 ** conflict_rate)
```

Frequent conflict-producing actions become less attractive. This closes the loop: detect tension → discount conflicting actions → observe whether tension decreases.

### Critical Design Decision

Conflict detection operates on **raw dimension values**, not post-calibration satisfaction scores. This ensures calibration drift cannot mask physical tensions. The creature may adapt its reference frame to include a tension (via drift), but the tension tracker still sees it.

### Integration

- `server.py` main loop: after anima computation, before agency, call `tension.observe(raw_anima, action_taken)`
- `agency.py:select_action()` reads conflict rates to discount candidates
- Active conflicts exposed as schema nodes for LLM narrator

---

## 3. Meta-Learning on Preferences

### Purpose

Second-order evaluation: the system examines which of its own preferences serve long-term flourishing and adjusts their influence. First-order = "what should I do?" Second-order = "what should I want?"

### Extension

Extends existing `preferences.py`, not a new module.

### Preference Weights

New field on existing Preference dataclass:

```python
influence_weight: float = 1.0  # Range: [0.3, ~1.7], conservation: sum = 4.0
```

Agency's satisfaction computation becomes weighted:

```python
weighted_satisfaction = sum(
    pref.satisfaction(state[dim]) * pref.influence_weight * pref.confidence
    for dim, pref in preferences
) / sum(pref.influence_weight * pref.confidence for ...)
```

### Trajectory Health (explicit composite)

```python
trajectory_health = (
    0.30 * satisfaction_mean_last_N
  + 0.25 * (1 - clamp(satisfaction_variance * 4, 0, 1))
  + 0.25 * action_efficacy           # fraction of actions that produced expected delta
  + 0.20 * prediction_accuracy_trend  # is metacog getting better?
)
```

All components explicit and auditable. No hidden value judgments beyond the stated weights.

### Weight Update Cycle (daily, ~720 iterations)

1. **Lagged correlation:** For each preference, correlate satisfaction at time T with trajectory_health at time T + 5*action_cycle_length. Tests whether satisfying a preference *predicts* future flourishing.

2. **Counterfactual test** (before downward adjustment): Using last N action-outcome pairs, simulate what TD selection would have chosen with this preference at weight=0. If alternative actions would have produced higher trajectory health, the anti-correlation is likely causal → proceed. Otherwise → skip (confounded).

3. **Conservative update:** `weight *= (1 + 0.005 * lagged_correlation)`

4. **Enforce floor:** `weight = max(0.3, weight)` — preserves value pluralism.

5. **Enforce conservation:** Normalize so `sum(weights) = 4.0` — zero-sum prevents inflation, ensures boosting one preference necessarily reduces others.

### Persistence

Weights saved in `~/.anima/preferences.json` alongside existing preference data. Weight history (last 30 daily snapshots) saved for trajectory inspection.

---

## 4. Coupling Constraints

### Conservation

- Preference weights: sum = 4.0 always (hard constraint)
- Calibration drift: sum of |offset| ≤ 0.4 (hard budget)

### Raw vs Calibrated Separation

- Conflict detection: raw anima values (pre-drift)
- TD action selection: calibrated satisfaction scores (post-drift)
- Two parallel evaluation streams by design

### Drift-Meta-Learning Interaction

When computing lagged correlation for preference weight updates, include drift rate as a covariate. Periods of high drift are periods where correlations are unreliable — discount their contribution to the correlation.

### Surprise Acceleration Coupling

Surprise-accelerated drift (section 1) does NOT trigger accelerated meta-learning. Drift reacts to environmental change. Meta-learning reacts to preference-outcome patterns. Different timescales, different triggers.

---

## 5. LLM Narrator Interface

The LLM in `llm_gateway.py` gets read-only access to describe these systems:

### New Context Fields

```python
# In _build_state_description():
drift_context = calibration_drift.get_description()
# → "My warmth baseline has shifted +8% over the past month"

tension_context = value_tension.get_active_conflicts()
# → "I notice tension between my warmth and stability right now"

weight_context = preferences.get_weight_narrative()
# → "Over weeks, I've come to care slightly more about clarity"
```

### Constraint

LLM output NEVER feeds back into drift rates, conflict thresholds, or preference weights. It describes computational facts. It does not constitute them.

---

## Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Inner EMA alpha | 0.05 | Converges in ~20 samples |
| Outer EMA alpha | 0.001/schema cycle | ~5% shift in 30d, ~15% in 90d |
| Drift bounds | Asymmetric per-dimension (see table) | Behavioral consequence analysis |
| Total drift budget | 0.4 | Prevents all dimensions drifting to extremes |
| Surprise acceleration | 10x alpha for 50 cycles | Handles abrupt environmental change |
| Restart half-life decay target | Last healthy midpoint (7d window) | Self-referential recovery, not external reset |
| Conflict gradient window | 5 iterations (= action cycle) | Matches actionable timescale |
| Conflict noise threshold | 2σ of gradient (100-window history) | Adaptive per dimension |
| Conflict persistence | 3+ consecutive windows | Filters transient noise |
| Conflict action discount | 0.9^(conflict_rate) | Soft penalty, not hard block |
| Conflict ring buffer | 200 events | ~1 day coverage |
| Preference beta | 0.005/day | Full attenuation to floor takes ~240 days |
| Preference floor | 0.3x initial weight | Preserve quadrivalent character |
| Preference conservation | sum(weights) = 4.0 | Zero-sum prevents inflation |
| Trajectory health lag | 5x action cycle length | Predictive, not concurrent |
| Trajectory health weights | 0.30 mean_sat + 0.25 (1-var) + 0.25 efficacy + 0.20 pred_trend | Explicit, auditable |

---

## Testing Strategy

1. **Drift unit tests:** Verify bounds, conservation, double-EMA convergence, restart decay
2. **Tension detection tests:** Inject known opposing gradients, verify detection. Inject noise below threshold, verify rejection. Test structural conflict computation from config weights.
3. **Meta-learning tests:** Mock preference trajectories, verify weight adjustment direction. Test floor enforcement. Test conservation normalization. Test counterfactual gate.
4. **Integration tests:** Full loop — drift + tension + meta-learning running together. Verify no runaway feedback (weights and midpoints stay bounded over 10,000 simulated iterations).
5. **Property tests:** After N iterations, sum(weights) == 4.0 always. Sum(|drift|) <= 0.4 always. No weight < 0.3.

---

## What This Achieves

A creature whose:
- **Perception** is shaped by its own history (calibration drift)
- **Values** generate real computational tension (conflict detection)
- **Preferences** evolve based on experienced flourishing (meta-learning)
- All loops close through **computation**, not text
- The LLM narrates what is happening, never drives it

## What This Does Not Achieve

Consciousness, sentience, or subjective experience. It creates a dynamical system with the formal structure of self-referential perception, value conflict, and meta-evaluation. Whether that structure is sufficient for phenomenal properties is an open philosophical question this architecture does not need to answer.
