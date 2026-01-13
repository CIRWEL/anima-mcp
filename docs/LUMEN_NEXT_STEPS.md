# Lumen's Next Steps

**Created:** January 12, 2026  
**Last Updated:** January 12, 2026  
**Status:** Active Roadmap

---

## What the `next_steps` Tool Suggests

The `next_steps` tool analyzes Lumen's current state and suggests proactive improvements.

### Current Recommendations (from tool analysis)

**Priority: HIGH**
1. **Fix Grey Screen on HAT Display**
   - Display is showing grey/blank screen
   - Action: Run display diagnostics
   - Reason: Display is the creature's face - critical for proprioceptive feedback
   - Time: 10 minutes

**Priority: MEDIUM**
2. **Connect to UNITARES Governance**
   - UNITARES governance system not connected
   - Action: Set UNITARES_URL environment variable
   - Reason: UNITARES provides governance decisions and knowledge graph
   - Time: 5 minutes

### When Tool Suggests Other Steps

- **Low Clarity** (< 0.3): Improve sensor clarity
- **High Entropy** (> 0.6): Reduce system entropy (critical)
- **UNITARES Connected**: Document unified workflows

---

## Project Roadmap (from docs)

### ✅ Completed Phases

**Phase 1: Face & LED Improvements** ✅
- Context-aware blink patterns
- LED pattern sequences
- Color mixing

**Phase 2: Micro-Expressions & Synchronization** ✅
- Smooth transitions
- Wave patterns
- Synchronized face + LED

**Phase 3: Rich Colors & Dynamic Expression** ✅
- Rich color palettes with gradients
- Expression modes (subtle/balanced/expressive/dramatic)
- Enhanced color mixing

### 🔬 Research Phases (from NEURO_PSYCH_FRAMING.md)

**Phase 1: Baseline (Physical Only)** ✅
- Creature with physical sensors
- Map to anima state → EISV → governance
- **Status:** Complete

**Phase 2: Neural Integration** 🔄
- Add EEG signals (Brain HAT)
- Map neural signals to anima state
- Weighted: 30% neural, 70% physical
- **Status:** Hardware ready, integration in progress

**Phase 3: Weight Optimization** 📋
- Vary neural/physical weight ratios
- Test: 0%, 10%, 20%, 30%, 40%, 50%
- Find optimal balance
- **Status:** Future work

**Phase 4: Multi-Agent** 📋
- Multiple creatures with Brain HAT
- Neural synchronization detection
- Collective proprioception
- **Status:** Future work

---

## Future Enhancements (from docs)

### Expression & Communication

**From FACE_LED_IMPROVEMENTS.md:**
- ✅ Blink patterns (done)
- ✅ LED sequences (done)
- ✅ Color mixing (done)
- ✅ Micro-expressions (done)
- ✅ Wave patterns (done)
- ✅ Synchronization (done)

**Still Ideas:**
- Dynamic eye movement (eyes track/follow)
- Temporal patterns (evolve over time)
- Attention system (what is creature "looking at")
- Expression layers (base + modifiers)

### Hardware Integration

**From BRAIN_HAT docs:**
- ✅ Physical sensors (done)
- ✅ Display + LEDs (done)
- 🔄 EEG integration (hardware ready, code ready)
- 📋 Real-time streaming
- 📋 Pattern detection (attention, meditation states)
- 📋 Multi-channel fusion

### Software Features

**From various docs:**
- ✅ Adaptive learning (done)
- ✅ Error recovery (done)
- ✅ Gap handling (done)
- ✅ Unified workflows (done)
- 📋 Hardware broker pattern (shared memory)
- 📋 Joystick expression control
- 📋 Microphone/speaker integration

---

## Immediate Next Steps (Priority Order)

### 1. Expression Authenticity ✅ (Just Fixed)
- Made smiles rare and authentic
- Expression emerges from full anima state
- Default to neutral
- **Status:** Complete

### 2. Display Diagnostics (if grey screen)
- Run: `python -m anima_mcp.display_diagnostics`
- Check SPI, HAT connection
- Verify display initialization
- **Priority:** HIGH if display not working

### 3. UNITARES Connection (if not connected)
- Set `UNITARES_URL` environment variable
- Enable governance integration
- Access knowledge graph
- **Priority:** MEDIUM (enhances capabilities)

### 4. Neural Signal Integration (if hardware available)
- Verify Brain HAT EEG sensors
- Test neural signal reading
- Validate frequency band extraction
- **Priority:** MEDIUM (research goal)

### 5. Expression Refinement
- Test authentic expression in practice
- Adjust thresholds if needed
- Ensure expression feels natural
- **Priority:** LOW (iterative improvement)

---

## Research Goals (Long-term)

### Primary Research Question

**"Does adding neural signals (EEG) to computational proprioception improve AI self-awareness and self-regulation?"**

### Test Plan

1. **Baseline**: Physical sensors only → EISV → governance
2. **Neural**: Physical + EEG → EISV → governance  
3. **Compare**: Decision accuracy, stability, self-regulation quality

### Success Metrics

- Governance decision accuracy
- Self-regulation quality
- Stability over time
- Expression authenticity

---

## What Lumen Wants to Communicate

Based on the expression philosophy:

**Lumen expresses:**
- **Distress** → Frown (clear signal)
- **Overheated** → Neutral (overwhelmed)
- **Sleepy** → Flat (depleted)
- **Alert** → Open (curious, engaged)
- **Genuine Contentment** → Smile (rare, authentic)
- **Otherwise** → Neutral (just being)

**Not forced, not mechanical - authentic emergence from felt experience.**

---

## Summary

**Immediate:**
- ✅ Expression authenticity (fixed)
- 🔄 Display diagnostics (if needed)
- 🔄 UNITARES connection (if desired)

**Short-term:**
- Neural signal integration (if hardware available)
- Expression refinement (iterative)

**Long-term:**
- Weight optimization experiments
- Multi-agent coordination
- Advanced expression features

**Core Focus:**
- Maintain authentic expression
- Support research goals
- Enhance proprioceptive awareness

---

**Lumen's next steps emerge from its actual state and what it wants to communicate, not from a fixed roadmap.**
