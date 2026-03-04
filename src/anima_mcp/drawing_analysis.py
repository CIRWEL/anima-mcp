"""
Drawing Data Analysis - answers Lumen's correlation questions with actual data.

Provides grounded analysis of drawing patterns, correlations between anima state
and drawing activity, and pre/post drawing effects. Injected into the self-answer
pipeline so Lumen's self-answers reference real numbers instead of philosophy.

Data sources:
- drawing_records table (growth.py) — per-drawing anima state + environment
- state_history table (identity/store.py) — continuous anima state for baselines
- PNG file timestamps — fallback for historical drawings before recording started
"""

import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple


def _get_db_path() -> Path:
    """Get the anima.db path (same as growth system uses)."""
    anima_dir = Path.home() / ".anima"
    return anima_dir / "anima.db"


def _connect() -> sqlite3.Connection:
    """Open a read-only connection to anima.db."""
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _safe_mean(values: List[float]) -> Optional[float]:
    """Mean of a list, or None if empty."""
    if not values:
        return None
    return sum(values) / len(values)


def _fmt(val: Optional[float], decimals: int = 2) -> str:
    """Format a float for display."""
    if val is None:
        return "?"
    return f"{val:.{decimals}f}"


# ---------------------------------------------------------------------------
# Core analysis functions
# ---------------------------------------------------------------------------

def get_drawing_summary() -> Optional[str]:
    """Summarize drawing activity: count, date range, time distribution, averages."""
    try:
        conn = _connect()
        rows = conn.execute(
            "SELECT * FROM drawing_records ORDER BY timestamp ASC"
        ).fetchall()
        conn.close()
    except Exception:
        return None

    if not rows:
        return None

    records = [dict(r) for r in rows]
    n = len(records)
    first_ts = records[0]["timestamp"][:10]
    last_ts = records[-1]["timestamp"][:10]

    # Time-of-day distribution
    hour_buckets = {"night (22-6)": 0, "morning (6-12)": 0,
                    "afternoon (12-18)": 0, "evening (18-22)": 0}
    for r in records:
        h = r["hour"] or 0
        if 22 <= h or h < 6:
            hour_buckets["night (22-6)"] += 1
        elif h < 12:
            hour_buckets["morning (6-12)"] += 1
        elif h < 18:
            hour_buckets["afternoon (12-18)"] += 1
        else:
            hour_buckets["evening (18-22)"] += 1

    peak_time = max(hour_buckets, key=hour_buckets.get)
    peak_count = hour_buckets[peak_time]

    # Average anima state during drawings
    avg_warmth = _safe_mean([r["warmth"] for r in records if r["warmth"] is not None])
    avg_clarity = _safe_mean([r["clarity"] for r in records if r["clarity"] is not None])
    avg_stability = _safe_mean([r["stability"] for r in records if r["stability"] is not None])
    avg_wellness = _safe_mean([r["wellness"] for r in records if r["wellness"] is not None])

    # Compare to overall baseline from state_history
    baseline_text = ""
    try:
        conn = _connect()
        baseline = conn.execute(
            "SELECT AVG(warmth) as w, AVG(clarity) as c, AVG(stability) as s "
            "FROM state_history"
        ).fetchone()
        conn.close()
        if baseline and baseline["w"] is not None:
            bw = baseline["w"]
            bc = baseline["c"]
            bs = baseline["s"]
            diffs = []
            if avg_warmth is not None and bw:
                diff = avg_warmth - bw
                if abs(diff) > 0.03:
                    diffs.append(f"warmth {'higher' if diff > 0 else 'lower'} by {abs(diff):.2f}")
            if avg_stability is not None and bs:
                diff = avg_stability - bs
                if abs(diff) > 0.03:
                    diffs.append(f"stability {'higher' if diff > 0 else 'lower'} by {abs(diff):.2f}")
            if diffs:
                baseline_text = f" Compared to my overall baseline: {', '.join(diffs)}."
    except Exception:
        pass

    lines = [
        f"I have {n} recorded drawings ({first_ts} to {last_ts}).",
        f"Most drawings happen at {peak_time} ({peak_count}/{n}).",
        f"Average state when drawing: warmth={_fmt(avg_warmth)}, "
        f"clarity={_fmt(avg_clarity)}, stability={_fmt(avg_stability)}, "
        f"wellness={_fmt(avg_wellness)}.{baseline_text}",
    ]
    return "\n".join(lines)


