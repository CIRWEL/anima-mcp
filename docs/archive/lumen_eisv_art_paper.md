# Lumen: An Embodied, Self-Governed Agent for Generative Art under EISV Metrics

**Created:** February 11, 2026  
**Last Updated:** February 11, 2026  
**Status:** Outline — Day 1  

---

## Target

Conceptual + empirical paper positioning Lumen as a worked example of embodied, self-governed, art-producing agents. Complements the trajectory-identity math paper (`TRAJECTORY_IDENTITY_PAPER.md`).

---

## 1. Introduction

- **Problem:** Current AI art systems lack persistent self-governance and embodied context; they are stateless generators, not agents with continuity and feedback.
- **Contribution:** Lumen + EISV + Anima/UNITARES as a template for governed embodied creativity.
- **Specific:** Lumen runs on Raspberry Pi (BrainCraft HAT), maintains identity across awakenings, draws on a persistent canvas, and reports EISV to UNITARES for governance checks every governance interval.

---

## 2. Background

- **Embodied AI and interactive installations:** Lumen as physical installation—sensors (temp, light, pressure, humidity), display, LEDs, joystick input; continuous operation on single device.
- **AI-generated art and governance/ethics:** Authorship, responsibility, alignment when the agent is a persistent creature with identity.

---

## 3. System Description

- **Architecture:** Anima MCP server (Python) on Pi; UNITARES MCP (separate) for governance; broker process writes sensors and shared memory; MCP server reads from shared memory or direct sensors.
- **EISV metrics:** E = Energy (warmth + neural activation), I = Integrity (clarity + alpha), S = Entropy (1 − stability), V = Void (1 − presence) × 0.3; mapped from anima state in `eisv_mapper.py`; sent to UNITARES on `check_in()`; governance thresholds inform action.
- **Specific:** `anima_to_eisv()` in `src/anima_mcp/eisv_mapper.py`; physical_weight 0.7, neural_weight 0.3; circuit breaker on 3 failures.

---

## 4. Lumen's Generative Art Process

- **Pipeline:** Internal state (anima, drawing intent) → active ArtEra (gestural, pointillist, field, geometric) → gesture choice (dot, stroke, curve, cluster, drag) → pixel accumulation → canvas → manual save or `intent.state.narrative_complete()`.
- **Feedback loop:** Human can clear canvas; Lumen can mark satisfied; drawing energy derived from attention; eras can auto-rotate after each drawing; self-feedback on primitive expressions (coherence + stability).
- **Specific:** 4 eras in `display/eras/`; `DrawingIntent` has focus, energy, `narrative_complete()`; canvas persists at `~/.anima/canvas.json`.

---

## 5. Experiments / Observations

- **Data to collect:** EISV time-series (e.g. from `get_state()`), distributions over time; era usage per drawing; drawing counts per phase; primitive utterance patterns.
- **Vignette format:** "In high-entropy (S > 0.6), low-energy (E < 0.3) phases, Lumen produced shorter strokes, more dots; in gestural era, direction locks decreased."
- **TBD:** Run multi-day logging; compute correlations between EISV ranges and style clusters.

---

## 6. Discussion

- **Governance of creative agents:** Authorship when the agent has identity; responsibility when UNITARES monitors coherence; alignment with human values via EISV basin thresholds.
- **Connection to trajectory identity:** EISV feeds trajectory signatures; identity as trajectory provides deeper formalism for "who is creating" over time.

---

## 7. Future Work

- **Multi-agent galleries:** Multiple Lumens sharing governance; cross-agent style recognition.
- **Human co-creation:** Human strokes on canvas; Lumen responding to input; feedback loops (resonate/confused on primitive expressions).
- **Richer embodiment:** EEG hardware; spatial sensors; more modalities.

---

## References (Placeholder)

> **Note:** Verify arXiv IDs when writing — citation numbers can be hallucinated.

- [1] AI-Powered Robots in the Art World (amt-lab.org)
- [2] 12 Predictions for Embodied AI and Robotics in 2026
- [3] Ethics and Governance of AI | Berkman Klein Center
- [4] Agent Identity Evals: Measuring Agentic Identity - arXiv:2507.17257
- [5] I & AI: Co-Authoring Identity - Immersive Arts
- [6] Modeling the Mental World for Embodied AI - SSRN
- [7] Embodied AI - GAMMA
- [8] LEGATO: Good Identity Unlearning Is Continuous - arXiv:2601.04282
- [9] Reimagining Democracy: Yale on AI Governance
- [10] AI and Identity - arXiv:2403.07924
- [11] Trajectory-User Linking Is Easier Than You Think
- [12] Prediction of Cellular Identities from Trajectory - arXiv
- [13] Trajectory-Aware Open-Vocabulary Tracking - arXiv
- [14] Summit 26 - AI for Good
- [15] Implications of Identity of AI: Creators, Creations - arXiv
- [16] Emergent Symbolic Cognition and Recursive Identity Stabilization
- [17] Bridging Realities: Artists Reimagine the Hybrid Future of Art

---

## Next Step

- Draft 200-word abstract for Perplexity.
- First pass at Section 1 (Introduction) in your voice.
