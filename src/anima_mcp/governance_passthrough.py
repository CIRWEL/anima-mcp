"""Phase-2 governance seam: consume the Elixir broker's governance verdicts.

When ``ANIMA_GOVERNANCE_FROM_SHM`` is set (to the Elixir shadow envelope
path), the Python broker makes NO UNITARES calls of its own and instead
copies the ``governance`` slice — which carries its own ``governance_at`` —
from the shadow envelope into the live envelope it writes. Same seam
contract as Phase-1's ``ANIMA_ENV_SENSORS_FROM_SHM``: single-writer-per-file
is preserved (Elixir owns the shadow file; this broker remains sole writer
of the live file), and the flag is independently reversible.

Fail-closed by design: a missing, malformed, action-less, or stale slice
yields None and the live envelope simply carries no fresh governance for
that tick — the MCP server's SERVER_GOVERNANCE_FALLBACK (240s) is the
safety net, exactly as when the bridge is down. Nothing here fabricates a
verdict: a shape without an ``action`` is never written as one (#97), and
a slice older than the governance staleness contract (210s, the same
threshold SHM consumers apply) is not re-published as current.

Rollback: unset the env var and restart; the bridge check-in loop resumes.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

# Matches SHM_GOVERNANCE_STALE_SECONDS on the consuming side: governance is
# published every ~180s, so anything older than 210s is not a current verdict.
DEFAULT_STALE_SECONDS = 210.0


def passthrough_path_from_env() -> Optional[Path]:
    """Shadow envelope path from ANIMA_GOVERNANCE_FROM_SHM, or None if unset."""
    raw = os.environ.get("ANIMA_GOVERNANCE_FROM_SHM", "").strip()
    return Path(raw) if raw else None


def stale_seconds_from_env() -> float:
    """Staleness threshold from ANIMA_GOV_SHADOW_STALE_SECONDS (default 210)."""
    raw = os.environ.get("ANIMA_GOV_SHADOW_STALE_SECONDS", "")
    try:
        return float(raw) if raw.strip() else DEFAULT_STALE_SECONDS
    except ValueError:
        return DEFAULT_STALE_SECONDS


def read_shadow_governance(
    path: Path,
    stale_seconds: float = DEFAULT_STALE_SECONDS,
    now: Optional[datetime] = None,
) -> Optional[dict]:
    """Return the shadow envelope's governance slice if provably fresh.

    None on any failure: unreadable/malformed file, missing slice, no
    ``action`` (#97: never a verdict), missing/unparseable ``governance_at``,
    or age beyond ``stale_seconds``. The Elixir client writes ``governance_at``
    as naive-local ISO-8601; aware timestamps are compared in their own zone.
    """
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    data = raw.get("data") if isinstance(raw, dict) else None
    gov = data.get("governance") if isinstance(data, dict) else None
    if not isinstance(gov, dict) or not gov.get("action"):
        return None
    gov_at = gov.get("governance_at")
    if not isinstance(gov_at, str) or not gov_at:
        return None
    try:
        ts = datetime.fromisoformat(gov_at)
    except ValueError:
        return None
    ref = now or (datetime.now(ts.tzinfo) if ts.tzinfo else datetime.now())
    if (ref - ts).total_seconds() > stale_seconds:
        return None
    return dict(gov)
