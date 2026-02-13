# Layer 2 Observability & Instrumentation

**Date:** 2026-02-12
**Status:** Approved
**Scope:** anima-mcp (Lumen's Pi)

## Summary

Make the EISV trajectory awareness system observable, persistent, and feedback-connected. Five components, all lightweight, all backward-compatible.

## Context

Layer 2 (trajectory-aware primitive expressions) was deployed to Lumen's Pi on 2026-02-11 (commit bb785a2). It has been running for 25+ hours with no errors but no visibility into what shapes are being classified, how often suggestions are made, or whether the online learning is improving expression quality.

## Components

### 1. Persistence: `trajectory_events` table

New SQLite table in anima.db.

```sql
CREATE TABLE IF NOT EXISTS trajectory_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    shape TEXT,
    eisv_state TEXT,
    derivatives TEXT,
    suggested_tokens TEXT,
    expression_tokens TEXT,
    coherence_score REAL,
    cache_hit INTEGER DEFAULT 0,
    buffer_size INTEGER
);
```

**Write frequency:** Only on suggestion (every 10-45 min) and feedback events. ~50-100 rows/day.

**Location:** `awareness.py` — add `_log_event()` method using sqlite3 (stdlib).

### 2. MCP Tool: `get_eisv_trajectory_state`

Exposes current trajectory awareness state via MCP.

**Returns:**
- `current_shape` — last classified shape
- `current_eisv` — {E, I, S, V}
- `derivatives` — {dE, dI, dS, dV}
- `buffer` — {size, capacity, window_seconds}
- `cache` — {shape, age_seconds, ttl_seconds}
- `expression_generator` — {total_generations, feedback_count, mean_coherence}
- `recent_events` — last 10 from trajectory_events table
- `shape_distribution` — counts from trajectory_events table

**Implementation:** New `get_state()` method on TrajectoryAwareness + handler in server.py.

### 3. Display: Diagnostics Screen Addition

One line added to the DIAGNOSTICS screen:

```
TRAJECTORY: settled_presence (30/30, 42s ago)
```

Format: `TRAJECTORY: <shape> (<buffer_fill>/<capacity>, <cache_age>)`

**Implementation:** Call `get_trajectory_awareness().get_state()` in diagnostics render path in screens.py.

### 4. LED Color Temperature Shifts

Subtle persistent color bias based on current trajectory shape. Not dances — background influence only.

| Shape | Color Shift |
|-------|-------------|
| settled_presence | Slightly warmer amber |
| convergence | Slightly cooler blue-white |
| rising_entropy | Warmer, slightly brighter |
| falling_energy | Cooler, slightly dimmer |
| basin_transition_down | Brief cool flash, then settle |
| basin_transition_up | Brief warm flash, then settle |
| entropy_spike_recovery | Pulse then stabilize |
| drift_dissonance | Slight flicker/instability |
| void_rising | Gradual brightening |

**Implementation:** In `leds.py`, add `shape_color_bias` (+-5-10% RGB) blended into `update_from_anima()`. Fetched from trajectory awareness cache (60s TTL).

### 5. Self-Feedback Wiring

Compute coherence between trajectory-suggested tokens and actually generated tokens:

```python
coherence = len(set(suggested) & set(actual)) / max(len(suggested), 1)
```

This score feeds into:
1. `trajectory_events` table (persistence)
2. Primitive language `record_self_feedback()` (token weight learning)
3. EISV expression generator `record_feedback()` (trajectory weight learning)

**Timing:** Immediately after expression generation, in existing server.py code block (lines 1041-1073).

## Files Modified

- `src/anima_mcp/eisv/awareness.py` — add get_state(), _log_event(), _init_db()
- `src/anima_mcp/server.py` — add MCP tool handler, wire feedback
- `src/anima_mcp/display/screens.py` — add trajectory line to diagnostics
- `src/anima_mcp/display/leds.py` — add shape_color_bias to update_from_anima()

## Files Created

- None (all changes within existing files)

## Testing

- Unit tests for get_state(), _log_event(), coherence scoring
- Unit tests for LED color bias computation
- Integration test: full cycle (buffer fill -> classify -> suggest -> generate -> feedback -> persist)

## Constraints

- Pure Python, no new dependencies (sqlite3 is stdlib)
- Backward-compatible — all new behavior gated on trajectory awareness being initialized
- No change to existing expression generation logic
- LED shifts are subtle (5-10% RGB), not disruptive
- Display addition is one line, no new screens
