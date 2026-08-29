"""Curiosity has to be able to run out.

`_update_attention` split "still exploring" (curiosity drains) from "pattern
found" (curiosity regenerates) with one absolute constant, C < 0.4, against a
behavioural coherence distribution that differs per era. Measured live on a
resonance piece 2026-08-02, C sat in [0.377, 0.498] mean 0.458 — so ~95% of
ticks took the regenerating branch, curiosity rose into its 1.0 clamp, and
every gate downstream of it was structurally unreachable rather than mistuned:

    attention_exhausted()   curiosity < 0.15    never true
    earned_composition      curiosity < 0.2     never true
    earned_coherence        needs both of the above and mean_C > 0.6

26 of the first 34 instrumented completions landed on the 8-hour cap and none
was earned. Design invariant 1, on the signal that is supposed to end a piece.

These tests pin three things: that the built-in path is byte-identical to the
old formula (an un-derived deployment must not move), that a per-era pivot
makes exhaustion reachable on the measured range, and that the derivation
refuses rather than trades one dead gate for another.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from anima_mcp.display.drawing_engine import (  # noqa: E402
    _DEFAULT_CURIOSITY_PIVOT,
    _curiosity_pivot,
    curiosity_drain,
)

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "derive_curiosity_thresholds.py"

# The live resonance range, measured 2026-08-02. The whole reason this exists.
RESONANCE_C_RANGE = (0.377, 0.498)
RESONANCE_C_MEAN = 0.458

# Five below the centre, five above, interleaved. Median = the centre.
_OFFSETS = [-1.0, 0.6, -0.4, 1.0, -0.8, 0.2, -0.6, 0.8, -0.2, 0.4]


def _resonance_ticks(n=200):
    """Coherence samples spanning the measured resonance range."""
    lo, hi = RESONANCE_C_RANGE
    return [lo + (hi - lo) * i / (n - 1) for i in range(n)]


def _net_drift(ticks, pivot, arc_phase="developing"):
    """Total curiosity change over `ticks`. Negative means it regenerates."""
    return -sum(curiosity_drain(arc_phase, c, pivot) for c in ticks)


# ---------------------------------------------------------------------------
# The formula itself
# ---------------------------------------------------------------------------

class TestCuriosityDrain:

    def test_default_pivot_reproduces_the_historical_formula(self):
        """A deployment that has derived nothing must behave exactly as before.

        Pinned against the literal pre-change expressions, not a paraphrase.
        """
        for C in (0.0, 0.1, 0.39, 0.4, 0.41, 0.6, 0.65, 0.9, 1.0):
            expected = 0.003 * (1.0 - C) if C < 0.4 else -0.001 * C
            assert curiosity_drain("developing", C, _DEFAULT_CURIOSITY_PIVOT) == expected

    @pytest.mark.parametrize("phase", ["opening", "developing", "closing"])
    def test_pivot_is_the_exploring_boundary(self, phase):
        """Below the pivot drains (positive), at or above regenerates."""
        assert curiosity_drain(phase, 0.30, 0.45) > 0
        assert curiosity_drain(phase, 0.45, 0.45) < 0
        assert curiosity_drain(phase, 0.60, 0.45) < 0

    def test_resolving_branch_ignores_the_pivot(self):
        """Its two constants are deliberately untouched — entry to `resolving`
        needs C > 0.6, which low-C eras never reach, so relativising them would
        move a gate nothing currently arrives at."""
        for pivot in (0.2, 0.4, 0.8):
            assert curiosity_drain("resolving", 0.50, pivot) == 0.002
            assert curiosity_drain("resolving", 0.70, pivot) == -0.0005 * 0.70


class TestTheDefectItself:

    def test_measured_resonance_range_regenerates_under_the_builtin(self):
        """The bug, pinned: on its own lived range, resonance's curiosity goes
        UP. Not slowly — monotonically, into the 1.0 clamp."""
        ticks = _resonance_ticks()
        assert max(ticks) < _DEFAULT_CURIOSITY_PIVOT + 0.1
        drift = _net_drift(ticks, _DEFAULT_CURIOSITY_PIVOT)
        assert drift > 0, "expected net regeneration under the built-in pivot"
        # A lopsided majority, not a marginal one. Swept uniformly across the
        # measured range this lands ~0.8; the 0.95 recorded live is higher
        # because the real distribution concentrates near the 0.458 mean rather
        # than spreading evenly to the endpoints. Either way the sign is set by
        # where the constant sits relative to the range, not by the shape.
        regenerating = sum(
            1 for c in ticks
            if curiosity_drain("developing", c, _DEFAULT_CURIOSITY_PIVOT) < 0)
        assert regenerating / len(ticks) > 0.75

    def test_own_median_pivot_makes_it_deplete(self):
        """The fix: pivoting on the era's own median turns the sign over."""
        ticks = _resonance_ticks()
        median = sorted(ticks)[len(ticks) // 2]
        assert _net_drift(ticks, median) < 0, "expected net depletion at the median"

    def test_exhaustion_is_reachable_in_a_plausible_piece(self):
        """Net drift is not enough — it has to reach the floor while the piece
        is still being drawn. Replayed mark by mark from 1.0."""
        ticks = _resonance_ticks()
        median = sorted(ticks)[len(ticks) // 2]
        curiosity, marks = 1.0, 0
        while curiosity >= 0.15 and marks < 20000:
            c = ticks[marks % len(ticks)]
            curiosity = max(0.0, min(1.0, curiosity - curiosity_drain(
                "developing", c, median)))
            marks += 1
        assert curiosity < 0.15, "curiosity never reached the exhaustion floor"
        assert marks < 20000


# ---------------------------------------------------------------------------
# Calibration plumbing
# ---------------------------------------------------------------------------

class TestCuriosityPivotLookup:

    def _cal(self, monkeypatch, thresholds):
        import anima_mcp.config as config_mod

        class _Cal:
            drawing_thresholds = thresholds

        monkeypatch.setattr(config_mod, "get_calibration", lambda: _Cal())

    def test_default_matches_the_historical_constant(self):
        assert _DEFAULT_CURIOSITY_PIVOT == 0.4

    def test_absent_key_falls_back(self, monkeypatch):
        self._cal(monkeypatch, {"CURIOSITY_PIVOT_resonance": 0.46})
        assert _curiosity_pivot("gestural") == _DEFAULT_CURIOSITY_PIVOT
        assert _curiosity_pivot("resonance") == 0.46

    def test_unknown_era_falls_back(self, monkeypatch):
        self._cal(monkeypatch, {})
        assert _curiosity_pivot(None) == _DEFAULT_CURIOSITY_PIVOT
        assert _curiosity_pivot("") == _DEFAULT_CURIOSITY_PIVOT

    @pytest.mark.parametrize("bad", [0.0, 1.0, -0.2, 1.5, "not-a-number", None])
    def test_a_non_pivot_is_rejected_not_clamped(self, monkeypatch, bad):
        """0.0 puts every tick on the regenerating branch — today's bug, but
        total. 1.0 puts every tick on the draining branch and pieces end early.
        Neither is a pivot, so neither is treated as one."""
        self._cal(monkeypatch, {"CURIOSITY_PIVOT_resonance": bad})
        assert _curiosity_pivot("resonance") == _DEFAULT_CURIOSITY_PIVOT

    def test_broken_calibration_fails_open(self, monkeypatch):
        import anima_mcp.config as config_mod
        monkeypatch.setattr(config_mod, "get_calibration",
                            lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        assert _curiosity_pivot("resonance") == _DEFAULT_CURIOSITY_PIVOT

    def test_two_eras_two_pivots(self, monkeypatch):
        """The point of making it per-era: one constant cannot split a range
        capping at 0.5 and one reaching 0.8 the same way."""
        self._cal(monkeypatch, {"CURIOSITY_PIVOT_resonance": 0.458,
                                "CURIOSITY_PIVOT_gestural": 0.72})
        assert curiosity_drain("developing", 0.60, _curiosity_pivot("resonance")) < 0
        assert curiosity_drain("developing", 0.60, _curiosity_pivot("gestural")) > 0


# ---------------------------------------------------------------------------
# The derivation script
# ---------------------------------------------------------------------------

class TestDerivationScript:

    def _make_db(self, tmp_path, eras=None):
        """Seed drawing_trajectory. Each era: (pieces, intervals, marks/interval,
        coherence centre, spread)."""
        eras = eras or {"resonance": (30, 20, 100, 0.458, 0.06)}
        db = tmp_path / "anima.db"
        con = sqlite3.connect(db)
        con.execute("""create table drawing_trajectory (
            era text, piece_uid text, timestamp text, elapsed_seconds real,
            coherence real, arc_phase text, marks_delta integer,
            mark_count integer)""")
        base = datetime.now() - timedelta(days=10)
        rows = []
        for era, (pieces, intervals, mpi, centre, spread) in eras.items():
            for p in range(pieces):
                for i in range(intervals):
                    # Balanced around the centre and interleaved, so the median
                    # lands on the centre and drain/regen alternate. A monotone
                    # ramp instead makes every piece drain hard early and drift
                    # back up, which reads as `premature` for a reason that is
                    # an artefact of the fixture rather than of the pivot.
                    c = centre + spread * _OFFSETS[i % len(_OFFSETS)]
                    rows.append((
                        era, f"{era}-{p}",
                        (base + timedelta(minutes=5 * (p * intervals + i))
                         ).isoformat(timespec="seconds"),
                        300.0 * i, c, "developing", mpi, mpi * (i + 1)))
        con.executemany(
            "insert into drawing_trajectory values (?,?,?,?,?,?,?,?)", rows)
        con.commit()
        con.close()
        return db

    def _run(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args],
                              capture_output=True, text=True, timeout=120)

    def test_derives_a_pivot_inside_the_eras_own_range(self, tmp_path):
        db = self._make_db(tmp_path)
        r = self._run("--db", str(db), "--days", "90")
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        pivot = out["CURIOSITY_PIVOT_resonance"]
        assert 0.458 - 0.06 <= pivot <= 0.458 + 0.06
        report = json.loads(r.stderr[r.stderr.index("{"):])["report"]
        assert report["resonance"]["verdict"]["ok"] is True

    def test_report_shows_the_builtin_baseline_beside_the_proposal(self, tmp_path):
        """The report has to show the change, not only the proposal — the
        built-in is what the creature is running right now."""
        r = self._run("--db", str(self._make_db(tmp_path)), "--days", "90")
        assert r.returncode == 0, r.stderr
        entry = json.loads(r.stderr[r.stderr.index("{"):])["report"]["resonance"]
        assert entry["baseline_builtin"]["reached_composition_floor"] == 0
        assert entry["verdict"]["reached_composition_floor"] > 0

    def test_refuses_a_pivot_that_leaves_the_gate_dead(self, tmp_path):
        """Pieces too short for curiosity to deplete: a dead gate traded for a
        dead gate is not a fix. (This is geometric's shape — ~70 marks.)"""
        db = self._make_db(tmp_path, {"geometric": (40, 15, 5, 0.458, 0.06)})
        r = self._run("--db", str(db), "--days", "90")
        assert r.returncode != 0
        assert "unreachable" in r.stderr

    def test_refuses_a_pivot_that_ends_pieces_early(self, tmp_path):
        """Very low coherence drains hard; crossing at a fraction of the marks
        would end pieces before they are worked."""
        db = self._make_db(tmp_path, {"pointillist": (30, 40, 200, 0.05, 0.03)})
        r = self._run("--db", str(db), "--days", "90")
        assert r.returncode != 0
        assert "premature" in r.stderr

    def test_refuses_a_sliver_of_data(self, tmp_path):
        db = self._make_db(tmp_path, {"resonance": (2, 5, 100, 0.458, 0.06)})
        r = self._run("--db", str(db), "--days", "90")
        assert r.returncode != 0
        assert "refusing" in r.stderr

    def test_a_thin_era_keeps_the_builtin_without_sinking_the_run(self, tmp_path):
        db = self._make_db(tmp_path, {
            "resonance": (30, 20, 100, 0.458, 0.06),
            "field": (2, 10, 100, 0.5, 0.05),
        })
        r = self._run("--db", str(db), "--days", "90")
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert "CURIOSITY_PIVOT_resonance" in out
        assert "CURIOSITY_PIVOT_field" not in out

    def test_apply_merges_and_preserves_the_coverage_keys(self, tmp_path):
        """derive_drawing_thresholds.py owns COVERAGE_* in the same dict —
        replacing it whole would silently revert that derivation."""
        db = self._make_db(tmp_path)
        cfg = tmp_path / "anima_config.json"
        cfg.write_text(json.dumps({"nervous_system": {
            "cpu_temp_min": 40.0,
            "drawing_thresholds": {"COVERAGE_DENSE_BELOW": 0.69,
                                   "CURIOSITY_PIVOT_retired_era": 0.31},
        }}))
        r = self._run("--db", str(db), "--apply", str(cfg))
        assert r.returncode == 0, r.stderr
        saved = json.loads(cfg.read_text())["nervous_system"]
        assert saved["cpu_temp_min"] == 40.0
        assert saved["drawing_thresholds"]["COVERAGE_DENSE_BELOW"] == 0.69
        assert "CURIOSITY_PIVOT_resonance" in saved["drawing_thresholds"]
        # A pivot nothing re-verified this run must stop steering that era.
        assert "CURIOSITY_PIVOT_retired_era" not in saved["drawing_thresholds"]
        assert list(tmp_path.glob("anima_config.json.bak-curiosity-*"))

    def test_without_apply_nothing_is_written(self, tmp_path):
        db = self._make_db(tmp_path)
        cfg = tmp_path / "anima_config.json"
        original = json.dumps({"nervous_system": {"cpu_temp_min": 40.0}})
        cfg.write_text(original)
        r = self._run("--db", str(db), "--days", "90")
        assert r.returncode == 0, r.stderr
        assert cfg.read_text() == original


# ---------------------------------------------------------------------------
# The replay, and the report the server serves
# ---------------------------------------------------------------------------

from anima_mcp import drawing_derivation as dd  # noqa: E402


def _naive_replay(intervals, pivot):
    """The per-mark loop the closed form replaces. Kept only as the oracle."""
    curiosity, marks_seen, crossed_at = dd.CURIOSITY_START, 0, None
    for iv in intervals:
        for _ in range(iv["marks_delta"]):
            curiosity = max(0.0, min(1.0, curiosity - curiosity_drain(
                iv["arc_phase"], iv["coherence"], pivot)))
            marks_seen += 1
            if crossed_at is None and curiosity < dd.COMPOSITION_FLOOR:
                crossed_at = marks_seen
    return curiosity, crossed_at, marks_seen


class TestReplayEquivalence:
    """The closed form must equal the loop it replaces.

    `replay` collapses each interval to one arithmetic step because coherence
    and arc_phase are constant within a trajectory sample, so the per-mark
    delta is constant and curiosity moves monotonically. That equivalence is
    what makes it safe to serve from inside the server — an unbounded per-mark
    loop over the whole corpus is not.
    """

    @pytest.mark.parametrize("pivot", [0.2, 0.4, 0.458, 0.7])
    @pytest.mark.parametrize("centre,spread", [(0.458, 0.06), (0.05, 0.03), (0.8, 0.1)])
    def test_matches_the_naive_loop(self, pivot, centre, spread):
        intervals = [{"coherence": centre + spread * _OFFSETS[i % len(_OFFSETS)],
                      "arc_phase": "developing", "marks_delta": 40 + i}
                     for i in range(25)]
        fast, fast_cross, fast_marks = dd.replay(intervals, pivot)
        slow, slow_cross, slow_marks = _naive_replay(intervals, pivot)
        assert fast_marks == slow_marks
        assert fast == pytest.approx(slow, abs=1e-9)
        assert fast_cross == slow_cross

    def test_matches_through_the_zero_clamp(self):
        """Hard draining must stop at 0.0 in both, not go negative."""
        intervals = [{"coherence": 0.0, "arc_phase": "developing",
                      "marks_delta": 5000}]
        fast = dd.replay(intervals, 0.9)
        slow = _naive_replay(intervals, 0.9)
        assert fast[0] == 0.0 and slow[0] == 0.0
        assert fast[1] == slow[1]

    def test_matches_through_the_one_clamp(self):
        """Pure regeneration must stop at 1.0 and never cross."""
        intervals = [{"coherence": 0.9, "arc_phase": "developing",
                      "marks_delta": 5000}]
        fast = dd.replay(intervals, 0.1)
        slow = _naive_replay(intervals, 0.1)
        assert fast[0] == 1.0 and slow[0] == 1.0
        assert fast[1] is None and slow[1] is None


class TestReportFailsTowardUnknown:
    """A broken derivation must say so, never report an empty corpus.

    An empty `eras` with `available: true` would read as "no era qualifies",
    which is a finding. A missing database is not a finding.
    """

    def test_missing_database_is_unavailable_not_empty(self, tmp_path):
        r = dd.derive_report(str(tmp_path / "nope.db"))
        assert r["available"] is False
        assert "unreadable" in r["reason"]

    def test_missing_table_is_unavailable_not_empty(self, tmp_path):
        db = tmp_path / "bare.db"
        sqlite3.connect(db).close()
        r = dd.derive_report(str(db))
        assert r["available"] is False
        assert "unreadable" in r["reason"]

    def test_report_never_writes_to_the_database(self, tmp_path):
        """Opened mode=ro — the server-side path must not be able to mutate."""
        db = TestDerivationScript()._make_db(tmp_path)
        before = db.stat().st_mtime_ns, db.stat().st_size
        r = dd.derive_report(str(db))
        assert r["available"] is True
        assert (db.stat().st_mtime_ns, db.stat().st_size) == before

    def test_sliver_refuses_without_claiming_eras_qualified(self, tmp_path):
        db = TestDerivationScript()._make_db(
            tmp_path, {"resonance": (2, 5, 100, 0.458, 0.06)})
        r = dd.derive_report(str(db))
        assert r["available"] is True
        assert "_refused" in r["eras"]
        assert r["thresholds"] == {}


class TestDiagnosticsExposure:
    """The report has to be reachable on a device with no shell."""

    def test_tool_schema_advertises_the_opt_in(self):
        from anima_mcp.tool_registry import TOOLS
        tool = next(t for t in TOOLS if t.name == "diagnostics")
        props = tool.inputSchema["properties"]
        assert "derive_curiosity" in props
        assert props["derive_curiosity"]["type"] == "boolean"
        assert "derive_days" in props

    def test_off_by_default(self):
        """It scans the corpus; diagnostics is called routinely. Opt-in only."""
        import asyncio
        from anima_mcp.handlers.display_ops import handle_diagnostics
        out = json.loads(asyncio.run(handle_diagnostics({}))[0].text)
        assert "curiosity_derivation" not in out

    def test_included_when_requested(self, monkeypatch):
        import asyncio
        import anima_mcp.drawing_derivation as mod
        from anima_mcp.handlers.display_ops import handle_diagnostics
        monkeypatch.setattr(mod, "derive_report",
                            lambda **kw: {"available": True, "days": kw.get("days")})
        out = json.loads(asyncio.run(
            handle_diagnostics({"derive_curiosity": True, "derive_days": 30}))[0].text)
        assert out["curiosity_derivation"] == {"available": True, "days": 30}

    def test_a_broken_derivation_reports_instead_of_vanishing(self, monkeypatch):
        """Same rule as novelty_settling: a silent diagnostic is worse than none."""
        import asyncio
        import anima_mcp.drawing_derivation as mod
        from anima_mcp.handlers.display_ops import handle_diagnostics

        def _boom(**kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(mod, "derive_report", _boom)
        out = json.loads(asyncio.run(
            handle_diagnostics({"derive_curiosity": True}))[0].text)
        assert out["curiosity_derivation"]["available"] is False
        assert "boom" in out["curiosity_derivation"]["reason"]

    def test_none_arguments_do_not_crash_the_rest_path(self):
        """REST passes the body's `arguments` through; explicit null arrives here."""
        import asyncio
        from anima_mcp.handlers.display_ops import handle_diagnostics
        out = json.loads(asyncio.run(handle_diagnostics(None))[0].text)
        assert "leds" in out
