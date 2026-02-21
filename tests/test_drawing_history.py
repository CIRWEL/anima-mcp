"""Tests for drawing_history table in anima.db."""
import sqlite3
import pytest

from anima_mcp.identity.store import IdentityStore


@pytest.fixture
def store(tmp_path):
    """Create IdentityStore with temp database."""
    db_path = str(tmp_path / "test_anima.db")
    s = IdentityStore(db_path=db_path)
    s.wake("test-creature")
    return s


class TestDrawingHistorySchema:
    """Test that drawing_history table exists and has correct schema."""

    def test_table_exists(self, store):
        conn = store._connect()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='drawing_history'"
        ).fetchall()
        assert len(tables) == 1, "drawing_history table should exist"

    def test_columns(self, store):
        conn = store._connect()
        info = conn.execute("PRAGMA table_info(drawing_history)").fetchall()
        col_names = {row[1] for row in info}
        expected = {
            "id", "timestamp", "E", "I", "S", "V", "C",
            "marks", "phase", "era", "energy",
            "curiosity", "engagement", "fatigue",
            "arc_phase", "gesture_entropy", "switching_rate", "intentionality",
        }
        assert expected.issubset(col_names), f"Missing columns: {expected - col_names}"

    def test_timestamp_index_exists(self, store):
        conn = store._connect()
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='drawing_history'"
        ).fetchall()
        index_names = {row[0] for row in indexes}
        assert "idx_drawing_history_time" in index_names


class TestDrawingHistoryRecording:
    """Test recording and querying drawing_history entries."""

    def test_record_drawing_state(self, store):
        store.record_drawing_state(
            E=0.7, I=0.2, S=0.5, V=-0.1, C=0.47,
            marks=142, phase="building", era="expressive",
            energy=0.6, curiosity=0.5, engagement=0.8, fatigue=0.2,
            arc_phase="developing", gesture_entropy=0.8,
            switching_rate=0.3, intentionality=0.6,
        )
        conn = store._connect()
        rows = conn.execute("SELECT COUNT(*) FROM drawing_history").fetchone()
        assert rows[0] == 1

    def test_get_recent_drawing_history(self, store):
        import time
        # Record 3 entries with slight delays to ensure ordering
        for i in range(3):
            store.record_drawing_state(
                E=0.5 + i * 0.1, I=0.2, S=0.5, V=0.0, C=0.5,
                marks=i * 50, phase="building", era="expressive",
                energy=0.8 - i * 0.2, curiosity=0.5, engagement=0.5,
                fatigue=0.1 * i, arc_phase="developing",
                gesture_entropy=0.5, switching_rate=0.3, intentionality=0.6,
            )
            time.sleep(0.01)  # Ensure distinct timestamps
        history = store.get_recent_drawing_history(limit=2)
        assert len(history) == 2
        # Should be ascending timestamp order (oldest first of the last 2)
        assert history[0]["E"] < history[1]["E"]

    def test_record_returns_none_gracefully(self, store):
        """Recording should never raise -- best-effort like trajectory_events."""
        store.record_drawing_state(
            E=0.0, I=0.0, S=0.0, V=0.0, C=0.0,
            marks=0, phase=None, era=None,
            energy=0.0, curiosity=0.0, engagement=0.0, fatigue=0.0,
            arc_phase=None, gesture_entropy=0.0,
            switching_rate=0.0, intentionality=0.0,
        )
