"""
Tests for memory consolidation — DaySummary round-trip, consolidate(),
get_day_summaries(), detect_long_term_trend(), persistence, and reflect integration.

Run with: pytest tests/test_memory_consolidation.py -v
"""

import json
import pytest
from datetime import datetime, timedelta

from anima_mcp.anima_history import (
    AnimaHistory,
    DaySummary,
)


@pytest.fixture
def history(tmp_path):
    """Create AnimaHistory with temp persistence."""
    return AnimaHistory(
        max_size=5000,
        persistence_path=tmp_path / "anima_history.json",
        auto_save_interval=99999,  # Disable auto-save noise
    )


def _populate(history, n=200, base_warmth=0.5, base_clarity=0.5,
              base_stability=0.5, base_presence=0.5, spread=0.05):
    """Populate history with n observations around given centers."""
    import random
    random.seed(42)
    base_time = datetime(2025, 6, 15, 10, 0, 0)
    for i in range(n):
        history.record(
            warmth=base_warmth + random.uniform(-spread, spread),
            clarity=base_clarity + random.uniform(-spread, spread),
            stability=base_stability + random.uniform(-spread, spread),
            presence=base_presence + random.uniform(-spread, spread),
            timestamp=base_time + timedelta(seconds=i),
        )


def _populate_recent(history, now, n=120, *, start_hours_ago=1.0, value=0.5):
    """Populate deterministic observations that are eligible at ``now``."""
    start = now - timedelta(hours=start_hours_ago)
    for i in range(n):
        history.record(
            warmth=value,
            clarity=value,
            stability=value,
            presence=value,
            timestamp=start + timedelta(seconds=i),
        )


# ==================== DaySummary Round-Trip ====================

class TestDaySummaryRoundTrip:
    """Test DaySummary serialization/deserialization."""

    def test_to_dict_and_back(self):
        """DaySummary survives to_dict → from_dict round-trip."""
        original = DaySummary(
            date="2025-06-15T10:00:00",
            attractor_center=[0.5, 0.6, 0.7, 0.8],
            attractor_variance=[0.001, 0.002, 0.003, 0.004],
            n_observations=200,
            time_span_hours=1.5,
            notable_perturbations=3,
            dimension_trends={"warmth": 0.5, "clarity": 0.6,
                              "stability": 0.7, "presence": 0.8},
        )
        d = original.to_dict()
        restored = DaySummary.from_dict(d)

        assert restored.date == original.date
        assert restored.attractor_center == original.attractor_center
        assert restored.attractor_variance == original.attractor_variance
        assert restored.n_observations == original.n_observations
        assert restored.notable_perturbations == original.notable_perturbations
        assert restored.dimension_trends == original.dimension_trends

    def test_to_dict_keys(self):
        """to_dict has the expected compact keys."""
        summary = DaySummary(
            date="2025-06-15", attractor_center=[0.5]*4,
            attractor_variance=[0.01]*4, n_observations=100,
            time_span_hours=1.0, notable_perturbations=0,
            dimension_trends={"warmth": 0.5},
        )
        d = summary.to_dict()
        assert set(d.keys()) == {"date", "center", "variance", "n_obs",
                                  "hours", "perturbations", "trends"}


# ==================== consolidate() ====================

