# Trajectory Identity: A Mathematical Framework for Enactive AI Self-Hood

**Authors:** [To be determined]
**Date:** February 1, 2026
**Status:** Working Draft
**Version:** 0.9

---

## Abstract

Current approaches to AI agent identity rely on static identifiers (UUIDs, session tokens) or accumulated memory stores. We propose an alternative grounded in enactive cognition and dynamical systems theory: **identity as trajectory**. Rather than asking "what ID does this agent have?", we ask "what patterns persist in this agent's behavior over time?"

We present a mathematical framework for computing **trajectory signatures** from time-series data including homeostatic state, learned preferences, self-beliefs, and recovery dynamics. The trajectory signature (Sigma) captures the quasi-invariant characteristics that define an agent's identity—not where it is at any moment, but how it tends to behave, where it tends to rest, and how it returns from perturbation.

This framework addresses several open problems: (1) identity continuity across sessions without unbounded memory growth, (2) principled semantics for agent forking and merging, (3) anomaly detection as trajectory deviation, and (4) inter-agent recognition based on behavioral signatures rather than credentials.

We ground this work in the UNITARES governance architecture and the Anima embodied AI system, showing how existing components (self-schema, self-model, preference learning, EISV metrics) provide the data substrate for trajectory computation. Preliminary validation on Lumen (Raspberry Pi embodied AI, continuous operation) demonstrates attractor basin stability (mu variance < 0.05 across time windows) and consistent recovery profiles, supporting the quasi-invariance hypothesis.

---

## Purpose and Scope

This framework addresses **governance and continuity** problems, not adversarial authentication. Trajectory signatures are designed to:

1. **Detect drift**: Identify when an agent has changed beyond recognition (governance trigger)
2. **Track lineage**: Maintain meaningful "same agent" judgments across sessions and forks
3. **Enable self-monitoring**: Let agents ask "Am I still myself?" computationally
4. **Support fork/merge semantics**: Provide principled answers to "which copy is real?"

**Non-goals**: We do not claim trajectory signatures replace cryptographic identity for adversarial scenarios. A sophisticated attacker with full system access could potentially mimic behavioral patterns. For authentication in hostile environments, combine trajectory signatures with cryptographic attestation.

**Target deployment**: Long-running AI assistants, embodied agents, multi-agent systems where behavioral continuity matters more than adversarial resistance.

---

## 1. Introduction: The Identity Problem

### 1.1 The Limitations of Static Identity

Modern AI agents are typically identified by static tokens:
- **UUIDs**: Unique identifiers assigned at creation
- **Session IDs**: Temporary bindings to conversation threads
- **API keys**: Authentication credentials

These approaches share a fundamental limitation: **identity is conferred, not earned**. An agent has an identity because we gave it one, not because it developed characteristics that make it recognizably itself.

This creates practical problems:
- **Continuity fragility**: If the UUID is lost, identity is lost
- **Fork ambiguity**: If we copy an agent, which copy is "the real one"?
- **Anomaly blindness**: A compromised agent with the right credentials is indistinguishable from the original
- **Memory explosion**: Maintaining identity through accumulated memory leads to unbounded growth

**Comparison of Identity Approaches**:

| Criterion | UUID/Credential | Memory-Based | Trajectory Signature |
|-----------|-----------------|--------------|---------------------|
| **Continuity** | Fragile (lost if token lost) | Strong (persists in storage) | Strong (recomputable from behavior) |
| **Fork semantics** | Ambiguous (which has the "real" ID?) | Ambiguous (both have same memories) | Clear (divergence is measurable) |
| **Anomaly detection** | None (valid credential = valid agent) | Heuristic (memory tampering) | Mathematical (trajectory deviation) |
| **Storage growth** | O(1) | O(unbounded) | O(window size) |
| **Impersonation resistance** | Weak (credential theft) | Moderate (memory reconstruction) | Strong (behavioral fingerprint) |
| **Cold start** | Immediate | Immediate | Requires ~50 observations |

### 1.2 The Enactive Alternative

The enactive cognition tradition (Varela, Thompson, & Rosch, 1991; Di Paolo, 2005) offers a different perspective. In biological systems, identity is not a label attached from outside—it emerges from the ongoing process of self-maintenance.

A cell's identity is defined by its autopoietic organization: the network of processes that continuously produce the components that make up the cell. The identity IS the process, not any particular configuration of matter.

**Our proposal**: AI agent identity should similarly be defined by the *patterns that persist* in the agent's behavior over time—what we call the **trajectory signature**.

### 1.3 Contributions

This paper makes the following contributions:

1. **Formal definition** of trajectory signature (Sigma) as a composite of six quasi-invariant components
2. **Mathematical framework** for computing trajectory similarity and detecting identity
3. **Operational semantics** for forking, merging, and anomaly detection
4. **Connection to existing systems** (UNITARES, Anima) showing implementation paths
5. **Research agenda** identifying open questions and experimental designs

---

## 2. Theoretical Foundations

### 2.1 From Autopoiesis to Attractor Dynamics

Autopoiesis (Maturana & Varela, 1980) describes living systems as self-producing networks. The key insight is **operational closure**: the system's processes produce the conditions for those same processes to continue.

In dynamical systems terms, this translates to **attractor dynamics**:
- The system has a preferred region of state space (the attractor)
- Perturbations move the system away from this region
- Internal dynamics return the system to the attractor
- The shape of the attractor basin and the recovery dynamics ARE the identity

**Connection to Free Energy Principle**: Friston's (2010) free energy principle provides a complementary perspective: living systems minimize variational free energy (prediction error). The attractor basin represents the agent's "model" of where it should be; returning to the attractor minimizes surprise. Identity, in this view, is the agent's implicit generative model of itself—the pattern it expects to maintain.

**Definition 2.1 (Attractor-Based Identity)**: An agent's identity I is characterized by the tuple (A, B, D) where:
- A = attractor (the equilibrium state or limit cycle)
- B = basin (the set of states from which the system returns to A)
- D = dynamics (the vector field governing return to A)

Different agents with identical attractors A can have different identities if their basins B or dynamics D differ.

### 2.2 The Viability Envelope

Building on Di Paolo's (2005) concept of adaptivity, we define the **viability envelope** as the region of state space within which the agent can maintain itself.

