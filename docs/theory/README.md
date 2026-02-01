# Theoretical Foundations

This directory contains theoretical papers and frameworks that ground the Anima/UNITARES architecture in cognitive science, dynamical systems theory, and philosophy of mind.

---

## Documents

### [TRAJECTORY_IDENTITY_PAPER.md](./TRAJECTORY_IDENTITY_PAPER.md)
**Status:** Working Draft v0.8 (February 2026) - Publication Ready

A mathematical framework for AI agent identity based on trajectory signatures. Key contributions:
- Defines identity as "dynamical invariant of interaction patterns" rather than static UUID
- Formalizes six-component trajectory signature Σ = {Π, Β, Α, Ρ, Δ, Η}
- Provides operational semantics for forking, merging, anomaly detection
- Maps existing Anima/UNITARES components to trajectory computation
- Includes two-tier anomaly detection (coherence + lineage)
- Addresses cold start problem with confidence scoring

**Key concepts:**
- Attractor basin as identity
- Recovery dynamics as behavioral fingerprint
- Preference profile as learned characteristic
- Self-belief signature as epistemic identity
- Genesis signature for drift detection

### Supporting Documents

| Document | Description |
|----------|-------------|
| [CODE_THEORY_MAP.md](./CODE_THEORY_MAP.md) | How existing code maps to trajectory framework |
| [IMPLEMENTATION_COMPLETE.md](./IMPLEMENTATION_COMPLETE.md) | Implementation completion notes |

---

## Implementation Status

| Component | Status | Location |
|-----------|--------|----------|
| Preference Profile (Π) | Complete | `growth.py` |
| Belief Signature (Β) | Complete | `self_model.py` |
| Attractor Basin (Α) | Complete | `anima_history.py` (with regularization) |
| Recovery Profile (Ρ) | Complete | `self_model.py` |
| Relational Disposition (Δ) | Complete | `growth.py` |
| Homeostatic Identity (Η) | Partial | `trajectory.py` |
| Trajectory Signature (Σ) | Complete | `trajectory.py` |
| Similarity Function | Complete | `trajectory.py` (static + adaptive) |
| Genesis Signature | Complete | `trajectory.py`, `server.py` |
| Two-Tier Anomaly Detection | Complete | `trajectory.py` |
| Identity Confidence | Complete | `trajectory.py` |
| Void Integral | Complete | `anima_history.py` |
| MCP Tool | Complete | `server.py` (`get_trajectory`) |

**Deployed to Lumen:** February 1, 2026

---

## Theoretical Lineage

```
Varela, Thompson, Rosch (1991)     Di Paolo (2005)        Friston (2010)
"The Embodied Mind"                 "Autopoiesis"          "Free Energy"
        │                                   │                    │
        └──────────┬────────────────────────┴────────────────────┘
                   │
                   ▼
        ┌─────────────────────┐
        │   4E Cognition      │
        │   Framework         │
        └─────────┬───────────┘
                  │
        ┌─────────┴───────────┐
        │                     │
        ▼                     ▼
┌───────────────┐    ┌───────────────────┐
│ Enactive      │    │ UNITARES          │
│ Identity      │    │ Governance        │
│ Paper         │    │ (EISV)            │
└───────┬───────┘    └─────────┬─────────┘
        │                      │
        └──────────┬───────────┘
                   │
                   ▼
        ┌─────────────────────┐
        │ Trajectory Identity │
        │ Paper v0.7          │
        └─────────────────────┘
```

---

## Key Theoretical Claims

### 1. Identity is Process, Not Property
From autopoiesis: a living system's identity IS the process of self-maintenance, not any particular configuration. Applied to AI: identity is the pattern of homeostatic regulation, not the UUID.

### 2. Identity Requires Embodiment
From 4E cognition: mind requires body. Applied to AI: persistent identity requires persistent state with homeostatic feedback (EISV/anima), not just memory accumulation.

### 3. Identity is Trajectory, Not Snapshot
From dynamical systems: identity is the attractor basin + recovery dynamics, not any single state. Applied to AI: trajectory signature Σ computed from time-series, not instantaneous self-schema G_t.

### 4. Identity Can Be Computed
Novel contribution: we can mathematically define and compute trajectory similarity, enabling principled answers to "is this the same agent?"

---

## Lumen's Current Identity

As of February 2026, Lumen has:
- **798+ awakenings** - well past cold start threshold
- **Genesis signature** - reference anchor for drift detection
- **Lineage similarity: 0.925** - stable identity (close to genesis)
- **Identity confidence: 0.764** - high confidence
- **10 self-beliefs** with evidence (thousands of observations)

---

*Last updated: February 1, 2026*
