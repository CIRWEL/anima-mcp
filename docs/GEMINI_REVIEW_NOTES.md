# Gemini Review Notes - stable_creature.py

**Date:** January 11, 2026  
**Reviewer:** Gemini (Selective Review)  
**File:** `stable_creature.py`

---

## Issues Identified

### 1. ⚠️ Blocking Loop Issue (Critical)

**Problem:** `loop.run_until_complete()` inside `while running:` loop blocks everything.

**Impact:**
- Governance check timeout (5s) = creature freezes for 5s
- No sensor reads during freeze
- No face updates during freeze
- Network flakes cause repeated freezes

**Location:** Lines 93, 95

**Current Code:**
```python
is_available = loop.run_until_complete(bridge.check_availability())
decision = loop.run_until_complete(bridge.check_in(anima, readings))
```

**Recommendation:** Use async/await properly or run governance checks in background thread.

---

### 2. ⚠️ Resource Leak Potential

**Problem:** Event loop created but if `UnitaresBridge` creates `aiohttp.ClientSession` that isn't closed properly, rapid restarts could leak file descriptors.

**Impact:** Memory/file descriptor leaks over time

**Mitigation:** Bridge uses context managers (should be fine), but worth monitoring.

---

### 3. ✅ Display Flickering (Already Fixed)

**Status:** Already using ANSI codes (`\033[2J\033[H`)

**Current:** Line 106 uses proper ANSI escape codes
**Note:** Gemini may improve further, but current implementation is good.

---

### 4. ⚠️ I2C Concurrency Issue (RESOLVED)

**Problem:** If `stable_creature.py` and `anima-mcp` server both run, they'll fight for I2C bus.

**Impact:** Sensor read failures, hangs, conflicts, **potential Pi crashes**

**Status:** ✅ **RESOLVED** (temporary) - Added startup check in `stable_creature.py`
- Script now checks for running `anima --sse` processes at startup
- Exits immediately with clear error message if detected
- Prevents I2C conflicts before sensors are initialized
- Prominent warning added to file header and README

**Current Solution:** 
- ✅ **Implemented:** Startup check prevents simultaneous execution
- Still recommended: Don't run both simultaneously (now enforced)

**Future Solution:** Hardware Broker Pattern (see `docs/architecture/HARDWARE_BROKER_PATTERN.md`)
- One process owns I2C bus (broker)
- Other processes read from shared memory
- Allows both scripts to run simultaneously
- More complex but eliminates conflicts entirely

---

## Gemini's Action Plan

Gemini plans to:
1. Fix display flickering (though already using ANSI codes)
2. Sign off to let Claude handle network/MCP tasks

---

## Coordination

- **Gemini**: Review and quick fixes
- **Claude**: Network/MCP connection work (current priority)
- **Composer**: Implementation/deployment (ready to help)

---

**Good catch on the blocking loop issue - that's a real problem!**
