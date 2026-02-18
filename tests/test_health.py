"""Tests for subsystem health monitoring."""

import time
from unittest.mock import patch

from anima_mcp.health import HealthRegistry, SubsystemHealth, HEARTBEAT_STALE_SECONDS


class TestSubsystemHealth:
    """Tests for individual subsystem health tracking."""

    def test_heartbeat_updates_timestamp(self):
        sub = SubsystemHealth(name="test")
        assert sub.last_heartbeat == 0.0
        sub.heartbeat()
        assert sub.last_heartbeat > 0

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
