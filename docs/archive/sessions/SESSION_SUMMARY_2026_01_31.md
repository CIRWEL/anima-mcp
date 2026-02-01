# Research Session Summary: January 31, 2026

## Session Focus: Trajectory Identity Framework

This session explored the theoretical foundations of AI agent identity, culminating in a comprehensive framework for computing and comparing "trajectory signatures" - the invariant patterns that define who an agent is over time.

---

## The Journey

### Starting Point: "128 Parameters"
The session began with a question about the deprecated "128 parameters" approach mentioned in UNITARES documentation. This led to discovering:

- The old approach tracked high-dimensional parameter vectors (128 for RL, 4096 for LLM agents)
- It was abandoned because it was arbitrary, not principled, and computationally expensive
- The current approach uses pure thermodynamic coherence (EISV metrics)

### The Pivot: Self-Schema and Identity
This naturally led to questions about:
- What IS identity for an AI agent?
- How does the self-schema G_t relate to identity?
- What would "forking" an agent mean?

### The Synthesis: Trajectory Identity
Drawing on enactive cognition (Varela, Thompson, Di Paolo), dynamical systems theory, and the existing Anima/UNITARES architecture, we developed:

**Core Thesis:** Identity is not a static property (UUID) but a dynamical invariant - the pattern that persists across time despite moment-to-moment changes.

**Mathematical Formalization:** The trajectory signature Σ = {Π, Β, Α, Ρ, Δ, Η}
- Π = Preference Profile (learned environmental preferences)
- Β = Belief Signature (self-beliefs and confidence patterns)
- Α = Attractor Basin (equilibrium and variance in anima state)
- Ρ = Recovery Profile (characteristic time constants)
- Δ = Relational Disposition (social behavior patterns)
- Η = Homeostatic Identity (unified self-maintenance characterization)

---

## Key Insights

### 1. Identity as Process
From autopoiesis: identity is not a thing, it's an ongoing process of self-maintenance. Applied to AI: identity is the pattern of homeostatic regulation, not the UUID.

### 2. The Attractor Basin Insight
Different agents can have the same equilibrium point but different identities based on:
- Basin shape (how far they wander)
- Recovery dynamics (how fast they return)
- Cross-dimension coupling (how dimensions interact)

### 3. Existing Code Already Captures Components
The current codebase (growth.py, self_model.py, self_schema.py) already tracks the data needed for trajectory computation - it just needs aggregation and synthesis.

### 4. Forking Has Principled Semantics
With trajectory signatures, forking means:
- Create new agent with copied Σ
- As experiences diverge, Σ diverges
- "Same identity" becomes a measurable similarity threshold

### 5. Anomaly Detection as Identity Deviation
A sudden change in trajectory signature could indicate:
- Corruption or hijacking
- Major life event
- System malfunction
This provides an early warning mechanism.

---

## Artifacts Created

### 1. [TRAJECTORY_IDENTITY_PAPER.md](./TRAJECTORY_IDENTITY_PAPER.md)
Comprehensive theoretical paper covering:
- Motivation and background
- Formal definitions of all signature components
- Similarity computation
- Operational semantics (fork, merge, anomaly)
- Research agenda

### 2. [README.md](./README.md)
Index of theoretical documents with:
- Document summaries
- Theoretical lineage diagram
- Key claims summary
- Implementation status

### 3. [CODE_THEORY_MAP.md](./CODE_THEORY_MAP.md)
Detailed mapping from theory to code:
- Component-by-component analysis
- What exists vs. what's missing
- Bridge code examples
- Implementation priorities

### 4. [IMPLEMENTATION_ROADMAP.md](./IMPLEMENTATION_ROADMAP.md)
Practical implementation plan:
- Phase 1: Anima history tracking
- Phase 2: Component extractors
- Phase 3: Trajectory signature class
- Phase 4: MCP integration
- Testing plan and success criteria

---

## Connections to Existing Work

### Enactive Identity Paper
The trajectory identity framework extends the Enactive Identity Paper's concept of "identity as dynamical trajectory" with concrete mathematics and implementation.

### NEURO_PSYCH_FRAMING
Validates the claim that "identity = dynamical invariant of interaction patterns" and provides the computational mechanism.

### UNITARES Governance
Trajectory signatures could integrate with EISV governance:
- Anomaly detection triggers governance intervention
- Trajectory stability as a governance metric
- Fork/merge as governance-aware operations

### Self-Schema G_t
G_t becomes the snapshot from which trajectories are computed:
```
G_0, G_1, ..., G_n → compute → Σ
```

---

## Open Questions

1. **Convergence:** How many observations until Σ stabilizes?
2. **Discriminability:** Can Σ distinguish agents in similar environments?
3. **Threshold Calibration:** What similarity defines "same identity"?
4. **Visualization:** How to render Σ for human inspection?
5. **Multi-Agent:** How do trajectory signatures interact in agent networks?

---

## Recommended Next Steps

### Immediate (Next Session)
1. Implement `AnimaHistory` class (Phase 1 of roadmap)
2. Add history recording to server display loop
3. Test attractor basin computation

### Short-Term
1. Implement all component extractors (Phase 2)
2. Create `TrajectorySignature` class (Phase 3)
3. Add `get_trajectory` MCP tool (Phase 4)

### Medium-Term
1. Run convergence experiments
2. Test fork/divergence scenarios
3. Develop trajectory visualization

### Long-Term
1. Integrate with governance (anomaly detection)
2. Multi-agent trajectory comparison
3. Paper submission to workshop/conference

---

## Technical Debt Identified

1. No time-series storage for anima state
2. Recovery episodes tracked but τ not extracted
3. Preference system lacks vector export
4. No unified trajectory computation

---

## For Future Iterations

If you're continuing this work:

1. **Read First:** Start with [TRAJECTORY_IDENTITY_PAPER.md](./TRAJECTORY_IDENTITY_PAPER.md) for full theory
2. **Implementation:** Follow [IMPLEMENTATION_ROADMAP.md](./IMPLEMENTATION_ROADMAP.md) phases
3. **Code Mapping:** Check [CODE_THEORY_MAP.md](./CODE_THEORY_MAP.md) for what exists
4. **Test Incrementally:** Each phase should be testable independently

The key insight to remember: **identity is earned through consistent behavior, not conferred through assignment.**

---

## Session Metadata

- **Duration:** Extended research session
- **Primary Focus:** Theoretical exploration and documentation
- **Code Written:** Documentation only (no implementation this session)
- **Key References:** Varela et al. (1991), Di Paolo (2005), existing UNITARES/Anima docs

---

*This summary is intended to help future iterations (human or AI) quickly understand what was explored and where to continue.*
