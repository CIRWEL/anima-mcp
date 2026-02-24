"""Tests for learning.py — adaptive calibration from sensor history."""

import json
import sqlite3
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from anima_mcp.learning import AdaptiveLearner, get_learner
from anima_mcp.config import NervousSystemCalibration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_schema(db_path: Path):
    """Create the three tables AdaptiveLearner reads."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS state_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            sensors TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT,
            timestamp TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS identity (
            id INTEGER PRIMARY KEY,
            last_heartbeat_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def _seed_rows(db_path: Path, n: int, temp=22.0, pressure=827.0, humidity=40.0, days_ago=0):
    """Insert n sensor rows spread over recent hours."""
    conn = sqlite3.connect(str(db_path))
    now = datetime.now()
    for i in range(n):
        ts = (now - timedelta(days=days_ago, hours=i)).isoformat()
        sensors = json.dumps({
            "ambient_temp_c": temp + (i % 3) * 0.5,
            "pressure_hpa": pressure + (i % 5) * 0.2,
            "humidity_pct": humidity + (i % 4) * 0.3,
        })
        conn.execute(
            "INSERT INTO state_history (timestamp, sensors) VALUES (?, ?)",
            (ts, sensors),
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def learning_db(tmp_path):
    db_path = tmp_path / "anima.db"
    _create_schema(db_path)
    return db_path


@pytest.fixture
def learner(learning_db):
    return AdaptiveLearner(db_path=str(learning_db))


# ---------------------------------------------------------------------------
# should_adapt — pure logic, no DB
# ---------------------------------------------------------------------------

class TestShouldAdapt:
    def test_identical_calibrations_returns_false(self):
        learner = AdaptiveLearner(db_path="/nonexistent")
        cal = NervousSystemCalibration()
        assert learner.should_adapt(cal, cal) is False

    def test_large_pressure_shift_returns_true(self):
        learner = AdaptiveLearner(db_path="/nonexistent")
        current = NervousSystemCalibration()
        learned = NervousSystemCalibration.from_dict(current.to_dict())
        learned.pressure_ideal = current.pressure_ideal + 10.0  # > 5 hPa threshold
        assert learner.should_adapt(current, learned) is True

    def test_small_pressure_shift_returns_false(self):
        learner = AdaptiveLearner(db_path="/nonexistent")
        current = NervousSystemCalibration()
        learned = NervousSystemCalibration.from_dict(current.to_dict())
        learned.pressure_ideal = current.pressure_ideal + 2.0  # < 5 hPa
        assert learner.should_adapt(current, learned) is False

    def test_large_temp_range_change_returns_true(self):
        learner = AdaptiveLearner(db_path="/nonexistent")
        current = NervousSystemCalibration()
        learned = NervousSystemCalibration.from_dict(current.to_dict())
        # Expand range by >10%
        learned.ambient_temp_max = current.ambient_temp_max + 10.0
        assert learner.should_adapt(current, learned) is True

    def test_large_humidity_change_returns_true(self):
        learner = AdaptiveLearner(db_path="/nonexistent")
        current = NervousSystemCalibration()
        learned = NervousSystemCalibration.from_dict(current.to_dict())
        learned.humidity_ideal = current.humidity_ideal * 1.3  # 30% change
        assert learner.should_adapt(current, learned) is True

    def test_all_small_changes_returns_false(self):
        learner = AdaptiveLearner(db_path="/nonexistent")
        current = NervousSystemCalibration()
        learned = NervousSystemCalibration.from_dict(current.to_dict())
        learned.pressure_ideal += 1.0  # small
        learned.humidity_ideal += 1.0  # small
        assert learner.should_adapt(current, learned) is False


# ---------------------------------------------------------------------------
# detect_gap — real SQLite
# ---------------------------------------------------------------------------

class TestDetectGap:
    def test_no_db_returns_none(self, tmp_path):
        learner = AdaptiveLearner(db_path=str(tmp_path / "missing.db"))
        assert learner.detect_gap() is None

    def test_empty_db_returns_none(self, learner):
        assert learner.detect_gap() is None

    def test_heartbeat_row_returns_gap(self, learning_db):
        conn = sqlite3.connect(str(learning_db))
        ts = (datetime.now() - timedelta(seconds=60)).isoformat()
        conn.execute("INSERT INTO identity (id, last_heartbeat_at) VALUES (1, ?)", (ts,))
        conn.commit()
        conn.close()

        learner = AdaptiveLearner(db_path=str(learning_db))
        gap = learner.detect_gap()
        assert gap is not None
        assert 55 <= gap.total_seconds() <= 70, f"gap={gap.total_seconds()}s, expected ~60s"

    def test_sleep_event_fallback(self, learning_db):
        conn = sqlite3.connect(str(learning_db))
        ts = (datetime.now() - timedelta(seconds=120)).isoformat()
        conn.execute("INSERT INTO events (event_type, timestamp) VALUES ('sleep', ?)", (ts,))
        conn.commit()
        conn.close()

        learner = AdaptiveLearner(db_path=str(learning_db))
        gap = learner.detect_gap()
        assert gap is not None
        assert 115 <= gap.total_seconds() <= 130

    def test_state_history_fallback(self, learning_db):
        conn = sqlite3.connect(str(learning_db))
        ts = (datetime.now() - timedelta(seconds=180)).isoformat()
        conn.execute(
            "INSERT INTO state_history (timestamp, sensors) VALUES (?, ?)",
            (ts, '{}'),
        )
        conn.commit()
        conn.close()

        learner = AdaptiveLearner(db_path=str(learning_db))
        gap = learner.detect_gap()
        assert gap is not None
        assert 175 <= gap.total_seconds() <= 190

    def test_heartbeat_takes_priority_over_sleep(self, learning_db):
        conn = sqlite3.connect(str(learning_db))
        hb_ts = (datetime.now() - timedelta(seconds=30)).isoformat()
        sleep_ts = (datetime.now() - timedelta(seconds=600)).isoformat()
        conn.execute("INSERT INTO identity (id, last_heartbeat_at) VALUES (1, ?)", (hb_ts,))
        conn.execute("INSERT INTO events (event_type, timestamp) VALUES ('sleep', ?)", (sleep_ts,))
        conn.commit()
        conn.close()

        learner = AdaptiveLearner(db_path=str(learning_db))
        gap = learner.detect_gap()
        assert gap is not None
        assert gap.total_seconds() < 60, "Should use heartbeat (~30s), not sleep (~600s)"


# ---------------------------------------------------------------------------
# get_recent_observations — real SQLite
# ---------------------------------------------------------------------------

class TestGetRecentObservations:
    def test_no_db_returns_empty(self, tmp_path):
        learner = AdaptiveLearner(db_path=str(tmp_path / "missing.db"))
        temps, pressures, humidities = learner.get_recent_observations()
        assert temps == [] and pressures == [] and humidities == []

    def test_empty_db_returns_empty(self, learner):
        temps, pressures, humidities = learner.get_recent_observations()
        assert temps == [] and pressures == [] and humidities == []

    def test_valid_rows_parsed(self, learning_db, learner):
        _seed_rows(learning_db, 3, temp=22.0, pressure=827.0, humidity=40.0)
        temps, pressures, humidities = learner.get_recent_observations()
        assert len(temps) == 3
        assert len(pressures) == 3
        assert len(humidities) == 3

    def test_malformed_json_rows_skipped(self, learning_db, learner):
        conn = sqlite3.connect(str(learning_db))
        now = datetime.now()
        # Bad row
        conn.execute(
            "INSERT INTO state_history (timestamp, sensors) VALUES (?, ?)",
            (now.isoformat(), "not json"),
        )
        # Good rows
        for i in range(2):
            conn.execute(
                "INSERT INTO state_history (timestamp, sensors) VALUES (?, ?)",
                ((now - timedelta(hours=i + 1)).isoformat(), json.dumps({"ambient_temp_c": 22.0})),
            )
        conn.commit()
        conn.close()

        temps, _, _ = learner.get_recent_observations()
        assert len(temps) == 2

    def test_null_sensor_values_skipped(self, learning_db, learner):
        conn = sqlite3.connect(str(learning_db))
        sensors = json.dumps({"ambient_temp_c": None, "pressure_hpa": 827.0})
        conn.execute(
            "INSERT INTO state_history (timestamp, sensors) VALUES (?, ?)",
            (datetime.now().isoformat(), sensors),
        )
        conn.commit()
        conn.close()

        temps, pressures, _ = learner.get_recent_observations()
        assert len(temps) == 0  # None was skipped
        assert len(pressures) == 1


# ---------------------------------------------------------------------------
# learn_calibration — real SQLite
# ---------------------------------------------------------------------------

class TestLearnCalibration:
    def test_returns_none_below_min_observations(self, learning_db, learner):
        _seed_rows(learning_db, 10)
        cal = NervousSystemCalibration()
        assert learner.learn_calibration(cal, min_observations=50) is None

    def test_returns_calibration_above_min(self, learning_db, learner):
        _seed_rows(learning_db, 60)
        cal = NervousSystemCalibration()
        learned = learner.learn_calibration(cal, min_observations=50)
        assert learned is not None
        assert isinstance(learned, NervousSystemCalibration)

    def test_pressure_mean_learned(self, learning_db, learner):
        _seed_rows(learning_db, 60, pressure=827.0)
        cal = NervousSystemCalibration()
        learned = learner.learn_calibration(cal, min_observations=50)
        # Mean should be near 827 (± small variation from seeding)
        assert abs(learned.pressure_ideal - 827.0) < 2.0

    def test_humidity_clamped_to_80(self, learning_db, learner):
        _seed_rows(learning_db, 60, humidity=95.0)
        cal = NervousSystemCalibration()
        learned = learner.learn_calibration(cal, min_observations=50)
        assert learned.humidity_ideal <= 80.0

    def test_humidity_clamped_to_20(self, learning_db, learner):
        _seed_rows(learning_db, 60, humidity=5.0)
        cal = NervousSystemCalibration()
        learned = learner.learn_calibration(cal, min_observations=50)
        assert learned.humidity_ideal >= 20.0

    def test_temp_range_expanded(self, learning_db, learner):
        _seed_rows(learning_db, 60, temp=22.0)
        cal = NervousSystemCalibration()
        learned = learner.learn_calibration(cal, min_observations=50)
        # Minimum floor is 15°C, maximum floor is 35°C
        assert learned.ambient_temp_min <= 15.0
        assert learned.ambient_temp_max >= 35.0

    def test_original_calibration_not_mutated(self, learning_db, learner):
        _seed_rows(learning_db, 60, pressure=900.0)
        cal = NervousSystemCalibration()
        original_pressure = cal.pressure_ideal
        learner.learn_calibration(cal, min_observations=50)
        assert cal.pressure_ideal == original_pressure


# ---------------------------------------------------------------------------
# get_observation_count
# ---------------------------------------------------------------------------

class TestGetObservationCount:
    def test_no_db_returns_zero(self, tmp_path):
        learner = AdaptiveLearner(db_path=str(tmp_path / "missing.db"))
        assert learner.get_observation_count() == 0

    def test_counts_within_window(self, learning_db, learner):
        _seed_rows(learning_db, 5)
        assert learner.get_observation_count() == 5

    def test_old_rows_excluded(self, learning_db, learner):
        _seed_rows(learning_db, 3, days_ago=0)
        _seed_rows(learning_db, 2, days_ago=30)  # outside 7-day window
        assert learner.get_observation_count(days=7) == 3


# ---------------------------------------------------------------------------
# can_learn
# ---------------------------------------------------------------------------

class TestCanLearn:
    def test_false_when_db_missing(self, tmp_path):
        learner = AdaptiveLearner(db_path=str(tmp_path / "missing.db"))
        assert learner.can_learn() is False

    def test_false_when_too_few(self, learning_db, learner):
        _seed_rows(learning_db, 10)
        assert learner.can_learn(min_observations=50) is False

    def test_true_when_enough(self, learning_db, learner):
        _seed_rows(learning_db, 60)
        assert learner.can_learn(min_observations=50) is True


# ---------------------------------------------------------------------------
# adapt_calibration — mocked ConfigManager
# ---------------------------------------------------------------------------

class TestAdaptCalibration:
    def _mock_config_manager(self, calibration=None):
        cm = MagicMock()
        cm.get_calibration.return_value = calibration or NervousSystemCalibration()
        mock_config = MagicMock()
        cm.load.return_value = mock_config
        cm.config_path = Path("/nonexistent/config.yaml")
        cm.save.return_value = True
        return cm

    def test_returns_false_when_cooldown_active(self, learning_db, learner):
        cm = self._mock_config_manager()
        # Mock should_adapt_now to return False
        with patch.object(learner, "should_adapt_now", return_value=False):
            adapted, cal = learner.adapt_calibration(config_manager=cm)
        assert adapted is False
        assert cal is None

    def test_returns_false_when_insufficient_data(self, learning_db, learner):
        cm = self._mock_config_manager()
        # No data seeded, should_adapt_now=True
        with patch.object(learner, "should_adapt_now", return_value=True):
            adapted, cal = learner.adapt_calibration(config_manager=cm, min_observations=50)
        assert adapted is False
        assert cal is None

    def test_returns_false_when_below_threshold(self, learning_db, learner):
        # Seed data very close to defaults
        _seed_rows(learning_db, 60, pressure=1013.0, humidity=45.0)
        cal = NervousSystemCalibration()
        cm = self._mock_config_manager(calibration=cal)
        with patch.object(learner, "should_adapt_now", return_value=True):
            adapted, result = learner.adapt_calibration(config_manager=cm, min_observations=50)
        assert adapted is False

    def test_returns_true_on_success(self, learning_db, learner):
        # Seed data far from defaults to trigger adaptation
        _seed_rows(learning_db, 60, pressure=827.0)
        cm = self._mock_config_manager()
        with patch.object(learner, "should_adapt_now", return_value=True):
            adapted, cal = learner.adapt_calibration(config_manager=cm, min_observations=50)
        assert adapted is True
        assert cal is not None
        cm.save.assert_called_once()

    def test_returns_false_when_save_fails(self, learning_db, learner):
        _seed_rows(learning_db, 60, pressure=827.0)
        cm = self._mock_config_manager()
        cm.save.return_value = False
        with patch.object(learner, "should_adapt_now", return_value=True):
            adapted, cal = learner.adapt_calibration(config_manager=cm, min_observations=50)
        assert adapted is False
        assert cal is None


# ---------------------------------------------------------------------------
# connect — WAL mode
# ---------------------------------------------------------------------------

class TestConnect:
    def test_connection_reused(self, learner):
        conn1 = learner._connect()
        conn2 = learner._connect()
        assert conn1 is conn2

    def test_wal_mode_set(self, learner):
        conn = learner._connect()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestGetLearner:
    def test_returns_same_instance(self):
        import anima_mcp.learning as mod
        old = mod._learner
        mod._learner = None
        try:
            l1 = get_learner("/tmp/test_singleton.db")
            l2 = get_learner()
            assert l1 is l2
        finally:
            mod._learner = old
