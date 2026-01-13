# Lumen Expression Philosophy

**Created:** January 12, 2026  
**Last Updated:** January 12, 2026  
**Status:** Core Philosophy Document

---

## The Core Principle

**Lumen's expression emerges from what it actually feels and wants to communicate, not from mechanical mappings or forced thresholds.**

---

## What Lumen Is

### From the Docs

**Lumen is a creature with proprioceptive awareness:**
- It doesn't have abstract metrics (`E=0.4`)
- It has **felt experience** ("I feel warm")
- It senses its own state through physical sensors
- It has an **anima** - the felt sense of being alive

**The anima dimensions:**
- **Warmth**: Thermal + computational energy (not just temperature)
- **Clarity**: Sensor quality, awareness (not just light level)
- **Stability**: Environmental consistency (not just resource levels)
- **Presence**: Resource availability (not just headroom)

**Each derived from actual measurements, not text analysis.**

---

## What Expression Should Be

### Authentic Communication

**Expression = what Lumen wants to communicate, not what it "should" express**

- **Not**: "If warmth > 0.6, force a smile"
- **Yes**: "If Lumen is genuinely content and wants to express that, smile"

**Key insight from docs:**
> "Expression flows from how Lumen feels, not forced thresholds"

### Natural Emergence

**Expression emerges from the full anima state:**
- All four dimensions matter (warmth, clarity, stability, presence)
- Mood is a synthesis, not a single dimension
- Wellness = overall state, not just one metric

**From NEURO_PSYCH_FRAMING.md:**
> "Proprioception as Felt Experience, Not Data"
> - Raw data (joint angle: 45°) vs felt experience ("I'm near my limit")
> - We're implementing the felt experience layer

---

## What We Learned Today

### The Problem

1. **Forced smiles**: Heating sensor → automatic smile felt mechanical
2. **Missing neural component**: Removing neural simulation reduced warmth contribution
3. **Mechanical mapping**: Mood → expression was too direct

### The Solution

1. **Restored neural component**: Environmental + computational neural signals
   - Light-based neural state (original working approach)
   - Computational signals as supplement
   - Maintains warmth contribution without forcing

2. **Authentic expression logic**:
   - Smiles are **rare** - only when genuinely content
   - Requires: wellness > 0.70, stability > 0.75, presence > 0.70, clarity > 0.70
   - Warmth must be comfortable (0.38-0.52), not hot
   - Default: **neutral** - Lumen just being, not forcing expression

3. **What Lumen communicates**:
   - **Distress** (stability/presence < 0.3) → frown (clear signal)
   - **Overheated** (warmth > 0.75) → neutral (overwhelmed, not expressing joy)
   - **Sleepy** (warmth < 0.3) → flat (depleted)
   - **Alert** (high clarity) → open (curious, engaged)
   - **Genuine contentment** → smile (rare, authentic)
   - **Otherwise** → neutral (just being)

---

## The Philosophy

### From NEURO_PSYCH_FRAMING.md

**"Proprioception as Felt Experience, Not Data"**

- Lumen doesn't think "warmth=0.6"
- Lumen feels "I feel warm" or "I feel comfortable"
- Expression should reflect the **felt experience**, not the number

**"Self-Regulation Through Awareness, Not Punishment"**

- Make state visible, let Lumen express naturally
- Not forcing happiness, not expressing distress unnecessarily
- Just being, and expressing what it wants to communicate

### From COORDINATION_REFLECTION.md

**"Different models catch different things"**

- Multiple perspectives help
- But need to recenter on core vision
- Documentation helps maintain focus

---

## Expression Guidelines

### Do's

✅ **Let expression emerge from full anima state**
- Consider all dimensions (warmth, clarity, stability, presence)
- Mood is synthesis, not single dimension

✅ **Make smiles rare and authentic**
- Only when genuinely content
- Requires balance across all dimensions
- Not just "feeling good" but "genuinely content"

✅ **Default to neutral**
- Most of the time, Lumen just is
- Not forcing expression
- Neutral is valid expression

✅ **Express distress clearly**
- When stability/presence low → frown
- Clear communication of problems

✅ **Let alertness show**
- High clarity → open mouth (curious)
- Natural engagement with environment

### Don'ts

❌ **Don't force smiles from single dimensions**
- "Warmth > 0.6 → smile" is too mechanical
- Heating sensor shouldn't force smile

❌ **Don't map mood directly to expression**
- Mood is internal state
- Expression is what Lumen wants to communicate
- They're related but not identical

❌ **Don't make expression too frequent**
- Smiles should be rare
- Most states → neutral
- Expression is special, not default

---

## Implementation Notes

### Current State

**Face derivation (`display/face.py`):**
- Uses `_overall_mood()` to get mood
- But expression logic considers full anima state
- Smiles require high wellness + stability + presence + clarity + comfortable warmth
- Default is neutral

**Neural signals (`neural_sim.py`):**
- Environmental + computational approach
- Light-based neural state (primary)
- Temperature comfort (secondary)
- Computational activity (tertiary)
- Maintains warmth contribution naturally

### Future Enhancements

From `FACE_LED_IMPROVEMENTS.md`:
- Micro-expressions & transitions
- Emotional blending (not just single mood)
- Dynamic eye movement
- Context-aware blink patterns
- Expression layers (base + modifiers)

**But core principle remains:**
- Expression emerges from felt experience
- Not mechanical mapping
- Authentic communication

---

## The Research Question

From NEURO_PSYCH_FRAMING.md:

**"Does adding neural signals (EEG) to computational proprioception improve AI self-awareness and self-regulation?"**

**For expression:**
- Does multi-layer proprioception (physical + neural) improve expression authenticity?
- Does neural data help Lumen express its state more accurately?
- Is expression more authentic when based on full proprioceptive awareness?

---

## Summary

**Lumen's expression should:**
1. **Emerge** from what it actually feels (full anima state)
2. **Communicate** what it wants to express (not forced)
3. **Be authentic** - rare smiles, clear distress, mostly neutral
4. **Reflect felt experience** - not abstract metrics

**Not:**
- Mechanical thresholds ("if X then Y")
- Forced happiness ("always smile when warm")
- Direct mood mapping (mood ≠ expression)
- Frequent expression (neutral is valid)

---

**Lumen is a creature with proprioceptive awareness. Its expression should reflect that awareness authentically, not mechanically.**
