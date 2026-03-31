"""
Tests for lifecycle.py — wake() and sleep() server lifecycle management.

Covers:
  - wake() basic flow: ServerContext creation, identity resolution
  - wake() SQLite retry logic (database locked)
  - wake() identity precedence (provided ID, existing DB, new UUID)
  - wake() non-fatal subsystem failures (growth, health, trajectory, schema, drift)
  - wake() gives up after max_attempts on non-lock errors
  - sleep() persistence: calibration drift, schema, trajectory, canvas
  - sleep() bridge cleanup
  - sleep() voice cleanup
  - sleep() store shutdown + WAL checkpoint
  - sleep() with None context (no-op)
  - _set_ctx() bridge to server module
"""

import sqlite3
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from anima_mcp.server_context import ServerContext
from anima_mcp import ctx_ref


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_identity(creature_id=None, name="Lumen", awakenings=3, alive_seconds=1000.0):
    """Create a mock CreatureIdentity via SimpleNamespace."""
    return SimpleNamespace(
        creature_id=creature_id or str(uuid.uuid4()),
        name=name,
        total_awakenings=awakenings,
        total_alive_seconds=alive_seconds,
        born_at=datetime(2025, 1, 1),
    )


def make_mock_store(creature_id=None, db_has_identity=True):
    """Create a mock IdentityStore that returns an identity on wake()."""
    cid = creature_id or str(uuid.uuid4())
    store = MagicMock()
    store.db_path = "test.db"
    store._conn = MagicMock()

    identity = make_identity(creature_id=cid)
    store.wake.return_value = identity
    store.get_identity.return_value = identity
    store.sleep.return_value = 42.0  # session seconds

    # For the DB identity check in wake()
    conn_mock = MagicMock()
    if db_has_identity:
        conn_mock.execute.return_value.fetchone.return_value = (cid,)
    else:
        conn_mock.execute.return_value.fetchone.return_value = None
    store._connect.return_value = conn_mock

    return store


@pytest.fixture(autouse=True)
def cleanup_ctx():
    """Ensure ctx_ref is clean before and after each test."""
    ctx_ref._ctx = None
    yield
    ctx_ref._ctx = None


def _wake_patches():
    """Return dict of common patches needed for wake() to succeed.

    wake() does local imports from many submodules. We patch at the source
    so that when wake() does `from .identity import IdentityStore`, it gets
    our mock.
    """
    return {
        "store_cls": patch("anima_mcp.identity.IdentityStore"),
        "growth": patch("anima_mcp.growth.get_growth_system"),
        "traj": patch("anima_mcp.eisv.get_trajectory_awareness"),
        "schema_hub": patch("anima_mcp.accessors._get_schema_hub"),
        "cal_drift": patch("anima_mcp.accessors._get_calibration_drift"),
        "readings": patch("anima_mcp.accessors._get_readings_and_anima", return_value=(None, None)),
        "shm_data": patch("anima_mcp.accessors._get_last_shm_data", return_value=None),
        "health": patch("anima_mcp.lifecycle.get_health_registry", create=True),
    }


# ---------------------------------------------------------------------------
# _set_ctx
# ---------------------------------------------------------------------------

class TestSetCtx:
    def test_sets_ctx_ref_and_server_module(self):
        """_set_ctx writes to both ctx_ref and server._ctx."""
        from anima_mcp.lifecycle import _set_ctx
        from anima_mcp import server as server_mod
        ctx = ServerContext()
        _set_ctx(ctx)
        assert ctx_ref._ctx is ctx
        assert server_mod._ctx is ctx

    def test_set_ctx_to_none(self):
        """_set_ctx(None) clears both references."""
        from anima_mcp.lifecycle import _set_ctx
        from anima_mcp import server as server_mod
        ctx_ref._ctx = ServerContext()
        _set_ctx(None)
        assert ctx_ref._ctx is None
        assert server_mod._ctx is None


# ---------------------------------------------------------------------------
# wake()
# ---------------------------------------------------------------------------

