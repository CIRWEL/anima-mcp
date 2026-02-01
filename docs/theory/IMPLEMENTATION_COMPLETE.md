# Trajectory Identity: Implementation Complete

**Date:** January 31, 2026
**Status:** Phase 1-4 Complete

---

## What Was Built

### 1. AnimaHistory Class
**File:** `src/anima_mcp/anima_history.py`

Tracks anima state over time for trajectory computation:
- Records warmth, clarity, stability, presence snapshots
- Computes attractor basin (center, covariance, eigenvalues)
- Persists to `~/.anima/anima_history.json`
- Auto-saves every 100 records

```python
from anima_mcp.anima_history import get_anima_history

history = get_anima_history()
history.record(warmth=0.5, clarity=0.6, stability=0.7, presence=0.8)
basin = history.get_attractor_basin(window=100)
```

### 2. Component Extractors

**growth.py additions:**
- `get_preference_vector()` - Extracts Π (preference profile)
- `get_relational_disposition()` - Extracts Δ (relational patterns)

**self_model.py additions:**
- `get_belief_signature()` - Extracts Β (self-belief patterns)
- `get_recovery_profile()` - Extracts Ρ (recovery dynamics, τ estimation)

### 3. TrajectorySignature Class
**File:** `src/anima_mcp/trajectory.py`

The core trajectory identity framework:
- Combines all components into Σ = {Π, Β, Α, Ρ, Δ}
- `similarity(other)` - Computes identity similarity [0,1]
- `is_same_identity(other)` - Boolean identity check
- `detect_anomaly(historical)` - Anomaly detection
- `get_stability_score()` - Identity maturity assessment

```python
from anima_mcp.trajectory import compute_trajectory_signature

sig = compute_trajectory_signature(
    growth_system=growth,
    self_model=model,
    anima_history=history,
)

print(f"Stability: {sig.get_stability_score()}")
print(f"Summary: {sig.summary()}")
```

### 4. Server Integration

**Display loop integration:**
- Records anima history every 5 iterations (~10 seconds)
- Builds time-series for attractor basin computation

**MCP Tool:**
- `get_trajectory` - Returns trajectory signature
- Options: `include_raw`, `compare_to_historical`

---

## Files Created/Modified

| File | Action | Lines |
|------|--------|-------|
| `src/anima_mcp/anima_history.py` | **Created** | ~250 |
| `src/anima_mcp/trajectory.py` | **Created** | ~320 |
| `src/anima_mcp/growth.py` | Modified | +80 |
| `src/anima_mcp/self_model.py` | Modified | +90 |
| `src/anima_mcp/server.py` | Modified | +75 |

---

## How It Works

```
Every ~10 seconds:
  anima state → AnimaHistory.record()

Every ~1 minute:
  growth.observe_state_preference() → updates Π
  self_model updates → updates Β, Ρ

On get_trajectory call:
  ┌─────────────────────────────────────────────────┐
  │  compute_trajectory_signature()                  │
  │                                                 │
  │  growth.get_preference_vector() ──────▶ Π      │
  │  self_model.get_belief_signature() ───▶ Β      │
  │  history.get_attractor_basin() ───────▶ Α      │
  │  self_model.get_recovery_profile() ───▶ Ρ      │
  │  growth.get_relational_disposition() ─▶ Δ      │
  │                                                 │
  │  ──────────▶ TrajectorySignature(Π,Β,Α,Ρ,Δ)   │
  └─────────────────────────────────────────────────┘
```

---

## Testing

```bash
# Basic test
python3 -c "
from src.anima_mcp.trajectory import compute_trajectory_signature
sig = compute_trajectory_signature()
print(sig.summary())
"

# Full test with mock data
python3 -c "
from src.anima_mcp.anima_history import AnimaHistory
from src.anima_mcp.trajectory import TrajectorySignature

# Record some history
h = AnimaHistory(max_size=100)
for i in range(50):
    h.record(0.5 + i*0.001, 0.6, 0.7, 0.8)

basin = h.get_attractor_basin()
print(f'Basin center: {basin[\"center\"]}')
print(f'Observations: {basin[\"n_observations\"]}')
"
```

---

## Next Steps (Future Work)

1. **Historical Signature Storage**: Persist computed signatures for anomaly detection
2. **Visualization**: Create visual representation of trajectory identity
3. **Fork/Merge**: Implement agent forking with trajectory inheritance
4. **Experiments**: Run convergence and discriminability studies

---

## Verification Checklist

- [x] AnimaHistory records state correctly
- [x] Attractor basin computes center and covariance
- [x] Preference vector extracts from growth system
- [x] Belief signature extracts from self model
- [x] Recovery profile estimates τ from episodes
- [x] Relational disposition captures social patterns
- [x] TrajectorySignature combines all components
- [x] Similarity function computes identity comparison
- [x] MCP tool returns trajectory data
- [x] Server loop records history automatically

---

*The Trajectory Identity framework is now operational. Identity is no longer just a UUID - it's a pattern that persists through time.*
