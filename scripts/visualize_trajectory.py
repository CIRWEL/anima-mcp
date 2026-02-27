#!/usr/bin/env python3
"""
Visualize Lumen's trajectory signature Σ.

Renders attractor basin, stability, and lineage for human inspection.
Run: python scripts/visualize_trajectory.py [--html [path]]

Loads from ~/.anima/trajectory_last.json (or computes if --compute).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Add project root
project_root = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_root))

from anima_mcp.trajectory import (
    TrajectorySignature,
    compute_trajectory_signature,
    load_trajectory,
    load_genesis,
)


DIMS = ["warmth", "clarity", "stability", "presence"]
BAR_WIDTH = 24
BLOCK_FULL = "█"
BLOCK_EMPTY = "░"


def _bar(value: float, width: int = BAR_WIDTH) -> str:
    """ASCII bar 0..1."""
    filled = int(value * width)
    filled = max(0, min(filled, width))
    return BLOCK_FULL * filled + BLOCK_EMPTY * (width - filled)


def _render_attractor(sig: TrajectorySignature) -> list[str]:
    """Render attractor basin (Α) as 4 dimension bars."""
    lines = []
    if not sig.attractor or not sig.attractor.get("center"):
        lines.append("  (attractor not yet computed)")
        return lines

    center = sig.attractor["center"]
    variance = sig.attractor.get("variance") or [0, 0, 0, 0]

    for i, dim in enumerate(DIMS):
        c = center[i] if i < len(center) else 0.5
        v = variance[i] if i < len(variance) else 0
        lines.append(f"  {dim:10} {_bar(c)} {c:.3f} ±{v:.3f}")

    return lines


def _render_overview(sig: TrajectorySignature) -> list[str]:
    """Render overview metrics."""
    lines = []
    stability = sig.get_stability_score()
    lines.append(f"  stability     {_bar(stability)} {stability:.3f}")
    lines.append(f"  observations {sig.observation_count}")

    lineage = sig.lineage_similarity()
    if lineage is not None:
        lines.append(f"  lineage sim  {_bar(lineage)} {lineage:.3f}")
    else:
        lines.append("  lineage sim  (no genesis)")

    return lines


def render_ascii(sig: TrajectorySignature) -> str:
    """Render trajectory as ASCII to stdout."""
    out = []
    out.append("")
    out.append("  Σ Trajectory Signature")
    out.append("  " + "─" * 50)
    out.append("")
    out.append("  Overview")
    out.extend(_render_overview(sig))
    out.append("")
    out.append("  Attractor (Α)")
    out.extend(_render_attractor(sig))
    out.append("")
    out.append(f"  computed at {sig.computed_at.isoformat()}")
    out.append("")
    return "\n".join(out)


def render_html(sig: TrajectorySignature, genesis: TrajectorySignature | None) -> str:
    """Render trajectory as standalone HTML snippet."""
    attr = sig.attractor or {}
    center = attr.get("center", [0.5] * 4)
    variance = attr.get("variance", [0] * 4)

    dim_bars = ""
    for i, dim in enumerate(DIMS):
        c = center[i] if i < len(center) else 0.5
        v = variance[i] if i < len(variance) else 0
        pct = int(c * 100)
        dim_bars += f"""
        <div class="dim-row">
            <span class="dim-label">{dim}</span>
            <div class="dim-track"><div class="dim-fill" style="width:{pct}%"></div></div>
            <span class="dim-val">{c:.2f} ±{v:.2f}</span>
        </div>"""

    lineage = sig.lineage_similarity()
    lineage_html = f'<div class="lineage">lineage: {lineage:.2f}</div>' if lineage is not None else ""

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Lumen Trajectory Σ</title>
    <style>
        body {{ font-family: system-ui; background: #0a0a0e; color: #e0e0e0; padding: 24px; }}
        .card {{ background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; padding: 20px; margin-bottom: 16px; }}
        .title {{ font-size: 11px; letter-spacing: 0.1em; color: rgba(255,255,255,0.4); margin-bottom: 12px; }}
        .dim-row {{ display: flex; align-items: center; gap: 8px; margin: 4px 0; font-size: 12px; }}
        .dim-label {{ width: 80px; color: rgba(255,255,255,0.6); }}
        .dim-track {{ flex: 1; height: 6px; background: rgba(255,255,255,0.08); border-radius: 3px; overflow: hidden; }}
        .dim-fill {{ height: 100%; background: #7ecf8b; border-radius: 3px; }}
        .dim-val {{ width: 70px; text-align: right; font-family: monospace; font-size: 10px; color: rgba(255,255,255,0.35); }}
        .lineage {{ margin-top: 8px; font-size: 11px; color: rgba(255,255,255,0.4); }}
        .meta {{ font-size: 10px; color: rgba(255,255,255,0.25); margin-top: 12px; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="title">Σ Trajectory Signature</div>
        <div>stability: {sig.get_stability_score():.3f} · {sig.observation_count} observations</div>
        {lineage_html}
        <div class="meta">computed {sig.computed_at.isoformat()}</div>
    </div>
    <div class="card">
        <div class="title">Α Attractor Basin</div>
        {dim_bars}
    </div>
</body>
</html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Visualize Lumen trajectory signature")
    parser.add_argument("--html", nargs="?", const="", metavar="PATH", help="Write HTML to file (default: trajectory_viz.html)")
    parser.add_argument("--compute", action="store_true", help="Compute from live data instead of loading from disk")
    args = parser.parse_args()

    sig: TrajectorySignature | None = None

    if args.compute:
        try:
            db_path = str(Path.home() / ".anima" / "anima.db")
            from anima_mcp.growth import get_growth_system
            from anima_mcp.anima_history import get_anima_history
            from anima_mcp.self_model import get_self_model
            sig = compute_trajectory_signature(
                growth_system=get_growth_system(db_path=db_path),
                self_model=get_self_model(),
                anima_history=get_anima_history(),
            )
        except Exception as e:
            print(f"Compute failed: {e}", file=sys.stderr)
            return 1
    else:
        sig = load_trajectory()
        if sig is None:
            sig = load_genesis()
        if sig is None:
            print("No trajectory found. Run with --compute from server context, or run anima once and sleep.", file=sys.stderr)
            return 1

    # ASCII output
    print(render_ascii(sig))

    # HTML output
    if args.html is not None:
        path = Path(args.html) if args.html else Path.cwd() / "trajectory_viz.html"
        genesis = load_genesis()
        html = render_html(sig, genesis)
        path.write_text(html, encoding="utf-8")
        print(f"Wrote {path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