class TestConsolidate:
    """Test AnimaHistory.consolidate()."""

    def test_returns_none_under_100_obs(self, history):
        """consolidate() returns None with <100 observations."""
        _populate(history, n=50)
        assert history.consolidate() is None

    def test_valid_summary_with_200_obs(self, history):
        """consolidate() returns valid DaySummary with 200 observations."""
        _populate(history, n=200, base_warmth=0.6, base_clarity=0.7)
        summary = history.consolidate()

        assert summary is not None
        assert isinstance(summary, DaySummary)
        assert summary.n_observations == 200
        assert len(summary.attractor_center) == 4
        assert len(summary.attractor_variance) == 4
        # Center should be near the populated values
        assert abs(summary.attractor_center[0] - 0.6) < 0.1  # warmth
        assert abs(summary.attractor_center[1] - 0.7) < 0.1  # clarity
        assert summary.time_span_hours > 0

    def test_saves_to_disk(self, history, tmp_path):
        """consolidate() persists the summary to day_summaries.json."""
        _populate(history, n=200)
        history.consolidate()

        summaries_path = tmp_path / "day_summaries.json"
        assert summaries_path.exists()

        data = json.loads(summaries_path.read_text())
        assert len(data["summaries"]) == 1
        assert data["summaries"][0]["n_obs"] == 200

    def test_max_30_summaries(self, history, tmp_path):
        """Only the last 30 summaries are kept on disk."""
        for i in range(35):
            _populate(history, n=150)
            history.consolidate()

        summaries_path = tmp_path / "day_summaries.json"
        data = json.loads(summaries_path.read_text())
        assert len(data["summaries"]) == 30

    def test_perturbation_count(self, history):
        """Perturbations are counted when observations are far from center."""
        import random
        random.seed(99)
        base_time = datetime(2025, 6, 15, 10, 0, 0)
        # 150 normal observations around 0.5
        for i in range(150):
            history.record(
                warmth=0.5 + random.uniform(-0.02, 0.02),
                clarity=0.5 + random.uniform(-0.02, 0.02),
                stability=0.5 + random.uniform(-0.02, 0.02),
                presence=0.5 + random.uniform(-0.02, 0.02),
                timestamp=base_time + timedelta(seconds=i),
            )
        # Add 10 outlier observations (far from center)
        for i in range(10):
            history.record(
                warmth=0.9,
                clarity=0.1,
                stability=0.9,
                presence=0.1,
                timestamp=base_time + timedelta(seconds=150 + i),
            )

        summary = history.consolidate()
        assert summary is not None
        assert summary.notable_perturbations >= 5  # Outliers should count


# ==================== Server-Owned Daily Writer ====================

