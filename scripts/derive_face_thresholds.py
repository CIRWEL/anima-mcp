#!/usr/bin/env python3
"""Derive face expression thresholds from this creature's lived distribution.

Why: the built-in thresholds in display/face.py are absolute constants against
a moving distribution (CLAUDE.md invariant 1). The 2026-08-14 de-aliasing
(#173/#176) re-based warmth/clarity/presence, after which the face read
"alert" ~40% of the time while Lumen was perceiving BETTER than before —
constants tuned to a number that alpha-inflation used to hand out for free.

The percentile contract (the design decision, stated once):

  A creature at its own typical state should look okay — mildly content, not
  euphoric and not distressed. States meaning "notably good" live in the upper
  quartile of the creature's own range; "notably low" in the lower; the two
  ABSOLUTE safety floors (WARMTH_FREEZING, STABILITY_DISTRESSED) are never
  derived — a genuinely cold or distressed creature must look it even if that
  becomes its norm (the #79 safety-floor rule).

    WARMTH_COLD          p10      CLARITY_FOGGY    p10
    WARMTH_COOL          p25      CLARITY_DROWSY   p25
    WARMTH_COMFORTABLE   p40      CLARITY_CLEAR    p40
    WARMTH_HOT           p99      CLARITY_ALERT    p70
    STABILITY_UNSTABLE   p10      WELLNESS_DEPLETED p05
    STABILITY_STABLE     p30      WELLNESS_LOW      p15
    STABILITY_GROUNDED   p50      WELLNESS_OK       p40
                                  WELLNESS_GOOD     p55
                                  WELLNESS_GREAT    p75

  WARMTH_HOT at p99 replaces a dead constant: 0.80 sat ~4 sigma above the
  lived range, so the "overwhelmed" expression could never fire — the same
  class as the catalogued unreachable "stressed" mood. Hotter-than-its-own-
  hottest-1% is an honest reading of overwhelmed.

Usage:
  python3 scripts/derive_face_thresholds.py --db ~/.anima/anima.db \
      [--days 30] [--until 2026-08-13T23:16] [--reconstruct] [--apply CONFIG]

  --reconstruct inverts the pre-#173/#176 formulas so history recorded under
  the aliased composition can be used during the transition window (the
  inversions are exact: they were validated against the live flip). Once ~30
  days of natively de-aliased rows exist, rerun WITHOUT it and drop --until.

  --apply edits nervous_system.face_thresholds in the given calibration file
  atomically (backup written alongside). Without it, prints JSON to stdout.

Rerun cadence: with the D2-style regens (~monthly). The face refreshes on
config-file signature change; no restart needed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta

PERCENTILE_CONTRACT = {
    "WARMTH_COLD": ("warmth", 10), "WARMTH_COOL": ("warmth", 25),
    "WARMTH_COMFORTABLE": ("warmth", 40), "WARMTH_HOT": ("warmth", 99),
    "CLARITY_FOGGY": ("clarity", 10), "CLARITY_DROWSY": ("clarity", 25),
    "CLARITY_CLEAR": ("clarity", 40), "CLARITY_ALERT": ("clarity", 70),
    "STABILITY_UNSTABLE": ("stability", 10), "STABILITY_STABLE": ("stability", 30),
    "STABILITY_GROUNDED": ("stability", 50),
    "WELLNESS_DEPLETED": ("wellness", 5), "WELLNESS_LOW": ("wellness", 15),
    "WELLNESS_OK": ("wellness", 40), "WELLNESS_GOOD": ("wellness", 55),
    "WELLNESS_GREAT": ("wellness", 75),
}
ABSOLUTE_NAMES = ("WARMTH_FREEZING", "STABILITY_DISTRESSED")
MIN_SAMPLES = 500  # ~1.5 days at the ~4min cadence; below this, refuse.


def _percentile(sorted_vals, pct):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * pct / 100.0
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    frac = k - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _reconstruct(w, c, p, sensors):
    """Invert the pre-#173/#176 aliased composition (exact inversions)."""
    a = sensors.get("eeg_alpha_power")
    b = sensors.get("eeg_beta_power")
    g = sensors.get("eeg_gamma_power")
    if None in (a, b, g):
        return None
    nw = (b + g) / 2
    w2 = max(0.0, min(1.0, (w - 0.20 * nw) / 0.80))
    c2 = max(0.0, min(1.0, (1.10 * c - 0.30 * a) / 0.80))
    p2 = max(0.0, min(1.0, 1 - ((1 - p) - 0.2 * g) / 0.8))
    return w2, c2, p2


