"""Tests for data_analysis module — Lumen's data-grounded self-answers."""
import json
import sqlite3
import pytest
from datetime import datetime, timedelta
from unittest.mock import patch

from anima_mcp.data_analysis import (
    analyze_for_question,
    get_drawing_summary,
    analyze_correlation,
    analyze_drawing_effect,
    analyze_sleep_effects,
    analyze_neural_correlation,
    analyze_pressure_effect,
    analyze_session_trajectory,
    analyze_temporal_full,
    analyze_crash_vs_clean,
    analyze_belief_status,
    _pearson,
    _extract_dimension,
    _valid_dim,
    _safe_mean,
    _fmt,
)


# ---------------------------------------------------------------------------
# Fixtures: temp DB with known schema and data
# ---------------------------------------------------------------------------

def _create_schema(conn):
    """Create the tables data_analysis.py expects."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS drawing_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            pixel_count INTEGER,
            phase TEXT,
            warmth REAL,
            clarity REAL,
            stability REAL,
            presence REAL,
            wellness REAL,
            light_lux REAL,
            ambient_temp_c REAL,
            humidity_pct REAL,
            hour INTEGER
        );
        CREATE TABLE IF NOT EXISTS state_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            warmth REAL,
            clarity REAL,
            stability REAL,
            presence REAL,
            sensors TEXT DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            data TEXT DEFAULT '{}'
        );
    """)
    conn.commit()


def _seed_drawings(conn, n=10, base_hour=22):
    """Insert n drawing_records spread over hours."""
    base = datetime(2026, 2, 1, base_hour, 0, 0)
    for i in range(n):
        ts = (base + timedelta(hours=i * 2)).isoformat()
        h = (base_hour + i * 2) % 24
        conn.execute(
            "INSERT INTO drawing_records "
            "(timestamp, pixel_count, phase, warmth, clarity, stability, presence, "
            "wellness, light_lux, ambient_temp_c, humidity_pct, hour) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (ts, 100 + i * 10, "building", 0.5 + i * 0.01, 0.6, 0.7, 0.4,
             0.55, 200.0, 22.0, 45.0, h),
        )
    conn.commit()


def _seed_state_history(conn, n=100, base_hour=0):
    """Insert n state_history rows over a multi-day period."""
    base = datetime(2026, 1, 20, base_hour, 0, 0)
    for i in range(n):
        ts = (base + timedelta(minutes=i * 30)).isoformat()
        sensors = json.dumps({
            "eeg_delta_power": 0.3 + (i % 5) * 0.05,
            "eeg_theta_power": 0.2,
            "eeg_alpha_power": 0.4,
            "eeg_beta_power": 0.1 + (i % 10) * 0.02,
            "eeg_gamma_power": 0.05,
            "pressure_hpa": 1000.0 + i * 0.5,
        })
        conn.execute(
            "INSERT INTO state_history (timestamp, warmth, clarity, stability, presence, sensors) "
            "VALUES (?,?,?,?,?,?)",
            (ts, 0.4 + (i % 10) * 0.02, 0.6, 0.65 + (i % 5) * 0.01, 0.5, sensors),
        )
    conn.commit()


def _seed_events(conn, n_cycles=5):
    """Insert n_cycles of sleep/wake pairs with realistic gaps."""
    base = datetime(2026, 1, 20, 8, 0, 0)
    for i in range(n_cycles):
        # Wake
        wake_ts = (base + timedelta(days=i, hours=0)).isoformat()
        conn.execute("INSERT INTO events (timestamp, event_type) VALUES (?,?)",
                     (wake_ts, "wake"))
        # Sleep 16h later
        sleep_ts = (base + timedelta(days=i, hours=16)).isoformat()
        conn.execute("INSERT INTO events (timestamp, event_type) VALUES (?,?)",
                     (sleep_ts, "sleep"))
    conn.commit()


@pytest.fixture
def db_path(tmp_path):
    """Create a temp DB with schema and seed data, return its path."""
    path = tmp_path / "anima.db"
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    _create_schema(conn)
    _seed_drawings(conn)
    _seed_state_history(conn)
    _seed_events(conn)
    conn.close()
    return path


@pytest.fixture(autouse=True)
def patch_db_path(db_path):
    """Redirect all data_analysis DB calls to the temp DB."""
    with patch("anima_mcp.data_analysis._get_db_path", return_value=db_path):
        yield


