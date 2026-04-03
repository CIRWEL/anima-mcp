"""Tests for system_metrics persistence in IdentityStore."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from anima_mcp.identity.store import IdentityStore


class FakeReadings:
    """Minimal SensorReadings stand-in for testing."""
    def __init__(self, **kwargs):
        defaults = {
            "cpu_temp_c": 55.0,
            "cpu_percent": 23.5,
            "memory_percent": 41.2,
            "disk_percent": 68.0,
            "ambient_temp_c": 22.1,
            "humidity_pct": 35.0,
            "light_lux": 150.0,
            "pressure_hpa": 1013.25,
            "led_brightness": 0.8,
            "throttled_now": False,
            "undervoltage_now": False,
            "freq_capped_now": False,
        }
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(self, k, v)


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "test_anima.db"
    s = IdentityStore(db_path=str(db_path))
    s._connect()  # Force schema init
    return s


class TestSystemMetricsTable:

    def test_table_exists(self, store):
        conn = store._connect()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='system_metrics'"
        ).fetchall()
        assert len(tables) == 1

    def test_table_creation_idempotent(self, store):
        """Calling _init_schema again should not fail."""
        store._init_schema()
        conn = store._connect()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='system_metrics'"
        ).fetchall()
        assert len(tables) == 1


class TestRecordSystemMetrics:

    def test_record_inserts_row(self, store):
        readings = FakeReadings()
        store.record_system_metrics(readings)

        conn = store._connect()
        rows = conn.execute("SELECT * FROM system_metrics").fetchall()
        assert len(rows) == 1

    def test_record_correct_values(self, store):
        readings = FakeReadings(cpu_temp_c=62.5, memory_percent=80.0)
        store.record_system_metrics(readings)

        conn = store._connect()
        row = conn.execute("SELECT cpu_temp_c, memory_percent FROM system_metrics").fetchone()
        assert row["cpu_temp_c"] == 62.5
        assert row["memory_percent"] == 80.0

    def test_record_bool_as_int(self, store):
        readings = FakeReadings(throttled_now=True, undervoltage_now=False)
        store.record_system_metrics(readings)

        conn = store._connect()
        row = conn.execute("SELECT throttled_now, undervoltage_now FROM system_metrics").fetchone()
        assert row["throttled_now"] == 1
        assert row["undervoltage_now"] == 0

    def test_record_none_values(self, store):
        readings = FakeReadings(cpu_temp_c=None, pressure_hpa=None, throttled_now=None)
        store.record_system_metrics(readings)

        conn = store._connect()
        row = conn.execute("SELECT cpu_temp_c, pressure_hpa, throttled_now FROM system_metrics").fetchone()
        assert row["cpu_temp_c"] is None
        assert row["pressure_hpa"] is None
        assert row["throttled_now"] is None

    def test_record_from_dict(self, store):
        d = {"cpu_temp_c": 50.0, "cpu_percent": 10.0}
        store.record_system_metrics(d)

        conn = store._connect()
        row = conn.execute("SELECT cpu_temp_c, cpu_percent FROM system_metrics").fetchone()
        assert row["cpu_temp_c"] == 50.0
        assert row["cpu_percent"] == 10.0

    def test_multiple_records(self, store):
        for i in range(5):
            store.record_system_metrics(FakeReadings(cpu_temp_c=50.0 + i))

        conn = store._connect()
        count = conn.execute("SELECT COUNT(*) FROM system_metrics").fetchone()[0]
        assert count == 5


class TestGetSystemMetrics:

    def test_returns_recent_rows(self, store):
        for i in range(3):
            store.record_system_metrics(FakeReadings(cpu_temp_c=50.0 + i))

        rows = store.get_system_metrics(hours=1)
        assert len(rows) == 3
        # Should be oldest first
        assert rows[0]["cpu_temp_c"] == 50.0
        assert rows[2]["cpu_temp_c"] == 52.0

    def test_respects_limit(self, store):
        for i in range(10):
            store.record_system_metrics(FakeReadings(cpu_temp_c=50.0 + i))

        rows = store.get_system_metrics(hours=1, limit=3)
        assert len(rows) == 3

    def test_excludes_old_rows(self, store):
        # Insert a row with old timestamp
        conn = store._connect()
        old_time = (datetime.now() - timedelta(hours=48)).isoformat()
        conn.execute(
            "INSERT INTO system_metrics (timestamp, cpu_temp_c, epoch) VALUES (?, ?, 1)",
            (old_time, 99.0)
        )
        conn.commit()

        # Insert a recent row
        store.record_system_metrics(FakeReadings(cpu_temp_c=55.0))

        rows = store.get_system_metrics(hours=24)
        assert len(rows) == 1
        assert rows[0]["cpu_temp_c"] == 55.0

    def test_empty_when_no_data(self, store):
        rows = store.get_system_metrics(hours=1)
        assert rows == []


class TestPruneSystemMetrics:

    def test_prune_deletes_old_rows(self, store):
        conn = store._connect()
        # Insert old row
        old_time = (datetime.now() - timedelta(hours=48)).isoformat()
        conn.execute(
            "INSERT INTO system_metrics (timestamp, cpu_temp_c, epoch) VALUES (?, ?, 1)",
            (old_time, 99.0)
        )
        # Insert recent row
        recent_time = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO system_metrics (timestamp, cpu_temp_c, epoch) VALUES (?, ?, 1)",
            (recent_time, 55.0)
        )
        conn.commit()

        deleted = store.prune_system_metrics(max_age_hours=24.0)
        assert deleted == 1

        remaining = conn.execute("SELECT COUNT(*) FROM system_metrics").fetchone()[0]
        assert remaining == 1

    def test_prune_keeps_recent_rows(self, store):
        for i in range(5):
            store.record_system_metrics(FakeReadings(cpu_temp_c=50.0 + i))

        deleted = store.prune_system_metrics(max_age_hours=24.0)
        assert deleted == 0

    def test_prune_returns_zero_when_empty(self, store):
        deleted = store.prune_system_metrics(max_age_hours=24.0)
        assert deleted == 0