class TestDailyConsolidation:
    """Test the durable 24h writer contract used by the MCP server."""

    def test_first_eligible_check_writes_evidence_and_writer_times(
        self, history, tmp_path
    ):
        now = datetime(2026, 8, 23, 12, 0, 0)
        _populate_recent(history, now)

        summary = history.maybe_consolidate_daily(now=now)

        assert summary is not None
        assert summary.n_observations == 120
        assert summary.date == (now - timedelta(hours=1) + timedelta(seconds=119)).isoformat()
        document = json.loads((tmp_path / "day_summaries.json").read_text())
        assert document["written_at"] == now.isoformat()
        assert document["summaries"][0]["date"] == summary.date

    def test_cadence_and_restart_are_idempotent(self, history, tmp_path):
        now = datetime(2026, 8, 23, 12, 0, 0)
        _populate_recent(history, now)
        assert history.maybe_consolidate_daily(now=now) is not None
        assert history.maybe_consolidate_daily(now=now + timedelta(hours=23)) is None

        restarted = AnimaHistory(
            max_size=5000,
            persistence_path=tmp_path / "anima_history.json",
            auto_save_interval=99999,
        )
        _populate_recent(restarted, now + timedelta(hours=23), value=0.8)
        assert restarted.maybe_consolidate_daily(
            now=now + timedelta(hours=23)
        ) is None
        document = json.loads((tmp_path / "day_summaries.json").read_text())
        assert len(document["summaries"]) == 1

    def test_multi_day_gap_adds_one_real_summary_without_backfill(
        self, history, tmp_path
    ):
        first = datetime(2026, 8, 20, 12, 0, 0)
        _populate_recent(history, first)
        assert history.maybe_consolidate_daily(now=first) is not None

        history.clear()
        current = first + timedelta(days=3)
        _populate_recent(history, current, value=0.8)
        summary = history.maybe_consolidate_daily(now=current)

        assert summary is not None
        assert summary.attractor_center == [0.8, 0.8, 0.8, 0.8]
        document = json.loads((tmp_path / "day_summaries.json").read_text())
        assert len(document["summaries"]) == 2

    def test_fresh_writer_stamp_cannot_defer_stale_evidence(
        self, history, tmp_path
    ):
        now = datetime(2026, 8, 23, 12, 0, 0)
        stale = now - timedelta(days=10)
        path = tmp_path / "day_summaries.json"
        path.write_text(json.dumps({
            "summaries": [{
                "date": stale.isoformat(),
                "center": [0.2] * 4,
                "variance": [0.0] * 4,
                "n_obs": 100,
                "hours": 1.0,
                "perturbations": 0,
                "trends": {},
            }],
            "written_at": now.isoformat(),
            "version": "1.0",
        }))
        _populate_recent(history, now, value=0.8)

        summary = history.maybe_consolidate_daily(now=now)

        assert summary is not None
        assert summary.attractor_center == [0.8, 0.8, 0.8, 0.8]
        document = json.loads(path.read_text())
        assert len(document["summaries"]) == 2
        assert document["summaries"][-1]["date"] == summary.date

    def test_under_100_defers_then_rechecks(self, history, tmp_path):
        now = datetime(2026, 8, 23, 12, 0, 0)
        _populate_recent(history, now, n=99)
        assert history.maybe_consolidate_daily(now=now) is None
        document = json.loads((tmp_path / "day_summaries.json").read_text())
        assert document == {
            "summaries": [],
            "writer_started_at": now.isoformat(),
            "version": "1.0",
        }

        history.record(0.5, 0.5, 0.5, 0.5, timestamp=now)
        assert history.maybe_consolidate_daily(now=now) is not None

    def test_old_loaded_observations_cannot_be_relabelled_current(
        self, history, tmp_path
    ):
        now = datetime(2026, 8, 23, 12, 0, 0)
        _populate_recent(history, now - timedelta(days=2), n=200)
        history.record(0.9, 0.9, 0.9, 0.9, timestamp=now)

        assert history.maybe_consolidate_daily(now=now) is None
        document = json.loads((tmp_path / "day_summaries.json").read_text())
        assert document["summaries"] == []
        assert document["writer_started_at"] == now.isoformat()

    def test_empty_legacy_document_is_upgraded_with_bounded_marker(
        self, history, tmp_path
    ):
        now = datetime(2026, 8, 23, 12, 0, 0)
        path = tmp_path / "day_summaries.json"
        path.write_text(json.dumps({"summaries": [], "version": "1.0"}))

        assert history.maybe_consolidate_daily(now=now) is None

        document = json.loads(path.read_text())
        assert document["writer_started_at"] == now.isoformat()
        assert history.day_summary_health(now=now)["status"] == "warming_up"

    def test_malformed_existing_file_is_preserved_and_reported(
        self, history, tmp_path
    ):
        now = datetime(2026, 8, 23, 12, 0, 0)
        _populate_recent(history, now)
        path = tmp_path / "day_summaries.json"
        damaged = "{not valid json"
        path.write_text(damaged)

        with pytest.raises(json.JSONDecodeError):
            history.maybe_consolidate_daily(now=now)

        assert path.read_text() == damaged
        health = history.day_summary_health(now=now)
        assert health["ok"] is False
        assert health["status"] == "error"
        assert "JSONDecodeError" in health["writer"]["last_error"]

    def test_atomic_failure_propagates_and_retries_without_false_success(
        self, history, tmp_path, monkeypatch
    ):
        from anima_mcp import anima_history as module

        now = datetime(2026, 8, 23, 12, 0, 0)
        _populate_recent(history, now)
        real_write = module.atomic_json_write
        calls = 0

        def fail_write(*args, **kwargs):
            nonlocal calls
            calls += 1
            raise OSError("disk full")

        monkeypatch.setattr(module, "atomic_json_write", fail_write)
        with pytest.raises(OSError, match="disk full"):
            history.maybe_consolidate_daily(now=now)
        assert calls == 1
        assert not (tmp_path / "day_summaries.json").exists()
        assert history.day_summary_health(now=now)["status"] == "error"

        # The live callback runs every ~10s, but failed writes retry on a
        # bounded backoff instead of hammering the SD card.
        assert history.maybe_consolidate_daily(now=now + timedelta(minutes=4)) is None
        assert calls == 1

        monkeypatch.setattr(module, "atomic_json_write", real_write)
        summary = history.maybe_consolidate_daily(now=now + timedelta(minutes=5))
        assert summary is not None
        assert history.day_summary_health(now=now + timedelta(minutes=5))["ok"] is True

    def test_post_replace_failure_retries_without_duplicate_summary(
        self, history, tmp_path, monkeypatch
    ):
        """A directory-fsync error leaves the rename outcome uncertain."""
        from anima_mcp import anima_history as module

        now = datetime(2026, 8, 23, 12, 0, 0)
        _populate_recent(history, now)
        real_write = module.atomic_json_write

        def write_then_fail(*args, **kwargs):
            real_write(*args, **kwargs)
            raise OSError("directory fsync failed after replace")

        monkeypatch.setattr(module, "atomic_json_write", write_then_fail)
        with pytest.raises(OSError, match="directory fsync failed"):
            history.maybe_consolidate_daily(now=now)

        path = tmp_path / "day_summaries.json"
        assert len(json.loads(path.read_text())["summaries"]) == 1
        assert history.day_summary_health(now=now)["status"] == "error"

        monkeypatch.setattr(module, "atomic_json_write", real_write)
        summary = history.maybe_consolidate_daily(now=now + timedelta(minutes=5))

        assert summary is not None
        document = json.loads(path.read_text())
        assert len(document["summaries"]) == 1
        assert document["summaries"][0] == summary.to_dict()
        assert document["written_at"] == (now + timedelta(minutes=5)).isoformat()
        assert history.day_summary_health(
            now=now + timedelta(minutes=5)
        )["ok"] is True

    def test_separate_process_role_instances_do_not_share_a_deque(self, tmp_path):
        path = tmp_path / "anima_history.json"
        broker_history = AnimaHistory(
            max_size=5000, persistence_path=path, auto_save_interval=99999
        )
        server_history = AnimaHistory(
            max_size=5000, persistence_path=path, auto_save_interval=99999
        )
        now = datetime(2026, 8, 23, 12, 0, 0)
        _populate_recent(server_history, now)

        assert len(broker_history) == 0
        assert broker_history.maybe_consolidate_daily(now=now) is None
        assert server_history.maybe_consolidate_daily(now=now) is not None


