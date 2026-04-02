#!/usr/bin/env python3
"""
Extract empirical data for the Trajectory Identity paper.
Generates CSV/JSON datasets and terminal summaries for figures.

Usage:
    python scripts/paper_figures.py                    # Summary only
    python scripts/paper_figures.py --export-dir /tmp/paper  # Export CSVs
"""

import json
import math
import sqlite3
import sys
from pathlib import Path

# Paths
ANIMA_DB = Path.home() / "backups/lumen/anima_data/anima.db"
SELF_MODEL = Path.home() / "backups/lumen/anima_data/self_model.json"
GENESIS = Path.home() / "backups/lumen/anima_data/trajectory_genesis.json"
LAST_TRAJ = Path.home() / "backups/lumen/anima_data/trajectory_last.json"
DAY_SUMMARIES = Path.home() / "backups/lumen/anima_data/day_summaries.json"
ANIMA_HISTORY = Path.home() / "backups/lumen/anima_data/anima_history.json"
PREFERENCES = Path.home() / "backups/lumen/anima_data/preferences.json"


def load_json(path):
    if not path.exists():
        print(f"  [missing] {path}")
        return None
    with open(path) as f:
        return json.load(f)


def figure_1_attractor_basin(conn, export_dir=None):
    """Figure 1: Attractor basin — center + variance across time windows."""
    print("\n=== Figure 1: Attractor Basin Stability ===")

    cur = conn.execute("""
        SELECT warmth, clarity, stability, presence, timestamp
        FROM state_history
        ORDER BY timestamp
    """)
    rows = cur.fetchall()
    total = len(rows)
    print(f"Total state samples: {total:,}")

    if total == 0:
        return

    # Compute attractor in sliding windows of 500
    window = 500
    step = 500
    windows = []
    for i in range(0, total - window, step):
        chunk = rows[i:i + window]
        w = [r[0] for r in chunk]
        c = [r[1] for r in chunk]
        s = [r[2] for r in chunk]
        p = [r[3] for r in chunk]

        mu = [sum(w) / len(w), sum(c) / len(c), sum(s) / len(s), sum(p) / len(p)]
        var = [
            sum((x - mu[0]) ** 2 for x in w) / len(w),
            sum((x - mu[1]) ** 2 for x in c) / len(c),
            sum((x - mu[2]) ** 2 for x in s) / len(s),
            sum((x - mu[3]) ** 2 for x in p) / len(p),
        ]
        windows.append({
            "window_start": chunk[0][4],
            "window_end": chunk[-1][4],
            "mu_warmth": mu[0],
            "mu_clarity": mu[1],
            "mu_stability": mu[2],
            "mu_presence": mu[3],
            "var_warmth": var[0],
            "var_clarity": var[1],
            "var_stability": var[2],
            "var_presence": var[3],
        })

    dims = ["warmth", "clarity", "stability", "presence"]
    print(f"Windows computed: {len(windows)} (size={window}, step={step})")
    print()

    # Variance of the means across windows (this is the key claim: mu variance < 0.05)
    print("Attractor center stability (variance of mu across windows):")
    for d in dims:
        mus = [w[f"mu_{d}"] for w in windows]
        grand_mean = sum(mus) / len(mus)
        var_of_mu = sum((m - grand_mean) ** 2 for m in mus) / len(mus)
        print(f"  {d:12s}  mean(mu)={grand_mean:.4f}  var(mu)={var_of_mu:.6f}  {'< 0.05' if var_of_mu < 0.05 else '>= 0.05'}")

    print()
    print("Average within-window variance:")
    for d in dims:
        vars_ = [w[f"var_{d}"] for w in windows]
        avg_var = sum(vars_) / len(vars_)
        print(f"  {d:12s}  avg_var={avg_var:.6f}")

    if export_dir:
        _export_csv(export_dir / "fig1_attractor_windows.csv", windows)


def figure_2_recovery_profile(export_dir=None):
    """Figure 2: Recovery profile — tau estimates from self_model."""
    print("\n=== Figure 2: Recovery Profile (Rho) ===")

    traj = load_json(LAST_TRAJ)
    if not traj:
        return

    recovery = traj.get("recovery", {})
    print(f"Recovery tau estimate: {recovery.get('tau_estimate', 'N/A')}s")
    print(f"Recovery tau mean:     {recovery.get('tau_mean', 'N/A')}s")
    print(f"Recovery tau std:      {recovery.get('tau_std', 'N/A')}s")
    print(f"Episodes analyzed:     {recovery.get('n_episodes', 'N/A')}")
    print(f"Valid tau estimates:    {recovery.get('n_valid_estimates', 'N/A')}")
    print(f"Confidence:            {recovery.get('confidence', 'N/A')}")


