# Layer 2 Observability & Instrumentation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Lumen's EISV trajectory awareness observable, persistent, and feedback-connected.

**Architecture:** Add event persistence (SQLite), an MCP query tool, a diagnostics display line, subtle LED color shifts, and coherence-based self-feedback wiring — all inside the existing anima-mcp codebase with zero new dependencies.

**Tech Stack:** Python 3.11, sqlite3 (stdlib), existing anima-mcp display/LED/primitive-language systems.

---

### Task 1: Persistence — `_init_db()` and `_log_event()` in awareness.py

**Files:**
- Modify: `src/anima_mcp/eisv/awareness.py`
- Test: `tests/test_eisv_awareness.py`

**Step 1: Write failing tests for persistence**

Add to `tests/test_eisv_awareness.py`:

```python
import json
import os
import sqlite3
import tempfile


class TestPersistence:
    def setup_method(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db_path = self.tmp.name

    def teardown_method(self):
        os.unlink(self.db_path)

    def test_init_db_creates_table(self):
        ta = TrajectoryAwareness(buffer_size=30, db_path=self.db_path)
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trajectory_events'")
        assert cur.fetchone() is not None
        conn.close()

    def test_log_event_writes_row(self):
        ta = TrajectoryAwareness(buffer_size=30, db_path=self.db_path)
        ta._log_event(
            event_type="suggestion",
            shape="settled_presence",
            eisv_state={"E": 0.5, "I": 0.7, "S": 0.2, "V": 0.1},
            derivatives={"dE": 0.01, "dI": 0.0, "dS": -0.01, "dV": 0.0},
            suggested_tokens=["warm", "feel"],
            buffer_size=10,
        )
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("SELECT * FROM trajectory_events").fetchall()
        assert len(rows) == 1
        conn.close()

    def test_log_event_no_db_path_is_noop(self):
        ta = TrajectoryAwareness(buffer_size=30)  # No db_path
        # Should not raise
        ta._log_event(event_type="suggestion", shape="settled_presence")

    def test_suggestion_logs_event(self):
        ta = TrajectoryAwareness(buffer_size=30, seed=42, db_path=self.db_path)
        for i in range(10):
            ta._buffer.append({"t": float(i), "E": 0.7, "I": 0.7, "S": 0.2, "V": 0.1})
        result = ta.get_trajectory_suggestion()
        assert result is not None
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("SELECT event_type, shape FROM trajectory_events").fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "classification"
        assert rows[0][1] == "settled_presence"
        conn.close()

    def test_feedback_logs_event(self):
        ta = TrajectoryAwareness(buffer_size=30, seed=42, db_path=self.db_path)
        for i in range(10):
            ta._buffer.append({"t": float(i), "E": 0.7, "I": 0.7, "S": 0.2, "V": 0.1})
        ta.get_trajectory_suggestion()
        ta.record_feedback(["~stillness~"], 0.8)
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("SELECT event_type FROM trajectory_events").fetchall()
        types = [r[0] for r in rows]
        assert "feedback" in types
        conn.close()

    def test_cache_hit_does_not_log_again(self):
        ta = TrajectoryAwareness(buffer_size=30, seed=42, db_path=self.db_path)
        for i in range(10):
            ta._buffer.append({"t": float(i), "E": 0.7, "I": 0.7, "S": 0.2, "V": 0.1})
        ta.get_trajectory_suggestion()
        ta.get_trajectory_suggestion()  # Cache hit
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("SELECT event_type FROM trajectory_events").fetchall()
        assert len(rows) == 1  # Only one classification, not two
        conn.close()
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/cirwel/projects/anima-mcp && python -m pytest tests/test_eisv_awareness.py::TestPersistence -v`
Expected: FAIL — `TypeError: TrajectoryAwareness() got an unexpected keyword argument 'db_path'`

**Step 3: Implement persistence in awareness.py**

Modify `src/anima_mcp/eisv/awareness.py`:

1. Add `import json, sqlite3` at top
2. Add `db_path: Optional[str] = None` to `__init__()` — store as `self._db_path`
3. Add `_init_db()` method:
```python
def _init_db(self) -> None:
    if self._db_path is None:
        return
    try:
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
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
            )
        """)
        conn.commit()
        conn.close()
    except Exception:
        self._db_path = None  # Disable persistence on error
```
4. Call `self._init_db()` at end of `__init__()`
5. Add `_log_event()` method:
```python
def _log_event(self, event_type: str, shape: str = None,
               eisv_state: dict = None, derivatives: dict = None,
               suggested_tokens: list = None, expression_tokens: list = None,
               coherence_score: float = None, cache_hit: bool = False,
               buffer_size: int = None) -> None:
    if self._db_path is None:
        return
    try:
        from datetime import datetime, timezone
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            """INSERT INTO trajectory_events
               (timestamp, event_type, shape, eisv_state, derivatives,
                suggested_tokens, expression_tokens, coherence_score,
                cache_hit, buffer_size)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                event_type,
                shape,
                json.dumps(eisv_state) if eisv_state else None,
                json.dumps(derivatives) if derivatives else None,
                json.dumps(suggested_tokens) if suggested_tokens else None,
                json.dumps(expression_tokens) if expression_tokens else None,
                coherence_score,
                1 if cache_hit else 0,
                buffer_size,
            )
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # Never break main loop for logging
```
6. In `get_trajectory_suggestion()`, after successful classification (line ~143-158), add logging:
```python
# Log classification event
self._log_event(
    event_type="classification",
    shape=shape.value,
    eisv_state={d: states[-1].get(d, 0.0) for d in ("E", "I", "S", "V")},
    derivatives={f"d{d}": window["derivatives"][-1].get(f"d{d}", 0.0) for d in ("E", "I", "S", "V")} if window["derivatives"] else None,
    suggested_tokens=lumen_tokens,
    buffer_size=len(self._buffer),
)
```
7. In `record_feedback()`, add logging after weight update:
```python
self._log_event(
    event_type="feedback",
    shape=self._current_shape,
    expression_tokens=tokens,
    coherence_score=score,
)
```
8. Also add tracking counters: `self._total_generations = 0`, `self._total_feedback = 0`, `self._coherence_sum = 0.0` in `__init__()`. Increment in suggestion and feedback methods.

**Step 4: Run tests to verify they pass**

Run: `cd /Users/cirwel/projects/anima-mcp && python -m pytest tests/test_eisv_awareness.py -v`
Expected: All tests pass (existing 25 + new 6 = 31)

**Step 5: Commit**

```bash
git add src/anima_mcp/eisv/awareness.py tests/test_eisv_awareness.py
git commit -m "feat(eisv): add trajectory event persistence to SQLite"
```

---

### Task 2: `get_state()` method on TrajectoryAwareness

**Files:**
- Modify: `src/anima_mcp/eisv/awareness.py`
- Test: `tests/test_eisv_awareness.py`

**Step 1: Write failing tests**

Add to `tests/test_eisv_awareness.py`:

```python
class TestGetState:
    def test_get_state_empty_buffer(self):
        ta = TrajectoryAwareness(buffer_size=30)
        state = ta.get_state()
        assert state["current_shape"] is None
        assert state["buffer"]["size"] == 0
        assert state["buffer"]["capacity"] == 30

    def test_get_state_with_data(self):
        ta = TrajectoryAwareness(buffer_size=30, seed=42)
        for i in range(10):
            ta._buffer.append({"t": float(i), "E": 0.7, "I": 0.7, "S": 0.2, "V": 0.1})
        ta.get_trajectory_suggestion()
        state = ta.get_state()
        assert state["current_shape"] == "settled_presence"
        assert state["buffer"]["size"] == 10
        assert state["current_eisv"]["E"] == 0.7
        assert "cache" in state
        assert state["cache"]["shape"] == "settled_presence"
        assert state["expression_generator"]["total_generations"] >= 1

    def test_get_state_with_recent_events(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        try:
            ta = TrajectoryAwareness(buffer_size=30, seed=42, db_path=tmp.name)
            for i in range(10):
                ta._buffer.append({"t": float(i), "E": 0.7, "I": 0.7, "S": 0.2, "V": 0.1})
            ta.get_trajectory_suggestion()
            state = ta.get_state()
            assert len(state["recent_events"]) >= 1
            assert state["shape_distribution"]["settled_presence"] >= 1
        finally:
            os.unlink(tmp.name)

    def test_get_state_window_seconds(self):
        ta = TrajectoryAwareness(buffer_size=30)
        ta._buffer.append({"t": 100.0, "E": 0.5, "I": 0.5, "S": 0.3, "V": 0.1})
        ta._buffer.append({"t": 160.0, "E": 0.5, "I": 0.5, "S": 0.3, "V": 0.1})
        state = ta.get_state()
        assert state["buffer"]["window_seconds"] == pytest.approx(60.0)
```