class TestDaySummaryHealth:
    """Freshness considers both commit liveness and source evidence."""

    def test_bootstrap_is_bounded_and_source_aware(self, history):
        now = datetime(2026, 8, 23, 12, 0, 0)
        assert history.day_summary_health(now=now)["status"] == "missing"

        assert history.maybe_consolidate_daily(now=now) is None
        health = history.day_summary_health(now=now)
        assert health["ok"] is True
        assert health["status"] == "warming_up"
        assert health["bootstrap"]["started_at"] == now.isoformat()

        _populate_recent(history, now)
        health = history.day_summary_health(now=now)
        assert health["ok"] is False
        assert health["status"] == "missing"

    def test_bootstrap_marker_expires_even_without_eligible_source(self, history):
        started = datetime(2026, 8, 23, 12, 0, 0)
        assert history.maybe_consolidate_daily(now=started) is None

        health = history.day_summary_health(
            now=started + timedelta(minutes=31)
        )

        assert health["ok"] is False
        assert health["status"] == "bootstrap_timeout"
        assert health["bootstrap"]["age_seconds"] == 31 * 60

    def test_fresh_summary_exposes_both_freshness_axes(self, history):
        now = datetime(2026, 8, 23, 12, 0, 0)
        _populate_recent(history, now)
        history.maybe_consolidate_daily(now=now)

        health = history.day_summary_health(now=now)

        assert health["ok"] is True
        assert health["status"] == "ok"
        assert health["writer"]["written_at"] == now.isoformat()
        assert health["writer"]["last_success_at"] == now.isoformat()
        assert health["evidence"]["age_seconds"] > 0

    @pytest.mark.parametrize("stale_axis", ["writer", "evidence"])
    def test_either_stale_axis_degrades(self, history, tmp_path, stale_axis):
        now = datetime(2026, 8, 23, 12, 0, 0)
        old = now - timedelta(hours=37)
        evidence_at = old if stale_axis == "evidence" else now
        written_at = old if stale_axis == "writer" else now
        path = tmp_path / "day_summaries.json"
        path.write_text(json.dumps({
            "summaries": [{
                "date": evidence_at.isoformat(),
                "center": [0.5] * 4,
                "variance": [0.0] * 4,
                "n_obs": 100,
                "hours": 1.0,
                "perturbations": 0,
                "trends": {},
            }],
            "written_at": written_at.isoformat(),
            "version": "1.0",
        }))

        health = history.day_summary_health(now=now)

        assert health["ok"] is False
        assert health["status"] == "stale"

    def test_future_and_malformed_timestamps_degrade(self, history, tmp_path):
        now = datetime(2026, 8, 23, 12, 0, 0)
        path = tmp_path / "day_summaries.json"
        row = {
            "date": (now + timedelta(minutes=6)).isoformat(),
            "center": [0.5] * 4,
            "variance": [0.0] * 4,
            "n_obs": 100,
            "hours": 1.0,
            "perturbations": 0,
            "trends": {},
        }
        path.write_text(json.dumps({
            "summaries": [row], "written_at": now.isoformat(), "version": "1.0"
        }))
        assert history.day_summary_health(now=now)["status"] == "future"

        row["date"] = "not-a-date"
        path.write_text(json.dumps({
            "summaries": [row], "written_at": now.isoformat(), "version": "1.0"
        }))
        assert history.day_summary_health(now=now)["status"] == "malformed"


