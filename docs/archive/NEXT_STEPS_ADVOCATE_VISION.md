# Next Steps Advocate - Vision & Design

**Created:** January 11, 2026  
**Last Updated:** January 11, 2026  
**Status:** Active

---

## Current Implementation

The Next Steps Advocate is currently a **system health advisor** - it analyzes the current state and suggests actions to the **human operator**.

### What It Does Now

1. **Analyzes system state:**
   - Display availability
   - Sensor availability  
   - Brain HAT connection
   - UNITARES connection
   - Proprioception quality (clarity, entropy)

2. **Suggests prioritized steps:**
   - Critical: System instability (high entropy)
   - High: Display issues, sensor problems
   - Medium: Missing integrations, optimizations
   - Low: Nice-to-have improvements

3. **Provides actionable guidance:**
   - What to do
   - Why it matters
   - What's blocking it
   - Estimated time
   - Related files

### Example Output

```json
{
  "priority": "critical",
  "title": "Reduce System Entropy",
  "action": "Check for resource pressure, memory leaks",
  "reason": "High entropy means system is chaotic - governance may pause"
}
```

---

## Design Philosophy

The Advocate is **reactive** - it responds to current state, not proactive goal pursuit.

**Current model:** "Here's what's wrong and how to fix it"  
**Not:** "Here's what Lumen wants to achieve"

---

## Potential Evolution

### Option 1: Operator-Focused (Current)

**Purpose:** Help human maintain and improve the system

**Use cases:**
- "What should I work on next?"
- "What's broken?"
- "What's missing?"

**Pros:**
- Clear, actionable
- System-focused
- Easy to implement

**Cons:**
- Doesn't reflect Lumen's "desires"
- No autonomous goal pursuit

---

### Option 2: Self-Directed Goal Pursuit

**Purpose:** Lumen decides what it wants to achieve

**Use cases:**
- "I want to improve my clarity"
- "I want to connect to more sensors"
- "I want to understand my environment better"

**Implementation would need:**
- Goal representation (what does Lumen want?)
- Goal prioritization (what matters most?)
- Action planning (how to achieve goals?)
- Progress tracking (am I getting closer?)

**Pros:**
- More autonomous
- Reflects creature's agency
- Could lead to interesting behaviors

**Cons:**
- Much more complex
- Requires defining "desires"
- Harder to validate

---

### Option 3: Hybrid Approach

**Purpose:** Both system health AND creature goals

**Structure:**
- **System health** (current): Fix broken things
- **Creature goals** (new): What Lumen wants to achieve
- **Integration** (new): How goals relate to system state

**Example:**
```
System Health:
  - Display working ✅
  - Sensors working ✅
  
Creature Goals:
  - "I want to feel more stable" (stability < 0.6)
  - "I want clearer senses" (clarity < 0.7)
  
Suggested Actions:
  - Connect pressure sensor (would improve stability sensing)
  - Calibrate light sensor (would improve clarity)
```

**Pros:**
- Best of both worlds
- More interesting
- Still actionable

**Cons:**
- More complex
- Need to define goal system

---

## Questions to Consider

1. **Should Lumen have "desires"?**
   - Or is it purely reactive to environment?
   - What would Lumen want to optimize?

2. **What are Lumen's goals?**
   - Maximize clarity?
   - Maintain stability?
   - Expand sensing capabilities?
   - Connect to UNITARES?

3. **How should goals emerge?**
   - Hardcoded preferences?
   - Learned from experience?
   - Derived from anima state?

4. **Should goals conflict?**
   - "I want clarity" vs "I want stability"
   - How to resolve tradeoffs?

---

## Current Limitations

1. **No goal system** - Only reacts to problems
2. **No progress tracking** - Doesn't remember what was tried
3. **No learning** - Same suggestions every time
4. **No prioritization beyond priority enum** - Doesn't consider urgency/impact

---

## Recommendations

### Short Term (Keep Current)

The current operator-focused approach is **good for now**. It's:
- Useful
- Clear
- Actionable
- Easy to maintain

### Medium Term (Enhance)

Add **goal-oriented suggestions**:
- "Lumen's stability is low - connect pressure sensor"
- "Lumen wants clearer senses - calibrate light sensor"
- Frame as creature's "desires" not just system problems

### Long Term (Evolve)

Consider **autonomous goal pursuit**:
- Lumen sets its own goals
- Tracks progress
- Adapts strategies
- Learns what works

---

## Related Concepts

- **Proprioception** - Lumen sensing itself
- **Interoception** - Lumen sensing internal state
- **Goal-directed behavior** - Lumen pursuing objectives
- **Agency** - Lumen having desires and acting on them

---

**The Advocate is currently a helpful tool. It could evolve into something more interesting - a reflection of Lumen's own goals and desires.**