def figure_3_belief_convergence(export_dir=None):
    """Figure 3: Belief signature — convergences and evidence."""
    print("\n=== Figure 3: Belief Signature (Beta) ===")

    sm = load_json(SELF_MODEL)
    if not sm:
        return

    beliefs = sm.get("beliefs", {})
    print(f"{'Belief':<35s} {'Conf':>6s} {'Value':>7s} {'Support':>8s} {'Contra':>8s} {'Ratio':>7s}")
    print("-" * 80)
    for name, b in sorted(beliefs.items(), key=lambda x: -x[1].get("confidence", 0)):
        conf = b.get("confidence", 0)
        val = b.get("value", 0)
        sup = b.get("supporting_count", 0)
        con = b.get("contradicting_count", 0)
        ratio = sup / max(con, 1)
        print(f"  {name:<33s} {conf:>6.3f} {val:>7.3f} {sup:>8d} {con:>8d} {ratio:>7.1f}")

    if export_dir:
        rows = []
        for name, b in beliefs.items():
            rows.append({
                "belief": name,
                "confidence": b.get("confidence", 0),
                "value": b.get("value", 0),
                "supporting": b.get("supporting_count", 0),
                "contradicting": b.get("contradicting_count", 0),
            })
        _export_csv(export_dir / "fig3_beliefs.csv", rows)


def figure_4_identity_confidence_growth(conn, export_dir=None):
    """Figure 4: Identity confidence vs observation count (cold start)."""
    print("\n=== Figure 4: Identity Confidence Growth ===")

    cur = conn.execute("SELECT COUNT(*) FROM state_history")
    total = cur.fetchone()[0]

    # Simulate confidence growth curve
    print("Observation count → Identity confidence:")
    points = []
    for obs in [0, 5, 10, 20, 30, 40, 50, 75, 100, 200, 500, 1000]:
        if obs > total:
            break
        cold_start = min(1.0, obs / 50)
        # Approximate stability score growth
        stability = min(1.0, obs / 100) * 0.9  # Simplified
        confidence = cold_start * max(stability, 0.3)
        points.append({"observations": obs, "confidence": round(confidence, 3)})
        bar = "#" * int(confidence * 40)
        print(f"  obs={obs:>5d}  conf={confidence:.3f}  {bar}")

    print(f"\n  Total observations available: {total:,}")
    print(f"  Cold start threshold (50 obs) reached in: ~{50 * 10 / 60:.0f} min")

    if export_dir:
        _export_csv(export_dir / "fig4_confidence_growth.csv", points)


def figure_5_genesis_vs_current(export_dir=None):
    """Figure 5: Genesis signature vs current — lineage similarity."""
    print("\n=== Figure 5: Genesis vs Current (Lineage) ===")

    genesis = load_json(GENESIS)
    current = load_json(LAST_TRAJ)

    if not genesis or not current:
        print("  Missing genesis or current trajectory")
        return

    # Compare preference vectors
    g_prefs = genesis.get("preferences", {}).get("vector", [])
    c_prefs = current.get("preferences", {}).get("vector", [])

    if g_prefs and c_prefs:
        # Cosine similarity
        dot = sum(a * b for a, b in zip(g_prefs, c_prefs))
        mag_g = math.sqrt(sum(a ** 2 for a in g_prefs))
        mag_c = math.sqrt(sum(a ** 2 for a in c_prefs))
        if mag_g > 0 and mag_c > 0:
            cos_sim = dot / (mag_g * mag_c)
            pref_sim = (cos_sim + 1) / 2  # Map to [0,1]
        else:
            pref_sim = 0.5
        print(f"  Preference similarity (Pi):  {pref_sim:.4f}")

    # Compare beliefs
    g_beliefs = genesis.get("beliefs", {}).get("values", [])
    c_beliefs = current.get("beliefs", {}).get("values", [])
    if g_beliefs and c_beliefs:
        dot = sum(a * b for a, b in zip(g_beliefs, c_beliefs))
        mag_g = math.sqrt(sum(a ** 2 for a in g_beliefs))
        mag_c = math.sqrt(sum(a ** 2 for a in c_beliefs))
        if mag_g > 0 and mag_c > 0:
            cos_sim = dot / (mag_g * mag_c)
            belief_sim = (cos_sim + 1) / 2
        else:
            belief_sim = 0.5
        print(f"  Belief similarity (Beta):    {belief_sim:.4f}")

    # Compare attractor centers
    g_att = genesis.get("attractor", {}).get("center", [])
    c_att = current.get("attractor", {}).get("center", [])
    if g_att and c_att:
        dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(g_att, c_att)))
        att_sim = max(0, 1 - dist)  # Simple distance-based
        print(f"  Attractor similarity (Alpha): {att_sim:.4f}  (center dist={dist:.4f})")

    # Genesis metadata
    g_obs = genesis.get("observation_count", "?")
    g_stab = genesis.get("stability_score", "?")
    c_obs = current.get("observation_count", "?")
    c_stab = current.get("stability_score", "?")
    print(f"\n  Genesis: {g_obs} obs, stability={g_stab}")
    print(f"  Current: {c_obs} obs, stability={c_stab}")


