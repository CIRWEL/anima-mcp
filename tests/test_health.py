"""Tests for subsystem health monitoring."""

import time

from anima_mcp.health import HealthRegistry, SubsystemHealth, HEARTBEAT_STALE_SECONDS


class TestSubsystemHealth:
    """Tests for individual subsystem health tracking."""

    def test_heartbeat_updates_timestamp(self):
        sub = SubsystemHealth(name="test")
        assert sub.last_heartbeat > 0  # Defaults to time.time() at creation
        before = sub.last_heartbeat
        time.sleep(0.01)
        sub.heartbeat()
        assert sub.last_heartbeat > before

    def test_status_ok_after_heartbeat(self):
        sub = SubsystemHealth(name="test")
        sub.heartbeat()
        assert sub.get_status() == "ok"

    def test_status_stale_without_heartbeat(self):
        sub = SubsystemHealth(name="test")
        # Set heartbeat in the past
        sub.last_heartbeat = time.time() - HEARTBEAT_STALE_SECONDS - 1
        assert sub.get_status() == "stale"

    def test_status_missing_when_not_registered(self):
        sub = SubsystemHealth(name="test", registered=False)
        assert sub.get_status() == "missing"

    def test_status_degraded_when_probe_fails(self):
        sub = SubsystemHealth(name="test", probe_fn=lambda: False)
        sub.heartbeat()
        # Force probe to run
        sub.last_probe_time = 0
        assert sub.get_status() == "degraded"

    def test_status_missing_when_stale_and_probe_fails(self):
        sub = SubsystemHealth(name="test", probe_fn=lambda: False)
        sub.last_heartbeat = time.time() - HEARTBEAT_STALE_SECONDS - 1
        sub.last_probe_time = 0
        assert sub.get_status() == "missing"

    def test_probe_exception_sets_degraded(self):
        sub = SubsystemHealth(name="test", probe_fn=lambda: 1 / 0)
        sub.heartbeat()
        sub.last_probe_time = 0
        assert sub.get_status() == "degraded"
        assert "division by zero" in sub.last_probe_error

    def test_probe_respects_interval(self):
        call_count = 0
        def counting_probe():
            nonlocal call_count
            call_count += 1
            return True

        sub = SubsystemHealth(name="test", probe_fn=counting_probe)
        sub.run_probe()
        assert call_count == 1
        # Second call should use cache
        sub.run_probe()
        assert call_count == 1

    def test_to_dict_includes_status(self):
        sub = SubsystemHealth(name="test")
        sub.heartbeat()
        d = sub.to_dict()
        assert d["status"] == "ok"
        assert d["last_heartbeat_ago_s"] is not None
        assert d["last_heartbeat_ago_s"] < 1.0

    def test_to_dict_includes_probe_when_set(self):
        sub = SubsystemHealth(name="test", probe_fn=lambda: True)
        sub.heartbeat()
        sub.last_probe_time = 0  # force probe
        d = sub.to_dict()
        assert "probe" in d
        assert d["probe"] == "ok"

    def test_to_dict_no_probe_when_none(self):
        sub = SubsystemHealth(name="test")
        sub.heartbeat()
        d = sub.to_dict()
        assert "probe" not in d

    # --- Debounce tests ---

    def test_debounce_suppresses_transient_bad_status(self):
        """Bad status within debounce window should report 'ok'."""
        sub = SubsystemHealth(name="test", debounce_seconds=6.0)
        sub.last_heartbeat = time.time() - HEARTBEAT_STALE_SECONDS - 1
        # First check: starts grace period, reports ok
        assert sub.get_status() == "ok"
        assert sub._first_bad_at > 0

    def test_debounce_reports_bad_after_expiry(self):
        """Bad status persisting beyond debounce_seconds should be reported."""
        sub = SubsystemHealth(name="test", debounce_seconds=0.05)
        sub.last_heartbeat = time.time() - HEARTBEAT_STALE_SECONDS - 1
        # Start grace period
        sub.get_status()
        time.sleep(0.06)
        # Grace period expired
        assert sub.get_status() == "stale"

    def test_debounce_resets_on_recovery(self):
        """Recovery to 'ok' during grace period resets debounce."""
        sub = SubsystemHealth(name="test", debounce_seconds=6.0)
        sub.last_heartbeat = time.time() - HEARTBEAT_STALE_SECONDS - 1
        # Start grace period
        assert sub.get_status() == "ok"
        assert sub._first_bad_at > 0
        # Recover
        sub.heartbeat()
        assert sub.get_status() == "ok"
        assert sub._first_bad_at == 0.0

    def test_debounce_zero_is_backward_compatible(self):
        """debounce_seconds=0 means instant transitions (no grace period)."""
        sub = SubsystemHealth(name="test", debounce_seconds=0.0)
        sub.last_heartbeat = time.time() - HEARTBEAT_STALE_SECONDS - 1
        assert sub.get_status() == "stale"

    def test_to_dict_includes_debouncing_flag(self):
        """to_dict() should include 'debouncing: True' during grace period."""
        sub = SubsystemHealth(name="test", debounce_seconds=6.0)
        sub.last_heartbeat = time.time() - HEARTBEAT_STALE_SECONDS - 1
        sub.get_status()  # start grace period
        d = sub.to_dict()
        assert d["status"] == "ok"
        assert d.get("debouncing") is True

    def test_to_dict_no_debouncing_when_healthy(self):
        """to_dict() should not include 'debouncing' when status is genuinely ok."""
        sub = SubsystemHealth(name="test", debounce_seconds=6.0)
        sub.heartbeat()
        d = sub.to_dict()
        assert "debouncing" not in d

    def test_is_debouncing_property(self):
        """is_debouncing should be True only during grace period."""
        sub = SubsystemHealth(name="test", debounce_seconds=6.0)
        sub.heartbeat()
        assert sub.is_debouncing is False
        # Make it stale
        sub.last_heartbeat = time.time() - HEARTBEAT_STALE_SECONDS - 1
        sub.get_status()  # trigger grace period
        assert sub.is_debouncing is True


