# Subsystem Health Monitoring

## Problem
Growth system was silently broken for weeks. Silent failures are the highest-risk class of bug in Lumen's architecture. Need visibility into subsystem health — both on the physical LCD and remotely via MCP.

## Design

### Health Registry (`src/anima_mcp/health.py`)
Singleton that tracks subsystem liveness and functional health.

**Two signals per subsystem:**
1. **Heartbeat** — subsystem calls `registry.heartbeat("name")` each loop iteration. Stale after 30s.
2. **Functional probe** — registry periodically calls a check function (~60s). Returns ok/failed with reason.

**Statuses:** `ok` | `stale` (heartbeat timeout) | `degraded` (probe failed) | `missing` (never registered)

### Subsystems

| Subsystem | Heartbeat source | Probe |
|-----------|-----------------|-------|
| sensors | sensor read | readings not None |
| display | render loop | display.is_available() |
| leds | LED update | leds.is_available() |
| growth | growth observation | _growth not None, DB queryable |
| governance | UNITARES check-in | last decision exists and recent |
| drawing | _lumen_draw / autonomy | canvas exists, not stalled |
| trajectory | trajectory record | _traj not None |
| voice | voice update | voice object exists |
| anima | anima computation | anima values non-None |

### LCD Health Screen
New `HEALTH` screen in joystick cycle. One row per subsystem, colored status dot (green/yellow/red).

### MCP Tool
`get_health` returns JSON with per-subsystem status, last heartbeat age, probe result, and overall status.

## Files
- **New:** `src/anima_mcp/health.py` (~150 lines)
- **Modify:** `server.py` — register subsystems, heartbeat calls, MCP tool
- **Modify:** `display/screens.py` — health screen renderer, add to cycle

## Out of Scope
- Alerting/notifications
- Auto-recovery
- Health history persistence