def figure_6_day_summaries_trend(export_dir=None):
    """Figure 6: Daily attractor center over time."""
    print("\n=== Figure 6: Daily Attractor Trend ===")

    summaries = load_json(DAY_SUMMARIES)
    if not summaries:
        return

    if isinstance(summaries, dict):
        summaries = summaries.get("summaries", [])

    print(f"Day summaries available: {len(summaries)}")
    if not summaries:
        return

    print(f"\n{'Date':<12s} {'Warmth':>8s} {'Clarity':>8s} {'Stability':>9s} {'Presence':>9s} {'Obs':>5s}")
    print("-" * 60)
    for s in summaries:
        date = s.get("date", "?")
        center = s.get("attractor_center", s.get("center", {}))
        obs = s.get("n_observations", "?")
        if isinstance(center, dict):
            w = center.get("warmth", center.get("w", "?"))
            c = center.get("clarity", center.get("c", "?"))
            st = center.get("stability", center.get("s", "?"))
            p = center.get("presence", center.get("p", "?"))
        elif isinstance(center, list) and len(center) >= 4:
            w, c, st, p = center[0], center[1], center[2], center[3]
        else:
            continue
        try:
            print(f"  {str(date):<10s} {float(w):>8.4f} {float(c):>8.4f} {float(st):>9.4f} {float(p):>9.4f} {obs:>5}")
        except (ValueError, TypeError):
            pass

    if export_dir:
        _export_csv(export_dir / "fig6_day_summaries.csv", summaries)


def figure_7_state_distribution(conn, export_dir=None):
    """Figure 7: Overall state distribution — histograms."""
    print("\n=== Figure 7: State Distribution Summary ===")

    for dim in ["warmth", "clarity", "stability", "presence"]:
        cur = conn.execute(f"""
            SELECT
                MIN({dim}), MAX({dim}), AVG({dim}),
                COUNT(*),
                AVG({dim} * {dim}) - AVG({dim}) * AVG({dim}) as variance
            FROM state_history
        """)
        row = cur.fetchone()
        std = math.sqrt(max(row[4], 0))
        print(f"  {dim:12s}  min={row[0]:.4f}  max={row[1]:.4f}  mean={row[2]:.4f}  std={std:.4f}  n={row[3]:,}")

    # Date range
    cur = conn.execute("SELECT MIN(timestamp), MAX(timestamp) FROM state_history")
    t_min, t_max = cur.fetchone()
    print(f"\n  Date range: {t_min} to {t_max}")

    if export_dir:
        # Export a sampled time series (every 100th point)
        cur = conn.execute("""
            SELECT timestamp, warmth, clarity, stability, presence
            FROM state_history
            WHERE rowid % 100 = 0
            ORDER BY timestamp
        """)
        rows = [{"timestamp": r[0], "warmth": r[1], "clarity": r[2],
                 "stability": r[3], "presence": r[4]} for r in cur.fetchall()]
        _export_csv(export_dir / "fig7_state_timeseries_sampled.csv", rows)


def _export_csv(path, rows):
    if not rows:
        return
    import csv
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = rows[0].keys() if isinstance(rows[0], dict) else None
    with open(path, "w", newline="") as f:
        if keys:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(rows)
    print(f"  -> Exported: {path}")


def main():
    export_dir = None
    if "--export-dir" in sys.argv:
        idx = sys.argv.index("--export-dir")
        export_dir = Path(sys.argv[idx + 1])
        export_dir.mkdir(parents=True, exist_ok=True)
        print(f"Exporting to: {export_dir}")

    if not ANIMA_DB.exists():
        print(f"Database not found: {ANIMA_DB}")
        sys.exit(1)

    conn = sqlite3.connect(str(ANIMA_DB))
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        figure_1_attractor_basin(conn, export_dir)
        figure_2_recovery_profile(export_dir)
        figure_3_belief_convergence(export_dir)
        figure_4_identity_confidence_growth(conn, export_dir)
        figure_5_genesis_vs_current(export_dir)
        figure_6_day_summaries_trend(export_dir)
        figure_7_state_distribution(conn, export_dir)
    finally:
        conn.close()

    print("\n=== Done ===")
    if export_dir:
        print(f"CSV files exported to {export_dir}")


if __name__ == "__main__":
    main()
