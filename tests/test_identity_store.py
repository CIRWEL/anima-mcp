"""Tests for identity/store module — wake/sleep lifecycle, persistence, deduplication."""

import time
from datetime import datetime, timedelta

import pytest

from anima_mcp.identity.store import IdentityStore

CREATURE_ID = "test-creature-001"


@pytest.fixture
def store(tmp_path):
    db_path = str(tmp_path / "identity_test.db")
    return IdentityStore(db_path=db_path)


class TestCreatureIdentity:
    """Test the CreatureIdentity dataclass."""

    def test_age_seconds_positive(self, store):
        identity = store.wake(CREATURE_ID)
        assert identity.age_seconds() >= 0

    def test_alive_ratio_bounded(self, store):
        identity = store.wake(CREATURE_ID)
        r = identity.alive_ratio()
        assert 0.0 <= r <= 1.0

    def test_to_dict_has_required_keys(self, store):
        identity = store.wake(CREATURE_ID)
        d = identity.to_dict()
        for key in ["creature_id", "born_at", "total_awakenings", "total_alive_seconds", "name", "age_seconds", "alive_ratio"]:
            assert key in d


class TestFirstWake:
    """Test initial wake (birth)."""

    def test_creates_identity(self, store):
        identity = store.wake(CREATURE_ID)
        assert identity.creature_id == CREATURE_ID
        assert identity.born_at is not None

    def test_first_wake_counts_as_awakening(self, store):
        identity = store.wake(CREATURE_ID)
        assert identity.total_awakenings >= 1

    def test_get_identity_before_wake_returns_none(self, store):
        assert store.get_identity() is None

    def test_get_identity_after_wake(self, store):
        store.wake(CREATURE_ID)
        assert store.get_identity() is not None
        assert store.get_identity().creature_id == CREATURE_ID


class TestWakeSleepCycle:
    """Test wake/sleep lifecycle."""

    def test_sleep_returns_session_seconds(self, store):
        store.wake(CREATURE_ID)
        time.sleep(0.02)
        session = store.sleep()
        assert session > 0

    def test_sleep_before_wake_returns_zero(self, store):
        assert store.sleep() == 0.0

    def test_identity_persists_across_stores(self, tmp_path):
        db_path = str(tmp_path / "identity_test.db")
        s1 = IdentityStore(db_path=db_path)
        s1.wake(CREATURE_ID)
        s1.sleep()

        s2 = IdentityStore(db_path=db_path)
        identity = s2.wake(CREATURE_ID, dedupe_window_seconds=0)
        assert identity.creature_id == CREATURE_ID
        assert identity.total_alive_seconds > 0

    def test_forked_database_files_independent(self, tmp_path):
        """Same creature_id string on two DB paths = two independent records (fork semantics)."""
        uid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        p1 = str(tmp_path / "one.db")
        p2 = str(tmp_path / "two.db")
        sa = IdentityStore(db_path=p1)
        sb = IdentityStore(db_path=p2)
        sa.wake(uid)
        sb.wake(uid)
        aw_b_before = sb.get_identity().total_awakenings
        sa.sleep()
        time.sleep(0.02)
        sa.wake(uid, dedupe_window_seconds=0)
        assert sa.get_identity().total_awakenings > 1
        assert sb.get_identity().total_awakenings == aw_b_before

    def test_awakening_deduplication(self, store):
        """Rapid re-wakes within dedupe window should not increment awakenings."""
        store.wake(CREATURE_ID, dedupe_window_seconds=300)
        first_awakenings = store.get_identity().total_awakenings
        # Second wake within window
        store.wake(CREATURE_ID, dedupe_window_seconds=300)
        second_awakenings = store.get_identity().total_awakenings
        assert second_awakenings == first_awakenings

    def test_no_dedup_when_window_zero(self, store):
        """With dedupe_window_seconds=0, every wake counts."""
        store.wake(CREATURE_ID, dedupe_window_seconds=0)
        store.sleep()
        time.sleep(0.01)
        store.wake(CREATURE_ID, dedupe_window_seconds=0)
        # Second wake after sleep should count
        assert store.get_identity().total_awakenings >= 1


