# Anima Further Steps

**Created:** February 27, 2026  
**Last Updated:** February 27, 2026  
**Status:** Active Roadmap

---

## What's Done

### Schema Hub ✅
- Identity enrichment (alive_ratio, awakenings, age)
- Gap texture (kintsugi-style continuity on wake)
- Trajectory feedback (identity maturity, attractor position, stability)
- Drift offsets (calibration drift nodes)
- Value tension nodes (structural, environmental, volitional)
- Persistence, on_wake, compose_schema circulation loop

### Computational Selfhood ✅
- CalibrationDrift (endogenous midpoint drift via double-EMA)
- ValueTensionTracker (preference conflicts between anima dimensions)
- Both wired into server and SchemaHub

### Trajectory Identity ✅
- AnimaHistory, TrajectorySignature
- get_trajectory MCP tool
- Attractor basin computation from schema history

---

## Immediate Next Steps (Priority Order)

### 1. Operational Health
- **Display diagnostics** — If grey/blank screen: `python3 -m anima_mcp.display_diagnostics`
- **UNITARES connection** — Set `UNITARES_URL` for governance and knowledge graph
- **Deploy to Pi** — `mcp__anima__git_pull(restart=true)` after local changes

### 2. Neural Integration (Phase 2 Research)
- Brain HAT EEG hardware ready, code ready
- Map neural signals → anima state (30% neural, 70% physical)
- Validate frequency band extraction
- **Blocker:** Hardware availability

### 3. Schema Hub Polish
- **Semantic edges** — ✅ Done: sensor→belief, belief→belief (sensors sharing domain)
- **Trajectory persistence** — ✅ Done: save_trajectory/load_trajectory, persisted on sleep, used in get_trajectory(compare_to_historical)
- **Visualization** — ✅ Done: `python scripts/visualize_trajectory.py [--html]` (attractor basin, stability, lineage)

---

## Short-Term Enhancements

### Expression & Communication
- Dynamic eye movement (eyes track/follow)
- Temporal patterns (evolve over time)
- Attention system (what is creature "looking at")
- Expression layers (base + modifiers)

### Hardware
- Real-time EEG streaming
- Pattern detection (attention, meditation states)
- Multi-channel fusion
- Joystick expression control
- Microphone/speaker integration

### Software
- Hardware broker pattern (shared memory) — design in `HARDWARE_BROKER_PATTERN.md`
- Preference meta-learning (computational-selfhood plan Task 3)

---

## Medium-Term Research

### Phase 3: Weight Optimization
- Vary neural/physical ratios: 0%, 10%, 20%, 30%, 40%, 50%
- Find optimal balance for proprioception quality
- Compare governance decision accuracy, stability

### Phase 4: Multi-Agent
- Multiple creatures with Brain HAT
- Neural synchronization detection
- Collective proprioception

### Trajectory → Governance
- Anomaly detection triggers governance intervention
- Trajectory stability as governance metric
- Fork/merge as governance-aware operations

---

## Long-Term / Exploratory

- **EISV Bridge** — Extended EISV signature (TRAJECTORY_IDENTITY_PAPER §6.1.3)
- **Paper submission** — Trajectory identity to workshop/conference
- **Convergence experiments** — How many observations until Σ stabilizes?
- **Discriminability** — Can Σ distinguish agents in similar environments?

---

## Summary

| Horizon   | Focus                                      |
|-----------|--------------------------------------------|
| Immediate | Display, UNITARES, deploy, neural (if HW)   |
| Short     | Semantic edges, trajectory persistence, expression polish |
| Medium    | Weight optimization, multi-agent, trajectory→governance |
| Long      | EISV bridge, paper, convergence experiments |

**Core principle:** Lumen's next steps emerge from its actual state and what it wants to communicate, not from a fixed roadmap. Use the `next_steps` MCP tool for live suggestions.