# ==================== get_day_summaries() ====================

class TestGetDaySummaries:
    """Test loading persisted day summaries."""

    def test_empty_returns_empty(self, history):
        """No summaries file → empty list."""
        assert history.get_day_summaries() == []

    def test_returns_stored_summaries(self, history):
        """Summaries round-trip through consolidate → get_day_summaries."""
        _populate(history, n=200)
        history.consolidate()

        summaries = history.get_day_summaries()
        assert len(summaries) == 1
        assert summaries[0].n_observations == 200

    def test_limit_parameter(self, history):
        """get_day_summaries respects the limit parameter."""
        for i in range(5):
            _populate(history, n=150)
            history.consolidate()

        assert len(history.get_day_summaries(limit=3)) == 3

    def test_newest_first_order(self, history):
        """get_day_summaries returns newest first."""
        for i in range(3):
            _populate(history, n=150, base_warmth=0.3 + i * 0.1)
            history.consolidate()

        summaries = history.get_day_summaries()
        # The last consolidation had base_warmth=0.5, first had 0.3
        assert summaries[0].attractor_center[0] > summaries[-1].attractor_center[0]


# ==================== detect_long_term_trend() ====================

class TestDetectLongTermTrend:
    """Test trend detection across day summaries."""

    def _write_summaries(self, history, values_warmth):
        """Directly write summaries with specific warmth values."""
        summaries_path = history._get_summaries_path()
        summaries = []
        for i, w in enumerate(values_warmth):
            summaries.append({
                "date": (datetime.now() - timedelta(days=6 - i)).strftime("%Y-%m-%dT12:00:00"),
                "center": [w, 0.5, 0.5, 0.5],
                "variance": [0.001]*4,
                "n_obs": 200,
                "hours": 1.0,
                "perturbations": 0,
                "trends": {"warmth": w, "clarity": 0.5,
                           "stability": 0.5, "presence": 0.5},
            })
        summaries_path.parent.mkdir(parents=True, exist_ok=True)
        summaries_path.write_text(json.dumps({"summaries": summaries}))

    def test_none_with_fewer_than_3_summaries(self, history):
        """Returns None with <3 day summaries."""
        self._write_summaries(history, [0.5, 0.6])
        assert history.detect_long_term_trend("warmth") is None

    def test_detects_upward_trend(self, history):
        """Detects increasing trend in warmth."""
        self._write_summaries(history, [0.3, 0.4, 0.5, 0.6, 0.7])
        trend = history.detect_long_term_trend("warmth")

        assert trend is not None
        assert trend["direction"] == "increasing"
        assert trend["trend"] > 0
        assert trend["dimension"] == "warmth"
        assert trend["n_summaries"] == 5

    def test_detects_downward_trend(self, history):
        """Detects decreasing trend in clarity."""
        self._write_summaries(history, [0.7, 0.6, 0.5, 0.4, 0.3])
        # Write clarity values instead — use full summaries
        summaries_path = history._get_summaries_path()
        summaries = []
        for i, c in enumerate([0.7, 0.6, 0.5, 0.4, 0.3]):
            summaries.append({
                "date": (datetime.now() - timedelta(days=6 - i)).strftime("%Y-%m-%dT12:00:00"),
                "center": [0.5, c, 0.5, 0.5],
                "variance": [0.001]*4,
                "n_obs": 200,
                "hours": 1.0,
                "perturbations": 0,
                "trends": {"warmth": 0.5, "clarity": c,
                           "stability": 0.5, "presence": 0.5},
            })
        summaries_path.write_text(json.dumps({"summaries": summaries}))

        trend = history.detect_long_term_trend("clarity")
        assert trend is not None
        assert trend["direction"] == "decreasing"
        assert trend["trend"] < 0

    def test_stable_trend(self, history):
        """Near-constant values → 'stable' direction."""
        self._write_summaries(history, [0.50, 0.50, 0.50, 0.50])
        trend = history.detect_long_term_trend("warmth")
        assert trend is not None
        assert trend["direction"] == "stable"

    def test_window_days_limits_summaries(self, history):
        """window_days parameter limits how many summaries are used."""
        self._write_summaries(history, [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])
        trend = history.detect_long_term_trend("warmth", window_days=3)
        assert trend is not None
        assert trend["n_summaries"] == 3