**Step 2: Run to verify fail**

Run: `cd /Users/cirwel/projects/anima-mcp && python -m pytest tests/test_eisv_awareness.py::TestGetState -v`
Expected: FAIL — `AttributeError: 'TrajectoryAwareness' object has no attribute 'get_state'`

**Step 3: Implement get_state()**

Add to `TrajectoryAwareness` class in `awareness.py`:

```python
def get_state(self) -> Dict[str, Any]:
    """Get complete trajectory awareness state for observability."""
    now = time.time()

    # Buffer info
    buf = list(self._buffer)
    window_seconds = (buf[-1]["t"] - buf[0]["t"]) if len(buf) >= 2 else 0.0

    # Current EISV from last buffer entry
    current_eisv = None
    current_derivs = None
    if buf:
        last = buf[-1]
        current_eisv = {d: last.get(d, 0.0) for d in ("E", "I", "S", "V")}

    # Compute derivatives if possible
    if len(buf) >= 2:
        from .mapping import compute_derivatives
        derivs = compute_derivatives(buf)
        if derivs:
            last_d = derivs[-1]
            current_derivs = {k: last_d.get(k, 0.0) for k in ("dE", "dI", "dS", "dV")}

    # Cache info
    cache_info = {
        "shape": self._cached_result.get("shape") if self._cached_result else None,
        "age_seconds": round(now - self._cache_time, 1) if self._cache_time > 0 else None,
        "ttl_seconds": self._cache_seconds,
    }

    # Generator stats
    gen_stats = {
        "total_generations": self._total_generations,
        "feedback_count": self._total_feedback,
        "mean_coherence": round(self._coherence_sum / self._total_feedback, 3) if self._total_feedback > 0 else None,
    }

    # Recent events from DB
    recent_events = []
    shape_distribution = {}
    if self._db_path:
        try:
            conn = sqlite3.connect(self._db_path)
            # Last 10 events
            rows = conn.execute(
                "SELECT timestamp, event_type, shape, suggested_tokens, coherence_score "
                "FROM trajectory_events ORDER BY id DESC LIMIT 10"
            ).fetchall()
            for row in rows:
                recent_events.append({
                    "timestamp": row[0],
                    "event_type": row[1],
                    "shape": row[2],
                    "tokens": json.loads(row[3]) if row[3] else None,
                    "score": row[4],
                })
            # Shape distribution
            dist_rows = conn.execute(
                "SELECT shape, COUNT(*) FROM trajectory_events "
                "WHERE event_type='classification' GROUP BY shape"
            ).fetchall()
            for row in dist_rows:
                shape_distribution[row[0]] = row[1]
            conn.close()
        except Exception:
            pass

    return {
        "current_shape": self._current_shape,
        "current_eisv": current_eisv,
        "derivatives": current_derivs,
        "buffer": {
            "size": len(self._buffer),
            "capacity": self._buffer.maxlen,
            "window_seconds": round(window_seconds, 1),
        },
        "cache": cache_info,
        "expression_generator": gen_stats,
        "recent_events": recent_events,
        "shape_distribution": shape_distribution,
    }
```

**Step 4: Run tests**

Run: `cd /Users/cirwel/projects/anima-mcp && python -m pytest tests/test_eisv_awareness.py -v`
Expected: All pass

**Step 5: Commit**

```bash
git add src/anima_mcp/eisv/awareness.py tests/test_eisv_awareness.py
git commit -m "feat(eisv): add get_state() for trajectory observability"
```

---

### Task 3: MCP Tool — `get_eisv_trajectory_state`

**Files:**
- Modify: `src/anima_mcp/server.py`
- Test: Manual (MCP tools tested via live system)

**Step 1: Add handler function**

In `server.py`, near the existing `handle_get_trajectory` function (~line 3050), add:

```python
async def handle_get_eisv_trajectory_state(arguments: dict) -> list[TextContent]:
    """Get current EISV trajectory awareness state."""
    try:
        _traj = get_trajectory_awareness()
        state = _traj.get_state()
        return [TextContent(type="text", text=json.dumps(state, indent=2, default=str))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]
```

**Step 2: Register the tool**

In the `TOOLS` list (near line 4107, after `get_trajectory`), add:

```python
Tool(
    name="get_eisv_trajectory_state",
    description="Get current EISV trajectory awareness state - shapes, buffer, cache, events, feedback stats",
    inputSchema={
        "type": "object",
        "properties": {},
    },
),
```

In the `TOOL_HANDLERS` dict (near line 5170), add:

```python
"get_eisv_trajectory_state": handle_get_eisv_trajectory_state,
```

**Step 3: Wire db_path to singleton**

In the bootstrap section (~line 5421), update the `get_trajectory_awareness()` call to pass `db_path`:

```python
# Bootstrap trajectory awareness from state history
try:
    _db_path = os.path.join(os.path.expanduser("~"), ".anima", "anima.db")
    _traj = get_trajectory_awareness(db_path=_db_path)
    history = _store.get_recent_state_history(limit=30)
    ...
```

Also update the `get_trajectory_awareness` factory in `awareness.py` to accept and forward `**kwargs` (already does).

**Step 4: Run full test suite**

Run: `cd /Users/cirwel/projects/anima-mcp && python -m pytest tests/ -v --timeout=30`
Expected: All pass

**Step 5: Commit**

```bash
git add src/anima_mcp/server.py
git commit -m "feat(eisv): add get_eisv_trajectory_state MCP tool"
```

---

### Task 4: Coherence Scoring + Self-Feedback Wiring

**Files:**
- Modify: `src/anima_mcp/eisv/awareness.py`
- Modify: `src/anima_mcp/server.py`
- Test: `tests/test_eisv_awareness.py`

**Step 1: Write failing tests for coherence scoring**

Add to `tests/test_eisv_awareness.py`:

```python
from anima_mcp.eisv.awareness import compute_expression_coherence


class TestCoherence:
    def test_full_overlap(self):
        assert compute_expression_coherence(["warm", "feel"], ["warm", "feel"]) == 1.0

    def test_no_overlap(self):
        assert compute_expression_coherence(["warm", "feel"], ["cold", "dim"]) == 0.0

    def test_partial_overlap(self):
        assert compute_expression_coherence(["warm", "feel"], ["warm", "cold"]) == 0.5

    def test_none_suggested(self):
        assert compute_expression_coherence(None, ["warm"]) is None

    def test_empty_suggested(self):
        assert compute_expression_coherence([], ["warm"]) is None
```

**Step 2: Run to verify fail**

Run: `cd /Users/cirwel/projects/anima-mcp && python -m pytest tests/test_eisv_awareness.py::TestCoherence -v`
Expected: FAIL — `ImportError: cannot import name 'compute_expression_coherence'`

**Step 3: Implement coherence function**

Add to `awareness.py` (module-level function):

```python
def compute_expression_coherence(
    suggested_tokens: Optional[List[str]],
    actual_tokens: List[str],
) -> Optional[float]:
    """Compute coherence between trajectory-suggested and actually-generated tokens."""
    if not suggested_tokens:
        return None
    overlap = set(suggested_tokens) & set(actual_tokens)
    return len(overlap) / max(len(suggested_tokens), 1)
```

**Step 4: Wire into server.py**

Modify the expression generation block in `server.py` (~lines 1041-1077). After utterance generation and before the existing self-feedback block:

```python
# Compute trajectory coherence and log
if _suggestion:
    from .eisv.awareness import compute_expression_coherence
    _coherence = compute_expression_coherence(
        _suggestion.get("suggested_tokens"),
        utterance.tokens,
    )
    if _coherence is not None:
        # Log to trajectory events
        try:
            _traj = get_trajectory_awareness()
            _traj._log_event(
                event_type="suggestion",
                shape=_suggestion.get("shape"),
                suggested_tokens=_suggestion.get("suggested_tokens"),
                expression_tokens=utterance.tokens,
                coherence_score=_coherence,
                buffer_size=_traj.buffer_size,
            )
            # Feed coherence back to trajectory weight learning
            _traj.record_feedback(
                _suggestion.get("eisv_tokens", []),
                _coherence,
            )
        except Exception:
            pass
```

