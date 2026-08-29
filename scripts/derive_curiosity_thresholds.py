#!/usr/bin/env python3
"""Derive the per-era curiosity pivot from this creature's own coherence range.

Why: `_update_attention` split "still exploring" from "pattern found" with one
absolute constant, C < 0.4, against a behavioural coherence distribution that
differs per era. Measured 2026-08-02 on a resonance piece, live C sat in
[0.377, 0.498] mean 0.458 — so ~95% of ticks took the REGENERATING branch and
curiosity rose monotonically into its 1.0 clamp. `attention_exhausted()`
(curiosity < 0.15) and `earned_composition` (curiosity < 0.2) were therefore
not badly tuned, they were unreachable: 26 of the first 34 instrumented
completions landed on the 8-hour cap and none was earned. An era reaching
C ~ 0.8 is split fairly by that same 0.4, which is exactly why one number
cannot serve every era. Design invariant 1, on the signal meant to end a piece.

The percentile contract (the design decision, stated once):

  "Pattern found" is a RELATIVE judgement. A piece is finding its pattern when
  it is more coherent than this era's own typical moment, and exploring when it
  is less. So the pivot is the era's own median coherence — one number per era,
  read off that era's lived distribution, not tuned.

    CURIOSITY_PIVOT_<era>    p50 of that era's coherence

Nothing below adjusts that percentile to make an era pass. When the median
pivot does not produce reachable exhaustion, this script REFUSES to emit a
pivot for that era and says so. Sliding the percentile until the simulation
looked good would smuggle a tuned constant back in wearing a contract's
clothes — the derivation would then be fitting the gate rather than measuring
the creature.

Verification (why a pivot can be refused):

  The pivot changes behaviour, so a derived value is replayed against the
  corpus before it is offered. `drawing_trajectory` samples every 300s and
  records coherence, arc_phase and marks_delta; curiosity_drain() runs once per
  placed mark. Replaying the ACTUAL engine function (imported, never
  re-implemented — a local copy could drift and certify a formula the creature
  does not run) marks_delta times per interval at that interval's coherence
  reconstructs the curiosity trace the piece would have had.

  Two refusals, opposite failure modes:
    unreachable — no piece in the era crosses the earned_composition floor
                  (curiosity < 0.2). That is today's bug at a different pivot:
                  a dead gate traded for a dead gate.
    premature   — the median piece crosses it before MIN_CROSS_FRACTION of its
                  observed marks. Pieces would end early, which is worse than
                  ending late: the 8h cap at least produced a finished canvas.

Population: `drawing_trajectory`, NOT drawing_records. The question is what
coherence looked like DURING pieces (the pivot is consulted per mark), and
endpoint rows describe the clock that ended them rather than the work.

Usage:
  python3 scripts/derive_curiosity_thresholds.py --db ~/.anima/anima.db \
      [--days 90] [--apply CONFIG]

  --apply merges CURIOSITY_PIVOT_* into nervous_system.drawing_thresholds in
  the given calibration file atomically (backup written alongside). Without it,
  prints the report and JSON to stdout and changes nothing. Absent keys fall
  back to the built-in 0.4, so an un-applied derivation moves no mark.

Rerun cadence: alongside the other derivations (~monthly), and after any change
that re-bases behavioural C (an I_signal or gesture-entropy change moves this
file's answer). _curiosity_pivot() reads through get_calibration(), which
refreshes on config-file signature change, so a rederive lands without a
restart.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
from anima_mcp.display.drawing_engine import curiosity_drain  # noqa: E402

PERCENTILE_CONTRACT = {"CURIOSITY_PIVOT": 50}

# Below this, a pivot encodes the last few days' weather rather than a range.
# Matched to derive_drawing_thresholds.py rather than argued separately.
MIN_SAMPLES = 500
# Per era. An era with a handful of samples gets no pivot rather than a pivot
# built from one afternoon; the built-in keeps serving it.
MIN_SAMPLES_PER_ERA = 120
# A piece must contribute at least this many usable intervals to be replayed.
MIN_INTERVALS_PER_PIECE = 4

# Curiosity floors that the pivot exists to make reachable. Mirrors
# DrawingState.attention_exhausted() and the earned_composition branch of
# completion_reason(); the looser of the two is what "reachable" means here.
COMPOSITION_FLOOR = 0.2
EXHAUSTION_FLOOR = 0.15
# Curiosity starts each piece at 1.0 (DrawingState.reset).
CURIOSITY_START = 1.0

# Earliest point in a piece's own mark count at which crossing the composition
# floor is acceptable. Below this the pivot ends pieces prematurely.
MIN_CROSS_FRACTION = 0.5


def _percentile(sorted_vals, pct):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * pct / 100.0
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    frac = k - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def load_samples(db, days):
    """Ordered per-piece trajectory samples, grouped by era.

    marks_delta IS NULL marks a sample this process could not attribute (a
    restart joined the piece mid-flight). Those intervals are dropped rather
    than replayed as zero marks — an unknown delta is not an absent one.
    """
    con = sqlite3.connect(db)
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    rows = con.execute(
        "select era, piece_uid, elapsed_seconds, coherence, arc_phase, "
        "       marks_delta, mark_count "
        "from drawing_trajectory "
        "where era is not null and coherence is not null "
        "  and marks_delta is not null and marks_delta > 0 "
        "  and timestamp > ? "
        "order by era, piece_uid, elapsed_seconds", (since,)).fetchall()
    con.close()
    by_era = defaultdict(lambda: defaultdict(list))
    for era, uid, elapsed, coherence, arc_phase, marks_delta, mark_count in rows:
        by_era[era][uid].append({
            "coherence": float(coherence),
            "arc_phase": arc_phase or "opening",
            "marks_delta": int(marks_delta),
            "mark_count": int(mark_count or 0),
        })
    return by_era


def replay(intervals, pivot):
    """Curiosity trace for one piece under `pivot`, using the engine's own fn.

    Returns (final_curiosity, marks_at_composition_cross_or_None, total_marks).
    """
    curiosity = CURIOSITY_START
    marks_seen = 0
    crossed_at = None
    for iv in intervals:
        for _ in range(iv["marks_delta"]):
            curiosity = max(0.0, min(1.0, curiosity - curiosity_drain(
                iv["arc_phase"], iv["coherence"], pivot)))
            marks_seen += 1
            if crossed_at is None and curiosity < COMPOSITION_FLOOR:
                crossed_at = marks_seen
    return curiosity, crossed_at, marks_seen


def evaluate(pieces, pivot):
    """Replay every piece in an era. Returns a verdict dict."""
    traces = []
    for uid, intervals in pieces.items():
        if len(intervals) < MIN_INTERVALS_PER_PIECE:
            continue
        final, crossed_at, total_marks = replay(intervals, pivot)
        if total_marks <= 0:
            continue
        traces.append({
            "piece": uid, "final": final, "crossed_at": crossed_at,
            "total_marks": total_marks,
            "cross_fraction": (crossed_at / total_marks) if crossed_at else None,
        })
    if not traces:
        return {"ok": False, "reason": "no piece had enough usable intervals",
                "traces": 0}
    crossings = [t for t in traces if t["crossed_at"] is not None]
    reached = len(crossings)
    verdict = {
        "traces": len(traces),
        "reached_composition_floor": reached,
        "reach_rate": round(reached / len(traces), 3),
        "median_final_curiosity": round(
            _percentile(sorted(t["final"] for t in traces), 50), 4),
    }
    if not crossings:
        verdict.update(ok=False, reason=(
            "unreachable: no replayed piece reaches curiosity < "
            f"{COMPOSITION_FLOOR} under this pivot — the gate stays dead, "
            "which is the defect this derivation exists to remove"))
        return verdict
    fractions = sorted(t["cross_fraction"] for t in crossings)
    median_fraction = _percentile(fractions, 50)
    verdict["median_cross_fraction"] = round(median_fraction, 3)
    if median_fraction < MIN_CROSS_FRACTION:
        verdict.update(ok=False, reason=(
            f"premature: the median piece crosses at {median_fraction:.2f} of "
            f"its marks (floor {MIN_CROSS_FRACTION}) — pieces would end before "
            "they are worked, which is a worse failure than ending late"))
        return verdict
    verdict.update(ok=True, reason="reachable without being premature")
    return verdict


def derive(by_era):
    total = sum(len(ivs) for pieces in by_era.values() for ivs in pieces.values())
    if total < MIN_SAMPLES:
        sys.exit(f"refusing: only {total} usable samples (< {MIN_SAMPLES}) — a "
                 f"pivot derived from a sliver would encode a mood, not a range")
    thresholds, report = {}, {}
    for era in sorted(by_era):
        pieces = by_era[era]
        coherence = sorted(iv["coherence"] for ivs in pieces.values() for iv in ivs)
        entry = {"samples": len(coherence), "pieces": len(pieces)}
        if len(coherence) < MIN_SAMPLES_PER_ERA:
            entry.update(emitted=False, reason=(
                f"only {len(coherence)} samples (< {MIN_SAMPLES_PER_ERA}); "
                "keeping the built-in"))
            report[era] = entry
            continue
        pivot = round(_percentile(coherence, PERCENTILE_CONTRACT["CURIOSITY_PIVOT"]), 4)
        entry["coherence_range"] = [round(coherence[0], 4), round(coherence[-1], 4)]
        entry["pivot"] = pivot
        # Baseline: what the built-in constant does on this same corpus, so the
        # report shows the change rather than only the proposal.
        entry["baseline_0.4"] = evaluate(pieces, 0.4)
        verdict = evaluate(pieces, pivot)
        entry["verdict"] = verdict
        if verdict.get("ok"):
            thresholds[f"CURIOSITY_PIVOT_{era}"] = pivot
            entry["emitted"] = True
        else:
            entry["emitted"] = False
        report[era] = entry
    return thresholds, report, total


def apply_to_config(path, thresholds):
    """Merge CURIOSITY_PIVOT_* into drawing_thresholds, preserving neighbours.

    Merged, not replaced: derive_drawing_thresholds.py owns the COVERAGE_* keys
    in this same dict and overwriting it whole would silently revert them.
    """
    path = os.path.expanduser(path)
    backup = f"{path}.bak-curiosity-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(path, backup)
    with open(path) as f:
        cfg = json.load(f)
    ns = cfg.setdefault("nervous_system", {})
    existing = ns.get("drawing_thresholds")
    if not isinstance(existing, dict):
        existing = {}
    # Drop stale pivots for eras this run did not emit, so a since-retired or
    # since-refused era stops being steered by a number nothing re-verified.
    existing = {k: v for k, v in existing.items()
                if not k.startswith("CURIOSITY_PIVOT_")}
    existing.update(thresholds)
    ns["drawing_thresholds"] = existing
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, path)
    return backup


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--apply", default=None, metavar="CONFIG_JSON")
    args = ap.parse_args()

    by_era = load_samples(os.path.expanduser(args.db), args.days)
    thresholds, report, total = derive(by_era)

    print(f"# derived from n={total} usable drawing_trajectory intervals "
          f"across {len(by_era)} eras", file=sys.stderr)
    print(json.dumps({"report": report}, indent=2), file=sys.stderr)
    if not thresholds:
        sys.exit("refusing: no era produced a verifiable pivot — see the report "
                 "above; the built-in 0.4 keeps serving every era")
    if args.apply:
        backup = apply_to_config(args.apply, thresholds)
        print(f"applied to {args.apply} (backup: {backup})", file=sys.stderr)
    print(json.dumps(thresholds, indent=2))


if __name__ == "__main__":
    main()