def analyze_correlation(dimension: str,
                        group_by: Optional[str] = None) -> Optional[str]:
    """Analyze correlation between a dimension and drawing context.

    Args:
        dimension: anima dimension (warmth, clarity, stability, presence, wellness)
                   or environment (light_lux, ambient_temp_c, humidity_pct)
        group_by: optional grouping — "hour", "phase", or an environment column
    """
    # Map friendly names to column names
    col_map = {
        "warmth": "warmth", "clarity": "clarity", "stability": "stability",
        "presence": "presence", "wellness": "wellness",
        "light": "light_lux", "light_lux": "light_lux",
        "temperature": "ambient_temp_c", "temp": "ambient_temp_c",
        "ambient_temp_c": "ambient_temp_c",
        "humidity": "humidity_pct", "humidity_pct": "humidity_pct",
    }
    col = col_map.get(dimension.lower())
    if not col:
        return None

    try:
        conn = _connect()
        rows = conn.execute("SELECT * FROM drawing_records").fetchall()
        conn.close()
    except Exception:
        return None

    if not rows:
        return None

    records = [dict(r) for r in rows]

    if group_by == "hour" or group_by == "time":
        # Group by time of day
        buckets: Dict[str, List[float]] = {
            "night": [], "morning": [], "afternoon": [], "evening": []
        }
        for r in records:
            val = r.get(col)
            if val is None:
                continue
            h = r["hour"] or 0
            if 22 <= h or h < 6:
                buckets["night"].append(val)
            elif h < 12:
                buckets["morning"].append(val)
            elif h < 18:
                buckets["afternoon"].append(val)
            else:
                buckets["evening"].append(val)

        parts = []
        for period, vals in buckets.items():
            if vals:
                parts.append(f"{period}: {_fmt(_safe_mean(vals))} (n={len(vals)})")
        if not parts:
            return None
        return f"{dimension} by time of day when drawing: {', '.join(parts)}"

    elif group_by:
        # Generic grouping
        group_col = col_map.get(group_by, group_by)
        groups: Dict[str, List[float]] = {}
        for r in records:
            val = r.get(col)
            gval = r.get(group_col)
            if val is None or gval is None:
                continue
            # Bin numeric values
            if isinstance(gval, (int, float)):
                gval = f"{gval:.0f}"
            groups.setdefault(str(gval), []).append(val)

        parts = []
        for g, vals in sorted(groups.items()):
            parts.append(f"{g}: {_fmt(_safe_mean(vals))} (n={len(vals)})")
        if not parts:
            return None
        return f"{dimension} grouped by {group_by}: {', '.join(parts[:8])}"

    else:
        # Overall stats for this dimension
        vals = [r[col] for r in records if r.get(col) is not None]
        if not vals:
            return None
        avg = _safe_mean(vals)
        mn = min(vals)
        mx = max(vals)
        return (f"Across {len(vals)} drawings, {dimension} averaged {_fmt(avg)} "
                f"(range {_fmt(mn)}-{_fmt(mx)})")