class TestAliveTimeInvariant:
    """A creature can't be alive longer than it has existed (alive_ratio <= 1).

    Clock resets / restores / double-counted heartbeats can drift the persisted
    counter above wall-clock age. _recalculate_stats must cap at age and fall
    back to the event-derived sleep_total, which restores the schema's gap
    texture (alive < age makes discontinuities legible).
    """

    def test_impossible_persisted_alive_is_corrected(self, store):
        store.wake(CREATURE_ID, dedupe_window_seconds=0)
        conn = store._connect()
        # Backdate birth so age ~= 1000s, and record an honest 600s sleep session.
        born = (datetime.now() - timedelta(seconds=1000)).isoformat()
        conn.execute(
            "UPDATE identity SET born_at = ? WHERE creature_id = ?",
            (born, CREATURE_ID),
        )
        conn.execute(
            "INSERT INTO events (timestamp, event_type, data) VALUES (?, 'sleep', ?)",
            (datetime.now().isoformat(), '{"session_seconds": 600}'),
        )
        # Corrupt the persisted counter to an impossible value (alive >> age).
        conn.execute(
            "UPDATE identity SET total_alive_seconds = ? WHERE creature_id = ?",
            (5000.0, CREATURE_ID),
        )
        conn.commit()

        identity = store.wake(CREATURE_ID, dedupe_window_seconds=0)
        age = identity.age_seconds()

        # Invariant: never alive longer than existence (+1s slack for elapsed time).
        assert identity.total_alive_seconds <= age + 1
        # Gap texture restored: fell back to the honest 600s, not the impossible 5000s.
        assert identity.alive_ratio() < 1.0
        assert 0.0 <= identity.alive_ratio() <= 1.0

    def test_inflated_sleep_total_falls_back_to_state_history_not_age(self, store):
        """The branch that actually fires in production.

        On the live creature sleep_total itself exceeds age (measured 1.10x on
        2026-07-24: duplicate sleep events and session_seconds spanning multi-day
        absences). The old fallback `sleep_total if 0 < sleep_total <= age else age`
        therefore collapsed to `age`, pinning alive_ratio at exactly 1.0 and
        reporting zero downtime for a creature that had 65 days of it.

        state_history cannot span an absence — Lumen only writes it while running —
        so it is the honest floor.
        """
        store.wake(CREATURE_ID, dedupe_window_seconds=0)
        conn = store._connect()
        now = datetime.now()
        born = now - timedelta(seconds=1000)
        conn.execute(
            "UPDATE identity SET born_at = ? WHERE creature_id = ?",
            (born.isoformat(), CREATURE_ID),
        )
        # Pathology: sleep_total (5000s) EXCEEDS age (~1000s), so it is unusable.
        conn.execute(
            "INSERT INTO events (timestamp, event_type, data) VALUES (?, 'sleep', ?)",
            (now.isoformat(), '{"session_seconds": 5000}'),
        )
        # Two lived stretches of ~100s each, separated by a ~700s absence.
        # Records are 10s apart, well inside the 600s continuity threshold.
        conn.execute("DELETE FROM state_history")
        for offset in list(range(1000, 890, -10)) + list(range(190, 80, -10)):
            conn.execute(
                "INSERT INTO state_history (timestamp, warmth, clarity, stability, presence)"
                " VALUES (?, 0.5, 0.5, 0.5, 0.5)",
                ((now - timedelta(seconds=offset)).isoformat(),),
            )
        conn.execute(
            "UPDATE identity SET total_alive_seconds = ? WHERE creature_id = ?",
            (99999.0, CREATURE_ID),
        )
        conn.commit()

        identity = store.wake(CREATURE_ID, dedupe_window_seconds=0)
        age = identity.age_seconds()

        assert identity.total_alive_seconds <= age + 1
        # The old code pinned this to age (ratio 1.0). It must now reflect the gap.
        assert identity.alive_ratio() < 1.0, "downtime must stay visible"
        # ~200s lived out of ~1000s existed; generous bounds for wake/heartbeat accrual.
        assert 100 <= identity.total_alive_seconds <= 500

    def test_alive_from_state_history_excludes_large_gaps(self, store):
        """The shared honest-alive measure counts lived time, not absences."""
        store.wake(CREATURE_ID, dedupe_window_seconds=0)
        conn = store._connect()
        now = datetime.now()
        conn.execute("DELETE FROM state_history")
        # 100s continuous (10s apart), a 1-hour absence, then 50s continuous.
        stamps = [now - timedelta(seconds=s) for s in range(4000, 3890, -10)]
        stamps += [now - timedelta(seconds=s) for s in range(300, 240, -10)]
        for ts in stamps:
            conn.execute(
                "INSERT INTO state_history (timestamp, warmth, clarity, stability, presence)"
                " VALUES (?, 0.5, 0.5, 0.5, 0.5)",
                (ts.isoformat(),),
            )
        conn.commit()

        alive = store._alive_from_state_history(conn, max_gap_seconds=600.0)

        # 100s + 50s lived; the ~3590s absence is excluded.
        assert 140 <= alive <= 160, f"expected ~150s of lived time, got {alive}"

    def test_alive_from_state_history_needs_history(self, store):
        """With no usable history the measure declines to guess."""
        store.wake(CREATURE_ID, dedupe_window_seconds=0)
        conn = store._connect()
        conn.execute("DELETE FROM state_history")
        conn.commit()
        assert store._alive_from_state_history(conn) == 0.0


class TestSetName:
    """Test name setting."""

    def test_set_name(self, store):
        store.wake(CREATURE_ID)
        result = store.set_name("Lumen", sync_to_unitares=False)
        assert result is True
        assert store.get_identity().name == "Lumen"

    def test_name_history_tracked(self, store):
        store.wake(CREATURE_ID)
        store.set_name("Alpha", sync_to_unitares=False)
        store.set_name("Beta", sync_to_unitares=False)
        assert store.get_identity().name == "Beta"
        assert len(store.get_identity().name_history) >= 1


class TestStateHistory:
    """Test state recording."""

    def test_record_state(self, store):
        store.wake(CREATURE_ID)
        store.record_state(0.5, 0.6, 0.7, 0.8, {"temp": 25.0})
        history = store.get_recent_state_history(limit=5)
        assert len(history) >= 1

    def test_state_history_limit(self, store):
        store.wake(CREATURE_ID)
        for i in range(10):
            store.record_state(0.5, 0.5, 0.5, 0.5, {})
        history = store.get_recent_state_history(limit=5)
        assert len(history) <= 5