**Step 5: Run tests**

Run: `cd /Users/cirwel/projects/anima-mcp && python -m pytest tests/test_eisv_awareness.py -v`
Expected: All pass

**Step 6: Commit**

```bash
git add src/anima_mcp/eisv/awareness.py src/anima_mcp/server.py tests/test_eisv_awareness.py
git commit -m "feat(eisv): add coherence scoring and self-feedback wiring"
```

---

### Task 5: LED Color Temperature Shifts

**Files:**
- Modify: `src/anima_mcp/display/leds.py`
- Test: `tests/test_eisv_awareness.py`

**Step 1: Write failing tests**

Add to `tests/test_eisv_awareness.py`:

```python
from anima_mcp.display.leds import get_shape_color_bias


class TestLEDShapeBias:
    def test_settled_presence_warm(self):
        bias = get_shape_color_bias("settled_presence")
        # Warm amber: positive R, slightly positive G, slightly negative B
        assert bias[0] > 0  # Warmer red
        assert bias[2] <= 0  # Less blue

    def test_convergence_cool(self):
        bias = get_shape_color_bias("convergence")
        # Cool blue-white: positive B
        assert bias[2] > 0

    def test_unknown_shape_zero(self):
        bias = get_shape_color_bias("not_a_shape")
        assert bias == (0, 0, 0)

    def test_none_shape_zero(self):
        bias = get_shape_color_bias(None)
        assert bias == (0, 0, 0)

    def test_all_shapes_small_magnitude(self):
        """All biases should be subtle (<=15 per channel)."""
        from anima_mcp.eisv.mapping import TrajectoryShape
        for shape in TrajectoryShape:
            bias = get_shape_color_bias(shape.value)
            assert all(abs(c) <= 15 for c in bias), f"{shape.value}: {bias} too large"
```

**Step 2: Run to verify fail**

Run: `cd /Users/cirwel/projects/anima-mcp && python -m pytest tests/test_eisv_awareness.py::TestLEDShapeBias -v`
Expected: FAIL — `ImportError: cannot import name 'get_shape_color_bias'`

**Step 3: Implement color bias function in leds.py**

Add near the top of `leds.py` (after existing imports, as a module-level function):

```python
def get_shape_color_bias(shape: Optional[str]) -> Tuple[int, int, int]:
    """Get subtle RGB color bias for a trajectory shape.

    Returns (dr, dg, db) to add to each LED's base color.
    Values are small (±5-15) for subtle influence.
    """
    if shape is None:
        return (0, 0, 0)
    SHAPE_BIASES = {
        "settled_presence":       (8, 4, -4),     # Warmer amber
        "convergence":            (-4, 2, 8),     # Cooler blue-white
        "rising_entropy":         (10, 5, -2),    # Warmer, slightly brighter
        "falling_energy":         (-6, -2, 4),    # Cooler, slightly dimmer
        "basin_transition_down":  (-8, -2, 6),    # Cool flash
        "basin_transition_up":    (10, 4, -2),    # Warm flash
        "entropy_spike_recovery": (4, 6, 4),      # Pulse/brighten
        "drift_dissonance":       (-4, -4, -4),   # Slight dimming
        "void_rising":            (6, 8, 6),      # Gradual brightening
    }
    return SHAPE_BIASES.get(shape, (0, 0, 0))
```

**Step 4: Integrate into `update_from_anima()`**

In `update_from_anima()`, after `derive_led_state()` is called (~line 600-605) and before the color transition code (~line 627), add:

```python
# Apply trajectory shape color bias (subtle influence)
try:
    from ..eisv import get_trajectory_awareness
    _traj = get_trajectory_awareness()
    _shape_bias = get_shape_color_bias(_traj.current_shape)
    if any(b != 0 for b in _shape_bias):
        dr, dg, db = _shape_bias
        state.led0 = (
            max(0, min(255, state.led0[0] + dr)),
            max(0, min(255, state.led0[1] + dg)),
            max(0, min(255, state.led0[2] + db)),
        )
        state.led1 = (
            max(0, min(255, state.led1[0] + dr)),
            max(0, min(255, state.led1[1] + dg)),
            max(0, min(255, state.led1[2] + db)),
        )
        state.led2 = (
            max(0, min(255, state.led2[0] + dr)),
            max(0, min(255, state.led2[1] + dg)),
            max(0, min(255, state.led2[2] + db)),
        )
except Exception:
    pass  # Never break LEDs for trajectory
```

**Step 5: Run tests**

Run: `cd /Users/cirwel/projects/anima-mcp && python -m pytest tests/test_eisv_awareness.py -v`
Expected: All pass

**Step 6: Commit**

```bash
git add src/anima_mcp/display/leds.py tests/test_eisv_awareness.py
git commit -m "feat(eisv): add trajectory shape color bias to LEDs"
```

---

### Task 6: Diagnostics Display — Trajectory Line

**Files:**
- Modify: `src/anima_mcp/display/screens.py`
- Test: Visual verification on Pi (display rendering is hard to unit test)

**Step 1: Add trajectory info to diagnostics screen**

In `screens.py`, in `_render_diagnostics()` (~line 1876, just before the screen indicator dots):

```python
# Trajectory awareness shape
if y_offset < 225:
    try:
        from ..eisv import get_trajectory_awareness
        _traj = get_trajectory_awareness()
        _shape = _traj.current_shape or "..."
        _buf_size = _traj.buffer_size
        _buf_cap = _traj._buffer.maxlen
        import time as _time
        _cache_age = int(_time.time() - _traj._cache_time) if _traj._cache_time > 0 else -1
        _cache_str = f"{_cache_age}s" if _cache_age >= 0 else "n/a"
        _traj_text = f"traj: {_shape} ({_buf_size}/{_buf_cap}, {_cache_str})"
        draw.text((bar_x, y_offset), _traj_text, fill=LIGHT_CYAN, font=font_small)
        y_offset += 14
    except Exception:
        pass
```

Also add trajectory to the text fallback in `_render_diagnostics_text_fallback()` (~line 1892):

```python
# Trajectory
try:
    from ..eisv import get_trajectory_awareness
    _traj = get_trajectory_awareness()
    if _traj.current_shape:
        lines.append(f"traj: {_traj.current_shape}")
except Exception:
    pass
```

**Step 2: Update cache key**

In `_render_diagnostics()` (~line 1693-1698), update the cache key to include trajectory shape:

```python
# Add trajectory shape to cache key
try:
    from ..eisv import get_trajectory_awareness
    _traj_shape = get_trajectory_awareness().current_shape or ""
except Exception:
    _traj_shape = ""
diag_key = (
    f"{anima.warmth:.2f}|{anima.clarity:.2f}|{anima.stability:.2f}|"
    f"{anima.presence:.2f}|{gov_state}|{_traj_shape}"
)
```

**Step 3: Run full test suite**

Run: `cd /Users/cirwel/projects/anima-mcp && python -m pytest tests/ -v --timeout=30`
Expected: All pass (display code paths are guarded by try/except)

**Step 4: Commit**

```bash
git add src/anima_mcp/display/screens.py
git commit -m "feat(eisv): show trajectory shape on diagnostics display"
```

---

### Task 7: Run Full Tests + Deploy to Pi

**Files:** None new

**Step 1: Run complete test suite**

Run: `cd /Users/cirwel/projects/anima-mcp && python -m pytest tests/ -v --timeout=30`
Expected: All tests pass (previous 316 + new ~16 = ~332)

**Step 2: Push to GitHub**

```bash
cd /Users/cirwel/projects/anima-mcp && git push origin main
```

**Step 3: Deploy to Pi**

Use the deploy-to-pi skill:
1. `git_pull(restart=true)` via anima MCP
2. Verify Lumen comes back up via `get_state()`
3. Verify new MCP tool works via `get_eisv_trajectory_state`

**Step 4: Verify observability**

1. Call `get_eisv_trajectory_state` — should show current shape, buffer, cache
2. Wait for next primitive expression generation (~10-25 min)
3. Call again — should show events logged with coherence scores
4. Navigate to DIAGNOSTICS screen — should show trajectory line
