"""Read-only percentile summary of Lumen's own anima history.

Companion to `drawing_derivation.channel_report`, which does the same for the
environment channels in `drawing_records`. This one reads `state_history`, so
the question it answers is "what range does Lumen's own state actually occupy",
which is what any fixed cut on warmth/clarity/stability/presence is implicitly
claiming to know.

The motivating case: `self_model.observe_temperament` tests
`warmth_baseline_low` as `warmth_mean < 0.40` and `presence_baseline_low` as
`presence_mean < 0.35`. Measured live 2026-08-29, temperament warmth was 0.686
and presence 0.721 — far above both — so each belief takes contradicting
evidence every cycle and converges to a verdict it was never going to revise. A
belief that is true (or false) by construction measures nothing. Whether that is
what actually happens is a question about a distribution, and nothing reported
one.

⚠️ **This is a proxy, and it answers in only one direction.** Temperament is
never persisted; `state_history` records raw anima, and temperament is a slow
EMA of it (`TEMPERAMENT_ALPHA` in `inner_life.py`, ~2-5 min half-life). An EMA
shares its source's mean but has a NARROWER spread, so:

  * anima p05 already above the cut  ⇒ temperament's is too, and higher.
    The belief is confirmed constant-verdict.
  * anima p05 below the cut          ⇒ temperament's may still be above it.
    Inconclusive — smoothing could have removed exactly the excursions that
    would have flipped the belief.

So a negative result here is evidence and a positive one is not. Reported
explicitly rather than left for the reader to infer, because the tempting
mistake is to read the proxy as the thing.

Like `channel_report`, this names no threshold: a cut's health is a question
about its consumer, which this module does not know. Read the percentiles
against whatever cut is in question.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from .db_paths import resolve_db_path
from .drawing_derivation import percentile

DIMENSIONS = ("warmth", "clarity", "stability", "presence")

# Hard bound on rows pulled into one report. state_history is written on the
# server's main loop, so a 90-day window is large; this keeps a runaway table
# from stalling the request rather than expressing a real ceiling.
MAX_ROWS = 500_000


def anima_report(db_path: Optional[str] = None, days: int = 90,
                 max_rows: int = MAX_ROWS) -> Dict[str, Any]:
    """Percentiles per anima dimension over the window. Never raises.

    Fails toward *unknown*: a missing table or unreadable database returns
    available=false with the reason, never an empty summary that would read as
    "nothing recorded".
    """
    path = resolve_db_path(db_path)
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            have = {row[1] for row in con.execute(
                "pragma table_info(state_history)")}
            if not have:
                return {"available": False, "db_path": path,
                        "reason": "state_history not present"}
            dims: Dict[str, Any] = {}
            for name in DIMENSIONS:
                if name not in have:
                    dims[name] = {"available": False,
                                  "reason": "column not present"}
                    continue
                vals = sorted(
                    float(v) for (v,) in con.execute(
                        f"select {name} from state_history "
                        f"where {name} is not null and timestamp > ? "
                        f"limit ?", (since, max_rows))
                )
                if not vals:
                    dims[name] = {"available": False, "n": 0,
                                  "reason": "no non-null rows in window"}
                    continue
                dims[name] = {
                    "available": True,
                    "n": len(vals),
                    "min": round(vals[0], 4),
                    "p05": round(percentile(vals, 5) or 0.0, 4),
                    "p25": round(percentile(vals, 25) or 0.0, 4),
                    "p50": round(percentile(vals, 50) or 0.0, 4),
                    "p75": round(percentile(vals, 75) or 0.0, 4),
                    "p95": round(percentile(vals, 95) or 0.0, 4),
                    "max": round(vals[-1], 4),
                }
        finally:
            con.close()
    except sqlite3.Error as e:
        return {"available": False, "db_path": path,
                "reason": f"database unreadable: {e}"}
    except (TypeError, ValueError) as e:
        return {"available": False, "db_path": path,
                "reason": f"unusable row data: {e}"}
    return {
        "available": True,
        "db_path": path,
        "days": days,
        "source": "state_history (raw anima)",
        "dimensions": dims,
        # Carried in the payload so a reader who never opens this file still
        # gets the caveat with the numbers.
        "temperament_caveat": (
            "Temperament is not persisted; these are raw anima. Temperament is "
            "a slow EMA of them, so it shares this mean with a NARROWER spread. "
            "For a temperament cut: a percentile already clear of the cut here "
            "is clear there too (conclusive); one that crosses it here may not "
            "cross there (inconclusive)."
        ),
    }