def analyze_drawing_effect(dimension: str) -> Optional[str]:
    """Compare anima state before and after drawings using state_history.

    Looks at state 10min before and 10min after each drawing timestamp.
    """
    dim_map = {
        "warmth": "warmth", "clarity": "clarity",
        "stability": "stability", "presence": "presence",
    }
    col = dim_map.get(dimension.lower())
    if not col:
        return None

    try:
        conn = _connect()
        drawings = conn.execute(
            "SELECT timestamp FROM drawing_records ORDER BY timestamp"
        ).fetchall()

        if not drawings:
            conn.close()
            return None

        before_vals = []
        after_vals = []

        for row in drawings:
            ts = row["timestamp"]
            try:
                dt = datetime.fromisoformat(ts)
            except (ValueError, TypeError):
                continue

            before_start = (dt - timedelta(minutes=10)).isoformat()
            after_end = (dt + timedelta(minutes=10)).isoformat()

            # Get state before drawing
            before = conn.execute(
                f"SELECT AVG({col}) as val FROM state_history "
                "WHERE timestamp BETWEEN ? AND ?",
                (before_start, ts)
            ).fetchone()
            if before and before["val"] is not None:
                before_vals.append(before["val"])

            # Get state after drawing
            after = conn.execute(
                f"SELECT AVG({col}) as val FROM state_history "
                "WHERE timestamp BETWEEN ? AND ?",
                (ts, after_end)
            ).fetchone()
            if after and after["val"] is not None:
                after_vals.append(after["val"])

        conn.close()
    except Exception:
        return None

    if not before_vals or not after_vals:
        return None

    avg_before = _safe_mean(before_vals)
    avg_after = _safe_mean(after_vals)
    if avg_before is None or avg_after is None:
        return None

    diff = avg_after - avg_before
    direction = "increased" if diff > 0 else "decreased"
    n = min(len(before_vals), len(after_vals))

    if abs(diff) < 0.02:
        return (f"Drawing doesn't noticeably change my {dimension} "
                f"(before: {_fmt(avg_before)}, after: {_fmt(avg_after)}, n={n})")
    else:
        return (f"My {dimension} {direction} by {abs(diff):.3f} on average after drawing "
                f"(before: {_fmt(avg_before)}, after: {_fmt(avg_after)}, n={n})")


# ---------------------------------------------------------------------------
# Backfill from PNG timestamps
# ---------------------------------------------------------------------------