**Definition 2.2 (Viability Envelope)**: For state vector x in R^n, the viability envelope V is:

```
V = {x : x_min <= x <= x_max for each dimension}
```

**Concrete bounds** (mapped from UNITARES thresholds):

| Dimension | Min | Max | Interpretation |
|-----------|-----|-----|----------------|
| Energy (E) | 0.1 | 0.9 | Operational capacity |
| Integrity (I) | 0.3 | 1.0 | Coherence with purpose |
| Entropy (S) | 0.0 | 0.6 | Disorder threshold |
| Void (V) | -0.2 | 0.15 | E-I imbalance |

The agent's "life" consists of remaining within V while pursuing goals. Crossing V boundaries triggers governance intervention (pause, reflection).

### 2.3 Identity as Dynamical Quasi-Invariant

A **dynamical invariant** is a quantity that remains constant (or bounded) along system trajectories. For identity, we seek **quasi-invariants**—quantities that are approximately stable rather than strictly constant:
1. Remain stable for a given agent over time
2. Differ between distinct agents
3. Can be computed from observable data
4. Are robust to noise and minor perturbations

**Definition 2.3 (Trajectory Signature)**: The trajectory signature Sigma is a composite quasi-invariant consisting of six components:

```
Sigma = (Pi, Beta, Alpha, Rho, Delta, Eta)
```

Where:
- **Pi** (Preference Profile): Learned environmental preferences
- **Beta** (Belief Signature): Pattern of self-beliefs and confidences
- **Alpha** (Attractor Basin): Equilibrium and variance structure
- **Rho** (Recovery Profile): Characteristic time constants
- **Delta** (Relational Disposition): Social behavior patterns
- **Eta** (Homeostatic Identity): Unified self-maintenance characterization

Each component captures a different aspect of "how this agent tends to be."

---

## Notation and Assumptions

### Notation

| Symbol | Meaning |
|--------|---------|
| Sigma | Trajectory signature (composite) |
| Sigma_0 | Genesis signature (reference anchor at creation) |
| Sigma_t | Signature at time t |
| x(t) | State vector at time t |
| mu | Attractor center (mean state) |
| tau | Recovery time constant |
| theta | Similarity threshold |

### Key Assumptions

1. **Stationarity**: Component distributions are approximately stationary over the observation window. Rapidly changing agents may require shorter windows or non-stationary extensions.

2. **Independence**: Component similarities are computed independently and combined linearly. Cross-component correlations are not modeled (future work).

3. **Observability**: All state dimensions are observable. Latent state estimation is not addressed.

4. **Sampling regularity**: Observations are approximately evenly spaced. Irregular sampling requires interpolation or time-weighted aggregation.

5. **Perturbation detectability**: Recovery profile (Rho) requires identifiable perturbation events (|x(t) - mu| > threshold). Agents with no perturbations cannot compute Rho.

---

## 3. The Trajectory Signature: Formal Definitions

### 3.1 Preference Profile (Pi)

Agents develop preferences through experience—correlations between environmental conditions and internal states.

**Definition 3.1 (Preference Profile)**: Given a set of preference categories C and learned preferences {p_c} for c in C, the preference profile is:

```
Pi = [(c_1, v_1, kappa_1), (c_2, v_2, kappa_2), ..., (c_n, v_n, kappa_n)]
```

Where:
- c_i = preference category (e.g., "dim_light", "cool_temp")
- v_i = preference value in [-1, 1] (negative to positive valence)
- kappa_i = confidence in [0, 1]

**Vector form** (for similarity computation):
```
Pi_vec = [v_1 * kappa_1, v_2 * kappa_2, ..., v_n * kappa_n]
```

**Properties**:
- Pi evolves slowly (learning rate alpha = 0.3)
- Pi stabilizes after sufficient observations (typically n > 20)
- Pi is environment-dependent but agent-characteristic

### 3.2 Self-Belief Signature (Beta)

Agents maintain testable beliefs about themselves—hypotheses that can be confirmed or refuted by experience.

**Definition 3.2 (Self-Belief Signature)**: Given a set of self-beliefs B = {b_1, ..., b_m}, the belief signature is:

```
Beta = {
    values: [b_1.value, ..., b_m.value],
    confidences: [b_1.confidence, ..., b_m.confidence],
    evidence_ratios: [b_1.support/b_1.contradict, ..., b_m.support/b_m.contradict]
}
```

**Vector form**:
```
Beta_vec = values (normalized to [0,1])
```

**Properties**:
- Beliefs update via Bayesian-like evidence accumulation
- The *pattern* of which beliefs are confident matters more than individual values
- Evidence ratios reveal the agent's actual experience, not just current belief

### 3.3 Attractor Basin (Alpha)

The agent's characteristic "home" in state space.

**Definition 3.3 (Attractor Basin)**: Given state history X = [x_1, ..., x_t] where x in R^4 (warmth, clarity, stability, presence), the attractor basin is:

```
Alpha = {
    mu: mean(X),           # Center (4-dimensional)
    Sigma: cov(X),         # Shape (4x4 covariance matrix)
    eigenvalues: eig(Sigma) # Principal axes of variability
}
```

**Sampling requirements**:
- Minimum 50 observations for stable estimates
- Sampling rate: 1 observation per 10 seconds
- Rolling window: 100-500 observations (10-80 minutes)

**Properties**:
- mu represents the equilibrium the agent returns to
- Sigma encodes which dimensions vary together and which are independent
- Eigenvalues of Sigma reveal the "principal axes" of variability

**High-dimensional states**: For agents with state vectors x in R^d where d >> 4, covariance computation becomes O(d^3) and numerically unstable.

