"""What range does Lumen's own state actually occupy?

Any fixed cut on warmth/clarity/stability/presence implicitly claims to know
that range. `self_model.observe_temperament` tests `warmth_baseline_low` as
`warmth_mean < 0.40` and `presence_baseline_low` as `presence_mean < 0.35`;
measured live 2026-08-29, temperament warmth was 0.686 and presence 0.721, so
each belief takes contradicting evidence every cycle and converges to a verdict
it was never going to revise. Whether that is what really happens is a question
about a distribution, and nothing reported one.

The proxy caveat is the substance of these tests as much as the percentiles:
temperament is never persisted, `state_history` holds the raw anima it is
smoothed from, and an EMA shares its source's mean with a narrower spread — so
the report is conclusive in only one direction.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from anima_mcp import anima_distributions as ad  # noqa: E402


def _db(tmp_path, rows=None, table=True, columns=None):
    db = tmp_path / "anima.db"
    con = sqlite3.connect(db)
    if table:
        cols = columns or "warmth real, clarity real, stability real, presence real"
        con.execute(f"create table state_history (timestamp text, {cols})")
        base = datetime.now() - timedelta(days=5)
        for i, r in enumerate(rows or []):
            con.execute(
                f"insert into state_history values ({','.join('?' * (len(r) + 1))})",
                ((base + timedelta(minutes=i)).isoformat(timespec="seconds"), *r))
    else:
        con.execute("create table unrelated (x int)")
    con.commit()
    con.close()
    return db


class TestReport:

    def test_reports_percentiles_per_dimension(self, tmp_path):
        rows = [(0.60 + i / 500, 0.80, 0.75, 0.70) for i in range(100)]
        r = ad.anima_report(str(_db(tmp_path, rows)))
        assert r["available"] is True
        w = r["dimensions"]["warmth"]
        assert w["n"] == 100
        assert w["min"] == 0.6 and round(w["max"], 3) == 0.798
        assert w["p05"] < w["p25"] < w["p50"] < w["p75"] < w["p95"]

    def test_the_question_it_exists_to_answer(self, tmp_path):
        """A warmth floor clear of 0.40 makes warmth_baseline_low a constant."""
        rows = [(0.60 + i / 500, 0.80, 0.75, 0.72) for i in range(100)]
        dims = ad.anima_report(str(_db(tmp_path, rows)))["dimensions"]
        assert dims["warmth"]["p05"] > 0.40      # never supports the belief
        assert dims["presence"]["p05"] > 0.35    # nor this one

    def test_a_range_that_straddles_the_cut_is_not_conclusive(self, tmp_path):
        """The other direction: raw anima dipping below does not settle it,
        because the EMA may have smoothed exactly those excursions away."""
        rows = [(0.20 + i / 200, 0.8, 0.75, 0.7) for i in range(100)]
        dims = ad.anima_report(str(_db(tmp_path, rows)))["dimensions"]
        assert dims["warmth"]["p05"] < 0.40 < dims["warmth"]["p95"]

    def test_caveat_travels_with_the_numbers(self, tmp_path):
        """A reader who never opens the module still gets the one-sidedness."""
        r = ad.anima_report(str(_db(tmp_path, [(0.6, 0.8, 0.7, 0.7)] * 5)))
        caveat = r["temperament_caveat"].lower()
        assert "not persisted" in caveat
        assert "narrower" in caveat
        assert "inconclusive" in caveat
        assert r["source"] == "state_history (raw anima)"

    def test_nulls_excluded_not_counted(self, tmp_path):
        rows = [(None, 0.8, 0.7, 0.7)] * 10 + [(0.65, 0.8, 0.7, 0.7)] * 10
        dims = ad.anima_report(str(_db(tmp_path, rows)))["dimensions"]
        assert dims["warmth"]["n"] == 10 and dims["warmth"]["min"] == 0.65
        assert dims["clarity"]["n"] == 20


class TestFailsTowardUnknown:

    def test_missing_table(self, tmp_path):
        r = ad.anima_report(str(_db(tmp_path, table=False)))
        assert r["available"] is False and "not present" in r["reason"]

    def test_missing_database(self, tmp_path):
        r = ad.anima_report(str(tmp_path / "nope.db"))
        assert r["available"] is False and "unreadable" in r["reason"]

    def test_missing_column_is_named_not_silently_dropped(self, tmp_path):
        db = _db(tmp_path, [(0.6, 0.8)] * 5, columns="warmth real, clarity real")
        dims = ad.anima_report(str(db))["dimensions"]
        assert dims["warmth"]["available"] is True
        assert dims["stability"]["available"] is False
        assert "column not present" in dims["stability"]["reason"]

    def test_empty_dimension_is_unavailable_not_zero(self, tmp_path):
        """n=0 must not read as a dimension pinned at 0.0."""
        dims = ad.anima_report(
            str(_db(tmp_path, [(None, 0.8, 0.7, 0.7)] * 5)))["dimensions"]
        assert dims["warmth"]["available"] is False and dims["warmth"]["n"] == 0

    def test_report_never_writes(self, tmp_path):
        db = _db(tmp_path, [(0.6, 0.8, 0.7, 0.7)] * 5)
        before = db.stat().st_mtime_ns, db.stat().st_size
        assert ad.anima_report(str(db))["available"] is True
        assert (db.stat().st_mtime_ns, db.stat().st_size) == before


class TestDiagnosticsExposure:

    def test_schema_advertises_the_opt_in(self):
        from anima_mcp.tool_registry import TOOLS
        tool = next(t for t in TOOLS if t.name == "diagnostics")
        props = tool.inputSchema["properties"]
        assert props["anima_distributions"]["type"] == "boolean"

    def test_off_by_default(self):
        import asyncio
        from anima_mcp.handlers.display_ops import handle_diagnostics
        out = json.loads(asyncio.run(handle_diagnostics({}))[0].text)
        assert "anima_distributions" not in out

    def test_included_when_requested(self, monkeypatch):
        import asyncio
        import anima_mcp.anima_distributions as mod
        from anima_mcp.handlers.display_ops import handle_diagnostics
        monkeypatch.setattr(mod, "anima_report",
                            lambda **kw: {"available": True, "days": kw.get("days")})
        out = json.loads(asyncio.run(handle_diagnostics(
            {"anima_distributions": True, "derive_days": 30}))[0].text)
        assert out["anima_distributions"] == {"available": True, "days": 30}

    def test_failure_reports_itself(self, monkeypatch):
        import asyncio
        import anima_mcp.anima_distributions as mod
        from anima_mcp.handlers.display_ops import handle_diagnostics

        def _boom(**kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(mod, "anima_report", _boom)
        out = json.loads(asyncio.run(handle_diagnostics(
            {"anima_distributions": True}))[0].text)
        assert out["anima_distributions"]["available"] is False
        assert "boom" in out["anima_distributions"]["reason"]