def backfill_from_png_timestamps() -> int:
    """Backfill drawing_records from PNG file timestamps + state_history.

    Scans ~/.anima/drawings/lumen_drawing_*.png, parses timestamps from
    filenames, and for each matches the nearest state_history record.

    Returns count of records inserted.
    """
    drawings_dir = Path.home() / ".anima" / "drawings"
    if not drawings_dir.exists():
        return 0

    pattern = re.compile(r"lumen_drawing_(\d{8}_\d{6})(_manual)?\.png")
    png_files = sorted(drawings_dir.glob("lumen_drawing_*.png"))

    if not png_files:
        return 0

    try:
        conn = _connect()
        # Check which timestamps already exist
        existing = set()
        for row in conn.execute("SELECT timestamp FROM drawing_records"):
            existing.add(row["timestamp"][:15])  # Compare up to minute precision

        inserted = 0
        for path in png_files:
            match = pattern.match(path.name)
            if not match:
                continue

            ts_str = match.group(1)  # "20260215_143022"
            try:
                dt = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
            except ValueError:
                continue

            # Skip if already have a record near this time
            ts_key = dt.isoformat()[:15]
            if ts_key in existing:
                continue

            # Find nearest state_history record (within 60s)
            window_start = (dt - timedelta(seconds=60)).isoformat()
            window_end = (dt + timedelta(seconds=60)).isoformat()
            state = conn.execute(
                "SELECT warmth, clarity, stability, presence, sensors "
                "FROM state_history "
                "WHERE timestamp BETWEEN ? AND ? "
                "ORDER BY ABS(julianday(timestamp) - julianday(?)) "
                "LIMIT 1",
                (window_start, window_end, dt.isoformat())
            ).fetchone()

            if not state:
                continue

            warmth = state["warmth"]
            clarity = state["clarity"]
            stability = state["stability"]
            presence = state["presence"]
            wellness = None
            if all(v is not None for v in [warmth, clarity, stability, presence]):
                wellness = (warmth + clarity + stability + presence) / 4.0

            # Extract environment from sensors JSON
            light_lux = None
            ambient_temp_c = None
            humidity_pct = None
            try:
                import json
                sensors = json.loads(state["sensors"]) if state["sensors"] else {}
                light_lux = sensors.get("light_lux") or sensors.get("world_light_lux")
                ambient_temp_c = sensors.get("ambient_temp_c")
                humidity_pct = sensors.get("humidity_pct")
            except Exception:
                pass

            conn.execute("""
                INSERT INTO drawing_records
                (timestamp, pixel_count, phase, warmth, clarity, stability, presence,
                 wellness, light_lux, ambient_temp_c, humidity_pct, hour)
                VALUES (?, NULL, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                dt.isoformat(), warmth, clarity, stability, presence,
                wellness, light_lux, ambient_temp_c, humidity_pct, dt.hour,
            ))
            inserted += 1

        conn.commit()
        conn.close()
        print(f"[DrawingAnalysis] Backfilled {inserted} records from PNG timestamps",
              file=sys.stderr, flush=True)
        return inserted
    except Exception as e:
        print(f"[DrawingAnalysis] Backfill error: {e}", file=sys.stderr, flush=True)
        return 0


# ---------------------------------------------------------------------------
# Entry point for self-answer pipeline
# ---------------------------------------------------------------------------

# Keywords that signal a data-answerable question
_CORRELATION_KEYWORDS = ["correlat", "when i draw", "while drawing", "during drawing",
                         "drawing and", "draw more when", "draw less when"]
_EFFECT_KEYWORDS = ["affect", "help", "improve", "change", "impact", "after drawing",
                    "does drawing", "drawing make"]
_PATTERN_KEYWORDS = ["tend to", "more when", "pattern", "usually", "most often",
                     "how often", "how many drawing"]
_DIMENSION_KEYWORDS = {
    "warmth": ["warm", "warmth", "temperature", "hot", "cold", "cool"],
    "clarity": ["clar", "clarity", "clear", "focus", "light", "bright", "dim"],
    "stability": ["stab", "stability", "stable", "calm", "settled", "steady"],
    "presence": ["presen", "presence", "present", "aware", "attentive", "engaged"],
    "wellness": ["well", "wellness", "good", "better", "worse", "feel"],
}


def _extract_dimension(text: str) -> str:
    """Extract the most likely anima dimension from question text."""
    text_lower = text.lower()
    for dim, keywords in _DIMENSION_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                return dim
    return "wellness"  # Default


def analyze_for_question(question_text: str) -> Optional[str]:
    """Analyze drawing data to answer a self-asked question.

    Entry point for the self-answer pipeline. Returns a data summary
    (3-5 lines) or None if this isn't a data-answerable question or
    there's insufficient data.
    """
    if not question_text:
        return None

    q_lower = question_text.lower()

    # Quick check: is this about drawing at all?
    drawing_related = any(w in q_lower for w in ["draw", "art", "creat", "canvas", "sketch"])
    if not drawing_related:
        # Could still be about correlations in sensor data
        data_related = any(w in q_lower for w in
                          ["correlat", "pattern", "tend to", "when i",
                           "affect", "sensor", "data", "history"])
        if not data_related:
            return None

    # Determine which analysis to run
    dim = _extract_dimension(question_text)
    parts = []

    if any(kw in q_lower for kw in _EFFECT_KEYWORDS):
        result = analyze_drawing_effect(dim)
        if result:
            parts.append(result)
        # Also add time-of-day correlation for context
        corr = analyze_correlation(dim, group_by="hour")
        if corr:
            parts.append(corr)

    elif any(kw in q_lower for kw in _CORRELATION_KEYWORDS):
        corr = analyze_correlation(dim, group_by="hour")
        if corr:
            parts.append(corr)
        # Add overall stats too
        overall = analyze_correlation(dim)
        if overall:
            parts.append(overall)

    elif any(kw in q_lower for kw in _PATTERN_KEYWORDS):
        summary = get_drawing_summary()
        if summary:
            parts.append(summary)
        corr = analyze_correlation(dim, group_by="hour")
        if corr:
            parts.append(corr)

    else:
        # General drawing question — provide summary + most relevant correlation
        summary = get_drawing_summary()
        if summary:
            parts.append(summary)

    if not parts:
        return None

    return "\n".join(parts)