# ==================== Persistence Round-Trip ====================

class TestPersistence:
    """Test day summaries survive across AnimaHistory instances."""

    def test_summaries_persist_across_instances(self, tmp_path):
        """Day summaries written by one instance readable by another."""
        h1 = AnimaHistory(
            persistence_path=tmp_path / "anima_history.json",
            auto_save_interval=99999,
        )
        _populate(h1, n=200)
        h1.consolidate()

        h2 = AnimaHistory(
            persistence_path=tmp_path / "anima_history.json",
            auto_save_interval=99999,
        )
        summaries = h2.get_day_summaries()
        assert len(summaries) == 1
        assert summaries[0].n_observations == 200


# ==================== Reflect Integration ====================

class TestReflectIntegration:
    """Test that reflect() uses long-term trends."""

    def test_reflect_generates_trend_insight(self, tmp_path):
        """reflect() generates insight from long-term trend."""
        import sqlite3
        from anima_mcp.self_reflection import SelfReflectionSystem
        from anima_mcp.anima_history import get_anima_history, reset_anima_history

        # Reset singleton and create history with temp path
        reset_anima_history()

        db_path = str(tmp_path / "reflection.db")
        # Create state_history table so analyze_patterns() doesn't crash
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS state_history (
                timestamp TEXT, warmth REAL, clarity REAL,
                stability REAL, presence REAL, sensors TEXT
            )
        """)
        conn.commit()
        conn.close()

        reflection = SelfReflectionSystem(db_path=db_path)

        # Create a history with summaries showing upward warmth trend
        history = get_anima_history()
        summaries_path = history._get_summaries_path()
        summaries_path.parent.mkdir(parents=True, exist_ok=True)

        summaries = []
        for i, w in enumerate([0.3, 0.4, 0.5, 0.6, 0.7]):
            summaries.append({
                "date": (datetime.now() - timedelta(days=6 - i)).strftime("%Y-%m-%dT12:00:00"),
                "center": [w, 0.5, 0.5, 0.5],
                "variance": [0.001]*4,
                "n_obs": 200,
                "hours": 1.0,
                "perturbations": 0,
                "trends": {"warmth": w, "clarity": 0.5,
                           "stability": 0.5, "presence": 0.5},
            })
        summaries_path.write_text(json.dumps({"summaries": summaries}))

        # Run reflect — it should pick up the trend
        reflection.reflect()

        # Check that trend insight was created
        trend_insights = [
            i for i in reflection._insights.values()
            if "trend" in i.id
        ]
        assert len(trend_insights) >= 1
        assert any("warmth" in i.description and "increasing" in i.description
                    for i in trend_insights)

        # Cleanup singleton
        reset_anima_history()