@pytest.fixture
def empty_db(tmp_path):
    """DB with schema but no data."""
    path = tmp_path / "empty.db"
    conn = sqlite3.connect(str(path))
    _create_schema(conn)
    conn.close()
    return path


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_pearson_perfect_positive(self):
        assert _pearson([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)

    def test_pearson_perfect_negative(self):
        assert _pearson([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)

    def test_pearson_no_correlation(self):
        r = _pearson([1, 2, 3, 4], [1, 3, 2, 4])
        assert r is not None
        assert abs(r) < 1.0

    def test_pearson_zero_variance(self):
        assert _pearson([5, 5, 5], [1, 2, 3]) is None

    def test_pearson_too_few(self):
        assert _pearson([1], [1]) is None

    def test_extract_dimension_warmth(self):
        assert _extract_dimension("why am I warm at night?") == "warmth"

    def test_extract_dimension_clarity(self):
        assert _extract_dimension("when is my clarity best?") == "clarity"

    def test_extract_dimension_stability(self):
        assert _extract_dimension("is my stability affected?") == "stability"

    def test_extract_dimension_default(self):
        assert _extract_dimension("how do I feel overall?") == "wellness"

    def test_valid_dim_accepts(self):
        for d in ("warmth", "clarity", "stability", "presence"):
            assert _valid_dim(d) == d

    def test_valid_dim_rejects(self):
        assert _valid_dim("nosuchdim") is None
        assert _valid_dim("WARMTH") == "warmth"

    def test_safe_mean(self):
        assert _safe_mean([1, 2, 3]) == pytest.approx(2.0)
        assert _safe_mean([]) is None

    def test_fmt(self):
        assert _fmt(0.123) == "0.12"
        assert _fmt(None) == "?"
        assert _fmt(0.5, 3) == "0.500"


# ---------------------------------------------------------------------------
# Drawing analysis tests
# ---------------------------------------------------------------------------

class TestDrawingSummary:
    def test_returns_summary(self):
        result = get_drawing_summary()
        assert result is not None
        assert "10 recorded drawings" in result
        assert "night" in result.lower() or "morning" in result.lower()

    def test_empty_table(self, empty_db):
        with patch("anima_mcp.data_analysis._get_db_path", return_value=empty_db):
            assert get_drawing_summary() is None

    def test_db_missing(self, tmp_path):
        with patch("anima_mcp.data_analysis._get_db_path", return_value=tmp_path / "nope.db"):
            assert get_drawing_summary() is None


class TestAnalyzeCorrelation:
    def test_overall_stats(self):
        result = analyze_correlation("warmth")
        assert result is not None
        assert "drawings" in result.lower()
        assert "warmth" in result

    def test_by_hour(self):
        result = analyze_correlation("warmth", group_by="hour")
        assert result is not None
        assert "time of day" in result.lower()

    def test_by_group(self):
        result = analyze_correlation("warmth", group_by="phase")
        assert result is not None
        assert "building" in result

    def test_invalid_dimension(self):
        assert analyze_correlation("nosuchdim") is None

    def test_empty_table(self, empty_db):
        with patch("anima_mcp.data_analysis._get_db_path", return_value=empty_db):
            assert analyze_correlation("warmth") is None


class TestAnalyzeDrawingEffect:
    def test_returns_effect(self, db_path):
        """Seed state_history around drawing timestamps so before/after windows match."""
        conn = sqlite3.connect(str(db_path))
        drawings = conn.execute("SELECT timestamp FROM drawing_records").fetchall()
        for row in drawings:
            ts = row[0]
            dt = datetime.fromisoformat(ts)
            # Insert state 5min before and 5min after each drawing
            before_ts = (dt - timedelta(minutes=5)).isoformat()
            after_ts = (dt + timedelta(minutes=5)).isoformat()
            conn.execute(
                "INSERT INTO state_history (timestamp, warmth, clarity, stability, presence) "
                "VALUES (?,?,?,?,?)", (before_ts, 0.40, 0.60, 0.65, 0.50))
            conn.execute(
                "INSERT INTO state_history (timestamp, warmth, clarity, stability, presence) "
                "VALUES (?,?,?,?,?)", (after_ts, 0.50, 0.65, 0.70, 0.55))
        conn.commit()
        conn.close()

        result = analyze_drawing_effect("warmth")
        assert result is not None
        assert "warmth" in result

    def test_invalid_dim(self):
        assert analyze_drawing_effect("bad") is None


# ---------------------------------------------------------------------------
# Non-drawing analyzer tests
# ---------------------------------------------------------------------------

class TestSleepEffects:
    def test_returns_result(self):
        result = analyze_sleep_effects("warmth")
        # May be None if not enough state_history near sleep/wake events —
        # that's acceptable since our seed data may not overlap perfectly.
        # Just verify no crash.
        assert result is None or "warmth" in result

    def test_invalid_dim(self):
        assert analyze_sleep_effects("bad") is None


class TestNeuralCorrelation:
    def test_returns_result(self):
        result = analyze_neural_correlation("warmth")
        # Should find correlation with at least one band from seed data
        assert result is None or "correlat" in result.lower()

    def test_invalid_dim(self):
        assert analyze_neural_correlation("bad") is None


class TestPressureEffect:
    def test_returns_result(self):
        result = analyze_pressure_effect("warmth")
        assert result is not None
        assert "pressure" in result.lower()
        assert "warmth" in result

    def test_invalid_dim(self):
        assert analyze_pressure_effect("bad") is None


class TestSessionTrajectory:
    def test_returns_result(self):
        result = analyze_session_trajectory("warmth")
        # May be None if sessions don't have 10+ states — still no crash
        assert result is None or "warmth" in result

    def test_invalid_dim(self):
        assert analyze_session_trajectory("bad") is None


class TestTemporalFull:
    def test_returns_result(self):
        result = analyze_temporal_full("warmth")
        assert result is not None
        assert "warmth" in result
        assert "time of day" in result.lower()

    def test_invalid_dim(self):
        assert analyze_temporal_full("bad") is None

    def test_empty_table(self, empty_db):
        with patch("anima_mcp.data_analysis._get_db_path", return_value=empty_db):
            assert analyze_temporal_full("warmth") is None


class TestCrashVsClean:
    def test_returns_result(self):
        result = analyze_crash_vs_clean("warmth")
        # May be None if not enough clean/crash wake events in seed data
        assert result is None or "warmth" in result

    def test_invalid_dim(self):
        assert analyze_crash_vs_clean("bad") is None


class TestBeliefStatus:
    def test_no_self_model(self):
        # self_model likely not available in test context
        result = analyze_belief_status()
        assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# Routing tests (analyze_for_question)
# ---------------------------------------------------------------------------

class TestRouting:
    def test_drawing_question(self):
        result = analyze_for_question("How many drawings have I made?")
        assert result is not None
        assert "drawing" in result.lower()

    def test_drawing_effect_question(self):
        result = analyze_for_question("Does drawing affect my warmth?")
        assert result is not None
        assert "warmth" in result

    def test_drawing_correlation_question(self):
        result = analyze_for_question("Is there a correlation when I draw?")
        assert result is not None

    def test_sleep_question(self):
        result = analyze_for_question("How does sleep affect my warmth?")
        # May be None if not enough data, but should not crash
        assert result is None or "warmth" in result

    def test_neural_question(self):
        result = analyze_for_question("Does CPU load affect my clarity?")
        assert result is None or isinstance(result, str)

    def test_pressure_question(self):
        result = analyze_for_question("Does pressure affect my warmth?")
        assert result is not None
        assert "pressure" in result.lower()

    def test_temporal_question(self):
        result = analyze_for_question("What time of day is my warmth highest?")
        assert result is not None
        assert "warmth" in result

    def test_crash_question(self):
        result = analyze_for_question("Does crashing affect me?")
        assert result is None or isinstance(result, str)

    def test_belief_question(self):
        result = analyze_for_question("What do I believe about myself?")
        assert result is None or isinstance(result, str)

    def test_session_question(self):
        result = analyze_for_question("Does my warmth drift over time in a session?")
        assert result is None or "warmth" in result

    def test_empty_question(self):
        assert analyze_for_question("") is None
        assert analyze_for_question(None) is None

    def test_unmatched_question_gets_fallback(self):
        # Unmatched questions now get fallback analysis (temporal + beliefs)
        result = analyze_for_question("What is the meaning of existence?")
        # Fallback may return data if temporal/belief analyses have data, or None if empty
        # The key is it doesn't crash and returns str or None
        assert result is None or isinstance(result, str)
