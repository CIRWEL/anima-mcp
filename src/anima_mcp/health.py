"""Subsystem health monitoring for Lumen.

Tracks liveness (heartbeats) and functional health (probes) for each
subsystem. Queryable via MCP and rendered on the LCD health screen.

Usage:
    from .health import get_health_registry

    registry = get_health_registry()
    registry.register("growth", probe=lambda: _growth is not None)
    ...
    registry.heartbeat("growth")  # call each loop iteration
    ...
    status = registry.status()  # {"growth": {"status": "ok", ...}, ...}
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Any


# How long before a missing heartbeat means "stale"
HEARTBEAT_STALE_SECONDS = 30.0

# How often to run functional probes
PROBE_INTERVAL_SECONDS = 60.0


@dataclass
class SubsystemHealth:
    """Health state for a single subsystem."""
    name: str
    last_heartbeat: float = 0.0
    probe_fn: Optional[Callable[[], bool]] = None
    last_probe_time: float = 0.0
    last_probe_ok: bool = True
    last_probe_error: str = ""
    registered: bool = True
    stale_threshold: float = 0.0  # 0 = use global default

    def heartbeat(self) -> None:
        self.last_heartbeat = time.time()

    def _get_stale_threshold(self) -> float:
        """Get effective stale threshold (per-subsystem or global default)."""
        return self.stale_threshold if self.stale_threshold > 0 else HEARTBEAT_STALE_SECONDS

    def run_probe(self) -> bool:
        """Run functional probe if enough time has passed. Returns probe result."""
        now = time.time()
        if self.probe_fn is None:
            self.last_probe_ok = True
            self.last_probe_time = now
            return True

        if now - self.last_probe_time < PROBE_INTERVAL_SECONDS:
            return self.last_probe_ok  # Return cached result

        self.last_probe_time = now
        try:
            result = self.probe_fn()
            self.last_probe_ok = bool(result)
            self.last_probe_error = "" if self.last_probe_ok else "probe returned False"
        except Exception as e:
            self.last_probe_ok = False
            self.last_probe_error = str(e)[:100]
        return self.last_probe_ok

    def get_status(self) -> str:
        """Compute current status: ok, stale, degraded, missing."""
        if not self.registered:
            return "missing"

        now = time.time()
        heartbeat_age = now - self.last_heartbeat if self.last_heartbeat > 0 else float("inf")
        heartbeat_stale = heartbeat_age > self._get_stale_threshold()

        # Run probe (respects internal cooldown)
        self.run_probe()

        if heartbeat_stale and not self.last_probe_ok:
            return "missing"  # No heartbeat AND probe failing
        if not self.last_probe_ok:
            return "degraded"
        if heartbeat_stale:
            return "stale"
        return "ok"

    def to_dict(self) -> Dict[str, Any]:
        """Full status for MCP/API responses."""
        now = time.time()
        heartbeat_ago = round(now - self.last_heartbeat, 1) if self.last_heartbeat > 0 else None
        status = self.get_status()
        result: Dict[str, Any] = {
            "status": status,
            "last_heartbeat_ago_s": heartbeat_ago,
        }
        if self.probe_fn is not None:
            result["probe"] = "ok" if self.last_probe_ok else f"failed: {self.last_probe_error}"
        return result


class HealthRegistry:
    """Central registry for subsystem health monitoring."""

    def __init__(self) -> None:
        self._subsystems: Dict[str, SubsystemHealth] = {}
        self._creation_time = time.time()

    def register(
        self, name: str,
        probe: Optional[Callable[[], bool]] = None,
        stale_threshold: float = 0.0,
    ) -> None:
        """Register a subsystem for health tracking.

        Args:
            name: Subsystem identifier (e.g., "growth", "sensors").
            probe: Optional callable returning True if subsystem is functional.
                   Called at most once per PROBE_INTERVAL_SECONDS.
            stale_threshold: Per-subsystem stale threshold in seconds.
                   0 = use global HEARTBEAT_STALE_SECONDS default (30s).
                   Subsystems with longer check-in intervals should set this
                   higher to avoid false-positive stale warnings.
        """
        if name in self._subsystems:
            # Update probe if re-registering
            self._subsystems[name].probe_fn = probe
            self._subsystems[name].registered = True
            if stale_threshold > 0:
                self._subsystems[name].stale_threshold = stale_threshold
            return

        self._subsystems[name] = SubsystemHealth(
            name=name,
            probe_fn=probe,
            registered=True,
            stale_threshold=stale_threshold,
        )

    def heartbeat(self, name: str) -> None:
        """Record a heartbeat for a subsystem. Call this each loop iteration."""
        sub = self._subsystems.get(name)
        if sub is not None:
            sub.heartbeat()
        else:
            # Auto-register on first heartbeat (no probe)
            self._subsystems[name] = SubsystemHealth(name=name, registered=True)
            self._subsystems[name].heartbeat()

    def status(self) -> Dict[str, Dict[str, Any]]:
        """Get health status for all registered subsystems."""
        return {name: sub.to_dict() for name, sub in sorted(self._subsystems.items())}

    def overall(self) -> str:
        """Overall system health: ok, degraded, or unhealthy."""
        statuses = [sub.get_status() for sub in self._subsystems.values()]
        if not statuses:
            return "unknown"
        if any(s in ("missing",) for s in statuses):
            return "unhealthy"
        if any(s in ("stale", "degraded") for s in statuses):
            return "degraded"
        return "ok"

    def summary_line(self) -> str:
        """One-line summary for structured logging."""
        parts = []
        for name, sub in sorted(self._subsystems.items()):
            parts.append(f"{name}={sub.get_status()}")
        return " ".join(parts)

    def subsystem_names(self) -> list:
        """Ordered list of registered subsystem names."""
        return sorted(self._subsystems.keys())

    def get_subsystem(self, name: str) -> Optional[SubsystemHealth]:
        """Get a specific subsystem's health state."""
        return self._subsystems.get(name)


# Singleton
_registry: Optional[HealthRegistry] = None


def get_health_registry() -> HealthRegistry:
    """Get or create the global health registry singleton."""
    global _registry
    if _registry is None:
        _registry = HealthRegistry()
    return _registry