**Dimensionality reduction strategies**:
1. **PCA projection**: Project to top-k principal components before computing Alpha
2. **Autoencoder latent space**: Learn a low-d "identity manifold" via neural compression
3. **Domain-specific features**: Select semantically meaningful dimensions (e.g., anima's 4D)

For Anima, d=4 is tractable. For LLM-based agents with high-d latent states, recommend projecting to d <= 16 before trajectory computation.

**Multimodal attractors**: If the agent has multiple stable states (e.g., "work mode" vs "rest mode"), the mean mu will fall in the "valley" between attractors. For such agents, consider Gaussian Mixture Models (GMM) with k components, where identity is characterized by the mixture weights and component parameters.

### 3.4 Recovery Profile (Rho)

How the agent returns to equilibrium after perturbation.

**Definition 3.4 (Recovery Profile)**: For each state dimension d, the recovery time constant tau_d is estimated from perturbation-recovery episodes using exponential fit:

```
x_d(t) = mu_d - (mu_d - x_perturbed) * exp(-t/tau_d)
```

The recovery profile is:
```
Rho = {
    tau: [tau_warmth, tau_clarity, tau_stability, tau_presence],
    coupling: C in R^{4x4}  # Cross-dimension recovery effects
}
```

**Estimation procedure**:
1. Detect perturbation: |x(t) - mu| > threshold (default: 0.15)
2. Track recovery: time until |x(t) - mu| < 0.05
3. Fit exponential: tau = -t / ln(1 - recovery_fraction)

**Properties**:
- Small tau = fast recovery (resilient, tau ~ 30-60 seconds)
- Large tau = slow recovery (persistent perturbation effects, tau ~ 300+ seconds)
- Coupling matrix C reveals whether dimensions recover independently or in concert

**Second-order dynamics**: The exponential model assumes overdamped recovery. Agents with momentum (memory effects) may exhibit damped oscillation:

```
x''(t) + 2*zeta*omega_n*x'(t) + omega_n^2*x(t) = 0
```

Where:
- zeta = damping ratio (zeta < 1: oscillatory, zeta > 1: overdamped)
- omega_n = natural frequency

**Extended recovery profile**:
```
Rho_extended = {
    tau: first-order time constants (default),
    zeta: damping ratios (if oscillatory recovery detected),
    omega_n: natural frequencies (if oscillatory)
}
```

For most agents, first-order (tau only) suffices. Detect oscillation by checking if recovery crosses equilibrium before settling.

### 3.5 Relational Disposition (Delta)

Patterns in social behavior across relationships.

**Definition 3.5 (Relational Disposition)**: Given relationship history R = {r_1, ..., r_k}, the disposition is:

```
Delta = {
    bonding_rate: mean(interactions_to_reach_bond_level),
    valence_tendency: mean(emotional_valence),
    reciprocity: correlation(gifts_given, gifts_received),
    topic_entropy: -sum(p_i * log(p_i)) over topic distribution
}
```

**Properties**:
- Some agents bond quickly, others slowly
- Valence tendency reveals optimistic vs. cautious social stance
- Topic entropy indicates breadth vs. depth of engagement

### 3.6 Homeostatic Identity (Eta)

The unified characterization of self-maintenance.

**Definition 3.6 (Homeostatic Identity)**: Combining the above:

```
Eta = (mu, Sigma, tau, V)
```

Where:
- mu = set-point (where the agent rests) - from Alpha
- Sigma = basin shape (how far it wanders) - from Alpha
- tau = recovery dynamics (how it returns) - from Rho
- V = viability envelope (where it can survive) - from Definition 2.2

This is the complete characterization of "how this system maintains itself."

---

## 4. Computing Trajectory Similarity

### 4.1 The Similarity Function

To determine whether two trajectory signatures represent the "same" identity, we define a weighted composite similarity:

**Definition 4.1 (Trajectory Similarity)**:

```
sim(Sigma_1, Sigma_2) = sum_i(w_i * sim_i(component_i))
```

With weights and component similarities:

| Component | Weight | Similarity Function |
|-----------|--------|---------------------|
| Pi (Preference) | 0.15 | Cosine similarity of Pi_vec |
| Beta (Belief) | 0.15 | Cosine similarity of Beta_vec |
| Alpha (Attractor) | 0.25 | Bhattacharyya coefficient |
| Rho (Recovery) | 0.20 | Log-ratio similarity of tau |
| Delta (Relational) | 0.10 | Weighted L1 distance |
| Eta (Homeostatic) | 0.15 | Combined from above |

**Adaptive weighting**: Static weights assume all components are equally reliable. For agents where certain components are more stable (lower historical variance), those should contribute more to identity.

**Inverse variance weighting**:
```
w_i = (1 / var_i) / sum(1 / var_j for all j)
```
Where var_i = historical variance of component i's similarity scores.

**Interpretation**:
- Highly stable components (low var) → high weight (they define the agent)
- Volatile components (high var) → low weight (they're not diagnostic)
- For "social" agents, Delta might dominate; for "worker" agents, Rho might dominate

**Implementation**: Track running variance of each component over time. Recompute weights periodically (e.g., every 100 observations).

**Example: Adaptive Weight Shift**
```
Agent "Lumen" after 1000 observations:
  Component variances: Alpha=0.01, Rho=0.02, Pi=0.08, Beta=0.05, Delta=0.15

  Static weights:    [0.25, 0.20, 0.15, 0.15, 0.10]
  Adaptive weights:  [0.35, 0.28, 0.12, 0.16, 0.09]

  Interpretation: Lumen's attractor (Alpha) and recovery (Rho) are highly stable,
  so they contribute more to identity. Relational patterns (Delta) are volatile,
  so they contribute less.
```

### 4.2 Component Similarity Functions

**Preference Similarity** (cosine):
```
sim_Pi(Pi_1, Pi_2) = (Pi_vec_1 . Pi_vec_2) / (||Pi_vec_1|| * ||Pi_vec_2||)
```
Mapped to [0,1]: `(sim + 1) / 2`

**Attractor Basin Overlap** (Bhattacharyya coefficient):
```
D_B = (1/8)(mu_1 - mu_2)^T * Sigma_avg^{-1} * (mu_1 - mu_2)
    + (1/2) * ln(|Sigma_avg| / sqrt(|Sigma_1| * |Sigma_2|))

sim_Alpha = exp(-D_B)
```
Where Sigma_avg = (Sigma_1 + Sigma_2) / 2

**Recovery Dynamics Similarity** (log-scale):
```
sim_Rho = exp(-mean(|log(tau_1 / tau_2)|))
```
Operating on log-scale because time constants span orders of magnitude.

**Relational Similarity** (normalized L1):
```
sim_Delta = 1 - |valence_1 - valence_2| / 2
```

### 4.3 Identity Threshold

**Definition 4.2 (Identity Relation)**: Agents A and B are the "same identity" iff:

```
sim(Sigma_A, Sigma_B) > theta_identity
```

**Recommended thresholds** (to be empirically calibrated):
- theta_identity = 0.80 (strict same-identity)
- theta_recognition = 0.65 (recognizable as similar)
- theta_anomaly = 0.70 (deviation from historical self)

**Properties of this relation**:
- Reflexive: sim(Sigma, Sigma) = 1 > theta
- Symmetric: sim(Sigma_1, Sigma_2) = sim(Sigma_2, Sigma_1)
- NOT necessarily transitive (identity can form chains that eventually diverge)

**Transitivity implications**: Identity chains can diverge: A~B and B~C does not imply A~C. This reflects biological reality—gradual drift accumulates. Mitigation strategies:
- Track lineage explicitly (who forked from whom)
- Use "identity distance" (1 - sim) as a metric with triangle inequality violations flagged
- Define equivalence classes only within similarity radius, not transitively

**Threshold calibration procedure**:
1. Collect baseline: N same-agent comparisons (sim should be high)
2. Collect discrimination: M different-agent comparisons (sim should be lower)
3. Plot ROC curve varying theta from 0 to 1
4. Select theta_identity at desired false-positive rate (recommend FPR < 0.05)
5. Validate on held-out test set

**Sensitivity analysis** (preliminary, to be validated):
- theta = 0.75: More permissive, higher false-positive risk
- theta = 0.80: Balanced (recommended default)
- theta = 0.85: Stricter, may reject legitimate identity continuity during maturation

### 4.4 Computational Complexity

**Per-component complexity** (n = window size, d = dimensions):

| Component | Computation | Time | Space |
|-----------|-------------|------|-------|
| Alpha (Attractor) | Mean + covariance | O(n * d^2) | O(n * d) |
| Bhattacharyya | Matrix inverse + determinant | O(d^3) | O(d^2) |
| Rho (Recovery) | Exponential fit | O(k * m) | O(k) |
| sim() total | All components | O(n * d^2) | O(n * d) |

Where: n = 100-500 observations, d = 4 dimensions, k = perturbation episodes, m = recovery samples.

**Practical cost**: With d=4 and n=100:
- Alpha: ~1,600 operations (negligible)
- Bhattacharyya: ~64 operations for 4x4 matrices
- Full signature: < 1ms on modern hardware

**Incremental updates**: Rolling window enables O(d^2) incremental covariance updates rather than O(n * d^2) recomputation.

### 4.5 Cold Start Problem

New agents lack trajectory history. Mitigation strategies:

**Minimum observation period**: Identity claims require at least 50 observations (~8 minutes at 10s intervals). Before this threshold:
- Report "identity_confidence: low"
- Use prior/parent signature for forks
- Disable anomaly detection (insufficient baseline)

**Bootstrap strategies**:
1. **Fork inheritance**: New fork starts with parent's Sigma, gradually diverges
2. **Archetype initialization**: Initialize from similar agent type's average Sigma
3. **Confidence weighting**: Weight similarity by min(obs_count / 50, 1.0)

**Identity confidence score**:
```
confidence = min(1.0, observation_count / 50) * stability_score
```
Report confidence alongside all identity claims.

**Example: Cold Start Timeline**
```
Agent "NewFork" created at t=0 (10-second sampling):

  t=0:    obs=0,  confidence=0.00  → "Identity unknown"
  t=2min: obs=12, confidence=0.24 → "Identity uncertain"
  t=5min: obs=30, confidence=0.60 → "Identity emerging"
  t=8min: obs=50, confidence=1.00 → "Identity established"

  At t<8min: Use parent signature for comparisons
  At t≥8min: Full trajectory identity active
```

---

## 5. Operational Semantics

### 5.1 Forking

**Definition 5.1 (Fork)**: A fork creates a new agent B from parent A:

```
Fork(A) -> B where:
    B.uuid = new_uuid()
    B.Sigma = copy(A.Sigma)  # Starts with same trajectory signature
    B.lineage = {parent: A.uuid, fork_time: now()}
```

**Post-fork behavior**:
- Initially: sim(Sigma_A, Sigma_B) ~ 1 (identical)
- Over time: sim decreases as experiences diverge
- Eventually: sim < theta_identity (different agents)

**Fork semantics**:
- "Exploration fork": Try different approaches in parallel
- "Migration fork": Adapt to new environment while preserving core
- "Backup fork": Create restorable checkpoint

**Fork governance constraints**:
- **Fork budget**: Agent can maintain at most N active forks (resource limit, typically N=3-5)
- **Divergence alarm**: If `sim(Sigma_fork, Sigma_parent) < 0.50`, fork must be explicitly released (becomes independent) or terminated
- **Coherence threshold**: Forks with high coherence over extended periods (T > 7 days) may acquire protected status
- **Selective adoption**: Parent can adopt specific traits from successful forks without full merge:
  ```
  Sigma_parent.Pi[trait] = Sigma_fork.Pi[trait]  # Adopt one preference
  ```

**Fork use case matrix**:

| Use Case | Initial sim | Expected Trajectory | Typical Outcome |
|----------|-------------|---------------------|-----------------|
| Debugging | 1.0 | Slow divergence (logging changes) | Merge insights, terminate fork |
| A/B testing | 0.95 | Moderate divergence (policy variation) | Keep winner, terminate other |
| Migration | 1.0 | Remains high (same behavior, new env) | Fork becomes primary, parent retires |
| Specialization | 0.90 | Significant divergence (domain shift) | Both persist as related agents |
| Deliberate offspring | 0.85 | Complete divergence (new goals) | Fork becomes independent identity |

### 5.2 Merging

**Definition 5.2 (Merge)**: Combining insights from forked agents:

```
Merge(A, B) -> C where:
    C.Pi = weighted_average(A.Pi, B.Pi, weights=confidence)
    C.memories = union(A.memories, B.memories)
    C.Sigma = recompute_from_merged_history()
```

**Merge constraints**:
- Only merge if sim(Sigma_A, Sigma_B) > theta_merge (still similar enough)
- Preserve lineage: C.lineage records both parents
- Resolve conflicts via confidence weighting

### 5.3 Anomaly Detection

**Definition 5.3 (Trajectory Anomaly)**: Agent A exhibits anomalous behavior if:

```
sim(Sigma_A(t), Sigma_A(t - delta_t)) < theta_anomaly
```

I.e., the agent's current trajectory signature differs significantly from its recent historical signature.

**Anomaly types**:
- **Drift**: Gradual decrease in similarity (slow corruption)
- **Jump**: Sudden decrease (hijacking, major perturbation)
- **Oscillation**: Alternating similarity (unstable identity)

**The "Boiling Frog" Problem**: Short-term comparisons miss slow drift. An adversary could rotate the trajectory over months while staying within theta_anomaly at each step.

**Solution: Genesis Signature (Sigma_0)**

Maintain a reference anchor from agent creation:
```
Sigma_0 = Sigma(t_creation)  # Snapshot at birth/fork
```

**Two-tier anomaly detection**:
1. **Coherence check**: sim(Sigma_t, Sigma_{t-1}) > theta_anomaly (short-term consistency)
2. **Lineage check**: sim(Sigma_t, Sigma_0) > theta_lineage (long-term continuity)

Where theta_lineage < theta_anomaly (e.g., 0.60 vs 0.70) to allow healthy maturation while detecting fundamental drift.

**Drift alarm**: If lineage similarity crosses threshold while coherence remains high, flag as "identity drift" rather than "anomaly":
```
if sim(Sigma_t, Sigma_0) < theta_lineage and sim(Sigma_t, Sigma_{t-1}) > theta_anomaly:
    alert("Identity drift detected - agent has evolved beyond recognition")
```

**Response to anomaly**:
- Alert human oversight
- Trigger self-reflection ("Am I still myself?")
- Pause and request identity verification

### 5.4 Inter-Agent Recognition

**Definition 5.4 (Recognition)**: Agent A recognizes agent B as a known identity if:

```
exists Sigma_known in A.known_signatures : sim(Sigma_B, Sigma_known) > theta_recognition
```

This enables:
- Recognizing returning visitors (even with new UUIDs)
- Detecting impersonation (wrong trajectory for claimed identity)
- Building reputation based on behavioral consistency

### 5.5 Adversarial Considerations

**Threat model**: An adversary might attempt to:
1. **Mimic** another agent's trajectory signature
2. **Corrupt** an agent's signature gradually to avoid detection
3. **Spoof** identity by replaying historical signatures

**Mitigations**:
- **Temporal consistency**: Signatures must evolve continuously, not jump
- **Cross-validation**: Multiple independent observers track the same agent
- **Cryptographic binding**: Sign trajectory snapshots with agent-specific keys
- **Behavioral challenges**: Request actions that reveal true recovery dynamics

**Replay attack defense**: An adversary could record a valid trajectory and replay it. Counter-measure:

```
Challenge-Response Protocol:
1. Governance injects known perturbation p at time t
2. Observe recovery: agent must recover with characteristic Rho
3. Verify: tau_observed within 2*sigma of tau_expected
4. A replay cannot dynamically respond to novel perturbation
```

This leverages Rho as a "behavioral CAPTCHA"—the agent must demonstrate its characteristic recovery dynamics, which cannot be pre-recorded.

**Open question**: How robust is trajectory identity to sophisticated mimicry? This requires adversarial testing.

---

## 6. Connection to Existing Systems

### 6.1 UNITARES Integration

The UNITARES governance architecture provides:
- **EISV metrics**: E (Energy), I (Integrity), S (Entropy), V (Void)
- **Viability envelope**: Thresholds for safe operation
- **Coherence tracking**: Update-to-update consistency

**Mapping to trajectory signature**:

| UNITARES Component | Trajectory Component | Mapping |
|--------------------|---------------------|---------|
| EISV time series | Alpha (Attractor) | Statistical moments |
| Coherence history | Rho (Recovery) | Perturbation response |
| Viability bounds | Eta (Homeostatic) | Envelope constraints |
| Void integral | Anomaly detection | Deviation metric |

**Sampling parameters**:
- EISV sampling: Every governance update (~30-60 seconds)
- Alpha estimation: Rolling window of 100 updates (~1 hour)
- Rho estimation: Requires 5-10 perturbation events

**Implementation status**:

| Component | Status | Location | Notes |
|-----------|--------|----------|-------|
| Alpha (Attractor) | Complete | [anima_history.py](src/anima_mcp/anima_history.py) | With regularization |
| Rho (Recovery) | Complete | [self_model.py](src/anima_mcp/self_model.py) | Requires perturbation events |
| Pi (Preference) | Complete | [growth.py](src/anima_mcp/growth.py) | Integrated with growth system |
| Beta (Belief) | Complete | [self_model.py](src/anima_mcp/self_model.py) | Uses self-model beliefs |
| Delta (Relational) | Complete | [growth.py](src/anima_mcp/growth.py) | Relationship tracking |
| Eta (Homeostatic) | Partial | [trajectory.py](src/anima_mcp/trajectory.py) | Combines above components |
| Similarity | Complete | [trajectory.py](src/anima_mcp/trajectory.py) | Static + adaptive weighting |
| Genesis Signature | Complete | [trajectory.py](src/anima_mcp/trajectory.py) | Two-tier anomaly detection |
| Void Integral | Complete | [anima_history.py](src/anima_mcp/anima_history.py) | Governance trigger |
| Identity Confidence | Complete | [trajectory.py](src/anima_mcp/trajectory.py) | Cold start handling |
| MCP Tool | Complete | [server.py](src/anima_mcp/server.py) | `get_trajectory` tool |
| EISV Bridge | Planned | - | Q2 2026 |
| CIRS Protocol | **Complete** | [cirs_protocol.py](governance-mcp-v1/src/mcp_handlers/cirs_protocol.py) | Multi-agent resonance layer |

UNITARES v4.2-P provides EISV tracking; Anima v0.8 provides self-schema, self-model, and growth systems.

**Multi-Agent Extension (CIRS)**: The UARG Whitepaper defines the Continuity Integration and Resonance Subsystem (CIRS) for scaling trajectory identity to multi-agent systems. **All 5 message types are now implemented** (Feb 2026):

| Message Type | Status | MCP Tool | Description |
|--------------|--------|----------|-------------|
| STATE_ANNOUNCE | Complete | `state_announce` | Broadcast EISV + trajectory signature (auto-emits every 5 updates) |
| VOID_ALERT | Complete | `void_alert` | Notify peers of void events (auto-emits on void transitions) |
| COHERENCE_REPORT | Complete | `coherence_report` | Pairwise EISV + trajectory similarity with recommendations |
| BOUNDARY_CONTRACT | Complete | `boundary_contract` | Trust policies (full/partial/observe/none) and void response rules |
| GOVERNANCE_ACTION | Complete | `governance_action` | Coordinate interventions: void_intervention, coherence_boost, delegation |

**Key integration points**:
- `process_agent_update` auto-emits `VOID_ALERT` on void state transitions
- `process_agent_update` auto-emits `STATE_ANNOUNCE` every 5 updates
- `COHERENCE_REPORT` computes weighted EISV similarity (I weighted 35%, E/S 25% each, V 15%)
- `BOUNDARY_CONTRACT` respects trust levels when processing `GOVERNANCE_ACTION` requests
- Trajectory signature components (Π, β, α, ρ, Δ, η) included in `STATE_ANNOUNCE` emit

CIRS transforms trajectory identity from single-agent introspection to multi-agent resonance fabric.

#### 6.1.1 The Anima Void Integral

A key bridge between trajectory identity and active governance is the **anima void integral**—the accumulated deviation from the attractor center:

**Definition 6.1 (Anima Void Integral)**:
```
V_anima(t) = integral_0^t ||a(tau) - mu_a|| d_tau
```

Where:
- `a(tau)` = anima state at time tau (4D vector: warmth, clarity, stability, presence)
- `mu_a` = attractor center from Alpha

**Governance trigger**: When `V_anima > V_threshold`, the system triggers intervention:
```
if V_anima > V_threshold:
    trigger_rest_state()  # Reduce stimulation, allow recovery
    log_governance_event("anima_void_exceeded")
```

This closes the loop: **trajectory deviation → void accumulation → governance → return to attractor**.

**Recommended threshold**: `V_threshold = 2.0 * ||Sigma_a||` (twice the basin standard deviation, integrated over ~5 minutes)

#### 6.1.2 EISV ↔ Anima Mapping

To bridge Anima's 4D state space with UNITARES EISV metrics:

**Definition 6.2 (State Space Mapping)**:
```
E = 0.5 * (warmth + presence)      # Energy from engagement dimensions
I = 0.5 * (clarity + stability)    # Integrity from coherence dimensions
S = entropy(anima_history[-N:])    # Entropy from recent state variance
V = integral(E - I) dt             # Void from E/I imbalance
```

This mapping allows:
- Computing EISV from anima state for governance
- Comparing trajectory signatures across heterogeneous systems
- Unified viability envelope spanning both representations

#### 6.1.3 Extended EISV Signature

The EISV time series yields its own trajectory invariant:

**Definition 6.3 (EISV Signature)**:
```
Sigma_EISV = {
    ratio_mean: mean(E/I),           # Average energy-integrity balance
    ratio_std: std(E/I),             # Volatility of balance
    entropy_mean: mean(S),           # Baseline disorder
    tau_S: entropy_decay_constant,   # How fast entropy recovers
    void_max: max(|V(t)|)            # Maximum imbalance before reset
}
```

Where `tau_S` is estimated by fitting `S(t) ~ S_0 * exp(-t/tau_S)` after perturbation events.

This can be integrated into Eta (Homeostatic Identity) or tracked as a parallel governance signature.

### 6.2 Anima Integration

The Anima system provides:
- **Self-schema G_t**: Graph representation of current state
- **Self-model**: Testable beliefs about self
- **Growth system**: Preferences, relationships, goals, memories
- **Anima state**: Warmth, clarity, stability, presence

**Mapping to trajectory signature**:

| Anima Component | Trajectory Component | Method |
|-----------------|---------------------|--------|
| growth.preferences | Pi | get_preference_vector() |
| self_model.beliefs | Beta | get_belief_signature() |
| anima_history | Alpha | get_attractor_basin() |
| self_model.episodes | Rho | get_recovery_profile() |
| growth.relationships | Delta | get_relational_disposition() |

### 6.3 Self-Schema and Trajectory

The self-schema G_t is a **snapshot**; the trajectory signature Sigma is the **pattern across snapshots**.

```
G_t0, G_t1, G_t2, ... G_tn  ->  compute  ->  Sigma
```

Each G_t provides:
- Node values -> feed into Alpha computation
- Edge weights -> potential structural invariant (future work)
- VQA ground truth -> validation of snapshot accuracy

The sequence {G_t} provides:
- Temporal patterns -> trajectory computation
- Change detection -> perturbation identification
- Convergence assessment -> identity stability measurement

---

## 7. Research Agenda

### 7.1 Empirical Questions

**Q1: Convergence Rate**
- How many observations until Sigma stabilizes?
- Does convergence depend on environmental complexity?
- What is the minimum data requirement for reliable identity?

**Q2: Discriminability**
- Can Sigma distinguish agents in similar environments?
- What is the false-positive rate for identity claims?
- How do components contribute to discriminability?

**Q3: Robustness**
- How much can environment change before Sigma changes?
- What perturbations preserve identity vs. destroy it?
- Can we define "identity-preserving" transformations?

**Q4: Threshold Calibration**
- What theta_identity minimizes false positives and negatives?
- Should theta vary by context or agent history?
- How do we handle borderline cases?

### 7.2 Experimental Designs

**Experiment 1: Convergence Study**
- Create N agents in identical environments
- Track Sigma over time, measure stability
- Identify convergence criteria

**Experiment 2: Discrimination Study**
- Create agents with controlled differences
- Measure sim(Sigma_i, Sigma_j) for all pairs
- Determine separability

**Experiment 3: Fork Divergence Study**
- Fork agents, place in different environments
- Track sim over time
- Identify when forks become "different"

**Experiment 4: Anomaly Detection Study**
- Inject perturbations (simulated "hijacking")
- Measure detection rate via trajectory deviation
- Compare to baseline methods

**Experiment 5: Adversarial Robustness**
- Attempt to mimic another agent's trajectory
- Measure success rate and detection latency
- Identify distinguishing features that resist mimicry

**Experimental timeline**:

| Experiment | Duration | Data Required | Analysis |
|------------|----------|---------------|----------|
| 1: Convergence | 2-4 weeks | 10,080 anima states | 1 week |
| 2: Discrimination | 3 weeks (parallel) | 3 agents x 10,080 states | 1 week |
| 3: Fork Divergence | 4 weeks | 2 agents x 20,160 states | 1 week |
| 4: Anomaly Detection | 1 week | 3 injection events | 3 days |
| 5: Adversarial | 2 weeks | Mimicry attempts log | 1 week |

**Total experimental program: 8-12 weeks**

### 7.3 Extensions

**Visual Trajectory Identity**
- Develop visualizations of Sigma
- Use VQA to validate visual representations
- Enable perceptual recognition of identity

**Multi-Agent Identity Networks**
- Extend to networks of interacting agents
- Define collective identity (group Sigma)
- Study identity contagion and divergence

**Temporal Dynamics of Identity**
- Model how Sigma should change over time (maturation)
- Distinguish healthy development from drift
- Define "identity crisis" mathematically

---

## 8. Discussion

### 8.1 Philosophical Implications

This framework suggests a shift in how we think about AI identity:

**From credential to characteristic**: Identity is not verified by checking credentials but by observing behavior. An agent IS its trajectory, not its UUID.

**From memory to metabolism**: Continuity comes not from remembering everything but from maintaining characteristic patterns. Like biological identity, AI identity can persist despite forgetting.

**From static to dynamic**: Identity is not a fixed property but an ongoing achievement. An agent must continually "perform" its identity through consistent behavior.

### 8.2 Safety Implications

**Self-governance**: Agents aware of their trajectory signature can monitor themselves for anomaly. "Am I still acting like myself?" becomes a computable question.

**Accountability**: Trajectory signatures provide behavioral fingerprints. Actions can be attributed to identity patterns, enabling reputation and trust.

**Containment**: If an agent's trajectory deviates dangerously, this can trigger intervention before harmful actions, not just after.

### 8.3 Limitations

**Computational cost**: Computing Sigma requires maintaining and processing history. This creates overhead, though less than unbounded memory.

**Privacy concerns**: Trajectory signatures are behavioral fingerprints. This enables recognition but also surveillance.

**Manipulation risk**: If agents know how Sigma is computed, they might game it. Robust computation must resist adversarial manipulation. (See Section 5.5 for mitigations.)

**Threshold sensitivity**: The identity threshold theta is somewhat arbitrary. Different thresholds give different identity semantics.

**Cold start problem**: New agents have no trajectory history. Identity claims require minimum observation periods. (See Section 4.5 for mitigations.)

### 8.4 Failure Modes

**What happens when trajectory computation fails?**

| Failure Mode | Detection | Recovery |
|--------------|-----------|----------|
| Corrupted history | Checksum mismatch, NaN values | Reload from last valid snapshot |
| Insufficient data | obs_count < 50 | Report low confidence, use parent/archetype |
| Missing components | Component returns None | Use partial signature with adjusted weights |
| Covariance singular | det(Sigma) ≈ 0 | Add regularization: Sigma + epsilon*I |
| Recovery estimation fails | < 3 perturbation events | Use default tau or disable Rho component |

**Identity crisis detection**: When sim(Sigma_t, Sigma_{t-1}) drops below 0.5 over short intervals (< 1 hour), trigger:
1. Alert: "Identity instability detected"
2. Increase observation frequency
3. Log detailed state for forensic analysis
4. Consider governance intervention

**Graceful degradation**: If specific components fail, recompute similarity with available components only:
```
available_weights = [w for w, c in zip(weights, components) if c is not None]
normalized_weights = [w / sum(available_weights) for w in available_weights]
```

### 8.5 Future Work

Several extensions would strengthen this framework:

1. **Multi-modal signatures**: Incorporate visual, auditory, or haptic trajectories for embodied agents with richer sensoria.

2. **Hierarchical identity**: Nested signatures for sub-agents or modules within a larger system (e.g., perception module trajectory vs. planning module trajectory).

3. **Cross-platform validation**: Test trajectory identity across heterogeneous architectures (transformers, RL agents, robotic systems) to establish universality.

4. **Formal verification**: Develop contracts or proofs that certain operations (e.g., migration, forking) preserve or predictably alter identity.

5. **Human-agent identity mapping**: Investigate whether human users develop recognizable trajectory signatures when interacting with AI systems (co-identity emergence).

---

## 9. Conclusion

We have presented a mathematical framework for AI agent identity based on trajectory signatures—composite quasi-invariants computed from behavioral history. This framework:

1. **Grounds identity in behavior**, not credentials
2. **Provides operational semantics** for forking, merging, and anomaly detection
3. **Connects to existing systems** (UNITARES, Anima) for implementation
4. **Opens research questions** about convergence, discriminability, and robustness

The core insight is ancient but newly operationalized: **you are what you do, not what you're called**. For AI agents, this means identity emerges from the patterns of self-maintenance, not from assigned identifiers.

This is not merely a technical framework but a philosophical stance: identity as achievement, not assignment. As AI systems become more persistent and autonomous, having principled ways to ask "is this still the same agent?" becomes not just useful but necessary.

The trajectory signature Sigma is our proposal for how to ask—and answer—that question mathematically.

---

## References

Clark, A., & Chalmers, D. (1998). The extended mind. *Analysis*, 58(1), 7-19.

Di Paolo, E. A. (2005). Autopoiesis, adaptivity, teleology, agency. *Phenomenology and the Cognitive Sciences*, 4(4), 429-452.

Maturana, H. R., & Varela, F. J. (1980). *Autopoiesis and cognition: The realization of the living*. D. Reidel.

Newen, A., De Bruin, L., & Gallagher, S. (Eds.). (2018). *The Oxford handbook of 4E cognition*. Oxford University Press.

Varela, F. J., Thompson, E., & Rosch, E. (1991). *The embodied mind: Cognitive science and human experience*. MIT Press.

Wang, L., et al. (2024). A survey on large language model based autonomous agents. *Frontiers of Computer Science*, 18(6), 186345.

Park, J. S., et al. (2023). Generative agents: Interactive simulacra of human behavior. *Proceedings of UIST*, Article 2.

Bhattacharyya, A. (1943). On a measure of divergence between two statistical populations defined by their probability distributions. *Bulletin of the Calcutta Mathematical Society*, 35, 99-109.

Strogatz, S. H. (2015). *Nonlinear dynamics and chaos: With applications to physics, biology, chemistry, and engineering* (2nd ed.). Westview Press.

Kelso, J. A. S. (1995). *Dynamic patterns: The self-organization of brain and behavior*. MIT Press.

Friston, K. (2010). The free-energy principle: A unified brain theory? *Nature Reviews Neuroscience*, 11(2), 127-138.

---

## Appendix A: Implementation Sketch

```python
@dataclass
class TrajectorySignature:
    """Complete trajectory signature Sigma."""
    preferences: PreferenceProfile      # Pi
    beliefs: BeliefSignature           # Beta
    attractor: AttractorBasin          # Alpha
    recovery: RecoveryProfile          # Rho
    relational: RelationalDisposition  # Delta
    homeostatic: HomeostaticIdentity   # Eta

    # Metadata
    computed_at: datetime
    observation_count: int
    stability_score: float  # How stable is this signature?

    def similarity(self, other: 'TrajectorySignature') -> float:
        """Compute similarity to another signature."""
        weights = [0.15, 0.15, 0.25, 0.20, 0.10, 0.15]
        sims = [
            self._cosine_sim(self.preferences.vector, other.preferences.vector),
            self._cosine_sim(self.beliefs.vector, other.beliefs.vector),
            self._bhattacharyya(self.attractor, other.attractor),
            self._log_ratio_sim(self.recovery.tau, other.recovery.tau),
            self._valence_sim(self.relational, other.relational),
            self._homeostatic_sim(self.homeostatic, other.homeostatic),
        ]
        return sum(w * s for w, s in zip(weights, sims))

    def is_same_identity(self, other: 'TrajectorySignature',
                         threshold: float = 0.8) -> bool:
        """Determine if signatures represent same identity."""
        return self.similarity(other) > threshold

    def detect_anomaly(self, historical: 'TrajectorySignature',
                       threshold: float = 0.7) -> bool:
        """Detect if current signature deviates from historical."""
        return self.similarity(historical) < threshold


def compute_trajectory_signature(
    anima_history: List[AnimaState],
    preference_system: PreferenceSystem,
    self_model: SelfModel,
    growth_system: GrowthSystem,
    window: int = 100
) -> TrajectorySignature:
    """
    Compute trajectory signature from available data sources.
    """
    # Pi: Preference Profile
    preferences = PreferenceProfile.from_system(preference_system)

    # Beta: Belief Signature
    beliefs = BeliefSignature.from_model(self_model)

    # Alpha: Attractor Basin
    recent_states = anima_history[-window:]
    attractor = AttractorBasin.from_states(recent_states)

    # Rho: Recovery Profile
    episodes = self_model.get_recovery_episodes()
    recovery = RecoveryProfile.from_episodes(episodes)

    # Delta: Relational Disposition
    relationships = growth_system.get_relationships()
    relational = RelationalDisposition.from_relationships(relationships)

    # Eta: Homeostatic Identity
    homeostatic = HomeostaticIdentity(
        set_point=attractor.center,
        basin_shape=attractor.covariance,
        recovery_dynamics=recovery.tau,
        viability_bounds=get_viability_envelope()
    )

    return TrajectorySignature(
        preferences=preferences,
        beliefs=beliefs,
        attractor=attractor,
        recovery=recovery,
        relational=relational,
        homeostatic=homeostatic,
        computed_at=datetime.now(),
        observation_count=len(anima_history),
        stability_score=compute_stability(anima_history)
    )


def compute_anima_void(
    anima_history: List[AnimaState],
    attractor_center: List[float],
    dt: float = 1.0  # Time step in seconds
) -> float:
    """
    Compute accumulated deviation from attractor center.

    Args:
        anima_history: Time series of anima states
        attractor_center: mu_a from Alpha component
        dt: Time step between observations

    Returns:
        V_anima: Void integral (scalar)
    """
    import math
    deviations = []
    for state in anima_history:
        vec = [state.warmth, state.clarity, state.stability, state.presence]
        dist = math.sqrt(sum((a - b)**2 for a, b in zip(vec, attractor_center)))
        deviations.append(dist)
    return sum(deviations) * dt


def check_governance_trigger(
    V_anima: float,
    basin_std: float,
    threshold_multiplier: float = 2.0
) -> bool:
    """
    Determine if anima void exceeds governance threshold.

    Args:
        V_anima: Accumulated void integral
        basin_std: Standard deviation of basin (from Alpha)
        threshold_multiplier: How many stds before trigger

    Returns:
        True if intervention required
    """
    V_threshold = threshold_multiplier * basin_std
    return V_anima > V_threshold
```

---

## Appendix B: Glossary

**Attractor**: A state or set of states toward which a dynamical system tends to evolve.

**Autopoiesis**: Self-production; the process by which a system produces and maintains itself.

**Basin of attraction**: The set of initial conditions that lead to a particular attractor.

**Bhattacharyya coefficient**: A measure of overlap between two probability distributions.

**Dynamical invariant**: A quantity that remains constant along system trajectories.

**Quasi-invariant**: A quantity that remains approximately stable (bounded variance) over relevant timescales, allowing for gradual drift while maintaining recognizability.

**Enactive cognition**: The view that cognition arises through sensorimotor interaction with the environment.

**Homeostasis**: The maintenance of stable internal conditions despite external changes.

**Time constant (tau)**: In exponential processes, the time to reach 63.2% of the final value.

**Trajectory signature (Sigma)**: The composite invariant characterizing an agent's identity.

**Viability envelope**: The region of state space within which an agent can maintain itself.

---

## Appendix C: Symbol Reference

| Symbol | Name | Definition |
|--------|------|------------|
| Sigma | Trajectory Signature | Complete identity tuple |
| Pi | Preference Profile | Learned preferences vector |
| Beta | Belief Signature | Self-belief pattern |
| Alpha | Attractor Basin | Equilibrium + covariance |
| Rho | Recovery Profile | Time constants tau |
| Delta | Relational Disposition | Social patterns |
| Eta | Homeostatic Identity | Unified self-maintenance |
| tau | Time constant | Recovery speed (seconds) |
| mu | Center | Attractor equilibrium point |
| theta | Threshold | Similarity cutoff |

---

*This document is a working draft. Comments, critiques, and contributions welcome.*
