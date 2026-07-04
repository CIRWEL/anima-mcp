"""Phase-2 governance SHM passthrough (ANIMA_GOVERNANCE_FROM_SHM).

The reader copies the Elixir shadow envelope's governance slice into the
live envelope. Fail-closed contract: anything that is not a provably fresh
verdict — no action (#97), no/unparseable governance_at, stale beyond the
210s governance contract, malformed file — yields None, leaving the MCP
server's 240s fallback as the safety net.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from anima_mcp.governance_passthrough import (
    DEFAULT_STALE_SECONDS,
    passthrough_path_from_env,
    read_shadow_governance,
    stale_seconds_from_env,
)

NOW = datetime(2026, 7, 4, 17, 0, 0)


def _write_shadow(tmp_path: Path, gov: dict | None, *, data_extra: dict | None = None) -> Path:
    payload: dict = {"updated_at": NOW.isoformat(), "data": dict(data_extra or {})}
    if gov is not None:
        payload["data"]["governance"] = gov
    p = tmp_path / "anima_state.shadow.json"
    p.write_text(json.dumps(payload))
    return p


def _slice(age_seconds: float = 10.0, **overrides) -> dict:
    gov = {
        "action": "proceed",
        "margin": "settling",
        "source": "unitares_ex",
        "governance_at": (NOW - timedelta(seconds=age_seconds)).isoformat(),
    }
    gov.update(overrides)
    return gov


def test_fresh_slice_is_copied_verbatim(tmp_path):
    gov = _slice(age_seconds=10)
    path = _write_shadow(tmp_path, gov)
    out = read_shadow_governance(path, now=NOW)
    assert out == gov
    assert out is not gov  # a copy, not a shared reference


def test_stale_slice_is_dropped(tmp_path):
    path = _write_shadow(tmp_path, _slice(age_seconds=DEFAULT_STALE_SECONDS + 1))
    assert read_shadow_governance(path, now=NOW) is None


def test_boundary_age_is_still_fresh(tmp_path):
    path = _write_shadow(tmp_path, _slice(age_seconds=DEFAULT_STALE_SECONDS - 1))
    assert read_shadow_governance(path, now=NOW) is not None


def test_actionless_shape_is_never_a_verdict(tmp_path):
    gov = _slice(age_seconds=5)
    del gov["action"]
    path = _write_shadow(tmp_path, gov)
    assert read_shadow_governance(path, now=NOW) is None


def test_missing_governance_at_is_dropped(tmp_path):
    gov = _slice(age_seconds=5)
    del gov["governance_at"]
    path = _write_shadow(tmp_path, gov)
    assert read_shadow_governance(path, now=NOW) is None


def test_unparseable_governance_at_is_dropped(tmp_path):
    path = _write_shadow(tmp_path, _slice(governance_at="not-a-timestamp"))
    assert read_shadow_governance(path, now=NOW) is None


def test_aware_timestamp_is_compared_in_its_zone(tmp_path):
    aware_now = datetime(2026, 7, 4, 17, 0, 0, tzinfo=timezone.utc)
    gov = _slice()
    gov["governance_at"] = (aware_now - timedelta(seconds=30)).isoformat()
    path = _write_shadow(tmp_path, gov)
    assert read_shadow_governance(path, now=aware_now) is not None


def test_missing_governance_slice(tmp_path):
    path = _write_shadow(tmp_path, None, data_extra={"readings": {}})
    assert read_shadow_governance(path, now=NOW) is None


def test_missing_file(tmp_path):
    assert read_shadow_governance(tmp_path / "nope.json", now=NOW) is None


def test_malformed_json(tmp_path):
    p = tmp_path / "torn.json"
    p.write_text('{"data": {"governance": {')
    assert read_shadow_governance(p, now=NOW) is None


def test_env_path_unset_and_set(monkeypatch):
    monkeypatch.delenv("ANIMA_GOVERNANCE_FROM_SHM", raising=False)
    assert passthrough_path_from_env() is None
    monkeypatch.setenv("ANIMA_GOVERNANCE_FROM_SHM", "/dev/shm/anima_state.shadow.json")
    assert passthrough_path_from_env() == Path("/dev/shm/anima_state.shadow.json")


def test_env_stale_default_override_and_garbage(monkeypatch):
    monkeypatch.delenv("ANIMA_GOV_SHADOW_STALE_SECONDS", raising=False)
    assert stale_seconds_from_env() == DEFAULT_STALE_SECONDS
    monkeypatch.setenv("ANIMA_GOV_SHADOW_STALE_SECONDS", "300")
    assert stale_seconds_from_env() == 300.0
    monkeypatch.setenv("ANIMA_GOV_SHADOW_STALE_SECONDS", "soon")
    assert stale_seconds_from_env() == DEFAULT_STALE_SECONDS