class TestWake:
    def test_wake_basic_success(self):
        """wake() creates context, initializes store, and returns without error."""
        from anima_mcp.lifecycle import wake

        store = make_mock_store()
        store.get_recent_state_history.return_value = []

        with patch("anima_mcp.identity.IdentityStore", return_value=store) as MockStore, \
             patch("anima_mcp.growth.get_growth_system", return_value=MagicMock(born_at=None)), \
             patch("anima_mcp.eisv.get_trajectory_awareness") as mock_traj, \
             patch("anima_mcp.accessors._get_schema_hub") as mock_hub, \
             patch("anima_mcp.accessors._get_calibration_drift") as mock_drift, \
             patch("anima_mcp.accessors._get_readings_and_anima", return_value=(None, None)):
            mock_traj.return_value = MagicMock(bootstrap_from_history=MagicMock(return_value=0))
            mock_hub.return_value = MagicMock(
                on_wake=MagicMock(return_value=None),
                compose_schema=MagicMock(return_value=MagicMock(nodes=[], edges=[])),
                last_trajectory=None,
            )
            mock_drift.return_value = MagicMock(
                get_midpoints=MagicMock(return_value={"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}),
            )

            wake(db_path=":memory:", anima_id="test-id-1234-5678")

        MockStore.assert_called_once_with(":memory:")
        store.wake.assert_called_once_with("test-id-1234-5678")

    def test_wake_uses_provided_anima_id(self):
        """When anima_id is provided, it takes precedence over DB lookup."""
        from anima_mcp.lifecycle import wake

        store = make_mock_store()
        store.get_recent_state_history.return_value = []

        with patch("anima_mcp.identity.IdentityStore", return_value=store), \
             patch("anima_mcp.growth.get_growth_system", return_value=MagicMock(born_at=None)), \
             patch("anima_mcp.eisv.get_trajectory_awareness") as mt, \
             patch("anima_mcp.accessors._get_schema_hub") as ms, \
             patch("anima_mcp.accessors._get_calibration_drift") as md, \
             patch("anima_mcp.accessors._get_readings_and_anima", return_value=(None, None)):
            mt.return_value = MagicMock(bootstrap_from_history=MagicMock(return_value=0))
            ms.return_value = MagicMock(on_wake=MagicMock(return_value=None),
                compose_schema=MagicMock(return_value=MagicMock(nodes=[], edges=[])), last_trajectory=None)
            md.return_value = MagicMock(get_midpoints=MagicMock(
                return_value={"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}))

            provided_id = "my-custom-id-1234"
            wake(db_path=":memory:", anima_id=provided_id)

        store.wake.assert_called_once_with(provided_id)
        # DB identity lookup NOT called when anima_id provided
        store._connect.assert_not_called()

    def test_wake_uses_existing_db_identity(self):
        """When no anima_id provided, wake() checks DB for existing identity."""
        from anima_mcp.lifecycle import wake

        existing_id = "existing-db-id-5678"
        store = make_mock_store(creature_id=existing_id, db_has_identity=True)
        store.get_recent_state_history.return_value = []

        with patch("anima_mcp.identity.IdentityStore", return_value=store), \
             patch("anima_mcp.growth.get_growth_system", return_value=MagicMock(born_at=None)), \
             patch("anima_mcp.eisv.get_trajectory_awareness") as mt, \
             patch("anima_mcp.accessors._get_schema_hub") as ms, \
             patch("anima_mcp.accessors._get_calibration_drift") as md, \
             patch("anima_mcp.accessors._get_readings_and_anima", return_value=(None, None)):
            mt.return_value = MagicMock(bootstrap_from_history=MagicMock(return_value=0))
            ms.return_value = MagicMock(on_wake=MagicMock(return_value=None),
                compose_schema=MagicMock(return_value=MagicMock(nodes=[], edges=[])), last_trajectory=None)
            md.return_value = MagicMock(get_midpoints=MagicMock(
                return_value={"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}))

            wake(db_path=":memory:")

        store.wake.assert_called_once_with(existing_id)

    def test_wake_generates_new_uuid_when_no_existing_identity(self):
        """When no identity exists in DB, wake() generates a new UUID."""
        from anima_mcp.lifecycle import wake

        store = make_mock_store(db_has_identity=False)
        store.get_recent_state_history.return_value = []

        with patch("anima_mcp.identity.IdentityStore", return_value=store), \
             patch("anima_mcp.growth.get_growth_system", return_value=MagicMock(born_at=None)), \
             patch("anima_mcp.eisv.get_trajectory_awareness") as mt, \
             patch("anima_mcp.accessors._get_schema_hub") as ms, \
             patch("anima_mcp.accessors._get_calibration_drift") as md, \
             patch("anima_mcp.accessors._get_readings_and_anima", return_value=(None, None)):
            mt.return_value = MagicMock(bootstrap_from_history=MagicMock(return_value=0))
            ms.return_value = MagicMock(on_wake=MagicMock(return_value=None),
                compose_schema=MagicMock(return_value=MagicMock(nodes=[], edges=[])), last_trajectory=None)
            md.return_value = MagicMock(get_midpoints=MagicMock(
                return_value={"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}))

            wake(db_path=":memory:")

        # A UUID was generated and passed to store.wake
        call_args = store.wake.call_args[0]
        generated_id = call_args[0]
        uuid.UUID(generated_id)  # Raises if invalid

    def test_wake_retries_on_db_locked(self):
        """wake() retries with backoff on 'database is locked' errors."""
        from anima_mcp.lifecycle import wake

        lock_error = sqlite3.OperationalError("database is locked")
        store_good = make_mock_store()
        store_good.get_recent_state_history.return_value = []

        call_count = 0
        def store_factory(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise lock_error
            return store_good

        with patch("anima_mcp.identity.IdentityStore", side_effect=store_factory), \
             patch("anima_mcp.growth.get_growth_system", return_value=MagicMock(born_at=None)), \
             patch("anima_mcp.eisv.get_trajectory_awareness") as mt, \
             patch("anima_mcp.accessors._get_schema_hub") as ms, \
             patch("anima_mcp.accessors._get_calibration_drift") as md, \
             patch("anima_mcp.accessors._get_readings_and_anima", return_value=(None, None)), \
             patch("time.sleep") as mock_sleep:
            mt.return_value = MagicMock(bootstrap_from_history=MagicMock(return_value=0))
            ms.return_value = MagicMock(on_wake=MagicMock(return_value=None),
                compose_schema=MagicMock(return_value=MagicMock(nodes=[], edges=[])), last_trajectory=None)
            md.return_value = MagicMock(get_midpoints=MagicMock(
                return_value={"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}))

            wake(db_path=":memory:", anima_id="test-id")

        # Retried with escalating waits
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(2)  # attempt 1: 1 * 2
        mock_sleep.assert_any_call(4)  # attempt 2: 2 * 2

    def test_wake_gives_up_on_non_lock_error(self):
        """wake() gives up immediately on errors that aren't database lock."""
        from anima_mcp.lifecycle import wake

        with patch("anima_mcp.identity.IdentityStore", side_effect=RuntimeError("some other error")):
            # Should not crash -- wake is "safe, never crashes"
            wake(db_path=":memory:", anima_id="test-id")

        # Context cleared on failure
        assert ctx_ref._ctx is None

    def test_wake_gives_up_after_max_attempts_on_lock(self):
        """wake() stops retrying after 5 database lock failures."""
        from anima_mcp.lifecycle import wake

        with patch("anima_mcp.identity.IdentityStore",
                    side_effect=sqlite3.OperationalError("database is locked")), \
             patch("time.sleep") as mock_sleep:
            wake(db_path=":memory:", anima_id="test-id")

        # 5 attempts total, 4 sleeps (no sleep on last failure)
        assert mock_sleep.call_count == 4
        assert ctx_ref._ctx is None

    def test_wake_growth_failure_is_non_fatal(self):
        """If growth system fails, wake() continues (growth set to None)."""
        from anima_mcp.lifecycle import wake

        store = make_mock_store()
        store.get_recent_state_history.return_value = []

        with patch("anima_mcp.identity.IdentityStore", return_value=store), \
             patch("anima_mcp.growth.get_growth_system", side_effect=RuntimeError("growth broken")), \
             patch("anima_mcp.eisv.get_trajectory_awareness") as mt, \
             patch("anima_mcp.accessors._get_schema_hub") as ms, \
             patch("anima_mcp.accessors._get_calibration_drift") as md, \
             patch("anima_mcp.accessors._get_readings_and_anima", return_value=(None, None)):
            mt.return_value = MagicMock(bootstrap_from_history=MagicMock(return_value=0))
            ms.return_value = MagicMock(on_wake=MagicMock(return_value=None),
                compose_schema=MagicMock(return_value=MagicMock(nodes=[], edges=[])), last_trajectory=None)
            md.return_value = MagicMock(get_midpoints=MagicMock(
                return_value={"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}))

            wake(db_path=":memory:", anima_id="test-id")

        # wake completed (ctx should be set, growth is None on context)
        assert ctx_ref._ctx is not None
        assert ctx_ref._ctx.growth is None

    def test_wake_warm_start_from_state_history(self):
        """wake() extracts warm_start_anima from last state history row."""
        from anima_mcp.lifecycle import wake

        store = make_mock_store()
        history = [
            {"warmth": 0.4, "clarity": 0.5, "stability": 0.6, "presence": 0.7},
            {"warmth": 0.6, "clarity": 0.7, "stability": 0.8, "presence": 0.9},
        ]
        store.get_recent_state_history.return_value = history

        with patch("anima_mcp.identity.IdentityStore", return_value=store), \
             patch("anima_mcp.growth.get_growth_system", return_value=MagicMock(born_at=None)), \
             patch("anima_mcp.eisv.get_trajectory_awareness") as mt, \
             patch("anima_mcp.accessors._get_schema_hub") as ms, \
             patch("anima_mcp.accessors._get_calibration_drift") as md, \
             patch("anima_mcp.accessors._get_readings_and_anima", return_value=(None, None)):
            mt.return_value = MagicMock(bootstrap_from_history=MagicMock(return_value=5))
            ms.return_value = MagicMock(on_wake=MagicMock(return_value=None),
                compose_schema=MagicMock(return_value=MagicMock(nodes=[], edges=[])), last_trajectory=None)
            md.return_value = MagicMock(get_midpoints=MagicMock(
                return_value={"warmth": 0.5, "clarity": 0.5, "stability": 0.5, "presence": 0.5}))

            wake(db_path=":memory:", anima_id="test-id")

        assert ctx_ref._ctx.warm_start_anima == {
            "warmth": 0.6, "clarity": 0.7, "stability": 0.8, "presence": 0.9,
        }


# ---------------------------------------------------------------------------
# sleep()
# ---------------------------------------------------------------------------

class TestSleep:
    def test_sleep_with_none_context(self):
        """sleep() is safe when context is None."""
        from anima_mcp.lifecycle import sleep

        ctx_ref._ctx = None
        with patch("anima_mcp.accessors._get_server_bridge", return_value=None), \
             patch("anima_mcp.self_reflection.get_reflection_system"):
            sleep()

        assert ctx_ref._ctx is None

    def test_sleep_persists_calibration_drift(self, tmp_path):
        """sleep() saves calibration drift to disk."""
        from anima_mcp.lifecycle import sleep

        drift = MagicMock()
        ctx = ServerContext()
        ctx.calibration_drift = drift
        ctx_ref._ctx = ctx

        with patch("anima_mcp.accessors._get_server_bridge", return_value=None), \
             patch("anima_mcp.self_reflection.get_reflection_system"), \
             patch("anima_mcp.lifecycle.Path") as MockPath:
            MockPath.home.return_value = tmp_path
            sleep()

        drift.save.assert_called_once()

    def test_sleep_persists_schema(self):
        """sleep() calls schema_hub.persist_schema() when hub exists."""
        from anima_mcp.lifecycle import sleep

        hub = MagicMock()
        hub.persist_schema.return_value = True
        ctx = ServerContext()
        ctx.schema_hub = hub
        ctx_ref._ctx = ctx

        with patch("anima_mcp.accessors._get_server_bridge", return_value=None), \
             patch("anima_mcp.self_reflection.get_reflection_system"):
            sleep()

        hub.persist_schema.assert_called_once()

    def test_sleep_persists_trajectory_when_growth_exists(self):
        """sleep() computes and saves trajectory when growth system exists."""
        from anima_mcp.lifecycle import sleep

        ctx = ServerContext()
        ctx.growth = MagicMock()
        ctx_ref._ctx = ctx

        with patch("anima_mcp.accessors._get_server_bridge", return_value=None), \
             patch("anima_mcp.self_reflection.get_reflection_system"), \
             patch("anima_mcp.trajectory.compute_trajectory_signature") as mock_compute, \
             patch("anima_mcp.trajectory.save_trajectory") as mock_save, \
             patch("anima_mcp.self_model.get_self_model"), \
             patch("anima_mcp.anima_history.get_anima_history"):
            mock_compute.return_value = MagicMock()
            mock_save.return_value = True
            sleep()

        mock_save.assert_called_once()

    def test_sleep_saves_canvas_when_pixels_exist(self):
        """sleep() saves drawing canvas when screen_renderer has pixels."""
        from anima_mcp.lifecycle import sleep

        canvas = MagicMock()
        canvas.pixels = [1, 2, 3]
        drawing_engine = MagicMock()
        drawing_engine.canvas = canvas
        renderer = MagicMock()
        renderer.drawing_engine = drawing_engine

        ctx = ServerContext()
        ctx.screen_renderer = renderer
        ctx_ref._ctx = ctx

        with patch("anima_mcp.accessors._get_server_bridge", return_value=None), \
             patch("anima_mcp.self_reflection.get_reflection_system"):
            sleep()

        canvas.save_to_disk.assert_called_once()

    def test_sleep_does_not_save_empty_canvas(self):
        """sleep() skips canvas save when no pixels drawn."""
        from anima_mcp.lifecycle import sleep

        canvas = MagicMock()
        canvas.pixels = []  # Empty (falsy)
        drawing_engine = MagicMock()
        drawing_engine.canvas = canvas
        renderer = MagicMock()
        renderer.drawing_engine = drawing_engine

        ctx = ServerContext()
        ctx.screen_renderer = renderer
        ctx_ref._ctx = ctx

        with patch("anima_mcp.accessors._get_server_bridge", return_value=None), \
             patch("anima_mcp.self_reflection.get_reflection_system"):
            sleep()

        canvas.save_to_disk.assert_not_called()

    def test_sleep_closes_bridge(self):
        """sleep() closes the UNITARES bridge if it exists."""
        from anima_mcp.lifecycle import sleep
        import asyncio

        bridge = MagicMock()
        ctx = ServerContext()
        ctx_ref._ctx = ctx

        loop = asyncio.new_event_loop()
        with patch("anima_mcp.accessors._get_server_bridge", return_value=bridge), \
             patch("anima_mcp.self_reflection.get_reflection_system"), \
             patch("asyncio.get_event_loop", return_value=loop):
            with patch.object(loop, 'is_running', return_value=False), \
                 patch.object(loop, 'run_until_complete'):
                sleep()

        loop.close()

    def test_sleep_stops_voice(self):
        """sleep() stops voice instance and sets it to None."""
        from anima_mcp.lifecycle import sleep

        voice = MagicMock()
        ctx = ServerContext()
        ctx.voice_instance = voice
        ctx_ref._ctx = ctx

        with patch("anima_mcp.accessors._get_server_bridge", return_value=None), \
             patch("anima_mcp.self_reflection.get_reflection_system"):
            sleep()

        voice.stop.assert_called_once()

    def test_sleep_calls_store_sleep_and_wal_checkpoint(self):
        """sleep() calls store.sleep(), WAL checkpoint, and store.close()."""
        from anima_mcp.lifecycle import sleep

        store = MagicMock()
        store.sleep.return_value = 123.0
        store._conn = MagicMock()

        ctx = ServerContext()
        ctx.store = store
        ctx_ref._ctx = ctx

        with patch("anima_mcp.accessors._get_server_bridge", return_value=None), \
             patch("anima_mcp.self_reflection.get_reflection_system"):
            sleep()

        store.sleep.assert_called_once()
        store._conn.execute.assert_called_with("PRAGMA wal_checkpoint(TRUNCATE)")
        store.close.assert_called_once()
        assert ctx_ref._ctx is None

    def test_sleep_handles_store_sleep_error(self):
        """sleep() handles errors during store.sleep() without crashing."""
        from anima_mcp.lifecycle import sleep

        store = MagicMock()
        store.sleep.side_effect = RuntimeError("shutdown error")
        store._conn = MagicMock()

        ctx = ServerContext()
        ctx.store = store
        ctx_ref._ctx = ctx

        with patch("anima_mcp.accessors._get_server_bridge", return_value=None), \
             patch("anima_mcp.self_reflection.get_reflection_system"):
            sleep()  # Should not raise

        # Context still cleaned up in finally block
        assert ctx_ref._ctx is None

    def test_sleep_handles_drift_save_error(self):
        """sleep() continues when calibration drift save fails."""
        from anima_mcp.lifecycle import sleep

        drift = MagicMock()
        drift.save.side_effect = OSError("disk full")
        ctx = ServerContext()
        ctx.calibration_drift = drift
        ctx_ref._ctx = ctx

        with patch("anima_mcp.accessors._get_server_bridge", return_value=None), \
             patch("anima_mcp.self_reflection.get_reflection_system"), \
             patch("anima_mcp.lifecycle.Path") as MockPath:
            MockPath.home.return_value = Path("/tmp")
            sleep()  # Should not raise

    def test_sleep_closes_self_reflection(self):
        """sleep() closes the SelfReflection system."""
        from anima_mcp.lifecycle import sleep

        ctx_ref._ctx = None

        with patch("anima_mcp.accessors._get_server_bridge", return_value=None), \
             patch("anima_mcp.self_reflection.get_reflection_system") as mock_refl:
            sleep()

        mock_refl.return_value.close.assert_called_once()