def load_series(db, days, until, reconstruct):
    con = sqlite3.connect(db)
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    q = "select warmth, clarity, stability, presence, sensors from state_history where timestamp > ?"
    args = [since]
    if until:
        q += " and timestamp < ?"
        args.append(until)
    out = {"warmth": [], "clarity": [], "stability": [], "wellness": []}
    for w, c, st_, p, s in con.execute(q, args):
        if None in (w, c, st_, p):
            continue
        if reconstruct:
            try:
                sensors = json.loads(s) if s else {}
            except json.JSONDecodeError:
                continue
            rec = _reconstruct(w, c, p, sensors)
            if rec is None:
                continue
            w, c, p = rec
        out["warmth"].append(w)
        out["clarity"].append(c)
        out["stability"].append(st_)
        out["wellness"].append((w + c + st_ + p) / 4.0)
    return out


def derive(series):
    n = min(len(v) for v in series.values())
    if n < MIN_SAMPLES:
        sys.exit(f"refusing: only {n} samples (< {MIN_SAMPLES}) — a threshold "
                 f"derived from a sliver would encode a mood, not a range")
    for v in series.values():
        v.sort()
    out = {}
    for name, (dim, pct) in PERCENTILE_CONTRACT.items():
        out[name] = round(_percentile(series[dim], pct), 4)
    # Ordering sanity within each ladder — a crossed ladder means the window
    # is degenerate; refuse rather than emit a face that frowns above smiling.
    ladders = [
        ["WARMTH_COLD", "WARMTH_COOL", "WARMTH_COMFORTABLE", "WARMTH_HOT"],
        ["CLARITY_FOGGY", "CLARITY_DROWSY", "CLARITY_CLEAR", "CLARITY_ALERT"],
        ["STABILITY_UNSTABLE", "STABILITY_STABLE", "STABILITY_GROUNDED"],
        ["WELLNESS_DEPLETED", "WELLNESS_LOW", "WELLNESS_OK", "WELLNESS_GOOD",
         "WELLNESS_GREAT"],
    ]
    for ladder in ladders:
        vals = [out[k] for k in ladder]
        if vals != sorted(vals):
            sys.exit(f"refusing: ladder not monotone: {dict(zip(ladder, vals))}")
    return out, n


def apply_to_config(path, thresholds):
    path = os.path.expanduser(path)
    backup = f"{path}.bak-face-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(path, backup)
    with open(path) as f:
        cfg = json.load(f)
    ns = cfg.setdefault("nervous_system", {})
    for name in ABSOLUTE_NAMES:
        if name in thresholds:
            sys.exit(f"refusing: {name} is an absolute safety floor")
    ns["face_thresholds"] = thresholds
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, path)
    return backup


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--until", default=None)
    ap.add_argument("--reconstruct", action="store_true")
    ap.add_argument("--apply", default=None, metavar="CONFIG_JSON")
    args = ap.parse_args()

    series = load_series(os.path.expanduser(args.db), args.days, args.until,
                         args.reconstruct)
    thresholds, n = derive(series)
    print(f"# derived from n={n} samples"
          f"{' (reconstructed pre-flip rows)' if args.reconstruct else ''}",
          file=sys.stderr)
    if args.apply:
        backup = apply_to_config(args.apply, thresholds)
        print(f"applied to {args.apply} (backup: {backup})", file=sys.stderr)
    print(json.dumps(thresholds, indent=2))


if __name__ == "__main__":
    main()