class TestHealthRegistry:
    """Tests for the central health registry."""

    def test_register_and_heartbeat(self):
        reg = HealthRegistry()
        reg.register("sensors")
        reg.heartbeat("sensors")
        status = reg.status()
        assert "sensors" in status
        assert status["sensors"]["status"] == "ok"

    def test_register_with_probe(self):
        reg = HealthRegistry()
        reg.register("growth", probe=lambda: True)
        reg.heartbeat("growth")
        status = reg.status()
        assert status["growth"]["probe"] == "ok"

    def test_auto_register_on_heartbeat(self):
        reg = HealthRegistry()
        reg.heartbeat("unknown_sub")
        assert "unknown_sub" in reg.subsystem_names()

    def test_overall_ok(self):
        reg = HealthRegistry()
        reg.register("a")
        reg.register("b")
        reg.heartbeat("a")
        reg.heartbeat("b")
        assert reg.overall() == "ok"

    def test_overall_degraded(self):
        reg = HealthRegistry()
        reg.register("a", probe=lambda: False)
        reg.heartbeat("a")
        # Force probe to run
        sub = reg.get_subsystem("a")
        sub.last_probe_time = 0
        assert reg.overall() == "degraded"

    def test_overall_unhealthy(self):
        reg = HealthRegistry()
        reg.register("a", probe=lambda: False)
        sub = reg.get_subsystem("a")
        sub.last_heartbeat = time.time() - HEARTBEAT_STALE_SECONDS - 1
        sub.last_probe_time = 0
        assert reg.overall() == "unhealthy"

    def test_overall_unknown_when_empty(self):
        reg = HealthRegistry()
        assert reg.overall() == "unknown"

    def test_summary_line(self):
        reg = HealthRegistry()
        reg.register("alpha")
        reg.register("beta")
        reg.heartbeat("alpha")
        reg.heartbeat("beta")
        line = reg.summary_line()
        assert "alpha=ok" in line
        assert "beta=ok" in line

    def test_subsystem_names_sorted(self):
        reg = HealthRegistry()
        reg.register("zebra")
        reg.register("alpha")
        reg.register("middle")
        assert reg.subsystem_names() == ["alpha", "middle", "zebra"]

    def test_re_register_updates_probe(self):
        reg = HealthRegistry()
        reg.register("test", probe=lambda: False)
        reg.register("test", probe=lambda: True)
        sub = reg.get_subsystem("test")
        sub.heartbeat()
        sub.last_probe_time = 0
        assert sub.run_probe() is True

    def test_get_subsystem_returns_none_for_unknown(self):
        reg = HealthRegistry()
        assert reg.get_subsystem("nonexistent") is None

    def test_register_with_debounce(self):
        reg = HealthRegistry()
        reg.register("fast", debounce_seconds=6.0)
        sub = reg.get_subsystem("fast")
        assert sub.debounce_seconds == 6.0

    def test_overall_ok_during_debounce_grace(self):
        """System should report ok while subsystem is debouncing."""
        reg = HealthRegistry()
        reg.register("a", debounce_seconds=6.0)
        reg.register("b")
        reg.heartbeat("b")
        # Make 'a' stale — but within debounce grace
        sub_a = reg.get_subsystem("a")
        sub_a.last_heartbeat = time.time() - HEARTBEAT_STALE_SECONDS - 1
        assert reg.overall() == "ok"  # debounce suppresses 'a'
